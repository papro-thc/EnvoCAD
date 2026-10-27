"""Topologie připojení – model, knihovna presetů a výběr podle specifikace (bez Qt)."""

import json
import logging
import subprocess
import sys

import pytest

from envocad.generator import spec as gspec
from envocad.generator.spec import (
    ROLES,
    building_kind,
    chain_text,
    check_topology,
    installed_kwp,
    select_topology,
)
from envocad.library import topologies as tlib
from envocad.model.topology import (
    TOPOLOGY_VERSION,
    CableLink,
    ChainNode,
    Topology,
    parse_topology,
    validate_topology,
)


def _data(**kw):
    d = {"version": 1, "id": "test", "name": "Test", "level": "nn", "buildings": ["company"],
         "nodes": [{"role": "rfve_ac", "ref": "RFVE.AC"}, {"role": "inverter"}, {"role": "grid", "sheet": False}]}
    d.update(kw)
    return d


# ---- model ----------------------------------------------------------------------------------------------------------

def test_parse_topology_full():
    t = parse_topology({
        "id": "x", "name": " Řetězec ", "description": "popis", "level": "vn", "buildings": ["company"],
        "nodes": [
            {"role": "rfve_dc", "ref": "RFVE.DC", "desc": "DC", "per_inverter": True, "macros": {"dc_tech": "M1"}},
            {"role": "inverter"},
            {"role": "hr", "ref": "HR", "existing": True, "options": {"main_in": 160, "metering": True, "k": 2.5},
             "link": {"cable": "CYKY-J 5x35", "cross": 35, "length": 20.0, "method": "D"}},
            {"role": "re", "ref": "RE", "branch": True},
            {"role": "grid", "sheet": False}]}, source="sdílená", path="a/x.json")
    assert t.id == "x" and t.name == "Řetězec" and t.level == "vn" and t.buildings == ("company",)
    assert t.source == "sdílená" and t.path.name == "x.json" and t.description == "popis"
    dc = t.node("rfve_dc")
    assert dc.per_inverter and dc.sheet and not dc.existing and dict(dc.macros) == {"dc_tech": "M1"}
    hr = t.node("hr")
    assert hr.existing and dict(hr.options) == {"main_in": "160", "metering": "1", "k": "2.5"}
    assert hr.link == CableLink("CYKY-J 5x35", "35", "20", "D")
    assert t.node("grid").sheet is False and t.node("inverter").link == CableLink()
    assert t.node("neni") is None
    assert t.roles() == ("rfve_dc", "inverter", "hr", "re", "grid")
    assert [n.role for n in t.flow()] == ["rfve_dc", "inverter", "hr", "grid"]
    assert t.chain_text() == "RFVE.DC → inverter → HR → grid (+ RE)"
    assert t.chain_text("stringy", {"inverter": "T", "grid": "DS"}) == "stringy → RFVE.DC → T → HR → DS (+ RE)"
    with pytest.raises(TypeError):
        hr.options["x"] = "1"          # neměnné
    hash(hr)                           # zmrazený článek jde použít jako klíč


def test_parse_defaults():
    t = parse_topology({"id": "a", "name": "A", "nodes": [{"role": "inverter"}]})
    assert t.level == "nn" and t.buildings == () and t.source == "vlastní" and t.path is None
    n = t.nodes[0]
    assert n == ChainNode("inverter") and n.ref == "" and n.sheet and not n.per_inverter


def test_validate_valid():
    assert validate_topology(_data()) == []
    assert validate_topology(_data(), known_roles=ROLES) == []


