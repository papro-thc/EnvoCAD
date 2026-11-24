"""Překlady rozhraní (issue #91): `envocad.i18n` (gettext-styl bez Qt, katalog `.po` čtený za běhu)."""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

from envocad import settings

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "envocad"


# ---- parse_po ------------------------------------------------------------------------------------------------
def test_parse_po_basic_comments_header_and_ctx():
    from envocad.i18n import parse_po
    po = '''# komentář
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"

#: envocad/x.py:1
msgid "&Soubor"
msgstr "&File"

msgctxt "menu"
msgid "Konec"
msgstr "Exit"

msgctxt "tlacitko"
msgid "Konec"
msgstr "Quit"
'''
    cat = parse_po(po)
    assert cat == {(None, "&Soubor"): "&File", ("menu", "Konec"): "Exit", ("tlacitko", "Konec"): "Quit"}
    assert (None, "") not in cat


def test_parse_po_escapes():
    from envocad.i18n import parse_po
    po = r'''msgid "a\nb\tc \"q\" \\ d"
msgstr "A\nB\tC \"Q\" \\ D"
'''
    assert parse_po(po) == {(None, "a\nb\tc \"q\" \\ d"): "A\nB\tC \"Q\" \\ D"}


def test_parse_po_multiline_strings():
    from envocad.i18n import parse_po
    po = '''msgid ""
"První řádek\\n"
"druhý řádek"
msgstr ""
"First line\\n"
"second line"
'''
    assert parse_po(po) == {(None, "První řádek\ndruhý řádek"): "First line\nsecond line"}


def test_parse_po_skips_empty_and_fuzzy():
    from envocad.i18n import parse_po
    po = '''msgid "Prázdný"
msgstr ""

#, fuzzy
msgid "Nejistý"
msgstr "Uncertain"

msgid "Dobrý"
msgstr "Good"
'''
    assert parse_po(po) == {(None, "Dobrý"): "Good"}


def test_parse_po_empty_text():
    from envocad.i18n import parse_po
    assert parse_po("") == {}


# ---- set_language / tr ---------------------------------------------------------------------------------------
def test_constants_and_default_language():
    from envocad import i18n
    assert i18n.DEFAULT_LANGUAGE == "cs"
    assert i18n.LANGUAGES == {"cs": "Čeština", "en": "English"}
    assert i18n.language() == "cs"


def test_tr_czech_is_identity():
    from envocad import i18n
    assert i18n.set_language("cs") == "cs"
    assert i18n.tr("&Soubor") == "&Soubor"
    assert i18n.tr("cokoliv jiného") == "cokoliv jiného"


def test_tr_english_translates_known_text():
    from envocad import i18n
    assert i18n.set_language("en") == "en"
    assert i18n.language() == "en"
    assert i18n.tr("&Soubor") == "&File"
    assert i18n.tr("Konec") == "Exit"


def test_tr_unknown_text_unchanged():
    from envocad import i18n
    i18n.set_language("en")
    assert i18n.tr("Tento text v katalogu určitě není 7f3a") == "Tento text v katalogu určitě není 7f3a"


@pytest.mark.parametrize("bad", ["de", "", "EN ", None, "../en"])
def test_set_language_invalid_falls_back_to_czech(bad):
    from envocad import i18n
    i18n.set_language("en")
    assert i18n.set_language(bad) == "cs"
    assert i18n.language() == "cs"


def test_tr_ctx_distinguishes_and_missing_ctx_falls_back(monkeypatch):
    from envocad import i18n
    monkeypatch.setattr(i18n, "load_catalog",
                        lambda lang: {("a", "Stejné"): "Same A", ("b", "Stejné"): "Same B", (None, "Prázdné"): ""}
                        if lang == "en" else {})
    i18n.set_language("en")
    assert i18n.tr("Stejné", "a") == "Same A"
    assert i18n.tr("Stejné", "b") == "Same B"
    assert i18n.tr("Stejné") == "Stejné"            # bez ctx se nehledá v záznamech s ctx
    assert i18n.tr("Prázdné") == "Prázdné"          # prázdný překlad = originál


def test_catalog_path_and_load_catalog():
    from envocad import i18n
    assert i18n.catalog_path("en") == PKG / "resources" / "i18n" / "en.po"
    assert i18n.catalog_path("en").is_file()
    cat = i18n.load_catalog("en")
    assert cat[(None, "&Soubor")] == "&File"
    assert i18n.load_catalog("cs") == {}
    assert i18n.load_catalog("xx") == {}            # chybějící soubor


