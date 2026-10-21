"""Výrobní data rozvaděče (`model/wiring.py`, `multipole.device_terminal`, výkaz „Výrobní zapojovací seznam“)."""
import pytest

from envocad.export import reports
from envocad.library.store import LibraryStore
from envocad.library.templates import apply_template
from envocad.model.multipole import device_terminal
from envocad.model.project import (
    FORMAT_VERSION,
    SWITCHBOARD_WIRE_ATTRIBUTES,
    Element,
    Layout,
    Project,
    Sheet,
    Wire,
    WireEnd,
)
from envocad.model.wiring import (
    FERRULE_DIN46228,
    FLEXIBLE_WIRE_TYPES,
    IN_TO_CROSS,
    NUMBER_NOTE,
    UNPLACED_LABELS,
    WIRING_DEFAULTS,
    WIRING_PARAMS,
    Ferrule,
    TerminalPoint,
    WiringParams,
    conductor_color,
    conductor_end,
    end_for,
    ferrule_for,
    is_flexible,
    param_sources,
    production_wires,
    route_length_mm,
    terminal_point,
    wire_cross,
    wire_end_labels,
)
from envocad.model.xref import DeviceIndex

AC = ["L1", "L2", "L3", "N", "PE"]


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _layout(**params) -> Layout:
    # 2 řady po 24 modulech (šířka lišty 420 mm), rozteč řad 150 mm
    return Layout(rows=2, modules_per_row=24, params={"row_pitch_mm": "150", **params})


def _sb(project: Project | None = None) -> tuple[Project, Sheet]:
    p = project or Project()
    s = Sheet(name="RDC1", kind="switchboard", loc="RDC1", layout=_layout())
    p.sheets.append(s)
    return p, s


def _el(s: Sheet, sid: str, ref: str, row=None, pos=None, **attrs) -> Element:
    e = Element(sid, attrs={"ref": ref, **{k: str(v) for k, v in attrs.items()}})
    s.elements.append(e)
    if row is not None:
        s.layout.set_placement(e.id, row, pos)
    return e


def _w(s: Sheet, a: Element, pa: str, b: Element, pb: str, conductors, **attrs) -> Wire:
    w = Wire(WireEnd(a.id, pa), WireEnd(b.id, pb), conductors=list(conductors), attrs=dict(attrs))
    s.wires.append(w)
    return w


# ---- trasa ------------------------------------------------------------------------------------------------------
def test_route_same_duct():
    lay, prm = _layout(), WiringParams()
    a, b = TerminalPoint(10, -52.5, 0, False), TerminalPoint(100, -52.5, 0, False)
    # ruční výpočet: svisle do žlabu 0 (y = 0) 52,5 + 52,5 = 105; vodorovně |10 − 100| = 90; + 2 × 100 (konce)
    # = 395; × 1,10 (rezerva) = 434,5 → nahoru na 50 = 450
    assert route_length_mm(a, b, lay, prm) == 450


def test_route_via_shorter_side_duct():
    lay, prm = _layout(), WiringParams()
    a = TerminalPoint(10, -52.5, 0, False)        # horní svorka řady 0 → žlab 0 (y = 0)
    b = TerminalPoint(400, -247.5, 2, False)      # dolní svorka řady 1 (osa −225) → žlab 2 (y = −300)
    # svisle do žlabů: 52,5 + 52,5 = 105; levý žlab x = −25: 35 + 425 = 460, pravý x = 445: 435 + 45 = 480 → 460;
    # mezi žlaby 300; 105 + 460 + 300 + 200 = 1065; × 1,1 = 1171,5 → 1200
    assert route_length_mm(a, b, lay, prm) == 1200
    # pravý žlab je kratší, když jsou oba konce vpravo
    a2 = TerminalPoint(410, -52.5, 0, False)
    # 105 + (35 + 45) + 300 + 200 = 685; × 1,1 = 753,5 → 800
    assert route_length_mm(a2, b, lay, prm) == 800


def test_route_rounding_exact_multiple():
    prm = WiringParams(end_mm=0, reserve_pct=0, round_mm=50)
    a, b = TerminalPoint(0, 0, 0, False), TerminalPoint(100, 0, 0, False)
    assert route_length_mm(a, b, _layout(), prm) == 100
    assert route_length_mm(a, TerminalPoint(101, 0, 0, False), _layout(), prm) == 150


# ---- svorky -----------------------------------------------------------------------------------------------------
def test_device_terminal_rules():
    _, s = _sb()
    bus = _el(s, "sb.busbar", "1")
    f = _el(s, "fve.breaker_mcb", "F2", in_=32, poles=3, modules=3)
    spd = _el(s, "fve.spd", "F1", poles=4, modules=4)
    x = Element("sb.terminal_block", attrs={"ref": "X2", "terminal": "6 7 8 9 10"})
    s.elements.append(x)
    w_in = _w(s, bus, "3", f, "1", AC)
    w_out = _w(s, f, "2", x, "1", AC)
    w_spd = _w(s, bus, "1", spd, "L", AC[:4])
    assert device_terminal(s, w_in, "L1", "b") == ("F2:1", True)
    assert device_terminal(s, w_in, "L2", "b") == ("F2:3", True)
    assert device_terminal(s, w_in, "L3", "b") == ("F2:5", True)
    assert device_terminal(s, w_out, "L2", "a") == ("F2:4", True)
    assert device_terminal(s, w_in, "N", "b") == ("F2:N", True)
    assert device_terminal(s, w_in, "PE", "b") == ("F2:PE", True)
    assert device_terminal(s, w_out, "L3", "b") == ("X2:8", False)       # svorkový prvek – čísla svorek
    assert device_terminal(s, w_spd, "L2", "b") == ("F1:L", False)       # jiné porty než 1/2 → jméno portu
    assert device_terminal(s, w_in, "L1", "a") == ("1:3", False)         # sběrnice není průchozí přístroj
    w_in.terminals = {"L1": {"b": "F2:11"}}
    assert device_terminal(s, w_in, "L1", "b") == ("F2:11", False)       # ruční přiřazení má přednost


