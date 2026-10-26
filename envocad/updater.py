"""Aktualizace EnvoCAD na vydané verze (git tagy `vX.Y.Z`). Bez Qt – dotaz na uživatele dodá volající (`ask`).

Dvě cesty instalace:

* **klon repozitáře** (`scripts/run.cmd`, `run.sh`): spouštěč před startem GUI zavolá `python -m envocad.updater
  check` – porovná lokální tagy s běžící verzí, při novější se zeptá a na pozadí spustí `git fetch`, aby příští start
  viděl nové tagy (start tak nikdy nečeká na síť). Po souhlasu spouštěč zavolá `python -m envocad.updater apply`
  v novém procesu bez Qt (pip pak může přepsat i PySide6): `git switch --detach vX.Y.Z` a `pip install -e .`, když se
  změnil `pyproject.toml`. Aktualizuje se jen čistý pracovní strom na `main` nebo na tagu, který je předkem nového
  tagu – vývojová větev ani rozpracované změny se nikdy nepřepíšou.
* **samostatná aplikace** (PyInstaller) nainstalovaná do `<kořen>/versions/<verze>/` (`scripts/install_exe.ps1`):
  při startu přečte `latest.json` ze sdílené složky vydání (`update_dir` v nastavení nebo `<kořen>/update_source.txt`),
  po souhlasu zkopíruje a ověří ZIP (SHA-256), rozbalí ho vedle běžící verze, zapíše `<kořen>/current.txt` (čte ho
  spouštěč `EnvoCAD.cmd`) a spustí novou verzi.

Stav je v `~/.envocad/update.json`: odložená nabídka („Teď ne“ na 24 h), cíl čekající na `apply`, předchozí stav pro
`python -m envocad.updater rollback` a výsledek poslední aktualizace (GUI ho po startu oznámí).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from envocad import __version__

log = logging.getLogger("envocad.updater")

MAIN_BRANCH = "main"
TAG_PREFIX = "v"
SKIP_SECONDS = 24 * 3600          # „Teď ne“ = znovu se zeptat za den
GIT_TIMEOUT = 30
PIP_TIMEOUT = 20 * 60
MANIFEST = "latest.json"
SOURCE_FILE = "update_source.txt"  # sdílená složka vydání zapsaná instalátorem samostatné aplikace
CURRENT_FILE = "current.txt"
EXE_NAME = "EnvoCAD.exe" if sys.platform == "win32" else "EnvoCAD"
EXIT_ACCEPTED = 10                 # `check`: uživatel souhlasí, spouštěč má zavolat `apply`
MAX_NOTES = 6000

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_SECTION_RE = re.compile(r"^## +v?(\d+\.\d+\.\d+)\b.*$", re.MULTILINE)
_HEADING_RE = re.compile(r"^## ", re.MULTILINE)
_UNRELEASED_RE =re.compile(r"^## +Nevydáno *$", re.MULTILINE)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class UpdateError(Exception):
    """Aktualizace selhala – text je česky pro uživatele."""


@dataclass
class Offer:
    version: str          # „0.12.0“
    ref: str              # git tag (`v0.12.0`) nebo cesta k ZIPu samostatné aplikace
    notes: str = ""
    sha256: str = ""


# ---- verze a changelog ---------------------------------------------------------------------------------------------
def parse_version(text: str | None) -> tuple[int, int, int] | None:
    m = _VERSION_RE.match((text or "").strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def _ver(text: str | None) -> tuple[int, int, int]:
    return parse_version(text) or (0, 0, 0)


def changelog_sections(text: str) -> list[tuple[str, str]]:
    """Vydané sekce `## X.Y.Z …` z CHANGELOG.md jako [(verze, text sekce včetně nadpisu)] v pořadí souboru."""
    out = []
    for m in _SECTION_RE.finditer(text):
        nxt = _HEADING_RE.search(text, m.end())
        out.append((m[1], text[m.start():nxt.start() if nxt else len(text)].strip()))
    return out


def release_notes(changelog: str, after: str, upto: str | None = None) -> str:
    """Sekce changelogu novější než `after` (a nejvýš `upto`), zkrácené pro dialog."""
    lo, hi = _ver(after), _ver(upto) if upto else None
    parts = [s for v, s in changelog_sections(changelog) if _ver(v) > lo and (hi is None or _ver(v) <= hi)]
    notes = "\n\n".join(parts)
    return notes if len(notes) <= MAX_NOTES else notes[:MAX_NOTES].rstrip() + "\n…"


def cut_release(changelog: str, version: str, date: str) -> str:
    """Přejmenuje sekci „## Nevydáno“ na `## <verze> – <datum>` a nad ni přidá novou prázdnou „## Nevydáno“."""
    if parse_version(version) is None:
        raise ValueError(f"Neplatná verze {version!r} (očekávám X.Y.Z)")
    if any(v == version for v, _ in changelog_sections(changelog)):
        raise ValueError(f"CHANGELOG už sekci {version} má")
    m = _UNRELEASED_RE.search(changelog)
    if not m:
        raise ValueError("CHANGELOG nemá sekci „## Nevydáno“")
    return changelog[:m.start()] + f"## Nevydáno\n\n## {version} – {date}" + changelog[m.end():]


