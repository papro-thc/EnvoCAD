"""Charakterizační testy `envocad/library/macros.py` – validační a chybové větve (bez Qt).

Popisují SOUČASNÉ chování (hlášky, návratové hodnoty); neříkají, co je oborově správně.
Doplňují `tests/test_macros.py`."""
import copy
import json
import logging
import types

import pytest

from envocad.library import macros
from envocad.library.macros import (
    Macro,
    MacroVar,
    ValueSet,
    condition,
    delete_macro,
    fragment_bounds,
    list_macros,
    load_macro,
    macro_dirs,
    macro_pitch,
    parse_macro,
    repeat_count,
    repeat_start,
    resolve_values,
    shared_dir,
    suggest_numbering,
    validate_macro,
)
from envocad.model.project import Project, Sheet


def _el(eid="a", ref="F1", **attrs):
    return {"id": eid, "symbol_id": "fve.breaker_mcb", "x": 0, "y": 0, "attrs": {"ref": ref, **attrs}}


def _frag(*els, wires=()):
    return {"elements": list(els), "wires": list(wires)}


def _valid(**over):
    """Platné makro v2; `over` přepíše klíče nejvyšší úrovně."""
    data = {"version": 2, "name": "M", "fragment": _frag(_el("a"), _el("b", "F2"),
            wires=[{"id": "w", "a": {"element_id": "a", "port": "1"}, "b": {"element_id": "b", "port": "2"}}])}
    data.update(over)
    return data


def _macro(fragment=None, **kw) -> Macro:
    return Macro(name=kw.pop("name", "T"), description="", fragment=fragment or _frag(_el()), path=kw.pop("path", macros.Path()),
                 source=kw.pop("source", "vlastní"), **kw)


# ---- MacroVar / ValueSet --------------------------------------------------------------------------------------
def test_macrovar_to_dict_full_and_minimal():
    assert MacroVar(name="x").to_dict() == {"name": "x"}
    v = MacroVar(name="c", label="Proud", type="choice", default="16", unit="A", help="h", required=True,
                 choices=("10", "16"), min=1.0, max=63.0, category="mcb", source="art.in_", auto=True)
    assert v.to_dict() == {"name": "c", "label": "Proud", "type": "choice", "default": "16", "unit": "A", "help": "h",
                           "category": "mcb", "from": "art.in_", "required": True, "choices": ["10", "16"],
                           "min": 1.0, "max": 63.0, "auto": True}
    assert v.title == "Proud" and MacroVar(name="x").title == "x"


def test_macrovar_from_dict_bad_numbers_become_none():
    v = MacroVar.from_dict({"name": "x", "min": "abc", "max": "", "default": 2.0, "choices": [1, True]})
    assert v.min is None and v.max is None and v.default == "2" and v.choices == ("1", "1")


def test_valueset_to_dict_with_and_without_description():
    assert ValueSet("A", {"x": "1"}).to_dict() == {"name": "A", "values": {"x": "1"}}
    assert ValueSet("A", {"x": "1"}, "popis").to_dict() == {"name": "A", "values": {"x": "1"}, "description": "popis"}


# ---- parse_macro / load_macro ---------------------------------------------------------------------------------
@pytest.mark.parametrize("data", [[], {"name": "x"}, {"fragment": []}])
def test_parse_macro_without_fragment_raises(data):
    with pytest.raises(ValueError, match="fragment"):
        parse_macro(data)


def test_parse_macro_invalid_version_raises():
    with pytest.raises(ValueError, match="Neplatná verze makra: 'x'"):
        parse_macro({"version": "x", "fragment": _frag()})


def test_parse_macro_bad_pitch_is_none_and_good_pitch_parsed():
    m = parse_macro({"fragment": _frag(), "repeat": {"count": "n", "pitch": "abc"}})
    assert m.repeat.count == "n" and m.repeat.pitch is None
    assert parse_macro({"fragment": _frag(), "repeat": {"count": "n", "pitch": "12,5"}}).repeat.pitch is None  # čárka není číslo
    assert parse_macro({"fragment": _frag(), "repeat": {"count": "n", "pitch": "12.5"}}).repeat.pitch == 12.5