def test_device_terminal_dc_and_single_wires():
    _, s = _sb()
    x = _el(s, "sb.feed", "X1", dir="in")
    d = _el(s, "fve.fuse_disconnect", "F1", poles=2, modules=2)
    w = _w(s, x, "1", d, "1", ["DC+", "DC-"])
    assert device_terminal(s, w, "DC+", "b") == ("F1:1", True)
    assert device_terminal(s, w, "DC-", "b") == ("F1:3", True)
    # tři jednožilové vodiče na port 1 – pól podle pořadí žil všech vodičů portu
    f = _el(s, "fve.breaker_mcb", "F3", poles=3, modules=3)
    ws = [_w(s, x, "1", f, "1", [c]) for c in ("L1", "L2", "L3")]
    assert [device_terminal(s, w, w.conductors[0], "b")[0] for w in ws] == ["F3:1", "F3:3", "F3:5"]


def test_terminal_point_three_pole_breaker(lib):
    p, s = _sb()
    bus = _el(s, "sb.busbar", "1")
    f = _el(s, "fve.breaker_mcb", "F2", row=0, pos=2, in_=32, poles=3, modules=3)
    _w(s, bus, "3", f, "1", AC)
    prm, idx = WiringParams(), DeviceIndex.build(p)
    # šířka 3 × 17,5 = 52,5 mm, pól 17,5 mm; začátek 2 × 17,5 = 35
    pt = terminal_point(p, s, f, "1", "L2", "F2:3", prm, idx)
    assert pt == TerminalPoint(35 + 1.5 * 17.5, -75 + 22.5, 0, False)   # pól 2 nahoře, osa řady −75
    pt = terminal_point(p, s, f, "2", "L3", "F2:6", prm, idx)
    assert pt == TerminalPoint(35 + 2.5 * 17.5, -75 - 22.5, 1, False)   # pól 3 dole → žlab 1
    # N (nečíselné) → pořadí žíly na portu (3), omezené na poslední pól; strana podle směru portu
    pt = terminal_point(p, s, f, "1", "N", "F2:N", prm, idx, lib)
    assert pt.x == pytest.approx(35 + 2.5 * 17.5) and pt.duct == 0


def test_coil_position_via_contactor(lib):
    p, s = _sb()
    _el(s, "fve.contactor", "K1", row=1, pos=0, poles=3, modules=3)
    coil = _el(s, "ctl.coil", "K1", modules=3)
    f = _el(s, "fve.fuse", "F9", row=1, pos=4, in_=6, poles=1, modules=1)
    w = _w(s, f, "2", coil, "A1", ["L"])
    _w(s, coil, "A2", f, "1", ["N"])
    assert s.layout.placement(coil.id) is None
    prm, idx = WiringParams(), DeviceIndex.build(p)
    a1 = terminal_point(p, s, coil, "A1", "L", "K1:A1", prm, idx, lib)
    # stykač na řadě 1 (osa −225), pozice 0: x = 0,5 × 52,5 / 3 = 8,75; A1 nahoře (port N)
    assert a1 == TerminalPoint(8.75, -225 + 22.5, 1, False)
    a2 = terminal_point(p, s, coil, "A2", "N", "K1:A2", prm, idx, lib)
    assert a2.duct == 2 and a2.y == -225 - 22.5
    # bez knihovny podle jména portu (A1 lichý = nahoře)
    assert terminal_point(p, s, coil, "A1", "L", "K1:A1", prm, idx) == a1
    pw = next(x for x in production_wires(p, s, {}) if x.wire_id == w.id)
    assert pw.cross == 1.5 and pw.cross_source == "jištění"     # pojistka 6 A → 1,5 mm² (ne řízení 1 mm²)
    # F9:2 (dole, žlab 2, x = 4 × 17,5 + 8,75 = 78,75, y = −247,5) → K1:A1 (nahoře, žlab 1, x = 8,75, y = −202,5):
    # svisle 52,5 + 52,5 = 105; levý žlab (−25): 103,75 + 33,75 = 137,5; mezi žlaby 150;
    # 105 + 137,5 + 150 + 200 = 592,5; × 1,1 = 651,75 → 700
    assert pw.length_mm == 700


def test_unplaced_ends(lib):
    p, s = _sb()
    bus = _el(s, "sb.busbar", "1")
    f = _el(s, "fve.breaker_mcb", "F2", row=0, pos=0, in_=16, poles=1, modules=1)
    f5 = _el(s, "fve.breaker_mcb", "F5", in_=16, poles=1, modules=1)                 # neumístěn
    out = _el(s, "sb.feed", "X3", dir="out")
    j = _el(s, "sb.junction", "")
    w1 = _w(s, bus, "1", f, "1", ["L1"])
    w2 = _w(s, f, "2", out, "1", ["L1"])
    w3 = _w(s, f5, "2", out, "1", ["L2"])
    w4 = _w(s, j, "S", f, "1", ["N"])
    prm, idx = WiringParams(), DeviceIndex.build(p)
    assert terminal_point(p, s, bus, "1", "L1", "1:1", prm, idx) == TerminalPoint(210, 0, 0, True)
    assert terminal_point(p, s, out, "1", "L1", "X3:1", prm, idx) == TerminalPoint(210, -300, 2, True)
    assert terminal_point(p, s, j, "S", "N", ":S", prm, idx) is None
    assert terminal_point(p, s, f5, "2", "L2", "F5:2", prm, idx) is None
    rows = {pw.wire_id: pw for pw in production_wires(p, s, {}, lib)}
    # F2:1 (x 8,75, y −52,5, žlab 0) → sběrnice odhadem (210, 0, žlab 0): 52,5 + 201,25 + 200 = 453,75 × 1,1 → 500
    assert rows[w1.id].length_mm == 500 and "délka odhadem – sběrnice 1" in rows[w1.id].notes
    assert rows[w2.id].length_mm and "délka odhadem – X3 neumístěn" in rows[w2.id].notes
    assert rows[w3.id].length_mm is None and "neumístěno: F5" in rows[w3.id].notes
    assert rows[w4.id].length_mm is None and "konec v uzlu odbočky" in rows[w4.id].notes
    # odhad vypnutý v parametrech skříně
    s.layout.params["wire_unplaced"] = "none"
    rows = {pw.wire_id: pw for pw in production_wires(p, s, {}, lib)}
    assert rows[w2.id].length_mm is None and "neumístěno: X3" in rows[w2.id].notes


