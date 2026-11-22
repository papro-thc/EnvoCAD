"""Archiv projektu `.ecpz` (issue #75): zabalení projektu s uživatelskými značkami a artikly, bezpečné čtení, import
do jiné knihovny (bez Qt). Jen smyšlená data."""
import json
import zipfile
from pathlib import Path

import pytest

from envocad.library import archive
from envocad.library.archive import (
    ARCHIVE_SUFFIX,
    ArchiveError,
    ProjectArchive,
    compare_with_library,
    import_missing,
    load_project,
    pack_project,
    read_archive,
)
from envocad.library.store import LibraryStore
from envocad.model.project import Cable, Element, Project, Sheet
from envocad.model.symbol import Symbol

ROOT = Path(__file__).resolve().parents[1]
MAKER = "Testovací s.r.o."


def _sym(sid="test.znacka", name="Testovací značka"):
    return Symbol(sid, name, category="Test", iec_ref="F")


def _comp(store, cid="test.artikl", symbol_id="test.znacka", name="Testovací artikl", params=None, price=12.5):
    store.put_component(cid, MAKER, "TA-1", name, symbol_id,
                        {"in_": "16"} if params is None else params, price, "https://example.com/ta")


def _builtin_ids(store):
    """(id vestavěné značky, id vestavěného artiklu z builtin CSV)."""
    sid = next(i for i, _n, _c in store.list_symbols() if store.is_builtin(i))
    cid = next(c["id"] for c in store.list_components() if not c["id"].startswith("test."))
    return sid, cid


def _home(monkeypatch, tmp_path, name):
    home = tmp_path / name
    home.mkdir()
    monkeypatch.setenv("ENVOCAD_HOME", str(home))
    return home


@pytest.fixture
def source(monkeypatch, tmp_path):
    """Zdrojová knihovna (ENVOCAD_HOME „zdroj“) s uživatelskou značkou + artiklem a projekt, který je používá;
    vrací (projekt, id vestavěné značky, id vestavěného artiklu, cesta k .ecpz, archiv z pack_project)."""
    _home(monkeypatch, tmp_path, "zdroj")
    store = LibraryStore()
    store.put_symbol(_sym())
    store.put_symbol(_sym("test.nepouzita", "Nepoužitá"))
    _comp(store)
    _comp(store, "test.nepouzity", None, "Nepoužitý artikl")
    bsym, bcomp = _builtin_ids(store)
    prj = Project(name="Archivní test", sheets=[Sheet(), Sheet()])
    prj.sheets[0].elements.append(Element("test.znacka", 0, 0, attrs={"ref": "F1"}, component_id="test.artikl"))
    prj.sheets[0].elements.append(Element(bsym, 50, 0, attrs={"ref": "F2"}, component_id=bcomp))
    prj.sheets[1].elements.append(Element("test.znacka", 0, 0, attrs={"ref": "F3"}))   # druhý list
    path = tmp_path / f"projekt{ARCHIVE_SUFFIX}"
    arch = pack_project(prj, store, path)
    store.close()
    return prj, bsym, bcomp, path, arch


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def _ok_members():
    return {"manifest.json": json.dumps({"format": 1}), "project.ecp": json.dumps(Project().to_dict())}


# ---- 1. round trip mezi dvěma knihovnami ----------------------------------------------------------------------
def test_suffix():
    assert ARCHIVE_SUFFIX == ".ecpz" and issubclass(ArchiveError, ValueError)


def test_pack_writes_flat_zip(source):
    _prj, _bs, _bc, path, arch = source
    assert isinstance(arch, ProjectArchive)
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
    assert {"manifest.json", "project.ecp", "symbols.json", "components.json"} <= names
    assert not any("/" in n or "\\" in n or ":" in n for n in names)


