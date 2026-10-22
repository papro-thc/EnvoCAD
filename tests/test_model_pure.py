"""Model a knihovna jsou čisté: nečtou uživatelská nastavení (`envocad.settings`), standard dostávají parametrem.

Výjimka (záměr): knihovna (`envocad/library/store.py`, `macros.py`, `topologies.py`) hledá podle nastavení složky
s daty – uživatelskou složku vedle `settings.json` a sdílenou firemní knihovnu. Je to umístění vstupních souborů, ne
firemní standard výkresu; test knihovny ho přesměruje přes `ENVOCAD_HOME` (conftest)."""
import ast
from pathlib import Path

from envocad import settings
from envocad.model import frame
from envocad.model import multipole as mp

ROOT = Path(__file__).resolve().parent.parent / "envocad"
LIBRARY_LOCATIONS = {"store.py", "macros.py", "topologies.py"}   # složky knihovny ze nastavení (záměr, viz výše)


def _imports_settings(path: Path) -> bool:
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.ImportFrom) and n.module == "envocad.settings":
            return True
        if isinstance(n, ast.ImportFrom) and n.module == "envocad" and any(a.name == "settings" for a in n.names):
            return True
        if isinstance(n, ast.Import) and any(a.name == "envocad.settings" for a in n.names):
            return True
    return False


def test_model_does_not_import_settings():
    bad = [str(p.relative_to(ROOT)) for p in sorted((ROOT / "model").rglob("*.py")) if _imports_settings(p)]
    assert bad == []


def test_library_reads_settings_only_for_locations():
    bad = [p.name for p in sorted((ROOT / "library").rglob("*.py")) if _imports_settings(p)]
    assert set(bad) <= LIBRARY_LOCATIONS


def _save(**standard) -> None:
    s = settings.load_settings()
    s["standard"].update(standard)
    s["frame"] = True
    settings.save_settings(s)


def test_settings_helpers_and_model_defaults():
    from envocad.model.project import Element, Project
    p = Project()
    blk = Element("fve.switchboard", 100, 100, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    assert settings.switchboard_paper() == "A4" and settings.company() == frame.COMPANY
    assert settings.frame_enabled() is False
    _save(switchboard_paper="A4 na výšku", company="Firma XY s.r.o.")
    assert settings.switchboard_paper() == "A4 na výšku" and settings.company() == "Firma XY s.r.o."
    assert settings.frame_enabled() is True
    # model nastavení nevidí: výchozí hodnoty, standard až parametrem
    assert mp.paper_choice(sb) == "A4" and mp.paper_choice(sb, settings.switchboard_paper()) == "A4 na výšku"
    assert frame.company_names() == ("ENVO", "ENVO s.r.o.")
    assert frame.company_names(settings.company()) == ("Firma", "Firma XY s.r.o.")
    assert frame.company_names("  ") == ("ENVO", "ENVO s.r.o.")
    texts = [t[2] for t in frame.frame_geometry(p, sb, company="Firma XY s.r.o.").texts]
    assert "Firma" in texts and "ENVO" not in texts
    assert "ENVO" in [t[2] for t in frame.frame_geometry(p, sb).texts]
    _save(company="")
    assert settings.company() == frame.COMPANY


def test_settings_helpers_survive_broken_file():
    settings.settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings.settings_path().write_text('{"standard": 5}', encoding="utf-8")
    assert settings.switchboard_paper() == mp.DEFAULT_SWITCHBOARD_PAPER
    assert settings.company() == frame.COMPANY and settings.frame_enabled() is False


def test_grow_sheet_pins_given_standard():
    """Zvětšení listu rozvaděče zapíše k listu formát vícepólu podle standardu od volajícího."""
    from envocad.library.store import LibraryStore
    from envocad.library.templates import apply_template
    from envocad.model.project import Element, Project
    lib = LibraryStore()
    for std, expect in ((mp.DEFAULT_SWITCHBOARD_PAPER, "A4"), ("A3", "A3")):
        p = Project()
        blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
        p.sheets[0].elements.append(blk)
        sh = p.create_switchboard_sheet(blk)
        apply_template(p, sh, "dc", {"n_strings": "9"}, lib=lib, standard_paper=std)
        assert sh.paper != "A3" and sh.mp_paper == expect
