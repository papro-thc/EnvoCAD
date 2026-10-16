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
    assert w1.conductors == ["DC+", "DC-"]
    assert w2.conductors == ["DC-"]          # ručně zadané žíly migrace nepřepíše
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


def test_example_migrates_to_v8():
    p = Project.load(EXAMPLE)
    assert FORMAT_VERSION == 8
    assert all(s.func == "" and s.loc == "" for s in p.sheets)
    assert p.structures == [] and p.revisions == []