@pytest.mark.parametrize(("data", "fragment"), [
    ([], "musí být objekt JSON"),
    (_data(id=""), "Chybí „id“"),
    (_data(id="a b"), "Neplatné „id“"),
    (_data(name=""), "chybí „name“"),
    (_data(name=5), "„name“ musí být text"),
    (_data(level="xx"), "Neplatná úroveň připojení „xx“"),
    (_data(buildings="house"), "„buildings“ musí být seznam"),
    (_data(version=TOPOLOGY_VERSION + 1), f"program umí nejvýše {TOPOLOGY_VERSION}"),
    (_data(version="1"), "Neplatná verze"),
    (_data(nodes=[]), "neprázdný seznam článků"),
    (_data(nodes=["x"]), "Článek 1: musí být objekt"),
    (_data(nodes=[{"ref": "X"}]), "Článek 1: chybí „role“"),
    (_data(nodes=[{"role": "RFVE"}]), "neplatná role „RFVE“"),
    (_data(nodes=[{"role": "hr"}, {"role": "hr"}]), "role „hr“ je v topologii dvakrát"),
    (_data(nodes=[{"role": "hr", "existing": "ano"}]), "„existing“ musí být true nebo false"),
    (_data(nodes=[{"role": "hr", "options": []}]), "„options“ musí být objekt"),
    (_data(nodes=[{"role": "hr", "options": {"a": [1]}}]), "hodnota „options.a“"),
    (_data(nodes=[{"role": "hr", "macros": {"1x": "M"}}]), "neplatný klíč „1x“"),
    (_data(nodes=[{"role": "hr", "link": "kabel"}]), "„link“ musí být objekt"),
    (_data(nodes=[{"role": "hr", "link": {"typ": "CYKY"}}]), "neznámý klíč „link.typ“"),
    (_data(nodes=[{"role": "hr", "rf": "HR"}]), "Článek 1 (hr): neznámý klíč „rf“"),
    (_data(nodes=[{"role": "re", "branch": True}]), "žádný článek hlavního toku"),
    (_data(extra=1), "Neznámý klíč topologie „extra“"),
])
def test_validate_errors_czech(data, fragment):
    errs = validate_topology(data)
    assert any(fragment in e for e in errs), errs
    with pytest.raises(ValueError, match="Neplatná topologie"):
        parse_topology(data)


def test_validate_known_roles():
    errs = validate_topology(_data(nodes=[{"role": "inverter"}, {"role": "trafo"}]), known_roles=ROLES)
    assert len(errs) == 1 and "neznámá role „trafo“" in errs[0] and "rfve_dc" in errs[0]
    assert validate_topology(_data(nodes=[{"role": "trafo"}])) == []    # bez known_roles se role nekontrolují


def test_model_has_no_qt():
    """Model, knihovna i výběr topologie jdou bez Qt a bez `envocad.generate` (souběžný refaktoring)."""
    code = ("import sys, envocad.model.topology, envocad.library.topologies, envocad.generator.spec; "
            "bad = [m for m in sys.modules if m.startswith('PySide6') or m == 'envocad.generate']; "
            "assert not bad, bad")
    subprocess.run([sys.executable, "-c", code], check=True, stdin=subprocess.DEVNULL)


# ---- knihovna -------------------------------------------------------------------------------------------------------

@pytest.fixture
def no_shared(monkeypatch):
    monkeypatch.setattr(tlib, "shared_dir", lambda: None)


def test_builtin_presets(no_shared):
    tops = tlib.load_topologies(ROLES)
    assert {"rd", "nn", "nn_hr_meter", "vn"} <= set(tops)
    for t in tops.values():
        assert t.source == "vestavěná" and check_topology(t) == []
    for f in tlib.BUILTIN_DIR.glob("*.json"):
        assert validate_topology(json.loads(f.read_text(encoding="utf-8")), ROLES) == [], f.name
        assert json.loads(f.read_text(encoding="utf-8"))["id"] == f.stem

    rd, nn, hrm, vn = tops["rd"], tops["nn"], tops["nn_hr_meter"], tops["vn"]
    assert chain_text(rd) == "stringy → RFVE → T → RD → RE → HDS → DS"
    assert chain_text(nn) == "stringy → RFVE.DC → T → RFVE.AC → HR → RE → HDS → DS"
    assert chain_text(hrm) == "stringy → RFVE.DC → T → RFVE.AC → HR → HDS → DS"
    assert chain_text(vn) == "stringy → RFVE.DC → T → RFVE.AC → HR → TR → RVN → DS (+ RE)"
    # druhy objektu a úroveň
    assert rd.buildings == ("house",) and rd.level == "nn"
    assert set(nn.buildings) == {"company", "apartment"} and vn.level == "vn"
    # rozhodnutí 3: RFVE.DC výchozí společný
    assert all(not t.node("rfve_dc").per_inverter for t in (nn, hrm, vn))
    # rozhodnutí 1: síťová ochrana nad 30 kWp v RFVE.AC, u RD v RFVE (zatím jen volba)
    assert rd.node("rfve").options["grid_protection"] == "auto"
    assert all(t.node("rfve_ac").options["grid_protection"] == "auto" for t in (nn, hrm, vn))
    # rozhodnutí 8 + 10: přepínač sítí a EPS jen u RD
    assert rd.node("rfve").options["changeover_switch"] == "1"
    assert all("changeover_switch" not in t.node("rfve_ac").options for t in (nn, hrm, vn))
    # rozhodnutí 4–6: stávající RD/HR, RE; měření v HR jen v nn_hr_meter
    assert rd.node("rd").existing and nn.node("hr").existing and nn.node("re").existing
    assert hrm.node("re") is None and hrm.node("hr").options["metering"] == "direct"
    assert "metering" not in nn.node("hr").options
    assert rd.node("re").options == {"metering": "direct", "boundary": "hds"}
    # HDS, DS a TR jen bloky; RE u vn odbočka
    assert not rd.node("hds").sheet and not vn.node("tr").sheet and not vn.node("grid").sheet
    assert vn.node("re").branch and vn.node("hds") is None
    # makra v F1 prázdná (výstup generátoru beze změny)
    assert all(not n.macros for t in tops.values() for n in t.nodes)


