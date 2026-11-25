"""Lokální normové tabulky (#82): formát `envocad-norms`, načítání z `ENVOCAD_HOME/norms`, dosazení do výpočtů
Iz (`calc`) a oteplení (`thermal`). Čísla v souborech jsou VYMYSLENÁ (1, 2, 3 …); vestavěné hodnoty se berou
odkazem na konstanty `calc` / `thermal`, ne opisem."""
from __future__ import annotations

import copy
import dataclasses
import json
import math
from types import SimpleNamespace

import pytest

from envocad.library import norms
from envocad.model import calc, norm_tables, thermal

B1_KEY = "iz/cu/pvc70/3/B1"
B1_FAKE = {1.5: 1, 2.5: 2, 4: 3}
MOUNTINGS = ("volně stojící", "nástěnná", "zapuštěná", "stojanová")
SURFACES = ("top", "bottom", "front", "back", "side")


@pytest.fixture(autouse=True)
def _clean_norm_cache():
    """Cache tabulek je stav procesu – test ji nesmí zanechat naplněnou (conftest ji zatím nečistí)."""
    norm_tables.clear_cache()
    yield
    norm_tables.clear_cache()


# ---- pomocníci -------------------------------------------------------------------------------------------------
def make_doc() -> dict:
    """Platný dokument se všemi položkami (vymyšlená čísla)."""
    b = {m: {"top": 1, "bottom": 0, "front": 1, "back": 1, "side": 1} for m in MOUNTINGS}
    return {
        "format": "envocad-norms", "format_version": 1,
        "source": {"standard": "PŘÍKLAD 0000-0", "edition": "ed. 9", "year": 2099, "amendments": ["Z1"],
                   "transcribed_by": "PR", "transcribed_on": "2099-01-01", "checked_by": "", "note": ""},
        "tables": {
            "iz": [{"conductor": "cu", "insulation": "pvc70", "loaded": 3, "t_ref_c": 30, "method": "B1",
                    "ref": "tab. X.1 sl. 3", "unit": "A", "points": [[1.5, 1], [2.5, 2], [4, 3]]}],
            "iz_2_factor": {"ref": "čl. 1.2", "value": 2},
            "al_factor": {"ref": "čl. 1.3", "value": 0.5},
            "k_temp_air": [{"insulation": "pvc70", "ref": "tab. X.2", "points": [[30, 1], [35, 2]]}],
            "k_large_no_vents": {"ref": "obr. 3", "points": [[1, 1], [2, 2]]},
            "k_small": {"ref": "obr. 4", "points": [[0.1, 3], [1.25, 2]]},
            "c_large_no_vents": {"ref": "obr. 6", "points": [[1, 1], [2, 2]]},
            "c_small": {"ref": "obr. 7", "points": [[0, 1], [3, 2]]},
            "d_partitions_no_vents": {"ref": "tab. 2", "points": [[0, 1], [1, 2], [2, 3], [3, 3]]},
            "b_factors": {"ref": "tab. 3", "value": b},
            "x_large": {"ref": "čl. 1", "value": 0.5},
            "x_small": {"ref": "čl. 1", "value": 0.25},
            "ae_limit_m2": {"ref": "čl. 1", "value": 1},
        },
    }


def doc_with(**tables) -> dict:
    """Platný dokument jen s vybranými položkami `tables` (částečné přepsání)."""
    doc = make_doc()
    doc["tables"] = tables
    return doc


def iz_item(method="B1", points=None, **over) -> dict:
    item = {"conductor": "cu", "insulation": "pvc70", "loaded": 3, "t_ref_c": 30, "method": method,
            "ref": "tab. X.1", "unit": "A", "points": points or [[1.5, 1], [2.5, 2], [4, 3]]}
    item.update(over)
    return item


