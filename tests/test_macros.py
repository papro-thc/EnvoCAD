"""Makra se zástupnými proměnnými, sadami hodnot, podmínkami a opakováním (bez Qt) – docs/design/makra_promenne.md."""
import json
import logging

import pytest
from generate_snapshot import CASES, SNAPSHOT, canon

from envocad.generate import _macro_ref, build_project
from envocad.library import macros
from envocad.library.macros import (
    MAX_REPEAT,
    Macro,
    ValueSet,
    expand,
    find_macro,
    instantiate,
    list_macros,
    load_macro,
    parse_macro,
    placeholders,
    resolve_values,
    save_macro,
    subst,
    validate_macro,
)
from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, Sheet


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _prefix(lib):
    return lambda sid: lib.get_symbol(sid).iec_ref


def _sb_sheet(p: Project) -> Sheet:
    s = Sheet(name="R", kind="switchboard", loc="R1")
    p.sheets.append(s)
    return s


# ---- subst, placeholders ----------------------------------------------------------------------------------------
def test_subst_only_simple_names():
    v = {"x": "1", "n": 3, "a": "A"}
    assert subst("F{x}.{n}", v) == "F1.3"
    assert subst("{unknown}-{x}", v) == "{unknown}-1"
    for keep in ("{}", "{0}", "{a.b}", "{a[0]}", "{x:>3}", "{x!r}", "{ x }"):
        assert subst(keep, v) == keep
    assert subst("{x}{x}", v) == "11" and subst(15, v) == "15" and subst("bez", v) == "bez"


def test_placeholders_collects_attrs_ports_component():
    frag = {"elements": [{"id": "a", "symbol_id": "s", "x": 0, "y": 0, "attrs": {"ref": "F{i}.{j}", "in_": "{fuse_in}"},
                          "component_id": "{inv}"}],
            "wires": [{"id": "w", "a": {"element_id": "a", "port": "T{k}"}, "b": {"element_id": "a", "port": "1"},
                       "attrs": {"desc": "{string}"}}]}
    assert placeholders(frag) == {"i", "j", "fuse_in", "inv", "k", "string"}


# ---- načtení, verze, implicitní proměnné ---------------------------------------------------------------------------
def test_v1_macro_gets_implicit_variables(tmp_path):
    p = tmp_path / "v1.json"
    p.write_text(json.dumps({"name": "Staré", "description": "", "fragment": {"elements": [
        {"id": "a", "symbol_id": "fve.breaker_mcb", "x": 0, "y": 0, "attrs": {"ref": "F{k}", "in_": "{proud}"}}],
        "wires": []}}), encoding="utf-8")
    m = load_macro(p)
    assert m.version == 1 and m.role == "" and m.repeat is None and m.has_parameters
    assert [(v.name, v.type, v.implicit, v.auto) for v in m.variables] == [("k", "text", True, True), ("proud", "text", True, False)]


def test_higher_version_is_skipped_with_log(tmp_path, monkeypatch, caplog):
    d = tmp_path / "m"
    d.mkdir()
    (d / "budouci.json").write_text(json.dumps({"version": 99, "name": "Budoucí", "fragment": {"elements": [], "wires": []}}),
                                    encoding="utf-8")
    (d / "rozbite.json").write_text("{", encoding="utf-8")
    assert load_macro(d / "budouci.json") is None
    monkeypatch.setattr(macros, "user_dir", lambda: d)
    monkeypatch.setattr(macros, "shared_dir", lambda: None)
    with caplog.at_level(logging.WARNING, logger="envocad.library"):
        names = [m.name for m in list_macros()]
    assert "Budoucí" not in names and "DC string v rozvaděči" in names
    assert any("verzi 99" in r.getMessage() for r in caplog.records)


def test_parse_macro_rejects_non_macro():
    with pytest.raises(ValueError):
        parse_macro({"name": "x"}, None, "vlastní")


def test_save_macro_writes_v2_with_implicit_variables(tmp_path, monkeypatch):
    monkeypatch.setattr(macros, "user_dir", lambda: tmp_path / "m")
    monkeypatch.setattr(macros, "shared_dir", lambda: None)
    frag = {"elements": [{"id": "a", "symbol_id": "fve.breaker_mcb", "x": 0, "y": 0, "attrs": {"ref": "F1", "in_": "{proud}"}}],
            "wires": []}
    path = save_macro("Můj jistič", "popis", frag)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 2 and data["variables"] == [{"name": "proud"}] and not validate_macro(data)
    m = load_macro(path)
    assert m.version == 2 and [v.name for v in m.variables] == ["proud"] and not m.variables[0].implicit


