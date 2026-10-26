"""Příkazový řádek: rozbor řádku (body, čísla, uvozovky, klíč=hodnota), aliasy a doplňování (bez Qt)."""
import json

import pytest

from envocad.cmd import parse
from envocad.cmd.builtin import BUILTIN, default_registry
from envocad.cmd.parse import ParseError
from envocad.cmd.registry import ALIASES_FILE, CommandDef, Param, Registry, norm


# ---- tokeny a hodnoty ---------------------------------------------------------------------------------------------
def test_tokenize_quotes_and_errors():
    assert parse.tokenize('SET desc="Hlavní jistič" in_=16') == ["SET", "desc=Hlavní jistič", "in_=16"]
    assert parse.tokenize("  MOVE   F1  0,0 @10,0 ") == ["MOVE", "F1", "0,0", "@10,0"]
    assert parse.tokenize("SET desc='a # b'") == ["SET", "desc=a # b"]      # # uvnitř řádku není komentář
    assert parse.tokenize("") == []
    assert parse.tokenize(r"SAVE C:\proj\a.ecp") == ["SAVE", r"C:\proj\a.ecp"]          # zpětné lomítko není escape
    assert parse.tokenize(r'SAVE "C:\Moje projekty\a.ecp"') == ["SAVE", r"C:\Moje projekty\a.ecp"]
    assert parse.space_submits(r'SAVE "C:\x\"')                                      # uvozovky uzavřené
    with pytest.raises(ParseError, match="uvozovky"):
        parse.tokenize('SET desc="neuzavřeno')


def test_points_absolute_relative_and_decimal_dot():
    assert parse.parse_xy("12.5,40") == (12.5, 40.0)
    assert parse.parse_xy("-5,+2.5") == (-5.0, 2.5)
    assert parse.parse_xy("@10,-2.5", (100.0, 50.0)) == (110.0, 47.5)
    with pytest.raises(ParseError, match="bez předchozího bodu"):
        parse.parse_xy("@1,1", None)
    with pytest.raises(ParseError, match="desetinnou tečkou"):
        parse.parse_xy("12,5,40")                       # desetinná čárka (rozhodnutí 5)
    for bad in ("abc", "1;2", "1,", ",2", "nan,1", "1e3,2"):
        with pytest.raises(ParseError):
            parse.parse_xy(bad)


def test_numbers():
    assert parse.parse_number("90") == 90.0
    assert parse.parse_number("-2.5") == -2.5
    with pytest.raises(ParseError, match="tečku"):
        parse.parse_number("2,5")
    for bad in ("inf", "nan", "1e400", "__import__('os')", ""):
        with pytest.raises(ParseError):
            parse.parse_number(bad)


def test_port_ref_kv_selector():
    assert parse.parse_port_ref("F1:2") == ("F1", "2")
    assert parse.parse_port_ref("T1:DC+") == ("T1", "DC+")
    assert parse.parse_port_ref("RFVE.AC:X1") == ("RFVE.AC", "X1")
    assert parse.parse_port_ref("10,20") is None and parse.parse_port_ref("F1") is None
    assert parse.parse_kv("desc=a=b") == ("desc", "a=b")
    assert parse.parse_kv("ref=") == ("ref", "")
    with pytest.raises(ParseError):
        parse.parse_kv("=x")
    assert [t for t in ("F1", "Q*", "RFVE.AC", "W1", "90", "1,2", "@1,2", "ref=F1", "F1:2") if parse.is_selector(t)] \
        == ["F1", "Q*", "RFVE.AC", "W1"]


def test_substitute_vars():
    assert parse.substitute_vars("SET ref=${r} desc=${r}x", {"r": "F3"}) == "SET ref=F3 desc=F3x"
    with pytest.raises(ParseError, match=r"\$\{neni\}"):
        parse.substitute_vars("SET ref=${neni}", {})
    assert parse.substitute_vars("SET desc=$x", {}) == "SET desc=$x"


def test_space_submits():
    """Mezerník = Enter mimo uvozovky a mimo textovou výzvu (rozhodnutí 3)."""
    assert parse.space_submits("MOVE")
    assert parse.space_submits('SET desc="a b"')
    assert not parse.space_submits('SET desc="a')
    assert not parse.space_submits("SET desc='a")
    assert not parse.space_submits("Hlavní", "text")


