#!/usr/bin/env python3
"""Executa os 6 testes de aceite do STI/UFCG nos VPCS via console.

Os testes consomem o inventário dinâmico gerado pelo Milestone 2
(``inventario_gns3.json``) e o plano declarativo
(``infra/config/plano_rede.json``). Nenhuma porta de console é hardcoded.

1. DHCP: ``ip dhcp`` e conferência de sub-rede, máscara e gateway.
2. Conectividade: cada host alcança o gateway da sua VLAN.
3. Malha completa: todos os hosts roteáveis se alcançam entre si (pares
   inter-VLAN e intra-VLAN), excluindo a VLAN ``Cameras``.
4. CFTV: ``CAM`` alcança o ``NVR`` em Camada 2 (VLAN 60, sem gateway).
5. Isolamento: nenhum laboratório alcança ``CAM``/``NVR``.
6. Soberania da VLAN: trocar o IP do ``PC-LACINA`` para a faixa do LSD não
   burla o isolamento L2, portanto o ping DEVE falhar; ao final o host é
   restaurado via DHCP.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:  # import relativo quando chamado como pacote
    from .provisionar import (
        aguardar_dhcp,
        carregar_credenciais,
        carregar_json,
        conectar,
        garantir_inventario,
        ler_ip_vpcs,
        validar_plano,
    )
except ImportError:  # execução direta: python infra/testes_aceite.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from provisionar import (  # type: ignore[no-redef]
        aguardar_dhcp,
        carregar_credenciais,
        carregar_json,
        conectar,
        garantir_inventario,
        ler_ip_vpcs,
        validar_plano,
    )

RAIZ = Path(__file__).resolve().parents[1]
INVENTARIO_PADRAO = RAIZ / "inventario_gns3.json"
PLANO_PADRAO = RAIZ / "infra" / "config" / "plano_rede.json"

#: IP temporário do Teste 6: pertence à sub-rede do LSD (172.20.1.128/25),
#: mas o PC-LACINA está fisicamente na VLAN LACINA.
IP_TESTE6 = "172.20.1.250/25"

ORIGEM_INTER_VLAN = "PC-LACINA"
ORIGENS_ISOLAMENTO = ("PC-LACINA", "PC-LSD")
HOSTS_CFTV = ("CAM", "NVR")

TITULOS = {
    1: "Endereçamento via DHCP",
    2: "Conectividade com o gateway",
    3: "Conectividade entre todos os nós",
    4: "CFTV: CAM -> NVR",
    5: "Isolamento da rede de câmeras",
    6: "Soberania da VLAN L2 (Teste 6)",
}

LINHA_SUCESSO = re.compile(r"^84 bytes from (?P<ip>\S+) icmp_seq=", re.MULTILINE)
SINAIS_FALHA = (
    "timeout",
    "unreachable",
    "not reachable",
    "no route to host",
    "destination net",
)


class SelecaoInvalidaError(ValueError):
    """Os testes pedidos em --only não existem."""


@dataclass(frozen=True)
class RespostaPing:
    respondeu: bool
    motivo: str
    saida: str = ""


@dataclass
class Resultado:
    numero: int
    titulo: str
    ok: bool
    falhas: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing e seleção (funções puras, cobertas por testes unitários)
# ---------------------------------------------------------------------------


def interpretar_ping(destino: str, saida: str) -> RespostaPing:
    """Decide se o ICMP foi respondido a partir do texto do console VPCS."""
    for achado in LINHA_SUCESSO.finditer(saida):
        if achado.group("ip").split("%")[0] == destino:
            return RespostaPing(True, "resposta ICMP recebida", saida)

    linhas = [linha.strip() for linha in saida.splitlines() if linha.strip()]
    for linha in linhas:
        minuscula = linha.lower()
        if any(sinal in minuscula for sinal in SINAIS_FALHA):
            return RespostaPing(False, linha, saida)
    return RespostaPing(False, "sem resposta conclusiva do VPCS", saida)


def selecionar_testes(args: argparse.Namespace) -> list[int]:
    if not args.only:
        return sorted(TITULOS)
    desejados: set[int] = set()
    for bruto in args.only.split(","):
        bruto = bruto.strip()
        if not bruto:
            continue
        try:
            numero = int(bruto)
        except ValueError as exc:
            raise SelecaoInvalidaError(f"teste inválido em --only: {bruto!r}") from exc
        if numero not in TITULOS:
            raise SelecaoInvalidaError(
                f"teste {numero} não existe (válidos: 1-{len(TITULOS)})"
            )
        desejados.add(numero)
    if not desejados:
        raise SelecaoInvalidaError("--only não selecionou nenhum teste")
    return sorted(desejados)


def gateway_esperado(plano: dict, host: dict) -> str | None:
    """Gateway configurado no host: fixo no plano ou o da VLAN (DHCP)."""
    if host["modo"] == "estatico":
        return host.get("gateway")
    return plano["redes"][host["vlan"]].get("gateway")


def hosts_comunicaveis(plano: dict) -> list[str]:
    """Hosts que participam da malha de comunicação: todos os que têm gateway.

    A VLAN ``Cameras`` não possui gateway por projeto (isolamento CFTV), então
    ``CAM``/``NVR`` ficam de fora automaticamente. Inclui os hosts estáticos
    roteados (ex.: ``ADM`` na VLAN Gerencia) além dos dinâmicos.
    """
    return [
        nome
        for nome, host in plano["hosts"].items()
        if gateway_esperado(plano, host) is not None
    ]


def pares_completos(plano: dict) -> list[tuple[str, str]]:
    """Todos os pares (origem, destino) da malha, sem repetir a ordem inversa.

    Um ICMP echo bem-sucedido exige ida e volta, então cada par é validado
    uma única vez. Pares na mesma VLAN (ex.: LIAD entre switches via tronco)
    também entram na malha.
    """
    hosts = hosts_comunicaveis(plano)
    return [
        (hosts[i], hosts[j])
        for i in range(len(hosts))
        for j in range(i + 1, len(hosts))
    ]


def pares_inter_vlan(plano: dict) -> list[tuple[str, str]]:
    """Subconjunto de ``pares_completos`` com hosts em VLANs diferentes."""
    return [
        (origem, destino)
        for origem, destino in pares_completos(plano)
        if plano["hosts"][origem]["vlan"] != plano["hosts"][destino]["vlan"]
    ]


def hosts_necessarios(testes: list[int], plano: dict) -> list[str]:
    """Nós que precisam estar no ar para executar os testes escolhidos."""
    necessarios: set[str] = set()
    for numero in testes:
        if numero == 1:
            necessarios |= {
                nome
                for nome, host in plano["hosts"].items()
                if host["modo"] == "dhcp"
            }
        elif numero == 2:
            necessarios |= {
                nome
                for nome, host in plano["hosts"].items()
                if gateway_esperado(plano, host)
            }
        elif numero == 3:
            necessarios |= set(hosts_comunicaveis(plano))
        elif numero == 4:
            necessarios |= set(HOSTS_CFTV)
        elif numero == 5:
            necessarios |= set(ORIGENS_ISOLAMENTO) | set(HOSTS_CFTV)
        elif numero == 6:
            necessarios.add(ORIGEM_INTER_VLAN)
    return sorted(necessarios)


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
        "--only",
        help="Testes a executar, separados por vírgula (padrão: 1,2,3,4,5,6)",
    )
    parser.add_argument(
        "--contagem",
        type=int,
        default=3,
        help="Pacotes ICMP por ping (padrão: 3)",
    )
    parser.add_argument(
        "--ip-teste6",
        default=IP_TESTE6,
        help=f"IP temporário usado no Teste 6 (padrão: {IP_TESTE6})",
    )
    parser.add_argument(
        "--json",
        type=Path,
        help="Escreve o relatório da execução em JSON no caminho indicado",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Imprime a saída bruta dos pings que falharem",
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
    parser.add_argument(
        "--ping-timeout",
        type=int,
        default=120,
        help="Espera máxima, em segundos, pela saída de cada ping no console "
        "(padrão: 120)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Sessões e execução no console
# ---------------------------------------------------------------------------


class Sessoes:
    """Mantém uma conexão Telnet por VPCS durante toda a bateria de testes."""

    def __init__(self, inventario: dict, credenciais, args: argparse.Namespace):
        self.inventario = inventario
        self.credenciais = credenciais
        self.args = args
        self._conexoes: dict[str, object] = {}

    def vpcs(self, nome: str):
        if nome not in self._conexoes:
            if nome not in self.inventario:
                raise KeyError(f"host {nome} ausente do inventário")
            self._conexoes[nome] = conectar(
                nome,
                self.inventario[nome],
                self.credenciais,
                self.args.timeout,
                self.args.check_timeout,
                self.args.poll,
            )
        return self._conexoes[nome]

    def comando(self, nome: str, comando: str, read_timeout: int = 120) -> str:
        return self.vpcs(nome).send_command_timing(
            comando,
            read_timeout=read_timeout,
            strip_prompt=False,
            strip_command=False,
        )

    def ping(self, nome: str, destino: str) -> RespostaPing:
        saida = self.comando(
            nome,
            f"ping {destino} -c {self.args.contagem}",
            read_timeout=self.args.ping_timeout,
        )
        return interpretar_ping(destino, saida)

    def fechar(self) -> None:
        for conexao in self._conexoes.values():
            try:
                conexao.disconnect()
            except Exception:  # noqa: BLE001 - encerramento best-effort
                pass
        self._conexoes.clear()


class Contexto:
    def __init__(self, plano: dict, sessoes: Sessoes, args: argparse.Namespace):
        self.plano = plano
        self.sessoes = sessoes
        self.args = args
        self.ips: dict[str, str] = {}
        self.falhas: list[str] = []

    # -- helpers ------------------------------------------------------------
    def registrar(self, descricao: str, ok: bool, detalhe: str = "") -> None:
        print(f"  {'OK  ' if ok else 'FALHA'} {descricao}", flush=True)
        if ok:
            return
        if detalhe:
            print(f"        {detalhe}", flush=True)
        self.falhas.append(f"{descricao}: {detalhe}" if detalhe else descricao)

    def ip_planejado(self, nome: str) -> str:
        return self.plano["hosts"][nome]["ip"].split("/")[0]

    def ip_atual(self, nome: str) -> str:
        """IP vigente do host, lendo o console se ainda não foi coletado.

        Hosts dinâmicos só são aceitos se o IP estiver dentro da rede da VLAN
        planejada; caso contrário o DHCP é reexecutado (importante quando o
        Teste 3 roda sozinho, sem o Teste 1 antes).
        """
        if nome in self.ips:
            return self.ips[nome]
        host = self.plano["hosts"][nome]
        if host["modo"] == "estatico":
            self.ips[nome] = host["ip"].split("/")[0]
            return self.ips[nome]
        rede = ipaddress.ip_network(
            self.plano["redes"][host["vlan"]]["rede"], strict=True
        )
        conexao = self.sessoes.vpcs(nome)
        ip, _ = ler_ip_vpcs(conexao)
        valido = False
        if ip and ip != "0.0.0.0/0":
            try:
                valido = ipaddress.ip_interface(ip).network == rede
            except ValueError:
                valido = False
        if not valido:
            self.sessoes.comando(nome, "ip dhcp")
            ip, _ = aguardar_dhcp(conexao, timeout=self.args.dhcp_timeout)
        self.ips[nome] = ip.split("/")[0]
        return self.ips[nome]

    def ping_esperado(self, origem: str, destino: str) -> None:
        resposta = self.sessoes.ping(origem, destino)
        self.registrar(f"{origem} -> {destino}", resposta.respondeu, resposta.motivo)
        if not resposta.respondeu and self.args.verbose:
            print(resposta.saida, flush=True)

    def ping_bloqueado(self, origem: str, destino: str) -> None:
        resposta = self.sessoes.ping(origem, destino)
        self.registrar(
            f"{origem} -> {destino} bloqueado",
            not resposta.respondeu,
            "houve resposta ICMP (isolamento falhou)",
        )
        if not resposta.respondeu and self.args.verbose:
            print(resposta.saida, flush=True)


# ---------------------------------------------------------------------------
# Testes de aceite
# ---------------------------------------------------------------------------


def teste_1_dhcp(ctx: Contexto) -> Resultado:
    for nome, host in ctx.plano["hosts"].items():
        if host["modo"] != "dhcp":
            continue
        try:
            ctx.sessoes.comando(nome, "ip dhcp")
            ip, gateway = aguardar_dhcp(
                ctx.sessoes.vpcs(nome), timeout=ctx.args.dhcp_timeout
            )
        except Exception as exc:  # noqa: BLE001 - registra e segue nos demais
            ctx.registrar(f"{nome} não obteve IP via DHCP", False, str(exc))
            continue
        ctx.ips[nome] = ip.split("/")[0]

        rede = ipaddress.ip_network(ctx.plano["redes"][host["vlan"]]["rede"])
        esperado_gw = str(ctx.plano["redes"][host["vlan"]]["gateway"])
        dentro = ipaddress.ip_interface(ip).network == rede
        ctx.registrar(
            f"{nome} obteve {ip} (gw {gateway})",
            dentro and gateway == esperado_gw,
            f"esperado dentro de {rede} com gw {esperado_gw}",
        )
    return _resultado(1, ctx)


def teste_2_gateway(ctx: Contexto) -> Resultado:
    for nome, host in ctx.plano["hosts"].items():
        gateway = gateway_esperado(ctx.plano, host)
        if not gateway:
            continue
        try:
            # Garante endereçamento válido antes do ping: um host sem IP
            # (DHCP que falhou no Teste 1, ou execução isolada com --only 2)
            # produz resposta inconclusiva do VPCS no lugar de um diagnóstico.
            ctx.ip_atual(nome)
        except Exception as exc:  # noqa: BLE001 - registra e segue nos demais
            ctx.registrar(f"{nome} sem IP válido", False, str(exc))
            continue
        ctx.ping_esperado(nome, gateway)
    return _resultado(2, ctx)


def teste_3_malha_completa(ctx: Contexto) -> Resultado:
    """Todos os hosts roteáveis devem se alcançar (malha completa).

    Inclui pares inter-VLAN (roteamento no ``SW-LACINA``) e pares intra-VLAN
    que atravessam tronco (``PC-LIAD`` <-> ``PC-LIAD-SALA``). ``CAM``/``NVR``
    ficam de fora porque a VLAN ``Cameras`` é isolada e não tem gateway.
    """
    pares = pares_completos(ctx.plano)
    if not pares:
        raise ValueError("nenhum par de hosts comunicáveis encontrado no plano")

    # Garante endereçamento válido em todos os nós antes de disparar os pings.
    for nome in hosts_comunicaveis(ctx.plano):
        ctx.ip_atual(nome)

    for origem, destino in pares:
        ctx.ping_esperado(origem, ctx.ip_atual(destino))
    return _resultado(3, ctx)


def teste_4_cftv(ctx: Contexto) -> Resultado:
    ctx.ping_esperado("CAM", ctx.ip_planejado("NVR"))
    return _resultado(4, ctx)


def teste_5_isolamento(ctx: Contexto) -> Resultado:
    for origem in ORIGENS_ISOLAMENTO:
        for alvo in HOSTS_CFTV:
            ctx.ping_bloqueado(origem, ctx.ip_planejado(alvo))
    return _resultado(5, ctx)


def teste_6_soberania_vlan(ctx: Contexto) -> Resultado:
    host = ctx.plano["hosts"][ORIGEM_INTER_VLAN]
    rede_vlan = ipaddress.ip_network(ctx.plano["redes"][host["vlan"]]["rede"])
    temporario = ipaddress.ip_interface(ctx.args.ip_teste6)
    if temporario.network == rede_vlan:
        raise ValueError(
            f"{temporario} pertence à própria sub-rede da VLAN {host['vlan']}; "
            "o Teste 6 precisa de um IP de outra sub-rede"
        )

    gateway_lsd = str(ctx.plano["redes"]["LSD"]["gateway"])
    try:
        ctx.sessoes.comando(
            ORIGEM_INTER_VLAN, f"ip {ctx.args.ip_teste6} {gateway_lsd}"
        )
        ip, gateway = ler_ip_vpcs(ctx.sessoes.vpcs(ORIGEM_INTER_VLAN))
        aceitou = ip is not None and ipaddress.ip_interface(ip) == temporario
        ctx.registrar(
            f"{ORIGEM_INTER_VLAN} aceitou o IP temporário {ip} (gw {gateway})",
            aceitou and gateway == gateway_lsd,
            f"esperado {temporario} com gw {gateway_lsd}",
        )
        # A porta segue na VLAN LACINA: o ping ao gateway do LSD deve falhar.
        ctx.ping_bloqueado(ORIGEM_INTER_VLAN, gateway_lsd)
    finally:
        try:
            ctx.sessoes.comando(ORIGEM_INTER_VLAN, "ip dhcp")
            ip, gateway = aguardar_dhcp(
                ctx.sessoes.vpcs(ORIGEM_INTER_VLAN),
                timeout=ctx.args.dhcp_timeout,
            )
        except Exception as exc:  # noqa: BLE001 - nunca mascarar o teste
            ctx.registrar("restauração do DHCP falhou", False, str(exc))
        else:
            ctx.ips[ORIGEM_INTER_VLAN] = ip.split("/")[0]
            esperado_gw = str(ctx.plano["redes"][host["vlan"]]["gateway"])
            ctx.registrar(
                f"{ORIGEM_INTER_VLAN} restaurado via DHCP em {ip}",
                gateway == esperado_gw,
                f"esperado gw {esperado_gw}",
            )
    return _resultado(6, ctx)


TESTES = {
    1: teste_1_dhcp,
    2: teste_2_gateway,
    3: teste_3_malha_completa,
    4: teste_4_cftv,
    5: teste_5_isolamento,
    6: teste_6_soberania_vlan,
}


def _resultado(numero: int, ctx: Contexto) -> Resultado:
    falhas = ctx.falhas
    ctx.falhas = []
    return Resultado(numero, TITULOS[numero], not falhas, falhas)


# ---------------------------------------------------------------------------
# Fluxo principal
# ---------------------------------------------------------------------------


def main() -> int:
    args = parse_args()
    try:
        plano = carregar_json(args.plano, "plano de rede")
        inventario = carregar_json(args.inventario, "inventário de consoles")
        validar_plano(plano)
        testes = selecionar_testes(args)
        garantir_inventario(inventario, hosts_necessarios(testes, plano))
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    credenciais = carregar_credenciais()
    sessoes = Sessoes(inventario, credenciais, args)
    ctx = Contexto(plano, sessoes, args)
    resultados: list[Resultado] = []

    try:
        for numero in testes:
            print(f"\n=== Teste {numero}: {TITULOS[numero]} ===", flush=True)
            try:
                resultado = TESTES[numero](ctx)
            except Exception as exc:  # noqa: BLE001 - continua nos demais testes
                resultado = Resultado(
                    numero,
                    TITULOS[numero],
                    False,
                    [f"erro: {type(exc).__name__}: {exc}"],
                )
            resultados.append(resultado)
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.", file=sys.stderr)
        return 130
    finally:
        sessoes.fechar()

    aprovados = [item for item in resultados if item.ok]
    reprovados = [item for item in resultados if not item.ok]

    if args.json:
        relatorio = {
            "ok": not reprovados,
            "aprovados": len(aprovados),
            "total": len(resultados),
            "resultados": [
                {
                    "teste": item.numero,
                    "titulo": item.titulo,
                    "ok": item.ok,
                    "falhas": item.falhas,
                }
                for item in resultados
            ],
        }
        args.json.write_text(
            json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if reprovados:
        print("\nTestes reprovados:", file=sys.stderr)
        for item in reprovados:
            print(f"  {item.numero} - {item.titulo}", file=sys.stderr)
            for falha in item.falhas:
                print(f"      {falha}", file=sys.stderr)
        print(
            f"\nTestes de aceite: {len(aprovados)}/{len(resultados)} aprovados.",
            file=sys.stderr,
        )
        return 1

    print(
        f"\nTestes de aceite: {len(aprovados)}/{len(resultados)} aprovados."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
