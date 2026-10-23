"""Vykonavatel příkazů (bez Qt): příkaz = generátor výzev, běh v transakci, výsledek s `ChangeSet`.

Jeden průběh příkazu = `Session`. Hodnoty výzev dodá řádek (tokeny za jménem příkazu), v GUI pak klávesnice nebo
klik (`Session.send` / `Session.send_value`). Před během se uloží `sheets_state`, po něm se porovná; změna je
`ChangeSet` (jen změněné listy + registr struktur). Chyba nebo zrušení uprostřed → stav „před“ se vrátí, nic
nezůstane. GUI (fáze 2) pushne `ChangeSet` jako `SheetsStateCommand(project, cs.before, cs.after, cs.label)` – první
redo nic nemění; headless drží historii `Journal` (UNDO/REDO ve skriptu).
"""
from __future__ import annotations

import contextlib
import copy
import fnmatch
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from envocad.cmd import parse
from envocad.cmd.parse import ParseError
from envocad.cmd.registry import CommandDef, Param, Registry, norm
from envocad.model.project import (
    Element,
    Project,
    Sheet,
    Wire,
    element_symbol,
    restore_sheets_state,
    sheets_state,
)

log = logging.getLogger("envocad.cmd")
PORT_SNAP_MM = 2.5           # bod výzvy „port“ = nejbližší port do této vzdálenosti
MAX_COMMANDS = 10_000        # řádků skriptu celkem i s vnořenými SCRIPT (ochrana před větvením a → b → c …)
_NOTHING = object()


class CommandError(Exception):
    """Chyba příkazu (česká hláška). Transakce se vrátí."""


class MissingArgument(CommandError):
    def __init__(self, cmd: str, prompt: Param):
        super().__init__(f"{cmd.upper()} – chybí {prompt.prompt.rstrip(':').strip()}")
        self.prompt = prompt


class Cancelled(CommandError):
    def __init__(self, cmd: str = ""):
        super().__init__(f"{cmd.upper()} zrušen" if cmd else "Zrušeno")


# ---- změny a historie --------------------------------------------------------------------------------------------
@dataclass
class ChangeSet:
    """Změna modelu jedním příkazem: `before` / `after` ve tvaru `sheets_state`, jen změněné listy (+ registr
    struktur celý). `restore_sheets_state(project, cs.before)` změnu vrátí, `cs.after` zopakuje."""
    label: str
    before: dict
    after: dict

    @property
    def changed_sheets(self) -> list[str]:
        return sorted(self.after["sheets"])

    @classmethod
    def between(cls, label: str, before: dict, after: dict) -> ChangeSet | None:
        changed = [sid for sid, d in after["sheets"].items() if before["sheets"].get(sid) != d]
        if not changed and before["structures"] == after["structures"]:
            return None
        return cls(label,
                   {"sheets": {sid: copy.deepcopy(before["sheets"][sid]) for sid in changed if sid in before["sheets"]},
                    "structures": copy.deepcopy(before["structures"])},
                   {"sheets": {sid: copy.deepcopy(after["sheets"][sid]) for sid in changed},
                    "structures": copy.deepcopy(after["structures"])})


@dataclass
class Journal:
    """Headless historie změn (GUI místo ní používá QUndoStack)."""
    done: list[ChangeSet] = field(default_factory=list)
    undone: list[ChangeSet] = field(default_factory=list)

    def push(self, cs: ChangeSet) -> None:
        self.done.append(cs)
        self.undone.clear()

    def undo(self, project: Project) -> ChangeSet | None:
        if not self.done:
            return None
        cs = self.done.pop()
        restore_sheets_state(project, cs.before)
        self.undone.append(cs)
        return cs

    def redo(self, project: Project) -> ChangeSet | None:
        if not self.undone:
            return None
        cs = self.undone.pop()
        restore_sheets_state(project, cs.after)
        self.done.append(cs)
        return cs


@dataclass
class SaveOptions:
    """Kam smí příkaz SAVE zapisovat (CLI: `-o` / `--in-place`; bez nich se neukládá – rozhodnutí 4)."""
    target: Path | None = None        # SAVE bez cesty
    allow: bool = False               # zápis povolen (bez -o / --in-place ne)
    overwrite: bool = False           # přepis existujícího jiného souboru
    dry_run: bool = False
    deferred: bool = False            # CLI: ukládá se jen na konci skriptu do `target`; SAVE uprostřed nic nezapíše