def test_list_and_find(no_shared):
    ids = [t.id for t in tlib.list_topologies()]
    assert ids[:4] == ["rd", "nn", "nn_hr_meter", "vn"]
    assert tlib.find_topology("vn").level == "vn" and tlib.find_topology("neni") is None


def _write(d, fname, **kw):
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{fname}.json"
    p.write_text(json.dumps(_data(**kw), ensure_ascii=False), encoding="utf-8")
    return p


def test_priority_user_over_shared_over_builtin(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    monkeypatch.setattr(tlib, "shared_dir", lambda: shared / "topologies")
    user = tlib.user_dir()
    assert [s for _, s in tlib.topology_dirs()] == ["vestavěná", "sdílená", "vlastní"]
    _write(shared / "topologies", "a", id="nn", name="NN sdílená")
    _write(shared / "topologies", "b", id="rd", name="RD sdílená", buildings=["house"])
    _write(shared / "topologies", "c", id="firemni", name="Firemní")
    _write(user, "z", id="rd", name="RD vlastní", buildings=["house"])
    tops = tlib.load_topologies()
    assert tops["nn"].name == "NN sdílená" and tops["nn"].source == "sdílená"
    assert tops["rd"].name == "RD vlastní" and tops["rd"].source == "vlastní"
    assert tops["firemni"].source == "sdílená" and tops["vn"].source == "vestavěná"
    assert tops["rd"].path == user / "z.json"
    listed = tlib.list_topologies()
    assert listed[0].id == "nn_hr_meter" and {t.id for t in listed} == set(tops)


def test_shared_dir_from_settings(tmp_path):
    from envocad import settings
    st = settings.load_settings()
    st["shared_library_dir"] = str(tmp_path)
    settings.save_settings(st)
    assert tlib.shared_dir() == tmp_path / "topologies"
    _write(tmp_path / "topologies", "x", id="x", name="X")
    assert tlib.load_topologies()["x"].source == "sdílená"


def test_invalid_files_skipped(tmp_path, no_shared, caplog):
    user = tlib.user_dir()
    user.mkdir(parents=True, exist_ok=True)
    (user / "broken.json").write_text("{nejde", encoding="utf-8")
    _write(user, "bad", id="bad", nodes=[])
    _write(user, "future", id="future", version=TOPOLOGY_VERSION + 1)
    _write(user, "nn", id="nn", nodes=[{"role": "trafo"}])    # neznámá role přepis vestavěné nepřebije
    with caplog.at_level(logging.WARNING, logger="envocad.library"):
        tops = tlib.load_topologies(ROLES)
    assert "bad" not in tops and "future" not in tops and tops["nn"].source == "vestavěná"
    text = caplog.text
    assert "broken.json nelze načíst" in text and "bad.json je neplatná" in text
    assert "má verzi 2, program umí nejvýše 1" in text and "neznámá role „trafo“" in text


def test_store_skips_topologies(tmp_path, caplog):
    """Složka topologies/ (vestavěná i ve sdílené knihovně) se nenačte jako značky."""
    from envocad import settings
    from envocad.library.store import NON_SYMBOL_DIRS, LibraryStore
    assert "topologies" in NON_SYMBOL_DIRS and "macros" in NON_SYMBOL_DIRS
    shared = tmp_path / "shared"
    _write(shared / "topologies", "rd", id="sdilena_topologie", name="X")
    # soubor topologie, který by jinak prošel jako značka (má id a name)
    st = settings.load_settings()
    st["shared_library_dir"] = str(shared)
    settings.save_settings(st)
    with caplog.at_level(logging.WARNING, logger="envocad.library"):
        lib = LibraryStore()
    ids = {row[0] for row in lib.list_symbols()}
    names = {row[1] for row in lib.list_symbols()}
    assert not {"rd", "nn", "vn", "nn_hr_meter", "sdilena_topologie"} & ids
    assert not {"Rodinný dům", "Připojení na vn", "X"} & names
    assert "topolog" not in caplog.text          # ani pokus o načtení jako značky (varování „značka … se nenačetla“)


# ---- výběr topologie (rozhodnutí kap. 8) ------------------------------------------------------------------------------

@pytest.fixture
def tops(no_shared):
    return tlib.load_topologies(ROLES)


def _spec(building="company", level=None, topology=None, kwp_strings=(20,)):
    s = {"building": building, "module": {"p_wp": 500}, "inverters": [{"strings": list(kwp_strings)}]}
    if level is not None:
        s["connection"] = {"level": level}
    if topology is not None:
        s["topology"] = topology
    return s


@pytest.mark.parametrize(("building", "level", "strings", "expected"), [
    ("house", None, (20,), "rd"),                 # RD 10 kWp
    ("house", "nn", (40, 40), "rd"),              # RD nad 30 kWp – stále rd (rozhodnutí 1)
    ("rodinný dům", "", (20,), "rd"),
    ("RD", "NN", (20,), "rd"),
    ("apartment", None, (20,), "nn"),             # bytový dům → nn (rozhodnutí 2)
    ("apartment", "nn", (80, 80), "nn"),
    ("bytový dům", None, (20,), "nn"),
    ("company", None, (20,), "nn"),               # firma pod 30 kWp výchozí nn
    ("company", "nn", (80, 80), "nn"),            # firma nad 30 kWp na nn
    ("", None, (20,), "nn"),                      # prázdné = firma
    ("company", "vn", (20,), "vn"),               # firma pod 30 kWp volbou vn
    ("firma", "VN", (80, 80), "vn"),
    ("apartment", "vn", (80, 80), "vn"),          # bytový dům s trafostanicí (jako dnes generate.py)
])
def test_select_auto(tops, building, level, strings, expected):
    assert select_topology(_spec(building, level, kwp_strings=strings), tops).id == expected


@pytest.mark.parametrize(("building", "level", "topology", "expected"), [
    ("company", None, "nn_hr_meter", "nn_hr_meter"),   # měření v HR jen volbou
    ("company", "nn", "nn_hr_meter", "nn_hr_meter"),
    ("apartment", None, "nn_hr_meter", "nn_hr_meter"),
    ("company", None, "vn", "vn"),                     # level nezadaný → podle presetu
    ("company", "vn", "vn", "vn"),
    ("company", "nn", " nn ", "nn"),
    ("house", None, "rd", "rd"),
    ("house", "", "", "rd"),                           # prázdné = automaticky
])
def test_select_explicit(tops, building, level, topology, expected):
    assert select_topology(_spec(building, level, topology), tops).id == expected


def test_select_hr_metering_not_automatic(tops):
    s = _spec("company", "nn")
    s["chain"] = {"hr": {"metering": "direct"}}
    assert select_topology(s, tops).id == "nn"       # rozhodnutí 6: žádná automatika


@pytest.mark.parametrize(("building", "level", "topology", "fragment"), [
    ("house", "vn", None, "Rodinný dům: rozvaděč FVE se připojuje do HDS"),
    ("house", None, "vn", "ne pro rodinný dům"),
    ("house", None, "nn", "ne pro rodinný dům"),
    ("company", None, "rd", "je pro druh objektu rodinný dům, ne pro firma"),
    ("company", "nn", "vn", "je pro připojení na vn, ale specifikace má připojení na nn"),
    ("company", "vn", "nn_hr_meter", "je pro připojení na nn, ale specifikace má připojení na vn"),
    ("company", None, "neni", "Neznámá topologie „neni“ – k dispozici: nn, nn_hr_meter, rd, vn"),
    ("hrad", None, None, "Neznámý druh objektu „hrad“"),
])
def test_select_errors(tops, building, level, topology, fragment):
    with pytest.raises(ValueError, match=fragment):
        select_topology(_spec(building, level, topology), tops)


def test_select_checks_roles_and_missing_preset():
    bad = parse_topology(_data(id="x", nodes=[{"role": "trafo"}, {"role": "grid"}]))
    with pytest.raises(ValueError, match="neznámá role „trafo“.*nemá článek „inverter“"):
        select_topology(_spec(topology="x"), {"x": bad})
    with pytest.raises(ValueError, match="Chybí topologie „nn“"):
        select_topology(_spec(), {})


def test_select_loads_library_by_default(no_shared):
    assert select_topology({"building": "house", "inverters": [{"strings": [10]}]}).id == "rd"


def test_installed_kwp_and_building():
    assert installed_kwp({"module": {"p_wp": 450}, "inverters": [{"strings": [20, 18]}, {"strings": ["10"]}]}) \
        == pytest.approx(21.6)
    assert installed_kwp({"module": {"p_wp": "500,5"}, "inverters": [{"strings": [2]}]}) == pytest.approx(1.001)
    assert installed_kwp({}) == 0 and installed_kwp({"module": {"p_wp": "x"}, "inverters": [{}]}) == 0
    assert building_kind("BD") == "apartment" and gspec.connection_level({"connection": {"level": " VN "}}) == "vn"
    assert gspec.connection_level({}) == "nn"


def test_topology_dataclass_equality():
    a = Topology("a", "A", (ChainNode("inverter"),))
    b = Topology("a", "A", (ChainNode("inverter"),), path=tlib.Path("x.json"))
    assert a == b   # cesta se neporovnává


# ---- review F1: role při výběru, rodinný dům, vn, druhy objektu, cache -----------------------------------------------

def test_select_skips_shared_file_with_unknown_role(tmp_path, monkeypatch, caplog):
    """Sdílená složka přepisuje „nn“ topologií s neznámou rolí: `select_topology` načítá s rolemi generátoru, soubor
    se vynechá (log) a platí vestavěný preset – žádná chyba „neznámá role“ při generování."""
    shared = tmp_path / "shared" / "topologies"
    monkeypatch.setattr(tlib, "shared_dir", lambda: shared)
    _write(shared, "nn", id="nn", name="NN sdílená", nodes=[{"role": "rfve_ac"}, {"role": "inverter"},
                                                            {"role": "trafo_x"}])
    assert tlib.load_topologies()["nn"].source == "sdílená"          # bez rolí se načte
    with caplog.at_level(logging.WARNING, logger="envocad.library"):
        topo = select_topology(_spec("company"))
    assert topo.id == "nn" and topo.source == "vestavěná"
    assert "neznámá role „trafo_x“" in caplog.text
    from envocad.generate import build_project
    p = build_project({"inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200,
                                      "u_mppt_max": 1000, "i_mppt_max": 30, "strings": [20]}]})
    assert p.meta["topology"] == "nn"


