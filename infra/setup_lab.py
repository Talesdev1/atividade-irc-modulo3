#!/usr/bin/env python3
"""Orquestra a topologia base do GNS3 e exporta o inventário de consoles.

A topologia base já deve ter sido importada no GNS3
(base_topology/*.gns3project): este script não cria nós. Ele localiza o
projeto ativo, garante o cabeamento L1 inicial (acessos dos VPCS e troncos
802.1Q definidos em ``infra/topologia.py``), valida a topologia, inicia todos
os nós de uma só vez via API e exporta as portas de console alocadas pelo
GNS3 para ``inventario_gns3.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from gns3fy import Gns3Connector, Project
from requests.exceptions import JSONDecodeError

try:  # import relativo quando chamado pelo atalho da raiz
    from .topologia import (
        ENLACES_INICIAIS,
        Enlace,
        adaptadores_necessarios,
    )
except ImportError:  # execução direta: python infra/setup_lab.py
    from topologia import (  # type: ignore[no-redef]
        ENLACES_INICIAIS,
        Enlace,
        adaptadores_necessarios,
    )

RAIZ = Path(__file__).resolve().parents[1]
BASE_TOPOLOGY_PADRAO = RAIZ / "base_topology"
INVENTARIO_PADRAO = RAIZ / "inventario_gns3.json"
HTTP_TIMEOUT = 10

# Driver Netmiko adequado ao tipo de nó exposto pelo GNS3.
DEVICE_TYPES = {
    "qemu": "extreme_exos_telnet",
    "vpcs": "generic_telnet",
}


class TokenInvalidoError(RuntimeError):
    """Token recusado pelo servidor GNS3."""


@dataclass(frozen=True)
class Configuracao:
    server_url: str
    project_name: str
    console_host: str
    access_token: str
    api_version: int


@dataclass(frozen=True)
class TopologiaBase:
    """Resumo do ``project.gns3`` embutido no arquivo portátil."""

    caminho: Path
    nodes: dict[str, str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", help="URL da API do GNS3 (sobrepõe GNS3_SERVER_URL)")
    parser.add_argument("--project", help="Nome do projeto (sobrepõe GNS3_PROJECT_NAME)")
    parser.add_argument(
        "--console-host",
        help="Host das portas de console (sobrepõe GNS3_CONSOLE_HOST)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=INVENTARIO_PADRAO,
        help="Arquivo JSON de saída (padrão: inventario_gns3.json na raiz)",
    )
    parser.add_argument(
        "--base-topology",
        type=Path,
        help="Arquivo .gns3project ou diretório base (padrão: base_topology/)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Apenas valida a conexão e o projeto, sem abrir, iniciar ou exportar",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Compara os nós com o .gns3project base e o cabeamento com o mapa padrão",
    )
    parser.add_argument(
        "--no-links",
        action="store_true",
        help="Não cria/ajusta o cabeamento L1 inicial (útil em mudanças posteriores)",
    )
    parser.add_argument("--no-start", action="store_true", help="Não inicia os nós")
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Espera máxima, em segundos, por abrir/iniciar (padrão: 60)",
    )
    return parser.parse_args()


def carregar_configuracao(args: argparse.Namespace) -> Configuracao:
    """Resolve configuração por CLI > variáveis de ambiente > .env > padrão."""
    load_dotenv(RAIZ / ".env")

    server_url = args.server or os.getenv("GNS3_SERVER_URL", "http://localhost:3080")
    project_name = args.project or os.getenv("GNS3_PROJECT_NAME", "uasc")
    console_host = args.console_host or os.getenv("GNS3_CONSOLE_HOST")
    if not console_host:
        console_host = urlparse(server_url).hostname or "127.0.0.1"

    api_version_texto = os.getenv("GNS3_API_VERSION", "3").strip()
    try:
        api_version = int(api_version_texto)
    except ValueError as exc:
        raise ValueError(
            f"GNS3_API_VERSION inválida: {api_version_texto!r} (esperado inteiro)"
        ) from exc

    return Configuracao(
        server_url=server_url,
        project_name=project_name,
        console_host=console_host,
        access_token=os.getenv("GNS3_ACCESS_TOKEN", "").strip(),
        api_version=api_version,
    )


def criar_conector(config: Configuracao) -> Gns3Connector:
    """Cria o conector já autenticado: o token vai em todas as chamadas."""
    connector = Gns3Connector(
        url=config.server_url,
        api_version=config.api_version,
    )
    connector.session.headers["Authorization"] = f"Bearer {config.access_token}"
    return connector


def verificar_token(connector: Gns3Connector) -> None:
    """Falha cedo e com mensagem clara se o token estiver inválido/expirado."""
    resposta = connector.session.get(
        f"{connector.base_url}/projects",
        timeout=HTTP_TIMEOUT,
    )
    if resposta.status_code == 401:
        raise TokenInvalidoError(
            "token recusado pelo servidor GNS3 (HTTP 401). "
            "Atualize GNS3_ACCESS_TOKEN no .env."
        )
    if not resposta.ok:
        raise RuntimeError(f"HTTP {resposta.status_code}: {resposta.text[:200]}")


def localizar_projeto(connector: Gns3Connector, project_name: str) -> Project:
    dados = connector.get_project(name=project_name)
    if not dados:
        raise LookupError(project_name)

    lab = Project(project_id=dados["project_id"], connector=connector)
    lab.get()
    return lab


def localizar_base_topology(caminho: Path | None) -> Path:
    """Aceita um arquivo .gns3project ou um diretório contendo um único arquivo."""
    candidato = caminho or BASE_TOPOLOGY_PADRAO
    if candidato.is_file():
        return candidato
    if not candidato.is_dir():
        raise FileNotFoundError(f"topologia base não encontrada: {candidato}")

    arquivos = sorted(candidato.glob("*.gns3project"))
    if not arquivos:
        raise FileNotFoundError(
            f"nenhum arquivo .gns3project encontrado em {candidato}"
        )
    if len(arquivos) > 1:
        nomes = ", ".join(arquivo.name for arquivo in arquivos)
        raise RuntimeError(
            f"mais de um .gns3project em {candidato}: {nomes}. "
            "Use --base-topology para escolher um."
        )
    return arquivos[0]


def ler_topologia_base(caminho: Path) -> TopologiaBase:
    """Lê nome e tipo dos nós do arquivo portátil."""
    try:
        with zipfile.ZipFile(caminho) as arquivo:
            dados = json.loads(arquivo.read("project.gns3"))
    except KeyError as exc:
        raise ValueError(f"{caminho} não contém project.gns3") from exc
    except zipfile.BadZipFile as exc:
        raise ValueError(f"{caminho} não é um .gns3project válido") from exc

    nodes = {
        node["name"]: node.get("node_type", "")
        for node in dados.get("topology", {}).get("nodes", [])
    }
    return TopologiaBase(caminho=caminho, nodes=nodes)


def validar_topologia(lab: Project, base: TopologiaBase) -> bool:
    """Compara os nós do projeto em execução com a topologia base."""
    atuais = {node.name: node.node_type for node in lab.nodes}
    problemas: list[str] = []

    ausentes = sorted(set(base.nodes) - set(atuais))
    extras = sorted(set(atuais) - set(base.nodes))
    if ausentes:
        problemas.append(f"nós ausentes no GNS3: {', '.join(ausentes)}")
    if extras:
        problemas.append(f"nós extras no GNS3: {', '.join(extras)}")

    for nome in sorted(set(base.nodes) & set(atuais)):
        if base.nodes[nome] != atuais[nome]:
            problemas.append(
                f"tipo divergente em {nome}: "
                f"base={base.nodes[nome]!r}, GNS3={atuais[nome]!r}"
            )

    print(
        f"Validação dos nós: base={base.caminho.name} "
        f"({len(base.nodes)} nó(s)) x GNS3 ({len(atuais)} nó(s))"
    )
    if problemas:
        for problema in problemas:
            print(f"  ERRO: {problema}", file=sys.stderr)
        return False
    print("  OK: os nós do GNS3 correspondem ao arquivo base.")
    return True


def _endpoint(node, porta: str) -> tuple[str, int, int]:
    """Resolve ``PortN``/``Ethernet0`` para (node_id, adapter, port)."""
    for dados in node.ports or []:
        if dados.get("name") == porta:
            return (
                node.node_id,
                int(dados["adapter_number"]),
                int(dados["port_number"]),
            )
    disponiveis = ", ".join(
        dados.get("name", "?") for dados in (node.ports or [])
    )
    raise LookupError(
        f"{node.name} não possui a porta {porta!r} "
        f"(disponíveis: {disponiveis or 'nenhuma'})"
    )


def _chave_enlace(link) -> frozenset[tuple[str, int, int]]:
    """Identifica um link pelos seus dois endpoints, independente da ordem."""
    return frozenset(
        (
            endpoint.get("node_id"),
            int(endpoint.get("adapter_number", -1)),
            int(endpoint.get("port_number", -1)),
        )
        for endpoint in (link.nodes or [])
    )


def _mapa_esperado(
    lab: Project,
) -> tuple[dict[frozenset[tuple[str, int, int]], Enlace], list[str]]:
    nos = {node.name: node for node in lab.nodes}
    esperados: dict[frozenset[tuple[str, int, int]], Enlace] = {}
    problemas: list[str] = []

    for enlace in ENLACES_INICIAIS:
        try:
            endpoint_a = _endpoint(nos[enlace.no_a], enlace.porta_a)
            endpoint_b = _endpoint(nos[enlace.no_b], enlace.porta_b)
        except KeyError as exc:
            problemas.append(f"nó do mapa não encontrado no GNS3: {exc}")
            continue
        except LookupError as exc:
            problemas.append(str(exc))
            continue
        esperados[frozenset((endpoint_a, endpoint_b))] = enlace

    return esperados, problemas


def validar_enlaces(lab: Project) -> bool:
    """Confere se todos os cabos do mapa padrão existem no projeto."""
    lab.get_nodes()
    lab.get_links()

    esperados, problemas = _mapa_esperado(lab)
    atuais = {_chave_enlace(link) for link in lab.links}
    faltando = [
        enlace for chave, enlace in esperados.items() if chave not in atuais
    ]
    extras = atuais - set(esperados)

    print(
        f"Validação do cabeamento: mapa={len(esperados)} enlace(s) x "
        f"GNS3={len(atuais)} enlace(s)"
    )
    if problemas:
        for problema in problemas:
            print(f"  ERRO: {problema}", file=sys.stderr)
    for enlace in faltando:
        print(f"  ERRO: enlace ausente: {enlace.descricao}", file=sys.stderr)
    if extras:
        print(
            f"  ERRO: {len(extras)} enlace(s) fora do mapa padrão no GNS3",
            file=sys.stderr,
        )
    if problemas or faltando or extras:
        return False
    print("  OK: o cabeamento do GNS3 corresponde ao mapa padrão.")
    return True


def validar_estado(lab: Project, base_path: Path | None) -> bool:
    """Valida os nós contra o arquivo base e os cabos contra o mapa padrão."""
    try:
        base = ler_topologia_base(localizar_base_topology(base_path))
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return False

    nos_ok = validar_topologia(lab, base)
    enlaces_ok = validar_enlaces(lab)
    return nos_ok and enlaces_ok


def aguardar(timeout: int, poll: float, verificador) -> bool:
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if verificador():
            return True
        time.sleep(poll)
    return verificador()


def abrir_projeto(lab: Project, timeout: int) -> bool:
    if lab.status == "opened":
        return True

    print("Abrindo o projeto...")
    lab.open()

    def aberto() -> bool:
        lab.get()
        return lab.status == "opened"

    return aguardar(timeout, 1.0, aberto)


def _no_por_nome(lab: Project, nome: str):
    for node in lab.nodes:
        if node.name == nome:
            return node
    raise LookupError(f"nó {nome!r} não encontrado no projeto GNS3")


def _parar_no(node) -> None:
    """Para um nó tolerando a resposta 2xx sem corpo do GNS3 3.x.

    O ``gns3fy 0.8.0`` tenta decodificar JSON nessa resposta e levanta
    ``JSONDecodeError`` mesmo quando o stop foi aceito pelo servidor.
    """
    try:
        node.stop()
    except JSONDecodeError:
        pass


def _portas_do_mapa(nome: str) -> set[str]:
    portas: set[str] = set()
    for enlace in ENLACES_INICIAIS:
        if enlace.no_a == nome:
            portas.add(enlace.porta_a)
        if enlace.no_b == nome:
            portas.add(enlace.porta_b)
    return portas


def garantir_adaptadores(lab: Project, timeout: int) -> None:
    """Expande os switches para que as portas dos troncos existam no GNS3."""
    for nome, requeridos in sorted(adaptadores_necessarios().items()):
        lab.get_nodes()
        node = _no_por_nome(lab, nome)
        atuais = int((node.properties or {}).get("adapters") or 0)
        if atuais >= requeridos:
            continue

        print(
            f"Cabeamento: ajustando {nome} de {atuais} para "
            f"{requeridos} adaptadores..."
        )
        if node.status == "started":
            print(f"  Parando {nome} para aplicar a mudança...")
            _parar_no(node)

            def parado(node=node) -> bool:
                node.get()
                return node.status == "stopped"

            if not aguardar(timeout, 1.0, parado):
                raise RuntimeError(
                    f"{nome} não parou dentro de {timeout}s "
                    "para ajustar os adaptadores."
                )

        properties = dict(node.properties or {})
        properties["adapters"] = requeridos
        node.update(properties=properties)
        node.get()

        portas = {dados.get("name") for dados in (node.ports or [])}
        faltantes = sorted(_portas_do_mapa(nome) - portas)
        if faltantes:
            raise RuntimeError(
                f"{nome} não expôs a(s) porta(s) {', '.join(faltantes)} "
                "após o ajuste de adaptadores."
            )
        print(f"  {nome} agora expõe {len(portas)} porta(s).")

    lab.get_nodes()


def garantir_enlaces(lab: Project) -> None:
    """Cria, de forma idempotente, os cabos L1 que ainda não existem."""
    lab.get_nodes()
    lab.get_links()

    esperados, problemas = _mapa_esperado(lab)
    if problemas:
        raise RuntimeError("; ".join(problemas))

    existentes = {_chave_enlace(link) for link in lab.links}
    usados: dict[tuple[str, int, int], object] = {}
    for link in lab.links:
        for endpoint in _chave_enlace(link):
            usados[endpoint] = link

    criados = 0
    conflitos = 0
    for chave, enlace in esperados.items():
        if chave in existentes:
            continue

        if any(endpoint in usados for endpoint in chave):
            print(
                f"AVISO: porta já ocupada por outro link; não criado: "
                f"{enlace.descricao}",
                file=sys.stderr,
            )
            conflitos += 1
            continue

        print(f"Criando enlace {enlace.descricao}...")
        lab.create_link(
            enlace.no_a,
            enlace.porta_a,
            enlace.no_b,
            enlace.porta_b,
        )
        novo_link = lab.links[-1] if lab.links else None
        existentes.add(chave)
        for endpoint in chave:
            usados[endpoint] = novo_link
        criados += 1

    lab.get_links()
    if criados:
        print(f"{criados} enlace(s) criado(s) a partir do mapa padrão.")
    elif not conflitos:
        print("Cabeamento inicial já está completo.")
    if conflitos:
        raise RuntimeError(
            f"{conflitos} enlace(s) do mapa não foram criados por conflito "
            "de porta; use --no-links se a topologia foi alterada de propósito."
        )


def iniciar_nos(lab: Project, timeout: int) -> None:
    """Dispara o start de todos os nós em uma única chamada à API."""
    pendentes = [node for node in lab.nodes if node.status != "started"]
    if not pendentes:
        print("Todos os nós já estão iniciados.")
        return

    print(f"Iniciando {len(pendentes)} nó(s) simultaneamente via API...")
    try:
        lab.start_nodes(poll_wait_time=5)
    except Exception as exc:
        print(
            f"AVISO: falha ao iniciar os nós: {exc}. "
            "Verifique o servidor GNS3.",
            file=sys.stderr,
        )

    def iniciados() -> bool:
        lab.get_nodes()
        return all(node.status == "started" for node in lab.nodes)

    if not aguardar(timeout, 2.0, iniciados):
        print(
            "AVISO: alguns nós não chegaram ao estado 'started' "
            f"dentro de {timeout}s.",
            file=sys.stderr,
        )


def aguardar_consoles(lab: Project, timeout: int) -> None:
    """Aguarda o GNS3 alocar uma porta de console para cada nó."""
    print("Aguardando a alocação das portas de console...")

    def consoles_prontos() -> bool:
        lab.get_nodes()
        return all(node.console for node in lab.nodes)

    if not aguardar(timeout, 1.0, consoles_prontos):
        print(
            "AVISO: nem todos os nós expuseram porta de console "
            f"dentro de {timeout}s.",
            file=sys.stderr,
        )


def montar_inventario(lab: Project, config: Configuracao) -> dict[str, dict]:
    inventario: dict[str, dict] = {}
    for node in sorted(lab.nodes, key=lambda n: n.name):
        if not node.console:
            print(
                f"AVISO: {node.name} não expõe porta de console; ignorado.",
                file=sys.stderr,
            )
            continue
        inventario[node.name] = {
            "node_id": node.node_id,
            "node_type": node.node_type,
            "console_type": node.console_type,
            "device_type": DEVICE_TYPES.get(node.node_type),
            "host": config.console_host,
            "port": node.console,
            "status": node.status,
        }
    return inventario


def gravar_inventario(caminho: Path, inventario: dict[str, dict]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(caminho.name + ".tmp")
    temporario.write_text(
        json.dumps(inventario, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporario.replace(caminho)


def main() -> int:
    args = parse_args()
    try:
        config = carregar_configuracao(args)
    except ValueError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    if not config.access_token:
        print(
            "ERRO: GNS3_ACCESS_TOKEN não configurado. "
            "Preencha a variável no .env (veja .env.example).",
            file=sys.stderr,
        )
        return 1

    print(
        f"Conectando ao GNS3 em {config.server_url} "
        f"(projeto '{config.project_name}', API v{config.api_version})...",
        flush=True,
    )
    try:
        connector = criar_conector(config)
        verificar_token(connector)
        lab = localizar_projeto(connector, config.project_name)
    except TokenInvalidoError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    except LookupError:
        print(
            f"ERRO: projeto '{config.project_name}' não encontrado no servidor "
            f"{config.server_url}.",
            file=sys.stderr,
        )
        print(
            "Importe base_topology/uasc.gns3project no GNS3 "
            "(File > Import portable project) e tente novamente.",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(
            f"ERRO: não foi possível falar com a API do GNS3 em "
            f"{config.server_url}: {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        f"Projeto encontrado: {lab.name} (ID {lab.project_id}), "
        f"status={lab.status}, nós={len(lab.nodes)}, links={len(lab.links)}"
    )

    if args.check:
        if args.validate and not validar_estado(lab, args.base_topology):
            return 1
        for node in sorted(lab.nodes, key=lambda n: n.name):
            print(
                f"  {node.name:16} type={node.node_type or '-':6} "
                f"status={node.status or '-':8} console={node.console or '-'}"
            )
        return 0

    if not abrir_projeto(lab, args.timeout):
        print(
            f"ERRO: o projeto não abriu em {args.timeout}s.",
            file=sys.stderr,
        )
        return 1

    if args.no_links:
        print("--no-links informado: o cabeamento L1 não será alterado.")
    else:
        try:
            garantir_adaptadores(lab, args.timeout)
            garantir_enlaces(lab)
        except Exception as exc:
            print(f"ERRO: falha ao garantir o cabeamento L1: {exc}", file=sys.stderr)
            return 1

    if args.validate and not validar_estado(lab, args.base_topology):
        return 1

    if args.no_start:
        print("--no-start informado: os nós não serão iniciados.")
    else:
        iniciar_nos(lab, args.timeout)

    aguardar_consoles(lab, args.timeout)
    inventario = montar_inventario(lab, config)
    gravar_inventario(args.output, inventario)

    print("\n--- Inventário de consoles ---")
    for nome, dados in inventario.items():
        print(
            f"{nome:16} {dados['node_type'] or '-':6} "
            f"{dados['status'] or '-':8} {dados['console_type'] or '-':7} "
            f"{dados['host']}:{dados['port']}"
        )
    print(f"\nInventário salvo em '{args.output}' ({len(inventario)} nó(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
