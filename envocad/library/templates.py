"""Šablony listů rozvaděčů – vygenerují přístroje a vodiče do listu. Bez Qt.

Šablona je funkce (project, sheet, params) → None. Souřadnice v mm, Y nahoru, mřížka 2,5 mm.
Přístroje se zároveň rozmístí na DIN lišty (layout), aby pohled rozložení nebyl prázdný.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from envocad.model.busbar import B1_X, BusLayout
from envocad.model.feed import FEED_SYMBOL, normalize_legacy_objects
from envocad.model.project import Element, Project, Sheet, Wire, WireEnd

AC_CONDUCTORS = ["L1", "L2", "L3", "N", "PE"]
DC_CONDUCTORS = ["L+", "L-"]   # ČSN EN 60445


@dataclass
class TemplateParam:
    key: str
    label: str
    default: str


@dataclass
class Template:
    id: str
    name: str
    description: str
    params: list[TemplateParam]
    build: Callable[[Project, Sheet, dict[str, str]], None]


def _el(project: Project, sheet: Sheet, sid: str, x: float, y: float, prefix: str, rot: int = 0, **attrs) -> Element:
    e = Element(symbol_id=sid, x=x, y=y, rotation=rot)
    e.attrs = {"ref": project.next_ref(prefix) if prefix else "", **{k: str(v) for k, v in attrs.items()}}
    sheet.elements.append(e)
    return e


def _feed(project: Project, sheet: Sheet, direction: str, x: float, y: float, prefix: str, rot: int = 0,
          **attrs) -> Element:
    """Přívod (`direction="in"`) / vývod (`"out"`) – značka `sb.feed`; při `rot=0` port nahoře, kabel dole."""
    return _el(project, sheet, FEED_SYMBOL, x, y, prefix, rot=rot, dir=direction, **attrs)


def _wire(project: Project, sheet: Sheet, a: Element, pa: str, b: Element, pb: str,
          conductors: list[str], **attrs) -> Wire:
    w = Wire(WireEnd(a.id, pa), WireEnd(b.id, pb), conductors=list(conductors))
    w.attrs = {"ref": "", **{k: str(v) for k, v in attrs.items()}}
    sheet.wires.append(w)
    return w


def _auto_link_feed(project: Project, sheet: Sheet, feed: Element, port_hint: str = "") -> None:
    """Přívod rozvaděče naváže na první vodič JPS napojený na blok ROZVADĚČ (přebere kabel a žíly)."""
    from envocad.model.project import feed_link_attrs, parent_sheet
    ps = parent_sheet(project, sheet)
    if ps is None:
        return
    block = sheet.parent_element_id
    cands = [w for w in ps.wires if w.touches(block)]
    cands.sort(key=lambda w: 0 if port_hint and (w.a.port == port_hint or w.b.port == port_hint) else 1)
    if not cands:
        return
    w = cands[0]
    # konec vodiče na bloku se přejmenuje na označení přívodu (X1) – blok má porty podle přívodů/vývodů
    for end in (w.a, w.b):
        if end.element_id == block and feed.ref:
            end.port = feed.ref
    feed.attrs.update(feed_link_attrs(project, sheet, feed, w.id))
    if cands[0].conductors:
        for w in sheet.wires:
            if w.touches(feed.id):
                w.conductors = list(cands[0].conductors)


# ---- parametry šablon: neplatná hodnota = ValueError s českou hláškou (GUI ji ukáže a nic nevloží) ----------
AC_MAX_OUTPUTS = 9      # vývody AC šablony; sběrnice sb.busbar má 12 vývodů (SPD + 9 vývodů + PE + rezerva)
DC_MAX_STRINGS = 9
BUSBAR_OUTPUTS = 12


def _raw(p: dict[str, str], key: str) -> str:
    return str(p.get(key) if p.get(key) is not None else "").strip()


def int_param(p: dict[str, str], key: str, label: str, lo: int, hi: int) -> int:
    """Celé číslo v rozsahu lo…hi; jinak ValueError („Počet vývodů: povolený rozsah je 1–9 (zadáno 0).“)."""
    raw = _raw(p, key)
    try:
        v = float(raw.replace(",", "."))
    except ValueError:
        raise ValueError(f"{label}: „{raw}“ není číslo – zadejte celé číslo {lo}–{hi}.") from None
    if not v.is_integer():
        raise ValueError(f"{label}: zadejte celé číslo {lo}–{hi} (zadáno „{raw}“).")
    if not lo <= v <= hi:
        raise ValueError(f"{label}: povolený rozsah je {lo}–{hi} (zadáno {raw}).")
    return int(v)


def current_param(p: dict[str, str], key: str, label: str) -> str:
    """Proud [A] > 0 (desetinná čárka i tečka); vrací zadaný text (bez mezer)."""
    raw = _raw(p, key)
    try:
        v = float(raw.replace(",", "."))
    except ValueError:
        raise ValueError(f"{label}: „{raw}“ není číslo – zadejte proud v A (např. 32).") from None
    if v <= 0:
        raise ValueError(f"{label}: proud musí být větší než 0 A (zadáno {raw}).")
    return raw


def distribution_param(p: dict[str, str]) -> bool:
    """Rozvod AC šablony: True = sběrnice (bus / sběrnice), False = svorky s můstky (terminals / svorky)."""
    raw = _raw(p, "distribution") or "bus"
    t = raw.lower()
    if t.startswith(("b", "sb")):
        return True
    if t.startswith(("t", "sv")):
        return False
    raise ValueError(f"Rozvod: „{raw}“ – zadejte bus (sběrnice) nebo terminals (svorky).")


ROUTE_KINDS = ("trasa", "trase", "po trase", "route", "r")
TECH_KINDS = ("tech", "technologie", "u technologie", "t")


def dc_kind_param(p: dict[str, str]) -> str:
    """Druh DC rozvaděče: „tech“ (u technologie – pojistkové odpínače) nebo „route“ (po trase – odpínače DC).
    Přijímá tech/technologie a trasa/Trasa/po trase/route (bez ohledu na velikost písmen)."""
    raw = _raw(p, "kind") or "tech"
    t = " ".join(raw.lower().split())
    if t in ROUTE_KINDS or t.startswith(("tras", "po tras", "route")):
        return "route"
    if t in TECH_KINDS or t.startswith(("tech", "u tech")):
        return "tech"
    raise ValueError(f"Druh: „{raw}“ – zadejte tech (u technologie) nebo trasa (po trase).")


def _place_sequential(sheet: Sheet, elements: list[Element]) -> None:
    """Rozmístí přístroje za sebou po řadách DIN lišt podle jejich šířky v modulech. Cívka stykače, jehož položkou
    výkazu je stykač na stejném listu (`xref.DeviceIndex.is_bom_device`), ani kontakty (`NON_DEVICE_SYMBOLS`) se
    nerozmísťují."""
    from envocad.model.project import NON_DEVICE_SYMBOLS
    from envocad.model.xref import DeviceIndex
    idx = DeviceIndex.for_sheets([sheet])
    row, pos = 0, 0.0
    for e in elements:
        m = e.modules
        if m <= 0 or e.symbol_id in NON_DEVICE_SYMBOLS or not idx.is_bom_device(e, sheet):
            continue
        if pos + m > sheet.layout.modules_per_row:
            row, pos = row + 1, 0.0
        sheet.layout.set_placement(e.id, row, pos)
        pos += m
    sheet.layout.rows = max(sheet.layout.rows, row + 1)


# ---------------------------------------------------------------------------
GROUP_PITCH = 30.0  # rozteč skupin svorek (mm) – ve vícepólu se roztáhne 2×, aby se vešlo 5 svorek po 7,5 mm


def _terminal_group(project: Project, sheet: Sheet, x: float, y: float, strip: str, first: int, n: int,
                    desc: str = "") -> Element:
    """Skupina n svorek svorkovnice `strip` s čísly first…first+n-1 (prvek sb.terminal_block)."""
    e = Element(symbol_id="sb.terminal_block", x=x, y=y)
    e.attrs = {"ref": strip, "terminal": " ".join(str(first + i) for i in range(n)), "desc": desc}
    sheet.elements.append(e)
    return e


def _bridge_groups(first_numbers: list[int], n: int) -> list[list[str]]:
    """Můstky mezi skupinami: žíla i spojuje svorky first+i všech skupin."""
    return [[str(f + i) for f in first_numbers] for i in range(n)]


def build_ac_fve(project: Project, sheet: Sheet, p: dict[str, str]) -> None:
    """AC rozvaděč FVE: přívod od střídače → hlavní vypínač → rozvod → SPD, vývody s jističi.
    Rozvod = sběrnice potenciálů (vodič, jako v EPLAN; `bus`) nebo rozvodné svorky X2 s můstky (`terminals`).
    Vše přichází zespodu (docs/design/znacka_privod_vyvod.md): přívod i vývody ve spodní řadě, přívodní větev teče
    od svorky X1 hlavním vypínačem (otočeným tokem nahoru) do sběrnice / skupiny napájení, vývody visí dolů."""
    n_out = int_param(p, "n_out", "Počet vývodů", 1, AC_MAX_OUTPUTS)
    i_main = current_param(p, "i_main", "In hlavního vypínače")
    i_out = current_param(p, "i_out", "In jističů vývodů")
    use_bus = distribution_param(p)
    y = 200.0
    x0 = 90.0                   # přívodní větev; vlevo od ní SPD a XPE / PE lišta
    nc = len(AC_CONDUCTORS)
    # sběrnice parametrická (`model/busbar.py`): přívod B1 nad hlavním vypínačem, vývod 1 (PE) nad XPE, 2 nad SPD,
    # 3… nad jističi vývodů – všechny odbočky svisle
    lay = BusLayout(1, n_out, GROUP_PITCH) if use_bus else None
    bus_x = x0 - B1_X
    x_spd = bus_x + lay.out_x("2") if lay else x0 - GROUP_PITCH
    feed = _feed(project, sheet, "in", x0, y - 95, "X", desc=p.get("feed_desc", "od střídače"))
    q = _el(project, sheet, "sb.main_switch", x0, y - 60, "Q", rot=90, in_=i_main, poles="4", modules="4")
    groups: list[Element] = []
    bus = None
    if use_bus:
        bus = _el(project, sheet, "sb.busbar", bus_x, y - 25, "", desc="rozvod", in_=i_main, conductors=" ".join(AC_CONDUCTORS),
                  taps="1", outs=str(n_out), tap_pitch=f"{GROUP_PITCH:g}")
        bus.attrs["ref"] = "1"
    else:
        strip = project.next_ref("X")
        # skupina 0 = napájení (od Q zdola – otočená, vstup 1 dole) + SPD, skupiny 1…n = vývody; napájení přes můstky
        firsts: list[int] = []
        for i in range(n_out + 1):
            first = 1 + i * nc
            firsts.append(first)
            groups.append(_terminal_group(project, sheet, x0 + i * GROUP_PITCH, y - 30, strip, first, nc,
                                          "napájení" if i == 0 else f"vývod {i}"))
        groups[0].rotation = 180
        project.set_bridges(strip, _bridge_groups(firsts, nc), sheet)
    spd = _el(project, sheet, "fve.spd", x_spd, y - 60, "F", spd_type="T1+T2", poles="4", modules="4")
    _wire(project, sheet, feed, "1", q, "1", AC_CONDUCTORS)
    if use_bus:
        # PE je potenciál sběrnice; uzemnění = vývod na ekvipotenciální svorkovnici (HOP) vně rozvaděče
        _wire(project, sheet, q, "2", bus, "B1", AC_CONDUCTORS)             # zdola pod přívodem (B1 = x sběrnice − 60)
        _wire(project, sheet, bus, "2", spd, "L", AC_CONDUCTORS[:4])
        xpe = _feed(project, sheet, "out", bus_x + lay.out_x("1"), y - 95, "X", desc="k HOP")
        _wire(project, sheet, spd, "PE", xpe, "1", ["PE"]).points = [(x_spd, 120.0), (xpe.x, 120.0)]   # SPD na HOP
        _wire(project, sheet, bus, "1", xpe, "1", ["PE"])
    else:
        pe = _el(project, sheet, "sb.pe_bar", x_spd + 7.5, y - 87.5, "X", kind="PE")   # port 2 pod SPD, port 1 vlevo
        _wire(project, sheet, q, "2", groups[0], "1", AC_CONDUCTORS)
        _wire(project, sheet, groups[0], "2", spd, "L", AC_CONDUCTORS[:4]).points = [(x0, 182.5), (x_spd, 182.5)]
        _wire(project, sheet, groups[0], "2", pe, "1", ["PE"]).points = [(x0, 187.5), (x_spd - 5.0, 187.5)]   # PE skupiny
        _wire(project, sheet, spd, "PE", pe, "2", ["PE"])
    outs: list[Element] = []
    for i in range(1, n_out + 1):
        x = bus_x + lay.out_x(str(i + 2)) if lay else x0 + i * GROUP_PITCH
        f = _el(project, sheet, "fve.breaker_mcb", x, y - 60, "F", rot=270, in_=i_out, char="B", poles="3", modules="3")
        out = _feed(project, sheet, "out", x, y - 95, "X", desc=f"vývod {i}")
        if use_bus:
            _wire(project, sheet, bus, str(i + 2), f, "1", AC_CONDUCTORS)
        else:
            _wire(project, sheet, groups[i], "2", f, "1", AC_CONDUCTORS)
        _wire(project, sheet, f, "2", out, "1", AC_CONDUCTORS)
        outs.append(f)
    _auto_link_feed(project, sheet, feed, "1")
    # skupiny rozvodných svorek zabírají na liště počet svorek × šířka svorky (`Element.modules`)
    _place_sequential(sheet, [q, spd, *outs, *groups])


DC_STRING_PITCH = 50.0   # rozteč stringů v DC rozvaděči (mm) – jako makra „DC string …“; popisek SPD vpravo od
                         # odbočky se vejde před další string (při 30 mm se texty překrývaly); 9 stringů se na A3
                         # nevejde – list zvětší `frame.grow_sheet_to_content` (`apply_template` s lib, generátor)


def build_dc_strings(project: Project, sheet: Sheet, strings: list[str], kind: str = "tech",
                     fuse_in: str | list[str] = "15", disconnect_in: str = "32", spd: str = "T2", first: int = 1,
                     dx: float = 0.0, pe: Element | None = None) -> None:
    """DC rozvaděč: stringy se v rozvaděči NIKDY nespojují – každý prochází odděleně: přívod X1…Xn → pojistkový
    odpínač (u technologie, `kind="tech"`) → vývod X(n+1)…X(2n), na každém stringu vlastní SPD DC; PE lišta.
    Rozvaděč po trase (`kind="route"`) odpínače nemá – přívod vede rovně na vývod, SPD odbočuje z přívodní svorky
    (odpojovací místo jsou pojistkové odpínače u střídače). `first` = číslo prvního přívodu (rozvaděč FVE rodinného
    domu má před DC částí přívody AC), `dx` = posun DC části v listu. `fuse_in` = In pro všechny stringy, nebo seznam
    In po stringech (rozvaděč FVE s více střídači); "" = neurčeno (prázdné In, kontrola F7 hlásí chybu).
    `pe` = existující PE cíl listu (vývod XPE / PE lišta AC části rozvaděče FVE) – SPD stringů se připojí na něj
    jako u makra „DC string v rozvaděči“, vlastní PE lišta se netvoří. `disconnect_in` se už nepoužívá (kompatibilita).
    (Paralelní spojení stringů dělá jen SolarEdge – to se kreslí jako jeden string.)"""
    n = len(strings)
    fuses = list(fuse_in) if isinstance(fuse_in, (list, tuple)) else [fuse_in] * n
    if len(fuses) != n:
        raise ValueError(f"DC rozvaděč: In pojistek pro {len(fuses)} stringů, stringů je {n}.")
    y, x0 = 200.0, 60.0 + dx
    devices: list[Element] = []
    spds: list[Element] = []
    if pe is None:
        pe = _el(project, sheet, "sb.pe_bar", x0 + (n - 1) * DC_STRING_PITCH / 2, y - 80, "", kind="PE")
        pe.attrs["ref"] = f"X{first + 2 * n}"   # za přívody X1…Xn a vývody X(n+1)…X(2n)
    pe_bar = pe.symbol_id == "sb.pe_bar"
    for k, g in enumerate(strings):
        x = x0 + k * DC_STRING_PITCH
        feed = _feed(project, sheet, "in", x, y + 40, "", rot=180, desc=f"od {g}")
        feed.attrs["ref"] = f"X{first + k}"
        out = _feed(project, sheet, "out", x, y - 30, "", desc=f"{g} dál")
        out.attrs["ref"] = f"X{first + n + k}"
        s_el = _el(project, sheet, "fve.spd", x + 12.5, y - 20, "F", spd_type=f"{spd} DC", uc="1000", poles="3", modules="3",
                   desc=g if g.lower().startswith("string") else f"string {g}")
        if kind == "tech":
            d = _el(project, sheet, "fve.fuse_disconnect", x, y + 10, "F", rot=270, in_=fuses[k], char="gPV", un="1000",
                    poles="2", modules="2")
            _wire(project, sheet, feed, "1", d, "1", DC_CONDUCTORS)
            _wire(project, sheet, d, "2", out, "1", DC_CONDUCTORS)
            _wire(project, sheet, d, "2", s_el, "L", DC_CONDUCTORS)
            devices.append(d)
        else:
            _wire(project, sheet, feed, "1", out, "1", DC_CONDUCTORS)
            _wire(project, sheet, feed, "1", s_el, "L", DC_CONDUCTORS)
        _wire(project, sheet, s_el, "PE", pe, str(min(k + 1, 6)) if pe_bar else "1", ["PE"])
        spds.append(s_el)
    _place_sequential(sheet, [*devices, *spds])


def build_dc(project: Project, sheet: Sheet, p: dict[str, str]) -> None:
    n_str = int_param(p, "n_strings", "Počet stringů", 1, DC_MAX_STRINGS)
    kind = dc_kind_param(p)
    i_fuse = current_param(p, "i_fuse", "In pojistkových odpínačů")
    build_dc_strings(project, sheet, [f"string {i + 1}" for i in range(n_str)], kind, i_fuse, spd=_raw(p, "spd") or "T2")


def build_empty(project: Project, sheet: Sheet, p: dict[str, str]) -> None:
    """Prázdný list: přívod (navázaný na vodič JPS k bloku ROZVADĚČ, je-li) a PE můstek."""
    feed = _feed(project, sheet, "in", 40, 220, "X", rot=180, desc="přívod")
    _el(project, sheet, "sb.pe_bar", 40, 120, "X", kind="PE")
    _auto_link_feed(project, sheet, feed, "1")


TEMPLATES: list[Template] = [
    Template("ac_fve", "AC rozvaděč FVE", "Přívod od střídače, hlavní vypínač, rozvod (sběrnice potenciálů nebo svorky s můstky), SPD, vývody s jističi",
             [TemplateParam("n_out", f"Počet vývodů (1–{AC_MAX_OUTPUTS})", "3"), TemplateParam("i_main", "In hlavního vypínače [A]", "80"),
              TemplateParam("i_out", "In jističů vývodů [A]", "32"), TemplateParam("feed_desc", "Přívod od", "od střídače"),
              TemplateParam("distribution", "Rozvod (bus = sběrnice / terminals = svorky)", "bus")],
             build_ac_fve),
    Template("dc", "DC rozvaděč", "Každý string zvlášť: pojistkový odpínač (u technologie), SPD na string, vývod; po trase jen SPD (bez odpínače)",
             [TemplateParam("n_strings", f"Počet stringů (1–{DC_MAX_STRINGS})", "4"),
              TemplateParam("kind", "Druh (tech / trasa)", "tech"),
              TemplateParam("i_fuse", "In pojistkových odpínačů [A]", "15"),
              TemplateParam("spd", "Typ SPD", "T2")],
             build_dc),
    Template("empty", "Prázdný list", "Jen přívod a PE můstek", [], build_empty),
]


def template(tid: str) -> Template:
    return next(t for t in TEMPLATES if t.id == tid)


def apply_template(project: Project, sheet: Sheet, tid: str, params: dict[str, str] | None = None,
                   lib=None) -> None:
    """Vloží šablonu do listu. Neplatný parametr → ValueError s českou hláškou; vestavěné šablony parametry ověří
    dřív, než cokoli vloží (list zůstane beze změny). S knihovnou (`lib`) se list zvětší, když obsah přetéká formát
    (`frame.grow_sheet_to_content` – např. DC rozvaděč s 9 stringy po `DC_STRING_PITCH` se na A3 nevejde)."""
    t = template(tid)
    p = {tp.key: tp.default for tp in t.params}
    p.update(params or {})
    t.build(project, sheet, p)
    # šablona pluginu ze starší verze může vkládat `sb.feed_in` / `sb.feed_out` – převod na `sb.feed` + směr
    normalize_legacy_objects(sheet.elements)
    if lib is not None:
        from envocad.model.frame import grow_sheet_to_content
        grow_sheet_to_content(project, sheet, lib)