# ---- kontext příkazu ---------------------------------------------------------------------------------------------
@dataclass
class Ctx:
    project: Project
    library: Any
    sheet: Sheet | None
    selection: list[str]
    log: Callable[[str], None]
    runner: CommandRunner | None = None
    last_point: tuple[float, float] | None = None
    base_dir: Path | None = None
    data: Any = None                   # strukturovaný výstup příkazu (CHECKS → nálezy) pro --json

    # -- pomocné dotazy pro příkazy (bez Qt) --
    def require_end(self) -> None:
        """Příkaz s vedlejším účinkem mimo transakci (UNDO, SAVE, SCRIPT): nadbytečné argumenty ohlásit dřív, než
        se něco stane (jinak by se kontrolovaly až po provedení)."""
        s = self.runner._active if self.runner is not None else None
        if s is not None and s.tokens:
            raise CommandError(f"{s.cmd.name.upper()} – nadbytečné argumenty: {' '.join(s.tokens)}")

    def require_sheet(self) -> Sheet:
        if self.sheet is None or self.sheet not in self.project.sheets:
            raise CommandError("Žádný aktivní list (SHEET)")
        return self.sheet

    def symbol_of(self, e: Element):
        try:
            return element_symbol(self.project, e, self.library)
        except Exception:  # noqa: BLE001 – dotaz pro doplňování / výběr nesmí shodit příkaz
            return None

    def selected_elements(self) -> list[Element]:
        s = self.sheet
        if s is None:
            return []
        ids = set(self.selection)
        return [e for e in s.elements if e.id in ids]

    def selected_wires(self) -> list[Wire]:
        s = self.sheet
        if s is None:
            return []
        ids = set(self.selection)
        return [w for w in s.wires if w.id in ids]

    def find_refs(self, patterns: list[str]) -> list[str]:
        """Id prvků a vodičů aktivního listu podle označení / globu (F1, Q*, RFVE.AC); nic nenalezeno → chyba."""
        s = self.require_sheet()
        out: list[str] = []
        for pat in patterns:
            hit = [e.id for e in s.elements if e.ref and fnmatch.fnmatchcase(e.ref, pat)]
            hit += [w.id for w in s.wires if w.attrs.get("ref") and fnmatch.fnmatchcase(w.attrs["ref"], pat)]
            if not hit:
                raise CommandError(f"„{pat}“ na listu „{s.name}“ není")
            out += [h for h in hit if h not in out]
        return out

    def port_position(self, ref: str, port: str) -> tuple[Element, str, tuple[float, float]]:
        s = self.require_sheet()
        cands = [e for e in s.elements if e.ref == ref]
        if not cands:
            raise CommandError(f"Prvek {ref} na listu „{s.name}“ není")
        for e in cands:
            sym = self.symbol_of(e)
            if sym is not None and any(p.name == port for p in sym.ports):
                return e, port, e.port_pos(sym, port)
        raise CommandError(f"{ref} nemá port {port}")

    def nearest_port(self, x: float, y: float, tol: float = PORT_SNAP_MM) -> tuple[Element, str] | None:
        s = self.require_sheet()
        best = None
        for e in s.elements:
            sym = self.symbol_of(e)
            if sym is None:
                continue
            for p in sym.ports:
                px, py = e.port_pos(sym, p.name)
                d = abs(px - x) + abs(py - y)
                if d <= tol + 1e-9 and (best is None or d < best[0]):
                    best = (d, e, p.name)
        return (best[1], best[2]) if best else None


# ---- výsledek a průběh -------------------------------------------------------------------------------------------
@dataclass
class Result:
    ok: bool
    cmd: str
    messages: list[str] = field(default_factory=list)
    changeset: ChangeSet | None = None
    error: str | None = None
    data: Any = None

    @property
    def changed_sheets(self) -> list[str]:
        return self.changeset.changed_sheets if self.changeset else []


