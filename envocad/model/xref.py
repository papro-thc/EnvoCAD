"""Křížové odkazy: přístroje a jejich kontakty (zrcadlo kontaktů, kontaktní obraz) a přerušovací body
(dvojice, řetěz, hvězda). Čistá data, bez Qt. Návrh: `docs/design/xref_zrcadleni_kontaktu.md`.

Přístroj = **skupina** prvků se stejným označením v jednom prostoru označení (`designation.scope_key`):
hostitel (cívka, jinak první ne-kontakt), položka výkazu (`device`), případně stykač kreslený v silovém schématu
jako silové kontakty cívky (`secondary`, `DUAL_ROLE`) a kontakty (přiřazené podle `ref`, přednost má skupina
ve stejném prostoru jako kontakt, jinak první). Index se staví jednou za O(N) – `DeviceIndex.build(project)`.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from itertools import pairwise
from types import SimpleNamespace

from envocad.model.designation import Designation, designation, scope_key
from envocad.model.multipole import is_terminal_block
from envocad.model.project import (
    COIL_SYMBOLS,
    CONTACT_KIND,
    DUAL_ROLE,
    INTERRUPT_SYMBOL,
    Element,
    Project,
    Sheet,
    is_contact,
)
from envocad.model.symbol import GRID

KIND_POWER, KIND_NO, KIND_NC = "power", "no", "nc"
COLUMN_ORDER = (KIND_POWER, KIND_NO, KIND_NC)        # vlevo → vpravo; osa mezi NO a NC
# druh kontaktu česky pro hlášky: (1 kontakt, 2–4 kontakty, 5+ kontaktů)
KIND_WORD = {KIND_POWER: ("silový kontakt", "silové kontakty", "silových kontaktů"),
             KIND_NO: ("spínací kontakt", "spínací kontakty", "spínacích kontaktů"),
             KIND_NC: ("rozpínací kontakt", "rozpínací kontakty", "rozpínacích kontaktů")}
DEFAULT_PAIR = {KIND_NO: "13/14", KIND_NC: "21/22", KIND_POWER: "1/2"}
IMAGE_PREFIX = {"NO": KIND_NO, "NC": KIND_NC, "P": KIND_POWER, "PWR": KIND_POWER, "HL": KIND_POWER}

Placed = tuple[Sheet, Element]
Box = tuple[float, float, float, float]
_SPLIT = re.compile(r"[\s,;]+")


def count_words(n: int, kind: str) -> str:
    """„použit 1 silový kontakt“, „použity 3 spínací kontakty“, „použito 5 rozpínacích kontaktů“ (česká shoda
    číslovky se slovesem a podstatným jménem)."""
    one, few, many = KIND_WORD[kind]
    if n == 1:
        return f"použit 1 {one}"
    if 2 <= n <= 4:
        return f"použity {n} {few}"
    return f"použito {n} {many}"


# ---- páry svorek a kontaktní obraz --------------------------------------------------------------------------
def natural_key(text: str) -> tuple:
    """Přirozené řazení párů: 1/2 < 3/4 < 13/14 < 21/22; DO1 < DO2 < DO10."""
    return tuple((0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.findall(r"\d+|\D+", text or ""))


def contact_kind(e: Element) -> str | None:
    """Druh kontaktu prvku: pomocný NO/NC, silový; stykač (`DUAL_ROLE`) = silový. Ostatní None."""
    return CONTACT_KIND.get(e.symbol_id) or DUAL_ROLE.get(e.symbol_id)


def contact_pairs(e: Element) -> list[str]:
    """Páry svorek kontaktu: `attrs["terminals"]` (i víc párů oddělených mezerou/čárkou), jinak výchozí podle druhu;
    silový kontakt/stykač má pár na každý pól (1/2, 3/4, 5/6)."""
    toks = [t for t in _SPLIT.split(e.attrs.get("terminals", "") or "") if t]
    if toks:
        return toks
    kind = contact_kind(e)
    if kind == KIND_POWER:
        return [f"{2 * i - 1}/{2 * i}" for i in range(1, max(e.poles, 1) + 1)]
    return [DEFAULT_PAIR[kind]] if kind else []


def classify_pair(pair: str) -> str | None:
    """Druh páru bez předpony dle IEC 60947-5-1: jednomístné liché/sudé (1/2, 3/4) = silový; dvoumístné se stejnou
    řadovou číslicí a funkční číslicí 3/4 nebo 7/8 = NO, 1/2 nebo 5/6 = NC. Jinak None."""
    m = re.fullmatch(r"(\d)/(\d)", pair)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return KIND_POWER if a % 2 == 1 and b == a + 1 else None
    m = re.fullmatch(r"(\d)(\d)/(\d)(\d)", pair)
    if m and m.group(1) == m.group(3):
        func = (int(m.group(2)), int(m.group(4)))
        if func in ((3, 4), (7, 8)):
            return KIND_NO
        if func in ((1, 2), (5, 6)):
            return KIND_NC
    return None


@dataclass(frozen=True)
class ContactSlot:
    kind: str
    pair: str


def parse_contact_image(text: str) -> tuple[list[ContactSlot], list[str]]:
    """Kontaktní obraz „1/2 3/4 5/6 13/14 21/22“, „NO:11/14 NC:11/12“, „NO:DO1“ → (sloty, nečitelné tokeny)."""
    slots: list[ContactSlot] = []
    bad: list[str] = []
    for tok in _SPLIT.split((text or "").strip()):
        if not tok:
            continue
        pre, sep, rest = tok.partition(":")
        if sep:
            kind = IMAGE_PREFIX.get(pre.upper())
            if kind is None or not rest:
                bad.append(tok)
            else:
                slots.append(ContactSlot(kind, rest))
            continue
        kind = classify_pair(tok)
        if kind is None:
            bad.append(tok)
        else:
            slots.append(ContactSlot(kind, tok))
    return slots, bad


def contact_image(group: DeviceGroup) -> list[ContactSlot] | None:
    """Kontaktní obraz skupiny z `device.attrs["contacts"]`, jinak z hostitele. None = nezadán (bez kontrol a rezerv)."""
    text = group.device[1].attrs.get("contacts", "") or group.host[1].attrs.get("contacts", "")
    if not (text or "").strip():
        return None
    slots, _bad = parse_contact_image(text)
    return slots or None


# ---- skupiny přístrojů -------------------------------------------------------------------------------------
def _host_candidate(e: Element) -> bool:
    return bool(e.ref) and not is_contact(e) and not is_terminal_block(e) and e.symbol_id != INTERRUPT_SYMBOL


@dataclass
class DeviceGroup:
    scope: tuple[str, str]
    ref: str
    host: Placed                                   # cívka, jinak první ne-kontakt
    device: Placed                                 # položka výkazu / artikl / rozložení
    secondary: list[Placed] = field(default_factory=list)    # DUAL_ROLE prvek při existenci cívky
    contacts: list[Placed] = field(default_factory=list)
    members: list[Placed] = field(default_factory=list)      # všechny ne-kontakty skupiny (pořadí projektu)

    @property
    def dup(self) -> bool:
        """Duplicitní označení: ve skupině smí být ≤1 cívka a ≤1 DUAL_ROLE prvek, jinak jen jeden prvek."""
        coils = sum(1 for _, e in self.members if e.symbol_id in COIL_SYMBOLS)
        duals = sum(1 for _, e in self.members if e.symbol_id in DUAL_ROLE)
        others = len(self.members) - coils - duals
        return coils > 1 or duals > 1 or others > 1 or (others >= 1 and coils + duals >= 1)

    def contact_items(self) -> list[tuple[Placed, str, list[str]]]:
        """Kontakty i póly stykače (secondary): [((list, prvek), druh, páry)…]."""
        out = []
        for s, e in [*self.secondary, *self.contacts]:
            out.append(((s, e), contact_kind(e) or KIND_NO, contact_pairs(e)))
        return out

    def used_pairs(self) -> list[str]:
        return [p for _, _, pairs in self.contact_items() for p in pairs]


@dataclass
class DeviceIndex:
    groups: dict[tuple[str, str, str], DeviceGroup] = field(default_factory=dict)
    by_element: dict[str, DeviceGroup] = field(default_factory=dict)
    by_ref: dict[str, list[DeviceGroup]] = field(default_factory=dict)
    project: Project | None = None
    _interrupts: dict | None = None

    @classmethod
    def build(cls, project) -> DeviceIndex:
        """Index přes `project.sheets` za O(N)."""
        idx = cls(project=project if isinstance(project, Project) else None)
        members: dict[tuple[str, str, str], list[Placed]] = {}
        contacts: list[Placed] = []
        for s in project.sheets:
            for e in s.elements:
                if is_contact(e):
                    if e.ref:
                        contacts.append((s, e))
                elif _host_candidate(e):
                    members.setdefault((*scope_key(s, e), e.ref), []).append((s, e))
        for key, ms in members.items():
            coils = [m for m in ms if m[1].symbol_id in COIL_SYMBOLS]
            duals = [m for m in ms if m[1].symbol_id in DUAL_ROLE]
            host = coils[0] if coils else ms[0]
            device = duals[0] if coils and duals else host
            g = DeviceGroup((key[0], key[1]), key[2], host, device, list(duals) if coils else [], [], list(ms))
            idx.groups[key] = g
            idx.by_ref.setdefault(key[2], []).append(g)
            for _, e in ms:
                idx.by_element[e.id] = g
        for s, c in contacts:
            g = idx.resolve(s, c)
            if g is not None:
                g.contacts.append((s, c))
                idx.by_element[c.id] = g
        return idx

    @classmethod
    def for_sheets(cls, sheets: list[Sheet]) -> DeviceIndex:
        """Index jen přes zadané listy (rozložení/teplo listu rozvaděče bez projektu)."""
        return cls.build(SimpleNamespace(sheets=list(sheets)))

    def resolve(self, sheet: Sheet | None, contact: Element) -> DeviceGroup | None:
        """Skupina, ke které kontakt patří: jediná se stejným ref, jinak ta ve stejném prostoru, jinak první."""
        cands = self.by_ref.get(contact.ref, []) if contact.ref else []
        if len(cands) <= 1:
            return cands[0] if cands else None
        if sheet is not None:
            g = self.groups.get((*scope_key(sheet, contact), contact.ref))
            if g is not None:
                return g
        return cands[0]

    def group_of(self, e: Element) -> DeviceGroup | None:
        return self.by_element.get(e.id)

    def is_bom_device(self, e: Element, sheet: Sheet | None = None) -> bool:
        """False pro cívku, když skupina má jinou položku výkazu (stykač); jinak True.

        Se `sheet` (položky jednoho listu – rozložení, teplo, výkaz/štítky listu) se cívka vynechá jen tehdy, když
        položka výkazu skupiny leží na **stejném** listu; stykač kreslený na jiném listu (silové schéma) cívku
        z listu rozvaděče neodstraní."""
        if e.symbol_id not in COIL_SYMBOLS:
            return True
        g = self.by_element.get(e.id)
        if g is None or g.device[1] is e or g.device[1].symbol_id in COIL_SYMBOLS:
            return True
        return sheet is not None and g.device[0] is not sheet

    def is_secondary(self, e: Element) -> bool:
        g = self.by_element.get(e.id)
        return g is not None and any(x is e for _, x in g.secondary)

    @property
    def interrupts(self) -> dict[str, list[Placed]]:
        """Skupiny přerušovacích bodů (počítá se jednou na index)."""
        if self._interrupts is None:
            self._interrupts = interrupt_groups(self.project) if self.project is not None else {}
        return self._interrupts


def next_contact_pair(group: DeviceGroup | None, kind: str) -> str:
    """Další volný pár druhu `kind`: první nepoužitý z kontaktního obrazu, jinak podle IEC (řadová číslice pomocných
    kontaktů je společná: 13/14, 21/22 → 33/34 / 31/32; silové 1/2, 3/4, 5/6…). Bez použitých = výchozí pár."""
    used = set(group.used_pairs()) if group is not None else set()
    image = contact_image(group) if group is not None else None
    if image:
        free = next((s.pair for s in image if s.kind == kind and s.pair not in used), "")
        if free:
            return free
    if kind == KIND_POWER:
        i = 1
        while f"{2 * i - 1}/{2 * i}" in used:
            i += 1
        return f"{2 * i - 1}/{2 * i}"
    aux = {p for p in used if classify_pair(p) in (KIND_NO, KIND_NC)}
    if not aux:
        return DEFAULT_PAIR.get(kind, "")
    seqs = {p[0] for p in aux}
    n = next(n for n in range(1, 100) if str(n) not in seqs)
    return f"{n}3/{n}4" if kind == KIND_NO else f"{n}1/{n}2"


# ---- odkaz na místo ------------------------------------------------------------------------------------------
def place_ref(project: Project, from_sheet: Sheet, from_target, to_sheet: Sheet, to_target) -> str:
    """Odkaz „/3.B4“ na místo cíle; aspekty cíle odlišné od zdroje se předřadí („+RDC1/3.B4“). Anonymní rozvaděč
    (list rozvaděče bez umístění) nemá kód umístění → jen „/3.B4“."""
    from envocad.model.frame import position_ref
    pos = position_ref(project, to_sheet, to_target.x, to_target.y)
    a, b = designation(from_sheet, from_target), designation(to_sheet, to_target)
    func = b.func if b.func != a.func else ""
    loc = b.loc if b.loc != a.loc else ""
    return str(Designation(func, loc)) + pos


# ---- zrcadlo kontaktů ----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MirrorRow:
    kind: str
    pair: str                 # „13/14“, „1/2“, „DO1“
    ref: str                  # „/3.B4“, „+RDC1/3.B4“; "" = rezerva z kontaktního obrazu
    sheet_id: str = ""
    element_id: str = ""

    @property
    def text(self) -> str:
        return f"{self.pair} {self.ref}" if self.ref else self.pair


@dataclass
class ContactMirror:
    host_id: str
    columns: dict[str, list[MirrorRow]] = field(default_factory=dict)   # jen neprázdné, v pořadí COLUMN_ORDER

    @property
    def empty(self) -> bool:
        return not any(self.columns.values())

    def rows(self) -> list[MirrorRow]:
        return [r for k in COLUMN_ORDER for r in self.columns.get(k, [])]


def contact_table(project: Project, host_sheet: Sheet, host: Element, index: DeviceIndex | None = None) -> ContactMirror:
    """Zrcadlo kontaktů hostitele: kontakty a póly stykače (řádek na pár svorek) + rezervy z kontaktního obrazu."""
    idx = index or DeviceIndex.build(project)
    out = ContactMirror(host.id)
    g = idx.group_of(host)
    if g is None or g.host[1] is not host:
        return out
    cols: dict[str, list[MirrorRow]] = {}
    used: set[str] = set()
    for (s, c), kind, pairs in g.contact_items():
        ref = place_ref(project, host_sheet, host, s, c)
        for pair in pairs:
            cols.setdefault(kind, []).append(MirrorRow(kind, pair, ref, s.id, c.id))
            used.add(pair)
    for slot in contact_image(g) or []:
        if slot.pair not in used:
            cols.setdefault(slot.kind, []).append(MirrorRow(slot.kind, slot.pair, ""))
            used.add(slot.pair)
    for k in COLUMN_ORDER:
        if cols.get(k):
            out.columns[k] = sorted(cols[k], key=lambda r: (natural_key(r.pair), natural_key(r.ref)))
    return out


HEADER_H = 5.0      # hlavička s piktogramem
ROW_PITCH = 3.0     # rozteč řádků
ROW_H = 1.8         # výška textu řádku
MIN_COL_W = 10.0


@dataclass
class MirrorGeometry:
    """Pole jako `frame.FrameGeometry` – kreslí se stejně (Qt `draw_frame`, DXF `_draw_geometry`)."""
    lines: list[tuple[float, float, float, float]] = field(default_factory=list)
    texts: list[tuple[float, float, str, float, str]] = field(default_factory=list)
    rects: list[tuple[float, float, float, float]] = field(default_factory=list)   # vždy prázdné (duck typing)
    boxes: list[Box] = field(default_factory=list)           # obálky textů pro textlayout / překryvy
    bounds: Box = (0.0, 0.0, 0.0, 0.0)

    @property
    def empty(self) -> bool:
        return not (self.lines or self.texts)


def _snap(v: float) -> float:
    return round(v / GRID) * GRID


def _floor_grid(v: float) -> float:
    return math.floor(v / GRID + 1e-9) * GRID


def _ceil_grid(v: float) -> float:
    return math.ceil(v / GRID - 1e-9) * GRID


# piktogramy hlavičky (svislý kontakt, souřadnice značek ctl.* zmenšené na 0,2)
_NO = [(0, 7.5, 0, 2.5), (0, -2.5, -3.5, 3.5), (0, -2.5, 0, -7.5)]
_NC = [(0, 7.5, 0, 2.5), (0, -2.5, 3.5, 3.5), (0, -2.5, 0, -7.5), (0, 2.5, 3, 2.5)]
_ARC = [(math.cos(math.radians(a)), 2.5 + math.sin(math.radians(a))) for a in range(0, 181, 45)]
_POWER = _NO + [(x1, y1, x2, y2) for (x1, y1), (x2, y2) in pairwise(_ARC)]
PICTOGRAM = {KIND_NO: _NO, KIND_NC: _NC, KIND_POWER: _POWER}


def mirror_geometry(e: Element, sym, mirror: ContactMirror) -> MirrorGeometry:
    """Tabulka zrcadla pod značkou: osa = střed obálky značky na mřížce, horní hrana 2,5 mm pod značkou (na mřížku
    dolů); vlevo silové a NO (NO u osy), vpravo NC; hlavička s piktogramem, řádky „pár odkaz“."""
    from envocad.model.textlayout import CHAR_W, symbol_box, text_box
    g = MirrorGeometry()
    if mirror.empty:
        g.bounds = (e.x, e.y, e.x, e.y)
        return g
    bx = symbol_box(e, sym)
    x0 = _snap((bx[0] + bx[2]) / 2)
    top = _floor_grid(bx[1] - GRID)
    width = {k: max(MIN_COL_W, _ceil_grid(max(len(r.text) for r in rows) * CHAR_W * ROW_H + 2))
             for k, rows in mirror.columns.items()}
    cols: dict[str, float] = {}             # druh → levý okraj sloupce
    x = x0
    for k in (KIND_NO, KIND_POWER):
        if k in mirror.columns:
            x -= width[k]
            cols[k] = x
    if KIND_NC in mirror.columns:
        cols[KIND_NC] = x0
    xmin = min(cols.values())
    xmax = max(cols[k] + width[k] for k in cols)
    nrows = max(len(rows) for rows in mirror.columns.values())
    bottom = top - HEADER_H - ROW_PITCH * nrows
    g.lines.append((xmin, top - HEADER_H, xmax, top - HEADER_H))
    edges = {x0} | {cols[k] for k in cols} | {cols[k] + width[k] for k in cols}
    for ex in sorted(edges):
        if ex == x0 or xmin < ex < xmax:
            g.lines.append((ex, top, ex, bottom))
    cy = top - HEADER_H / 2
    for k, rows in mirror.columns.items():
        cx = cols[k] + width[k] / 2
        g.lines += [(cx + 0.2 * x1, cy + 0.2 * y1, cx + 0.2 * x2, cy + 0.2 * y2) for x1, y1, x2, y2 in PICTOGRAM[k]]
        for i, r in enumerate(rows):
            ty = top - HEADER_H - ROW_PITCH * (i + 1) + 0.6
            g.texts.append((cols[k] + 1.0, ty, r.text, ROW_H, "left"))
            g.boxes.append(text_box(cols[k] + 1.0, ty, r.text, ROW_H))
    g.bounds = (xmin, bottom, xmax, top)
    return g


def mirror_enabled(e: Element) -> bool:
    """`attrs["mirror"] == "0"` zrcadlo potlačí."""
    return str(e.attrs.get("mirror", "")).strip() != "0"


def is_mirror_host(project: Project, sheet: Sheet, e: Element, index: DeviceIndex | None = None) -> bool:
    """Je prvek hostitelem zrcadla kontaktů (hostitel skupiny s ≥1 kontaktem nebo zadaným kontaktním obrazem)?
    Nezávisí na `mirror` – podle toho panel Vlastnosti nabídne zaškrtávátko „Zobrazit zrcadlo kontaktů“."""
    idx = index or DeviceIndex.build(project)
    g = idx.group_of(e)
    if g is None or g.host[1] is not e:
        return False
    return not contact_table(project, sheet, e, idx).empty


def sheet_mirrors(project: Project, sheet: Sheet, lib, index: DeviceIndex | None = None,
                  symbols: dict | None = None) -> dict[str, MirrorGeometry]:
    """Zrcadla všech hostitelů na listu: {id hostitele: geometrie}. `symbols` = již načtené značky {id prvku: Symbol}."""
    from envocad.model.project import element_symbol
    idx = index or DeviceIndex.build(project)
    out: dict[str, MirrorGeometry] = {}
    for e in sheet.elements:
        g = idx.group_of(e)
        if g is None or g.host[1] is not e or not mirror_enabled(e):
            continue
        table = contact_table(project, sheet, e, idx)
        if table.empty:
            continue
        sym = (symbols or {}).get(e.id) or element_symbol(project, e, lib)
        geom = mirror_geometry(e, sym, table)
        if not geom.empty:
            out[e.id] = geom
    return out


# ---- přerušovací body ----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class InterruptLink:
    mode: str                           # alone | pair | chain | star_source | star_target
    prev: Placed | None = None
    next: Placed | None = None
    source: Placed | None = None
    targets: tuple = ()


def interrupt_groups(project: Project) -> dict[str, list[Placed]]:
    """Přerušovací body podle označení (celý projekt), seřazené (index listu, x, −y, id)."""
    out: dict[str, list[tuple[tuple, Placed]]] = {}
    for si, s in enumerate(project.sheets):
        for e in s.elements:
            if e.symbol_id == INTERRUPT_SYMBOL and e.ref:
                out.setdefault(e.ref, []).append(((si, e.x, -e.y, e.id), (s, e)))
    return {ref: [m for _, m in sorted(ms, key=lambda km: km[0])] for ref, ms in out.items()}


def is_star_source(e: Element) -> bool:
    return str(e.attrs.get("star_source", "")).strip() == "1"


def interrupt_link(project: Project, sheet: Sheet, e: Element, groups: dict | None = None) -> InterruptLink:
    """Vazba přerušovacího bodu: bod se `star_source="1"` ve skupině → hvězda (zdroj = první takový), jinak řetěz
    (2 body = dvojice)."""
    del sheet  # poloha bodu ve skupině je daná řazením; parametr pro shodné rozhraní s interrupt_xref
    if e.symbol_id != INTERRUPT_SYMBOL or not e.ref:
        return InterruptLink("alone")
    groups = groups if groups is not None else interrupt_groups(project)
    members = groups.get(e.ref, [])
    i = next((k for k, (_, o) in enumerate(members) if o is e), None)
    if i is None or len(members) < 2:
        return InterruptLink("alone")
    src = next((m for m in members if is_star_source(m[1])), None)
    if src is not None:
        if src[1] is e:
            return InterruptLink("star_source", targets=tuple(m for m in members if m[1] is not e))
        return InterruptLink("star_target", source=src)
    prev = members[i - 1] if i > 0 else None
    nxt = members[i + 1] if i + 1 < len(members) else None
    return InterruptLink("pair" if len(members) == 2 else "chain", prev=prev, next=nxt)


STAR_PER_LINE = 3


def interrupt_xref(project: Project, sheet: Sheet, e: Element, groups: dict | None = None) -> str:
    """Text odkazu přerušovacího bodu: dvojice „→ /2.C3“, řetěz „← /1.A2“ + „→ /4.C1“, zdroj hvězdy
    „→ /2.A2, /3.B1, /4.C5“ (max 3 na řádek), cíl hvězdy „← /1.F3“, osamělý „→ ?“."""
    link = interrupt_link(project, sheet, e, groups)

    def ref(m: Placed) -> str:
        return place_ref(project, sheet, e, m[0], m[1])

    if link.mode == "pair":
        return "→ " + ref(link.next or link.prev)
    if link.mode == "chain":
        return "\n".join(t for t in ((link.prev and "← " + ref(link.prev)), (link.next and "→ " + ref(link.next))) if t)
    if link.mode == "star_target":
        return "← " + ref(link.source)
    if link.mode == "star_source":
        refs = [ref(m) for m in link.targets]
        chunks = [refs[i:i + STAR_PER_LINE] for i in range(0, len(refs), STAR_PER_LINE)]
        lines = [("→ " if k == 0 else "  ") + ", ".join(c) + ("," if k + 1 < len(chunks) else "")
                 for k, c in enumerate(chunks)]
        return "\n".join(lines)
    return "→ ?"


def interrupt_partner_of(link: InterruptLink) -> Placed | None:
    """Jeden protějšek pro zpětnou kompatibilitu: next, jinak prev, jinak zdroj, jinak první cíl."""
    return link.next or link.prev or link.source or (link.targets[0] if link.targets else None)
