"""Hromadná úprava vlastností vybraných prvků (issue #77), headless: `bulk_common`, `bulk_changes`,
`bulk_edit_elements` v `envocad.cmd.edits`. Hromadně jde artikl (jen při stejné značce), `func`, `loc`, `note`."""
import json

import pytest

from envocad.cmd.edits import (
    BULK_ATTR_KEYS,
    BulkChange,
    BulkField,
    bulk_changes,
    bulk_common,
    bulk_edit_elements,
)
from envocad.model.project import Element, Project, Wire, WireEnd

MCB = "fve.breaker_mcb"
ART_A, ART_B = "eaton-az-3-b100", "eaton-az-3-b63"   # reálné artikly značky fve.breaker_mcb (builtin/components)


def _project():
    """Tři jističe F1–F3 (F1 má func=AC, F2 func=DC, F3 bez func), střídač T1 a vodič mezi F1 a F2."""
    p = Project(name="Hromadna")
    s = p.sheets[0]
    f1 = Element(MCB, 0, 0, attrs={"ref": "F1", "func": "AC", "loc": "R1", "note": "stejná"})
    f2 = Element(MCB, 20, 0, attrs={"ref": "F2", "func": "DC", "loc": "R1", "note": "stejná"})
    f3 = Element(MCB, 40, 0, attrs={"ref": "F3", "loc": "R1", "note": "stejná"})
    t1 = Element("fve.inverter", 60, 0, attrs={"ref": "T1"})
    s.elements += [f1, f2, f3, t1]
    s.wires.append(Wire(WireEnd(f1.id, "2"), WireEnd(f2.id, "1")))
    return p, s, f1, f2, f3, t1


def _state(p):
    return json.dumps(p.to_dict(), sort_keys=True, ensure_ascii=False)


def test_constants():
    assert BULK_ATTR_KEYS == ("func", "loc", "note")


def test_bulk_field_defaults():
    f = BulkField()
    assert (f.value, f.mixed, f.enabled) == ("", False, True)


# ---- bulk_common --------------------------------------------------------------------------------------------
def test_common_keys_and_values():
    _p, s, f1, f2, f3, _t = _project()
    c = bulk_common(s, [f1.id, f2.id, f3.id])
    assert set(c) == {"component", "func", "loc", "note"}
    assert c["loc"] == BulkField("R1", False, True)
    assert c["note"].value == "stejná" and not c["note"].mixed
    assert c["func"].mixed and c["func"].value == ""     # AC / DC / chybí
    assert c["component"] == BulkField("", False, True)  # nikdo nemá artikl, stejné značky


def test_common_missing_attr_counts_as_empty_and_mixed():
    _p, s, f1, _f2, f3, _t = _project()
    c = bulk_common(s, [f1.id, f3.id])      # "AC" vs. chybí
    assert c["func"].mixed


def test_common_all_missing_is_empty_not_mixed():
    _p, s, _f1, _f2, f3, _t = _project()
    del f3.attrs["note"]
    c = bulk_common(s, [f3.id])
    assert c["note"] == BulkField("", False, True)


def test_common_component_same_and_mixed():
    _p, s, f1, f2, f3, _t = _project()
    f1.component_id = f2.component_id = ART_A
    assert bulk_common(s, [f1.id, f2.id])["component"] == BulkField(ART_A, False, True)
    c = bulk_common(s, [f1.id, f2.id, f3.id])["component"]      # f3 bez artiklu
    assert c.mixed and c.value == "" and c.enabled
    f3.component_id = ART_B
    assert bulk_common(s, [f1.id, f3.id])["component"].mixed


def test_common_component_disabled_for_different_symbols():
    _p, s, f1, _f2, _f3, t1 = _project()
    c = bulk_common(s, [f1.id, t1.id])
    assert c["component"].enabled is False
    assert c["func"].enabled and c["loc"].enabled and c["note"].enabled


def test_common_empty_selection_disables_all():
    _p, s, *_ = _project()
    c = bulk_common(s, [])
    assert set(c) == {"component", "func", "loc", "note"}
    assert all(f.enabled is False for f in c.values())


