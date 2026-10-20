"""Regrese z QA auditu rozvaděčů (audit 2) a JPS (audit 1) – šablony, rozložení, oteplení, vícepól, výkazy,
kopie a kabely. Headless (bez Qt)."""
import pytest

from envocad.export import reports
from envocad.library.store import LibraryStore
from envocad.library.templates import apply_template, dc_kind_param
from envocad.model import checks
from envocad.model import multipole as mp
from envocad.model.project import (
    Element,
    Project,
    Sheet,
    Wire,
    WireEnd,
    copy_fragment,
    enclosure_number,
    enclosure_param_error,
    paste_fragment,
    sync_cables,
    terminal_group_modules,
    without_dangling,
)
from envocad.model.thermal import (
    DEFAULT_T_MAX_C,
    LOSS_PER_A_PER_POLE,
    DeviceTemp,
    ThermalResult,
    device_power_loss,
    layout_inputs,
    temperature_rise,
)


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return LibraryStore(tmp_path_factory.mktemp("lib") / "l.db")


def _sb(tid="ac_fve", params=None, ref="R1"):
    p = Project()
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": ref})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, tid, params or {})
    return p, sb


def _mk(lib, sh, sid, **kw):
    e = Element(sid, 0, 0)
    e.attrs = {a.key: a.default for a in lib.get_symbol(sid).attributes}
    e.attrs.update({k: str(v) for k, v in kw.items()})
    sh.elements.append(e)
    return e


def _bare_sb():
    p = Project()
    sb = Sheet(name="R1", kind="switchboard")
    p.sheets.append(sb)
    return p, sb


# ---- šablony -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("n", ["1", "7", "8", "9"])
def test_bus_template_all_ports_exist(lib, n):
    """#1: sběrnice má vývody pro SPD + až 9 vývodů + PE (dřív n_out 8–9 vedlo na neexistující porty)."""
    p, sb = _sb("ac_fve", {"distribution": "bus", "n_out": n})
    for w in sb.wires:
        for end in (w.a, w.b):
            lib.get_symbol(sb.element(end.element_id).symbol_id).port(end.port)
    assert checks.check_project(p, lib) is not None
    assert not [f for f in checks.check_project(p, lib) if f.code == "bad_port"]


@pytest.mark.parametrize("kind", ["trasa", "Trasa", "po trase", "route", "  TRASA "])
def test_dc_template_route_kinds(kind):
    """#5: „trasa“ (i s velkým písmenem, „po trase“, „route“) = jen SPD, bez odpínačů (ty jsou u střídače)."""
    _p, sb = _sb("dc", {"kind": kind, "n_strings": "2"})
    ids = {e.symbol_id for e in sb.elements}
    assert "fve.spd" in ids and not ids & {"fve.dc_disconnect", "fve.fuse_disconnect"}


def test_dc_template_tech_and_bad_kind():
    assert dc_kind_param({"kind": "technologie"}) == "tech" and dc_kind_param({}) == "tech"
    with pytest.raises(ValueError, match="Druh"):
        dc_kind_param({"kind": "střecha"})


def test_dc_template_string_desc_not_doubled():
    """#16: popis SPD „string 1“, ne „string string 1“."""
    _p, sb = _sb("dc", {"n_strings": "2"})
    descs = [e.attrs.get("desc") for e in sb.elements if e.symbol_id == "fve.spd"]
    assert descs == ["string 1", "string 2"]


def test_empty_template_links_feed_to_jps_wire():
    """#21: šablona „Prázdný list“ naváže přívod na vodič JPS k bloku (jako AC/DC šablona)."""
    p = Project()
    j = p.sheets[0]
    inv = Element("fve.inverter", 50, 150, attrs={"ref": "T1"})
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    j.elements += [inv, blk]
    w = Wire(WireEnd(inv.id, "AC"), WireEnd(blk.id, "1"), attrs={"ref": "W2", "cable": "CYKY-J 5x10"},
             conductors=["L1", "L2", "L3", "N", "PE"])
    j.wires.append(w)
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "empty")
    feed = next(e for e in sb.elements if e.symbol_id == "sb.feed_in")
    assert feed.attrs["wire_id"] == w.id and feed.attrs["cable"].startswith("CYKY-J 5x10")
    assert w.b.port == feed.ref