def test_parse_macro_name_defaults_to_file_stem():
    assert parse_macro({"fragment": _frag()}, "/x/kus.json").name == "kus"


def test_load_macro_unreadable_and_invalid_json(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="envocad.library")
    assert load_macro(tmp_path / "neni.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{nejson", encoding="utf-8")
    assert load_macro(bad) is None
    assert "nelze načíst" in caplog.text


def test_load_macro_non_numeric_version_is_invalid(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="envocad.library")
    p = tmp_path / "v.json"
    p.write_text(json.dumps({"version": "abc", "fragment": _frag()}), encoding="utf-8")
    assert load_macro(p) is None
    assert "je neplatné" in caplog.text and "Neplatná verze" in caplog.text


def test_load_macro_without_fragment_is_invalid(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="envocad.library")
    p = tmp_path / "nf.json"
    p.write_text(json.dumps({"name": "x"}), encoding="utf-8")
    assert load_macro(p) is None
    assert "je neplatné" in caplog.text


def test_load_macro_non_dict_json_is_invalid(tmp_path):
    p = tmp_path / "list.json"
    p.write_text("[1, 2]", encoding="utf-8")
    assert load_macro(p) is None


# ---- validate_macro -------------------------------------------------------------------------------------------
def test_validate_valid_macro_has_no_errors():
    assert validate_macro(_valid()) == []


def test_validate_not_object():
    assert validate_macro([]) == ["Makro není objekt JSON."]


@pytest.mark.parametrize("data, expected", [
    ({"fragment": _frag()}, ["Chybí název makra („name“)."]),
    ({"name": "x", "version": True, "fragment": _frag()}, ["Neplatná verze makra True (podporováno 1–3)."]),
    ({"name": "x", "version": 4, "fragment": _frag()}, ["Neplatná verze makra 4 (podporováno 1–3)."]),
    ({"name": "x"}, ["Chybí fragment makra („fragment“)."]),
    ({"name": "x", "fragment": {"elements": {}}}, ["Fragment musí mít seznamy „elements“ a „wires“."]),
])
def test_validate_top_level_errors(data, expected):
    assert validate_macro(data) == expected


def test_validate_role_must_be_text():
    assert validate_macro(_valid(role=5)) == ["Role makra musí být text."]


def _var(**kw):
    return {"name": "x", **kw}


@pytest.mark.parametrize("variables, fragment_text", [
    ("neseznam", "„variables“ musí být seznam."),
    ([5], "Proměnná musí být objekt."),
    ([{"name": "1bad"}], "Neplatný název proměnné '1bad'"),
    ([{"label": "bez jména"}], "Neplatný název proměnné None"),
    ([_var(), _var()], "Proměnná „x“ je deklarovaná dvakrát."),
    ([_var(type="bool")], "Proměnná „x“: neznámý typ 'bool' (povolené: text, number, choice, component)."),
    ([_var(default=[1])], "Proměnná „x“: výchozí hodnota musí být text."),
    ([_var(type="choice")], "Proměnná „x“ typu choice potřebuje neprázdný seznam „choices“."),
    ([_var(type="choice", choices=[1])], "typu choice potřebuje neprázdný seznam"),
    ([_var(type="component")], "Proměnná „x“ typu component potřebuje „category“."),
    ([_var(min="abc")], "Proměnná „x“: „min“ musí být číslo."),
    ([_var(max=True)], "Proměnná „x“: „max“ musí být číslo."),
    ([_var(**{"from": "a"})], "„from“ musí mít tvar"),
    ([_var(**{"from": "x.in_"})], "„from“ musí mít tvar"),
])
def test_validate_variable_errors(variables, fragment_text):
    errs = validate_macro(_valid(variables=variables))
    assert any(fragment_text in e for e in errs), errs


def test_validate_from_component_variable_ok():
    data = _valid(variables=[{"name": "art", "type": "component", "category": "mcb"},
                             {"name": "in_", "from": "art.in_"}])
    assert validate_macro(data) == []