def test_builtin_macros_are_valid_v2():
    found = {m.name: m for m in list_macros() if m.source == "vestavěné"}
    assert len(found) == 6
    for m in found.values():
        data = json.loads(m.path.read_text(encoding="utf-8"))
        assert data["version"] == 2 and validate_macro(data) == [], (m.name, validate_macro(data))
    roles = {m.role: m.name for m in found.values() if m.role}
    assert roles == {"dc_tech": "DC string v rozvaděči", "dc_route": "DC string po trase",
                     "ac_feed": "AC přívod střídače", "ac_core": "AC jádro rozvaděče"}
    dc = found["DC string v rozvaděči"]
    assert dc.repeat.count == "n" and dc.repeat.pitch == 40 and dc.value_sets
    assert all(v.label for v in dc.variables)
    assert not found["String → střídač"].has_parameters


def test_validate_macro_reports_errors():
    data = {"version": 2, "name": "X", "variables": [
        {"name": "1bad"}, {"name": "a", "type": "choice"}, {"name": "c", "type": "component"},
        {"name": "b", "from": "a.p_ac_kw"}, {"name": "dup"}, {"name": "dup"}],
        "value_sets": [{"name": "S", "values": {"neni": "1"}}],
        "repeat": {"count": "pocet", "pitch": -1},
        "fragment": {"elements": [{"id": "e", "symbol_id": "s", "x": 0, "y": 0,
                                   "attrs": {"ref": "{zzz}", "when": "a b"}},
                                  {"id": "f", "symbol_id": "s", "x": 0, "y": 0, "attrs": {"when": "!nikde"}}],
                     "wires": [{"id": "w", "a": {"element_id": "e", "port": "1"}, "b": {"element_id": "nic", "port": "1"}}]}}
    text = "\n".join(validate_macro(data))
    for frag in ("1bad", "choices", "category", "from", "dvakrát", "neni", "pocet", "pitch", "Podmínka", "neexistující",
                 "{zzz}", "„nikde“"):
        assert frag in text, frag
    assert validate_macro({"version": 99, "name": "X", "fragment": {"elements": [], "wires": []}})
    assert validate_macro([]) == ["Makro není objekt JSON."]


# ---- resolve_values ------------------------------------------------------------------------------------------------
def _m(variables, value_sets=(), **kw) -> Macro:
    data = {"version": 2, "name": "Test", "variables": variables, "value_sets": list(value_sets),
            "fragment": kw.pop("fragment", {"elements": [], "wires": []}), **kw}
    return parse_macro(data, None, "vlastní")


class _Comp:
    def __init__(self, cid, category, **params):
        self.id, self.category, self.part_number, self.manufacturer = cid, category, params.pop("pn", cid), "Výrobce"
        self.params = params
        self.applied = []

    def apply_to(self, e):
        e.attrs.update({"mppt": self.params["mppt"], "strings_per_mppt": self.params["strings_per_mppt"],
                        "type": self.part_number})
        e.component_id = self.id
        self.applied.append(e)
        return {}


def test_resolve_values_order_default_base_component_set_given_context():
    comps = {"inv1": _Comp("inv1", "inverter", p_ac_kw="25", mppt="3", strings_per_mppt="2")}
    m = _m([{"name": "inv", "type": "component", "category": "inverter", "default": "inv1"},
            {"name": "p", "type": "number", "from": "inv.p_ac_kw", "default": "10"},
            {"name": "a", "default": "d"}, {"name": "b", "default": "d"}, {"name": "c", "default": "d"},
            {"name": "e", "default": "d"}, {"name": "label", "default": "{a}-{i}"}],
           [{"name": "S", "values": {"b": "set", "c": "set", "e": "set"}}])
    vals, errs = resolve_values(m, given={"c": "given", "e": "given"}, value_set="S", components=comps.get,
                                context={"e": "ctx", "i": 7}, base={"a": "base", "p": "99"})
    assert not errs
    assert (vals["a"], vals["b"], vals["c"], vals["e"]) == ("base", "set", "given", "ctx")
    assert vals["p"] == "25"            # artikl přebije základ, ale ne sadu / zadané
    assert vals["label"] == "base-7"    # výchozí hodnota skládá text (jeden průchod)
    vals, _ = resolve_values(m, given={"p": "30"}, components=comps.get)
    assert vals["p"] == "30"