# ---- settings.language() -------------------------------------------------------------------------------------
def test_settings_language_default():
    assert settings.DEFAULTS["language"] == "cs"
    assert settings.load_settings()["language"] == "cs"
    assert settings.language() == "cs"


def test_settings_language_saved_en():
    s = settings.load_settings()
    s["language"] = "en"
    settings.save_settings(s)
    assert settings.language() == "en"


@pytest.mark.parametrize("bad", ["de", "", 5, None, ["en"]])
def test_settings_language_invalid_value_is_czech(bad):
    s = settings.load_settings()
    s["language"] = bad
    settings.save_settings(s)
    assert settings.language() == "cs"


def test_settings_language_corrupt_file_is_czech():
    settings.settings_path().write_text("{ tohle není json", encoding="utf-8")
    assert settings.language() == "cs"


# ---- bez Qt --------------------------------------------------------------------------------------------------
def test_i18n_imports_without_qt():
    code = ("import envocad.i18n, sys; "
            "bad = [m for m in sys.modules if m.startswith(('PySide6', 'shiboken6', 'envocad.ui'))]; assert not bad, bad")
    subprocess.run([sys.executable, "-c", code], check=True, cwd=ROOT, stdin=subprocess.DEVNULL)


# ---- úplnost katalogu ----------------------------------------------------------------------------------------
def _tr_calls():
    """(soubor, řádek, ctx, text) všech volání `tr(...)` / `i18n.tr(...)`; text/ctx None = není řetězcový literál."""
    out = []
    for path in sorted(PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            is_tr = (isinstance(f, ast.Name) and f.id == "tr") or \
                    (isinstance(f, ast.Attribute) and f.attr == "tr" and isinstance(f.value, ast.Name)
                     and f.value.id == "i18n")
            if not is_tr:
                continue

            def lit(node):
                return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None
            text = lit(n.args[0]) if n.args else None
            ctx_node = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "ctx"), None)
            ctx = lit(ctx_node) if ctx_node is not None else None
            out.append((str(path.relative_to(ROOT)), n.lineno, ctx, text, ctx_node is not None and ctx is None))
    return out


def test_tr_calls_use_string_literals():
    bad = [f"{p}:{ln}" for p, ln, _ctx, text, bad_ctx in _tr_calls() if text is None or bad_ctx]
    assert bad == [], f"tr() musí dostat řetězcový literál (ne f-string / proměnnou): {bad}"


def test_catalog_complete_and_without_leftovers():
    from envocad import i18n
    cat = i18n.load_catalog("en")
    used = {(ctx, text) for _p, _ln, ctx, text, _b in _tr_calls() if text is not None}
    assert used, "v kódu není žádné volání tr()"
    missing = sorted(k for k in used if not cat.get(k))
    assert missing == [], f"chybí překlad v en.po: {missing}"
    unused = sorted(k for k in cat if k not in used)
    assert unused == [], f"en.po obsahuje nepoužité záznamy: {unused}"


# ---- balení --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["envocad.spec", "pyproject.toml"])
def test_packaging_includes_po_catalogs(name):
    assert "resources/i18n/*.po" in (ROOT / name).read_text(encoding="utf-8")


def test_parse_po_fuzzy_without_blank_line_keeps_previous_entry():
    """`#, fuzzy` hned za záznamem (bez prázdného řádku) patří až dalšímu záznamu."""
    from envocad import i18n
    text = 'msgid "a"\nmsgstr "A"\n#, fuzzy\nmsgid "b"\nmsgstr "B"\n#, fuzzy\nmsgctxt "x"\nmsgid "c"\nmsgstr "C"\n'
    assert i18n.parse_po(text) == {(None, "a"): "A"}


def test_load_catalog_invalid_utf8_is_empty(tmp_path, monkeypatch):
    """Poškozený katalog (neplatné UTF-8) nesmí shodit start – rozhraní zůstane česky."""
    from envocad import i18n
    bad = tmp_path / "en.po"
    bad.write_bytes(b'msgid "a"\nmsgstr "\xff"\n')
    monkeypatch.setattr(i18n, "catalog_path", lambda lang: bad)
    assert i18n.load_catalog("en") == {}
    assert i18n.set_language("en") == "en"
    assert i18n.tr("a") == "a"