@pytest.mark.parametrize("params, msg", [
    ({"n_out": "abc"}, "není číslo"), ({"n_out": ""}, "není číslo"), ({"n_out": "0"}, "rozsah je 1–9"),
    ({"n_out": "-3"}, "rozsah"), ({"n_out": "2.5"}, "celé číslo"), ({"n_out": "10"}, "rozsah"),
    ({"i_main": "x"}, "In hlavního vypínače"), ({"i_out": "0"}, "větší než 0"),
    ({"distribution": "drát"}, "Rozvod"),
])
def test_template_invalid_params_raise_czech_and_change_nothing(params, msg):
    """#24: neplatný parametr = ValueError s českou hláškou, list zůstane prázdný (žádné tiché „1“)."""
    p = Project()
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    with pytest.raises(ValueError, match=msg):
        apply_template(p, sb, "ac_fve", params)
    assert sb.elements == [] and sb.wires == [] and sb.layout.placements == [] and not sb.bridges


def test_dc_template_invalid_strings():
    p = Project()
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    for bad in ("0", "-1", "x", "12"):
        with pytest.raises(ValueError, match="Počet stringů"):
            apply_template(p, sb, "dc", {"n_strings": bad})
    assert sb.elements == []


def test_template_terminal_groups_width_by_terminal_count(lib):
    """#18: skupina 5 svorek = 5 × 6,2 mm (ne 0,35 M za celou skupinu); skupiny šablony jsou rozmístěné."""
    _p, sb = _sb("ac_fve", {"distribution": "terminals", "n_out": "2"})
    groups = [e for e in sb.elements if e.symbol_id == "sb.terminal_block"]
    assert groups and all(g.modules == terminal_group_modules(5) == 1.77 for g in groups)
    assert all(sb.layout.placement(g.id) is not None for g in groups)
    assert lib.get_symbol("sb.terminal_block").attributes[-1].default == ""
    one = Element("sb.terminal_block", attrs={"ref": "X1", "terminal": "7"})
    assert one.modules == 0.35                                  # jedna svorka
    assert Element("sb.terminal_block", attrs={"ref": "X1", "terminal": "1 2", "modules": "2"}).modules == 2.0


# ---- rozložení ------------------------------------------------------------------------------------------------------
def test_layout_coil_plus_main_contact_is_one_device(lib):
    """#4: cívka + hlavní kontakt = jeden přístroj; kontakty se do rozložení nepočítají."""
    p, sb = _bare_sb()
    coil = _mk(lib, sb, "ctl.coil", ref="K1")
    _mk(lib, sb, "ctl.contact_power", ref="K1", in_="25")
    _mk(lib, sb, "ctl.contact_no", ref="K1")
    assert sb.layout.devices(sb, p) == [coil]
    sb.layout.set_placement(coil.id, 0, 0.0)
    assert sb.layout.used_modules(sb, p) == coil.modules


def test_layout_overflow_and_overlap_findings(lib):
    """#9: přetečení řady a překryv → WARNING layout_overflow / layout_overlap; zmenšení modulů nic nemaže."""
    p, sb = _bare_sb()
    a = _mk(lib, sb, "fve.breaker_mcb", ref="F1", in_="16")      # 3 M
    b = _mk(lib, sb, "fve.breaker_mcb", ref="F2", in_="16")
    c = _mk(lib, sb, "fve.breaker_mcb", ref="F3", in_="16")
    sb.layout.modules_per_row = 12
    sb.layout.set_placement(a.id, 0, 0.0)
    sb.layout.set_placement(b.id, 0, 2.0)                       # překryv s F1 (0–3)
    sb.layout.set_placement(c.id, 0, 6.0)
    codes = {(f.code, f.ref) for f in checks.check_project(p, lib) if f.code.startswith("layout_")}
    assert codes == {("layout_overlap", "F2")}
    sb.layout.modules_per_row = 8                               # F3 (6–9) za koncem řady, součet 9 > 8
    found = [f for f in checks.check_project(p, lib) if f.code.startswith("layout_")]
    assert {(f.code, f.ref) for f in found} == {("layout_overlap", "F2"), ("layout_overflow", "F3"),
                                                ("layout_overflow", "")}
    assert all(f.severity == checks.WARNING for f in found)
    assert len(sb.layout.placements) == 3 and sb.layout.placement(c.id) is not None
    assert "přesahuje konec řady" in next(f.text for f in found if f.ref == "F3")