def test_common_ignores_wire_ids():
    _p, s, f1, *_ = _project()
    wid = s.wires[0].id
    c = bulk_common(s, [f1.id, wid])
    assert c["loc"].value == "R1" and not c["loc"].mixed and c["component"].enabled
    assert all(f.enabled is False for f in bulk_common(s, [wid]).values())


# ---- bulk_changes -------------------------------------------------------------------------------------------
def test_set_value_for_all():
    p, s, f1, f2, f3, _t = _project()
    before = _state(p)
    ch = bulk_changes(s, [f1.id, f2.id, f3.id], func="DC", note="  nová  ")
    assert _state(p) == before                        # nic nemění
    got = {(c.element_id, c.key): (c.old, c.new) for c in ch}
    assert got == {
        (f1.id, "func"): ("AC", "DC"),
        (f3.id, "func"): ("", "DC"),
        (f1.id, "note"): ("stejná", "nová"),
        (f2.id, "note"): ("stejná", "nová"),
        (f3.id, "note"): ("stejná", "nová"),
    }                                                  # f2 už DC → bez změny
    assert all(isinstance(c, BulkChange) for c in ch)


def test_none_keeps_mixed_values():
    p, s, f1, f2, f3, _t = _project()
    assert bulk_changes(s, [f1.id, f2.id, f3.id]) == []
    assert bulk_changes(s, [f1.id, f2.id, f3.id], func=None, loc="R1") == []   # loc už R1
    assert bulk_edit_elements(p, s, [f1.id, f2.id, f3.id], loc="R1") == 0
    assert (f1.attrs["func"], f2.attrs["func"], "func" in f3.attrs) == ("AC", "DC", False)


def test_clear_with_empty_string():
    p, s, f1, f2, f3, _t = _project()
    ch = bulk_changes(s, [f1.id, f2.id, f3.id], func="", note="")
    got = {(c.element_id, c.key): (c.old, c.new) for c in ch}
    assert got[(f1.id, "func")] == ("AC", "")
    assert got[(f2.id, "func")] == ("DC", "")
    assert (f3.id, "func") not in got                  # chybějící == "" → bez změny
    assert got[(f1.id, "note")] == ("stejná", "")
    assert bulk_edit_elements(p, s, [f1.id, f2.id, f3.id], func="", note="") == 3
    for e in (f1, f2, f3):
        assert not e.attrs.get("func") and not e.attrs.get("note")


def test_clear_component():
    p, s, f1, f2, _f3, _t = _project()
    f1.component_id = f2.component_id = ART_A
    ch = bulk_changes(s, [f1.id, f2.id], component="")
    comp = [c for c in ch if c.key == "component"]
    assert {(c.element_id, c.old, c.new) for c in comp} == {(f1.id, ART_A, None), (f2.id, ART_A, None)}
    assert bulk_edit_elements(p, s, [f1.id, f2.id], component="") == 2
    assert f1.component_id is None and f2.component_id is None


def test_normalization_upper_strip():
    p, s, f1, f2, f3, _t = _project()
    n = bulk_edit_elements(p, s, [f1.id, f2.id, f3.id], func="  rfve.ac ", loc=" q1 ")
    assert n == 3
    assert all(e.attrs["func"] == "RFVE.AC" and e.attrs["loc"] == "Q1" for e in (f1, f2, f3))


@pytest.mark.parametrize("kw", [{"func": "1AB"}, {"loc": "a b"}, {"func": "A-B"}, {"loc": "X" * 40}])
def test_invalid_code_raises_and_changes_nothing(kw):
    p, s, f1, f2, f3, _t = _project()
    before = _state(p)
    with pytest.raises(ValueError):
        bulk_changes(s, [f1.id, f2.id, f3.id], **kw)
    with pytest.raises(ValueError):
        bulk_edit_elements(p, s, [f1.id, f2.id, f3.id], **kw)
    assert _state(p) == before


def test_note_is_free_text_not_validated():
    p, s, f1, *_ = _project()
    assert bulk_edit_elements(p, s, [f1.id], note=" pozn. s mezerami & 1-2 ") == 1
    assert f1.attrs["note"] == "pozn. s mezerami & 1-2"