def _house(nodes, **kw):
    return parse_topology(_data(id="rd_x", buildings=["house"], nodes=nodes, **kw))


def test_house_topology_requires_rfve():
    """Rodinný dům s `rfve_ac` místo `rfve` by rozbil projekt (DC vodiče do RFVE na neexistující přívody) – chyba."""
    bad = _house([{"role": "inverter"}, {"role": "rfve_ac"}, {"role": "grid"}])
    assert any("pro rodinný dům nemá článek „rfve“" in e for e in check_topology(bad))
    assert any("nemá článek „rfve“" in e for e in check_topology(parse_topology(_data(buildings=[])), "house"))
    assert check_topology(parse_topology(_data(buildings=[])), "company") == []
    with pytest.raises(ValueError, match="pro rodinný dům nemá článek „rfve“"):
        select_topology(_spec("house", topology="rd_x"), {"rd_x": bad})
    ok = _house([{"role": "rfve"}, {"role": "inverter"}, {"role": "grid"}])
    assert check_topology(ok) == [] and select_topology(_spec("house", topology="rd_x"), {"rd_x": ok}) is ok
    both = _house([{"role": "rfve"}, {"role": "inverter"}, {"role": "rfve_ac"}, {"role": "grid"}])
    assert any("„rfve“ i „rfve_ac“" in e for e in check_topology(both))