def test_layout_contacts_not_in_overlap_check(lib):
    p, sb = _bare_sb()
    coil = _mk(lib, sb, "ctl.coil", ref="K1")
    pc = _mk(lib, sb, "ctl.contact_power", ref="K1")
    sb.layout.set_placement(coil.id, 0, 0.0)
    sb.layout.set_placement(pc.id, 0, 0.0)                      # starý projekt: kontakt umístěný přes cívku
    assert checks.layout_problems(sb, p) == []


# ---- parametry skříně ------------------------------------------------------------------------------------------------
def test_enclosure_param_validation():
    """#25: neplatné číslo / mimo rozsah → česká hláška; rdf 0–1; prázdné = nezadáno."""
    assert enclosure_param_error("rdf", "0,8") is None and enclosure_param_error("rdf", "") is None
    assert "mimo rozsah" in enclosure_param_error("rdf", "1.5")
    assert "mimo rozsah" in enclosure_param_error("rdf", "0")
    assert "není číslo" in enclosure_param_error("t_ambient", "teplo")
    assert "mimo rozsah" in enclosure_param_error("width_mm", "-5")
    assert enclosure_param_error("ip", "IP 54") is None                # nečíselný parametr
    # nezávislé hodnoty: neplatné RDF neshodí teplotu okolí
    sb = Sheet(kind="switchboard")
    sb.layout.params.update({"rdf": "abc", "t_ambient": "40"})
    assert layout_inputs(sb.layout) == (0.8, 40.0)
    assert enclosure_number({"rdf": "0,5"}, "rdf", 0.8) == 0.5


# ---- oteplení --------------------------------------------------------------------------------------------------------
def test_losses_for_common_builtin_devices(lib):
    """#12: pojistkový odpínač, silový kontakt a cívka mají orientační ztrátu; každý vestavěný přístroj s proudem
    a šířkou na liště má odhad ztrát (kromě elektroměru, SPD – pevná ztráta – a svorek)."""
    p, sb = _sb("dc", {"n_strings": "9", "kind": "tech"})
    fd = next(e for e in sb.elements if e.symbol_id == "fve.fuse_disconnect")
    assert device_power_loss(fd) > 2
    assert temperature_rise(sb, project=p).p_devices_w > 20
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "envocad" / "library" / "builtin"
    for f in [*root.glob("switchboard/sb.*.json"), *root.glob("fve/fve.*.json"), *root.glob("control/ctl.*.json")]:
        d = json.loads(f.read_text(encoding="utf-8"))
        keys = {a["key"]: a["default"] for a in d["attributes"]}
        if "in_" in keys and keys.get("modules") not in (None, "", "0"):
            assert d["id"] in LOSS_PER_A_PER_POLE, d["id"]
    p2, sb2 = _bare_sb()
    _mk(lib, sb2, "ctl.coil", ref="K1")
    _mk(lib, sb2, "ctl.contact_power", ref="K1", in_="25")
    assert temperature_rise(sb2, project=p2).p_devices_w > 2.5


