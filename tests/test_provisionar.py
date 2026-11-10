"""Testes unitários do provisionamento (sem acesso ao GNS3)."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from infra import provisionar

RAIZ = Path(__file__).resolve().parents[1]
PLANO = json.loads((RAIZ / "infra" / "config" / "plano_rede.json").read_text())


class FakeRelogio:
    """Substitui o módulo 'time' dentro de provisionar (relógio discreto)."""

    def __init__(self) -> None:
        self.agora = 1000.0

    def monotonic(self) -> float:
        return self.agora

    def sleep(self, segundos: float) -> None:
        self.agora += segundos


class ConexaoVpcsFake:
    """Console VPCS simulado: 'show ip' scriptado e comandos registrados."""

    def __init__(self, respostas_show_ip: list[str]) -> None:
        self.respostas = list(respostas_show_ip)
        self.comandos_enviados: list[str] = []

    def send_command(self, comando: str, read_timeout: int = 60) -> str:
        if comando != "show ip":
            return ""
        if self.respostas:
            self.ultima = self.respostas.pop(0)
        return self.ultima

    def send_command_timing(self, comando: str, **kwargs) -> str:
        self.comandos_enviados.append(comando)
        return ""


class PlanoTest(unittest.TestCase):
    def test_plano_real_e_valido(self) -> None:
        vlans, redes, switches = provisionar.validar_plano(PLANO)
        self.assertEqual(vlans["Cameras"], 60)
        self.assertIsNone(redes["Cameras"]["gateway"])
        self.assertFalse(redes["Cameras"]["dhcp"])
        self.assertEqual(switches["SW-LACINA"]["papel"], "core")

    def test_rejeita_cameras_com_gateway(self) -> None:
        plano = copy.deepcopy(PLANO)
        plano["redes"]["Cameras"]["gateway"] = "172.20.2.129"
        plano["redes"]["Cameras"]["dhcp"] = True
        with self.assertRaises(provisionar.PlanoInvalidoError):
            provisionar.validar_plano(plano)

    def test_rejeita_id_de_vlan_fora_da_norma(self) -> None:
        plano = copy.deepcopy(PLANO)
        plano["vlans"][0]["id"] = 11
        with self.assertRaises(provisionar.PlanoInvalidoError):
            provisionar.validar_plano(plano)

    def test_rejeita_host_fora_do_mapa_l1(self) -> None:
        plano = copy.deepcopy(PLANO)
        plano["hosts"]["PC-LACINA"]["porta"] = 9
        with self.assertRaises(provisionar.PlanoInvalidoError):
            provisionar.validar_plano(plano)


class RenderizacaoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ambiente = provisionar.criar_ambiente(
            RAIZ / "infra" / "templates"
        )

    def _render_switch(self, nome: str) -> list[str]:
        contexto, _, _ = provisionar.montar_contexto_switch(PLANO, nome, None)
        return provisionar.renderizar_switch(self.ambiente, contexto)

    def test_core_cria_vlans_svis_e_dhcp(self) -> None:
        comandos = self._render_switch("SW-LACINA")
        self.assertIn("create vlan Cameras tag 60", comandos)
        self.assertIn("configure vlan LACINA ipaddress 172.20.1.1/25", comandos)
        self.assertIn("enable ipforwarding vlan LACINA", comandos)
        self.assertIn("enable dhcp ports 1,22-24 vlan LACINA", comandos)
        self.assertIn("enable dhcp ports 2,22-24 vlan WiFi", comandos)
        self.assertIn("save configuration", comandos)
        self.assertFalse(
            any("Cameras" in cmd and "ipaddress" in cmd for cmd in comandos)
        )
        self.assertFalse(
            any("Cameras" in cmd and "ipforwarding" in cmd for cmd in comandos)
        )
        self.assertFalse(any("iproute add default" in cmd for cmd in comandos))

    def test_acesso_tem_ip_de_gerencia_e_rota_padrao(self) -> None:
        comandos = self._render_switch("SW-LSD")
        self.assertIn(
            "configure vlan Gerencia ipaddress 172.20.2.162/28", comandos
        )
        self.assertIn("configure iproute add default 172.20.2.161", comandos)
        self.assertFalse(any("dhcp-address-range" in cmd for cmd in comandos))

    def test_host_estatico_renderiza_duas_linhas(self) -> None:
        host = PLANO["hosts"]["NVR"]
        comandos = provisionar.renderizar_host(self.ambiente, host)
        self.assertEqual(comandos, ["ip 172.20.2.129/27", "save"])

        host = PLANO["hosts"]["ADM"]
        comandos = provisionar.renderizar_host(self.ambiente, host)
        self.assertEqual(
            comandos, ["ip 172.20.2.165/28 172.20.2.161", "save"]
        )

    def test_host_dhcp_renderiza_ip_dhcp(self) -> None:
        comandos = provisionar.renderizar_host(
            self.ambiente, PLANO["hosts"]["PC-LACINA"]
        )
        self.assertEqual(comandos, ["ip dhcp", "save"])


class ReadBeforeWriteTest(unittest.TestCase):
    def test_portas_ja_corretas_nao_geram_comandos(self) -> None:
        acesso = provisionar.portas_acesso(PLANO, "SW-LACINA")
        troncos = provisionar.troncos_normalizados(PLANO, "SW-LACINA")
        estado = {
            "untagged_por_porta": {1: "LACINA", 2: "WiFi", 3: "Gerencia"},
            "tagged_por_porta": {
                22: {"LSD", "LACINA", "LSI", "LIAD", "WiFi", "Cameras", "Gerencia"},
                23: {"LSD", "LACINA", "LSI", "LIAD", "WiFi", "Cameras", "Gerencia"},
                24: {"LSD", "LACINA", "LSI", "LIAD", "WiFi", "Cameras", "Gerencia"},
            },
        }
        self.assertEqual(
            provisionar.calcular_comandos_portas(acesso, troncos, estado), []
        )

    def test_porta_na_default_e_movida(self) -> None:
        acesso = [{"porta": 1, "vlan": "LACINA"}]
        comandos = provisionar.calcular_comandos_portas(
            acesso, [], {"untagged_por_porta": {1: "Default"}}
        )
        self.assertEqual(
            comandos,
            [
                "configure vlan Default delete ports 1",
                "configure vlan LACINA add ports 1 untagged",
            ],
        )

    def test_comprimir_portas(self) -> None:
        self.assertEqual(provisionar.comprimir_portas([1, 22, 23, 24]), "1,22-24")
        self.assertEqual(provisionar.comprimir_portas({22, 23, 24}), "22-24")
        self.assertEqual(provisionar.comprimir_portas([5]), "5")

    def test_escopos_dhcp_do_core(self) -> None:
        troncos = provisionar.troncos_normalizados(PLANO, "SW-LACINA")
        acesso = provisionar.portas_acesso(PLANO, "SW-LACINA")
        escopos = {
            escopo["nome"]: escopo
            for escopo in provisionar.montar_escopos_dhcp(
                PLANO, troncos, acesso
            )
        }
        self.assertEqual(escopos["LACINA"]["inicio"], "172.20.1.2")
        self.assertEqual(escopos["LACINA"]["fim"], "172.20.1.126")
        self.assertEqual(escopos["LACINA"]["portas"], "1,22-24")
        self.assertEqual(escopos["LSD"]["inicio"], "172.20.1.130")
        self.assertEqual(escopos["LSI"]["fim"], "172.20.2.62")
        self.assertEqual(escopos["LIAD"]["inicio"], "172.20.2.66")
        self.assertEqual(escopos["WiFi"]["portas"], "2,22-24")
        self.assertNotIn("Cameras", escopos)
        self.assertNotIn("Gerencia", escopos)


class AguardarDhcpTest(unittest.TestCase):
    """Espera do DHCP com reenvio periódico de 'ip dhcp' e relógio falso."""

    def setUp(self) -> None:
        self.relogio = FakeRelogio()
        patcher = mock.patch("infra.provisionar.time", self.relogio)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _sem_ip(self) -> str:
        return "IP/MASK     : 0.0.0.0/0\nGATEWAY     : 0.0.0.0\n"

    def _com_ip(self) -> str:
        return "IP/MASK     : 172.20.2.10/26\nGATEWAY     : 172.20.2.1\n"

    def test_obtem_ip_sem_reenvio(self) -> None:
        conn = ConexaoVpcsFake([self._sem_ip(), self._com_ip()])
        ip, gateway = provisionar.aguardar_dhcp(conn)
        self.assertEqual(ip, "172.20.2.10/26")
        self.assertEqual(gateway, "172.20.2.1")
        self.assertEqual(conn.comandos_enviados, [])

    def test_reenvia_ip_dhcp_enquanto_espera(self) -> None:
        # 12 leituras sem IP (t=0,2,...,20) e resposta válida em t=22:
        # 'ip dhcp' deve ser reenviado em t=10 e t=20.
        conn = ConexaoVpcsFake([self._sem_ip()] * 11 + [self._com_ip()])
        ip, gateway = provisionar.aguardar_dhcp(conn)
        self.assertEqual(ip, "172.20.2.10/26")
        self.assertEqual(conn.comandos_enviados, ["ip dhcp", "ip dhcp"])

    def test_estoura_timeout_reenviando(self) -> None:
        conn = ConexaoVpcsFake([self._sem_ip()])
        with self.assertRaises(provisionar.ValidacaoError) as contexto:
            provisionar.aguardar_dhcp(conn, timeout=30)
        self.assertIn("30s", str(contexto.exception))
        self.assertIn("0.0.0.0/0", str(contexto.exception))
        self.assertEqual(conn.comandos_enviados, ["ip dhcp", "ip dhcp"])


if __name__ == "__main__":
    unittest.main()