# ---- stav ----------------------------------------------------------------------------------------------------------
def state_path() -> Path:
    from envocad.library.store import home_dir
    return home_dir() / "update.json"


def load_state() -> dict:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    state_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def is_skipped(state: dict, version: str, now: float | None = None) -> bool:
    s = state.get("skip") or {}
    return s.get("version") == version and (now or time.time()) < float(s.get("until") or 0)


def remember_skip(state: dict, version: str, now: float | None = None) -> None:
    state["skip"] = {"version": version, "until": (now or time.time()) + SKIP_SECONDS}


def take_result() -> dict | None:
    """Výsledek poslední aktualizace pro GUI (jednorázově – po přečtení se smaže)."""
    state = load_state()
    res = state.pop("result", None)
    if res is not None:
        save_state(state)
    return res if isinstance(res, dict) else None


def enabled() -> bool:
    """Kontrola aktualizací zapnutá? Vypíná ji `auto_update: false` v nastavení nebo `ENVOCAD_NO_UPDATE=1`."""
    if os.environ.get("ENVOCAD_NO_UPDATE"):
        return False
    try:
        from envocad.settings import load_settings
        return bool(load_settings().get("auto_update", True))
    except Exception:  # noqa: BLE001 – poškozené nastavení nesmí zablokovat start
        return True


# ---- klon repozitáře -----------------------------------------------------------------------------------------------
def repo_root() -> Path | None:
    """Kořen git klonu, ze kterého běží program (None = instalace bez gitu nebo samostatná aplikace)."""
    if getattr(sys, "frozen", False):
        return None
    root = Path(__file__).resolve().parents[1]
    return root if (root / ".git").exists() and (root / "pyproject.toml").exists() else None


def _git_env() -> dict:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"     # bez dotazu na heslo v konzoli
    env["GCM_INTERACTIVE"] = "never"     # Git Credential Manager nesmí při startu otevřít přihlašovací okno
    return env


def _git_run(repo: Path, *args: str, timeout: float = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], check=False, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, env=_git_env(), creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as ex:
        raise UpdateError(f"git {args[0]} nejde spustit: {ex}") from ex


def git(repo: Path, *args: str, timeout: float = GIT_TIMEOUT) -> str:
    r = _git_run(repo, *args, timeout=timeout)
    if r.returncode:
        raise UpdateError(f"git {' '.join(args)}: {r.stderr.strip() or f'kód {r.returncode}'}")
    return r.stdout.strip()


def latest_tag(repo: Path) -> str | None:
    tags = [t for t in git(repo, "tag", "--list", f"{TAG_PREFIX}*").split() if parse_version(t)]
    return max(tags, key=_ver) if tags else None


def current_branch(repo: Path) -> str:
    """Jméno větve, prázdné = odpojená HEAD (typicky na tagu po aktualizaci)."""
    return _git_run(repo, "symbolic-ref", "-q", "--short", "HEAD").stdout.strip()