def test_thermal_verdict_uses_absolute_temperature():
    """#12 (po přístrojích): hodnocení podle teploty vzduchu u přístroje (okolí + Δt v jeho řadě) proti jeho t_max,
    ne podle samotného Δt ani pevného prahu skříně."""
    def res(dt, amb, t_max=55.0, src="artikl"):
        r = ThermalResult(10, 10, 1, dt / 1.2, dt, 0.8, amb, [])
        r.devices = [DeviceTemp("e1", "F3", 0, amb + dt, t_max, src)]
        return r
    assert res(25, 35).verdict().startswith("NEVYHOVUJE")                # 60 °C > 55 °C
    assert res(10, 35).verdict().startswith("vyhovuje (orientačně)")     # 45 °C ≤ 55 °C
    assert "derating" in res(10, 35).verdict()                           # nad 40 °C připomenout odlehčení
    assert "derating" not in res(4, 35).verdict()
    assert res(10, 50).verdict().startswith("NEVYHOVUJE")                # 60 °C uvnitř
    assert res(10, 50, t_max=70).verdict().startswith("vyhovuje")        # přístroj do 70 °C
    assert res(4, 35, t_max=DEFAULT_T_MAX_C, src="předpoklad").verdict().startswith("vyhovuje")
    assert "orientačně" in res(4, 35).verdict() and "orientačně" in res(25, 35).verdict()
    empty = ThermalResult(0, 0, 1, 0, 0, 0.8, 35, [])
    assert empty.verdict().startswith("vyhovuje (orientačně) – bez přístrojů")


# ---- vícepól ---------------------------------------------------------------------------------------------------------
def test_coil_neutral_on_a2_has_pole(lib):
    """#7: cívka A1 = L1, A2 = N – N se napojí na A2 pólu cívky (ne mimo prvek)."""
    _p, sb = _bare_sb()
    c = _mk(lib, sb, "ctl.coil", ref="K1")
    a = _mk(lib, sb, "sb.feed_in", ref="X1")
    b = _mk(lib, sb, "sb.feed_out", ref="X2")
    sb.wires.append(Wire(WireEnd(a.id, "1"), WireEnd(c.id, "A1"), conductors=["L1"]))
    sb.wires.append(Wire(WireEnd(c.id, "A2"), WireEnd(b.id, "1"), conductors=["N"]))
    ep = mp.element_poles(sb, c, lib.get_symbol("ctl.coil"))
    assert ep.switched == ["L1"] and ep.joined == {"N": "L1"} and ep.slots == ["L1"]
    assert ep.pole_pos("A2", "N") == ep.pole_pos("A2", "L1")
    assert ep.pole_pos("A2", "N") == c.port_pos(lib.get_symbol("ctl.coil"), "A2")


def test_three_pole_breaker_bypass_unchanged(lib):
    _p, sb = _bare_sb()
    f = _mk(lib, sb, "fve.breaker_mcb", ref="F1", poles="3")
    a = _mk(lib, sb, "sb.feed_in", ref="X1")
    b = _mk(lib, sb, "sb.feed_out", ref="X2")
    five = ["L1", "L2", "L3", "N", "PE"]
    sb.wires.append(Wire(WireEnd(a.id, "1"), WireEnd(f.id, "1"), conductors=five))
    sb.wires.append(Wire(WireEnd(f.id, "2"), WireEnd(b.id, "1"), conductors=five))
    ep = mp.element_poles(sb, f, lib.get_symbol("fve.breaker_mcb"))
    assert ep.switched == ["L1", "L2", "L3"] and ep.bypass == ["N", "PE"] and ep.joined == {}


# ---- výkazy ----------------------------------------------------------------------------------------------------------
def _two_boards(lib):
    p = Project(name="Rep")
    j = p.sheets[0]
    inv = Element("fve.inverter", 50, 150, attrs={"ref": "T1"})
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    j.elements += [inv, blk]
    j.wires.append(Wire(WireEnd(inv.id, "AC"), WireEnd(blk.id, "1"), attrs={"ref": "W2", "cable": "CYKY-J 5x16"},
                        conductors=["L1", "L2", "L3", "N", "PE"]))
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals", "n_out": "3"})
    blk2 = Element("fve.switchboard", 120, 250, attrs={"ref": "R2"})
    j.elements.append(blk2)
    sb2 = p.create_switchboard_sheet(blk2)
    apply_template(p, sb2, "dc", {"n_strings": "2"})
    return p, sb, sb2


