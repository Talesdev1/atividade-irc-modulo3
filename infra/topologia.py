"""Mapa de cabeamento L1 da topologia inicial do laboratório.

As portas dos switches EXOS são expostas pelo GNS3 como ``Port1``, ``Port2``,
... (o adaptador 0 é a porta ``Mgmt``). Os VPCS usam ``Ethernet0``.
"""

from __future__ import annotations

from dataclasses import dataclass

SWITCHES = ("SW-LACINA", "SW-LSD", "SW-LSI", "SW-LIAD")
PORTA_VPCS = "Ethernet0"


@dataclass(frozen=True)
class Enlace:
    """Um cabo físico entre dois nós do GNS3."""

    no_a: str
    porta_a: str
    no_b: str
    porta_b: str
    tipo: str

    @property
    def descricao(self) -> str:
        return (
            f"{self.no_a} {self.porta_a} <-> "
            f"{self.no_b} {self.porta_b} ({self.tipo})"
        )


# Mapa de portas do projeto (docs/docs.md, Etapa 2). A ordem segue primeiro os
# acessos dos VPCS e depois os troncos 802.1Q entre os switches.
ENLACES_INICIAIS: tuple[Enlace, ...] = (
    # Acessos no SW-LACINA
    Enlace("PC-LACINA", PORTA_VPCS, "SW-LACINA", "Port1", "acesso"),
    Enlace("WIFI-1", PORTA_VPCS, "SW-LACINA", "Port2", "acesso"),
    Enlace("ADM", PORTA_VPCS, "SW-LACINA", "Port3", "acesso"),
    # Acessos no SW-LSD
    Enlace("PC-LSD", PORTA_VPCS, "SW-LSD", "Port1", "acesso"),
    Enlace("NVR", PORTA_VPCS, "SW-LSD", "Port2", "acesso"),
    # Acessos no SW-LSI
    Enlace("PC-LSI", PORTA_VPCS, "SW-LSI", "Port1", "acesso"),
    Enlace("PC-LIAD-SALA", PORTA_VPCS, "SW-LSI", "Port2", "acesso"),
    # Acessos no SW-LIAD
    Enlace("PC-LIAD", PORTA_VPCS, "SW-LIAD", "Port1", "acesso"),
    Enlace("WIFI-2", PORTA_VPCS, "SW-LIAD", "Port2", "acesso"),
    Enlace("CAM", PORTA_VPCS, "SW-LIAD", "Port3", "acesso"),
    # Troncos 802.1Q em estrela, centralizados no SW-LACINA
    Enlace("SW-LACINA", "Port22", "SW-LSD", "Port22", "tronco"),
    Enlace("SW-LACINA", "Port23", "SW-LSI", "Port23", "tronco"),
    Enlace("SW-LACINA", "Port24", "SW-LIAD", "Port24", "tronco"),
)


def adaptadores_necessarios() -> dict[str, int]:
    """Quantidade mínima de adaptadores para expor todas as portas usadas.

    O adaptador 0 é a porta ``Mgmt``; por isso ``PortN`` exige ``N + 1``
    adaptadores.
    """
    necessarios: dict[str, int] = {}
    for enlace in ENLACES_INICIAIS:
        for no, porta in (
            (enlace.no_a, enlace.porta_a),
            (enlace.no_b, enlace.porta_b),
        ):
            if no not in SWITCHES:
                continue
            numero = int(porta.removeprefix("Port"))
            necessarios[no] = max(necessarios.get(no, 0), numero + 1)
    return necessarios
