#!/usr/bin/env python3
"""Gestão de mudanças (Day 2) do laboratório: os três chamados do Milestone 5.

Abordagem híbrida: a API do GNS3 (``gns3fy``) cria nós e cabos, enquanto o
Netmiko aplica/valida a configuração EXOS e o endereçamento dos VPCS. Os
chamados são sequenciais e idempotentes:

1. ``chamado1``: cria o VPCS ``PC-LACINA-SALA`` no ``SW-LIAD`` porta 4 e
   associa a porta à VLAN ``LACINA``;
2. ``chamado2``: simula o rompimento do tronco ``SW-LACINA`` x ``SW-LIAD``
   (``disable port 24`` nas duas pontas), liga o cabo de contingência
   ``SW-LSI`` x ``SW-LIAD`` porta 22 e reconfigura os troncos;
3. ``chamado3``: migra ``PC-LIAD-SALA`` para a VLAN ``LSI`` no ``SW-LSI`` e
   remove a VLAN ``LIAD`` residual daquele switch.

Nenhuma porta de console é hardcoded: tudo vem do ``inventario_gns3.json``,
que é regravado sempre que um nó é criado ou renomeado.
"""

from __future__ import annotations

import argparse
import ipaddress
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from gns3fy import Node, Project
from requests.exceptions import JSONDecodeError

try:  # import relativo quando chamado como pacote
    from .provisionar import (
        Credenciais,
        aplicar_exos,
        aplicar_vpcs,
        aguardar_dhcp,
        calcular_comandos_portas,
        carregar_credenciais,
        carregar_json,
        comprimir_portas,
        conectar,
        ler_estado_switch,
        ler_ip_vpcs,
        validar_plano,
    )
    from .setup_lab import (
        Configuracao,
        _chave_enlace,
        _endpoint,
        aguardar,
        carregar_configuracao,
        criar_conector,
        gravar_inventario,
        localizar_projeto,
        montar_inventario,
        verificar_token,
    )
    from .testes_aceite import interpretar_ping
    from .topologia import ENLACES_INICIAIS, PORTA_VPCS
except ImportError:  # execução direta: python infra/mudancas.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from provisionar import (  # type: ignore[no-redef]
        Credenciais,
        aplicar_exos,
        aplicar_vpcs,
        aguardar_dhcp,
        calcular_comandos_portas,
        carregar_credenciais,
        carregar_json,
        comprimir_portas,
        conectar,
        ler_estado_switch,
        ler_ip_vpcs,
        validar_plano,
    )
    from setup_lab import (  # type: ignore[no-redef]
        Configuracao,
        _chave_enlace,
        _endpoint,
        aguardar,
        carregar_configuracao,
        criar_conector,
        gravar_inventario,
        localizar_projeto,
        montar_inventario,
        verificar_token,
    )
    from testes_aceite import interpretar_ping  # type: ignore[no-redef]
    from topologia import ENLACES_INICIAIS, PORTA_VPCS  # type: ignore[no-redef]

RAIZ = Path(__file__).resolve().parents[1]
PLANO_PADRAO = RAIZ / "infra" / "config" / "plano_rede.json"
PLANO_MUDANCAS_PADRAO = RAIZ / "infra" / "config" / "plano_mudancas.json"
INVENTARIO_PADRAO = RAIZ / "inventario_gns3.json"

CHAMADOS = ("chamado1", "chamado2", "chamado3")
TITULOS = {
    "chamado1": "Chamado 1: LACINA ganha uma sala no LIAD",
    "chamado2": "Chamado 2: obra rompe o tronco LACINA-LIAD",
    "chamado3": "Chamado 3: LIAD devolve a sala ao LSI",
}


class MudancaInvalidaError(ValueError):
    """O plano de mudanças é inconsistente com a topologia/plano base."""


class ValidacaoMudancaError(RuntimeError):
    """O estado observado após a mudança divergiu do esperado."""


# ---------------------------------------------------------------------------
# Validação do plano de mudanças
# ---------------------------------------------------------------------------


def _inteiro(valor: object, campo: str) -> int:
    if not isinstance(valor, int) or isinstance(valor, bool) or valor < 1:
        raise MudancaInvalidaError(f"{campo} deve ser inteiro positivo: {valor!r}")
    return valor


def _nome(valor: object, campo: str) -> str:
    if not isinstance(valor, str) or not valor:
        raise MudancaInvalidaError(f"{campo} deve ser texto não vazio: {valor!r}")
    return valor


def _vlans_do_plano(plano: dict) -> list[str]:
    return [item["nome"] for item in plano["vlans"]]


def _portas_do_switch(plano: dict, switch: str) -> set[int]:
    """Portas já usadas por hosts ou troncos declarados no plano base."""
    portas = {
        int(tronco["porta"])
        for tronco in plano["switches"][switch].get("troncos", [])
    }
    portas.update(
        int(host["porta"])
        for host in plano["hosts"].values()
        if host["switch"] == switch
    )
    return portas


