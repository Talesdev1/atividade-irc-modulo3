#!/usr/bin/env python3
"""Provisiona VLANs, L3, DHCP e hosts do laboratório via Netmiko + Jinja2.

Consome o inventário dinâmico gerado pelo Milestone 2 (``inventario_gns3.json``)
e o plano declarativo em ``infra/config/plano_rede.json``. Para cada switch EXOS
o script:

1. faz o *readiness check* (polling até o EXOS responder ``show version``);
2. lê o estado atual (``show vlan``) antes de escrever (ADR 003);
3. renderiza os templates Jinja2 de ``infra/templates``;
4. aplica as diferenças e valida o resultado (``show vlan``/``show ipconfig``/
   ``show iproute``);
5. configura os VPCS (IP fixo ou DHCP) e valida com ``show ip``.

Nenhuma porta de console é hardcoded: tudo vem do inventário.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from netmiko import ConnectHandler

try:  # import relativo quando chamado como pacote
    from .topologia import ENLACES_INICIAIS
except ImportError:  # execução direta: python infra/provisionar.py
    from topologia import ENLACES_INICIAIS  # type: ignore[no-redef]

RAIZ = Path(__file__).resolve().parents[1]
INVENTARIO_PADRAO = RAIZ / "inventario_gns3.json"
PLANO_PADRAO = RAIZ / "infra" / "config" / "plano_rede.json"
TEMPLATES_PADRAO = RAIZ / "infra" / "templates"

NOME_VLAN = re.compile(r"^[A-Za-z0-9_]+$")


class PlanoInvalidoError(ValueError):
    """O plano de rede viola as normas do STI ou está inconsistente."""


class ProntidaoError(RuntimeError):
    """O nó não ficou pronto para receber comandos dentro do timeout."""


class ValidacaoError(RuntimeError):
    """O estado do equipamento divergiu do plano após o provisionamento."""


@dataclass(frozen=True)
class Credenciais:
    username: str
    password: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventario",
        type=Path,
        default=INVENTARIO_PADRAO,
        help="Inventário de consoles gerado pelo Milestone 2",
    )
    parser.add_argument(
        "--plano",
        type=Path,
        default=PLANO_PADRAO,
        help="Plano de rede declarativo (padrão: infra/config/plano_rede.json)",
    )
    parser.add_argument(
        "--templates",
        type=Path,
        default=TEMPLATES_PADRAO,
        help="Diretório de templates Jinja2",
    )
    parser.add_argument(
        "--only",
        help="Lista separada por vírgulas de nós a processar (switches e/ou VPCS)",
    )
    parser.add_argument(
        "--skip-switches",
        action="store_true",
        help="Não configura os switches EXOS",
    )
    parser.add_argument(
        "--skip-hosts",
        action="store_true",
        help="Não configura os VPCS",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Apenas valida o estado atual, sem alterar configurações",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Renderiza as configurações e imprime, sem conectar ao GNS3",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Imprime os blocos de configuração renderizados",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Espera máxima, em segundos, pelo boot de cada nó (padrão: 600)",
    )
    parser.add_argument(
        "--check-timeout",
        type=int,
        default=20,
        help="Timeout de cada tentativa de conexão, em segundos (padrão: 20)",
    )
    parser.add_argument(
        "--poll",
        type=float,
        default=5.0,
        help="Intervalo entre tentativas de conexão, em segundos (padrão: 5)",
    )
    return parser.parse_args()


def carregar_json(caminho: Path, descricao: str) -> dict:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{descricao} não encontrado: {caminho}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{descricao} inválido ({caminho}): {exc}") from exc
    if not isinstance(dados, dict):
        raise ValueError(f"{descricao} deve ser um objeto JSON: {caminho}")
    return dados


def carregar_credenciais() -> Credenciais:
    load_dotenv(RAIZ / ".env")
    return Credenciais(
        username=os.getenv("EXOS_USERNAME", "admin"),
        password=os.getenv("EXOS_PASSWORD", ""),
    )


# ---------------------------------------------------------------------------
# Validação do plano declarativo
# ---------------------------------------------------------------------------


def _validar_vlans(plano: dict) -> dict[str, int]:
    itens = plano.get("vlans")
    if not isinstance(itens, list) or not itens:
        raise PlanoInvalidoError("'vlans' deve ser uma lista não vazia")

    nomes: set[str] = set()
    ids: set[int] = set()
    mapa: dict[str, int] = {}
    for item in itens:
        if not isinstance(item, dict):
            raise PlanoInvalidoError(f"VLAN inválida: {item!r}")
        nome = item.get("nome")
        vid = item.get("id")
        if not isinstance(nome, str) or not NOME_VLAN.match(nome):
            raise PlanoInvalidoError(
                f"nome de VLAN inválido: {nome!r} (sem espaços, acentos ou símbolos)"
            )
        if nome in nomes:
            raise PlanoInvalidoError(f"VLAN duplicada: {nome}")
        if not isinstance(vid, int) or isinstance(vid, bool):
            raise PlanoInvalidoError(f"ID da VLAN {nome} deve ser inteiro: {vid!r}")
        if vid in (1, 4095) or vid % 10 != 0:
            raise PlanoInvalidoError(
                f"ID da VLAN {nome} deve ser múltiplo de 10 e diferente de 1/4095: {vid}"
            )
        if vid in ids:
            raise PlanoInvalidoError(f"ID de VLAN duplicado: {vid}")
        nomes.add(nome)
        ids.add(vid)
        mapa[nome] = vid
    return mapa


def _validar_redes(plano: dict, vlans: dict[str, int]) -> dict[str, dict]:
    redes = plano.get("redes")
    if not isinstance(redes, dict) or not redes:
        raise PlanoInvalidoError("'redes' deve ser um objeto não vazio")

    resultado: dict[str, dict] = {}
    for nome, dados in redes.items():
        if nome not in vlans:
            raise PlanoInvalidoError(f"rede {nome!r} não corresponde a uma VLAN")
        if not isinstance(dados, dict):
            raise PlanoInvalidoError(f"rede {nome!r} inválida")
        try:
            rede = ipaddress.ip_network(dados.get("rede", ""), strict=True)
        except ValueError as exc:
            raise PlanoInvalidoError(f"rede {nome} inválida: {exc}") from exc

        gateway = dados.get("gateway")
        if gateway is not None:
            try:
                gateway_ip = ipaddress.ip_address(gateway)
            except ValueError as exc:
                raise PlanoInvalidoError(
                    f"gateway de {nome} inválido: {gateway!r}"
                ) from exc
            if gateway_ip not in rede:
                raise PlanoInvalidoError(
                    f"gateway {gateway} não pertence à rede {rede} ({nome})"
                )
            if gateway_ip in (rede.network_address, rede.broadcast_address):
                raise PlanoInvalidoError(
                    f"gateway {gateway} é endereço de rede/broadcast ({nome})"
                )

        dhcp = bool(dados.get("dhcp"))
        if dhcp and gateway is None:
            raise PlanoInvalidoError(f"rede {nome} tem DHCP sem gateway")
        if dhcp and rede.num_addresses < 4:
            raise PlanoInvalidoError(f"rede {nome} é pequena demais para DHCP")

        resultado[nome] = {
            "rede": rede,
            "gateway": gateway_ip if gateway is not None else None,
            "dhcp": dhcp,
        }

    ausentes = sorted(set(vlans) - set(resultado))
    if ausentes:
        raise PlanoInvalidoError(
            f"VLANs sem rede definida em 'redes': {', '.join(ausentes)}"
        )
    return resultado


def _validar_switches(plano: dict, redes: dict[str, dict]) -> dict[str, dict]:
    switches = plano.get("switches")
    if not isinstance(switches, dict) or not switches:
        raise PlanoInvalidoError("'switches' deve ser um objeto não vazio")

    resultado: dict[str, dict] = {}
    nucleos = 0
    gerencia = redes["Gerencia"]["rede"]
    ips_gerencia: set[str] = set()

    for nome, dados in switches.items():
        if not isinstance(dados, dict):
            raise PlanoInvalidoError(f"switch {nome!r} inválido")
        papel = dados.get("papel")
        if papel not in ("core", "acesso"):
            raise PlanoInvalidoError(
                f"papel do switch {nome} inválido: {papel!r} (use 'core' ou 'acesso')"
            )
        if papel == "core":
            nucleos += 1

        troncos: list[dict] = []
        portas_vistas: set[int] = set()
        for bruto in dados.get("troncos", []):
            if not isinstance(bruto, dict):
                raise PlanoInvalidoError(f"tronco inválido em {nome}: {bruto!r}")
            porta = bruto.get("porta")
            if not isinstance(porta, int) or isinstance(porta, bool):
                raise PlanoInvalidoError(
                    f"porta de tronco inválida em {nome}: {porta!r}"
                )
            if porta in portas_vistas:
                raise PlanoInvalidoError(
                    f"porta {porta} repetida nos troncos de {nome}"
                )
            portas_vistas.add(porta)
            vlans = bruto.get("vlans")
            if vlans is not None:
                if not isinstance(vlans, list) or not vlans:
                    raise PlanoInvalidoError(
                        f"'vlans' do tronco {porta} de {nome} deve ser lista não vazia"
                    )
            troncos.append({"porta": porta, "vlans": vlans})

        item: dict = {"papel": papel, "troncos": troncos}

        if papel == "acesso":
            endereco = dados.get("gerencia")
            if not isinstance(endereco, str):
                raise PlanoInvalidoError(
                    f"switch de acesso {nome} exige 'gerencia' no formato IP/prefixo"
                )
            try:
                interface = ipaddress.ip_interface(endereco)
            except ValueError as exc:
                raise PlanoInvalidoError(
                    f"IP de gerência inválido em {nome}: {endereco!r}"
                ) from exc
            if interface.network != gerencia:
                raise PlanoInvalidoError(
                    f"IP de gerência de {nome} ({interface.ip}) fora da rede "
                    f"{gerencia}"
                )
            if interface.ip == redes["Gerencia"]["gateway"]:
                raise PlanoInvalidoError(
                    f"IP de gerência de {nome} colide com o gateway "
                    f"{redes['Gerencia']['gateway']}"
                )
            if str(interface.ip) in ips_gerencia:
                raise PlanoInvalidoError(
                    f"IP de gerência duplicado: {interface.ip}"
                )
            ips_gerencia.add(str(interface.ip))
            item["gerencia"] = endereco

        resultado[nome] = item

    if nucleos != 1:
        raise PlanoInvalidoError(
            f"exatamente um switch deve ter papel 'core' (encontrados: {nucleos})"
        )
    return resultado


def _enlaces_por_host() -> dict[str, tuple[str, int]]:
    """Mapeia VPCS -> (switch, porta) a partir do mapa L1 do Milestone 2."""
    mapa: dict[str, tuple[str, int]] = {}
    for enlace in ENLACES_INICIAIS:
        porta_a = re.fullmatch(r"Port(\d+)", enlace.porta_a)
        porta_b = re.fullmatch(r"Port(\d+)", enlace.porta_b)
        if porta_b:
            mapa.setdefault(enlace.no_a, (enlace.no_b, int(porta_b.group(1))))
        if porta_a:
            mapa.setdefault(enlace.no_b, (enlace.no_a, int(porta_a.group(1))))
    return mapa


def _enlaces_entre_switches() -> set[tuple[str, int]]:
    """Conjunto (switch, porta) de todas as pontas de tronco do mapa L1."""
    portas: set[tuple[str, int]] = set()
    for enlace in ENLACES_INICIAIS:
        porta_a = re.fullmatch(r"Port(\d+)", enlace.porta_a)
        porta_b = re.fullmatch(r"Port(\d+)", enlace.porta_b)
        if porta_a and porta_b:  # ambos os lados são portas de switch
            portas.add((enlace.no_a, int(porta_a.group(1))))
            portas.add((enlace.no_b, int(porta_b.group(1))))
    return portas


def _validar_hosts(
    plano: dict,
    vlans: dict[str, int],
    redes: dict[str, dict],
    switches: dict[str, dict],
) -> None:
    hosts = plano.get("hosts")
    if not isinstance(hosts, dict) or not hosts:
        raise PlanoInvalidoError("'hosts' deve ser um objeto não vazio")

    enlaces_host = _enlaces_por_host()
    portas_acesso: dict[str, set[int]] = {nome: set() for nome in switches}

    for nome, dados in hosts.items():
        if not isinstance(dados, dict):
            raise PlanoInvalidoError(f"host {nome!r} inválido")
        switch = dados.get("switch")
        porta = dados.get("porta")
        vlan = dados.get("vlan")
        if switch not in switches:
            raise PlanoInvalidoError(f"host {nome} aponta para switch inexistente: {switch!r}")
        if not isinstance(porta, int) or isinstance(porta, bool) or porta < 1:
            raise PlanoInvalidoError(f"porta inválida para {nome}: {porta!r}")
        if vlan not in vlans:
            raise PlanoInvalidoError(f"VLAN inválida para {nome}: {vlan!r}")

        if porta in portas_acesso[switch]:
            raise PlanoInvalidoError(
                f"porta {porta} de {switch} usada por mais de um host"
            )
        portas_acesso[switch].add(porta)

        fisico = enlaces_host.get(nome)
        if fisico != (switch, porta):
            where = (
                f"{fisico[0]}:Port{fisico[1]}" if fisico is not None else "nenhum"
            )
            raise PlanoInvalidoError(
                f"{nome}: o plano declara {switch}:Port{porta}, "
                f"mas o mapa L1 do Milestone 2 diz {where}"
            )

        modo = dados.get("modo")
        rede = redes[vlan]
        if modo == "estatico":
            try:
                interface = ipaddress.ip_interface(dados.get("ip", ""))
            except ValueError as exc:
                raise PlanoInvalidoError(f"IP inválido para {nome}: {exc}") from exc
            if interface.network != rede["rede"]:
                raise PlanoInvalidoError(
                    f"IP de {nome} ({interface}) fora da rede {rede['rede']} ({vlan})"
                )
            if interface.ip in (
                rede["rede"].network_address,
                rede["rede"].broadcast_address,
            ):
                raise PlanoInvalidoError(
                    f"IP de {nome} é endereço de rede/broadcast: {interface.ip}"
                )
            gateway = dados.get("gateway")
            if gateway is not None:
                try:
                    gateway_ip = ipaddress.ip_address(gateway)
                except ValueError as exc:
                    raise PlanoInvalidoError(
                        f"gateway inválido para {nome}: {gateway!r}"
                    ) from exc
                if gateway_ip not in rede["rede"]:
                    raise PlanoInvalidoError(
                        f"gateway de {nome} fora da rede {rede['rede']}"
                    )
                if rede["gateway"] is not None and gateway_ip != rede["gateway"]:
                    raise PlanoInvalidoError(
                        f"gateway de {nome} deve ser {rede['gateway']} (VLAN {vlan})"
                    )
            elif rede["gateway"] is not None:
                raise PlanoInvalidoError(
                    f"{nome} está em VLAN roteada e exige gateway {rede['gateway']}"
                )
        elif modo == "dhcp":
            if not rede["dhcp"]:
                raise PlanoInvalidoError(
                    f"{nome} usa DHCP, mas a VLAN {vlan} não possui escopo DHCP"
                )
            if dados.get("ip") or dados.get("gateway"):
                raise PlanoInvalidoError(
                    f"{nome} é dinâmico e não deve declarar ip/gateway"
                )
        else:
            raise PlanoInvalidoError(
                f"modo inválido para {nome}: {modo!r} (use 'estatico' ou 'dhcp')"
            )

    for nome, dados in switches.items():
        troncos = {item["porta"] for item in dados["troncos"]}
        conflito = portas_acesso[nome] & troncos
        if conflito:
            raise PlanoInvalidoError(
                f"porta(s) {sorted(conflito)} de {nome} são acesso e tronco ao mesmo tempo"
            )


def _validar_troncos(plano: dict, switches: dict[str, dict]) -> None:
    fisicos = _enlaces_entre_switches()
    for nome, dados in switches.items():
        for tronco in dados["troncos"]:
            chave = (nome, tronco["porta"])
            if chave not in fisicos:
                raise PlanoInvalidoError(
                    f"tronco {nome}:Port{tronco['porta']} não existe no mapa L1"
                )

    cameras = plano["redes"]["Cameras"]
    if cameras["gateway"] is not None or cameras["dhcp"]:
        raise PlanoInvalidoError(
            "a VLAN Cameras deve permanecer isolada (sem gateway e sem DHCP)"
        )


def validar_plano(plano: dict) -> tuple[dict[str, int], dict[str, dict], dict[str, dict]]:
    """Valida as normas do STI e a coerência com o mapa L1 do Milestone 2."""
    vlans = _validar_vlans(plano)
    redes = _validar_redes(plano, vlans)
    switches = _validar_switches(plano, redes)
    _validar_hosts(plano, vlans, redes, switches)
    _validar_troncos(plano, switches)
    return vlans, redes, switches


# ---------------------------------------------------------------------------
# Contexto de renderização
# ---------------------------------------------------------------------------


def portas_acesso(plano: dict, switch: str) -> list[dict]:
    return sorted(
        (
            {"porta": host["porta"], "vlan": host["vlan"]}
            for host in plano["hosts"].values()
            if host["switch"] == switch
        ),
        key=lambda item: item["porta"],
    )


def troncos_normalizados(plano: dict, switch: str) -> list[dict]:
    todas = [item["nome"] for item in plano["vlans"]]
    troncos: list[dict] = []
    for bruto in plano["switches"][switch].get("troncos", []):
        vlans = bruto.get("vlans")
        troncos.append(
            {
                "porta": int(bruto["porta"]),
                "vlans": list(vlans) if vlans is not None else todas,
            }
        )
    return troncos


def comprimir_portas(portas: list[int] | set[int]) -> str:
    """Compacta ``[1, 22, 23, 24]`` em ``1,22-24`` (sintaxe EXOS)."""
    numeros = sorted(set(portas))
    if not numeros:
        return ""
    blocos: list[str] = []
    inicio = anterior = numeros[0]
    for numero in numeros[1:]:
        if numero == anterior + 1:
            anterior = numero
            continue
        blocos.append(str(inicio) if inicio == anterior else f"{inicio}-{anterior}")
        inicio = anterior = numero
    blocos.append(str(inicio) if inicio == anterior else f"{inicio}-{anterior}")
    return ",".join(blocos)


def calcular_comandos_portas(
    acesso: list[dict],
    troncos: list[dict],
    estado: dict | None,
) -> list[str]:
    """Gera apenas as mudanças de porta necessárias (read-before-write)."""
    untagged = (estado or {}).get("untagged_por_porta", {})
    tagged = (estado or {}).get("tagged_por_porta", {})
    comandos: list[str] = []

    for item in acesso:
        porta = item["porta"]
        vlan = item["vlan"]
        atual = untagged.get(porta)
        if atual != vlan:
            if atual is not None:
                comandos.append(f"configure vlan {atual} delete ports {porta}")
            comandos.append(f"configure vlan {vlan} add ports {porta} untagged")
        for outra in sorted(tagged.get(porta, set()) - {vlan}):
            comandos.append(f"configure vlan {outra} delete ports {porta}")

    for item in troncos:
        porta = item["porta"]
        atual = untagged.get(porta)
        if atual is not None:
            comandos.append(f"configure vlan {atual} delete ports {porta}")
        presentes = tagged.get(porta, set())
        for vlan in item["vlans"]:
            if vlan not in presentes:
                comandos.append(f"configure vlan {vlan} add ports {porta} tagged")

    return comandos


def montar_escopos_dhcp(
    plano: dict, troncos: list[dict], acesso: list[dict]
) -> list[dict]:
    portas_tronco = {item["porta"] for item in troncos}
    escopos: list[dict] = []
    for vlan in plano["vlans"]:
        nome = vlan["nome"]
        dados = plano["redes"][nome]
        if not dados["dhcp"]:
            continue
        rede = ipaddress.ip_network(dados["rede"], strict=True)
        gateway = ipaddress.ip_address(dados["gateway"])
        inicio = int(gateway) + 1
        fim = int(rede.broadcast_address) - 1
        if inicio > fim:
            raise PlanoInvalidoError(
                f"faixa DHCP vazia para {nome}: gateway {gateway} no fim da rede"
            )
        portas = set(portas_tronco)
        portas.update(item["porta"] for item in acesso if item["vlan"] == nome)
        escopos.append(
            {
                "nome": nome,
                "inicio": str(ipaddress.ip_address(inicio)),
                "fim": str(ipaddress.ip_address(fim)),
                "gateway": str(gateway),
                "portas": comprimir_portas(portas),
            }
        )
    return escopos


def montar_contexto_switch(
    plano: dict, switch: str, estado: dict | None
) -> tuple[dict, list[dict], list[dict]]:
    dados = plano["switches"][switch]
    acesso = portas_acesso(plano, switch)
    troncos = troncos_normalizados(plano, switch)

    existentes = set((estado or {}).get("ids", {}))
    vlans_ausentes = [
        vlan for vlan in plano["vlans"] if vlan["nome"] not in existentes
    ]

    contexto: dict = {
        "papel": dados["papel"],
        "vlans_ausentes": vlans_ausentes,
        "comandos_portas": calcular_comandos_portas(acesso, troncos, estado),
    }

    if dados["papel"] == "core":
        redes_com_gateway = []
        for vlan in plano["vlans"]:
            nome = vlan["nome"]
            rede = plano["redes"][nome]
            if rede["gateway"] is None:
                continue
            prefixo = ipaddress.ip_network(rede["rede"], strict=True).prefixlen
            redes_com_gateway.append(
                {"nome": nome, "ip": f"{rede['gateway']}/{prefixo}"}
            )
        contexto["redes_com_gateway"] = redes_com_gateway
        contexto["escopos_dhcp"] = montar_escopos_dhcp(plano, troncos, acesso)
    else:
        contexto["gerencia"] = {
            "ip": dados["gerencia"],
            "gateway": str(plano["redes"]["Gerencia"]["gateway"]),
        }

    return contexto, acesso, troncos


def criar_ambiente(templates: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(templates)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def renderizar_switch(ambiente: Environment, contexto: dict) -> list[str]:
    texto = ambiente.get_template("exos/switch.j2").render(**contexto)
    return [linha.strip() for linha in texto.splitlines() if linha.strip()]


def renderizar_host(ambiente: Environment, host: dict) -> list[str]:
    template = (
        "vpcs/estatico.j2" if host["modo"] == "estatico" else "vpcs/dhcp.j2"
    )
    texto = ambiente.get_template(template).render(host=host)
    return [linha.strip() for linha in texto.splitlines() if linha.strip()]


# ---------------------------------------------------------------------------
# Leitura do estado atual (EXOS)
# ---------------------------------------------------------------------------


def _extrair_portas(texto: str) -> set[int]:
    portas: set[int] = set()
    for token in re.split(r"[\s,]+", texto):
        achado = re.match(r"[*!]?(\d+)", token)
        if achado:
            portas.add(int(achado.group(1)))
    return portas


def _parse_detalhe_vlan(texto: str) -> dict:
    ip = None
    achado = re.search(r"^\s*(?:Primary IP|IPv4):\s+(\S+)", texto, re.M)
    if achado and achado.group(1).lower() != "none":
        ip = achado.group(1)

    forwarding = False
    achado = re.search(r"^\s*IPv4 Forwarding:\s+(\S+)", texto, re.M)
    if achado and achado.group(1).lower().startswith("enabled"):
        forwarding = True

    untagged: set[int] = set()
    tagged: set[int] = set()
    secao: str | None = None
    for linha in texto.splitlines():
        cabecalho = re.match(r"^\s*(Untag|Tag|Flags):\s*(.*)$", linha)
        if cabecalho:
            nome = cabecalho.group(1)
            secao = None if nome == "Flags" else nome
            if secao == "Untag":
                untagged |= _extrair_portas(cabecalho.group(2))
            elif secao == "Tag":
                tagged |= _extrair_portas(cabecalho.group(2))
            continue
        if secao is None:
            continue
        if not linha.strip():
            secao = None
            continue
        if re.match(r"^\s*[A-Za-z][A-Za-z /]*:", linha):
            secao = None
            continue
        if secao == "Untag":
            untagged |= _extrair_portas(linha)
        else:
            tagged |= _extrair_portas(linha)

    return {
        "ip": ip,
        "forwarding": forwarding,
        "untagged": untagged,
        "tagged": tagged,
    }


def _ler_comando(conn, comando: str, marcador: str, tentativas: int = 3) -> str:
    """Executa um comando de leitura tolerando respostas truncadas do console."""
    ultima = ""
    for tentativa in range(1, tentativas + 1):
        saida = conn.send_command(comando, read_timeout=60)
        if marcador in saida:
            return saida
        ultima = saida
        if tentativa < tentativas:
            time.sleep(1)
    raise ValidacaoError(
        f"saída inesperada de {comando!r} "
        f"(esperado {marcador!r}): {ultima[:300]!r}"
    )


def ler_estado_switch(conn) -> dict:
    resumo = _ler_comando(conn, "show vlan", "Name")
    ids: dict[str, int] = {}
    for linha in resumo.splitlines():
        achado = re.match(r"^([A-Za-z0-9_-]+)\s+(\d+)\s+", linha)
        if achado:
            ids[achado.group(1)] = int(achado.group(2))
    if not ids:
        raise ValidacaoError(
            "não foi possível interpretar 'show vlan' (nenhuma VLAN encontrada)"
        )

    untagged_por_porta: dict[int, str] = {}
    tagged_por_porta: dict[int, set[str]] = {}
    ip_por_vlan: dict[str, str] = {}
    forwarding: dict[str, bool] = {}

    for nome in ids:
        detalhe = _ler_comando(
            conn, f"show vlan {nome}", "VLAN Interface with name"
        )
        info = _parse_detalhe_vlan(detalhe)
        if info["ip"]:
            ip_por_vlan[nome] = info["ip"]
        forwarding[nome] = info["forwarding"]
        for porta in info["untagged"]:
            untagged_por_porta[porta] = nome
        for porta in info["tagged"]:
            tagged_por_porta.setdefault(porta, set()).add(nome)

    return {
        "ids": ids,
        "untagged_por_porta": untagged_por_porta,
        "tagged_por_porta": tagged_por_porta,
        "ip_por_vlan": ip_por_vlan,
        "forwarding": forwarding,
    }


def ler_ipconfig(conn) -> tuple[dict[str, str], dict[str, bool]]:
    saida = _ler_comando(conn, "show ipconfig", "Interface")
    ips: dict[str, str] = {}
    forwarding: dict[str, bool] = {}
    for linha in saida.splitlines():
        achado = re.match(
            r"^(\S+)\s+(\d+\.\d+\.\d+\.\d+)\s+/(\d+)\s+(\S+)\s+\d+\s*$",
            linha,
        )
        if not achado:
            continue
        nome = achado.group(1)
        ips[nome] = f"{achado.group(2)}/{achado.group(3)}"
        forwarding[nome] = "f" in achado.group(4)
    return ips, forwarding


def ler_rota_padrao(conn) -> str | None:
    saida = _ler_comando(conn, "show iproute", "Destination")
    for linha in saida.splitlines():
        achado = re.match(
            r"^\S+\s+Default Route\s+(\d+\.\d+\.\d+\.\d+)\b", linha, re.I
        )
        if achado:
            return achado.group(1)
    return None


# ---------------------------------------------------------------------------
# Conexão / readiness check
# ---------------------------------------------------------------------------


def _parametros_conexao(
    nome: str, dados: dict, credenciais: Credenciais, timeout: int
) -> dict:
    device_type = dados.get("device_type") or (
        "extreme_exos_telnet" if dados.get("node_type") == "qemu" else "generic_telnet"
    )
    parametros = {
        "device_type": device_type,
        "host": dados["host"],
        "port": int(dados["port"]),
        "timeout": timeout,
        "conn_timeout": timeout,
        "global_delay_factor": 2,
        "fast_cli": False,
    }
    if device_type.startswith("extreme"):
        parametros["username"] = credenciais.username
        parametros["password"] = credenciais.password
    return parametros


def conectar(
    nome: str,
    dados: dict,
    credenciais: Credenciais,
    timeout: int,
    check_timeout: int,
    poll: float,
) -> object:
    """Polling de boot: só devolve a conexão quando o SO responde de fato."""
    limite = time.monotonic() + timeout
    tentativa = 0

    while True:
        tentativa += 1
        try:
            conn = ConnectHandler(
                **_parametros_conexao(nome, dados, credenciais, check_timeout)
            )
            prompt = conn.find_prompt()
            device_type = conn.device_type
            if device_type.startswith("extreme"):
                if "#" not in prompt:
                    raise ProntidaoError(f"prompt inesperado: {prompt!r}")
                versao = conn.send_command("show version", read_timeout=60)
                if "ExtremeXOS" not in versao:
                    raise ProntidaoError("EXOS ainda não respondeu a 'show version'")
            else:
                if not prompt.strip().endswith(">"):
                    conn.write_channel("\r\n")
                    prompt = conn.find_prompt()
                if not prompt.strip().endswith(">"):
                    raise ProntidaoError(f"prompt do VPCS inesperado: {prompt!r}")
                conn.send_command("show ip", read_timeout=30)
            return conn
        except Exception as exc:  # noqa: BLE001 - tentativas de boot
            if time.monotonic() >= limite:
                raise ProntidaoError(
                    f"{nome} não ficou pronto em {timeout}s "
                    f"(último erro: {type(exc).__name__}: {exc})"
                ) from exc
            if tentativa == 1 or tentativa % 6 == 0:
                print(
                    f"  aguardando {nome} subir (tentativa {tentativa}): "
                    f"{type(exc).__name__}",
                    flush=True,
                )
            time.sleep(poll)


# ---------------------------------------------------------------------------
# Aplicação e validação
# ---------------------------------------------------------------------------


def aplicar_exos(conn, comandos: list[str]) -> None:
    if not comandos:
        print("  nenhuma diferença de configuração.")
        return
    print(f"  aplicando {len(comandos)} comando(s)...")
    conn.send_config_set(
        comandos,
        cmd_verify=False,
        read_timeout=120,
        strip_prompt=False,
        strip_command=False,
    )


def aplicar_vpcs(conn, comandos: list[str]) -> None:
    for comando in comandos:
        conn.send_command_timing(
            comando,
            read_timeout=60,
            strip_prompt=False,
            strip_command=False,
        )


def validar_exos(
    conn,
    nome: str,
    plano: dict,
    contexto: dict,
    acesso: list[dict],
    troncos: list[dict],
) -> None:
    estado = ler_estado_switch(conn)
    erros: list[str] = []

    for vlan in plano["vlans"]:
        esperado = vlan["id"]
        atual = estado["ids"].get(vlan["nome"])
        if atual != esperado:
            erros.append(
                f"VLAN {vlan['nome']}: esperado ID {esperado}, encontrado {atual!r}"
            )

    for item in acesso:
        porta = item["porta"]
        atual = estado["untagged_por_porta"].get(porta)
        if atual != item["vlan"]:
            erros.append(
                f"porta {porta}: esperada untagged em {item['vlan']}, "
                f"encontrada untagged em {atual!r}"
            )
        if atual == "Default":
            erros.append(f"porta {porta} de acesso ainda pertence à VLAN Default")

    for item in troncos:
        porta = item["porta"]
        if estado["untagged_por_porta"].get(porta) is not None:
            erros.append(
                f"porta {porta} de tronco ainda possui VLAN untagged "
                f"({estado['untagged_por_porta'][porta]})"
            )
        presentes = estado["tagged_por_porta"].get(porta, set())
        for vlan in item["vlans"]:
            if vlan not in presentes:
                erros.append(f"porta {porta}: falta a VLAN {vlan} como tagged")

    ips, forwarding = ler_ipconfig(conn)

    if contexto["papel"] == "core":
        for item in contexto["redes_com_gateway"]:
            esperado = ipaddress.ip_interface(item["ip"])
            atual = ips.get(item["nome"])
            if atual is None or ipaddress.ip_interface(atual) != esperado:
                erros.append(
                    f"SVI {item['nome']}: esperado {item['ip']}, encontrado {atual!r}"
                )
            if not forwarding.get(item["nome"], False):
                erros.append(f"SVI {item['nome']} sem ipforwarding")

        cameras = "Cameras"
        if cameras in ips:
            erros.append(
                f"VLAN {cameras} possui IP ({ips[cameras]}); isolamento CFTV violado"
            )
        if forwarding.get(cameras, False):
            erros.append(
                f"VLAN {cameras} possui ipforwarding; isolamento CFTV violado"
            )
    else:
        gerencia = contexto["gerencia"]["ip"]
        esperado = ipaddress.ip_interface(gerencia)
        atual = ips.get("Gerencia")
        if atual is None or ipaddress.ip_interface(atual) != esperado:
            erros.append(
                f"IP de gerência: esperado {gerencia}, encontrado {atual!r}"
            )
        rota = ler_rota_padrao(conn)
        if rota != contexto["gerencia"]["gateway"]:
            erros.append(
                f"rota padrão: esperado {contexto['gerencia']['gateway']}, "
                f"encontrado {rota!r}"
            )

    if erros:
        raise ValidacaoError(f"{nome}:\n  - " + "\n  - ".join(erros))


def ler_ip_vpcs(conn) -> tuple[str | None, str | None]:
    saida = _ler_comando(conn, "show ip", "IP/MASK")
    ip = None
    gateway = None
    achado = re.search(r"IP/MASK\s*:\s*(\S+)", saida)
    if achado:
        ip = achado.group(1)
    achado = re.search(r"GATEWAY\s*:\s*(\S+)", saida)
    if achado:
        gateway = achado.group(1)
    return ip, gateway


def aguardar_dhcp(conn, timeout: int = 45):
    limite = time.monotonic() + timeout
    while True:
        ip, gateway = ler_ip_vpcs(conn)
        if ip and ip != "0.0.0.0/0":
            return ip, gateway
        if time.monotonic() >= limite:
            raise ValidacaoError(
                f"host não obteve IP via DHCP em {timeout}s (show ip: {ip!r})"
            )
        time.sleep(2)


def validar_vpcs(conn, nome: str, plano: dict, host: dict) -> None:
    if host["modo"] == "dhcp":
        rede = ipaddress.ip_network(
            plano["redes"][host["vlan"]]["rede"], strict=True
        )
        ip, gateway = aguardar_dhcp(conn)
        interface = ipaddress.ip_interface(ip)
        if interface.network != rede:
            raise ValidacaoError(
                f"{nome}: DHCP entregou {ip}, fora da rede {rede} "
                f"(VLAN {host['vlan']})"
            )
        esperado_gw = str(plano["redes"][host["vlan"]]["gateway"])
        if gateway != esperado_gw:
            raise ValidacaoError(
                f"{nome}: gateway DHCP {gateway!r}, esperado {esperado_gw!r}"
            )
        return

    ip, gateway = ler_ip_vpcs(conn)
    esperado = ipaddress.ip_interface(host["ip"])
    if ip is None or ipaddress.ip_interface(ip) != esperado:
        raise ValidacaoError(
            f"{nome}: IP esperado {host['ip']}, encontrado {ip!r}"
        )
    esperado_gw = host.get("gateway") or "0.0.0.0"
    if gateway != esperado_gw:
        raise ValidacaoError(
            f"{nome}: gateway esperado {esperado_gw}, encontrado {gateway!r}"
        )


# ---------------------------------------------------------------------------
# Fluxo principal
# ---------------------------------------------------------------------------


def garantir_inventario(inventario: dict, nomes: list[str]) -> None:
    faltando: list[str] = []
    parados: list[str] = []
    for nome in nomes:
        dados = inventario.get(nome)
        if not isinstance(dados, dict):
            faltando.append(nome)
            continue
        if not dados.get("host") or not dados.get("port"):
            faltando.append(nome)
            continue
        if dados.get("status") != "started":
            parados.append(f"{nome} ({dados.get('status')!r})")
    if faltando:
        raise RuntimeError(
            "nós ausentes/incompletos no inventário: "
            + ", ".join(faltando)
            + ". Execute 'python setup_lab.py' antes."
        )
    if parados:
        raise RuntimeError(
            "nós não iniciados: "
            + ", ".join(parados)
            + ". Inicie o laboratório com 'python setup_lab.py'."
        )


def processar_switch(
    nome: str,
    dados: dict,
    plano: dict,
    ambiente: Environment,
    credenciais: Credenciais,
    args: argparse.Namespace,
    somente_validar: bool = False,
) -> None:
    conn = conectar(
        nome,
        dados,
        credenciais,
        args.timeout,
        args.check_timeout,
        args.poll,
    )
    try:
        if somente_validar:
            contexto, acesso, troncos = montar_contexto_switch(plano, nome, None)
            validar_exos(conn, nome, plano, contexto, acesso, troncos)
            print("  OK: estado validado.")
            return

        estado = ler_estado_switch(conn)
        contexto, acesso, troncos = montar_contexto_switch(plano, nome, estado)
        comandos = renderizar_switch(ambiente, contexto)
        if args.verbose:
            print("  --- configuração renderizada ---")
            for comando in comandos:
                print(f"  {comando}")
        aplicar_exos(conn, comandos)
        validar_exos(conn, nome, plano, contexto, acesso, troncos)
        print("  OK: provisionado e validado.")
    finally:
        conn.disconnect()


def processar_host(
    nome: str,
    dados: dict,
    plano: dict,
    ambiente: Environment,
    credenciais: Credenciais,
    args: argparse.Namespace,
    somente_validar: bool = False,
) -> None:
    conn = conectar(
        nome,
        dados,
        credenciais,
        args.timeout,
        args.check_timeout,
        args.poll,
    )
    try:
        host = plano["hosts"][nome]
        if somente_validar:
            validar_vpcs(conn, nome, plano, host)
            print("  OK: host validado.")
            return

        comandos = renderizar_host(ambiente, host)
        if args.verbose:
            print("  --- configuração renderizada ---")
            for comando in comandos:
                print(f"  {comando}")
        aplicar_vpcs(conn, comandos)
        validar_vpcs(conn, nome, plano, host)
        print("  OK: host configurado e validado.")
    finally:
        conn.disconnect()


def selecionar(args: argparse.Namespace, plano: dict) -> tuple[list[str], list[str]]:
    switches = list(plano["switches"])
    hosts = list(plano["hosts"])

    if args.only:
        desejados = {nome.strip() for nome in args.only.split(",") if nome.strip()}
        desconhecidos = desejados - set(switches) - set(hosts)
        if desconhecidos:
            raise ValueError(
                "nós desconhecidos em --only: " + ", ".join(sorted(desconhecidos))
            )
        switches = [nome for nome in switches if nome in desejados]
        hosts = [nome for nome in hosts if nome in desejados]

    if args.skip_switches:
        switches = []
    if args.skip_hosts:
        hosts = []
    return switches, hosts


def main() -> int:
    args = parse_args()
    try:
        plano = carregar_json(args.plano, "plano de rede")
        inventario = carregar_json(args.inventario, "inventário de consoles")
        validar_plano(plano)
        switches, hosts = selecionar(args, plano)
        if not switches and not hosts:
            print("Nada a fazer: nenhum nó selecionado.", file=sys.stderr)
            return 1
        if not args.dry_run:
            garantir_inventario(inventario, switches + hosts)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    credenciais = carregar_credenciais()
    ambiente = criar_ambiente(args.templates)

    if args.dry_run:
        for nome in switches:
            contexto, _, _ = montar_contexto_switch(plano, nome, None)
            print(f"\n=== {nome} (dry-run) ===")
            for comando in renderizar_switch(ambiente, contexto):
                print(comando)
        for nome in hosts:
            print(f"\n=== {nome} (dry-run) ===")
            for comando in renderizar_host(ambiente, plano["hosts"][nome]):
                print(comando)
        return 0

    somente_validar = args.check
    if somente_validar:
        print("Modo --check: nenhuma configuração será alterada.")

    falhas: list[str] = []
    try:
        # O core primeiro: os hosts dinâmicos dependem do DHCP.
        for nome in switches:
            print(f"\n=== {nome} ===", flush=True)
            try:
                processar_switch(
                    nome,
                    inventario[nome],
                    plano,
                    ambiente,
                    credenciais,
                    args,
                    somente_validar=somente_validar,
                )
            except Exception as exc:  # noqa: BLE001 - continua nos demais nós
                print(f"  ERRO: {exc}", file=sys.stderr)
                falhas.append(nome)

        for nome in hosts:
            print(f"\n=== {nome} ===", flush=True)
            try:
                processar_host(
                    nome,
                    inventario[nome],
                    plano,
                    ambiente,
                    credenciais,
                    args,
                    somente_validar=somente_validar,
                )
            except Exception as exc:  # noqa: BLE001 - continua nos demais nós
                print(f"  ERRO: {exc}", file=sys.stderr)
                falhas.append(nome)
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.", file=sys.stderr)
        return 130

    if falhas:
        print(
            "\nFalha em: " + ", ".join(falhas),
            file=sys.stderr,
        )
        return 1

    acao = "validado" if somente_validar else "provisionado"
    print(
        f"\nMilestone 3 {acao}: {len(switches)} switch(es) e "
        f"{len(hosts)} host(s) OK."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
