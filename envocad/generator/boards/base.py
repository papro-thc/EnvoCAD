"""Společná data sestavení řetězce FVE (bez Qt): `ChainContext` sdílí `pv` (stringy, střídače, DC rozvaděče),
`chain` (bloky a listy článků řetězce) a buildery rozvaděčů v `boards/`. Návrh `docs/design/topologie_f1_f2.md`,
kap. 1.3 (kroky 5–6)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from envocad.model.project import Element, Project, Sheet, Wire
from envocad.model.topology import ChainNode, Topology


@dataclass
class PvGeometry:
    """Pracovní souřadnice JPS (mm) před rozmístěním na list: řady střídačů, sloupce rozvaděčů, střídačů a sítě."""
    row_h: list[float]           # výška řady střídače (podle počtu stringů)
    row_extra: list[float]       # místo navíc pod řadou (baterie, pás svorek střídače) – `pv.build` ho doplní
    y_top: float
    n_route: int                 # DC rozvaděčů po trase na střídač
    n_boxes: int                 # DC rozvaděčů na střídač celkem (u RD je posledním rozvaděč FVE)
    x_str: float
    n_max: int                   # nejvíc stringů jednoho střídače
    n_all: int                   # stringů celkem
    dc_first: int                # první DC přívod rozvaděče FVE RD (za AC přívody)
    x_boxes: list[float]
    x_dc: float                  # samostatný odpínač DC (bez rozvaděčů)
    x_inv: float
    x_blk: float                 # blok hlavního AC článku (RFVE.AC / RFVE)
    x_grid: float
    common_dc: bool = False      # jeden společný DC rozvaděč u technologie pro všechny střídače (F2, rozhodnutí 3)


@dataclass
class ChainContext:
    """Stav jednoho sestavení projektu: specifikace (sloučená s `DEFAULT_SPEC`), projekt, list JPS, zvolená topologie
    a prvky, které vytvořila FV část (`pv.build`) – střídače, stringy, řady, AC vodiče, DC rozvaděče."""
    spec: dict
    project: Project
    sheet: Sheet
    building: str
    combined: bool                # rodinný dům: DC část v rozvaděči FVE (RFVE) s AC částí
    geo: PvGeometry
    topology: Topology | None = None
    kwp: float = 0.0              # instalovaný výkon DC (Σ stringů) – `meta["p_installed_kwp"]`
    opt_comp: object | None = None    # artikl optimizéru (`spec.optimizer.component_id`)
    inverters: list[Element] = field(default_factory=list)
    strings: list[list[Element]] = field(default_factory=list)     # stringy po střídačích
    rows: list[list[Element]] = field(default_factory=list)        # prvky řady střídače (dělení JPS na listy)
    ac_wires: list[Wire] = field(default_factory=list)
    # DC rozvaděče: (blok, stringy, druh "tech" | "route", č. střídače, označení střídače)
    dc_boxes: list[tuple[Element, list[Element], str, int, str]] = field(default_factory=list)
    blocks: dict[str, Element] = field(default_factory=dict)       # role → blok článku řetězce ("main" = AC rozvaděč)
    grid: Element | None = None
    earth: Element | None = None
    mv: dict | None = None        # bloky přípojky VN (`boards.mv._connection_blocks`)
    fuse_cache: dict[str, tuple[str, str]] = field(default_factory=dict)
    done: set[str] = field(default_factory=set)    # už sestavené části (listy DC rozvaděčů, hlavní rozvaděč…)
    tail: tuple[Element, str] | None = None         # poslední blok řetězce směrem k síti a jeho vývod (XOUT)
    dc_common: Element | None = None                # společný DC rozvaděč u technologie RFVE.DC (2+ střídače)

    @property
    def main(self) -> Element:
        """Blok hlavního AC článku (RFVE.AC, u rodinného domu RFVE) – přívody od střídačů X1…Xn."""
        return self.blocks["main"]


@dataclass(frozen=True)
class ChainPorts:
    """Porty bloku článku řetězce: přívody od FV strany (`pv_side`, např. X1…Xn) a vývod k síti (`grid_side`, XOUT)."""
    pv_side: tuple[str, ...]
    grid_side: str


class BoardBuilder(Protocol):
    """Builder článku řetězce (`boards/<role>.py`, registr `chain.BOARD_BUILDERS`). `chain.build` ho volá ve dvou
    průchodech topologií: `block` (blok v JPS za FV částí; vrací blok článku, nebo None) a `build` (list rozvaděče).
    Builder, který obslouží víc rolí (přípojka VN), se v každém průchodu volá jen jednou – `name` je klíč."""
    name: str

    def block(self, ctx: ChainContext, node: ChainNode) -> Element | None: ...

    def ports(self, ctx: ChainContext, node: ChainNode) -> ChainPorts: ...

    def build(self, ctx: ChainContext, node: ChainNode) -> None: ...
