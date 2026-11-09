"""Testes unitários da gestão de mudanças (sem acesso ao GNS3)."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from infra import mudancas

RAIZ = Path(__file__).resolve().parents[1]
PLANO = json.loads((RAIZ / "infra" / "config" / "plano_rede.json").read_text())
MUDANCAS = json.loads(
    (RAIZ / "infra" / "config" / "plano_mudancas.json").read_text()
)


class PlanoMudancasTest(unittest.TestCase):
    def test_plano_real_e_valido(self) -> None:
        mudancas.validar_plano_mudancas(MUDANCAS, PLANO)

    def test_rejeita_chamado_ausente(self) -> None:
        plano = copy.deepcopy(MUDANCAS)
        del plano["chamado2"]
        with self.assertRaises(mudancas.MudancaInvalidaError):
            mudancas.validar_plano_mudancas(plano, PLANO)

    def test_rejeita_host_que_ja_existe(self) -> None:
        plano = copy.deepcopy(MUDANCAS)
        plano["chamado1"]["host"]["nome"] = "PC-LIAD"
        with self.assertRaises(mudancas.MudancaInvalidaError):
            mudancas.validar_plano_mudancas(plano, PLANO)

    def test_rejeita_porta_do_chamado1_em_uso(self) -> None:
        plano = copy.deepcopy(MUDANCAS)
        plano["chamado1"]["host"]["porta"] = 24
        with self.assertRaises(mudancas.MudancaInvalidaError):
            mudancas.validar_plano_mudancas(plano, PLANO)

    def test_rejeita_vlan_inexistente_no_chamado1(self) -> None:
        plano = copy.deepcopy(MUDANCAS)
        plano["chamado1"]["host"]["vlan"] = "Inexistente"
        with self.assertRaises(mudancas.MudancaInvalidaError):
            mudancas.validar_plano_mudancas(plano, PLANO)

    def test_rejeita_enlace_rompido_fora_do_mapa(self) -> None:
        plano = copy.deepcopy(MUDANCAS)
        plano["chamado2"]["enlace_rompido"]["porta_a"] = 21
        with self.assertRaises(mudancas.MudancaInvalidaError):
            mudancas.validar_plano_mudancas(plano, PLANO)

    def test_rejeita_novo_tronco_que_ja_existe(self) -> None:
        plano = copy.deepcopy(MUDANCAS)
        plano["chamado2"]["novo_tronco"] = {
            "no_a": "SW-LACINA",
            "porta_a": 23,
            "no_b": "SW-LSI",
            "porta_b": 23,
        }
        with self.assertRaises(mudancas.MudancaInvalidaError):
            mudancas.validar_plano_mudancas(plano, PLANO)

    def test_rejeita_porta_de_tronco_em_uso(self) -> None:
        plano = copy.deepcopy(MUDANCAS)
        plano["chamado2"]["novo_tronco"]["porta_a"] = 23
        with self.assertRaises(mudancas.MudancaInvalidaError):
            mudancas.validar_plano_mudancas(plano, PLANO)

    def test_rejeita_host_do_chamado3_fora_do_lugar(self) -> None:
        plano = copy.deepcopy(MUDANCAS)
        plano["chamado3"]["porta"] = 1
        with self.assertRaises(mudancas.MudancaInvalidaError):
            mudancas.validar_plano_mudancas(plano, PLANO)

    def test_rejeita_vlan_de_origem_divergente(self) -> None:
        plano = copy.deepcopy(MUDANCAS)
        plano["chamado3"]["vlan_origem"] = "LSI"
        with self.assertRaises(mudancas.MudancaInvalidaError):
            mudancas.validar_plano_mudancas(plano, PLANO)


class ComandosTest(unittest.TestCase):
    def test_acesso_migra_porta_entre_vlans(self) -> None:
        estado = {
            "untagged_por_porta": {4: "Default"},
            "tagged_por_porta": {},
        }
        comandos = mudancas.comandos_acesso(estado, 4, "LACINA")
        self.assertEqual(
            comandos,
            [
                "configure vlan Default delete ports 4",
                "configure vlan LACINA add ports 4 untagged",
            ],
        )

    def test_acesso_idempotente(self) -> None:
        estado = {
            "untagged_por_porta": {4: "LACINA"},
            "tagged_por_porta": {},
        }
        self.assertEqual(mudancas.comandos_acesso(estado, 4, "LACINA"), [])

    def test_acesso_remove_tag_residual(self) -> None:
        estado = {
            "untagged_por_porta": {4: "LACINA"},
            "tagged_por_porta": {4: {"LSI"}},
        }
        self.assertEqual(
            mudancas.comandos_acesso(estado, 4, "LACINA"),
            ["configure vlan LSI delete ports 4"],
        )

    def test_tronco_remove_untagged_e_adiciona_tags(self) -> None:
        estado = {
            "untagged_por_porta": {22: "Default"},
            "tagged_por_porta": {22: {"LSD"}},
        }
        comandos = mudancas.comandos_tronco(estado, 22, ["LSD", "LACINA"])
        self.assertEqual(
            comandos,
            [
                "configure vlan Default delete ports 22",
                "configure vlan LACINA add ports 22 tagged",
            ],
        )

    def test_tronco_idempotente(self) -> None:
        estado = {
            "untagged_por_porta": {},
            "tagged_por_porta": {22: {"LSD", "LACINA"}},
        }
        self.assertEqual(mudancas.comandos_tronco(estado, 22, ["LSD", "LACINA"]), [])

    def test_tronco_ignora_vlan_inexistente_no_switch(self) -> None:
        estado = {
            "ids": {"LSI": 30},
            "untagged_por_porta": {},
            "tagged_por_porta": {22: {"LSI"}},
        }
        self.assertEqual(
            mudancas.comandos_tronco(estado, 22, ["LSI", "LIAD"]), []
        )

    def test_remover_vlan_limpa_portas_e_apaga(self) -> None:
        estado = {
            "ids": {"LIAD": 40},
            "untagged_por_porta": {2: "LIAD"},
            "tagged_por_porta": {22: {"LIAD", "LSI"}},
        }
        self.assertEqual(
            mudancas.comandos_remover_vlan(estado, "LIAD"),
            [
                "configure vlan LIAD delete ports 2,22",
                "delete vlan LIAD",
            ],
        )

    def test_remover_vlan_sem_portas(self) -> None:
        estado = {"ids": {"LIAD": 40}, "untagged_por_porta": {}, "tagged_por_porta": {}}
        self.assertEqual(
            mudancas.comandos_remover_vlan(estado, "LIAD"), ["delete vlan LIAD"]
        )

    def test_remover_vlan_ausente_e_idempotente(self) -> None:
        estado = {"ids": {}, "untagged_por_porta": {}, "tagged_por_porta": {}}
        self.assertEqual(mudancas.comandos_remover_vlan(estado, "LIAD"), [])

    def test_desabilitar_porta(self) -> None:
        self.assertEqual(
            mudancas.comandos_desabilitar_porta(24), ["disable port 24"]
        )


class VerificacoesTest(unittest.TestCase):
    def test_erros_acesso(self) -> None:
        estado = {"untagged_por_porta": {4: "Default"}}
        self.assertTrue(mudancas.erros_acesso(estado, 4, "LACINA"))
        estado = {"untagged_por_porta": {4: "LACINA"}}
        self.assertEqual(mudancas.erros_acesso(estado, 4, "LACINA"), [])

    def test_erros_tronco_com_untagged(self) -> None:
        estado = {
            "ids": {"LSI": 30},
            "untagged_por_porta": {22: "Default"},
            "tagged_por_porta": {22: {"LSI"}},
        }
        erros = mudancas.erros_tronco(estado, 22, ["LSI"])
        self.assertEqual(len(erros), 1)
        self.assertIn("untagged", erros[0])

    def test_erros_tronco_com_vlan_faltando(self) -> None:
        estado = {
            "ids": {"LSI": 30, "LIAD": 40},
            "untagged_por_porta": {},
            "tagged_por_porta": {22: {"LSI"}},
        }
        erros = mudancas.erros_tronco(estado, 22, ["LSI", "LIAD"])
        self.assertEqual(len(erros), 1)
        self.assertIn("LIAD", erros[0])

    def test_erros_tronco_ignora_vlan_ja_removida_do_switch(self) -> None:
        estado = {
            "ids": {"LSI": 30},
            "untagged_por_porta": {},
            "tagged_por_porta": {22: {"LSI"}},
        }
        self.assertEqual(mudancas.erros_tronco(estado, 22, ["LSI", "LIAD"]), [])

    def test_erros_vlan_ausente(self) -> None:
        self.assertTrue(mudancas.erros_vlan_ausente({"ids": {"LIAD": 40}}, "LIAD"))
        self.assertEqual(mudancas.erros_vlan_ausente({"ids": {}}, "LIAD"), [])


class AdminPortaTest(unittest.TestCase):
    class _FakeConn:
        def __init__(self, saida: str) -> None:
            self.saida = saida

        def send_command_timing(self, *args, **kwargs) -> str:
            return self.saida

    def test_porta_habilitada(self) -> None:
        conn = self._FakeConn("Admin state:\tEnabled with auto-speed sensing")
        self.assertTrue(mudancas.ler_admin_porta(conn, 24))

    def test_porta_desabilitada(self) -> None:
        conn = self._FakeConn("Admin state:\tDisabled")
        self.assertFalse(mudancas.ler_admin_porta(conn, 24))

    def test_saida_invalida(self) -> None:
        conn = self._FakeConn("sem informacao")
        with self.assertRaises(mudancas.ValidacaoMudancaError):
            mudancas.ler_admin_porta(conn, 24)


class TopologiaTest(unittest.TestCase):
    def test_nome_porta(self) -> None:
        self.assertEqual(mudancas._nome_porta(22), "Port22")
        self.assertEqual(mudancas._nome_porta("Ethernet0"), "Ethernet0")

    def test_enlace_do_mapa(self) -> None:
        self.assertTrue(mudancas._enlace_do_mapa("SW-LACINA", 24, "SW-LIAD", 24))
        self.assertTrue(mudancas._enlace_do_mapa("SW-LIAD", 24, "SW-LACINA", 24))
        self.assertFalse(mudancas._enlace_do_mapa("SW-LSI", 22, "SW-LIAD", 22))


if __name__ == "__main__":
    unittest.main()