# ---- průřez, barva, koncovky ------------------------------------------------------------------------------------
def test_wire_cross_sources():
    p, s = _sb()
    prm = WiringParams()
    bus = _el(s, "sb.busbar", "1", in_=80)
    spd = _el(s, "fve.spd", "F1")
    f16 = _el(s, "fve.breaker_mcb", "F2", in_=16)
    f32 = _el(s, "fve.breaker_mcb", "F3", in_="32")
    f6 = _el(s, "fve.breaker_mcb", "F4", in_="6")
    big = _el(s, "fve.breaker_mccb", "Q2", in_="200")
    coil = _el(s, "ctl.coil", "K1")
    pe = _el(s, "sb.pe_bar", "X9")
    assert wire_cross(p, s, _w(s, f16, "2", f32, "1", AC, cross="2,5"), prm) == (2.5, "vodič")
    assert wire_cross(p, s, _w(s, f16, "2", f32, "1", AC), prm) == (2.5, "jištění")      # min(16, 32) → 2,5
    assert wire_cross(p, s, _w(s, bus, "3", f32, "1", AC), prm) == (6.0, "jištění")      # sběrnice se nepočítá
    assert wire_cross(p, s, _w(s, bus, "1", spd, "L", AC), prm) == (None, "SPD")         # SPD bez výchozího
    assert wire_cross(p, s, _w(s, f6, "2", coil, "A1", ["L"]), prm) == (1.5, "jištění")
    assert wire_cross(p, s, _w(s, f6, "2", f6, "1", ["L"]), WiringParams(cross_min=2.5)) == (2.5, "jištění")
    assert wire_cross(p, s, _w(s, coil, "A2", pe, "1", ["N"]), prm) == (1.0, "řízení")
    assert wire_cross(p, s, _w(s, big, "2", pe, "1", ["L1"]), prm) == (None, "jištění")
    assert IN_TO_CROSS[0] == (10, 1.5) and IN_TO_CROSS[-1] == (160, 70)


def test_conductor_color():
    single = Wire(WireEnd("a", "1"), WireEnd("b", "1"), conductors=["PE"], attrs={"color": "černá"})
    multi = Wire(WireEnd("a", "1"), WireEnd("b", "1"), conductors=AC, attrs={"color": "černá"})
    plain = Wire(WireEnd("a", "1"), WireEnd("b", "1"), conductors=AC)
    assert conductor_color(single, "PE") == "černá"                 # jednožilový vždy
    assert conductor_color(multi, "L2") == "černá"
    assert conductor_color(multi, "N") == "modrá" and conductor_color(multi, "PE") == "zelenožlutá"
    assert [conductor_color(plain, c) for c in AC] == ["hnědá", "černá", "šedá", "modrá", "zelenožlutá"]


def test_ferrules_and_ends():
    f = ferrule_for(1.5)
    assert f == Ferrule(1.5, 8, "černá") and f.text() == "dutinka 1,5/8 černá"
    assert ferrule_for(1.5, twin=True).text() == "dvojitá dutinka 2×1,5/8 černá"
    assert ferrule_for(0.75).text() == "dutinka 0,75/8 šedá"
    assert ferrule_for(70) is None and ferrule_for(None) is None
    assert set(FERRULE_DIN46228) >= {0.5, 1.5, 2.5, 4, 6, 10, 16, 25, 35, 50}
    w = Wire(WireEnd("a", "1"), WireEnd("b", "1"), conductors=["L1"])
    assert end_for(w, "a", 2.5, "H07V-K") == ("dutinka 2,5/8 modrá", Ferrule(2.5, 8, "modrá"))
    assert end_for(w, "a", 2.5, "H07V-U") == ("", None)              # tuhý vodič bez dutinky
    assert end_for(w, "a", 2.5, "LiYY 3x1")[0].startswith("dutinka")
    w.attrs = {"end_a": "-", "end_b": "kabelové oko M8"}
    assert end_for(w, "a", 2.5, "H07V-K") == ("", None)
    assert end_for(w, "b", 2.5, "H07V-K") == ("kabelové oko M8", None)


def test_twin_ferrule_and_three_wires(lib):
    p, s = _sb()
    spd = _el(s, "fve.breaker_mcb", "F1", row=0, pos=0, modules=1, poles=1, in_=10)
    f = _el(s, "fve.breaker_mcb", "F2", row=0, pos=4, modules=1, poles=1, in_=10)   # 10 A → 1,5 mm² jako F1
    pe = _el(s, "sb.pe_bar", "X9")
    w1 = _w(s, spd, "2", pe, "1", ["PE"])
    w2 = _w(s, f, "2", pe, "1", ["PE"])
    rows = {pw.wire_id: pw for pw in production_wires(p, s, {}, lib)}
    for w in (w1, w2):
        assert rows[w.id].end_to == "dvojitá dutinka 2×1,5/8 černá"
        assert rows[w.id].ferrule_to.twin and not rows[w.id].ferrule_from.twin
    w3 = _w(s, f, "1", pe, "1", ["PE"])
    rows = {pw.wire_id: pw for pw in production_wires(p, s, {}, lib)}
    assert "3 žíly ve svorce +RDC1-X9:1 – ověřit" in rows[w3.id].notes
    assert not rows[w3.id].ferrule_to.twin
    # žíly jednoho vodiče na svorce pojmenované portem (SPD „L“) nejsou dvojice
    bus = _el(s, "sb.busbar", "1")
    spd4 = _el(s, "fve.spd", "F7", row=1, pos=0, modules=4, poles=4)
    w4 = _w(s, bus, "1", spd4, "L", AC[:4])
    assert not any(pw.ferrule_to and pw.ferrule_to.twin or pw.ferrule_from and pw.ferrule_from.twin
                   for pw in production_wires(p, s, {}, lib) if pw.wire_id == w4.id)