def test_house_custom_topology_rfve_ac_build_raises(tmp_path, monkeypatch):
    """Generátor: vlastní topologie RD s `rfve_ac` → ValueError místo projektu s chybou `bad_port`."""
    user = tlib.user_dir()
    _write(user, "rd", id="rd", name="RD vlastní", buildings=["house"],
           nodes=[{"role": "inverter"}, {"role": "rfve_ac"}, {"role": "grid"}])
    from envocad.generate import build_project
    with pytest.raises(ValueError, match="nemá článek „rfve“"):
        build_project({"building": "house", "inverters": [{"ref": "T1", "strings": [12]}]})


def test_vn_topology_requires_mv_role():
    """Úroveň vn bez HR / TR / RVN / RE / DS by tiše vytvořila přípojku nn – chyba."""
    bad = parse_topology(_data(id="v", level="vn", nodes=[{"role": "rfve_dc"}, {"role": "inverter"},
                                                          {"role": "rfve_ac"}]))
    errs = check_topology(bad)
    assert len(errs) == 1 and "pro připojení na vn, ale nemá žádný článek přípojky VN" in errs[0]
    with pytest.raises(ValueError, match="nemá žádný článek přípojky VN"):
        select_topology(_spec("company", "vn", "v"), {"v": bad})
    only_grid = parse_topology(_data(id="v", level="vn", nodes=[{"role": "inverter"}, {"role": "grid"}]))
    assert check_topology(only_grid) == []