class Session:
    """Jeden běh příkazu. Neinteraktivně (`interactive=False`) musí argumenty pokrýt všechny povinné výzvy
    (jinak `MissingArgument`); interaktivně čeká na `send` / `send_value` a `prompt` je aktuální výzva."""

    def __init__(self, runner: CommandRunner, cmd: CommandDef, tokens: list[str], interactive: bool):
        self.runner, self.cmd, self.tokens, self.interactive = runner, cmd, list(tokens), interactive
        self.prompt: Param | None = None
        self.result: Result | None = None
        self.messages: list[str] = []
        ctx = runner.ctx
        self._before = sheets_state(runner.project) if cmd.transaction else None
        self._waiting = False                    # čeká na vstup z GUI
        self._clean = True                       # příkaz zatím model neměnil (mění až po poslední výzvě)
        self._sel_before = list(ctx.selection)
        self._sheet_before = ctx.sheet
        self._gen = None
        self.parent = runner._active             # vnější příkaz (SCRIPT), jeho výstup dostane i hlášky tohoto
        runner._active = self
        ctx.data = None
        try:
            gen = cmd.run(ctx)
            if inspect.isgenerator(gen):
                self._gen = gen
                self._step(_NOTHING)
            else:                                    # příkaz bez výzev může být obyčejná funkce
                self._gen = None
                self._finish(gen)
        except Exception as ex:  # noqa: BLE001 – chyba příkazu se vrátí jako výsledek, transakce se vrátí
            self._fail(ex)

    @property
    def done(self) -> bool:
        return self.result is not None

    # -- vstup --
    def send(self, text: str) -> None:
        """Text z klávesnice pro aktuální výzvu (prázdný = Enter: volitelná výzva → výchozí hodnota, výběr →
        aktuální výběr)."""
        if self.done:
            return
        self._resume()
        try:
            toks = parse.tokenize(text)
            if not toks:
                self._step(self._empty_value(self.prompt))
                return
            self.tokens = toks
            self._step(self._take(self.prompt))
        except Exception as ex:  # noqa: BLE001
            self._fail(ex)

    def send_value(self, value: Any) -> None:
        """Hodnota přímo (GUI: bod kliknutím (x, y) mm, výběr jako seznam id). Bod u výzvy „port“ se přichytí."""
        if self.done:
            return
        self._resume()
        try:
            p = self.prompt
            if p is not None and p.kind == "port" and isinstance(value, tuple) and len(value) == 2 \
                    and all(isinstance(v, (int, float)) for v in value):
                value = self._port_from_point(p, value)
            elif p is not None and p.kind == "point":
                self.runner.ctx.last_point = tuple(value)
            elif p is not None and p.kind == "selection":
                self.runner.ctx.selection = list(value)
            self._step(value)
        except Exception as ex:  # noqa: BLE001
            self._fail(ex)

    def cancel(self) -> Result:
        """Esc: vrátí výběr a aktivní list před příkazem. Model nemění – čekající příkaz ho ještě neměnil a změny
        udělané mezitím jinou cestou (myš, Ctrl+Z, dialog) musí zůstat."""
        if not self.done:
            self._fail(Cancelled(self.cmd.name))
        return self.result

    # -- čekání na vstup: snímek „před“ se při pokračování posune přes změny udělané mezitím --
    def _pause(self) -> None:
        self._waiting = True
        if self._before is not None:
            self._clean = sheets_state(self.runner.project) == self._before
            if not self._clean:
                log.warning("příkaz %s změnil model před výzvou – Esc ho vrátí celý", self.cmd.name)

    def _resume(self) -> None:
        if self._waiting and self._before is not None and self._clean:
            self._before = sheets_state(self.runner.project)
        self._waiting = False

    # -- průběh --
    def _step(self, value: Any) -> None:
        while True:
            try:
                prompt = next(self._gen) if value is _NOTHING else self._gen.send(value)
            except StopIteration as stop:
                self._finish(stop.value)
                return
            self.prompt = prompt
            if self.tokens:
                value = self._take(prompt)
                continue
            if prompt.kind == "selection" and (self.runner.ctx.selection or not self.interactive):
                value = self._empty_value(prompt)    # platí aktuální výběr (jako ZWCAD s předvýběrem)
                continue
            if not self.interactive:
                if prompt.optional:
                    value = prompt.default
                    continue
                raise MissingArgument(self.cmd.name, prompt)
            self._pause()
            return                                   # čeká na vstup z GUI

    def _empty_value(self, p: Param | None) -> Any:
        if p is None:
            return None
        if p.kind == "selection":
            sel = self.runner.ctx.selection
            if not sel and not p.optional:
                raise CommandError("Nic není vybráno (SELECT nebo označení za příkazem)")
            return list(sel)
        if p.kind == "kv":
            if not p.optional:
                raise MissingArgument(self.cmd.name, p)
            return {}
        if p.optional:
            return p.default
        raise MissingArgument(self.cmd.name, p)

    def _take(self, p: Param) -> Any:
        """Hodnota výzvy z tokenů řádku."""
        ctx = self.runner.ctx
        if p.kind == "selection":
            pats = []
            while self.tokens and parse.is_selector(self.tokens[0]):
                pats.append(self.tokens.pop(0))
            if not pats:
                return self._empty_value(p)
            ctx.selection = ctx.find_refs(pats)
            return list(ctx.selection)
        if p.kind == "kv":
            out: dict[str, str] = {}
            while self.tokens and parse.is_kv(self.tokens[0]):
                k, v = parse.parse_kv(self.tokens.pop(0))
                out[k] = v
            if not out:
                return self._empty_value(p)
            return out
        if p.kind == "point" and p.optional and parse.is_number(self.tokens[0]):
            return p.default                          # bod vynechán, číslo patří další výzvě (RO T1 90)
        tok = self.tokens.pop(0)
        if p.kind == "point":
            pr = parse.parse_port_ref(tok)
            pt = ctx.port_position(*pr)[2] if pr else parse.parse_xy(tok, ctx.last_point)
            ctx.last_point = pt
            return pt
        if p.kind == "port":
            pr = parse.parse_port_ref(tok)
            if pr:
                e, port, pt = ctx.port_position(*pr)
                ctx.last_point = pt
                return e, port
            return self._port_from_point(p, parse.parse_xy(tok, ctx.last_point))
        if p.kind == "number":
            return parse.parse_number(tok)
        if p.kind == "choice":
            for c in p.choices:
                if norm(c) == norm(tok):
                    return c
            raise CommandError(f"„{tok}“: možnosti jsou {', '.join(p.choices)}")
        if p.kind == "symbol":
            lib = ctx.library
            try:
                lib.get_symbol(tok)
            except KeyError as ex:
                raise CommandError(f"Značka „{tok}“ v knihovně není") from ex
            return tok
        return tok                                    # text

    def _port_from_point(self, p: Param, pt: tuple[float, float]) -> Any:
        ctx = self.runner.ctx
        ctx.last_point = (float(pt[0]), float(pt[1]))
        hit = ctx.nearest_port(*pt)
        if hit is not None:
            return hit
        if p.allow_point:
            return ("bod", ctx.last_point)
        raise CommandError(f"V bodě {pt[0]:g},{pt[1]:g} není port (do {PORT_SNAP_MM:g} mm)")

    def _finish(self, message: str | None) -> None:
        r = self.runner
        if self.tokens:
            raise CommandError(f"{self.cmd.name.upper()} – nadbytečné argumenty: {' '.join(self.tokens)}")
        if message:
            r.ctx.log(message)
        cs = None
        if self._before is not None:
            cs = ChangeSet.between(self.cmd.title, self._before, sheets_state(r.project))
            if cs is not None:
                if r.on_change is not None:
                    r.on_change(r.project)           # před zápisem do historie: chyba tady nenechá krok v journalu
                if r.journal is not None:
                    r.journal.push(cs)
        self.prompt = None
        self.result = Result(True, self.cmd.name, list(self.messages), cs, data=r.ctx.data)
        r._active = self.parent
        r.last_command = self.cmd

    def _fail(self, ex: BaseException) -> None:
        r = self.runner
        if not isinstance(ex, (CommandError, ParseError, ValueError, KeyError)):
            log.exception("příkaz %s spadl", self.cmd.name)
        if self._gen is not None:
            with contextlib.suppress(Exception):      # úklid generátoru, chyba už je hlášená
                self._gen.close()
        if self._before is not None and not (self._waiting and self._clean):
            restore_sheets_state(r.project, self._before)
        r.ctx.selection = self._sel_before
        r.ctx.sheet = self._sheet_before
        msg = _error_text(ex)
        self.messages.append(msg)
        self.prompt = None
        self.result = Result(False, self.cmd.name, list(self.messages), None, msg)
        r._active = self.parent


