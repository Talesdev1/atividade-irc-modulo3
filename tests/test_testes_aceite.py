"""Testes unitários dos testes de aceite (sem acesso ao GNS3)."""

from __future__ import annotations

import argparse
import ipaddress
import json
import unittest
from pathlib import Path

from infra import testes_aceite

RAIZ = Path(__file__).resolve().parents[1]
PLANO = json.loads((RAIZ / "infra" / "config" / "plano_rede.json").read_text())


def _args(**extra) -> argparse.Namespace:
    base = {"only": None, "ip_teste6": testes_aceite.IP_TESTE6}
    base.update(extra)
    return argparse.Namespace(**base)


class PingTest(unittest.TestCase):
    def test_resposta_de_sucesso(self) -> None:
        saida = (
            "ping 172.20.1.1 -c 3\n\n"
            "84 bytes from 172.20.1.1 icmp_seq=1 ttl=64 time=1.727 ms\n"
            "84 bytes from 172.20.1.1 icmp_seq=2 ttl=64 time=2.027 ms\n"
        )
        resposta = testes_aceite.interpretar_ping("172.20.1.1", saida)
        self.assertTrue(resposta.respondeu)
        self.assertIn("ICMP", resposta.motivo)

    def test_isolamento_com_icmp_unreachable(self) -> None:
        saida = (
            "ping 172.20.2.130 -c 3\n\n"
            "*172.20.1.1 icmp_seq=1 ttl=64 time=0.504 ms "
            "(ICMP type:3, code:1, Destination host unreachable)\n"
        )
        resposta = testes_aceite.interpretar_ping("172.20.2.130", saida)
        self.assertFalse(resposta.respondeu)
        self.assertIn("unreachable", resposta.motivo.lower())

    def test_timeout(self) -> None:
        saida = "ping 172.20.2.130 -c 3\n\n172.20.2.130 icmp_seq=1 timeout\n"
        resposta = testes_aceite.interpretar_ping("172.20.2.130", saida)
        self.assertFalse(resposta.respondeu)
        self.assertIn("timeout", resposta.motivo.lower())

    def test_host_not_reachable(self) -> None:
        saida = "ping 172.20.1.129 -c 3\n\nhost (172.20.1.129) not reachable\n"
        resposta = testes_aceite.interpretar_ping("172.20.1.129", saida)
        self.assertFalse(resposta.respondeu)
        self.assertIn("reachable", resposta.motivo.lower())

    def test_saida_sem_marcador_e_inconclusiva(self) -> None:
        resposta = testes_aceite.interpretar_ping("172.20.2.130", "VPCS>")
        self.assertFalse(resposta.respondeu)
        self.assertIn("conclusiva", resposta.motivo)

    def test_sucesso_de_outro_ip_nao_conta(self) -> None:
        saida = "84 bytes from 172.20.1.1 icmp_seq=1 ttl=64 time=1.0 ms\n"
        resposta = testes_aceite.interpretar_ping("172.20.2.130", saida)
        self.assertFalse(resposta.respondeu)


class SelecaoTest(unittest.TestCase):
    def test_padrao_executa_todos(self) -> None:
        self.assertEqual(testes_aceite.selecionar_testes(_args()), [1, 2, 3, 4, 5, 6])

    def test_selecao_parcial_e_ordenada(self) -> None:
        self.assertEqual(
            testes_aceite.selecionar_testes(_args(only="6, 1 ,3")), [1, 3, 6]
        )

    def test_rejeita_teste_inexistente(self) -> None:
        with self.assertRaises(testes_aceite.SelecaoInvalidaError):
            testes_aceite.selecionar_testes(_args(only="7"))

    def test_rejeita_valor_nao_numerico(self) -> None:
        with self.assertRaises(testes_aceite.SelecaoInvalidaError):
            testes_aceite.selecionar_testes(_args(only="dhcp"))


class GatewayTest(unittest.TestCase):
    def test_host_dhcp_usa_gateway_da_vlan(self) -> None:
        self.assertEqual(
            testes_aceite.gateway_esperado(
                PLANO, PLANO["hosts"]["PC-LACINA"]
            ),
            "172.20.1.1",
        )

    def test_host_estatico_sem_gateway(self) -> None:
        self.assertIsNone(
            testes_aceite.gateway_esperado(PLANO, PLANO["hosts"]["CAM"])
        )

    def test_host_estatico_com_gateway(self) -> None:
        self.assertEqual(
            testes_aceite.gateway_esperado(PLANO, PLANO["hosts"]["ADM"]),
            "172.20.2.161",
        )