@pytest.mark.parametrize("sets, expected", [
    ([5], ["Sada hodnot musí mít název."]),
    ([{"name": " "}], ["Sada hodnot musí mít název."]),
    ([{"name": "A", "values": {}}, {"name": "A", "values": {}}], ["Sada hodnot „A“ je dvakrát."]),
    ([{"name": "A", "values": []}], ["Sada hodnot „A“: „values“ musí být objekt."]),
    ([{"name": "A", "values": {"y": "1"}}], ["Sada hodnot „A“: neznámá proměnná „y“."]),
])
def test_validate_value_set_errors(sets, expected):
    assert validate_macro(_valid(variables=[_var()], value_sets=sets)) == expected


@pytest.mark.parametrize("repeat, expected", [
    (5, ["„repeat“ musí být objekt s „count“ (název proměnné)."]),
    ({"count": 3}, ["„repeat“ musí být objekt s „count“ (název proměnné)."]),
    ({"count": "m"}, ["Opakování: proměnná počtu „m“ není deklarovaná."]),
    ({"count": "x", "pitch": "abc"}, ["Opakování: „pitch“ musí být kladné číslo."]),
    ({"count": "x", "pitch": 0}, ["Opakování: „pitch“ musí být kladné číslo."]),
])
def test_validate_repeat_errors(repeat, expected):
    assert validate_macro(_valid(variables=[_var()], repeat=repeat)) == expected


def test_validate_repeat_max_over_limit():
    errs = validate_macro(_valid(variables=[_var(max=101)], repeat={"count": "x"}))
    assert errs == ["Opakování: „max“ proměnné počtu „x“ (101) je větší než 100."]


def test_validate_fragment_element_errors_and_non_dict_items():
    data = _valid(fragment=_frag({"symbol_id": "s"}, "ne-dict", wires=["ne-dict"]))
    assert validate_macro(data) == ["Prvek fragmentu musí mít „id“ a „symbol_id“.",
                                    "Prvek fragmentu musí mít „id“ a „symbol_id“.",
                                    "Vodič fragmentu musí být objekt."]


def test_validate_when_conditions():
    bad = _el("a", when="a b c")
    undeclared = _el("b", "F2", when="neznama")
    errs = validate_macro(_valid(variables=[_var()], fragment=_frag(bad, undeclared)))
    assert errs[0].startswith("Podmínka „a b c“ (prvek) – povolené tvary")
    assert errs[1] == "Podmínka „neznama“ (prvek) odkazuje na nedeklarovanou proměnnou „neznama“."


def test_validate_wire_to_missing_element_and_undeclared_placeholder():
    wire = {"id": "w1", "a": {"element_id": "a", "port": "1"}, "b": {"element_id": "zzz", "port": "{p}"}}
    errs = validate_macro(_valid(variables=[_var()], fragment=_frag(_el("a"), wires=[wire])))
    assert errs == ["Vodič w1 odkazuje na neexistující prvek.", "Zástupný symbol {p} není deklarovaný v „variables“."]


# ---- adresáře maker ------------------------------------------------------------------------------------------
def test_shared_dir_swallows_settings_errors(monkeypatch):
    import envocad.settings as st

    def boom():
        raise RuntimeError("x")
    monkeypatch.setattr(st, "shared_library_dir", boom)
    assert shared_dir() is None


def test_macro_dirs_include_shared_dir_between_builtin_and_user(monkeypatch, tmp_path):
    import envocad.settings as st
    monkeypatch.setattr(st, "shared_library_dir", lambda: tmp_path)
    dirs = macro_dirs()
    assert [s for _, s in dirs] == ["vestavěné", "sdílené", "vlastní"]
    assert dirs[1][0] == tmp_path / "macros"


def test_list_macros_user_overrides_shared_by_name_and_sorts(monkeypatch, tmp_path):
    import envocad.settings as st
    shared = tmp_path / "shared"
    (shared / "macros").mkdir(parents=True)
    monkeypatch.setattr(st, "shared_library_dir", lambda: shared)
    (shared / "macros" / "a.json").write_text(json.dumps({"name": "Zz", "fragment": _frag()}), encoding="utf-8")
    macros.save_macro("Zz", "vlastní verze", _frag(_el()))
    got = {m.name: m for m in list_macros() if m.name == "Zz"}
    assert got["Zz"].source == "vlastní" and got["Zz"].description == "vlastní verze"