# ---- registr a aliasy ---------------------------------------------------------------------------------------------
def test_norm_ignores_case_diacritics_prefix():
    assert norm("OTOČIT") == norm("otocit") == norm("_Otočit") == norm("-otocit") == "otocit"


def test_default_aliases_zwcad_and_czech():
    reg = default_registry(user_aliases=False)
    expect = {"I": "insert", "L": "wire", "M": "move", "CO": "copy", "CP": "copy", "RO": "rotate", "MI": "mirror",
              "E": "delete", "ERASE": "delete", "Z": "zoom", "U": "undo", "F7": "checks", "ATTR": "set",
              "VLOZIT": "insert", "vložit": "insert", "Posun": "move", "otočit": "rotate", "ZRCADLIT": "mirror",
              "smazat": "delete", "NASTAVIT": "set", "list": "sheet", "SCR": "script", "Ulož": "save"}
    for alias, name in expect.items():
        assert reg.resolve(alias).name == name, alias
    assert reg.resolve("move").name == "move" and reg.resolve("_MOVE").name == "move"
    assert reg.resolve("XY") is None
    assert "M" in reg.aliases_of("move") and "POSUN" in reg.aliases_of("move")


def test_aliases_file_targets_registered_commands():
    data = json.loads(ALIASES_FILE.read_text(encoding="utf-8"))
    names = {c.name for c in BUILTIN}
    assert data["format"] == "envocad-aliases"
    bad = {a: t for a, t in data["aliases"].items() if t not in names}
    assert bad == {}
    canon = {norm(n) for n in names}
    assert not [a for a in data["aliases"] if norm(a) in canon]       # alias nepřekrývá kanonické jméno


def test_user_aliases_override_but_not_canonical(tmp_path):
    reg = default_registry(user_aliases=False)
    f = tmp_path / "aliases.json"
    f.write_text(json.dumps({"aliases": {"M": "mirror", "MOVE": "delete", "XX": "neexistuje", "PP": "copy"}}),
                 encoding="utf-8")
    warn = reg.load_aliases(f)
    assert reg.resolve("M").name == "mirror"              # přepis aliasu (obdoba acad.pgp)
    assert reg.resolve("MOVE").name == "move"             # kanonické jméno zůstává
    assert reg.resolve("PP").name == "copy"
    assert len(warn) == 2 and reg.resolve("XX") is None
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    assert reg.load_aliases(tmp_path / "bad.json")
    assert reg.load_aliases(tmp_path / "chybi.json") == []


def test_user_aliases_from_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVOCAD_HOME", str(tmp_path))
    (tmp_path / "aliases.json").write_text(json.dumps({"aliases": {"PRESUN": "move"}}), encoding="utf-8")
    assert default_registry().resolve("přesun").name == "move"
    assert default_registry(user_aliases=False).resolve("presun") is None


def test_registry_rejects_duplicates_and_bad_param():
    reg = Registry()
    reg.add(CommandDef("x", "X", aliases=("XA",)))
    with pytest.raises(ValueError):
        reg.add(CommandDef("x", "X2"))
    reg.add(CommandDef("x", "X3"), replace=True)
    assert reg.resolve("xa").title == "X3"
    with pytest.raises(ValueError):
        Param("a", "nesmysl", "A:")


def test_complete_commands():
    reg = default_registry(user_aliases=False)
    out = reg.complete("ro")
    assert "ROTATE" in out and "RO" in out
    assert "ZRCADLIT" in reg.complete("zrc")
    assert reg.complete("qqq") == []


def test_suggest_while_typing():
    reg = default_registry(user_aliases=False)
    out = reg.suggest("ro")
    assert out[0].word == "RO" and out[0].name == "rotate" and out[0].title
    assert len({s.name for s in out}) == len(out)                # každý příkaz jednou
    assert [s.name for s in reg.suggest("li")] == [s.name for s in reg.suggest("LI")]   # bez ohledu na velikost
    assert all(s.word.lower().startswith("li") for s in reg.suggest("li"))           # 2 znaky: jen začátek slova
    assert "rotate" in {s.name for s in reg.suggest("otoč")}       # od 3 znaků i uvnitř / v českém názvu
    assert reg.suggest("") == [] and reg.suggest("RO F1") == [] and reg.suggest("qqq") == []
    assert len(reg.suggest("e", limit=3)) <= 3