# ---- seznam ------------------------------------------------------------------------------------------------------
def test_production_wires_filter_sort_numbers(lib):
    p, s = _sb()
    p.sheets[0].wires.append(Wire(WireEnd("x", "1"), WireEnd("y", "1")))      # list JPS se nevypisuje
    out = _el(s, "sb.feed", "X3", dir="out")
    f3 = _el(s, "fve.breaker_mcb", "F3", row=1, pos=0, in_=16, poles=3, modules=3)
    f2 = _el(s, "fve.breaker_mcb", "F2", row=0, pos=3, in_=16, poles=3, modules=3)
    q = _el(s, "sb.main_switch", "Q1", row=0, pos=0, in_=63, poles=4, modules=4)
    w_out = _w(s, out, "1", f3, "2", AC[:3], ref="W7")    # neumístěný konec první v datech → prohodí se
    _w(s, q, "2", f2, "1", AC[:3])
    _w(s, q, "2", f3, "1", AC[:3], prod="0")              # vyřazený z výrobního seznamu
    rows = production_wires(p, None, {}, lib)
    assert [r.number for r in rows] == list(range(1, 7))
    assert all(r.sheet == "RDC1" for r in rows)
    assert [r.from_text for r in rows] == ["+RDC1-Q1:2", "+RDC1-Q1:4", "+RDC1-Q1:6",
                                           "+RDC1-F3:2", "+RDC1-F3:4", "+RDC1-F3:6"]
    assert [r.to_text for r in rows][:3] == ["+RDC1-F2:1", "+RDC1-F2:3", "+RDC1-F2:5"]
    swapped = [r for r in rows if r.wire_id == w_out.id]
    assert [r.to_text for r in swapped] == ["+RDC1-X3:1", "+RDC1-X3:2", "+RDC1-X3:3"]
    assert swapped[0].ref == "W7" and swapped[0].wire_type == "H07V-K"


def test_bypassed_neutral_note(lib):
    p, s = _sb()
    bus = _el(s, "sb.busbar", "1")
    f = _el(s, "fve.breaker_mcb", "F2", row=0, pos=0, in_=16, poles=3, modules=3)
    q = _el(s, "sb.main_switch", "Q1", row=0, pos=3, in_=63, poles=4, modules=4)
    _w(s, bus, "1", f, "1", AC)
    _w(s, bus, "2", q, "1", AC[:4])
    n_f = next(r for r in production_wires(p, s, {}, lib) if "F2:N" in (r.from_text + r.to_text))
    assert "N nespínaný – ve skutečnosti vede kolem F2" in n_f.notes
    n_q = next(r for r in production_wires(p, s, {}, lib) if "Q1:7" in (r.from_text + r.to_text))
    assert n_q.conductor == "N" and not any("nespínaný" in n for n in n_q.notes)   # 4p vypínač spíná N (7/8)


def test_params_priority_and_sources():
    lay = _layout(wire_end_mm="150", wire_type="", wire_round_mm="abc")
    base = {"wire_end_mm": 120, "wire_reserve_pct": "5", "wire_type": "H05V-K", "wire_unplaced": "none"}
    prm = WiringParams.resolve(lay, base)
    assert prm.end_mm == 150            # rozvaděč > standard
    assert prm.reserve_pct == 5         # standard > výchozí
    assert prm.wire_type == "H05V-K"    # prázdná hodnota v rozvaděči se nepoužije
    assert prm.round_mm == 50           # neplatná hodnota → výchozí
    assert prm.unplaced == "none"
    assert WiringParams.resolve(None) == WiringParams()
    assert WiringParams.resolve(Layout(params={"wire_cross_min": "2,5"})).cross_min == 2.5
    assert [k for k, _, _ in WIRING_PARAMS] == list(WIRING_DEFAULTS)
    assert all(k.startswith("wire_") for k in WIRING_DEFAULTS)
    # výchozí texty odpovídají výchozím hodnotám dataclass
    assert WiringParams.resolve(Layout(params=dict(WIRING_DEFAULTS))) == WiringParams()
    src = {k: (v, z) for k, _, v, z in param_sources(lay, base)}
    assert src["wire_end_mm"] == ("150", "rozvaděč") and src["wire_reserve_pct"] == ("5", "firemní standard")
    assert src["wire_cross_min"] == ("1,5", "výchozí")


def test_template_production_list(lib):
    """Šablona AC rozvaděče: odvozené svorky jističů a délka F2:1 → sběrnice podle ručního výpočtu."""
    p, s = _sb()
    s.layout = Layout()
    apply_template(p, s, "ac_fve", {"n_out": "2"})
    head, rows = reports.production_wiring_list(p, lib, s, {})
    col = {h: i for i, h in enumerate(head)}
    r = next(r for r in rows if r[col["Odkud"]] == "+RDC1-F2:1")
    assert r[col["Kam"]] == "+RDC1-1L1" and r[col["Průřez [mm²]"]] == 6 and r[col["Žíla"]] == "L1"
    # Q1 (4 M) poz. 0, F1 = SPD (4 M) poz. 4, F2 (3 M) poz. 8; rozteč řad (500 − 50) / 3 = 150
    # F2:1: x = 8 × 17,5 + 0,5 × 52,5 / 3 = 148,75, y = −75 + 22,5 = −52,5 (žlab 0);
    # sběrnice odhadem uprostřed žlabu 0: x = 24 × 17,5 / 2 = 210, y = 0
    # 52,5 + |148,75 − 210| + 200 = 313,75; × 1,1 = 345,125 → 350
    assert r[col["Délka [mm]"]] == 350 and isinstance(r[col["Délka [mm]"]], int)
    assert r[col["Koncovka odkud"]] == "dutinka 6/12 žlutá"
    assert "délka odhadem – sběrnice 1" in r[col["Poznámka"]]
    assert [x[col["Č."]] for x in rows] == list(range(1, len(rows) + 1))
    sub = reports.production_subtitle(p, s, {})
    assert "přídavek na konec 100 mm" in sub[0] and "2k+1" in sub[-2]
    assert sub[-1] == NUMBER_NOTE and "může změnit" in sub[-1]


