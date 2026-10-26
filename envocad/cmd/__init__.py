"""Příkazový řádek EnvoCAD (styl ZWCAD) – jádro bez Qt pro GUI, CLI, skripty, agenty a pluginy.

Návrh `docs/design/prikazovy_radek.md`. Moduly: `registry` (CommandDef, Param, Registry, aliasy), `parse` (tokeny,
body), `runner` (CommandRunner, Session, ChangeSet, Journal), `edits` (změny modelu), `builtin` (vestavěné příkazy,
`default_registry`), `script` (.ecs), `__main__` (CLI).
"""
from envocad.cmd.builtin import default_registry
from envocad.cmd.registry import CommandDef, Param, Prompt, Registry
from envocad.cmd.runner import (
    ChangeSet,
    CommandError,
    CommandRunner,
    Ctx,
    Journal,
    Result,
    SaveOptions,
    Session,
    sync_derived,
)
from envocad.cmd.script import run_script, run_script_file

__all__ = [
    "ChangeSet", "CommandDef", "CommandError", "CommandRunner", "Ctx", "Journal", "Param", "Prompt", "Registry",
    "Result", "SaveOptions", "Session", "default_registry", "run_script", "run_script_file", "sync_derived",
]
