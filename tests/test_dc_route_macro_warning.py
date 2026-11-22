"""Issue #69: generátor varuje před vlastní kopií makra „DC string po trase“ (role dc_route), která ještě obsahuje
odpínač `fve.dc_disconnect` (vestavěné makro ho nemá). Jen varování – kopii nic nemění."""
import json
import logging
from pathlib import Path

from envocad.generate import build_project
from envocad.library.macros import user_dir

BUILTIN = Path(__file__).resolve().parents[1] / "envocad" / "library" / "builtin" / "macros" / "dc_string_po_trase.json"
_INV25 = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


def _spec(inverters=1):
    return {"module": {"isc": 18.5}, "dc": {"route_boxes": 2},
            "inverters": [{"ref": f"T{i + 1}", **_INV25, "strings": [20, 20]} for i in range(inverters)]}


def _write_user_macro(with_disconnect: bool) -> Path:
    data = json.loads(BUILTIN.read_text(encoding="utf-8"))
    if with_disconnect:
        data["fragment"]["elements"].append(
            {"id": "d15c0nnec700", "symbol_id": "fve.dc_disconnect", "x": 60, "y": 120, "rotation": 0,
             "attrs": {"ref": "Q{k}"}, "component_id": None})
    d = user_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / "dc_string_po_trase.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def _warnings(caplog):
    return [r for r in caplog.records
            if r.name == "envocad.generate" and r.levelno == logging.WARNING
            and "DC string po trase" in r.getMessage() and "odpínač" in r.getMessage()]


def _build(caplog, spec):
    with caplog.at_level(logging.WARNING, logger="envocad.generate"):
        return build_project(spec)


def test_user_copy_with_disconnect_warns_once(caplog):
    _write_user_macro(True)
    p = _build(caplog, _spec())
    assert len(_warnings(caplog)) == 1
    assert p.sheets


def test_warns_once_with_more_inverters(caplog):
    _write_user_macro(True)
    _build(caplog, _spec(inverters=2))
    assert len(_warnings(caplog)) == 1


def test_note_on_first_route_switchboard_sheet(caplog):
    _write_user_macro(True)
    p = _build(caplog, _spec(inverters=2))
    assert len(p.notes) == 1
    n = p.notes[0]
    assert n.status == "open" and n.no >= 1
    assert "DC string po trase" in n.text and "odpínač" in n.text
    sheet = next(s for s in p.sheets if s.id == n.sheet_id)
    assert sheet.is_switchboard


def test_builtin_macro_no_warning(caplog):
    p = _build(caplog, _spec())
    assert not _warnings(caplog)
    assert p.notes == []


def test_user_copy_without_disconnect_no_warning(caplog):
    _write_user_macro(False)
    p = _build(caplog, _spec())
    assert not _warnings(caplog)
    assert p.notes == []


def test_user_file_unchanged(caplog):
    path = _write_user_macro(True)
    before = path.read_bytes()
    _build(caplog, _spec())
    assert path.read_bytes() == before
