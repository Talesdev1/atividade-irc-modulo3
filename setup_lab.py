#!/usr/bin/env python3
"""Localiza o projeto GNS3 existente e exporta o inventário de consoles.

A topologia base já deve ter sido importada no GNS3
(base_topology/uasc.gns3project): este script não cria nós nem links.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from gns3fy import Gns3Connector, Project

RAIZ = Path(__file__).resolve().parent
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
        "--check",
        action="store_true",
        help="Apenas valida a conexão e o projeto, sem abrir, iniciar ou exportar",
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


def aguardar(timeout: int, poll: float, verificador) -> bool:
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if verificador():
            return True
        time.sleep(poll)
    return verificador()


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
        f"status={lab.status}, nós={len(lab.nodes)}"
    )

    if args.check:
        for node in sorted(lab.nodes, key=lambda n: n.name):
            print(
                f"  {node.name:16} type={node.node_type or '-':6} "
                f"status={node.status or '-':8} console={node.console or '-'}"
            )
        return 0

    if lab.status != "opened":
        print("Abrindo o projeto...")
        lab.open()

        def aberto() -> bool:
            lab.get()
            return lab.status == "opened"

        if not aguardar(args.timeout, 1.0, aberto):
            print(
                f"ERRO: o projeto não abriu em {args.timeout}s.",
                file=sys.stderr,
            )
            return 1

    pendentes = [node for node in lab.nodes if node.status != "started"]
    if args.no_start:
        print("--no-start informado: os nós não serão iniciados.")
    elif not pendentes:
        print("Todos os nós já estão iniciados.")
    else:
        print(f"Iniciando {len(pendentes)} nó(s)...")
        for node in pendentes:
            try:
                node.start()
            except Exception as exc:
                print(
                    f"AVISO: falha ao iniciar {node.name}: {exc}",
                    file=sys.stderr,
                )

        def iniciados() -> bool:
            lab.get_nodes()
            return all(node.status == "started" for node in lab.nodes)

        if not aguardar(args.timeout, 2.0, iniciados):
            print(
                "AVISO: alguns nós não chegaram ao estado 'started' "
                f"dentro de {args.timeout}s.",
                file=sys.stderr,
            )

    def consoles_prontos() -> bool:
        lab.get_nodes()
        return all(node.console for node in lab.nodes)

    aguardar(args.timeout, 1.0, consoles_prontos)

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

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporario = args.output.with_name(args.output.name + ".tmp")
    temporario.write_text(
        json.dumps(inventario, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporario.replace(args.output)

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
