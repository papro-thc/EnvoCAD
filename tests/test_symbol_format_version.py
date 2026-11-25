"""Verze formátu symbolu (issue #135): symbol z novější verze se nenačte potichu špatně, ale ohlásí česky. Bez Qt."""
import json
import logging
import os
import zipfile

import ezdxf
import pytest

from envocad.library import archive, dxf_import, qet_import, symbol_edit
from envocad.library.archive import (
    ArchiveError,
    ProjectArchive,
    compare_with_library,
    import_missing,
    read_archive,
)
from envocad.library.store import BUILTIN_DIR, NON_SYMBOL_DIRS, LibraryStore, user_library_dir
from envocad.model import symbol as symbol_mod
from envocad.model.symbol import Attribute, Port, Symbol

SID = "firma.nova"


def _sym(sid=SID):
    return Symbol(sid, "Testovací", category="Test", iec_ref="F",
                  ports=[Port("1", 0, 0, "W"), Port("2", 5, 0, "E")],
                  attributes=[Attribute("ref", "Označení", "", True)])


def _newer(sid=SID, version=2, **extra):
    """Slovník značky ve formátu z novější verze; port má klíč, který tento program nezná."""
    d = _sym(sid).to_dict()
    d["format_version"] = version
    d["ports"][0]["budouci_klic"] = 1
    d.update(extra)
    return d


@pytest.fixture
def lib(tmp_path):
    store = LibraryStore(tmp_path / "lib.db", load_builtin=False)
    yield store
    store.close()


# ---- konstanty a zápis ---------------------------------------------------------------------------------------------
def test_constants_and_exception_type():
    assert symbol_mod.SYMBOL_FORMAT_VERSION == 1
    assert issubclass(symbol_mod.SymbolVersionError, ValueError)


def test_to_dict_writes_version_first_and_not_a_field():
    d = _sym().to_dict()
    assert d["format_version"] == symbol_mod.SYMBOL_FORMAT_VERSION
    assert next(iter(d)) == "format_version"
    assert not hasattr(_sym(), "format_version")
    assert "format_version" not in Symbol.__dataclass_fields__


def test_to_json_writes_version(tmp_path):
    f = tmp_path / "s.json"
    _sym().to_json(f)
    assert json.loads(f.read_text(encoding="utf-8"))["format_version"] == 1


def test_put_symbol_writes_version_to_data_column(lib):
    lib.put_symbol(_sym())
    row = lib.conn.execute("SELECT data FROM symbols WHERE id=?", (SID,)).fetchone()
    assert json.loads(row["data"])["format_version"] == 1


def test_save_user_symbol_writes_version(lib):
    saved = symbol_edit.save_user_symbol(lib, _sym("user.ulozena"))
    row = lib.conn.execute("SELECT data FROM symbols WHERE id=?", (saved.id,)).fetchone()
    assert json.loads(row["data"])["format_version"] == 1


def test_dxf_import_writes_version(tmp_path):
    src = tmp_path / "v.dxf"
    doc = ezdxf.new()
    doc.modelspace().add_line((0, 0), (10, 0))
    doc.saveas(src)
    out = tmp_path / "v.json"
    dxf_import.main([str(src), "--id", "fp.v", "--name", "V", "-o", str(out)])
    assert json.loads(out.read_text(encoding="utf-8"))["format_version"] == 1
    assert dxf_import.import_dxf(src, "fp.v", "V").to_dict()["format_version"] == 1