def _enlace_do_mapa(no_a: str, porta_a: int, no_b: str, porta_b: int) -> bool:
    procurado = frozenset(((no_a, porta_a), (no_b, porta_b)))
    for enlace in ENLACES_INICIAIS:
        numero_a = int(enlace.porta_a.removeprefix("Port")) if enlace.porta_a.startswith("Port") else None
        numero_b = int(enlace.porta_b.removeprefix("Port")) if enlace.porta_b.startswith("Port") else None
        if numero_a is None or numero_b is None:
            continue
        if frozenset(((enlace.no_a, numero_a), (enlace.no_b, numero_b))) == procurado:
            return True
    return False


def validar_plano_mudancas(mudancas: dict, plano: dict) -> None:
    """Confere coerência entre ``plano_mudancas.json`` e o plano/topologia base."""
    if not isinstance(mudancas, dict):
        raise MudancaInvalidaError("plano de mudanças deve ser um objeto JSON")
    for chave in CHAMADOS:
        if not isinstance(mudancas.get(chave), dict):
            raise MudancaInvalidaError(f"'{chave}' ausente ou inválido")

    vlans = set(_vlans_do_plano(plano))
    switches = set(plano["switches"])

    # -- Chamado 1 ---------------------------------------------------------
    host = mudancas["chamado1"].get("host")
    if not isinstance(host, dict):
        raise MudancaInvalidaError("chamado1.host deve ser um objeto")
    nome = _nome(host.get("nome"), "chamado1.host.nome")
    if nome in plano["hosts"]:
        raise MudancaInvalidaError(f"chamado1: host {nome} já existe no plano base")
    switch = _nome(host.get("switch"), "chamado1.host.switch")
    if switch not in switches:
        raise MudancaInvalidaError(f"chamado1: switch desconhecido {switch!r}")
    porta = _inteiro(host.get("porta"), "chamado1.host.porta")
    if porta in _portas_do_switch(plano, switch):
        raise MudancaInvalidaError(
            f"chamado1: porta {porta} de {switch} já está em uso no plano base"
        )
    vlan = _nome(host.get("vlan"), "chamado1.host.vlan")
    if vlan not in vlans:
        raise MudancaInvalidaError(f"chamado1: VLAN desconhecida {vlan!r}")
    if host.get("modo") != "dhcp":
        raise MudancaInvalidaError("chamado1: o host deve usar modo 'dhcp'")
    if not plano["redes"][vlan].get("dhcp"):
        raise MudancaInvalidaError(f"chamado1: VLAN {vlan} não possui DHCP")

    # -- Chamado 2 ---------------------------------------------------------
    rompido = mudancas["chamado2"].get("enlace_rompido")
    novo = mudancas["chamado2"].get("novo_tronco")
    if not isinstance(rompido, dict) or not isinstance(novo, dict):
        raise MudancaInvalidaError(
            "chamado2 exige 'enlace_rompido' e 'novo_tronco'"
        )

    def _pontas(item: dict, prefixo: str) -> tuple[str, int, str, int]:
        no_a = _nome(item.get("no_a"), f"{prefixo}.no_a")
        no_b = _nome(item.get("no_b"), f"{prefixo}.no_b")
        if no_a not in switches or no_b not in switches:
            raise MudancaInvalidaError(f"{prefixo}: switch desconhecido")
        if no_a == no_b:
            raise MudancaInvalidaError(f"{prefixo}: as duas pontas são o mesmo switch")
        porta_a = _inteiro(item.get("porta_a"), f"{prefixo}.porta_a")
        porta_b = _inteiro(item.get("porta_b"), f"{prefixo}.porta_b")
        return no_a, porta_a, no_b, porta_b

    no_a, porta_a, no_b, porta_b = _pontas(rompido, "chamado2.enlace_rompido")
    if not _enlace_do_mapa(no_a, porta_a, no_b, porta_b):
        raise MudancaInvalidaError(
            "chamado2: o enlace rompido não existe no mapa L1 base"
        )

    no_c, porta_c, no_d, porta_d = _pontas(novo, "chamado2.novo_tronco")
    if _enlace_do_mapa(no_c, porta_c, no_d, porta_d):
        raise MudancaInvalidaError("chamado2: o novo tronco já existe no mapa L1 base")
    for no_p, porta_p in ((no_c, porta_c), (no_d, porta_d)):
        if porta_p in _portas_do_switch(plano, no_p):
            raise MudancaInvalidaError(
                f"chamado2: porta {porta_p} de {no_p} já está em uso no plano base"
            )
    if (no_c, porta_c) in ((switch, porta),) or (no_d, porta_d) in ((switch, porta),):
        raise MudancaInvalidaError(
            "chamado2: o novo tronco colide com a porta do chamado1"
        )

    # -- Chamado 3 ---------------------------------------------------------
    dados = mudancas["chamado3"]
    host_atual = _nome(dados.get("host_atual"), "chamado3.host_atual")
    if host_atual not in plano["hosts"]:
        raise MudancaInvalidaError(
            f"chamado3: host {host_atual} não existe no plano base"
        )
    base = plano["hosts"][host_atual]
    if dados.get("switch") != base["switch"] or dados.get("porta") != base["porta"]:
        raise MudancaInvalidaError(
            f"chamado3: {host_atual} está em {base['switch']}:{base['porta']} "
            "no plano base"
        )
    if dados.get("vlan_origem") != base["vlan"]:
        raise MudancaInvalidaError(
            f"chamado3: VLAN de origem deveria ser {base['vlan']}"
        )
    _nome(dados.get("novo_nome"), "chamado3.novo_nome")
    destino = _nome(dados.get("vlan_destino"), "chamado3.vlan_destino")
    if destino not in vlans:
        raise MudancaInvalidaError(f"chamado3: VLAN desconhecida {destino!r}")
    if not plano["redes"][destino].get("dhcp"):
        raise MudancaInvalidaError(f"chamado3: VLAN {destino} não possui DHCP")
    residual = _nome(dados.get("vlan_residual"), "chamado3.vlan_residual")
    if residual != base["vlan"]:
        raise MudancaInvalidaError(
            f"chamado3: VLAN residual deveria ser {base['vlan']}"
        )


