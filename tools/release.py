"""Vydání verze EnvoCAD (postup v docs/RELEASE.md).

    python tools/release.py prepare 0.12.0      # verze v pyproject.toml + envocad/__init__.py, sekce v CHANGELOG.md
    python tools/release.py tag                 # ověří main = origin/main, testy, vytvoří a pushne tag v0.12.0
    python tools/release.py publish \\\\server\\envocad\\release
                                                # z tagu postaví samostatnou aplikaci a nahraje ji do sdílené složky

Klony repozitáře si novou verzi nabídnou podle tagu (`envocad/updater.py`), samostatná aplikace podle
`latest.json` ve sdílené složce.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from envocad import updater

PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "envocad" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"


def die(msg: str) -> None:
    print(f"CHYBA: {msg}", file=sys.stderr)
    sys.exit(1)


def sh(*args: str, check: bool = True) -> str:
    r = subprocess.run(args, check=False, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode:
        die(f"{' '.join(args)}\n{r.stdout}{r.stderr}")
    return r.stdout.strip()


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write(p: Path, text: str) -> None:
    p.write_text(text, encoding="utf-8", newline="\n")


def project_version() -> str:
    m = re.search(r'^version = "([^"]+)"', read(PYPROJECT), re.MULTILINE)
    return m[1] if m else ""


def init_version() -> str:
    m = re.search(r'^__version__ = "([^"]+)"', read(INIT), re.MULTILINE)
    return m[1] if m else ""


def cmd_prepare(version: str) -> None:
    if updater.parse_version(version) is None:
        die(f"neplatná verze {version!r} (očekávám X.Y.Z)")
    cur = project_version()
    if updater.parse_version(version) <= (updater.parse_version(cur) or (0, 0, 0)):
        die(f"verze {version} není vyšší než současná {cur}")
    try:
        changelog = updater.cut_release(read(CHANGELOG), version, dt.date.today().isoformat())
    except ValueError as ex:
        die(str(ex))
    write(CHANGELOG, changelog)
    write(PYPROJECT, re.sub(r'^version = "[^"]+"', f'version = "{version}"', read(PYPROJECT), count=1,
                            flags=re.MULTILINE))
    write(INIT, re.sub(r'^__version__ = "[^"]+"', f'__version__ = "{version}"', read(INIT), count=1,
                       flags=re.MULTILINE))
    print(f"Připraveno {version}: pyproject.toml, envocad/__init__.py, CHANGELOG.md.\n"
          f"Zkontroluj CHANGELOG, commitni („Vydání {version}“), dostaň do main (PR) a pak: "
          "python tools/release.py tag")


def _check_main_clean() -> None:
    if sh("git", "symbolic-ref", "-q", "--short", "HEAD", check=False) != "main":
        die("vydává se z větve main (git switch main && git pull)")
    if sh("git", "status", "--porcelain", "--untracked-files=no"):
        die("pracovní strom má necommitnuté změny")
    sh("git", "fetch", "--quiet", "--tags", "origin")
    if sh("git", "rev-parse", "HEAD") != sh("git", "rev-parse", "origin/main"):
        die("main není shodný s origin/main (git pull / git push)")


def cmd_tag(skip_tests: bool) -> None:
    _check_main_clean()
    version = project_version()
    if version != init_version():
        die(f"verze se liší: pyproject.toml {version}, envocad/__init__.py {init_version()}")
    if not any(v == version for v, _ in updater.changelog_sections(read(CHANGELOG))):
        die(f"CHANGELOG.md nemá sekci ## {version} (python tools/release.py prepare {version})")
    tag = f"{updater.TAG_PREFIX}{version}"
    if sh("git", "tag", "--list", tag):
        die(f"tag {tag} už existuje")
    latest = updater.latest_tag(ROOT)
    if latest and updater.parse_version(latest) >= updater.parse_version(version):
        die(f"poslední vydaná verze je {latest}, {version} není vyšší")
    if not skip_tests:
        print("pytest…")
        if subprocess.run([sys.executable, "-m", "pytest", "-q", "-x"], check=False, cwd=ROOT).returncode:
            die("pytest neprošel")
        print("ruff…")
        if subprocess.run([sys.executable, "-m", "ruff", "check", "."], check=False, cwd=ROOT).returncode:
            die("ruff hlásí chyby")
    sh("git", "tag", "-a", tag, "-m", f"EnvoCAD {version}")
    sh("git", "push", "origin", tag)
    print(f"Vydáno {tag}. Klony repozitáře ho nabídnou při druhém startu (první start tag stáhne na pozadí).\n"
          "Samostatná aplikace: python tools/release.py publish <sdílená složka>")


def cmd_publish(dest: Path, skip_build: bool) -> None:
    version = project_version()
    tag = f"{updater.TAG_PREFIX}{version}"
    if sh("git", "status", "--porcelain", "--untracked-files=no"):
        die("pracovní strom má necommitnuté změny")
    if sh("git", "rev-parse", "HEAD") != sh("git", "rev-parse", f"{tag}^{{commit}}", check=False):
        die(f"HEAD není na tagu {tag} (python tools/release.py tag, nebo git switch --detach {tag})")
    if not dest.is_dir():
        die(f"sdílená složka {dest} neexistuje")
    dist = ROOT / "dist" / "EnvoCAD"
    build = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "envocad.spec"]
    if not skip_build and subprocess.run(build, check=False, cwd=ROOT).returncode:
        die("PyInstaller selhal")
    if not (dist / updater.EXE_NAME).exists():
        die(f"chybí {dist / updater.EXE_NAME}")
    zip_path = ROOT / "dist" / f"EnvoCAD-{version}.zip"
    print(f"Balím {zip_path.name}…")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(dist.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(dist).as_posix())
    manifest = updater.make_manifest(version, zip_path, read(CHANGELOG))
    print(f"Kopíruji do {dest}…")
    shutil.copy2(zip_path, dest / zip_path.name)
    for name in ("install_exe.ps1", "install_exe.cmd"):
        shutil.copy2(ROOT / "scripts" / name, dest / ("Instalovat EnvoCAD.cmd" if name.endswith(".cmd") else name))
    # latest.json až nakonec – dokud ZIP není celý zkopírovaný, aplikace novou verzi nevidí
    tmp = dest / (updater.MANIFEST + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(dest / updater.MANIFEST)
    print(f"Publikováno EnvoCAD {version} do {dest}. Nová instalace: „Instalovat EnvoCAD.cmd“ ze sdílené složky.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Vydání verze EnvoCAD (docs/RELEASE.md)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="zvedne verzi a uzavře sekci Nevydáno v CHANGELOG.md")
    p.add_argument("version")
    p = sub.add_parser("tag", help="otaguje main a pushne tag")
    p.add_argument("--skip-tests", action="store_true")
    p = sub.add_parser("publish", help="samostatná aplikace do sdílené složky")
    p.add_argument("dest", type=Path)
    p.add_argument("--skip-build", action="store_true", help="použít existující dist/EnvoCAD")
    a = ap.parse_args()
    if a.cmd == "prepare":
        cmd_prepare(a.version)
    elif a.cmd == "tag":
        cmd_tag(a.skip_tests)
    else:
        cmd_publish(a.dest, a.skip_build)


if __name__ == "__main__":
    main()