def test_wiring_list_color_on_switchboard(lib):
    p, s = _sb()
    f = _el(s, "fve.breaker_mcb", "F2", in_=16, poles=1, modules=1)
    x = _el(s, "sb.feed", "X3", dir="out")
    _w(s, f, "2", x, "1", ["L1", "N"], color="černá")
    head, rows = reports.wiring_list(p, lib, s)
    ci = head.index("Barva")
    assert [r[ci] for r in rows] == ["černá", "modrá"]


def test_not_in_doc():
    assert "Výrobní zapojovací seznam" in reports.NOT_IN_DOC
    names = [n for n, _ in reports.ALL_REPORTS]
    assert names.index("Výrobní zapojovací seznam") == names.index("Zapojovací seznam") + 1


def test_switchboard_wire_attrs_roundtrip(tmp_path):
    assert [a.key for a in SWITCHBOARD_WIRE_ATTRIBUTES] == ["color", "end_a", "end_b", "prod"]
    p, s = _sb()
    f = _el(s, "fve.breaker_mcb", "F2")
    x = _el(s, "sb.feed", "X3", dir="out")
    attrs = {"color": "černá", "end_a": "-", "end_b": "kabelové oko M6", "prod": "0", "cross": "4"}
    w = _w(s, f, "2", x, "1", ["L1"], **attrs)
    s.layout.params.update({"wire_type": "H05V-K", "wire_end_mm": "80"})
    path = tmp_path / "v.ecp"
    p.save(path)
    import json
    assert json.loads(path.read_text(encoding="utf-8"))["format_version"] == FORMAT_VERSION == 15
    q = Project.load(path)
    s2 = q.sheets[-1]
    assert s2.wires[0].attrs == attrs and s2.wires[0].id == w.id
    assert s2.layout.params["wire_type"] == "H05V-K" and s2.layout.params["wire_end_mm"] == "80"
    assert WiringParams.resolve(s2.layout).end_mm == 80


# ---- opravy z review ---------------------------------------------------------------------------------------------
def _rows(p, s, lib):
    return production_wires(p, s, {}, lib)


def test_busbar_end_is_potential(lib):
    """(1) Sběrnice v textu konce jako potenciál {ref}{žíla} s aspekty, poznámka „sběrnice 1“."""
    p, s = _sb()
    bus = _el(s, "sb.busbar", "1")
    f = _el(s, "fve.breaker_mcb", "F2", row=0, pos=0, in_=16, poles=1, modules=1)
    w = _w(s, bus, "T1", f, "1", ["L2"])
    pw = next(r for r in _rows(p, s, lib) if r.wire_id == w.id)
    assert "+RDC1-1L2" in (pw.from_text, pw.to_text) and "1:T1" not in pw.from_text + pw.to_text
    assert "délka odhadem – sběrnice 1" in pw.notes and not any("1 neumístěn" in n for n in pw.notes)
    assert conductor_end(p, s, w, "L2", "a").origin == "sběrnice"
    s.layout.params["wire_unplaced"] = "none"
    pw = next(r for r in _rows(p, s, lib) if r.wire_id == w.id)
    assert "neumístěno: sběrnice 1" in pw.notes and pw.length_mm is None


def test_port_with_several_conductors_adds_conductor(lib):
    """(2) Nečíselný port s více žilami (SPD „L“) → „F1:L1“, „F1:N“; jedna žíla → jméno portu; číselný → „3/L1“."""
    p, s = _sb()
    bus = _el(s, "sb.busbar", "1")
    spd = _el(s, "fve.spd", "F1", row=0, pos=0, poles=4, modules=4)
    w = _w(s, bus, "1", spd, "L", AC[:4])
    assert [conductor_end(p, s, w, c, "b").text for c in AC[:4]] == \
        ["+RDC1-F1:L1", "+RDC1-F1:L2", "+RDC1-F1:L3", "+RDC1-F1:N"]
    spd1 = _el(s, "fve.spd", "F8", poles=1)
    w1 = _w(s, bus, "2", spd1, "L", ["L1"])
    assert conductor_end(p, s, w1, "L1", "b").text == "+RDC1-F8:L"
    dev = _el(s, "x.device", "U1")
    w2 = _w(s, bus, "4", dev, "3", ["L1", "N"])
    assert conductor_end(p, s, w2, "N", "b").terminal == "U1:3/N"
    # konec podle portu s více žilami: klíč svorky po žílách → žádná dvojitá dutinka mezi L1 a N
    rows = [r for r in _rows(p, s, lib) if r.wire_id == w.id]
    assert len({r.to_text for r in rows} | {r.from_text for r in rows}) == 8


def test_bypass_merged_into_one_row(lib):
    """(3) PE a N vedené kolem 3p jističe: jeden řádek vnější konec ↔ vnější konec, délka mezi nimi."""
    p, s = _sb()
    bus = _el(s, "sb.busbar", "1")
    f = _el(s, "fve.breaker_mcb", "F2", row=0, pos=0, in_=16, poles=3, modules=3)
    x = _el(s, "sb.feed", "X3", dir="out")
    w_in = _w(s, bus, "3", f, "1", AC)
    w_out = _w(s, f, "2", x, "1", AC)
    rows = _rows(p, s, lib)
    assert len(rows) == 8                                   # 10 úseků, N a PE sloučeny
    pe = next(r for r in rows if r.conductor == "PE")
    assert (pe.from_text, pe.to_text) == ("+RDC1-1PE", "+RDC1-X3:5")
    assert "vede kolem F2" in pe.notes and not any("F2:" in t for t in (pe.from_text, pe.to_text))
    assert set(pe.wire_ids) == {w_in.id, w_out.id}
    assert pe.end_from == pe.end_to == "dutinka 2,5/8 modrá"
    # délka mezi vnějšími konci: sběrnice (210, 0, žlab 0) ↔ X3 (210, −300, žlab 2): svisle 300 přes kratší boční
    # žlab (2 × 235) + 200 = 970; × 1,1 = 1067 → 1100
    assert pe.length_mm == 1100
    n = next(r for r in rows if r.conductor == "N")
    assert (n.from_text, n.to_text) == ("+RDC1-1N", "+RDC1-X3:4") and "vede kolem F2" in n.notes
    # řetěz přes dva přístroje
    f5 = _el(s, "fve.breaker_mcb", "F5", row=0, pos=3, in_=16, poles=3, modules=3)
    w_out.b = WireEnd(f5.id, "1")
    _w(s, f5, "2", x, "1", AC)
    pe = next(r for r in _rows(p, s, lib) if r.conductor == "PE")
    assert "vede kolem F2, F5" in pe.notes and len(pe.wire_ids) == 3
    # nejednoznačné (dva vývody PE z přístroje) → beze sloučení, původní poznámka
    _w(s, f5, "2", _el(s, "sb.feed", "X4", dir="out"), "1", AC)
    pes = [r for r in _rows(p, s, lib) if r.conductor == "PE"]
    assert any("PE nespínaný – ve skutečnosti vede kolem F5" in r.notes for r in pes)