def git_offer(repo: Path, current: str = __version__) -> tuple[Offer | None, str]:
    """Nabídka aktualizace klonu na nejnovější tag, nebo (None, důvod) – z lokálních tagů, bez sítě."""
    tag = latest_tag(repo)
    if not tag:
        return None, "žádná vydaná verze"
    version = tag.removeprefix(TAG_PREFIX)
    if _ver(version) <= _ver(current):
        return None, f"aktuální ({current})"
    branch = current_branch(repo)
    if branch and branch != MAIN_BRANCH:
        return None, f"vývojová větev {branch}"
    if git(repo, "status", "--porcelain", "--untracked-files=no"):
        return None, "lokální změny v repozitáři"
    if _git_run(repo, "merge-base", "--is-ancestor", "HEAD", f"{tag}^{{commit}}").returncode:
        return None, f"HEAD obsahuje commity, které v {tag} nejsou (vývoj)"
    changelog = _git_run(repo, "show", f"{tag}:CHANGELOG.md").stdout
    return Offer(version, tag, release_notes(changelog, current, version)), ""


def background_fetch(repo: Path) -> None:
    """`git fetch --tags` na pozadí pro příští start; chyby (offline, přihlášení) se tiše ignorují."""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | _NO_WINDOW
    try:
        subprocess.Popen(["git", "-C", str(repo), "fetch", "--quiet", "--tags", "origin"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env=_git_env(), creationflags=flags, start_new_session=sys.platform != "win32")
    except OSError as ex:
        log.info("git fetch nejde spustit: %s", ex)


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def pip_install(repo: Path, python: str = sys.executable) -> None:
    try:
        r = subprocess.run([python, "-m", "pip", "install", "-q", "-e", str(repo)], check=False,
                           timeout=PIP_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as ex:
        raise UpdateError(f"pip nejde spustit: {ex}") from ex
    if r.returncode:
        raise UpdateError(f"instalace závislostí selhala (pip, kód {r.returncode})")


def _switch(repo: Path, branch: str, commit: str) -> None:
    if branch:
        git(repo, "switch", "--quiet", branch)
    else:
        git(repo, "switch", "--quiet", "--detach", commit)


def switch_to(repo: Path, tag: str, pip=pip_install) -> dict:
    """Přepne klon na `tag`, při změně `pyproject.toml` doinstaluje závislosti; při chybě vrátí původní stav.
    Vrací původní stav {"branch", "commit", "version"} pro návrat."""
    prev = {"branch": current_branch(repo), "commit": git(repo, "rev-parse", "HEAD"), "version": __version__}
    deps = _file_hash(repo / "pyproject.toml")
    git(repo, "switch", "--quiet", "--detach", tag)
    if _file_hash(repo / "pyproject.toml") != deps:
        try:
            pip(repo)
        except UpdateError:
            _switch(repo, prev["branch"], prev["commit"])
            raise
    return prev


def apply_pending(repo: Path, pip=pip_install) -> dict:
    """Provede aktualizaci odsouhlasenou v `check` (stav `pending`); výsledek uloží pro GUI a vrátí ho."""
    state = load_state()
    tag = state.pop("pending", None)
    if not tag:
        return {}
    try:
        prev = switch_to(repo, tag, pip)
        state["previous"] = prev
        result = {"ok": True, "version": tag.removeprefix(TAG_PREFIX), "from": prev["version"]}
    except UpdateError as ex:
        result = {"ok": False, "version": tag.removeprefix(TAG_PREFIX), "error": str(ex)}
    state["result"] = result
    save_state(state)
    return result


def rollback(repo: Path, pip=pip_install) -> dict:
    """Návrat na stav před poslední aktualizací (`python -m envocad.updater rollback`)."""
    state = load_state()
    prev = state.get("previous")
    if not isinstance(prev, dict) or not prev.get("commit"):
        raise UpdateError("Není uložena předchozí verze.")
    deps = _file_hash(repo / "pyproject.toml")
    _switch(repo, str(prev.get("branch") or ""), str(prev["commit"]))
    if _file_hash(repo / "pyproject.toml") != deps:
        pip(repo)
    state.pop("previous", None)
    state["skip"] = {"version": __version__, "until": time.time() + SKIP_SECONDS}   # neptat se hned znovu
    state["result"] = {"ok": True, "version": str(prev.get("version") or ""), "rollback": True}
    save_state(state)
    return state["result"]


def check(repo: Path, ask, fetch=background_fetch, now: float | None = None) -> bool:
    """Spouštěč před startem GUI: nabídne aktualizaci klonu. `ask(offer, current) -> bool`. True = odsouhlaseno,
    cíl uložen jako `pending` pro `apply_pending`."""
    accepted = False
    try:
        offer, why = git_offer(repo)
        if offer is None:
            log.info("aktualizace: %s", why)
            return False
        state = load_state()
        if is_skipped(state, offer.version, now):
            return False
        if ask(offer, __version__):
            state["pending"] = offer.ref
            accepted = True
        else:
            remember_skip(state, offer.version, now)
        save_state(state)
        return accepted
    finally:
        if not accepted:
            fetch(repo)


# ---- samostatná aplikace (PyInstaller) -----------------------------------------------------------------------------
def frozen_install_root() -> Path | None:
    """Kořen instalace `<kořen>/versions/<verze>/EnvoCAD.exe`; None = nejde o instalaci s verzemi."""
    if not getattr(sys, "frozen", False):
        return None
    d = Path(sys.executable).resolve().parent
    return d.parent.parent if d.parent.name == "versions" else None


def update_source(root: Path) -> Path | None:
    """Sdílená složka vydání: `update_dir` z nastavení, jinak `<kořen>/update_source.txt` z instalace."""
    d = ""
    try:
        from envocad.settings import load_settings
        d = str(load_settings().get("update_dir") or "")
    except Exception as ex:  # noqa: BLE001 – poškozené nastavení → složka z instalace
        log.info("nastavení nejde přečíst: %s", ex)
    if not d:
        try:
            d = (root / SOURCE_FILE).read_text(encoding="utf-8-sig").strip()
        except OSError:
            return None
    return Path(d) if d else None


def read_manifest(source: Path) -> dict:
    data = json.loads((source / MANIFEST).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or parse_version(str(data.get("version"))) is None:
        raise UpdateError(f"{MANIFEST}: chybí platná verze")
    name = str(data.get("zip") or "")
    if not name or Path(name).name != name or name in (".", ".."):
        raise UpdateError(f"{MANIFEST}: neplatné jméno ZIPu {name!r}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(data.get("sha256") or "")):
        raise UpdateError(f"{MANIFEST}: chybí SHA-256")
    return data


def make_manifest(version: str, zip_path: Path, changelog: str) -> dict:
    """`latest.json` pro sdílenou složku: verze, ZIP, SHA-256 a sekce changelogu (dialog si vybere novější)."""
    return {"version": version, "zip": zip_path.name, "sha256": sha256_file(zip_path),
            "sections": dict(changelog_sections(changelog)[:20])}


def exe_offer(source: Path, current: str = __version__) -> Offer | None:
    m = read_manifest(source)
    version = str(m["version"])
    if _ver(version) <= _ver(current):
        return None
    sections = m.get("sections") if isinstance(m.get("sections"), dict) else {}
    parts = [str(t) for v, t in sections.items() if _ver(current) < _ver(v) <= _ver(version)]
    notes = "\n\n".join(parts)[:MAX_NOTES]
    return Offer(version, str(source / m["zip"]), notes, str(m["sha256"]))


def call_with_timeout(fn, timeout: float):
    """Zavolá `fn()` ve vlákně; po `timeout` s vrátí None (nedostupný síťový disk umí blokovat desítky sekund)."""
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except Exception as ex:  # noqa: BLE001 – chyba se jen zaloguje, start pokračuje
            box["error"] = ex

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if "error" in box:
        log.info("aktualizace: %s", box["error"])
    return box.get("value")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy(src: Path, dst: Path, progress=None) -> str:
    """Kopie po blocích se SHA-256; `progress(hotovo, celkem)` vrátí False = zrušit."""
    total = src.stat().st_size
    h, done = hashlib.sha256(), 0
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        for chunk in iter(lambda: fi.read(1 << 20), b""):
            fo.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress is not None and progress(done, total) is False:
                raise UpdateError("Aktualizace zrušena.")
    return h.hexdigest()


def _remove_dir(path: Path) -> None:
    """Smaže starou verzi; běžící verzi (zamčené soubory) nechá být – přejmenování ji odhalí dřív než mazání."""
    trash = path.with_name(path.name + ".del")
    try:
        path.rename(trash)
    except OSError:
        return
    shutil.rmtree(trash, ignore_errors=True)


def install_version(root: Path, offer: Offer, progress=None, keep: tuple[str, ...] = ()) -> Path:
    """Zkopíruje a ověří ZIP, rozbalí do `<kořen>/versions/<verze>`, přepne `current.txt`; staré verze kromě `keep`
    smaže. Vrací cestu k nové spustitelné aplikaci."""
    versions = root / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    target = versions / offer.version
    if not (target / EXE_NAME).exists():
        part = versions / f"{offer.version}.zip.part"
        tmp = versions / f"{offer.version}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            try:
                digest = _copy(Path(offer.ref), part, progress)
            except OSError as ex:
                raise UpdateError(f"Novou verzi nejde zkopírovat: {ex}") from ex
            if offer.sha256 and digest != offer.sha256:
                raise UpdateError("Stažený soubor je poškozený (nesouhlasí SHA-256).")
            try:
                with zipfile.ZipFile(part) as z:
                    z.extractall(tmp)      # extractall odstraní absolutní cesty a „..“
            except (OSError, zipfile.BadZipFile) as ex:
                raise UpdateError(f"Novou verzi nejde rozbalit: {ex}") from ex
            if not (tmp / EXE_NAME).exists():
                raise UpdateError(f"V balíčku chybí {EXE_NAME}.")
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            tmp.rename(target)
        finally:
            part.unlink(missing_ok=True)
            shutil.rmtree(tmp, ignore_errors=True)
    (root / CURRENT_FILE).write_text(offer.version, encoding="ascii")
    for d in versions.iterdir():
        if d.is_dir() and d.name not in {offer.version, *keep}:
            _remove_dir(d)
    return target / EXE_NAME


def launch(exe: Path, args: list[str]) -> None:
    flags = subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0
    subprocess.Popen([str(exe), *args], cwd=str(exe.parent), creationflags=flags,
                     start_new_session=sys.platform != "win32")


# ---- příkazová řádka spouštěče -------------------------------------------------------------------------------------
def _setup_log() -> None:
    from envocad.logging_setup import log_dir
    h = logging.FileHandler(log_dir() / "update.log", encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "check"
    try:
        _setup_log()
    except OSError:
        pass
    repo = repo_root()
    if repo is None:
        if cmd != "check":
            print("EnvoCAD neběží z git klonu – aktualizace přes git nejsou k dispozici.")
            return 1
        return 0
    try:
        if cmd == "check":
            if not enabled():
                return 0
            from envocad.ui.update_prompt import ask_update
            return EXIT_ACCEPTED if check(repo, ask_update) else 0
        if cmd == "apply":
            res = apply_pending(repo)
            if res:
                print(f"EnvoCAD aktualizován na {res['version']}." if res["ok"]
                      else f"Aktualizace na {res['version']} selhala: {res['error']}")
            return 0
        if cmd == "rollback":
            res = rollback(repo)
            print(f"EnvoCAD vrácen na verzi {res['version']}.")
            return 0
        if cmd == "status":
            offer, why = git_offer(repo)
            print(f"Běží {__version__}; " + (f"k dispozici {offer.version}" if offer else why))
            return 0
    except UpdateError as ex:
        log.warning("aktualizace (%s): %s", cmd, ex)
        print(f"Aktualizace: {ex}")
        return 1
    except Exception:  # chyba aktualizace nesmí zabránit startu programu
        log.exception("aktualizace (%s) spadla", cmd)
        return 1
    print("Použití: python -m envocad.updater [check|apply|rollback|status]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