# ---------------------------------------------------------------------------
# Geração de comandos (funções puras, cobertas por testes unitários)
# ---------------------------------------------------------------------------


def comandos_acesso(estado: dict, porta: int, vlan: str) -> list[str]:
    """Comandos para deixar ``porta`` como acesso ``untagged`` em ``vlan``."""
    return _calcular_portas([{"porta": porta, "vlan": vlan}], [], estado)


def comandos_tronco(estado: dict, porta: int, vlans: list[str]) -> list[str]:
    """Comandos para deixar ``porta`` como tronco ``tagged`` com as VLANs.

    VLANs que já não existem no switch (por exemplo, ``LIAD`` removida do
    ``SW-LSI`` pelo Chamado 3) são ignoradas para manter a operação idempotente.
    """
    ids = estado.get("ids")
    if ids is not None:
        vlans = [vlan for vlan in vlans if vlan in ids]
    return _calcular_portas([], [{"porta": porta, "vlans": list(vlans)}], estado)


def _calcular_portas(acesso: list[dict], troncos: list[dict], estado: dict) -> list[str]:
    return calcular_comandos_portas(acesso, troncos, estado)


def comandos_remover_vlan(estado: dict, vlan: str) -> list[str]:
    """Remove a VLAN de todas as portas e depois a apaga do switch."""
    if vlan not in estado.get("ids", {}):
        return []
    portas: set[int] = {
        porta
        for porta, nome in estado.get("untagged_por_porta", {}).items()
        if nome == vlan
    }
    portas.update(
        porta
        for porta, nomes in estado.get("tagged_por_porta", {}).items()
        if vlan in nomes
    )
    comandos: list[str] = []
    if portas:
        comandos.append(
            f"configure vlan {vlan} delete ports {comprimir_portas(portas)}"
        )
    comandos.append(f"delete vlan {vlan}")
    return comandos


def comandos_desabilitar_porta(porta: int) -> list[str]:
    return [f"disable port {porta}"]


def erros_acesso(estado: dict, porta: int, vlan: str) -> list[str]:
    atual = estado.get("untagged_por_porta", {}).get(porta)
    if atual != vlan:
        return [f"porta {porta}: esperada untagged em {vlan}, encontrada {atual!r}"]
    return []


def erros_tronco(estado: dict, porta: int, vlans: list[str]) -> list[str]:
    erros: list[str] = []
    atual = estado.get("untagged_por_porta", {}).get(porta)
    if atual is not None:
        erros.append(f"porta {porta}: ainda possui VLAN untagged ({atual})")
    presentes = estado.get("tagged_por_porta", {}).get(porta, set())
    ids = estado.get("ids", {})
    faltando = [
        vlan for vlan in vlans if vlan not in presentes and vlan in ids
    ]
    if faltando:
        erros.append(f"porta {porta}: VLANs tagged ausentes: {', '.join(faltando)}")
    return erros


def erros_vlan_ausente(estado: dict, vlan: str) -> list[str]:
    if vlan in estado.get("ids", {}):
        return [f"VLAN {vlan} ainda existe no switch"]
    return []


def ler_admin_porta(conn, porta: int) -> bool:
    """True se a porta está administrativamente habilitada."""
    saida = conn.send_command_timing(
        f"show ports {porta} information detail",
        read_timeout=60,
        last_read=2,
        strip_prompt=False,
        strip_command=False,
    )
    achado = re.search(r"Admin state:\s*(\S+)", saida, re.I)
    if not achado:
        raise ValidacaoMudancaError(
            f"não foi possível ler o estado administrativo da porta {porta}"
        )
    return achado.group(1).lower().startswith("enabled")