def test_resolve_values_errors_and_normalization():
    m = _m([{"name": "fuse_in", "label": "In pojistky", "type": "number", "required": True, "min": 1, "max": 63},
            {"name": "spd", "type": "choice", "choices": ["", "T2", "T1+T2"]},
            {"name": "inv", "type": "component", "category": "inverter"},
            {"name": "j", "type": "number", "default": "{k}"}])
    vals, errs = resolve_values(m, given={"fuse_in": "15,0", "spd": "t1 + t2"})
    assert not errs and vals["fuse_in"] == "15" and vals["spd"] == "T1+T2" and vals["j"] == "{k}"
    assert resolve_values(m, given={"fuse_in": "2,5"})[0]["fuse_in"] == "2.5"
    _, errs = resolve_values(m)
    assert errs == ["Makro „Test“: In pojistky: hodnota je povinná."]
    for given, word in (({"fuse_in": "15A"}, "není číslo"), ({"fuse_in": "0"}, "menší"), ({"fuse_in": "100"}, "větší"),
                        ({"fuse_in": "10", "spd": "T3"}, "nabídky")):
        _, errs = resolve_values(m, given=given)
        assert len(errs) == 1 and word in errs[0], (given, errs)
    _, errs = resolve_values(m, given={"fuse_in": "10"}, value_set="Neexistuje")
    assert "neznámá sada" in errs[0]
    _, errs = resolve_values(m, given={"fuse_in": "10", "inv": "x"}, components=lambda cid: None)
    assert "nenalezen" in errs[0]
    _, errs = resolve_values(m, given={"fuse_in": "10", "inv": "x"}, components=lambda cid: _Comp(cid, "mcb"))
    assert "kategorie" in errs[0]
    vs = ValueSet("Vlastní", {"fuse_in": "20"})
    assert resolve_values(m, value_set=vs)[0]["fuse_in"] == "20"


# ---- expand: when, repeat, shared, component -------------------------------------------------------------------------
def test_expand_does_not_touch_sheet_instantiate_does(lib):
    m = find_macro("DC string v rozvaděči")
    p = Project()
    s = _sb_sheet(p)
    vals, errs = resolve_values(m, given={"fuse_in": "20"}, context={"k": 1, "nk": 2, "n": 1, "i": 1, "j": 1, "string": "G1"})
    assert not errs
    els, wires = expand(p, s, m, vals, ref_prefix_of=_prefix(lib), repeat=False)
    assert not s.elements and not s.wires and len(els) == 5 and len(wires) == 4
    els, wires = instantiate(p, s, m.fragment, vals, ref_prefix_of=_prefix(lib))
    assert len(s.elements) == 5 and len(s.wires) == 4
    fu = next(e for e in els if e.symbol_id == "fve.fuse_disconnect")
    assert fu.ref == "FU1.1" and fu.attrs["in_"] == "20" and "when" not in next(e for e in els if e.symbol_id == "fve.spd").attrs


@pytest.mark.parametrize("spd, n_spd", [("T2", 1), ("", 0)])
def test_when_drops_element_and_its_wires(lib, spd, n_spd):
    m = find_macro("DC string v rozvaděči")
    p = Project()
    s = _sb_sheet(p)
    vals, errs = resolve_values(m, given={"spd": spd, "n": 1})
    assert not errs
    els, wires = expand(p, s, m, vals, ref_prefix_of=_prefix(lib))
    assert sum(e.symbol_id == "fve.spd" for e in els) == n_spd
    assert sum(e.ref == "XPE" for e in els) == n_spd     # vývod k HOP jen s SPD
    ids = {e.id for e in els}
    assert all(w.a.element_id in ids and w.b.element_id in ids for w in wires)
    assert len(wires) == (4 if n_spd else 2)


def test_condition_forms():
    from envocad.library.macros import condition
    v = {"spd": "T2", "off": "Ne", "z": "0"}
    assert condition("spd", v) and not condition("!spd", v) and not condition("off", v) and not condition("z", v)
    assert not condition("missing", v) and condition("!missing", v)
    assert condition("spd=T2", v) and not condition("spd=T1", v) and condition("spd!=T1", v) and not condition("spd!=T2", v)