class HostsNecessariosTest(unittest.TestCase):
    def test_teste_cftv_precisa_apenas_cam_e_nvr(self) -> None:
        self.assertEqual(
            testes_aceite.hosts_necessarios([4], PLANO), ["CAM", "NVR"]
        )

    def test_teste_isolamento_inclui_origens_e_alvos(self) -> None:
        necessarios = testes_aceite.hosts_necessarios([5], PLANO)
        self.assertEqual(
            necessarios, ["CAM", "NVR", "PC-LACINA", "PC-LSD"]
        )

    def test_teste_gateway_ignora_hosts_sem_gateway(self) -> None:
        necessarios = testes_aceite.hosts_necessarios([2], PLANO)
        self.assertIn("ADM", necessarios)
        self.assertIn("WIFI-1", necessarios)
        self.assertNotIn("CAM", necessarios)
        self.assertNotIn("NVR", necessarios)

    def test_teste6_precisa_do_pc_lacina(self) -> None:
        self.assertEqual(
            testes_aceite.hosts_necessarios([6], PLANO), ["PC-LACINA"]
        )


class MalhaTest(unittest.TestCase):
    def test_hosts_comunicaveis_inclui_estaticos_roteados(self) -> None:
        self.assertEqual(
            testes_aceite.hosts_comunicaveis(PLANO),
            [
                "PC-LACINA",
                "WIFI-1",
                "ADM",
                "PC-LSD",
                "PC-LSI",
                "PC-LIAD-SALA",
                "PC-LIAD",
                "WIFI-2",
            ],
        )

    def test_hosts_comunicaveis_exclui_cftv(self) -> None:
        comunicaveis = testes_aceite.hosts_comunicaveis(PLANO)
        self.assertNotIn("CAM", comunicaveis)
        self.assertNotIn("NVR", comunicaveis)

    def test_malha_cobre_todos_os_pares_sem_repetir(self) -> None:
        pares = testes_aceite.pares_completos(PLANO)
        hosts = testes_aceite.hosts_comunicaveis(PLANO)
        self.assertEqual(len(pares), len(hosts) * (len(hosts) - 1) // 2)
        self.assertEqual(len(set(pares)), len(pares))
        for origem, destino in pares:
            self.assertNotEqual(origem, destino)
            self.assertNotIn((destino, origem), pares)

    def test_malha_inclui_par_intra_vlan_entre_switches(self) -> None:
        pares = testes_aceite.pares_completos(PLANO)
        self.assertIn(("PC-LIAD-SALA", "PC-LIAD"), pares)

    def test_pares_inter_vlan_e_subconjunto_da_malha(self) -> None:
        malha = set(testes_aceite.pares_completos(PLANO))
        inter = testes_aceite.pares_inter_vlan(PLANO)
        self.assertTrue(inter)
        self.assertTrue(set(inter).issubset(malha))
        for origem, destino in inter:
            self.assertNotEqual(
                PLANO["hosts"][origem]["vlan"], PLANO["hosts"][destino]["vlan"]
            )

    def test_teste3_exige_todos_os_hosts_da_malha(self) -> None:
        self.assertEqual(
            testes_aceite.hosts_necessarios([3], PLANO),
            sorted(testes_aceite.hosts_comunicaveis(PLANO)),
        )


class Teste6Test(unittest.TestCase):
    def test_ip_temporario_pertence_a_outra_sub_rede(self) -> None:
        temporario = ipaddress.ip_interface(testes_aceite.IP_TESTE6)
        lsd = ipaddress.ip_network(PLANO["redes"]["LSD"]["rede"])
        lacina = ipaddress.ip_network(PLANO["redes"]["LACINA"]["rede"])
        self.assertEqual(temporario.network, lsd)
        self.assertNotEqual(temporario.network, lacina)

    def test_gateway_do_lsd_esta_na_sub_rede_temporaria(self) -> None:
        temporario = ipaddress.ip_interface(testes_aceite.IP_TESTE6)
        gateway = ipaddress.ip_address(PLANO["redes"]["LSD"]["gateway"])
        self.assertIn(gateway, temporario.network)


if __name__ == "__main__":
    unittest.main()