# ---------------------------------------------------------------------------
# Contexto e acesso ao GNS3
# ---------------------------------------------------------------------------


@dataclass
class Contexto:
    lab: Project
    config: Configuracao
    inventario: dict
    inventario_path: Path
    credenciais: Credenciais
    plano: dict
    mudancas: dict
    args: argparse.Namespace

    def atualizar_inventario(self) -> None:
        self.lab.get_nodes()
        self.inventario = montar_inventario(self.lab, self.config)
        gravar_inventario(self.inventario_path, self.inventario)


def _no_ou_none(lab: Project, nome: str):
    for no in lab.nodes:
        if no.name == nome:
            return no
    return None


def _exigir_no(lab: Project, nome: str):
    no = _no_ou_none(lab, nome)
    if no is None:
        raise ValidacaoMudancaError(f"nó {nome!r} não encontrado no GNS3")
    return no


def _aguardar_status(no, status: str, timeout: int) -> bool:
    def verificar() -> bool:
        no.get()
        return no.status == status

    return aguardar(timeout, 1.0, verificar)


def _parar_no(no, timeout: int) -> None:
    if no.status != "started":
        return
    try:
        no.stop()
    except JSONDecodeError:  # GNS3 3.x responde 2xx sem corpo
        pass
    if not _aguardar_status(no, "stopped", timeout):
        raise RuntimeError(f"{no.name} não parou em {timeout}s")


def _iniciar_no(no, timeout: int) -> None:
    if no.status != "started":
        try:
            no.start()
        except JSONDecodeError:
            pass
        if not _aguardar_status(no, "started", timeout):
            raise RuntimeError(f"{no.name} não iniciou em {timeout}s")
    if not aguardar(timeout, 1.0, lambda: (no.get(), bool(no.console))[1]):
        raise RuntimeError(f"{no.name} não expôs console em {timeout}s")


def _template_vpcs(ctx: Contexto) -> str:
    """ID do template VPCS válido no controlador (não o embutido no projeto)."""
    template = ctx.lab.connector.get_template(name="VPCS")
    if template and template.get("template_id"):
        return template["template_id"]
    for no in ctx.lab.nodes:
        if no.node_type == "vpcs" and no.template_id:
            return no.template_id
    raise RuntimeError("template VPCS não encontrado no servidor GNS3")


def garantir_no_vpcs(ctx: Contexto, nome: str, timeout: int):
    """Cria o VPCS se ainda não existir. Devolve (nó, criado)."""
    ctx.lab.get_nodes()
    existente = _no_ou_none(ctx.lab, nome)
    if existente is not None:
        print(f"  nó {nome} já existe (idempotente).")
        _iniciar_no(existente, timeout)
        return existente, False

    print(f"  criando VPCS {nome} via API...")
    no = Node(
        project_id=ctx.lab.project_id,
        connector=ctx.lab.connector,
        name=nome,
        node_type="vpcs",
        template_id=_template_vpcs(ctx),
    )
    no.create()
    ctx.lab.get_nodes()
    criado = _exigir_no(ctx.lab, nome)
    return criado, True


def _nome_porta(porta: int | str) -> str:
    return f"Port{porta}" if isinstance(porta, int) else str(porta)


def garantir_porta_switch(ctx: Contexto, nome: str, numero: int, timeout: int) -> None:
    """Expande os adaptadores do switch se ``PortN`` ainda não existir."""
    ctx.lab.get_nodes()
    no = _exigir_no(ctx.lab, nome)
    if any(dados.get("name") == f"Port{numero}" for dados in (no.ports or [])):
        return

    requeridos = numero + 1
    atuais = int((no.properties or {}).get("adapters") or 0)
    print(
        f"  ajustando adaptadores de {nome} de {atuais} para {requeridos} "
        f"para expor Port{numero}..."
    )
    _parar_no(no, timeout)
    properties = dict(no.properties or {})
    properties["adapters"] = max(atuais, requeridos)
    no.update(properties=properties)
    no.get()
    ctx.lab.get_nodes()
    _iniciar_no(_exigir_no(ctx.lab, nome), timeout)
    if not any(
        dados.get("name") == f"Port{numero}"
        for dados in (_exigir_no(ctx.lab, nome).ports or [])
    ):
        raise RuntimeError(f"{nome} não expôs Port{numero} após ajustar adaptadores")


def link_existe(
    ctx: Contexto, no_a: str, porta_a: str, no_b: str, porta_b: str
) -> bool:
    ctx.lab.get_nodes()
    ctx.lab.get_links()
    nos = {no.name: no for no in ctx.lab.nodes}
    try:
        alvo = frozenset(
            (_endpoint(nos[no_a], porta_a), _endpoint(nos[no_b], porta_b))
        )
    except (KeyError, LookupError):
        return False
    return any(_chave_enlace(link) == alvo for link in ctx.lab.links)