def test_check_topology_unknown_building():
    t = parse_topology(_data(buildings=["company", "rodinný dům"]))
    errs = check_topology(t)
    assert errs == ["Topologie „test“: neznámý druh objektu „rodinný dům“ – známé: company, house, apartment."]
    with pytest.raises(ValueError, match="neznámý druh objektu „rodinný dům“"):
        select_topology(_spec("apartment", topology="test"), {"test": t})


def test_load_topologies_cached_by_mtime(tmp_path, monkeypatch):
    """Cache podle stavu složek: opakované načtení soubory znovu nečte, změna / nový / smazaný soubor ano."""
    import os
    shared = tmp_path / "shared" / "topologies"
    monkeypatch.setattr(tlib, "shared_dir", lambda: shared)
    p = _write(shared, "f", id="firemni", name="Firemní")
    calls = []
    real = tlib.load_topology
    monkeypatch.setattr(tlib, "load_topology", lambda *a, **k: calls.append(a[0]) or real(*a, **k))
    first = tlib.load_topologies(ROLES)
    n = len(calls)
    assert n >= 5 and first["firemni"].name == "Firemní"
    second = tlib.load_topologies(ROLES)
    assert len(calls) == n and second == first and second is not first     # z cache, nový slovník
    second.pop("nn")
    assert "nn" in tlib.load_topologies(ROLES)                              # úprava výsledku cache nepoškodí
    assert len(calls) == n
    tlib.load_topologies()                                                  # jiné role = jiný klíč
    assert len(calls) == 2 * n
    p.write_text(json.dumps(_data(id="firemni", name="Firemní 2")), encoding="utf-8")
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    assert tlib.load_topologies(ROLES)["firemni"].name == "Firemní 2"
    p.unlink()
    assert "firemni" not in tlib.load_topologies(ROLES)
    # build_project sdílenou složku znovu nečte
    from envocad.generate import build_project
    spec = {"inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000,
                           "i_mppt_max": 30, "strings": [20]}]}
    build_project(spec)
    k = len(calls)
    build_project(spec)
    assert len(calls) == k