@pytest.mark.parametrize("dist", ["bus", "terminals"])
def test_template_bypass_merge_loses_nothing(lib, dist):
    """(3) Šablona AC: méně řádků, každá žíla každého vodiče je právě v jednom řádku."""
    p, s = _sb()
    s.layout = Layout()
    apply_template(p, s, "ac_fve", {"distribution": dist})
    rows = _rows(p, s, lib)
    segs = {(w.id, c) for w in s.wires for c in w.conductors}
    got = [(wid, r.conductor) for r in rows for wid in r.wire_ids]
    assert len(got) == len(set(got)) and set(got) == segs
    assert len(rows) < len(segs)
    assert not any(":PE" in r.from_text + r.to_text and "Q1" in r.from_text + r.to_text for r in rows)


def test_switched_neutral_pole_numbers():
    """(4) Spínaný N 4p přístroje = další pól (7/8), nespínaný N 3p jističe = „N“."""
    _, s = _sb()
    bus = _el(s, "sb.busbar", "1")
    q = _el(s, "sb.main_switch", "Q1", poles=4, modules=4)
    f = _el(s, "fve.breaker_mcb", "F2", poles=3, modules=3)
    x = _el(s, "sb.feed", "X3", dir="out")
    w_in, w_out = _w(s, x, "1", q, "1", AC), _w(s, q, "2", bus, "IN", AC)
    assert device_terminal(s, w_in, "N", "b") == ("Q1:7", True)
    assert device_terminal(s, w_out, "N", "a") == ("Q1:8", True)
    assert device_terminal(s, w_out, "PE", "a") == ("Q1:PE", True)
    w_f = _w(s, bus, "1", f, "1", AC)
    assert device_terminal(s, w_f, "N", "b") == ("F2:N", True)
    # 1p+N: N je pól 2 → 3/4
    g = _el(s, "fve.breaker_mcb", "F6", poles=2, modules=2)
    w_g = _w(s, bus, "2", g, "1", ["L1", "N"])
    assert device_terminal(s, w_g, "N", "b") == ("F6:3", True)


def test_power_contact_cross_from_contactor(lib):
    """(5) Silový kontakt není řízení: In stykače ve skupině, jinak výchozí silový s poznámkou."""
    p, s = _sb()
    prm = WiringParams()
    k = _el(s, "ctl.contact_power", "K1", row=0, pos=0, poles=3, modules=3)
    x = _el(s, "sb.feed", "X3", dir="out")
    w = _w(s, k, "2", x, "1", AC[:3])
    assert wire_cross(p, s, w, prm, DeviceIndex.build(p)) == (1.5, "výchozí")
    pw = next(r for r in _rows(p, s, lib) if r.wire_id == w.id)
    assert "průřez výchozí – ověřit" in pw.notes
    _el(s, "fve.contactor", "K1", in_=25, poles=3, modules=3)
    assert wire_cross(p, s, w, prm, DeviceIndex.build(p)) == (4.0, "stykač")
    assert next(r for r in _rows(p, s, lib) if r.wire_id == w.id).cross == 4.0
    coil = _el(s, "ctl.coil", "K1")
    assert wire_cross(p, s, _w(s, coil, "A2", x, "2", ["N"]), prm) == (1.0, "řízení")


def test_flexible_types_table():
    """(6) Ohebné typy z tabulky: CYA, LgY, H05V-K, H07V-K, -F; tuhé ne."""
    for t in ("CYA", "CYA 6", "LgY", "H05V-K", "H07V-K", "H07V2-K", "H05VV-F", "LiYCY"):
        assert is_flexible(t), t
    for t in ("CY", "H07V-U", "H07V-R", "CYKY"):
        assert not is_flexible(t), t
    assert any(p == "CYA" for p, _ in FLEXIBLE_WIRE_TYPES)


def test_number_note_and_empty_designation_column(lib, tmp_path):
    """(7) Č. není trvalé (podnadpis, list Parametry); prázdný sloupec Označení se vynechá."""
    from openpyxl import load_workbook

    from envocad.export.xlsx_export import export_production_xlsx
    p, s = _sb()
    f = _el(s, "fve.breaker_mcb", "F2", row=0, pos=0, in_=16, poles=1, modules=1)
    x = _el(s, "sb.feed", "X3", dir="out")
    w = _w(s, f, "2", x, "1", ["L1"])
    head, rows = reports.production_wiring_list(p, lib, s, {})
    assert "Označení" not in head and len(rows[0]) == len(head)
    assert NUMBER_NOTE in reports.production_subtitle(p, s, {})
    out = tmp_path / "v.xlsx"
    export_production_xlsx(p, lib, out, None, {})
    prm = [r[0] for r in load_workbook(out)["Parametry"].iter_rows(values_only=True)]
    assert NUMBER_NOTE in prm
    w.attrs["ref"] = "W1"
    head, rows = reports.production_wiring_list(p, lib, s, {})
    assert head[1] == "Označení" and rows[0][1] == "W1"