def test_terminal_report_and_plan_other_end_per_conductor(lib):
    """#10: „Připojeno na“ / vnitřní připojení po žílách jako zapojovací seznam (Q1:1, Q1:3 …, PE kolem)."""
    p, sb = _sb("ac_fve", {"distribution": "terminals"})
    rows = [r for r in reports.terminals(p, lib, sb)[1] if r[0] == "X1"]
    assert [r[4] for r in rows] == ["Q1:1", "Q1:3", "Q1:5", "Q1:7", "Q1:PE"]
    from envocad.model.terminal_plan import terminal_plan
    plan = next(x for x in terminal_plan(p, sb) if x.strip == "X1")
    assert [r.internal for r in plan.rows] == ["Q1:1", "Q1:3", "Q1:5", "Q1:7", "Q1:PE"]


def test_labels_no_contacts_and_one_per_strip(lib):
    """#13: štítky bez kontaktů; skupiny svorek jedné svorkovnice = jeden štítek."""
    p, sb = _bare_sb()
    _mk(lib, sb, "fve.contactor", ref="K1")
    _mk(lib, sb, "ctl.contact_no", ref="K1")
    _mk(lib, sb, "ctl.contact_nc", ref="K1")
    assert [r[0] for r in reports.labels(p, lib)[1]].count("K1") == 1
    p, sb = _sb("ac_fve", {"distribution": "terminals", "n_out": "3"})
    labels = [r[0] for r in reports.labels(p, lib, sb)[1]]
    assert labels.count("+R1-X2") == 1
    assert next(r[1] for r in reports.labels(p, lib, sb)[1] if r[0] == "+R1-X2") == "Svorkovnice"


def test_bom_and_potentials_full_designations(lib):
    """#15: BOM a Potenciály s plným označením; X1 z různých rozvaděčů rozlišené; můstky s umístěním;
    Potenciály se sloupcem List; Přístroje = svorkovnice jednou se souhrnem."""
    p, _sb1, _sb2 = _two_boards(lib)
    head, rows = reports.bom(p, lib)
    term = next(r for r in rows if r[1] == "Řadová svorka")[6]
    assert "+R1-X1 (5)" in term and "+R2-X1 (2)" in term and "+R1-X2 (20)" in term
    bridges = next(r for r in rows if r[1] == "Můstek svorek")[6]
    assert bridges.startswith("+R1-X2:1-6-11-16")
    assert "+R1-Q1" in next(r for r in rows if r[1] == "Hlavní vypínač")[6]
    head, rows = reports.potentials(p, lib)
    assert head[-1] == "List"
    pe2 = next(r for r in rows if "+R2-X5:1" in r[4])
    assert pe2[-1] == "R2"
    assert any("Blokové schéma" in r[-1] and "R1" in r[-1] for r in rows)
    head, rows = reports.device_list(p, lib)
    x2 = [r for r in rows if r[0] == "+R1-X2"]
    assert len(x2) == 1 and x2[0][head.index("Parametry")] == "20 svorek, 4 skupiny"
    assert x2[0][head.index("Moduly")] == round(4 * terminal_group_modules(5), 2)


def test_natural_sort_in_reports(lib):
    """#17: 6 A < 10 A < 16 A < 100 A v BOM; listy R2 < R10 a označení F2 < F10 přirozeně."""
    p = Project()
    sb10, sb2 = Sheet(name="R10", kind="switchboard"), Sheet(name="R2", kind="switchboard")
    p.sheets += [sb10, sb2]
    for i, a in enumerate(["6", "100", "16", "10"]):
        _mk(lib, sb10, "fve.breaker_mcb", ref=f"F{10 - i}", in_=a)
    _mk(lib, sb2, "fve.breaker_mcb", ref="F1", in_="16")
    ins = [r[4].split(" ")[0] for r in reports.bom(p, lib)[1]]
    assert ins == ["6", "10", "16", "100"]
    rows = reports.device_list(p, lib)[1]
    assert [(r[0], r[-1]) for r in rows] == [("F1", "R2"), ("F7", "R10"), ("F8", "R10"), ("F9", "R10"),
                                             ("F10", "R10")]
    assert reports._ref_key("+R2-F1") < reports._ref_key("+R10-F1") < reports._ref_key("+R10-F2")