def test_roundtrip_into_empty_library(source, monkeypatch, tmp_path):
    prj, _bsym, _bcomp, path, arch = source
    orig_comp = arch.components[0]
    assert [c["id"] for c in arch.components] == ["test.artikl"]
    _home(monkeypatch, tmp_path, "cil")
    store = LibraryStore()
    assert not store.has_symbol("test.znacka") and store.get_component("test.artikl") is None

    got = read_archive(path)
    assert [s.id for s in got.symbols] == ["test.znacka"]
    rep = compare_with_library(got, store)
    assert rep.new_symbols == ["test.znacka"] and rep.new_components == ["test.artikl"] and not rep.conflicts
    assert not store.has_symbol("test.znacka")              # compare nic nezapisuje

    rep = import_missing(got, store)
    assert rep.new_symbols == ["test.znacka"] and rep.new_components == ["test.artikl"]
    assert rep.conflict_symbols == [] and rep.conflict_components == [] and not rep.conflicts
    assert store.has_symbol("test.znacka") and not store.is_builtin("test.znacka")
    assert store.get_symbol("test.znacka") == Symbol.from_dict(_sym().to_dict())  # from_dict doplní povinný atribut ref
    assert store.get_component("test.artikl") == orig_comp
    assert store.get_component("test.artikl")["params"] == {"in_": "16"}

    loaded = load_project(got)
    assert loaded.path is None and loaded.name == prj.name and len(loaded.sheets) == 2
    for sheet in loaded.sheets:
        for e in sheet.elements:
            assert store.has_symbol(e.symbol_id), e.symbol_id
            assert e.component_id is None or store.get_component(e.component_id) is not None, e.component_id

    store.close()
    again = LibraryStore()                                   # položky přežijí znovuotevření
    assert again.has_symbol("test.znacka") and not again.is_builtin("test.znacka")
    assert again.get_component("test.artikl") == orig_comp
    # druhý import: nic nového, nic konfliktního
    rep2 = import_missing(read_archive(path), again)
    assert not (rep2.new_symbols or rep2.new_components or rep2.conflicts)


def test_cable_component_and_footprint_are_packed(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path, "zdroj")
    store = LibraryStore()
    store.put_symbol(_sym("test.pata", "Patice"))
    store.put_symbol(_sym("test.kabel_sym", "Kabel sym"))
    store.put_component("test.kabel", MAKER, "K-1", "Kabel", None, {})
    store.put_component("test.jistic", MAKER, "J-1", "Jistič", "test.kabel_sym", {"footprint_id": "test.pata"})
    prj = Project(sheets=[Sheet()], cables=[Cable("W1", component_id="test.kabel")])
    prj.sheets[0].elements.append(Element("test.kabel_sym", 0, 0, attrs={"ref": "F1"}, component_id="test.jistic"))
    arch = pack_project(prj, store, tmp_path / "p.ecpz")
    assert {c["id"] for c in arch.components} == {"test.kabel", "test.jistic"}
    assert {s.id for s in arch.symbols} == {"test.pata", "test.kabel_sym"}   # i značka z params["footprint_id"]


# ---- 2. vestavěné a nepoužité se nebalí --------------------------------------------------------------------------
def test_builtin_and_unused_not_packed(source):
    _prj, bsym, bcomp, path, arch = source
    assert [s.id for s in arch.symbols] == ["test.znacka"]
    assert [c["id"] for c in arch.components] == ["test.artikl"]
    with zipfile.ZipFile(path) as z:
        blob = b"".join(z.read(n) for n in z.namelist() if n not in ("project.ecp",))
    for forbidden in (bsym, bcomp, "test.nepouzita", "test.nepouzity"):
        assert forbidden.encode() not in blob, forbidden
    # v project.ecp zůstanou odkazy na vestavěné značky/artikl
    with zipfile.ZipFile(path) as z:
        ecp = json.loads(z.read("project.ecp"))
    assert bcomp in json.dumps(ecp)


# ---- 3. konflikty ----------------------------------------------------------------------------------------------
def _conflict_store(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path, "cil")
    store = LibraryStore()
    store.put_symbol(_sym(name="Jiná značka"))
    _comp(store, name="Jiný artikl")
    return store