def test_twin_only_same_cross_and_flexible(lib):
    """(8) Dvojitá dutinka jen při stejném průřezu obou ohebných žil; jinak bez dutinky + poznámka."""
    p, s = _sb()
    f1 = _el(s, "fve.breaker_mcb", "F1", row=0, pos=0, in_=10, poles=1, modules=1)
    f2 = _el(s, "fve.breaker_mcb", "F2", row=0, pos=1, in_=16, poles=1, modules=1)
    pe = _el(s, "sb.pe_bar", "X9")
    w1, w2 = _w(s, f1, "2", pe, "1", ["PE"]), _w(s, f2, "2", pe, "1", ["PE"])
    rows = {r.wire_id: r for r in _rows(p, s, lib)}
    for w in (w1, w2):
        assert rows[w.id].end_to == "" and rows[w.id].ferrule_to is None
        assert "2 vodiče různého průřezu ve svorce – ověřit" in rows[w.id].notes
    w2.attrs["cross"] = "1,5"
    w2.attrs["cable"] = "H07V-U"                       # stejný průřez, ale tuhý → ne dvojitá
    rows = {r.wire_id: r for r in _rows(p, s, lib)}
    assert rows[w1.id].ferrule_to and not rows[w1.id].ferrule_to.twin and rows[w2.id].ferrule_to is None
    w2.attrs["cable"] = "CYA"
    rows = {r.wire_id: r for r in _rows(p, s, lib)}
    assert rows[w1.id].ferrule_to.twin and rows[w2.id].ferrule_to.twin


def test_clamp_key_by_terminal_origin(lib):
    """(9) Ruční svorka shodná se jménem portu je konkrétní svorka → s odvozenou F5:1 tvoří dvojici."""
    p, s = _sb()
    f6 = _el(s, "fve.breaker_mcb", "F6", row=1, pos=2, in_=16, poles=1, modules=1)
    f5 = _el(s, "fve.breaker_mcb", "F5", row=1, pos=0, in_=16, poles=1, modules=1)
    q = _el(s, "sb.main_switch", "Q1", row=0, pos=4, in_=200, poles=3, modules=3)
    w1 = _w(s, f6, "1", f5, "1", ["L1"])
    w1.terminals = {"L1": {"b": "F5:1"}}
    w2 = _w(s, q, "2", f5, "1", ["L1"], cross="2,5")
    assert conductor_end(p, s, w1, "L1", "b").origin == "ruční"
    assert conductor_end(p, s, w2, "L1", "b").origin == "pravidlo"
    rows = {r.wire_id: r for r in _rows(p, s, lib)}
    f5_end = lambda r: r.end_to if r.to_text.endswith("F5:1") else r.end_from
    assert f5_end(rows[w1.id]) == f5_end(rows[w2.id]) == "dvojitá dutinka 2×2,5/8 modrá"


def test_wiring_list_same_ends_as_production(lib):
    """(10) Zapojovací seznam na listu rozvaděče: stejné svorky a texty konců jako výrobní seznam."""
    p, s = _sb()
    s.layout = Layout()
    apply_template(p, s, "ac_fve", {})
    head, rows = reports.wiring_list(p, lib, s)
    ends = {(r[head.index("Odkud")], r[head.index("Kam")]) for r in rows}
    assert ("+RDC1-1L1", "+RDC1-F2:1") in ends and ("+RDC1-F2:2", "+RDC1-X3:1") in ends
    assert not any(":T1" in a + b or "-1:" in a + b for a, b in ends)
    prod = {t for pw in production_wires(p, s, {}, lib) for t in (pw.from_text, pw.to_text)}
    assert prod <= {t for e in ends for t in e}
    # list schématu beze změny (jméno portu)
    q = Project()
    sch = q.sheets[0]
    f = _el(sch, "fve.breaker_mcb", "F2", poles=3)
    x = _el(sch, "fve.terminal", "X1")
    _w(sch, x, "1", f, "1", ["L1", "L2"])
    h2, r2 = reports.wiring_list(q, lib, sch)
    assert {r[h2.index("Kam")] for r in r2} == {"F2:1"}


def test_end_labels_and_unplaced_labels():
    """(12) Popisek koncovky s koncem; (13) wire_unplaced česky, uložená hodnota zůstává."""
    _, s = _sb()
    f = _el(s, "fve.breaker_mcb", "F2")
    x = _el(s, "sb.feed", "X1", dir="out")
    bus = _el(s, "sb.busbar", "1")
    w = _w(s, f, "2", x, "1", ["L1"])
    assert wire_end_labels(s, w) == {"end_a": "Koncovka A (F2:2)", "end_b": "Koncovka B (X1:1)"}
    assert wire_end_labels(s, _w(s, bus, "1", f, "1", ["L1"]))["end_a"] == "Koncovka A (sběrnice 1)"
    assert UNPLACED_LABELS == {"estimate": "odhad", "none": "bez délky"}
    prm = WiringParams.resolve(Layout(params={"wire_unplaced": "none"}))
    assert prm.value("wire_unplaced") == "none" and prm.display("wire_unplaced") == "bez délky"
    assert WiringParams.resolve(Layout(params={"wire_unplaced": "bez délky"})).unplaced == "none"
    src = {k: v for k, _, v, _ in param_sources(Layout(params={"wire_unplaced": "none"}))}
    assert src["wire_unplaced"] == "bez délky"
    assert "neumístěné konce: bez délky" in prm.describe()


def test_sheets_sorted_naturally(lib):
    """(14) Listy RDC2 < RDC10."""
    p = Project()
    for name in ("RDC10", "RDC2"):
        s = Sheet(name=name, kind="switchboard", loc=name, layout=_layout())
        p.sheets.append(s)
        f = _el(s, "fve.breaker_mcb", "F2", row=0, pos=0, in_=16, poles=1, modules=1)
        _w(s, f, "2", _el(s, "sb.feed", "X3", dir="out"), "1", ["L1"])
    assert [r.sheet for r in production_wires(p, None, {}, lib)] == ["RDC2", "RDC10"]