def test_component_for_same_symbol_resets_manual_sizes():
    p, s, f1, f2, f3, _t = _project()
    f1.attrs.update({"width_mm": "35", "height_mm": "90"})
    f2.attrs["depth_mm"] = "70"
    ch = bulk_changes(s, [f1.id, f2.id, f3.id], component=ART_A)
    comp = {c.element_id: c for c in ch if c.key == "component"}
    assert set(comp) == {f1.id, f2.id, f3.id}
    assert all(c.old is None and c.new == ART_A for c in comp.values())
    sizes = {(c.element_id, c.key): (c.old, c.new) for c in ch if c.key.endswith("_mm")}
    assert sizes == {(f1.id, "width_mm"): ("35", ""), (f1.id, "height_mm"): ("90", ""), (f2.id, "depth_mm"): ("70", "")}
    assert bulk_edit_elements(p, s, [f1.id, f2.id, f3.id], component=ART_A) == 3
    assert all(e.component_id == ART_A for e in (f1, f2, f3))
    assert not any(e.attrs.get(k) for e in (f1, f2, f3) for k in ("width_mm", "height_mm", "depth_mm"))


def test_same_component_no_change():
    _p, s, f1, f2, *_ = _project()
    f1.component_id = f2.component_id = ART_A
    f1.attrs["width_mm"] = "35"
    assert bulk_changes(s, [f1.id, f2.id], component=ART_A) == []
    assert f1.attrs["width_mm"] == "35"


def test_component_for_different_symbols_raises():
    p, s, f1, _f2, _f3, t1 = _project()
    before = _state(p)
    with pytest.raises(ValueError):
        bulk_changes(s, [f1.id, t1.id], component=ART_A)
    with pytest.raises(ValueError):
        bulk_edit_elements(p, s, [f1.id, t1.id], component=ART_A)
    assert _state(p) == before
    # bez zadaného artiklu jdou ostatní pole i u různých značek
    assert bulk_edit_elements(p, s, [f1.id, t1.id], note="x") == 2


def test_wire_ids_ignored_in_changes():
    p, s, f1, f2, *_ = _project()
    wid = s.wires[0].id
    ch = bulk_changes(s, [f1.id, wid, f2.id], note="x")
    assert {c.element_id for c in ch} == {f1.id, f2.id}
    assert bulk_edit_elements(p, s, [wid], note="x") == 0


# ---- bulk_edit_elements -------------------------------------------------------------------------------------
def test_edit_counts_changed_elements_not_changes():
    p, s, f1, f2, f3, _t = _project()
    # f2 má func=DC → mění se jen f1 a f3; každý prvek se počítá jednou, i když se mění víc polí
    n = bulk_edit_elements(p, s, [f1.id, f2.id, f3.id], func="DC", loc="R2", note="n")
    assert n == 3
    n = bulk_edit_elements(p, s, [f1.id, f2.id, f3.id], func="DC", loc="R2", note="n")
    assert n == 0
    assert f2.attrs == {"ref": "F2", "func": "DC", "loc": "R2", "note": "n"}


def test_edit_partial_count():
    p, s, f1, f2, f3, _t = _project()
    assert bulk_edit_elements(p, s, [f1.id, f2.id, f3.id], func="DC") == 2   # f1, f3
    assert f1.attrs["func"] == f2.attrs["func"] == f3.attrs["func"] == "DC"


def test_edit_empty_selection():
    p, s, *_ = _project()
    before = _state(p)
    assert bulk_edit_elements(p, s, [], func="AC", note="x", component="") == 0
    assert _state(p) == before
    assert bulk_changes(s, [], func="AC") == []


def test_edit_does_not_touch_unselected_and_ref():
    p, s, f1, f2, f3, t1 = _project()
    bulk_edit_elements(p, s, [f1.id, f2.id], note="jen dva")
    assert f3.attrs["note"] == "stejná" and "note" not in t1.attrs
    assert [e.ref for e in (f1, f2, f3, t1)] == ["F1", "F2", "F3", "T1"]
