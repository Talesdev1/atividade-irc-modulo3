"""Testes unitários dos testes de aceite (sem acesso ao GNS3)."""

from __future__ import annotations

import argparse
import contextlib
import io
import ipaddress
import json
import unittest
from pathlib import Path
from unittest import mock

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


class SessoesFake:
    """Sessões de console simuladas: registra comandos e pings.

    ``vpcs()`` devolve o próprio nome do host como token, o que permite aos
    stubs de ``aguardar_dhcp``/``ler_ip_vpcs`` saber de qual host se trata.
    """

    def __init__(self, resposta_ping: testes_aceite.RespostaPing | None = None):
        self.comandos: list[tuple[str, str]] = []
        self.resposta_ping = resposta_ping or testes_aceite.RespostaPing(
            True, "resposta ICMP recebida"
        )

    def vpcs(self, nome: str) -> str:
        return nome

    def comando(self, nome: str, comando: str, read_timeout: int = 120) -> str:
        self.comandos.append((nome, comando))
        return ""

    def ping(self, nome: str, destino: str) -> testes_aceite.RespostaPing:
        self.comandos.append((nome, f"ping {destino}"))
        return self.resposta_ping


def _args_sessoes(**extra) -> argparse.Namespace:
    return _args(
        dhcp_timeout=90,
        ping_timeout=120,
        contagem=3,
        verbose=False,
        **extra,
    )


def _ip_da_vlan(plano: dict, vlan: str) -> str:
    rede = ipaddress.ip_network(plano["redes"][vlan]["rede"])
    return f"{rede.network_address + 10}/{rede.prefixlen}"


class Teste1DhcpTest(unittest.TestCase):
    """Falha de DHCP em um host não pode abortar os demais hosts."""

    def _executar(self, sem_ip: set[str]) -> tuple[testes_aceite.Resultado, SessoesFake]:
        sessoes = SessoesFake()
        ctx = testes_aceite.Contexto(PLANO, sessoes, _args_sessoes())
        self._ctx = ctx

        def aguardar_stub(conn, timeout=45):
            nome = conn
            vlan = PLANO["hosts"][nome]["vlan"]
            if nome in sem_ip:
                raise RuntimeError(
                    f"host não obteve IP via DHCP em {timeout}s "
                    "(show ip: '0.0.0.0/0')"
                )
            gateway = str(PLANO["redes"][vlan]["gateway"])
            return _ip_da_vlan(PLANO, vlan), gateway

        with (
            mock.patch.object(testes_aceite, "aguardar_dhcp", aguardar_stub),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            resultado = testes_aceite.teste_1_dhcp(ctx)
        return resultado, sessoes

    def test_falha_em_um_host_nao_interrompe_os_demais(self) -> None:
        resultado, sessoes = self._executar({"PC-LSD"})
        self.assertFalse(resultado.ok)
        self.assertTrue(
            any("PC-LSD não obteve IP" in falha for falha in resultado.falhas)
        )
        # Todos os hosts dinâmicos foram tentados, mesmo após a falha.
        dhcp_hosts = [
            nome
            for nome, host in PLANO["hosts"].items()
            if host["modo"] == "dhcp"
        ]
        disparados = [nome for nome, cmd in sessoes.comandos if cmd == "ip dhcp"]
        self.assertEqual(sorted(disparados), sorted(dhcp_hosts))
        # Hosts que obtiveram IP seguem registrados no contexto.
        self.assertIn("PC-LACINA", self._ctx.ips)
        self.assertNotIn("PC-LSD", self._ctx.ips)

    def test_todos_com_ip_aprovam_o_teste(self) -> None:
        resultado, _ = self._executar(set())
        self.assertTrue(resultado.ok)
        self.assertEqual(resultado.falhas, [])


class Teste2GatewayTest(unittest.TestCase):
    """Sem IP válido o Teste 2 registra causa clara em vez de ping cego."""

    def _executar(self, sem_ip: set[str]) -> tuple[testes_aceite.Resultado, SessoesFake]:
        sessoes = SessoesFake()
        ctx = testes_aceite.Contexto(PLANO, sessoes, _args_sessoes())

        def ler_stub(conn):
            nome = conn
            vlan = PLANO["hosts"][nome]["vlan"]
            if nome in sem_ip:
                return "0.0.0.0/0", None
            return _ip_da_vlan(PLANO, vlan), str(PLANO["redes"][vlan]["gateway"])

        def aguardar_stub(conn, timeout=45):
            raise RuntimeError(
                f"host não obteve IP via DHCP em {timeout}s (show ip: '0.0.0.0/0')"
            )

        with (
            mock.patch.object(testes_aceite, "ler_ip_vpcs", ler_stub),
            mock.patch.object(testes_aceite, "aguardar_dhcp", aguardar_stub),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            resultado = testes_aceite.teste_2_gateway(ctx)
        return resultado, sessoes

    def test_host_sem_ip_registra_falha_clara_e_nao_pinge(self) -> None:
        resultado, sessoes = self._executar({"PC-LSI"})
        self.assertFalse(resultado.ok)
        self.assertTrue(
            any("PC-LSI sem IP válido" in falha for falha in resultado.falhas)
        )
        # O host sem IP não gerou ping inconclusivo; os demais foram pingados.
        pings = [nome for nome, cmd in sessoes.comandos if cmd.startswith("ping")]
        self.assertNotIn("PC-LSI", pings)
        com_gateway = [
            nome
            for nome, host in PLANO["hosts"].items()
            if testes_aceite.gateway_esperado(PLANO, host)
        ]
        self.assertEqual(
            sorted(pings), sorted(n for n in com_gateway if n != "PC-LSI")
        )

    def test_hosts_com_ip_pingam_o_gateway(self) -> None:
        resultado, sessoes = self._executar(set())
        self.assertTrue(resultado.ok)
        com_gateway = [
            nome
            for nome, host in PLANO["hosts"].items()
            if testes_aceite.gateway_esperado(PLANO, host)
        ]
        pings = [nome for nome, cmd in sessoes.comandos if cmd.startswith("ping")]
        self.assertEqual(sorted(pings), sorted(com_gateway))


if __name__ == "__main__":
    unittest.main()
