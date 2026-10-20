"""Načtení projektů ze starších verzí formátu (migrate) – skutečný soubor v1 i ručně složené mezistupně."""
import copy
import json
from pathlib import Path

import pytest

from envocad.library.store import LibraryStore
from envocad.model.project import FORMAT_VERSION, Project, element_symbol

EXAMPLE = Path(__file__).parent.parent / "examples" / "ukazka_fve.ecp"


def _ports_ok(p: Project, lib: LibraryStore) -> None:
    """Každý konec vodiče míří na existující prvek a port, který jeho značka má."""
    for s in p.sheets:
        by_id = {e.id: e for e in s.elements}
        for w in s.wires:
            for end in (w.a, w.b):
                e = by_id[end.element_id]
                sym = element_symbol(p, e, lib)
                assert end.port in {pt.name for pt in sym.ports}, f"{e.ref or e.symbol_id}: port {end.port}"


def _roundtrip_stable(p: Project) -> None:
    d = p.to_dict()
    assert d["format_version"] == FORMAT_VERSION
    assert Project.from_dict(copy.deepcopy(d)).to_dict() == d


def test_example_v1_loads(tmp_path):
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert raw["format_version"] == 1
    p = Project.load(EXAMPLE)
    lib = LibraryStore()
    _ports_ok(p, lib)
    _roundtrip_stable(p)
    n_el = sum(len(s["elements"]) for s in raw["sheets"])
    n_w = sum(len(s["wires"]) for s in raw["sheets"])
    assert sum(len(s.elements) for s in p.sheets) == n_el
    assert sum(len(s.wires) for s in p.sheets) == n_w
    # uložení a znovunačtení v aktuálním formátu
    out = tmp_path / "v.ecp"
    p.save(out)
    assert Project.load(out).to_dict() == p.to_dict()


def _v(ver: int, sheets: list, **extra) -> dict:
    return {"format": "envocad-project", "format_version": ver, "name": "Starý", "meta": {}, "sheets": sheets, **extra}


def _sheet(sid: str, elements: list, wires: list | None = None, **extra) -> dict:
    return {"id": sid, "name": sid, "elements": elements, "wires": wires or [], **extra}


def _el(eid: str, sym: str, ref: str = "") -> dict:
    return {"id": eid, "symbol_id": sym, "x": 0, "y": 0, "attrs": {"ref": ref} if ref else {}}


def test_v4_dc_ports_and_conductors():
    d = _v(4, [_sheet("s1", [_el("g", "fve.pv_string", "G1"), _el("t", "fve.inverter", "T1")], [
        {"id": "w1", "a": {"element_id": "g", "port": "DC+"}, "b": {"element_id": "t", "port": "DC+"}},
        {"id": "w2", "a": {"element_id": "g", "port": "DC-"}, "b": {"element_id": "t", "port": "DC-"},
         "conductors": ["DC-"]},
    ])])
    p = Project.from_dict(d)
    w1, w2 = p.sheets[0].wires
    assert (w1.a.port, w1.b.port) == ("DC", "DC1")
    assert (w2.a.port, w2.b.port) == ("DC", "DC2")
    assert w1.conductors == ["L+", "L-"]
    assert w2.conductors == ["L-"]           # ručně zadané žíly migrace nepřepíše (jen název dle ČSN EN 60445)
    _ports_ok(p, LibraryStore())
    _roundtrip_stable(p)


def test_v1_sheet_without_kind():
    p = Project.from_dict(_v(1, [_sheet("s1", [_el("f", "fve.breaker_mcb", "F1")])]))
    assert p.sheets[0].kind == "schematic"
    _roundtrip_stable(p)