def garantir_enlace(
    ctx: Contexto, no_a: str, porta_a: str, no_b: str, porta_b: str
) -> bool:
    """Cria o cabo se ainda não existir. Devolve True se criou."""
    if link_existe(ctx, no_a, porta_a, no_b, porta_b):
        print(f"  cabo {no_a} {porta_a} <-> {no_b} {porta_b} já existe.")
        return False
    print(f"  criando cabo {no_a} {porta_a} <-> {no_b} {porta_b} via API...")
    ctx.lab.create_link(no_a, porta_a, no_b, porta_b)
    ctx.lab.get_links()
    if not link_existe(ctx, no_a, porta_a, no_b, porta_b):
        raise RuntimeError("o GNS3 não confirmou a criação do cabo")
    return True


def renomear_no(ctx: Contexto, atual: str, novo: str) -> bool:
    """Renomeia o nó no GNS3 (parando/iniciando para preservar o console)."""
    ctx.lab.get_nodes()
    if _no_ou_none(ctx.lab, novo) is not None:
        print(f"  nó {novo} já existe (idempotente).")
        return False
    no = _exigir_no(ctx.lab, atual)
    print(f"  renomeando {atual} -> {novo}...")
    _parar_no(no, ctx.args.timeout)
    no.update(name=novo)
    no.get()
    _iniciar_no(no, ctx.args.timeout)
    return True


# ---------------------------------------------------------------------------
# Acesso a switches e hosts
# ---------------------------------------------------------------------------


def estado_switch(ctx: Contexto, nome: str) -> dict:
    conn = conectar(
        nome,
        ctx.inventario[nome],
        ctx.credenciais,
        ctx.args.timeout,
        ctx.args.check_timeout,
        ctx.args.poll,
    )
    try:
        return ler_estado_switch(conn)
    finally:
        conn.disconnect()


def porta_habilitada(ctx: Contexto, nome: str, porta: int) -> bool:
    conn = conectar(
        nome,
        ctx.inventario[nome],
        ctx.credenciais,
        ctx.args.timeout,
        ctx.args.check_timeout,
        ctx.args.poll,
    )
    try:
        return ler_admin_porta(conn, porta)
    finally:
        conn.disconnect()


def aplicar_no_switch(ctx: Contexto, nome: str, construtor) -> list[str]:
    """Lê o estado, calcula o diff, aplica e salva a configuração."""
    conn = conectar(
        nome,
        ctx.inventario[nome],
        ctx.credenciais,
        ctx.args.timeout,
        ctx.args.check_timeout,
        ctx.args.poll,
    )
    try:
        estado = ler_estado_switch(conn)
        comandos = construtor(estado)
        if ctx.args.verbose:
            print("  --- comandos ---")
            for comando in comandos:
                print(f"  {comando}")
        if comandos:
            aplicar_exos(
                conn,
                ["disable clipaging", *comandos, "save configuration"],
            )
        else:
            print("  nenhuma diferença de configuração.")
        return comandos
    finally:
        conn.disconnect()


def desabilitar_porta(ctx: Contexto, nome: str, porta: int) -> bool:
    conn = conectar(
        nome,
        ctx.inventario[nome],
        ctx.credenciais,
        ctx.args.timeout,
        ctx.args.check_timeout,
        ctx.args.poll,
    )
    try:
        if not ler_admin_porta(conn, porta):
            print(f"  porta {porta} de {nome} já está desabilitada.")
            return False
        aplicar_exos(
            conn,
            ["disable clipaging", *comandos_desabilitar_porta(porta), "save configuration"],
        )
        if ler_admin_porta(conn, porta):
            raise ValidacaoMudancaError(
                f"porta {porta} de {nome} continua habilitada após 'disable port'"
            )
        return True
    finally:
        conn.disconnect()


def configurar_host_dhcp(ctx: Contexto, nome: str, vlan: str) -> str:
    conn = conectar(
        nome,
        ctx.inventario[nome],
        ctx.credenciais,
        ctx.args.timeout,
        ctx.args.check_timeout,
        ctx.args.poll,
    )
    try:
        aplicar_vpcs(conn, ["ip dhcp"])
        ip, gateway = aguardar_dhcp(conn, timeout=ctx.args.dhcp_timeout)
        aplicar_vpcs(conn, ["save"])
    finally:
        conn.disconnect()

    rede = ipaddress.ip_network(ctx.plano["redes"][vlan]["rede"], strict=True)
    esperado_gw = str(ctx.plano["redes"][vlan]["gateway"])
    if ipaddress.ip_interface(ip).network != rede:
        raise ValidacaoMudancaError(
            f"{nome}: DHCP entregou {ip}, fora da rede {rede} (VLAN {vlan})"
        )
    if gateway != esperado_gw:
        raise ValidacaoMudancaError(
            f"{nome}: gateway {gateway!r}, esperado {esperado_gw!r}"
        )
    print(f"  {nome}: DHCP entregou {ip} (gw {gateway}).")
    return ip