# ---- delete, bounds, pitch -----------------------------------------------------------------------------------
def test_delete_macro_builtin_missing_and_existing(tmp_path):
    assert delete_macro(_macro(source="vestavěné")) is False
    assert delete_macro(_macro(path=tmp_path / "neni.json")) is False
    p = tmp_path / "x.json"
    p.write_text("{}", encoding="utf-8")
    assert delete_macro(_macro(path=p)) is True and not p.exists()


def test_fragment_bounds_empty_and_nonempty():
    assert fragment_bounds({}) == (0.0, 0.0, 0.0, 0.0)
    f = _frag({**_el("a"), "x": 5, "y": -2}, {**_el("b", "F2"), "x": 25, "y": 7})
    assert fragment_bounds(f) == (5, -2, 25, 7)


@pytest.mark.parametrize("pitch, expected", [(40, 40.0), ("abc", 30.0), ([1], 30.0), (None, 30.0), (0, 30.0)])
def test_macro_pitch_explicit_or_width_plus_ten(pitch, expected):
    frag = _frag({**_el("a"), "x": 0}, {**_el("b", "F2"), "x": 20}) | ({"pitch": pitch} if pitch is not None else {})
    assert macro_pitch(_macro(frag)) == expected


# ---- resolve_values: větve --------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw", ["inf", "nan", "-inf"])
def test_resolve_values_non_finite_is_not_a_number(raw):
    m = _macro(variables=[MacroVar(name="n", type="number")])
    _, errs = resolve_values(m, given={"n": raw})
    assert errs == [f"Makro „T“: n: „{raw}“ není číslo."]


class _Comp:
    id = "art1"
    part_number = "PN-1"
    manufacturer = "Acme"
    name = "Jistič"
    category = "mcb"
    symbol_id = "fve.breaker_mcb"
    footprint_id = None
    params = types.MappingProxyType({"in_": "16", "pocet": 3})


def test_resolve_values_component_parameters_from_artikl():
    m = _macro(variables=[MacroVar(name="art", type="component", category="mcb"),
                          MacroVar(name="a_id", source="art.id"), MacroVar(name="a_fp", source="art.footprint_id"),
                          MacroVar(name="a_in", source="art.in_"), MacroVar(name="a_cnt", source="art.pocet"),
                          MacroVar(name="a_no", source="art.neni")])
    vals, errs = resolve_values(m, given={"art": "art1"}, components=lambda cid: _Comp())
    assert errs == []
    assert (vals["a_id"], vals["a_in"], vals["a_cnt"], vals["a_no"], vals["a_fp"]) == ("art1", "16", "3", "", "")


def test_resolve_values_component_errors():
    m = _macro(variables=[MacroVar(name="art", type="component", category="rcd")])
    _, errs = resolve_values(m, given={"art": "art1"}, components=lambda cid: None)
    assert errs == ["Makro „T“: art: artikl „art1“ nenalezen."]
    _, errs = resolve_values(m, given={"art": "art1"}, components=lambda cid: _Comp())
    assert errs == ["Makro „T“: art: artikl „art1“ není kategorie „rcd“."]
    _, errs = resolve_values(m, given={"art": "art1"})   # bez vyhledávače se artikl nehledá
    assert errs == []


def test_resolve_values_unknown_value_set_and_choice_normalization():
    m = _macro(variables=[MacroVar(name="c", type="choice", choices=("1 P", "3P"))])
    _, errs = resolve_values(m, value_set="nic")
    assert errs == ["Makro „T“: neznámá sada hodnot „nic“."]
    vals, errs = resolve_values(m, given={"c": "3p"})
    assert errs == [] and vals["c"] == "3P"
    _, errs = resolve_values(m, given={"c": "2P"})
    assert errs == ["Makro „T“: c: „2P“ není z nabídky (1 P, 3P)."]