def test_qet_import_writes_version(tmp_path):
    elmt = ('<definition version="0.100.0" type="element" width="30" height="60" hotspot_x="15" hotspot_y="30">'
            '<names><name lang="cs">X</name></names><description>'
            '<line x1="0" y1="-30" x2="0" y2="30" style="" antialias="false"/>'
            '<terminal x="0" y="-30" orientation="n" name="1"/><terminal x="0" y="30" orientation="s" name="2"/>'
            '</description></definition>')
    f = tmp_path / "one.elmt"
    f.write_text(elmt, encoding="utf-8")
    out = tmp_path / "one.json"
    assert qet_import.main([str(f), "-o", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["format_version"] == 1


# ---- starý JSON bez pole a aktuální verze ----------------------------------------------------------------------------
def test_missing_key_is_version_1():
    d = _sym().to_dict()
    del d["format_version"]
    assert Symbol.from_dict(d) == _sym()


def test_current_version_roundtrip(tmp_path):
    sym = _sym()
    assert Symbol.from_dict(sym.to_dict()) == sym
    f = tmp_path / "s.json"
    sym.to_json(f)
    assert Symbol.from_json(f) == sym


def test_all_builtin_symbols_still_load():
    files = [f for f in BUILTIN_DIR.rglob("*.json") if not NON_SYMBOL_DIRS & set(f.relative_to(BUILTIN_DIR).parts)]
    assert files
    for f in files:
        sym = Symbol.from_json(f)           # starý soubor (bez pole, nebo s verzí 1) se musí načíst
        assert sym.id


def test_builtin_library_loads_through_store(tmp_path):
    st = LibraryStore(tmp_path / "b.db")
    try:
        assert st.get_symbol("fve.breaker_mcb").id == "fve.breaker_mcb"
    finally:
        st.close()


# ---- novější verze ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("version", [2, 3, 99])
def test_newer_version_raises_czech_error_with_id(version):
    with pytest.raises(symbol_mod.SymbolVersionError) as ei:
        Symbol.from_dict(_newer(version=version))
    assert "novější verzí EnvoCAD" in str(ei.value)
    assert SID in str(ei.value)


def test_newer_version_checked_before_parsing_ports():
    # bez kontroly verze by `Port(**p)` padl na TypeError kvůli neznámému klíči
    with pytest.raises(symbol_mod.SymbolVersionError):
        Symbol.from_dict(_newer())


@pytest.mark.parametrize("bad", [True, "2", 1.5, 0, -1])
def test_invalid_version_is_value_error_not_version_error(bad):
    d = _sym().to_dict()
    d["format_version"] = bad
    with pytest.raises(ValueError) as ei:
        Symbol.from_dict(d)
    assert not isinstance(ei.value, symbol_mod.SymbolVersionError)
    assert "neplatná verze formátu" in str(ei.value)


def test_from_json_newer_version(tmp_path):
    f = tmp_path / "n.json"
    f.write_text(json.dumps(_newer()), encoding="utf-8")
    with pytest.raises(symbol_mod.SymbolVersionError):
        Symbol.from_json(f)


# ---- LibraryStore: synchronizace složky ------------------------------------------------------------------------------
def test_sync_skips_newer_file_and_loads_others(caplog):
    d = user_library_dir() / "firma"
    d.mkdir(parents=True, exist_ok=True)
    _sym("firma.stara").to_json(d / "stara.json")
    (d / "nova.json").write_text(json.dumps(_newer("firma.nova")), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="envocad.library"):
        st = LibraryStore()
    try:
        assert st.has_symbol("firma.stara")
        assert not st.has_symbol("firma.nova")
        assert st.has_symbol("fve.breaker_mcb")              # vestavěné značky zůstaly
    finally:
        st.close()
    msgs = [r.getMessage() for r in caplog.records if r.name == "envocad.library" and r.levelno == logging.WARNING]
    assert any("novější verzí" in m for m in msgs)


# ---- LibraryStore: řádek v SQLite z novějšího programu ---------------------------------------------------------------
def test_get_symbol_row_with_newer_version_is_key_error(tmp_path, caplog):
    path = tmp_path / "lib.db"
    st = LibraryStore(path, load_builtin=False)
    try:
        st.put_symbol(_sym())
        st._cache.clear()
        st.conn.execute("UPDATE symbols SET data=? WHERE id=?", (json.dumps(_newer()), SID))
        st.conn.commit()
        with caplog.at_level(logging.WARNING, logger="envocad.library"), pytest.raises(KeyError):
            st.get_symbol(SID)
        assert any(r.levelno == logging.WARNING for r in caplog.records)
        assert SID not in st._cache
        with pytest.raises(KeyError):                         # podruhé stejně – nic se nezapamatovalo
            st.get_symbol(SID)
    finally:
        st.close()


# ---- archiv ----------------------------------------------------------------------------------------------------------
def _write_archive(path, symbols):
    from envocad.model.project import Project
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": archive.ARCHIVE_FORMAT}))
        z.writestr("project.ecp", json.dumps(Project().to_dict()))
        z.writestr("symbols.json", json.dumps(symbols))
        z.writestr("components.json", "[]")


def test_read_archive_newer_symbol_version(tmp_path):
    p = tmp_path / "a.ecpz"
    _write_archive(p, [_newer()])
    with pytest.raises(ArchiveError) as ei:
        read_archive(p)
    assert "novější verze programu" in str(ei.value)
    assert "poškozen" not in str(ei.value)


def test_read_archive_current_symbol_ok(tmp_path):
    p = tmp_path / "a.ecpz"
    _write_archive(p, [_sym().to_dict()])
    assert [s.id for s in read_archive(p).symbols] == [SID]


@pytest.mark.parametrize("overwrite", [False, True])
def test_import_with_library_symbol_of_newer_version_is_conflict(lib, overwrite):
    lib.put_symbol(_sym())
    newer = json.dumps(_newer())
    lib.conn.execute("UPDATE symbols SET data=? WHERE id=?", (newer, SID))
    lib.conn.commit()
    lib._cache.clear()
    arc = ProjectArchive(project={}, symbols=[_sym()], components=[])
    assert compare_with_library(arc, lib).conflict_symbols == [SID]
    rep = import_missing(arc, lib, overwrite=overwrite)
    assert SID in rep.conflict_symbols and SID not in rep.new_symbols
    row = lib.conn.execute("SELECT data FROM symbols WHERE id=?", (SID,)).fetchone()
    assert row["data"] == newer                                 # novější data nepřepsána


def test_pack_project_skips_library_symbol_of_newer_version(lib, tmp_path):
    from envocad.model.project import Element, Project, Sheet
    lib.put_symbol(_sym())
    lib.put_symbol(_sym("firma.stara"))
    lib.conn.execute("UPDATE symbols SET data=? WHERE id=?", (json.dumps(_newer()), SID))
    lib.conn.commit()
    lib._cache.clear()
    prj = Project(sheets=[Sheet()])
    prj.sheets[0].elements.append(Element(SID, 0, 0, attrs={"ref": "F1"}))
    prj.sheets[0].elements.append(Element("firma.stara", 50, 0, attrs={"ref": "F2"}))
    arc = archive.pack_project(prj, lib, tmp_path / "p.ecpz")   # nespadne na KeyError
    assert [s.id for s in arc.symbols] == ["firma.stara"]


# ---- symbol_edit.is_read_only ----------------------------------------------------------------------------------------
def test_is_read_only_for_id_in_newer_source_file():
    f = user_library_dir() / "firma" / "nova.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(_newer("firma.nova")), encoding="utf-8")
    st = LibraryStore()
    try:
        assert not st.has_symbol("firma.nova")
        assert symbol_edit.is_read_only(st, "firma.nova")
        assert not symbol_edit.is_read_only(st, "firma.jina")
    finally:
        st.close()


def test_is_read_only_still_false_for_unknown_id(lib):
    assert os.path.isdir(user_library_dir())
    assert not symbol_edit.is_read_only(lib, "neexistuje")