def ping(ctx: Contexto, origem: str, destino: str) -> bool:
    conn = conectar(
        origem,
        ctx.inventario[origem],
        ctx.credenciais,
        ctx.args.timeout,
        ctx.args.check_timeout,
        ctx.args.poll,
    )
    try:
        saida = conn.send_command_timing(
            f"ping {destino} -c 3",
            read_timeout=120,
            strip_prompt=False,
            strip_command=False,
        )
    finally:
        conn.disconnect()
    resposta = interpretar_ping(destino, saida)
    if ctx.args.verbose and not resposta.respondeu:
        print(saida)
    return resposta.respondeu


def _ip_do_host(ctx: Contexto, nome: str) -> str:
    conn = conectar(
        nome,
        ctx.inventario[nome],
        ctx.credenciais,
        ctx.args.timeout,
        ctx.args.check_timeout,
        ctx.args.poll,
    )
    try:
        ip, _ = ler_ip_vpcs(conn)
    finally:
        conn.disconnect()
    return (ip or "").split("/")[0]


# ---------------------------------------------------------------------------
# Verificações de estado (usadas no --check e após cada chamado)
# ---------------------------------------------------------------------------


def erros_chamado1(ctx: Contexto) -> list[str]:
    dados = ctx.mudancas["chamado1"]["host"]
    erros: list[str] = []
    ctx.lab.get_nodes()
    if _no_ou_none(ctx.lab, dados["nome"]) is None:
        erros.append(f"nó {dados['nome']} não existe no GNS3")
    if not link_existe(ctx, dados["nome"], PORTA_VPCS, dados["switch"], _nome_porta(dados["porta"])):
        erros.append(f"cabo {dados['nome']} <-> {dados['switch']}:Port{dados['porta']} ausente")
    try:
        estado = estado_switch(ctx, dados["switch"])
        erros.extend(erros_acesso(estado, dados["porta"], dados["vlan"]))
    except Exception as exc:  # noqa: BLE001 - vira erro de validação
        erros.append(f"{dados['switch']}: {exc}")
    try:
        ip = _ip_do_host(ctx, dados["nome"])
        rede = ipaddress.ip_network(ctx.plano["redes"][dados["vlan"]]["rede"])
        if not ip or ipaddress.ip_address(ip) not in rede:
            erros.append(f"{dados['nome']}: IP {ip!r} fora da rede {rede}")
    except Exception as exc:  # noqa: BLE001
        erros.append(f"{dados['nome']}: {exc}")
    return erros


def erros_chamado2(ctx: Contexto) -> list[str]:
    dados = ctx.mudancas["chamado2"]
    rompido = dados["enlace_rompido"]
    novo = dados["novo_tronco"]
    vlans = _vlans_do_plano(ctx.plano)
    erros: list[str] = []

    for no, porta in (
        (rompido["no_a"], rompido["porta_a"]),
        (rompido["no_b"], rompido["porta_b"]),
    ):
        try:
            if porta_habilitada(ctx, no, porta):
                erros.append(f"{no}: porta {porta} deveria estar desabilitada")
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{no}: {exc}")

    if not link_existe(
        ctx,
        novo["no_a"],
        _nome_porta(novo["porta_a"]),
        novo["no_b"],
        _nome_porta(novo["porta_b"]),
    ):
        erros.append(
            f"cabo de contingência {novo['no_a']}:Port{novo['porta_a']} <-> "
            f"{novo['no_b']}:Port{novo['porta_b']} ausente"
        )

    for no, porta in (
        (novo["no_a"], novo["porta_a"]),
        (novo["no_b"], novo["porta_b"]),
    ):
        try:
            estado = estado_switch(ctx, no)
            erros.extend(erros_tronco(estado, porta, vlans))
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{no}: {exc}")
    return erros


def erros_chamado3(ctx: Contexto) -> list[str]:
    dados = ctx.mudancas["chamado3"]
    erros: list[str] = []
    ctx.lab.get_nodes()
    if _no_ou_none(ctx.lab, dados["novo_nome"]) is None:
        erros.append(f"nó {dados['novo_nome']} não existe no GNS3")
    if _no_ou_none(ctx.lab, dados["host_atual"]) is not None:
        erros.append(f"nó antigo {dados['host_atual']} ainda existe no GNS3")
    try:
        estado = estado_switch(ctx, dados["switch"])
        erros.extend(erros_acesso(estado, dados["porta"], dados["vlan_destino"]))
        erros.extend(erros_vlan_ausente(estado, dados["vlan_residual"]))
    except Exception as exc:  # noqa: BLE001
        erros.append(f"{dados['switch']}: {exc}")
    try:
        ip = _ip_do_host(ctx, dados["novo_nome"])
        rede = ipaddress.ip_network(ctx.plano["redes"][dados["vlan_destino"]]["rede"])
        if not ip or ipaddress.ip_address(ip) not in rede:
            erros.append(f"{dados['novo_nome']}: IP {ip!r} fora da rede {rede}")
    except Exception as exc:  # noqa: BLE001
        erros.append(f"{dados['novo_nome']}: {exc}")
    return erros