def test_v6_project_bridges_move_to_sheet_with_strip():
    d = _v(6, [
        _sheet("jps", [_el("b1", "fve.breaker_mcb", "F1")]),
        _sheet("rh", [_el("x", "sb.terminal_block", "X1")], kind="switchboard"),
        _sheet("rdc", [_el("y", "sb.terminal_block", "X2")], kind="switchboard"),
    ], bridges={"X1": [["1", "2"]], "X2": [[3, 4]], "X9": [["5", "6"]]})
    p = Project.from_dict(d)
    by = {s.name: s for s in p.sheets}
    assert by["rh"].bridges["X1"] == [["1", "2"]]
    assert by["rdc"].bridges["X2"] == [["3", "4"]]   # čísla svorek jako text
    # svorkovnice, která na žádném listu není → první rozvaděč
    assert by["rh"].bridges["X9"] == [["5", "6"]]
    assert not by["jps"].bridges
    assert "bridges" not in p.to_dict()
    _roundtrip_stable(p)


def test_migrate_does_not_touch_current_version():
    p = Project.load(EXAMPLE)
    d = p.to_dict()
    assert Project.from_dict(copy.deepcopy(d)).to_dict() == d


def test_newer_or_foreign_file_is_rejected():
    with pytest.raises(ValueError, match="novější"):
        Project.from_dict(_v(FORMAT_VERSION + 1, []))
    with pytest.raises(ValueError, match="není projekt"):
        Project.from_dict({"format": "něco jiného", "sheets": []})


def test_missing_version_means_v1():
    d = _v(1, [_sheet("s1", [_el("g", "fve.pv_string", "G1"), _el("t", "fve.inverter", "T1")], [
        {"id": "w1", "a": {"element_id": "g", "port": "DC+"}, "b": {"element_id": "t", "port": "DC+"}}])])
    del d["format_version"]
    p = Project.from_dict(d)
    assert p.sheets[0].wires[0].b.port == "DC1"


def test_v7_to_v8_switchboard_location_and_structures():
    blk = _el("b1", "fve.switchboard", "RDC1")
    blk["attrs"]["desc"] = "DC rozvaděč"
    blk2 = _el("b2", "fve.switchboard", "RDC1")          # stejné označení → jedna struktura, sdílený prostor
    anon = _el("b3", "fve.switchboard")                   # bez označení → anonymní list
    d = _v(7, [
        _sheet("jps", [blk, blk2, anon]),
        _sheet("sb1", [_el("f", "fve.breaker_mcb", "F1")], kind="switchboard", parent_element_id="b1"),
        _sheet("sb2", [], kind="switchboard", parent_element_id="b2"),
        _sheet("sb3", [], kind="switchboard", parent_element_id="b3"),
        _sheet("orphan", [], kind="switchboard", parent_element_id="nic"),
    ])
    p = Project.from_dict(d)
    by = {s.id: s for s in p.sheets}
    assert by["sb1"].loc == "RDC1" and by["sb2"].loc == "RDC1"
    assert by["sb3"].loc == "" and by["orphan"].loc == "" and by["jps"].loc == ""
    assert all(s.func == "" for s in p.sheets)
    assert [x.to_dict() for x in p.structures] == [{"aspect": "+", "code": "RDC1", "description": "DC rozvaděč"}]
    assert p.revisions == []
    _roundtrip_stable(p)


def test_v7_to_v8_keeps_existing_values():
    d = _v(7, [_sheet("sb", [], kind="switchboard", parent_element_id="x", loc="RH", func="AC")],
           structures=[{"aspect": "+", "code": "RH", "description": "Hlavní"}])
    p = Project.from_dict(d)
    assert (p.sheets[0].func, p.sheets[0].loc) == ("AC", "RH")
    assert len(p.structures) == 1 and p.structures[0].description == "Hlavní"