def test_repeat_shared_grid_and_numbering(lib):
    m = find_macro("DC string v rozvaděči")
    p = Project()
    s = _sb_sheet(p)
    vals, errs = resolve_values(m, given={"n": 2, "fuse_in": 20})
    assert not errs
    els, wires = expand(p, s, m, vals, dx=1.0, ref_prefix_of=_prefix(lib))
    assert not s.elements
    refs = [e.ref for e in els]
    assert refs.count("XPE") == 1                                    # shared sloučený
    assert {"X1", "X2", "X3", "X4", "FU1.1", "FU1.2", "SPD-DC1.1", "SPD-DC1.2"} <= set(refs)
    descs = sorted(e.attrs["desc"] for e in els if e.symbol_id == "sb.feed_in")
    assert descs == ["od G1", "od G2"]
    fus = sorted((e for e in els if e.symbol_id == "fve.fuse_disconnect"), key=lambda e: e.x)
    assert [e.x for e in fus] == [61.0, 101.0]                     # posun dx + (k−1)·40
    assert not any("{" in v for e in els for v in e.attrs.values())
    assert not any("{" in w.a.port + w.b.port for w in wires)
    xpe = next(e for e in els if e.ref == "XPE")
    assert sum(w.b.element_id == xpe.id for w in wires) == 2        # PE obou svodičů na jeden XPE
    # shared prvek už na listu → sloučí se s ním (není nový)
    s.elements.append(Element("sb.feed_out", 0, 0, attrs={"ref": "XPE", "shared": "1"}))
    els2, _ = expand(p, s, m, vals, ref_prefix_of=_prefix(lib))
    assert not [e for e in els2 if e.ref == "XPE"]


def test_repeat_pitch_snaps_to_grid(lib):
    frag = {"elements": [{"id": "a", "symbol_id": "fve.breaker_mcb", "x": 0, "y": 0, "attrs": {"ref": "F{k}"}}], "wires": []}
    m = _m([{"name": "n", "type": "number", "default": "3"}], fragment=frag, repeat={"count": "n", "pitch": 11})
    els, _ = expand(Project(), Sheet(), m, resolve_values(m)[0])
    assert [e.x for e in els] == [0, 10, 22.5] and [e.ref for e in els] == ["F1", "F2", "F3"]


def test_repeat_limit(lib):
    m = find_macro("DC string v rozvaděči")
    vals, _ = resolve_values(m, given={"n": MAX_REPEAT + 1})
    with pytest.raises(ValueError, match="mimo rozsah"):
        expand(Project(), Sheet(), m, vals)
    vals["n"] = "abc"
    with pytest.raises(ValueError, match="celé číslo"):
        expand(Project(), Sheet(), m, vals)


def test_component_from_and_apply_to_inverter_dc_inputs(lib):
    """Proměnná typu component + `from` čte artikl; prvek s component_id „{inv}“ dostane jeho parametry → DC vstupy."""
    from envocad.model.project import inverter_dc_inputs
    frag = {"elements": [{"id": "t", "symbol_id": "fve.inverter", "x": 0, "y": 0, "attrs": {"ref": "T1", "p_ac": "{p_ac}"},
                          "component_id": "{inv}"}], "wires": []}
    m = _m([{"name": "inv", "type": "component", "category": "inverter"},
            {"name": "p_ac", "type": "number", "from": "inv.p_ac_kw"}], fragment=frag)
    vals, errs = resolve_values(m, given={"inv": "sma-stp-25-50"}, components=lib.component)
    assert not errs and vals["p_ac"] == "25"
    p = Project()
    els, _ = expand(p, p.sheets[0], m, vals, components=lib.component)
    t = els[0]
    assert t.component_id == "sma-stp-25-50" and t.attrs["mppt"] == "3" and t.attrs["type"] == "STP 25-50"
    assert inverter_dc_inputs(p, t) == 6     # 3 MPPT × 2 stringy (výchozí strings_per_mppt symbolu)
    # bez hodnoty artiklu zůstane prvek bez artiklu
    els, _ = expand(Project(), Sheet(), m, {"p_ac": "10"}, components=lib.component)
    assert els[0].component_id is None


