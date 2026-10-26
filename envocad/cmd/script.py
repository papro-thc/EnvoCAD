"""Skripty příkazového řádku `.ecs` (bez Qt): UTF-8 text, řádek = příkaz, `#` na začátku řádku = komentář,
prázdné řádky se přeskočí, `${name}` = textové dosazení proměnné. Nic se nespouští jako kód – každý řádek jde přes
registr příkazů (neznámé slovo = „Neznámý příkaz“). Vnoření `SCRIPT` nejvýš `MAX_DEPTH`."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from envocad.cmd.parse import ParseError, substitute_vars
from envocad.cmd.runner import CommandError, CommandRunner, Result

MAX_DEPTH = 4
MAX_SCRIPT_BYTES = 1_000_000


@dataclass
class LineResult:
    line: int
    text: str
    result: Result
    source: str = ""                  # název skriptu (u vnořených)

    def to_json(self) -> dict:
        r = self.result
        d = {"line": self.line, "cmd": r.cmd, "ok": r.ok, "messages": list(r.messages),
             "changed_sheets": r.changed_sheets}
        if r.data is not None:
            d["data"] = r.data
        return d


@dataclass
class ScriptReport:
    lines: list[LineResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(x.result.ok for x in self.lines)

    @property
    def count(self) -> int:
        return len(self.lines)

    @property
    def errors(self) -> list[str]:
        return [f"řádek {x.line}: {x.result.error}" for x in self.lines if not x.result.ok]

    @property
    def first_error(self) -> str | None:
        e = self.errors
        return e[0] if e else None


def script_lines(text: str) -> Iterator[tuple[int, str]]:
    """(číslo řádku od 1, řádek) bez komentářů a prázdných řádků."""
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line and not line.startswith("#"):
            yield no, line


def run_script(runner: CommandRunner, text: str, *, name: str = "", base_dir: Path | None = None,
               variables: dict[str, str] | None = None, stop_on_error: bool = True,
               on_result: Callable[[LineResult], None] | None = None) -> ScriptReport:
    """Vykoná skript řádek po řádku přes `runner.execute`. Každý řádek je samostatná transakce (a krok historie).
    Chyba → `ScriptReport` s číslem řádku; `stop_on_error` = konec při první chybě. Hlavní skript (hloubka 0)
    nastaví kořen pro vnořené `SCRIPT` (`runner.script_root`) a rozpočet řádků `runner.max_commands` i s vnořenými –
    po jeho vyčerpání `CommandError` ukončí celý běh (i s `--keep-going`)."""
    if runner.script_depth >= MAX_DEPTH:
        raise CommandError(f"Skripty lze vnořit nejvýš {MAX_DEPTH}×")
    rep = ScriptReport()
    old_dir = runner.ctx.base_dir
    old_vars = getattr(runner, "variables", {})
    old_root = runner.script_root
    runner.variables = {**old_vars, **(variables or {})}
    if base_dir is not None:
        runner.ctx.base_dir = base_dir
    if runner.script_depth == 0:
        runner.commands_run = runner.exports_run = 0
        runner.exported = set()
        runner.script_root = runner.ctx.base_dir
    runner.script_depth += 1
    try:
        for no, line in script_lines(text):
            runner.commands_run += 1
            if runner.commands_run > runner.max_commands:
                raise CommandError(f"Skript přesáhl {runner.max_commands} příkazů i s vnořenými – přerušeno")
            try:
                res = runner.execute(substitute_vars(line, runner.variables))
            except (ParseError, CommandError) as ex:
                res = Result(False, line.split()[0], [str(ex)], None, str(ex))
            lr = LineResult(no, line, res, name)
            rep.lines.append(lr)
            if on_result is not None:
                on_result(lr)
            if not res.ok and stop_on_error:
                break
    finally:
        runner.script_depth -= 1
        runner.ctx.base_dir = old_dir
        runner.variables = old_vars
        runner.script_root = old_root
    return rep


def read_script(path: Path | str) -> str:
    """Text skriptu (UTF-8, BOM se zahodí); větší než `MAX_SCRIPT_BYTES` → OSError."""
    p = Path(path)
    if p.stat().st_size > MAX_SCRIPT_BYTES:
        raise OSError(f"skript je větší než {MAX_SCRIPT_BYTES // 1_000_000} MB")
    return p.read_text(encoding="utf-8-sig")


def run_script_file(runner: CommandRunner, path: Path | str, **kw) -> ScriptReport:
    p = Path(path)
    try:
        text = read_script(p)
    except OSError as ex:
        raise CommandError(f"Skript {p} nelze načíst: {ex.strerror or ex}") from ex
    except UnicodeDecodeError as ex:
        raise CommandError(f"Skript {p} není v UTF-8") from ex
    return run_script(runner, text, name=p.name, base_dir=p.parent, **kw)
