"""Nastavení a firemní standard, sdílená knihovna (bez Qt)."""

import json


def test_settings_and_shared_library(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVOCAD_HOME", str(tmp_path / "home"))
    from envocad import settings
    st = settings.load_settings()
    assert st["standard"]["company"] == "ENVO s.r.o." and st["shared_library_dir"] == ""
    st["standard"]["author"] = "PR"
    st["standard"]["dc_cable"] = "H1Z2Z2-K 1x10"
    shared = tmp_path / "shared"
    shared.mkdir()
    st["shared_library_dir"] = str(shared)
    settings.save_settings(st)
    assert settings.load_settings()["standard"]["author"] == "PR"
    assert settings.shared_library_dir() == shared
    spec = settings.apply_standard_to_spec({"name": "X", "inverters": [{"strings": [10]}], "ac": {"cross": 25}})
    assert spec["meta"]["author"] == "PR" and spec["dc"]["cable"] == "H1Z2Z2-K 1x10" and spec["ac"]["cross"] == 25
    # sdílená značka se načte do knihovny (výchozí DB v ENVOCAD_HOME)
    sym = {"id": "shared.test", "name": "Sdílená značka", "category": "Jištění", "primitives": [],
           "ports": [{"name": "1", "x": 0, "y": 0, "dir": "W"}], "attributes": [], "label_pos": {"x": 0, "y": 0}}
    (shared / "shared.test.json").write_text(json.dumps(sym), encoding="utf-8")
    from envocad.library.store import LibraryStore
    lib = LibraryStore()
    assert lib.get_symbol("shared.test").name == "Sdílená značka"