def test_v7_revisions_from_meta():
    meta = {"revision": "C", "author": "Patrik", "changes": (
        "A | 2026-01-10 | List 1: přidáno F1 prvek | PR\n"
        "A | 2026-01-10 | List 1: změněno W2 vodič – průřez | PR\n"
        "B | 2026-02-01 | Rozvaděč: odebráno X3 | JN\n"
        "\n"
        "B | | popis | s | rourou | JN")}
    p = Project.from_dict(_v(7, [_sheet("s1", [])], meta=meta))
    assert [r.label for r in p.revisions] == ["A", "B", "C"]
    a, b, c = p.revisions
    assert a.closed and b.closed and not c.closed
    assert (a.date, a.author) == ("2026-01-10", "PR")
    assert a.description == "List 1: přidáno F1 prvek\nList 1: změněno W2 vodič – průřez"
    assert b.description.endswith("popis | s | rourou") and b.author == "JN"
    assert c.author == "Patrik" and not c.marks and not c.fingerprints
    assert p.meta["changes"] == meta["changes"] and p.meta["revision"] == "C"   # meta zůstává
    _roundtrip_stable(p)
    # aktuální revize je už v seznamu → žádná otevřená navíc
    p2 = Project.from_dict(_v(7, [_sheet("s1", [])], meta={**meta, "revision": "B"}))
    assert [r.label for r in p2.revisions] == ["A", "B"]
    # bez změnového listu a bez revize → prázdný seznam
    assert Project.from_dict(_v(7, [_sheet("s1", [])])).revisions == []


def test_v7_revisions_from_meta_skips_header_and_free_text():
    """Hlavička tabulky, volný text a dlouhé „označení“ nejsou revize."""
    meta = {"changes": (
        "Rev | Datum | Popis | Zpracoval\n"
        "Revize | Datum | Popis | Zpracoval\n"
        "Změnový list projektu FVE\n"
        "A\n"
        "Pozn. k revizi | viz TZ\n"
        "DLOUHEOZNACENI | 2026 | x | PR\n"
        "A | 2026-01-10 | List 1: přidáno F1 | PR\n"
        "B1 | 2026-02-01 | změna | JN")}
    p = Project.from_dict(_v(7, [_sheet("s1", [])], meta=meta))
    assert [r.label for r in p.revisions] == ["A", "B1"]
    assert p.revisions[0].description == "List 1: přidáno F1" and p.revisions[0].author == "PR"


def test_example_migrates_to_current():
    p = Project.load(EXAMPLE)
    assert FORMAT_VERSION == 13
    assert all(s.func == "" and s.loc == "" for s in p.sheets)
    assert p.structures == [] and p.revisions == [] and p.notes == []


def test_v8_to_v9_notes():
    """v8 nemá připomínky → prázdný seznam; ostatní obsah v8 (revize, struktury) beze změny."""
    d = _v(8, [_sheet("s1", [_el("f", "fve.breaker_mcb", "F1")], func="AC", loc="")],
           structures=[{"aspect": "=", "code": "AC", "description": "AC část"}],
           revisions=[{"id": "r1", "label": "A", "closed": True, "marks": [], "fingerprints": {"s1": "x"}}])
    p = Project.from_dict(copy.deepcopy(d))
    assert p.notes == []
    assert p.sheets[0].func == "AC" and p.structures[0].code == "AC"
    assert p.revisions[0].label == "A" and p.revisions[0].fingerprints == {"s1": "x"}
    out = p.to_dict()
    assert out["format_version"] == FORMAT_VERSION and out["notes"] == []
    _roundtrip_stable(p)


def test_v9_notes_roundtrip_and_v8_program_rejects():
    from envocad.model.project import Note
    p = Project()
    sid = p.sheets[0].id
    p.notes = [Note(sid, 10.0, 20.0, "Zkontrolovat průřez", no=1, author="PR", created="2026-10-16T14:05"),
               Note(sid, 50.0, 50.0, "Obdélník", no=2, w=20.0, h=10.0, target_id="e1", status="resolved",
                    reply="Opraveno", resolved_by="JN", resolved="2026-10-17T08:00")]
    d = json.loads(json.dumps(p.to_dict()))
    q = Project.from_dict(d)
    assert q.notes == p.notes
    _roundtrip_stable(q)
    # neznámý stav se načte jako otevřený
    d["notes"][0]["status"] = "neco"
    assert Project.from_dict(copy.deepcopy(d)).notes[0].status == "open"
    # soubor v9 je pro program s formátem 8 „z novější verze“ (nezahodí tiše připomínky)
    import envocad.model.project as prj
    old = prj.FORMAT_VERSION
    try:
        prj.FORMAT_VERSION = 8
        with pytest.raises(ValueError, match="novější"):
            Project.from_dict(d)
    finally:
        prj.FORMAT_VERSION = old