# ---------------------------------------------------------------------------
# Execução dos chamados
# ---------------------------------------------------------------------------


def executar_chamado1(ctx: Contexto) -> None:
    host = ctx.mudancas["chamado1"]["host"]
    switch, porta, vlan = host["switch"], host["porta"], host["vlan"]

    garantir_porta_switch(ctx, switch, porta, ctx.args.timeout)
    garantir_no_vpcs(ctx, host["nome"], ctx.args.timeout)
    garantir_enlace(
        ctx, host["nome"], PORTA_VPCS, switch, _nome_porta(porta)
    )
    _iniciar_no(_exigir_no(ctx.lab, host["nome"]), ctx.args.timeout)
    ctx.atualizar_inventario()

    aplicar_no_switch(
        ctx, switch, lambda estado: comandos_acesso(estado, porta, vlan)
    )
    configurar_host_dhcp(ctx, host["nome"], vlan)


def executar_chamado2(ctx: Contexto) -> None:
    dados = ctx.mudancas["chamado2"]
    rompido = dados["enlace_rompido"]
    novo = dados["novo_tronco"]
    vlans = _vlans_do_plano(ctx.plano)

    for no, porta in (
        (rompido["no_a"], rompido["porta_a"]),
        (rompido["no_b"], rompido["porta_b"]),
    ):
        print(f"  simulando rompimento: disable port {porta} em {no}")
        desabilitar_porta(ctx, no, porta)

    for item in (novo["no_a"], novo["no_b"]):
        porta = novo["porta_a"] if item == novo["no_a"] else novo["porta_b"]
        garantir_porta_switch(ctx, item, porta, ctx.args.timeout)

    garantir_enlace(
        ctx,
        novo["no_a"],
        _nome_porta(novo["porta_a"]),
        novo["no_b"],
        _nome_porta(novo["porta_b"]),
    )

    for no, porta in (
        (novo["no_a"], novo["porta_a"]),
        (novo["no_b"], novo["porta_b"]),
    ):
        aplicar_no_switch(
            ctx, no, lambda estado, p=porta: comandos_tronco(estado, p, vlans)
        )

    # Validação funcional do desvio: o LIAD deve sair pelo LSI.
    # Se o Chamado 3 já removeu a VLAN LIAD do SW-LSI, a validação L3 do LIAD
    # não se aplica (o próprio Chamado 3 documenta essa perda).
    estado_lsi = estado_switch(ctx, novo["no_a"])
    if "LIAD" in estado_lsi.get("ids", {}):
        configurar_host_dhcp(ctx, "PC-LIAD", "LIAD")
        gateway_liad = str(ctx.plano["redes"]["LIAD"]["gateway"])
        if not ping(ctx, "PC-LIAD", gateway_liad):
            raise ValidacaoMudancaError(
                f"PC-LIAD não alcança o gateway {gateway_liad} pelo desvio"
            )
        print(f"  PC-LIAD alcança o gateway {gateway_liad} pelo desvio.")
    else:
        print(
            "  AVISO: VLAN LIAD ausente do SW-LSI (Chamado 3 já aplicado); "
            "validação L3 do PC-LIAD pelo desvio foi pulada."
        )
    nvr = ctx.plano["hosts"]["NVR"]["ip"].split("/")[0]
    if not ping(ctx, "CAM", nvr):
        raise ValidacaoMudancaError(f"CAM não alcança o NVR ({nvr}) pelo desvio")
    print(f"  CAM alcança o NVR ({nvr}) pelo desvio.")


def executar_chamado3(ctx: Contexto) -> None:
    dados = ctx.mudancas["chamado3"]

    renomear_no(ctx, dados["host_atual"], dados["novo_nome"])
    ctx.atualizar_inventario()

    aplicar_no_switch(
        ctx,
        dados["switch"],
        lambda estado: comandos_acesso(estado, dados["porta"], dados["vlan_destino"]),
    )
    aplicar_no_switch(
        ctx,
        dados["switch"],
        lambda estado: comandos_remover_vlan(estado, dados["vlan_residual"]),
    )

    configurar_host_dhcp(ctx, dados["novo_nome"], dados["vlan_destino"])

    alvo = _ip_do_host(ctx, "PC-LSI")
    if not alvo:
        raise ValidacaoMudancaError("PC-LSI não possui IP para o teste de ping")
    if not ping(ctx, dados["novo_nome"], alvo):
        raise ValidacaoMudancaError(f"{dados['novo_nome']} não alcança PC-LSI ({alvo})")
    print(f"  {dados['novo_nome']} alcança PC-LSI ({alvo}).")

    print(
        "  AVISO: VLAN LIAD removida do SW-LSI conforme o plano. Enquanto o "
        "enlace SW-LACINA-SW-LIAD estiver desabilitado, o PC-LIAD perde "
        "conectividade L3 (o VLAN LIAD não é mais transportada pelo SW-LSI)."
    )


