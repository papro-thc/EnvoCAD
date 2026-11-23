"""CLI příkazového řádku: `python -m envocad.cmd projekt.ecp skript.ecs [-o výstup.ecp [--force] | --in-place]
[--dry-run] [--json] [--keep-going] [--no-user-aliases] [--plugins] [--var name=value …]`. Skript `-` = ze stdin.
Exporty (EXPORT_DXF, EXPORT_PDF, DOC_PDF) jen do složky skriptu; příkazy pluginů jen s `--plugins` (plugin je kód).
Vstup i výstup je vždy UTF-8 (i v rouře na Windows), SAVE ve skriptu jen potvrdí cíl – zapisuje se až na konci.

Bez `-o` / `--in-place` se nic neuloží (bezpečný výchozí stav pro agenty). Kód návratu 0 = vše v pořádku,
1 = chyba příkazu, 2 = chybné použití (argumenty, soubor projektu / skriptu). Při první chybě konec bez uložení,
`--keep-going` pokračuje (a uloží). Před uložením se dopočtou odvozená data (kabely, vazby přívodů) a výstup
dostane souhrn kontroly F7.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

USAGE_ERROR, COMMAND_ERROR = 2, 1


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m envocad.cmd",
                                 description="Spustí skript příkazového řádku EnvoCAD (.ecs) nad projektem (.ecp).")
    ap.add_argument("project", help="projekt .ecp")
    ap.add_argument("script", help="skript .ecs („-“ = stdin)")
    out = ap.add_mutually_exclusive_group()
    out.add_argument("-o", "--output", help="uložit výsledek do souboru (jinak se nic neukládá)")
    out.add_argument("--in-place", action="store_true", help="uložit zpět do projektu (záloha .ecp.bak)")
    ap.add_argument("--dry-run", action="store_true", help="jen vykonat a vypsat, nic neukládat")
    ap.add_argument("--json", action="store_true", help="řádek JSON na příkaz (line, cmd, ok, messages, "
                                                         "changed_sheets) a nakonec souhrn")
    ap.add_argument("--keep-going", action="store_true", help="po chybě pokračovat dalším řádkem")
    ap.add_argument("--force", action="store_true", help="s -o přepsat existující soubor; exporty skriptu smí přepsat existující PDF / DXF")
    ap.add_argument("--no-user-aliases", action="store_true",
                    help="bez uživatelských aliasů ~/.envocad/aliases.json (stejné chování na každém stroji)")
    ap.add_argument("--plugins", action="store_true",
                    help="načíst pluginy ~/.envocad/plugins (jejich příkazy; plugin běží s právy uživatele)")
    ap.add_argument("--var", action="append", default=[], metavar="NAME=VALUE", help="proměnná ${NAME} ve skriptu")
    return ap


_CONTROL = {c: None for c in [*range(0x09), *range(0x0A, 0x20), 0x7F]}   # bez tabulátoru


def _emit(obj, as_json: bool, err: bool = False) -> None:
    """Řádek výstupu. Text mimo JSON bez řídicích znaků (ESC sekvence z hodnot atributů by ovládaly terminál)."""
    stream = sys.stderr if err and not as_json else sys.stdout
    print(json.dumps(obj, ensure_ascii=False) if as_json else str(obj).translate(_CONTROL), file=stream, flush=True)


def _utf8_streams() -> None:
    """Roura na Windows je jinak v kódové stránce (cp1250) – „→“ ve výstupu by shodil běh."""
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _utf8_streams()
    ap = _parser()
    try:
        a = ap.parse_args(argv)
    except SystemExit as ex:
        return int(ex.code or 0) and USAGE_ERROR
    variables = {}
    for v in a.var:
        name, sep, value = v.partition("=")
        if not sep or not name.isidentifier():
            print(f"chybná proměnná „{v}“ (NAME=VALUE)", file=sys.stderr)
            return USAGE_ERROR
        variables[name] = value

    from envocad.cmd.runner import CommandError, CommandRunner, Journal, SaveOptions, sync_derived
    from envocad.cmd.script import read_script, run_script
    from envocad.model.project import Project, sync_cables, sync_feed_links

    proj_path = Path(a.project)
    try:
        project = Project.load(proj_path)
    except (OSError, ValueError) as ex:
        print(f"Projekt {proj_path} nelze otevřít: {ex}", file=sys.stderr)
        return USAGE_ERROR
    try:
        if a.script == "-":
            from envocad.cmd.script import MAX_SCRIPT_BYTES
            raw = sys.stdin.buffer.read(MAX_SCRIPT_BYTES + 1)
            if len(raw) > MAX_SCRIPT_BYTES:
                raise OSError(f"skript je větší než {MAX_SCRIPT_BYTES // 1_000_000} MB")
            text, base = raw.decode("utf-8-sig"), Path.cwd()
        else:
            text, base = read_script(a.script), Path(a.script).resolve().parent
    except (OSError, UnicodeDecodeError) as ex:
        print(f"Skript {a.script} nelze načíst: {ex}", file=sys.stderr)
        return USAGE_ERROR

    target = Path(a.output) if a.output else (proj_path if a.in_place else None)
    if a.output and target.exists() and target.resolve() != proj_path.resolve() and not a.force:
        print(f"Soubor {target} existuje – přepis jen s --force", file=sys.stderr)
        return USAGE_ERROR
    save = SaveOptions(target=target, allow=target is not None and not a.dry_run, overwrite=a.force,
                       dry_run=a.dry_run, deferred=True)
    from envocad.cmd.builtin import default_registry
    from envocad.library.store import LibrarySchemaError, LibraryStore
    try:
        lib = LibraryStore()
    except LibrarySchemaError as ex:
        print(f"Knihovnu nelze otevřít: {ex}", file=sys.stderr)
        return COMMAND_ERROR
    sync_feed_links(project)               # jako otevření v GUI
    sync_cables(project)
    registry = default_registry(user_aliases=not a.no_user_aliases)
    if a.plugins:
        from envocad.plugins import failed_message, load_plugins, register_plugin_commands
        plugins = load_plugins(lib)
        for w in [failed_message(plugins)] + register_plugin_commands(plugins, registry):
            if w:
                print(w, file=sys.stderr)
    runner = CommandRunner(project, lib, registry, journal=Journal(), on_change=sync_derived, base_dir=base,
                           save=save)

    def on_result(lr) -> None:
        if a.json:
            _emit(lr.to_json(), True)
            return
        r = lr.result
        for m in r.messages if r.ok else r.messages[:-1]:
            _emit(m, False)
        if not r.ok:
            _emit(f"řádek {lr.line}: {r.error}", False, err=True)

    try:
        rep = run_script(runner, text, name=Path(a.script).name, variables=variables,
                         stop_on_error=not a.keep_going, on_result=on_result)
    except CommandError as ex:
        print(str(ex), file=sys.stderr)
        return COMMAND_ERROR
    failed = not rep.ok
    saved = None
    from envocad.model.checks import check_project
    from envocad.settings import switchboard_paper
    if not failed or a.keep_going:
        sync_derived(project)
        if target is not None and not a.dry_run:
            try:
                project.save(target)
                saved = str(target)
            except OSError as ex:
                print(f"Uložení do {target} selhalo: {ex}", file=sys.stderr)
                return COMMAND_ERROR
    counts = Counter(f.severity for f in check_project(project, lib, standard_paper=switchboard_paper()))
    if a.json:
        _emit({"summary": {"ok": not failed, "commands": rep.count, "errors": rep.errors, "saved": saved,
                           "checks": dict(counts)}}, True)
    else:
        chk = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "bez nálezů"
        _emit(f"Kontrola F7: {chk}", False)
        if saved:
            _emit(f"Uloženo: {saved}", False)
        elif failed and target is not None:
            _emit("Chyba – neuloženo", False, err=True)
        elif target is None:
            _emit("Neuloženo (bez -o / --in-place)", False)
        elif a.dry_run:
            _emit(f"--dry-run: neuloženo ({target})", False)
    return COMMAND_ERROR if failed else 0


if __name__ == "__main__":
    sys.exit(main())