def test_v9_to_v10_mirror_and_texts():
    """v10: zrcadlení prvku a volné texty listu – v9 je nemá (výchozí hodnoty), uloží se jen když jsou použité;
    program s formátem 9 soubor v10 odmítne (nezahodí tiše zrcadlení a texty)."""
    from envocad.model.project import SheetText
    p = Project.from_dict(_v(9, [_sheet("s1", [_el("f", "fve.breaker_mcb", "F1")])]))
    assert p.sheets[0].texts == [] and p.sheets[0].elements[0].mirror is False
    out = p.to_dict()
    assert "texts" not in out["sheets"][0] and "mirror" not in out["sheets"][0]["elements"][0]
    p.sheets[0].elements[0].mirror = True
    p.sheets[0].texts.append(SheetText(10, 20, "Řádek 1\nŘádek 2", 3.5))
    d = json.loads(json.dumps(p.to_dict()))
    assert d["format_version"] == FORMAT_VERSION and d["sheets"][0]["elements"][0]["mirror"] is True
    q = Project.from_dict(d)
    assert q.sheets[0].elements[0].mirror and q.sheets[0].texts[0].lines() == ["Řádek 1", "Řádek 2"]
    _roundtrip_stable(q)
    import envocad.model.project as prj
    old = prj.FORMAT_VERSION
    try:
        prj.FORMAT_VERSION = 9
        with pytest.raises(ValueError, match="novější"):
            Project.from_dict(d)
    finally:
        prj.FORMAT_VERSION = old
    bad = copy.deepcopy(d)
    bad["sheets"][0]["texts"][0]["height"] = 0
    with pytest.raises(ValueError, match="height"):
        Project.from_dict(bad)


def test_v10_to_v11_conductor_names_en60445():
    """v11: žíly DC+ / DC− → L+ / L− (ČSN EN 60445) ve vodičích, svorkách žil, kabelech i atributu `conductors`."""
    from envocad.model.project import conductor_name
    sh = _sheet("s1", [_el("g", "fve.pv_string", "G1"), _el("t", "fve.inverter", "T1"),
                       {"id": "x", "symbol_id": "sb.terminal_block", "x": 0, "y": 0,
                        "attrs": {"ref": "X1", "conductors": "DC+, DC-"}}])
    sh["wires"] = [{"id": "w1", "a": {"element_id": "g", "port": "DC"}, "b": {"element_id": "t", "port": "DC1"},
                    "conductors": ["DC+", "DC−"], "terminals": {"DC+": {"a": "X1:1"}}, "attrs": {"ref": "W1"}}]
    d = _v(10, [sh], cables=[{"id": "k", "ref": "W1", "cores": [{"name": "DC+"}, {"name": "DC-", "color": "černá"}]}])
    p = Project.from_dict(d)
    s = p.sheets[0]
    assert s.wires[0].conductors == ["L+", "L-"] and s.wires[0].terminals == {"L+": {"a": "X1:1"}}
    assert [c.name for c in p.cables[0].cores] == ["L+", "L-"]
    assert s.element("x").attrs["conductors"] == "L+ L-"
    assert p.to_dict()["format_version"] == FORMAT_VERSION
    assert conductor_name("dc-") == "L-" and conductor_name("PE") == "PE"


def test_v11_to_v12_single_line_offset():
    """v12: ruční posun prvku v jednopólovém schématu (`sl_pos`) – v11 ho nemá, uloží se jen když je zadaný."""
    p = Project.from_dict(_v(11, [_sheet("s1", [_el("f", "fve.breaker_mcb", "F1")])]))
    e = p.sheets[0].elements[0]
    assert e.sl_pos is None and "sl_pos" not in p.to_dict()["sheets"][0]["elements"][0]
    e.sl_pos = (12.5, -5.0)
    d = json.loads(json.dumps(p.to_dict()))
    assert d["format_version"] == FORMAT_VERSION and d["sheets"][0]["elements"][0]["sl_pos"] == [12.5, -5.0]
    assert Project.from_dict(d).sheets[0].elements[0].sl_pos == (12.5, -5.0)
    _roundtrip_stable(Project.from_dict(d))
