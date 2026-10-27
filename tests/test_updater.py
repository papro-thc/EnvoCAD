"""Aktualizace na vydané verze (`envocad/updater.py`) – proti dočasnému git repozitáři a ZIPu, bez sítě a bez Qt."""
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from envocad import updater

CHANGELOG = """# Changelog

## Nevydáno
- rozpracované

## 0.12.0 – 2026-11-01
- nová funkce B

## 0.11.0 – 2026-10-01
- funkce A
"""


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVOCAD_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENVOCAD_NO_UPDATE", raising=False)
    return tmp_path / "home"


def run(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL).stdout.strip()


def commit(repo: Path, version: str, deps: str = "a", tag: bool = False) -> None:
    (repo / "pyproject.toml").write_text(f'version = "{version}"\ndeps = "{deps}"\n', encoding="utf-8")
    (repo / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", f"verze {version}")
    if tag:
        run(repo, "tag", "-a", f"v{version}", "-m", version)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    run(r, "init", "-q", "-b", "main")
    run(r, "config", "user.email", "t@example.com")
    run(r, "config", "user.name", "Test")
    run(r, "config", "core.autocrlf", "false")
    commit(r, "0.11.0", tag=True)
    return r


def released(repo: Path, version: str = "0.12.0", deps: str = "a") -> None:
    """Na main přibude vydaná verze, pracovní kopie zůstane na předchozím commitu (kolega ještě neaktualizoval)."""
    head = run(repo, "rev-parse", "HEAD")
    commit(repo, version, deps=deps, tag=True)
    run(repo, "reset", "-q", "--hard", head)


# ---- verze a changelog ---------------------------------------------------------------------------------------------
def test_parse_version():
    assert updater.parse_version("v0.12.3") == (0, 12, 3)
    assert updater.parse_version("1.0.0") == (1, 0, 0)
    assert updater.parse_version("v1.0") is None
    assert updater.parse_version("v1.0.0-rc1") is None
    assert updater.parse_version(None) is None


def test_release_notes_between_versions():
    notes = updater.release_notes(CHANGELOG, "0.11.0", "0.12.0")
    assert "funkce B" in notes and "funkce A" not in notes and "rozpracované" not in notes
    assert updater.release_notes(CHANGELOG, "0.12.0") == ""


def test_cut_release():
    out = updater.cut_release(CHANGELOG.replace("## 0.12.0 – 2026-11-01\n- nová funkce B\n\n", ""), "0.12.0",
                              "2026-11-02")
    assert out.index("## Nevydáno") < out.index("## 0.12.0 – 2026-11-02") < out.index("- rozpracované")
    assert updater.release_notes(out, "0.11.0").startswith("## 0.12.0 – 2026-11-02\n- rozpracované")
    with pytest.raises(ValueError):
        updater.cut_release(CHANGELOG, "0.12.0", "2026-11-02")    # sekce už existuje
    with pytest.raises(ValueError):
        updater.cut_release("# Changelog\n", "0.13.0", "2026-11-02")


# ---- klon repozitáře -----------------------------------------------------------------------------------------------
def test_no_offer_without_newer_tag(repo):
    offer, why = updater.git_offer(repo, "0.11.0")
    assert offer is None and "aktuální" in why


def test_offer_on_main_behind_tag(repo):
    released(repo)
    offer, why = updater.git_offer(repo, "0.11.0")
    assert offer is not None, why
    assert (offer.version, offer.ref) == ("0.12.0", "v0.12.0")
    assert "funkce B" in offer.notes


def test_no_offer_on_feature_branch(repo):
    released(repo)
    run(repo, "switch", "-q", "-c", "feature/x")
    offer, why = updater.git_offer(repo, "0.11.0")
    assert offer is None and "feature/x" in why


def test_no_offer_with_local_changes(repo):
    released(repo)
    (repo / "pyproject.toml").write_text("upraveno\n", encoding="utf-8")
    offer, why = updater.git_offer(repo, "0.11.0")
    assert offer is None and "lokální změny" in why


def test_untracked_files_do_not_block(repo):
    released(repo)
    (repo / "poznamky.txt").write_text("x", encoding="utf-8")
    assert updater.git_offer(repo, "0.11.0")[0] is not None


def test_no_offer_when_main_has_unreleased_commits(repo):
    released(repo)
    (repo / "dev.txt").write_text("x", encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", "vývoj")       # vývojář: main odbočil mimo tag
    offer, why = updater.git_offer(repo, "0.11.0")
    assert offer is None and "vývoj" in why


def test_check_accept_then_apply(repo):
    released(repo)
    fetched = []
    assert updater.check(repo, lambda offer, cur: True, fetch=fetched.append) is True
    assert fetched == []                              # po souhlasu se nefetchuje (apply hned následuje)
    assert updater.load_state()["pending"] == "v0.12.0"
    pips = []
    res = updater.apply_pending(repo, pip=pips.append)
    assert res == {"ok": True, "version": "0.12.0", "from": updater.__version__}
    assert run(repo, "rev-parse", "HEAD") == run(repo, "rev-parse", "v0.12.0^{commit}")
    assert pips == [repo]                             # verze v pyproject.toml se změnila → pip (i metadata balíčku)
    state = updater.load_state()
    assert "pending" not in state and state["previous"]["branch"] == "main"
    assert updater.take_result()["version"] == "0.12.0"
    assert updater.take_result() is None              # oznámí se jen jednou


def test_apply_installs_changed_dependencies(repo):
    released(repo, deps="b")
    commit_before = run(repo, "rev-parse", "HEAD")
    prev = updater.switch_to(repo, "v0.12.0", pip=lambda r: None)
    assert prev["commit"] == commit_before
    run(repo, "switch", "-q", "main")
    pips = []
    updater.switch_to(repo, "v0.12.0", pip=pips.append)
    assert pips == [repo]


def test_apply_rolls_back_when_pip_fails(repo):
    released(repo, deps="b")
    head = run(repo, "rev-parse", "HEAD")
    state = {"pending": "v0.12.0"}
    updater.save_state(state)

    def broken(_repo):
        raise updater.UpdateError("pip selhal")

    res = updater.apply_pending(repo, pip=broken)
    assert res["ok"] is False and "pip selhal" in res["error"]
    assert run(repo, "rev-parse", "HEAD") == head and updater.current_branch(repo) == "main"


def test_check_later_skips_for_a_day(repo):
    released(repo)
    asked, fetched = [], []

    def ask(offer, cur):
        asked.append(offer.version)
        return False

    assert updater.check(repo, ask, fetch=fetched.append, now=1000.0) is False
    assert updater.check(repo, ask, fetch=fetched.append, now=1000.0 + 3600) is False
    assert updater.check(repo, ask, fetch=fetched.append, now=1000.0 + updater.SKIP_SECONDS + 1) is False
    assert asked == ["0.12.0", "0.12.0"]
    assert fetched == [repo, repo, repo]              # bez souhlasu se vždy na pozadí stáhnou nové tagy


def test_rollback(repo):
    released(repo)
    updater.save_state({"pending": "v0.12.0"})
    updater.apply_pending(repo, pip=lambda r: None)
    updater.take_result()
    res = updater.rollback(repo, pip=lambda r: None)
    assert res["rollback"] is True
    assert updater.current_branch(repo) == "main"
    with pytest.raises(updater.UpdateError):
        updater.rollback(repo, pip=lambda r: None)


def test_main_check_disabled_by_env(monkeypatch):
    monkeypatch.setenv("ENVOCAD_NO_UPDATE", "1")
    assert updater.enabled() is False
    assert updater.main(["check"]) == 0


def test_enabled_by_settings(home):
    assert updater.enabled() is True
    home.mkdir(parents=True, exist_ok=True)
    (home / "settings.json").write_text(json.dumps({"auto_update": False}), encoding="utf-8")
    assert updater.enabled() is False


# ---- samostatná aplikace -------------------------------------------------------------------------------------------
def make_release(share: Path, version: str, exe: bool = True) -> Path:
    share.mkdir(parents=True, exist_ok=True)
    zip_path = share / f"EnvoCAD-{version}.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        if exe:
            z.writestr(updater.EXE_NAME, f"exe {version}")
        z.writestr("_internal/data.txt", "x")
    manifest = updater.make_manifest(version, zip_path, CHANGELOG)
    (share / updater.MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return zip_path


def test_exe_offer_and_install(tmp_path):
    share, root = tmp_path / "share", tmp_path / "app"
    make_release(share, "0.12.0")
    (root / "versions" / "0.10.0").mkdir(parents=True)
    (root / "versions" / "0.11.0").mkdir(parents=True)
    assert updater.exe_offer(share, "0.12.0") is None
    offer = updater.exe_offer(share, "0.11.0")
    assert offer.version == "0.12.0" and "funkce B" in offer.notes and "funkce A" not in offer.notes
    seen = []
    exe = updater.install_version(root, offer, lambda d, t: seen.append((d, t)), keep=("0.11.0",))
    assert exe == root / "versions" / "0.12.0" / updater.EXE_NAME and exe.read_text() == "exe 0.12.0"
    assert (root / "current.txt").read_text() == "0.12.0"
    assert sorted(p.name for p in (root / "versions").iterdir()) == ["0.11.0", "0.12.0"]   # 0.10.0 smazána
    assert seen and seen[-1][0] == seen[-1][1]


def test_exe_install_rejects_bad_checksum(tmp_path):
    share, root = tmp_path / "share", tmp_path / "app"
    make_release(share, "0.12.0")
    offer = updater.exe_offer(share, "0.11.0")
    offer.sha256 = "0" * 64
    with pytest.raises(updater.UpdateError, match="SHA-256"):
        updater.install_version(root, offer)
    assert not (root / "versions" / "0.12.0").exists() and not (root / "current.txt").exists()
    assert list((root / "versions").iterdir()) == []


def test_exe_install_requires_executable(tmp_path):
    share, root = tmp_path / "share", tmp_path / "app"
    make_release(share, "0.12.0", exe=False)
    with pytest.raises(updater.UpdateError, match=updater.EXE_NAME):
        updater.install_version(root, updater.exe_offer(share, "0.11.0"))
    assert not (root / "versions" / "0.12.0").exists()


def test_exe_install_cancel(tmp_path):
    share, root = tmp_path / "share", tmp_path / "app"
    make_release(share, "0.12.0")
    with pytest.raises(updater.UpdateError, match="zrušena"):
        updater.install_version(root, updater.exe_offer(share, "0.11.0"), lambda d, t: False)
    assert not (root / "current.txt").exists()


@pytest.mark.parametrize("patch", [{"zip": "../evil.zip"}, {"zip": "C:\\x.zip"}, {"sha256": "abc"}, {"version": "x"}])
def test_manifest_validation(tmp_path, patch):
    share = tmp_path / "share"
    make_release(share, "0.12.0")
    m = json.loads((share / updater.MANIFEST).read_text(encoding="utf-8"))
    m.update(patch)
    (share / updater.MANIFEST).write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(updater.UpdateError):
        updater.read_manifest(share)


def test_update_source_from_install_file(tmp_path, home):
    root = tmp_path / "app"
    root.mkdir()
    assert updater.update_source(root) is None
    (root / updater.SOURCE_FILE).write_text("\\\\server\\envocad\\release\n", encoding="utf-8")
    assert updater.update_source(root) == Path("\\\\server\\envocad\\release")
    home.mkdir(parents=True, exist_ok=True)
    (home / "settings.json").write_text(json.dumps({"update_dir": str(tmp_path / "jinde")}), encoding="utf-8")
    assert updater.update_source(root) == tmp_path / "jinde"


def test_call_with_timeout():
    import threading
    stop = threading.Event()
    assert updater.call_with_timeout(lambda: 42, 1.0) == 42
    assert updater.call_with_timeout(lambda: stop.wait(5), 0.05) is None
    stop.set()
    assert updater.call_with_timeout(lambda: 1 / 0, 1.0) is None


def test_versions_in_sync():
    import re
    root = Path(updater.__file__).resolve().parents[1]
    m = re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"), re.MULTILINE)
    assert m and m[1] == updater.__version__