def set_path(doc, path: str, value):
    cur = doc
    keys = path.split(".")
    for k in keys[:-1]:
        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
    last = keys[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value
    return doc


def del_path(doc, path: str):
    cur = doc
    keys = path.split(".")
    for k in keys[:-1]:
        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
    del cur[keys[-1]]
    return doc


def write_norm(home, name: str, doc) -> None:
    folder = home / "norms"
    folder.mkdir(exist_ok=True)
    text = doc if isinstance(doc, (str, bytes)) else json.dumps(doc, ensure_ascii=False)
    (folder / name).write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("ENVOCAD_HOME", str(h))
    return h


def wire(**attrs):
    return SimpleNamespace(attrs=attrs)


def expected_rise(w, h, d, mounting, p, partitions=0, plastic=False):
    """Dosavadní postup `temperature_rise` poskládaný z existujících funkcí (referenční výsledek)."""
    ae = thermal.cooling_area(w, h, d, mounting)
    if plastic:
        ae /= thermal.K_PLASTIC_PENALTY
    x = thermal.X_LARGE if ae > thermal.AE_LIMIT_M2 else thermal.X_SMALL
    k, dd, c = thermal.k_factor(ae), thermal.d_factor(partitions), thermal.c_factor(ae, h, w, d)
    mid = k * dd * p ** x if p > 0 else 0.0
    return ae, k, c, dd, x, mid, c * mid


# ---- BUILTIN ---------------------------------------------------------------------------------------------------
def test_builtin_mirrors_module_constants():
    b = norm_tables.BUILTIN
    assert b.iz3 == calc.IZ_3
    assert b.iz2_factor == calc.IZ_2_FACTOR and b.al_factor == calc.AL_FACTOR
    assert b.k_t_pvc_air == calc.K_T_PVC_AIR
    assert tuple(b.k_large_no_vents) == thermal.K_LARGE_NO_VENTS
    assert tuple(b.k_small) == thermal.K_SMALL
    assert tuple(b.c_large_no_vents) == thermal.C_LARGE_NO_VENTS
    assert tuple(b.c_small) == thermal.C_SMALL
    assert b.d_partitions_no_vents == thermal.D_PARTITIONS_NO_VENTS
    assert b.b_factors == thermal.B_FACTORS
    assert (b.x_large, b.x_small, b.ae_limit_m2) == (thermal.X_LARGE, thermal.X_SMALL, thermal.AE_LIMIT_M2)


def test_builtin_sources_are_all_builtin():
    assert all(v is None for v in norm_tables.BUILTIN.sources.values())
    assert norm_tables.is_builtin("k_small")
    assert norm_tables.is_builtin(B1_KEY)


def test_normtables_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        norm_tables.BUILTIN.al_factor = 1.0  # type: ignore[misc]


def test_format_constants():
    assert norm_tables.NORMS_FORMAT == "envocad-norms"
    assert norm_tables.NORMS_FORMAT_VERSION == 1


# ---- current() bez souborů, cache, reload ----------------------------------------------------------------------
def test_without_files_current_is_builtin(home):
    assert norm_tables.current() is norm_tables.BUILTIN
    rep = norm_tables.load_report()
    assert rep.files_used == [] and rep.files_rejected == [] and rep.warnings == []


def test_norms_dir_is_under_home_and_not_created(home):
    assert norms.norms_dir() == home / "norms"
    assert not (home / "norms").exists()
    norm_tables.current()
    assert not (home / "norms").exists()


def test_load_dir_missing_or_empty_dir_gives_builtin(tmp_path):
    t, rep = norms.load_dir(tmp_path / "neexistuje")
    assert t == norm_tables.BUILTIN and rep.files_used == [] and rep.files_rejected == []
    (tmp_path / "prazdna").mkdir()
    (tmp_path / "prazdna" / "README.txt").write_text("není json", encoding="utf-8")
    t, rep = norms.load_dir(tmp_path / "prazdna")
    assert t == norm_tables.BUILTIN and rep.files_used == [] and rep.files_rejected == []


def test_file_is_not_watched_until_reload(home):
    assert norm_tables.current() is norm_tables.BUILTIN
    write_norm(home, "a.json", doc_with(iz=[iz_item()]))
    assert norm_tables.current() is norm_tables.BUILTIN          # cache
    assert calc.ampacity(2.5, "B1") == pytest.approx(round(calc.IZ_3["B1"][2.5], 1))
    t = norm_tables.reload()
    assert t is norm_tables.current() and t is not norm_tables.BUILTIN
    assert calc.ampacity(2.5, "B1") == 2.0
    norm_tables.clear_cache()
    assert norm_tables.current().iz3["B1"] == B1_FAKE            # po clear_cache se čte znovu


def test_cache_key_is_norms_dir(tmp_path, monkeypatch):
    h1, h2 = tmp_path / "h1", tmp_path / "h2"
    h1.mkdir(), h2.mkdir()
    write_norm(h1, "a.json", doc_with(iz=[iz_item()]))
    monkeypatch.setenv("ENVOCAD_HOME", str(h1))
    assert norm_tables.current().iz3["B1"] == B1_FAKE
    monkeypatch.setenv("ENVOCAD_HOME", str(h2))
    assert norm_tables.current() is norm_tables.BUILTIN


def test_builtin_behaviour_identical_before_and_after_load(home):
    ref = {m: calc.ampacity(25, m) for m in calc.IZ_3}
    for m, v in ref.items():
        assert v == round(calc.IZ_3[m][25], 1)
    write_norm(home, "a.json", doc_with(iz=[iz_item()]))
    norm_tables.reload()
    norm_tables.clear_cache()
    assert calc.IZ_3["B1"][25] == norm_tables.BUILTIN.iz3["B1"][25]
    for m in calc.IZ_3:
        if m != "B1":
            assert calc.ampacity(25, m) == ref[m]


# ---- dosazení: Iz ----------------------------------------------------------------------------------------------
def test_file_overrides_only_one_method(home):
    write_norm(home, "a.json", doc_with(iz=[iz_item()]))
    norm_tables.reload()
    assert calc.ampacity(2.5, "B1") == 2.0
    assert calc.ampacity(1.5, "B1") == 1.0
    assert calc.ampacity(2.0, "B1") == pytest.approx(1.6)         # průřez mimo řadu: lineární odhad
    assert calc.ampacity(5, "B1") is None                         # řada si bere průřezy ze souboru
    cur = norm_tables.current()
    assert cur.iz3["B1"] == B1_FAKE
    for m in calc.IZ_3:
        if m != "B1":
            assert cur.iz3[m] == calc.IZ_3[m]
            assert calc.ampacity(10, m) == round(calc.IZ_3[m][10], 1)
    assert cur.iz2_factor == calc.IZ_2_FACTOR and cur.al_factor == calc.AL_FACTOR
    assert cur.k_small == norm_tables.BUILTIN.k_small


def test_file_overrides_factors_and_temperature(home):
    write_norm(home, "a.json", doc_with(
        iz=[iz_item()], iz_2_factor={"ref": "r", "value": 2}, al_factor={"ref": "r", "value": 0.5},
        k_temp_air=[{"insulation": "pvc70", "ref": "r", "points": [[30, 1], [35, 2]]}]))
    norm_tables.reload()
    assert calc.ampacity(2.5, "B1", loaded=2) == 4.0
    assert calc.ampacity(2.5, "B1", aluminium=True) == 1.0
    assert calc.ampacity(2.5, "B1", t_ambient=35) == 4.0
    assert calc.ampacity(2.5, "B1", t_ambient=50) == 4.0          # chybí klíč, t > 30 → nejvyšší teplota tabulky
    assert calc.ampacity(2.5, "B1", t_ambient=20) == 2.0          # chybí klíč, t ≤ 30 → 1,0
    assert calc.ampacity(2.5, "B1", grouping=0.5) == 1.0


def test_builtin_temperature_factor_unchanged():
    top = max(calc.K_T_PVC_AIR)
    iz = calc.IZ_3["C"][25]
    assert calc.ampacity(25, "C", t_ambient=40) == round(iz * calc.K_T_PVC_AIR[40], 1)
    assert calc.ampacity(25, "C", t_ambient=55) == round(iz * calc.K_T_PVC_AIR[top], 1)
    assert calc.ampacity(25, "C", t_ambient=20) == round(iz, 1)
    assert calc.ampacity(25, "C", t_ambient=28) == round(iz * calc.K_T_PVC_AIR[30], 1)


def test_min_cross_uses_file(home):
    write_norm(home, "a.json", doc_with(iz=[iz_item()]))
    norm_tables.reload()
    assert calc.min_cross(2, "B1") == 2.5
    assert calc.min_cross(3, "B1") == 4.0
    assert calc.min_cross(3.5, "B1") is None
    assert calc.min_cross(40, "C") == next(c for c in sorted(calc.IZ_3["C"]) if round(calc.IZ_3["C"][c], 1) >= 40)


def test_route_method_keeps_method_set(home):
    write_norm(home, "a.json", doc_with(iz=[iz_item()]))
    norm_tables.reload()
    assert set(norm_tables.current().iz3) == set(calc.IZ_3)
    for m in calc.IZ_3:
        assert calc.route_method(wire(method=m.lower())) == m
    assert calc.route_method(wire(route="v zemi")) == "D"
    assert calc.route_method(wire()) == "C"


def test_tables_parameter(home):
    t = dataclasses.replace(norm_tables.BUILTIN, iz3={**norm_tables.BUILTIN.iz3, "B1": B1_FAKE},
                            iz2_factor=2, al_factor=0.5)
    assert calc.ampacity(2.5, "B1", tables=t) == 2.0
    assert calc.ampacity(2.5, "B1", loaded=2, tables=t) == 4.0
    assert calc.ampacity(2.5, "B1", aluminium=True, tables=t) == 1.0
    assert calc.min_cross(3, "B1", tables=t) == 4.0
    assert calc.route_method(wire(method="B1"), tables=t) == "B1"
    # globální stav tím nedotčen
    assert norm_tables.current() is norm_tables.BUILTIN
    assert calc.ampacity(2.5, "B1") == round(calc.IZ_3["B1"][2.5], 1)


def test_route_method_tables_without_method(home):
    t = dataclasses.replace(norm_tables.BUILTIN, iz3={"C": B1_FAKE})
    assert calc.route_method(wire(method="B1"), tables=t) == "C"


# ---- dosazení: oteplení ----------------------------------------------------------------------------------------
RISE_CASES = [
    (600, 800, 250, "nástěnná", 120, 0, False),
    (800, 2000, 400, "volně stojící", 500, 0, False),
    (800, 2000, 400, "volně stojící", 500, 2, True),
    (300, 400, 200, "zapuštěná", 30, 1, False),
    (300, 400, 200, "stojanová", 0, 0, False),
    (1200, 2000, 600, "nástěnná", 900, 5, False),
]


@pytest.mark.parametrize("args", RISE_CASES)
def test_enclosure_rise_matches_existing_functions(args):
    ae, k, c, dd, x, mid, top = expected_rise(*args)
    r = thermal.enclosure_rise(*args)
    assert r.ae_m2 == pytest.approx(ae, rel=1e-12)
    assert (r.k, r.c, r.d, r.x) == (pytest.approx(k, rel=1e-12), pytest.approx(c, rel=1e-12), dd, x)
    assert r.dt_mid_k == pytest.approx(mid, rel=1e-12)
    assert r.dt_top_k == pytest.approx(top, rel=1e-12)
    assert dataclasses.is_dataclass(r) and r.__dataclass_params__.frozen


@pytest.mark.parametrize("args", RISE_CASES)
def test_enclosure_rise_with_explicit_builtin_tables(args):
    assert thermal.enclosure_rise(*args, tables=norm_tables.BUILTIN) == thermal.enclosure_rise(*args)


def test_thermal_functions_accept_tables():
    t = norm_tables.BUILTIN
    assert thermal.k_factor(0.5, tables=t) == thermal.k_factor(0.5)
    assert thermal.k_factor(3.0, tables=t) == thermal.k_factor(3.0)
    assert thermal.d_factor(2, tables=t) == thermal.d_factor(2)
    assert thermal.c_factor(1.0, 800, 600, 250, tables=t) == thermal.c_factor(1.0, 800, 600, 250)
    assert thermal.cooling_area(600, 800, 250, "nástěnná", tables=t) == thermal.cooling_area(600, 800, 250, "nástěnná")


def test_file_overrides_thermal_tables(home):
    write_norm(home, "a.json", {**make_doc(), "tables": {k: v for k, v in make_doc()["tables"].items()
                                                          if k not in ("iz", "k_temp_air")}})
    norm_tables.reload()
    assert thermal.k_factor(1.0) == pytest.approx(3 + (2 - 3) * (1.0 - 0.1) / (1.25 - 0.1))
    assert thermal.k_factor(2.0) == pytest.approx(2.0)                # ae_limit = 1 → velká skříň, křivka 1→1, 2→2
    assert thermal.d_factor(1) == 2.0 and thermal.d_factor(9) == 3.0
    # nástěnná: top 1, bottom 0, front 1, back 1, side 1
    w, h, d = 600, 800, 250
    assert thermal.cooling_area(w, h, d, "nástěnná") == pytest.approx(
        (w / 1000) * (d / 1000) + 2 * (w / 1000) * (h / 1000) + 2 * (h / 1000) * (d / 1000))
    r = thermal.enclosure_rise(300, 400, 200, "nástěnná", 10)
    assert r.x == 0.25 and r.ae_m2 <= 1
    assert r.dt_mid_k == pytest.approx(r.k * r.d * 10 ** 0.25)
    assert thermal.enclosure_rise(2000, 2000, 600, "nástěnná", 10).x == 0.5
    # globální konstanty modulů se nezměnily
    assert thermal.X_SMALL == norm_tables.BUILTIN.x_small and thermal.AE_LIMIT_M2 == norm_tables.BUILTIN.ae_limit_m2


def test_temperature_rise_uses_current_tables(home):
    from envocad.model.project import Sheet
    sheet = Sheet(name="L1")
    before = thermal.temperature_rise(sheet)
    write_norm(home, "a.json", doc_with(x_small={"ref": "r", "value": 0.25}, ae_limit_m2={"ref": "r", "value": 100}))
    assert thermal.temperature_rise(sheet) == before                  # cache bez reload
    norm_tables.reload()
    after = thermal.temperature_rise(sheet)
    assert after.x == 0.25


# ---- validace: odmítnutí celého souboru -----------------------------------------------------------------------
def _nan(d):
    return set_path(d, "tables.al_factor.value", float("nan"))


REJECT_RULES = {
    "format": lambda d: set_path(d, "format", "jiny"),
    "format_chybi": lambda d: del_path(d, "format"),
    "verze_chybi": lambda d: del_path(d, "format_version"),
    "verze_text": lambda d: set_path(d, "format_version", "1"),
    "verze_desetinna": lambda d: set_path(d, "format_version", 1.5),
    "verze_vyssi": lambda d: set_path(d, "format_version", 2),
    "verze_nula": lambda d: set_path(d, "format_version", 0),
    "verze_zaporna": lambda d: set_path(d, "format_version", -1),
    "source_standard": lambda d: del_path(d, "source.standard"),
    "source_edition": lambda d: del_path(d, "source.edition"),
    "source_year": lambda d: del_path(d, "source.year"),
    "source_transcribed_by": lambda d: del_path(d, "source.transcribed_by"),
    "source_transcribed_on": lambda d: del_path(d, "source.transcribed_on"),
    "source_chybi": lambda d: del_path(d, "source"),
    "ref_iz": lambda d: del_path(d, "tables.iz.0.ref"),
    "ref_skalar": lambda d: del_path(d, "tables.al_factor.ref"),
    "ref_krivka": lambda d: del_path(d, "tables.k_small.ref"),
    "ref_k_temp": lambda d: del_path(d, "tables.k_temp_air.0.ref"),
    "ref_b": lambda d: del_path(d, "tables.b_factors.ref"),
    "neznamy_klic_tables": lambda d: set_path(d, "tables.neco_noveho", {"ref": "r", "value": 1}),
    "hodnota_nan": _nan,
    "hodnota_inf": lambda d: set_path(d, "tables.x_small.value", float("inf")),
    "hodnota_bool": lambda d: set_path(d, "tables.al_factor.value", True),
    "hodnota_text": lambda d: set_path(d, "tables.al_factor.value", "1"),
    "hodnota_nula": lambda d: set_path(d, "tables.al_factor.value", 0),
    "hodnota_zaporna": lambda d: set_path(d, "tables.iz_2_factor.value", -1),
    "ae_limit_nula": lambda d: set_path(d, "tables.ae_limit_m2.value", 0),
    "iz_hodnota_nula": lambda d: set_path(d, "tables.iz.0.points", [[1.5, 0], [2.5, 2]]),
    "iz_hodnota_bool": lambda d: set_path(d, "tables.iz.0.points", [[1.5, True], [2.5, 2]]),
    "krivka_y_nula": lambda d: set_path(d, "tables.k_small.points", [[1, 0], [2, 2]]),
    "krivka_y_zaporna": lambda d: set_path(d, "tables.c_small.points", [[1, -1], [2, 2]]),
    "krivka_x_zaporna": lambda d: set_path(d, "tables.c_small.points", [[-1, 1], [2, 2]]),
    "krivka_x_nan": lambda d: set_path(d, "tables.c_small.points", [[float("nan"), 1], [2, 2]]),
    "krivka_jeden_bod": lambda d: set_path(d, "tables.k_small.points", [[1, 1]]),
    "krivka_zadny_bod": lambda d: set_path(d, "tables.k_small.points", []),
    "iz_jeden_bod": lambda d: set_path(d, "tables.iz.0.points", [[1.5, 1]]),
    "krivka_x_stejne": lambda d: set_path(d, "tables.k_small.points", [[1, 1], [1, 2]]),
    "krivka_x_klesajici": lambda d: set_path(d, "tables.k_large_no_vents.points", [[2, 1], [1, 2]]),
    "iz_x_klesajici": lambda d: set_path(d, "tables.iz.0.points", [[4, 3], [2.5, 2]]),
    "iz_klesa_s_prurezem": lambda d: set_path(d, "tables.iz.0.points", [[1.5, 3], [2.5, 2], [4, 1]]),
    "k_temp_jeden_bod": lambda d: set_path(d, "tables.k_temp_air.0.points", [[30, 1]]),
    "k_temp_x_klesajici": lambda d: set_path(d, "tables.k_temp_air.0.points", [[35, 1], [30, 2]]),
    "d_bez_nuly": lambda d: set_path(d, "tables.d_partitions_no_vents.points", [[1, 1], [2, 2], [3, 3]]),
    "d_bez_trojky": lambda d: set_path(d, "tables.d_partitions_no_vents.points", [[0, 1], [1, 2], [2, 3]]),
    "d_bez_jednicky": lambda d: set_path(d, "tables.d_partitions_no_vents.points", [[0, 1], [2, 2], [3, 3]]),
    "d_hodnota_nula": lambda d: set_path(d, "tables.d_partitions_no_vents.points",
                                         [[0, 1], [1, 0], [2, 3], [3, 3]]),
    "b_chybi_montaz": lambda d: del_path(d, "tables.b_factors.value.zapuštěná"),
    "b_chybi_stojanova": lambda d: del_path(d, "tables.b_factors.value.stojanová"),
    "b_chybi_plocha_top": lambda d: del_path(d, "tables.b_factors.value.nástěnná.top"),
    "b_chybi_plocha_side": lambda d: del_path(d, "tables.b_factors.value.volně stojící.side"),
    "b_top_nula": lambda d: set_path(d, "tables.b_factors.value.nástěnná.top", 0),
    "b_bottom_zaporne": lambda d: set_path(d, "tables.b_factors.value.nástěnná.bottom", -1),
    "b_front_text": lambda d: set_path(d, "tables.b_factors.value.nástěnná.front", "1"),
}


def test_full_document_is_accepted():
    t, errors, warnings = norm_tables.apply_document(make_doc(), norm_tables.BUILTIN, path="x.json")
    assert t is not None and errors == [] and warnings == []


def test_zero_allowed_where_spec_says():
    doc = make_doc()
    doc["tables"]["b_factors"]["value"]["nástěnná"]["bottom"] = 0
    doc["tables"]["c_small"]["points"] = [[0, 1], [3, 2]]
    doc["tables"]["d_partitions_no_vents"]["points"] = [[0, 1], [1, 2], [2, 3], [3, 3]]
    t, errors, _ = norm_tables.apply_document(doc, norm_tables.BUILTIN)
    assert t is not None and errors == []
    assert t.b_factors["nástěnná"][1] == 0
    assert t.b_factors["nástěnná"] == (1, 0, 1, 1, 1)               # pořadí (top, bottom, front, back, side)


@pytest.mark.parametrize("name", sorted(REJECT_RULES))
def test_apply_document_rejects_whole_file(name):
    base = norm_tables.BUILTIN
    doc = REJECT_RULES[name](make_doc())
    t, errors, _warnings = norm_tables.apply_document(doc, base, path="bad.json")
    assert t is None
    assert errors and all(isinstance(e, str) and e for e in errors)


@pytest.mark.parametrize("root", [[], "text", 5, None, [make_doc()]])
def test_apply_document_rejects_non_object_root(root):
    t, errors, _ = norm_tables.apply_document(root, norm_tables.BUILTIN)
    assert t is None and errors


@pytest.mark.parametrize("name", sorted(REJECT_RULES))
def test_rejected_file_keeps_builtin_and_calc_works(home, name):
    write_norm(home, "bad.json", REJECT_RULES[name](make_doc()))
    t = norm_tables.reload()
    assert t == norm_tables.BUILTIN
    rep = norm_tables.load_report()
    assert rep.files_used == []
    assert len(rep.files_rejected) == 1
    fname, errors = rep.files_rejected[0]
    assert "bad.json" in fname and errors
    assert calc.ampacity(10, "B1") == round(calc.IZ_3["B1"][10], 1)
    assert thermal.enclosure_rise(600, 800, 250, "nástěnná", 50).ae_m2 == pytest.approx(
        expected_rise(600, 800, 250, "nástěnná", 50)[0])


@pytest.mark.parametrize("content", [b"{neplatny json", b"\xff\xfe\x00\x00", b"", b"[1, 2]", b'"text"', b"null"])
def test_unreadable_or_non_object_file_is_rejected(home, content):
    write_norm(home, "bad.json", content)
    assert norm_tables.reload() == norm_tables.BUILTIN
    rep = norm_tables.load_report()
    assert rep.files_used == [] and len(rep.files_rejected) == 1
    assert calc.ampacity(10, "C") == round(calc.IZ_3["C"][10], 1)


def test_rejected_file_keeps_previous_state(home):
    write_norm(home, "a_ok.json", doc_with(iz=[iz_item()]))
    write_norm(home, "b_bad.json", set_path(make_doc(), "format", "jiny"))
    norm_tables.reload()
    assert norm_tables.current().iz3["B1"] == B1_FAKE               # tabulky z dosavadního stavu zůstaly
    rep = norm_tables.load_report()
    assert [p.replace("\\", "/").rsplit("/", 1)[-1] for p in rep.files_used] == ["a_ok.json"]
    assert [n.replace("\\", "/").rsplit("/", 1)[-1] for n, _ in rep.files_rejected] == ["b_bad.json"]


def test_files_are_read_sorted_by_name(home):
    write_norm(home, "c.json", doc_with(al_factor={"ref": "r", "value": 3}))
    write_norm(home, "a.json", doc_with(x_small={"ref": "r", "value": 2}))
    write_norm(home, "b.json", doc_with(x_large={"ref": "r", "value": 4}))
    norm_tables.reload()
    names = [p.replace("\\", "/").rsplit("/", 1)[-1] for p in norm_tables.load_report().files_used]
    assert names == ["a.json", "b.json", "c.json"]


# ---- varování --------------------------------------------------------------------------------------------------
UNIMPLEMENTED = {
    "vodic_al": {"conductor": "al"},
    "izolace_xlpe": {"insulation": "xlpe90"},
    "loaded_2": {"loaded": 2},
    "t_ref_40": {"t_ref_c": 40},
    "metoda_mimo": {"method": "Z9"},
}


@pytest.mark.parametrize("name", sorted(UNIMPLEMENTED))
def test_unimplemented_iz_combination_warns_and_is_skipped(name):
    over = UNIMPLEMENTED[name]
    item = iz_item("B1", **{k: v for k, v in over.items() if k != "method"})
    if "method" in over:
        item["method"] = over["method"]
    doc = doc_with(iz=[item], al_factor={"ref": "r", "value": 3})
    t, errors, warnings = norm_tables.apply_document(doc, norm_tables.BUILTIN)
    assert t is not None and errors == []
    assert warnings
    assert t.iz3 == calc.IZ_3 and "Z9" not in t.iz3
    assert t.al_factor == 3                                          # ostatní položky souboru se použijí


def test_unimplemented_k_temp_air_warns_and_is_skipped():
    doc = doc_with(k_temp_air=[{"insulation": "xlpe90", "ref": "r", "points": [[30, 1], [35, 2]]}])
    t, errors, warnings = norm_tables.apply_document(doc, norm_tables.BUILTIN)
    assert t is not None and errors == [] and warnings
    assert t.k_t_pvc_air == calc.K_T_PVC_AIR


def test_unimplemented_item_does_not_block_valid_one():
    doc = doc_with(iz=[iz_item("B1", conductor="al"), iz_item("C", points=[[1, 1], [2, 2]])])
    t, errors, warnings = norm_tables.apply_document(doc, norm_tables.BUILTIN)
    assert t is not None and errors == [] and warnings
    assert t.iz3["B1"] == calc.IZ_3["B1"]
    assert t.iz3["C"] == {1: 1, 2: 2}


def test_unknown_fields_only_warn():
    doc = make_doc()
    doc["source"]["neznamy"] = "x"
    t, errors, warnings = norm_tables.apply_document(doc, norm_tables.BUILTIN)
    assert t is not None and errors == [] and warnings
    doc = make_doc()
    doc["tables"]["iz"][0]["neznamy"] = "x"
    t, errors, warnings = norm_tables.apply_document(doc, norm_tables.BUILTIN)
    assert t is not None and errors == [] and warnings


def test_warnings_reach_load_report(home):
    write_norm(home, "a.json", doc_with(iz=[iz_item("B1", conductor="al")]))
    norm_tables.reload()
    rep = norm_tables.load_report()
    assert len(rep.files_used) == 1 and rep.warnings and rep.files_rejected == []


# ---- konflikt dvou souborů -------------------------------------------------------------------------------------
def test_conflict_keeps_builtin_for_item_and_warns(home):
    write_norm(home, "a.json", doc_with(iz=[iz_item()], al_factor={"ref": "r", "value": 3}))
    write_norm(home, "b.json", doc_with(iz=[iz_item(points=[[1.5, 5], [2.5, 6]])],
                                        x_small={"ref": "r", "value": 2}))
    t = norm_tables.reload()
    assert t.iz3["B1"] == calc.IZ_3["B1"]                            # sporná položka zůstává vestavěná
    assert norm_tables.is_builtin(B1_KEY)
    assert t.al_factor == 3 and t.x_small == 2                       # ostatní položky obou souborů platí
    rep = norm_tables.load_report()
    assert len(rep.files_used) == 2 and rep.files_rejected == []
    assert any("B1" in w for w in rep.warnings)


def test_conflict_on_scalar(home):
    write_norm(home, "a.json", doc_with(al_factor={"ref": "r", "value": 3}))
    write_norm(home, "b.json", doc_with(al_factor={"ref": "r", "value": 4}))
    t = norm_tables.reload()
    assert t.al_factor == calc.AL_FACTOR
    assert any("al_factor" in w for w in norm_tables.load_report().warnings)


def test_different_methods_in_two_files_do_not_conflict(home):
    write_norm(home, "a.json", doc_with(iz=[iz_item("B1")]))
    write_norm(home, "b.json", doc_with(iz=[iz_item("C", points=[[1, 1], [2, 2]])]))
    t = norm_tables.reload()
    assert t.iz3["B1"] == B1_FAKE and t.iz3["C"] == {1: 1, 2: 2}
    assert norm_tables.load_report().warnings == []


# ---- provenance / is_builtin / apply_document ------------------------------------------------------------------
def test_provenance_and_is_builtin(home):
    write_norm(home, "a.json", doc_with(iz=[iz_item()], k_small={"ref": "obr. 4", "points": [[1, 3], [2, 2]]}))
    norm_tables.reload()
    assert not norm_tables.is_builtin(B1_KEY) and not norm_tables.is_builtin("k_small")
    assert norm_tables.is_builtin("iz/cu/pvc70/3/C") and norm_tables.is_builtin("al_factor")
    src = norm_tables.provenance([B1_KEY, "iz/cu/pvc70/3/C"])
    assert set(src) == {B1_KEY, "iz/cu/pvc70/3/C"}
    s = src[B1_KEY]
    assert isinstance(s, norm_tables.NormSource)
    assert (s.standard, s.edition, s.year) == ("PŘÍKLAD 0000-0", "ed. 9", 2099)
    assert (s.ref, s.transcribed_by, s.transcribed_on) == ("tab. X.1", "PR", "2099-01-01")
    assert s.path.replace("\\", "/").endswith("a.json")
    assert len(s.sha256) == 64
    assert src["iz/cu/pvc70/3/C"] is None
    assert norm_tables.provenance(["k_small"])["k_small"].ref == "obr. 4"
    full = norm_tables.provenance()
    assert full[B1_KEY] == s and full["al_factor"] is None


def test_sha256_matches_file_bytes(home):
    import hashlib
    write_norm(home, "a.json", doc_with(iz=[iz_item()]))
    norm_tables.reload()
    data = (home / "norms" / "a.json").read_bytes()
    assert norm_tables.provenance([B1_KEY])[B1_KEY].sha256 == hashlib.sha256(data).hexdigest()


def test_apply_document_is_pure():
    base = norm_tables.BUILTIN
    iz_before, factor = copy.deepcopy(calc.IZ_3), calc.AL_FACTOR
    doc = make_doc()
    snapshot = copy.deepcopy(doc)
    t, errors, _ = norm_tables.apply_document(doc, base, path="p.json", sha256="abc")
    assert t is not None and errors == []
    assert t is not base and doc == snapshot
    assert base.iz3 == iz_before == calc.IZ_3 and calc.AL_FACTOR == factor == base.al_factor
    assert t.iz3["B1"] == B1_FAKE and t.al_factor == 0.5
    assert t.iz3["C"] == base.iz3["C"]
    s = t.sources[B1_KEY]
    assert s.path == "p.json" and s.sha256 == "abc" and s.ref == "tab. X.1 sl. 3"
    assert base.sources.get(B1_KEY) is None
    assert t.sources.get("k_small").ref == "obr. 4"
    r2, _, _ = norm_tables.apply_document(copy.deepcopy(doc), t)    # řetězení nad výsledkem
    assert r2 is not None and r2.al_factor == 0.5


def test_apply_document_partial_keeps_rest():
    t, errors, warnings = norm_tables.apply_document(doc_with(x_large={"ref": "r", "value": 7}),
                                                     norm_tables.BUILTIN)
    assert errors == [] and warnings == []
    assert t.x_large == 7 and t.x_small == norm_tables.BUILTIN.x_small
    assert t.iz3 == calc.IZ_3 and t.b_factors == thermal.B_FACTORS
    assert math.isfinite(t.al_factor)