def test_wiring_list_matches_production_for_bypassed_pe(lib):
    """#22: zapojovací seznam listu rozvaděče netvrdí „Q1:PE“ – PE vedený v JPS přes Q1 je jeden řádek
    „vede kolem Q1“ jako ve výrobním seznamu; počet řádků sedí."""
    p, sb = _sb("ac_fve", {"distribution": "terminals", "n_out": "2"})
    rows = [r for r in reports.wiring_list(p, lib, sb)[1]]
    prod = reports.production_wiring_list(p, lib, sb, base={})[1]
    assert len(rows) == len(prod)
    assert not any(r[5].endswith("Q1:PE") or r[6].endswith("Q1:PE") for r in rows)
    pe = next(r for r in rows if r[2] == "PE" and "vede kolem Q1" in r[7])
    assert (pe[5], pe[6]) == ("+R1-X1:5", "+R1-X2:5")


def test_bom_ignores_bridges_to_missing_terminals(lib):
    """#20: můstek na smazanou svorku se ve výkazu materiálu nepočítá."""
    p, sb = _sb("ac_fve", {"distribution": "terminals", "n_out": "3"})
    g = [e for e in sb.elements if e.symbol_id == "sb.terminal_block"][2]     # svorky 11–15
    sb.remove_element(g.id)
    rows = reports.bom(p, lib, sb)[1]
    br = next(r for r in rows if r[1] == "Můstek svorek")
    assert br[4] == "3 pólů" and "11" not in br[6].split(":")[1].split("-")


def test_bridge_text_validation():
    from envocad.model.terminal_plan import bridge_errors, parse_bridges, strip_numbers
    p, sb = _sb("ac_fve", {"distribution": "terminals", "n_out": "2"})
    nums = strip_numbers(p, sb, "X2")
    assert nums == {str(i) for i in range(1, 16)}
    assert parse_bridges("1-6\n2, 7 12\n3") == [["1", "6"], ["2", "7", "12"]]
    assert bridge_errors("X2", "1-6-11", nums) == []
    errs = bridge_errors("X2", "1-6-99\n7\n6-2", nums)
    assert any("99" in e for e in errs) and any("aspoň 2" in e for e in errs) and any("svorka 6" in e for e in errs)


# ---- kopie a kabely (audit JPS) ----------------------------------------------------------------------------------------
def _jps():
    p = Project()
    s = p.sheets[0]
    g = Element("fve.pv_string", 40, 150, attrs={"ref": "G1"})
    t = Element("fve.inverter", 100, 150, attrs={"ref": "T1"})
    s.elements += [g, t]
    s.wires.append(Wire(WireEnd(g.id, "+"), WireEnd(t.id, "DC1"), attrs={"ref": "W1", "cable": "H1Z2Z2-K 1x6"},
                        conductors=["DC+", "DC-"]))
    sync_cables(p)
    return p, s


def test_paste_does_not_share_cable_and_detaches_feed():
    """Audit 1 #3: vložený vodič nepřevezme cable_id (vlastní kabel podle nového označení); přívod nepřevezme
    vazbu na vodič JPS ani texty z ní."""
    p, s = _jps()
    orig = s.wires[0]
    frag = copy_fragment(s, [e.id for e in s.elements])
    assert "cable_id" not in frag["wires"][0]["attrs"]
    els, wires = paste_fragment(p, {"elements": [e.to_dict() for e in s.elements],
                                    "wires": [orig.to_dict()]}, lambda sid: {"fve.pv_string": "G"}.get(sid, "T"))
    assert "cable_id" not in wires[0].attrs and wires[0].attrs["ref"] != "W1"
    s.elements += els
    s.wires += wires
    sync_cables(p)
    assert orig.attrs["cable_id"] != wires[0].attrs["cable_id"]
    assert p.cable_of_wire(orig).ref == "W1" and p.cable_of_wire(wires[0]).ref == wires[0].attrs["ref"]
    feed = Element("sb.feed_in", attrs={"ref": "X1", "wire_id": orig.id, "from": "W1 T1:AC /1.A1", "cable": "CYKY",
                                        "desc": "přívod"})
    els, _ = paste_fragment(p, {"elements": [feed.to_dict()], "wires": []}, lambda sid: "X")
    assert (els[0].attrs["wire_id"], els[0].attrs["from"], els[0].attrs["cable"], els[0].attrs["desc"]) == \
        ("", "", "", "přívod")