EXECUTORES = {
    "chamado1": executar_chamado1,
    "chamado2": executar_chamado2,
    "chamado3": executar_chamado3,
}

VERIFICACOES = {
    "chamado1": erros_chamado1,
    "chamado2": erros_chamado2,
    "chamado3": erros_chamado3,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "chamado",
        nargs="?",
        default="todos",
        choices=[*CHAMADOS, "todos"],
        help="Chamado a executar (padrão: todos, na ordem sequencial)",
    )
    parser.add_argument(
        "--plano",
        type=Path,
        default=PLANO_PADRAO,
        help="Plano de rede base (padrão: infra/config/plano_rede.json)",
    )
    parser.add_argument(
        "--plano-mudancas",
        type=Path,
        default=PLANO_MUDANCAS_PADRAO,
        help="Plano de mudanças (padrão: infra/config/plano_mudancas.json)",
    )
    parser.add_argument(
        "--inventario",
        type=Path,
        default=INVENTARIO_PADRAO,
        help="Inventário de consoles (padrão: inventario_gns3.json)",
    )
    parser.add_argument("--server", help="URL da API do GNS3 (sobrepõe GNS3_SERVER_URL)")
    parser.add_argument("--project", help="Nome do projeto (sobrepõe GNS3_PROJECT_NAME)")
    parser.add_argument(
        "--console-host",
        help="Host das portas de console (sobrepõe GNS3_CONSOLE_HOST)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Apenas valida o estado final, sem alterar o laboratório",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Imprime os comandos e as saídas de ping que falharem",
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
    parser.add_argument(
        "--dhcp-timeout",
        type=int,
        default=90,
        help="Espera máxima, em segundos, pelo DHCP de cada host (padrão: 90)",
    )
    return parser.parse_args()


def _conectar_gns3(args: argparse.Namespace):
    config = carregar_configuracao(args)
    if not config.access_token:
        raise RuntimeError(
            "GNS3_ACCESS_TOKEN não configurado. Preencha a variável no .env."
        )
    connector = criar_conector(config)
    verificar_token(connector)
    lab = localizar_projeto(connector, config.project_name)
    return config, lab


def main() -> int:
    load_dotenv(RAIZ / ".env")
    args = parse_args()

    try:
        plano = carregar_json(args.plano, "plano de rede")
        mudancas = carregar_json(args.plano_mudancas, "plano de mudanças")
        validar_plano(plano)
        validar_plano_mudancas(mudancas, plano)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    acoes = list(CHAMADOS) if args.chamado == "todos" else [args.chamado]

    try:
        config, lab = _conectar_gns3(args)
        inventario = carregar_json(args.inventario, "inventário de consoles")
    except (FileNotFoundError, ValueError, RuntimeError, LookupError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    ctx = Contexto(
        lab=lab,
        config=config,
        inventario=inventario,
        inventario_path=args.inventario,
        credenciais=carregar_credenciais(),
        plano=plano,
        mudancas=mudancas,
        args=args,
    )

    if args.check:
        print("Modo --check: nenhuma alteração será feita.")
        falhas = 0
        for acao in acoes:
            print(f"\n=== {TITULOS[acao]} ===")
            try:
                erros = VERIFICACOES[acao](ctx)
            except Exception as exc:  # noqa: BLE001
                erros = [f"{type(exc).__name__}: {exc}"]
            if erros:
                falhas += 1
                for erro in erros:
                    print(f"  ERRO: {erro}", file=sys.stderr)
            else:
                print("  OK: estado conforme o plano de mudanças.")
        return 1 if falhas else 0

    falhas: list[str] = []
    for acao in acoes:
        print(f"\n=== {TITULOS[acao]} ===", flush=True)
        try:
            EXECUTORES[acao](ctx)
            erros = VERIFICACOES[acao](ctx)
            if erros:
                raise ValidacaoMudancaError("\n  - " + "\n  - ".join(erros))
            print("  OK: mudança aplicada e validada.")
        except Exception as exc:  # noqa: BLE001 - continua apenas se independente
            print(f"  ERRO: {exc}", file=sys.stderr)
            falhas.append(acao)
            if args.chamado == "todos":
                print(
                    "  Interrompendo: os chamados são sequenciais.",
                    file=sys.stderr,
                )
                break

    if falhas:
        print(f"\nFalha em: {', '.join(falhas)}", file=sys.stderr)
        return 1

    print(f"\nMilestone 5 concluído: {', '.join(acoes)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
