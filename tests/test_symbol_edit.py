"""Editor symbolů – logika úprav portů a atributů (issue #85, fáze 1). Bez Qt."""
import subprocess
import sys

import pytest

from envocad.library.store import LibraryStore
from envocad.model.symbol import Attribute, Port, Symbol

BUILTIN = "fve.breaker_mcb"      # vestavěná značka: porty 1 (-7.5, 0, W) a 2 (7.5, 0, E), vícepólová, atribut ref


@pytest.fixture
def lib(tmp_path):
    store = LibraryStore(tmp_path / "lib.db")
    yield store
    store.close()


def _user_symbol(sid="user.test", ports=None):
    return Symbol(id=sid, name="Test", category="Uživatelské",
                  ports=ports if ports is not None else [Port("A", 0, 0, "W"), Port("B", 5, 0, "E")],
                  attributes=[Attribute("ref", "Označení", "", True), Attribute("type", "Typ", "x")])


def _se():
    from envocad.library import symbol_edit
    return symbol_edit


# ---- čistota -----------------------------------------------------------------------------------------------------
def test_symbol_edit_imports_no_qt():
    code = "import sys, envocad.library.symbol_edit; sys.exit(1 if any(m.startswith('PySide6') for m in sys.modules) else 0)"
    r = subprocess.run([sys.executable, "-c", code], check=False, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr or "symbol_edit importuje Qt"


# ---- editable_copy -----------------------------------------------------------------------------------------------
def test_editable_copy_is_deep(lib):
    se = _se()
    orig = lib.get_symbol(BUILTIN)
    n_ports, n_prims = len(orig.ports), len(orig.primitives)
    first = (orig.ports[0].x, orig.attributes[0].label)
    cp = se.editable_copy(orig)
    assert cp is not orig and cp.to_dict() == orig.to_dict()
    se.add_port(cp, "Z", 10, 10)
    cp.ports[0].x = 99
    cp.attributes[0].label = "jiný"
    cp.primitives.clear()
    cp.multipole.clear()
    assert len(orig.ports) == n_ports and len(orig.primitives) == n_prims and orig.multipole
    assert (orig.ports[0].x, orig.attributes[0].label) == first
    assert lib.get_symbol(BUILTIN).ports[0].x == first[0]


# ---- porty -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("x,y,ex,ey", [(3.1, -4.9, 2.5, -5.0), (0, 0, 0, 0), (1.2, 1.3, 0.0, 2.5), (7.4, 6.2, 7.5, 5.0)])
def test_add_port_snaps_to_grid(x, y, ex, ey):
    se = _se()
    sym = _user_symbol()
    p = se.add_port(sym, "X9", x, y, "S")
    assert (p.x, p.y, p.dir, p.name) == (pytest.approx(ex), pytest.approx(ey), "S", "X9")
    assert sym.ports[-1] is p
    assert sym.validate() == []


def test_add_port_strips_name_and_default_direction():
    se = _se()
    sym = _user_symbol()
    p = se.add_port(sym, "  N1  ", 0, 0)
    assert p.name == "N1" and p.dir == "E"


@pytest.mark.parametrize("name", ["", "   "])
def test_add_port_empty_name(name):
    se = _se()
    sym = _user_symbol()
    with pytest.raises(se.SymbolEditError):
        se.add_port(sym, name, 0, 0)
    assert len(sym.ports) == 2


def test_add_port_duplicate_name():
    se = _se()
    sym = _user_symbol()
    with pytest.raises(se.SymbolEditError):
        se.add_port(sym, "A", 5, 5)
    with pytest.raises(se.SymbolEditError):
        se.add_port(sym, " A ", 5, 5)
    assert [p.name for p in sym.ports] == ["A", "B"]


@pytest.mark.parametrize("d", ["X", "e", "", "NE"])
def test_add_port_invalid_direction(d):
    se = _se()
    sym = _user_symbol()
    with pytest.raises(se.SymbolEditError):
        se.add_port(sym, "C", 0, 0, d)
    assert len(sym.ports) == 2


def test_symbol_edit_error_is_value_error():
    assert issubclass(_se().SymbolEditError, ValueError)


def test_move_port_snaps():
    se = _se()
    sym = _user_symbol()
    p = se.move_port(sym, "B", 11.3, -2.4)
    assert (p.x, p.y) == (pytest.approx(12.5), pytest.approx(-2.5))
    assert sym.port("B").x == pytest.approx(12.5)
    with pytest.raises(se.SymbolEditError):
        se.move_port(sym, "nope", 0, 0)


def test_update_port_rename_and_direction():
    se = _se()
    sym = _user_symbol()
    se.update_port(sym, "A", new_name=" L ")
    assert [p.name for p in sym.ports] == ["L", "B"]
    p = se.update_port(sym, "B", direction="N")
    assert p.dir == "N" and p.name == "B"
    p = se.update_port(sym, "L", new_name="L", direction="S")     # stejné jméno = beze změny
    assert p.name == "L" and p.dir == "S"


def test_update_port_errors():
    se = _se()
    sym = _user_symbol()
    with pytest.raises(se.SymbolEditError):
        se.update_port(sym, "A", new_name="B")            # duplicita s jiným portem
    with pytest.raises(se.SymbolEditError):
        se.update_port(sym, "A", new_name="  ")
    with pytest.raises(se.SymbolEditError):
        se.update_port(sym, "A", direction="Q")
    with pytest.raises(se.SymbolEditError):
        se.update_port(sym, "nope", direction="N")
    assert [(p.name, p.dir) for p in sym.ports] == [("A", "W"), ("B", "E")]


def test_remove_port():
    se = _se()
    sym = _user_symbol()
    se.remove_port(sym, "A")
    assert [p.name for p in sym.ports] == ["B"]
    with pytest.raises(se.SymbolEditError):
        se.remove_port(sym, "A")


# ---- atributy ----------------------------------------------------------------------------------------------------
def test_set_attribute_modifies_only_given_fields():
    se = _se()
    sym = _user_symbol()
    a = se.set_attribute(sym, "type", label="Typ prvku")
    assert (a.label, a.default, a.show) == ("Typ prvku", "x", False)
    a = se.set_attribute(sym, "type", default="y", show=True)
    assert (a.label, a.default, a.show) == ("Typ prvku", "y", True)
    assert [x.key for x in sym.attributes] == ["ref", "type"]


def test_set_attribute_adds_new_with_defaults():
    se = _se()
    sym = _user_symbol()
    a = se.set_attribute(sym, " power ")
    assert (a.key, a.label, a.default, a.show) == ("power", "power", "", False)
    assert sym.attributes[-1] is a
    a = se.set_attribute(sym, "u", label="Napětí", default="230", show=True)
    assert (a.label, a.default, a.show) == ("Napětí", "230", True)


def test_set_attribute_empty_key():
    se = _se()
    with pytest.raises(se.SymbolEditError):
        se.set_attribute(_user_symbol(), "  ")


def test_remove_attribute():
    se = _se()
    sym = _user_symbol()
    se.remove_attribute(sym, "type")
    assert [a.key for a in sym.attributes] == ["ref"]
    with pytest.raises(se.SymbolEditError):
        se.remove_attribute(sym, "ref")
    with pytest.raises(se.SymbolEditError):
        se.remove_attribute(sym, "type")


# ---- check -------------------------------------------------------------------------------------------------------
def test_check_ok_for_valid_and_builtin(lib):
    se = _se()
    assert se.check(_user_symbol()) == []
    assert se.check(lib.get_symbol(BUILTIN)) == []


def test_check_reports_validate_problems():
    se = _se()
    sym = _user_symbol(ports=[Port("A", 1.0, 0, "E"), Port("A", 0, 0, "Q")])
    issues = se.check(sym)
    assert len(issues) >= 3 and all(isinstance(i, str) for i in issues)


def test_check_missing_ref():
    se = _se()
    sym = _user_symbol()
    sym.attributes = [a for a in sym.attributes if a.key != "ref"]
    assert any("ref" in i for i in se.check(sym))


def test_check_duplicate_attribute_keys_and_empty_port_name():
    se = _se()
    sym = _user_symbol()
    sym.attributes.append(Attribute("type", "Znovu"))
    assert se.check(sym)
    sym2 = _user_symbol(ports=[Port("", 0, 0, "E")])
    assert se.check(sym2)


# ---- removed_ports -----------------------------------------------------------------------------------------------
def test_removed_ports_sorted_incl_renamed():
    se = _se()
    old = _user_symbol(ports=[Port("c", 0, 0), Port("a", 5, 0), Port("b", 10, 0), Port("d", 15, 0)])
    new = se.editable_copy(old)
    se.remove_port(new, "c")
    se.update_port(new, "a", new_name="a2")
    se.add_port(new, "zz", 20, 0)
    assert se.removed_ports(old, new) == ["a", "c"]
    assert se.removed_ports(old, old) == []


# ---- save_user_symbol --------------------------------------------------------------------------------------------
def test_save_builtin_saves_copy_with_new_id(lib):
    se = _se()
    before = [(p.name, p.x, p.y, p.dir) for p in lib.get_symbol(BUILTIN).ports]
    sym = se.editable_copy(lib.get_symbol(BUILTIN))
    se.add_port(sym, "X9", 3.1, -4.9, "S")
    saved = se.save_user_symbol(lib, sym)
    assert saved.id == f"{BUILTIN}_2" and lib.has_symbol(saved.id) and not lib.is_builtin(saved.id)
    assert "X9" in [p.name for p in lib.get_symbol(saved.id).ports]
    assert lib.is_builtin(BUILTIN)
    assert [(p.name, p.x, p.y, p.dir) for p in lib.get_symbol(BUILTIN).ports] == before
    # druhé uložení vestavěné značky → další volné id
    sym2 = se.editable_copy(lib.get_symbol(BUILTIN))
    assert se.save_user_symbol(lib, sym2).id == f"{BUILTIN}_3"


def test_save_user_symbol_overwrites_same_id(lib):
    se = _se()
    lib.put_symbol(_user_symbol())
    sym = se.editable_copy(lib.get_symbol("user.test"))
    se.remove_port(sym, "A")
    se.add_port(sym, "C", 2.6, 0)
    saved = se.save_user_symbol(lib, sym)
    assert saved.id == "user.test" and not lib.has_symbol("user.test_2")
    assert [p.name for p in lib.get_symbol("user.test").ports] == ["B", "C"]
    assert lib.get_symbol("user.test").port("C").x == pytest.approx(2.5)


def test_save_new_id(lib):
    se = _se()
    saved = se.save_user_symbol(lib, _user_symbol("user.new"))
    assert saved.id == "user.new" and lib.has_symbol("user.new") and not lib.is_builtin("user.new")


def test_save_invalid_saves_nothing(lib):
    se = _se()
    sym = se.editable_copy(lib.get_symbol(BUILTIN))
    sym.attributes = [a for a in sym.attributes if a.key != "ref"]
    with pytest.raises(se.SymbolEditError):
        se.save_user_symbol(lib, sym)
    assert not lib.has_symbol(f"{BUILTIN}_2")
    bad = _user_symbol("user.bad", ports=[Port("A", 0, 0), Port("A", 5, 0)])
    with pytest.raises(se.SymbolEditError):
        se.save_user_symbol(lib, bad)
    assert not lib.has_symbol("user.bad")


# ---- round-trip --------------------------------------------------------------------------------------------------
def test_json_round_trip(lib, tmp_path):
    se = _se()
    sym = se.editable_copy(lib.get_symbol(BUILTIN))
    se.add_port(sym, "X9", 3.1, -4.9, "S")
    se.move_port(sym, "1", -12.4, 0)
    se.set_attribute(sym, "poznamka", label="Poznámka", default="a", show=True)
    f = tmp_path / "s.json"
    sym.to_json(f)
    back = Symbol.from_json(f)
    assert [p.to_dict() for p in back.ports] == [p.to_dict() for p in sym.ports]
    assert [a.to_dict() for a in back.attributes] == [a.to_dict() for a in sym.attributes]


def test_library_round_trip_new_store(lib, tmp_path):
    se = _se()
    sym = se.editable_copy(lib.get_symbol(BUILTIN))
    se.add_port(sym, "X9", 3.1, -4.9, "S")
    saved = se.save_user_symbol(lib, sym)
    lib.close()
    lib2 = LibraryStore(tmp_path / "lib.db")
    try:
        got = lib2.get_symbol(saved.id)
        assert got.port("X9").x == pytest.approx(2.5) and got.port("X9").y == pytest.approx(-5.0)
        assert got.port("X9").dir == "S"
        assert lib2.is_builtin(BUILTIN) and not lib2.is_builtin(saved.id)
    finally:
        lib2.close()