def _error_text(ex: BaseException) -> str:
    if isinstance(ex, KeyError) and ex.args:
        text = str(ex.args[0])
        return text if " " in text else f"„{text}“ neexistuje"     # holé id / klíč z modelu → česká hláška
    return str(ex) or type(ex).__name__


# ---- vykonavatel -------------------------------------------------------------------------------------------------
class CommandRunner:
    """Vykonavatel nad živým projektem. `execute(line)` = celý řádek neinteraktivně (skripty, CLI, agenti);
    `start(line)` = interaktivní průběh pro GUI. `on_message(text)` dostává výstup, `on_change(project)` se volá po
    každé změně modelu (CLI: dopočet odvozených dat `sync_derived`; GUI to dělá samo)."""

    def __init__(self, project: Project, library, registry: Registry | None = None, sheet: Sheet | None = None,
                 journal: Journal | None = None, on_message: Callable[[str], None] | None = None,
                 on_change: Callable[[Project], None] | None = None, base_dir: Path | None = None,
                 save: SaveOptions | None = None):
        if registry is None:
            from envocad.cmd.builtin import default_registry
            registry = default_registry()
        self.project, self.library, self.registry = project, library, registry
        self.journal = journal
        self.on_message, self.on_change = on_message, on_change
        self.save = save or SaveOptions()
        self.script_depth = 0
        self.script_root: Path | None = None     # složka hlavního skriptu – vnořené SCRIPT jen pod ní
        self.max_commands = MAX_COMMANDS         # rozpočet řádků na jeden hlavní skript i s vnořenými
        self.commands_run = 0
        self.variables: dict[str, str] = {}      # ${name} ve skriptech (CLI --var)
        self.last_command: CommandDef | None = None
        self._active: Session | None = None
        self.ctx = Ctx(project, library, sheet if sheet is not None else (project.sheets[0] if project.sheets else None),
                       [], self._log, self, base_dir=base_dir)

    def _log(self, text: str) -> None:
        s = self._active
        while s is not None:                     # i vnějším příkazům (SCRIPT vrátí hlášky svých řádků)
            s.messages.append(text)
            s = s.parent
        if self.on_message is not None:
            self.on_message(text)
        log.info("%s", text)

    def resolve(self, line: str) -> tuple[CommandDef, list[str]]:
        toks = parse.tokenize(line)
        if not toks:
            raise CommandError("Prázdný příkaz")
        cmd = self.registry.resolve(toks[0])
        if cmd is None:
            raise CommandError(f"Neznámý příkaz „{toks[0]}“ – Tab doplní")
        if cmd.run is None or cmd.needs_gui:
            raise CommandError(f"{cmd.name.upper()} ({cmd.title}) je jen v GUI")
        return cmd, toks[1:]

    def start(self, line: str, interactive: bool = True) -> Session | Result:
        """Spustí příkaz z řádku; chyba už při rozboru → `Result` s chybou, jinak `Session` (může být hotová)."""
        try:
            cmd, args = self.resolve(line)
        except (CommandError, ParseError) as ex:
            word = line.split()[0] if line.split() else ""
            return Result(False, word, [str(ex)], None, str(ex))
        return Session(self, cmd, args, interactive)

    def execute(self, line: str) -> Result:
        s = self.start(line, interactive=False)
        if isinstance(s, Result):
            return s
        assert s.result is not None
        return s.result

    # -- historie --
    def undo(self, n: int = 1) -> int:
        if self.journal is None:
            raise CommandError("Historie změn není k dispozici")
        k = 0
        while k < n and self.journal.undo(self.project) is not None:
            k += 1
        if k and self.on_change is not None:
            self.on_change(self.project)
        return k

    def redo(self, n: int = 1) -> int:
        if self.journal is None:
            raise CommandError("Historie změn není k dispozici")
        k = 0
        while k < n and self.journal.redo(self.project) is not None:
            k += 1
        if k and self.on_change is not None:
            self.on_change(self.project)
        return k


def sync_derived(project: Project) -> None:
    """Odvozená data po změně modelu, jako GUI mimo undo: vazby přívodů (`sync_feed_link_attrs`) a kabely."""
    from envocad.model.project import sync_cables, sync_feed_link_attrs
    sync_feed_link_attrs(project)
    sync_cables(project)