def test_conflict_not_overwritten(source, monkeypatch, tmp_path):
    arch = read_archive(source[3])
    store = _conflict_store(monkeypatch, tmp_path)
    rep = compare_with_library(arch, store)
    assert rep.conflict_symbols == ["test.znacka"] and rep.conflict_components == ["test.artikl"]
    assert rep.conflicts and not rep.new_symbols and not rep.new_components
    assert store.get_symbol("test.znacka").name == "Jiná značka"        # compare nezapsal

    rep = import_missing(arch, store)
    assert rep.conflict_symbols == ["test.znacka"] and rep.conflict_components == ["test.artikl"] and rep.conflicts
    assert store.get_symbol("test.znacka").name == "Jiná značka"
    assert store.get_component("test.artikl")["name"] == "Jiný artikl"


def test_conflict_overwrite(source, monkeypatch, tmp_path):
    arch = read_archive(source[3])
    store = _conflict_store(monkeypatch, tmp_path)
    import_missing(arch, store, overwrite=True)
    assert store.get_symbol("test.znacka").name == "Testovací značka"
    assert store.get_component("test.artikl")["name"] == "Testovací artikl"
    assert not store.is_builtin("test.znacka")


def test_same_content_is_neither_new_nor_conflict(source, monkeypatch, tmp_path):
    arch = read_archive(source[3])
    _home(monkeypatch, tmp_path, "cil")
    store = LibraryStore()
    store.put_symbol(_sym())
    _comp(store)
    for rep in (compare_with_library(arch, store), import_missing(arch, store)):
        assert rep.new_symbols == [] and rep.new_components == [] and not rep.conflicts


def test_builtin_symbol_never_overwritten(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path, "cil")
    store = LibraryStore()
    bsym, _ = _builtin_ids(store)
    original = store.get_symbol(bsym)
    fake = Symbol(bsym, "Podvržená vestavěná", category="Test")
    arch = ProjectArchive(project=Project().to_dict(), symbols=[fake], components=[])
    for ow in (False, True):
        rep = import_missing(arch, store, overwrite=ow)
        assert rep.conflict_symbols == [bsym] and rep.conflicts
        assert store.is_builtin(bsym) and store.get_symbol(bsym).name == original.name != fake.name


# ---- 4. bezpečnost ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad_name", ["../zlo.json", "a/b.json", "C:x", "a\\b"])
def test_unsafe_member_name(tmp_path, bad_name):
    path = _zip(tmp_path / "zly.ecpz", {**_ok_members(), bad_name: "{}"})
    with pytest.raises(ArchiveError):
        read_archive(path)
    assert not (tmp_path.parent / "zlo.json").exists() and not (tmp_path / "zlo.json").exists()


def test_not_a_zip(tmp_path):
    p = tmp_path / "x.ecpz"
    p.write_text("tohle není zip", encoding="utf-8")
    with pytest.raises(ArchiveError):
        read_archive(p)


def test_missing_project_or_manifest(tmp_path):
    ok = _ok_members()
    with pytest.raises(ArchiveError):
        read_archive(_zip(tmp_path / "a.ecpz", {k: v for k, v in ok.items() if k != "project.ecp"}))
    with pytest.raises(ArchiveError):
        read_archive(_zip(tmp_path / "b.ecpz", {k: v for k, v in ok.items() if k != "manifest.json"}))


def test_invalid_json(tmp_path):
    with pytest.raises(ArchiveError):
        read_archive(_zip(tmp_path / "c.ecpz", {**_ok_members(), "project.ecp": "{ není json"}))


def test_read_extracts_nothing_to_disk(source, tmp_path, monkeypatch):
    work = tmp_path / "prazdna"
    work.mkdir()
    monkeypatch.chdir(work)
    read_archive(source[3])
    assert list(work.iterdir()) == []


# ---- 5. git / licence ------------------------------------------------------------------------------------------
def test_gitignore_and_license_check():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "*.ecpz" in [ln.strip() for ln in lines]
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_licensed_data", ROOT / "tools" / "check_licensed_data.py")
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    assert check.problems(["x/projekt.ecpz"])


# ---- 6. bez Qt ------------------------------------------------------------------------------------------------
def test_archive_module_has_no_qt():
    """Obecně hlídá `test_model_pure` (celá složka `library`); tady jen jistota, že modul existuje a Qt neimportuje."""
    src = Path(archive.__file__).read_text(encoding="utf-8")
    assert "PySide6" not in src and "PyQt" not in src