def test_spd_cross_left_to_designer(lib):
    """(15) AC SPD bez In na druhém konci: průřez None, poznámka, bez dutinky; In jištění SPD má přednost.
    PE od SPD má vlastní pravidlo: 6 mm² Cu, SPD typu I s jímací soustavou 16 mm² Cu."""
    p, s = _sb()
    bus = _el(s, "sb.busbar", "1")
    spd = _el(s, "fve.spd", "F1", row=0, pos=0, poles=4, modules=4)
    pe = _el(s, "sb.pe_bar", "X9")
    w = _w(s, spd, "PE", pe, "1", ["PE"])
    wl = _w(s, bus, "1", spd, "L", AC[:4])
    rows = _rows(p, s, lib)
    pw = next(r for r in rows if r.wire_id == wl.id)
    assert pw.cross is None and pw.cross_source == "SPD"
    assert "SPD – průřez určí projektant (dle výrobce SPD)" in pw.notes
    assert pw.end_from == pw.end_to == "" and pw.ferrule_from is None
    pe_row = next(r for r in rows if r.wire_id == w.id)
    assert pe_row.cross == 6.0 and pe_row.cross_source == "PE SPD"
    spd.attrs["spd_type"] = "T1+T2"
    assert wire_cross(p, s, w, WiringParams()) == (6.0, "PE SPD")
    assert wire_cross(p, s, w, WiringParams(lps="yes")) == (16.0, "PE SPD")
    spd.attrs["spd_type"] = "T2"
    assert wire_cross(p, s, w, WiringParams(lps="yes")) == (6.0, "PE SPD")
    fb = _el(s, "fve.fuse", "F0", in_=25)
    assert wire_cross(p, s, _w(s, fb, "2", spd, "L", ["L1"]), WiringParams()) == (4.0, "jištění")


def test_wire_markers_modes_and_local_text():
    """Návlečky dle ČSN EN 62491: adresné (výchozí), odkud/kam, číslo vodiče, bez; konce bez vlastního umístění."""
    from envocad.model.project import Sheet
    from envocad.model.wiring import (
        CHOICE_LABELS,
        ProductionWire,
        WiringParams,
        local_end_text,
        parse_param,
        wire_markers,
    )
    sh = Sheet(kind="switchboard", func="AC", loc="RDC1")
    assert local_end_text(sh, "=AC+RDC1-F2:3") == "F2:3"
    assert local_end_text(sh, "+RH-X1:2") == "+RH-X1:2"          # jiné umístění zůstane celé
    assert local_end_text(Sheet(kind="switchboard"), "F2:3") == "F2:3"
    pw = ProductionWire(7, "RDC1", "", "L1", "+RDC1-F2:3", "+RDC1-X1:1", 1.5, "", "hnědá", "H07V-K", 500,
                        "", "", None, None, local_from="F2:3", local_to="X1:1")
    assert wire_markers(pw) == ("X1:1", "F2:3")
    pw.marking = "both"
    assert wire_markers(pw) == ("F2:3 / X1:1", "X1:1 / F2:3")
    pw.marking = "number"
    assert wire_markers(pw) == ("7", "7")
    pw.ref = "W12"
    assert wire_markers(pw) == ("W12", "W12")
    pw.marking = "none"
    assert wire_markers(pw) == ("", "")
    assert parse_param("wire_marking", "odkud / kam") == "both" and parse_param("wire_marking", "x") is None
    assert WiringParams().marking == "address" and "wire_marking" in CHOICE_LABELS


def test_marking_report_cable_tags_and_sleeves():
    from envocad.export.reports import NOT_IN_DOC, marking, production_wiring_list
    from envocad.model.project import Element, Project, Wire, WireEnd
    lib = LibraryStore()
    p = Project()
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    g = Element("fve.pv_string", 0, 150, attrs={"ref": "G1"})
    p.sheets[0].elements += [blk, g]
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals"})
    p.sheets[0].wires.append(Wire(WireEnd(g.id, "DC"), WireEnd(blk.id, "X1"), attrs={"ref": "W1", "cable": "H1Z2Z2-K"}))
    _head, rows = marking(p, lib)
    tags = [r for r in rows if r[0] == "Štítek kabelu"]
    assert len(tags) == 2 and {r[1] for r in tags} == {"W1"}
    assert {r[2] for r in tags} == {"→ +R1-X1", "→ G1:DC"} and "Značení vodičů a kabelů" in NOT_IN_DOC
    sleeves = [r for r in rows if r[0] == "Návlečka"]
    assert sleeves and not any(r[1].startswith("+R1") for r in sleeves)   # vlastní umístění se na návlečce neopakuje
    ph, prow = production_wiring_list(p, lib, sb)
    assert "Návlečka odkud" in ph and prow[0][ph.index("Návlečka odkud")]
    sb.layout.params["wire_marking"] = "none"
    ph, _ = production_wiring_list(p, lib, sb)
    assert "Návlečka odkud" not in ph


def test_port_on_top_uses_element_symbol(lib):
    """Směr portu bez čísla svorky ze značky prvku (`element_symbol`): parametrická sběrnice má přívod zdola B13
    (port dole) – pevná značka z knihovny ho nemá a odhad podle jména by dal „nahoře“ (liché číslo). Osiřelý port
    a prvek bez knihovny dál podle jména."""
    from envocad.model.wiring import _port_on_top
    p, s = _sb()
    bus = _el(s, "sb.busbar", "1", taps=13)
    f = _el(s, "fve.breaker_mcb", "F1", in_=16, poles=1, modules=1)
    _w(s, f, "2", bus, "B13", ["L1"])
    _w(s, f, "1", bus, "T13", ["L1"])
    assert _port_on_top(p, bus, "B13", lib) is False
    assert _port_on_top(p, bus, "T13", lib) is True
    assert _port_on_top(p, bus, "B13", None) is True               # bez knihovny podle jména (liché = nahoře)
    _w(s, f, "1", bus, "Z7", ["L1"])                                # osiřelý port → podle jména
    assert _port_on_top(p, bus, "Z7", lib) is True