# ---- generátor ------------------------------------------------------------------------------------------------------
def test_generator_regression_snapshot():
    """Generátor po refaktoru maker dává stejný výstup jako před ním (snímek tests/data/generate_snapshot.json)."""
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    for name, spec in CASES.items():
        got = canon(build_project(spec))
        if name == "with_component":
            # záměrný rozdíl: artikl střídače doplní atributy, které specifikace nezadala (typ, výrobce, p_dc_max, Un)
            inv = next(e for e in got["sheets"][0]["elements"] if e["symbol_id"] == "fve.inverter")
            assert {k: inv["attrs"][k] for k in ("type", "manufacturer", "p_dc_max", "un")} == \
                {"type": "STP 25-50", "manufacturer": "SMA", "p_dc_max": "37.5", "un": "400"}
            assert inv["attrs"]["p_ac"] == "25" and inv["attrs"]["mppt"] == "3"   # zadané ve specifikaci zůstávají
            old = next(e for e in snap[name]["sheets"][0]["elements"] if e["symbol_id"] == "fve.inverter")
            old["attrs"].update({"type": "STP 25-50", "manufacturer": "SMA", "p_dc_max": "37.5", "un": "400"})
        assert got == snap[name], name


def test_generator_component_fills_mppt_when_not_given():
    spec = {"inverters": [{"ref": "T1", "p_ac": 20, "strings": [20, 20, 18], "component_id": "sma-stp-25-50"}]}
    p = build_project(spec)
    t = next(e for e in p.sheets[0].elements if e.symbol_id == "fve.inverter")
    assert t.attrs["mppt"] == "3" and t.attrs["p_ac"] == "20" and t.component_id == "sma-stp-25-50"
    # neznámý artikl generátor nezastaví
    spec["inverters"][0]["component_id"] = "neexistuje"
    assert build_project(spec)


def test_macro_ref_forms():
    assert _macro_ref("DC string po trase") == ("DC string po trase", None, {})
    assert _macro_ref({"name": "X", "value_set": "S", "values": {"fuse_in": 20}}) == ("X", "S", {"fuse_in": "20"})
    assert _macro_ref(None) == ("", None, {})
    assert _macro_ref({}) == ("", None, {})


def _tech_sheet(p):
    return next(s for s in p.sheets if s.is_switchboard and any(e.symbol_id == "fve.fuse_disconnect" for e in s.elements))


def test_generator_object_macro_entry_value_set_and_values():
    base = {"inverters": [{"ref": "T1", "strings": [20, 20]}], "dc": {"route_boxes": 0, "fuse_in": 15}}
    p = build_project({**base, "macros": {"dc_tech": {"name": "DC string v rozvaděči",
                                                       "value_set": "Pojistka 20 A gPV, SPD T1+T2"}}})
    s = _tech_sheet(p)
    assert {e.attrs["in_"] for e in s.elements if e.symbol_id == "fve.fuse_disconnect"} == {"20"}   # sada přebije spec.dc
    assert {e.attrs["spd_type"] for e in s.elements if e.symbol_id == "fve.spd"} == {"T1+T2 DC"}
    p = build_project({**base, "macros": {"dc_tech": {"name": "DC string v rozvaděči", "value_set": "Pojistka 20 A gPV, SPD T1+T2",
                                                       "values": {"fuse_in": "25", "spd": ""}}}})
    s = _tech_sheet(p)
    assert {e.attrs["in_"] for e in s.elements if e.symbol_id == "fve.fuse_disconnect"} == {"25"}   # zadané přebije sadu
    assert not [e for e in s.elements if e.symbol_id == "fve.spd" or e.ref == "XPE"]                # when: spd


def test_generator_macro_errors_name_the_macro():
    base = {"inverters": [{"ref": "T1", "strings": [20]}], "dc": {"route_boxes": 0}}
    with pytest.raises(ValueError, match="DC string v rozvaděči.*není číslo"):
        build_project({**base, "macros": {"dc_tech": {"name": "DC string v rozvaděči", "values": {"fuse_in": "x"}}}})
    with pytest.raises(ValueError, match="AC jádro rozvaděče.*neznámá sada"):
        build_project({**base, "macros": {"ac_core": {"name": "AC jádro rozvaděče", "value_set": "Nic"}}})