def test_macro_expand_and_save_drop_link_attrs(tmp_path, monkeypatch):
    from envocad.library import macros
    monkeypatch.setenv("ENVOCAD_HOME", str(tmp_path))
    p, s = _jps()
    frag = {"elements": [e.to_dict() for e in s.elements], "wires": [w.to_dict() for w in s.wires]}
    assert frag["wires"][0]["attrs"]["cable_id"]
    path = macros.save_macro("Kopie", "", frag)
    import json
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "cable_id" not in saved["fragment"]["wires"][0]["attrs"]
    assert frag["wires"][0]["attrs"]["cable_id"]                        # vstup se nemění
    _els, wires = macros.expand(p, s, frag, {}, ref_prefix_of=lambda sid: "G" if sid == "fve.pv_string" else "T")
    assert "cable_id" not in wires[0].attrs


def test_orphan_cable_removed_and_restored_exactly():
    """Audit 1 #15: kabel bez vodiče sync_cables odebere; vrácený vodič (undo) dostane týž kabel zpět – to_dict
    projektu je přesně původní."""
    p, s = _jps()
    t = s.elements[1]
    g2 = Element("fve.pv_string", 40, 100, attrs={"ref": "G2"})
    s.elements.append(g2)
    w2 = Wire(WireEnd(g2.id, "+"), WireEnd(t.id, "DC2"), attrs={"ref": "W2", "cable": "H1Z2Z2-K 1x6"},
              conductors=["DC+", "DC-"])
    s.wires.append(w2)
    sync_cables(p)
    p.cable_of_wire(s.wires[0]).cores[0].color = "fialová"                # ruční úprava kabelu W1
    before = p.to_dict()
    w1 = s.wires.pop(0)                                                    # smazání vodiče W1
    sync_cables(p)
    assert [c.ref for c in p.cables] == ["W2"]
    s.wires.insert(0, w1)                                                  # undo
    sync_cables(p)
    assert p.to_dict() == before
    s.wires.remove(w2)                                                     # undo vložení posledního vodiče
    sync_cables(p)
    s.wires.append(w2)                                                     # redo
    sync_cables(p)
    assert p.to_dict() == before


def test_reports_on_dangling_view_do_not_drop_model_cables(lib):
    p, s = _jps()
    s.wires.append(Wire(WireEnd("nonexistent", "1"), WireEnd(s.elements[1].id, "DC2"), attrs={"ref": "W9"}))
    sync_cables(p)
    n = len(p.cables)
    assert without_dangling(p).cables is not p.cables
    reports.cable_plan(p, lib)
    assert len(p.cables) == n


def test_block_copy_prefix_from_existing_blocks():
    """Audit 1 #16: kopie bloku rozvaděče RDC1 → RDC2 (podle bloků projektu), ne R1."""
    p = Project()
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "RDC1"})
    p.sheets[0].elements.append(blk)
    els, _ = paste_fragment(p, {"elements": [blk.to_dict()], "wires": []}, lambda sid: "R")
    assert els[0].ref == "RDC2"
    f = Element("fve.breaker_mcb", attrs={"ref": "QF3"})
    els, _ = paste_fragment(p, {"elements": [f.to_dict()], "wires": []}, lambda sid: "F")
    assert els[0].ref == "F1"                                              # ostatní prvky podle značky