# ---- condition, repeat_count, repeat_start ------------------------------------------------------------------
@pytest.mark.parametrize("expr, vals, expected", [
    ("a b c", {}, True),          # neplatný zápis = pravda
    ("", {}, True),
    ("x", {"x": "Ne"}, False), ("x", {"x": "1"}, True), ("!x", {"x": "off"}, True),
    ("x=2", {"x": "2"}, True), ("x!=2", {"x": "2"}, False), ("x=", {}, True),
])
def test_condition_branches(expr, vals, expected):
    assert condition(expr, vals) is expected


def test_repeat_count_without_repeat_is_one():
    assert repeat_count(_macro(), {}) == 1


def test_repeat_count_errors():
    m = _macro(variables=[MacroVar(name="n", type="number", max=5.0)], repeat=macros.Repeat("n"))
    assert repeat_count(m, {"n": "3,0"}) == 3
    with pytest.raises(ValueError, match="počet opakování „“ \\(n\\) není celé číslo"):
        repeat_count(m, {})
    with pytest.raises(ValueError, match="„2.5“"):
        repeat_count(m, {"n": "2.5"})
    with pytest.raises(ValueError, match="6 je mimo rozsah 0–5"):
        repeat_count(m, {"n": "6"})
    with pytest.raises(ValueError, match="-1 je mimo rozsah 0–5"):
        repeat_count(m, {"n": "-1"})


@pytest.mark.parametrize("val, expected", [(None, 1), ("abc", 1), ("0", 1), ("4,9", 4), ("7", 7)])
def test_repeat_start(val, expected):
    assert repeat_start({} if val is None else {"k_start": val}) == expected


# ---- expand: vodič s nesplněnou podmínkou -------------------------------------------------------------------
def test_expand_skips_wire_with_false_when():
    wire = {"id": "w", "a": {"element_id": "a", "port": "1"}, "b": {"element_id": "b", "port": "2"},
            "attrs": {"when": "spoj"}}
    frag = _frag(_el("a"), _el("b", "F2"), wires=[wire])
    p = Project()
    s = Sheet(name="L")
    p.sheets.append(s)
    els, wires = macros.expand(p, s, frag, {"spoj": "ne"})
    assert len(els) == 2 and wires == []
    els, wires = macros.expand(p, s, frag, {"spoj": "ano"})
    assert len(wires) == 1 and "when" not in wires[0].attrs


# ---- suggest_numbering: krajní případy ----------------------------------------------------------------------
def test_suggest_numbering_without_placeholder_refs_is_empty():
    p = Project()
    s = Sheet(name="L")
    p.sheets.append(s)
    assert suggest_numbering(p, s, _macro(_frag(_el("a", "F1")))) == {}


def test_suggest_numbering_non_repeating_without_auto_k_is_empty():
    p = Project()
    s = Sheet(name="L")
    p.sheets.append(s)
    m = _macro(_frag(_el("a", "X{q}")), variables=[MacroVar(name="q")])
    assert suggest_numbering(p, s, m) == {}


def test_suggest_numbering_limit_zero_gives_empty():
    p = Project()
    s = Sheet(name="L")
    p.sheets.append(s)
    m = _macro(_frag(_el("a", "X{k}")), variables=[MacroVar(name="k", auto=True)])
    assert suggest_numbering(p, s, m, limit=0) == {}


def test_suggest_numbering_follows_existing_refs():
    p = Project()
    s = Sheet(name="L")
    p.sheets.append(s)
    m = _macro(_frag(_el("a", "X{k}")), variables=[MacroVar(name="k", auto=True)])
    assert suggest_numbering(p, s, m) == {}
    from envocad.model.project import Element
    s.elements.append(Element(symbol_id="fve.breaker_mcb", x=0, y=0, attrs={"ref": "X1"}))
    s.elements.append(Element(symbol_id="fve.breaker_mcb", x=0, y=0, attrs={"ref": "X2"}))
    assert suggest_numbering(p, s, m) == {"k": "3"}


def test_macro_data_roundtrip_is_not_mutated_by_validate():
    data = _valid()
    snap = copy.deepcopy(data)
    validate_macro(data)
    assert data == snap
