"""Dok „Příkazový řádek“ ve stylu ZWCAD (fáze 2 návrhu `docs/design/prikazovy_radek.md`).

Tenká vrstva nad `envocad.cmd` (bez Qt): `CommandRunner` pracuje na živém projektu, hotový `ChangeSet` se pushne
jako `SheetsStateCommand` (jeden krok Ctrl+Z, přestavba pohledů změněných listů). Výzvy bodu jde zadat textem nebo
klikem do výkresu (`Mode.PICK`), výzvu výběru myší a Enter. UNDO/REDO/SAVE a příkazy jen pro GUI spouští akce okna.

Host (`MainWindow`) dodá: `project`, `library`, `undo` (QUndoStack), `actions` (id → QAction), `current_sheet`,
`draw_scene`, `sheets_changed(ids)` (přestavba pohledů) a `open_sheet(sheet)`.
"""
from __future__ import annotations

import html
import logging

from PySide6.QtCore import QEvent, QObject, QStringListModel, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCompleter,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from envocad.cmd import CommandRunner, parse
from envocad.cmd.parse import ParseError
from envocad.cmd.registry import Registry
from envocad.cmd.runner import Result, Session
from envocad.ui.canvas import Mode

log = logging.getLogger("envocad.cmd")
HISTORY_MAX = 200
HISTORY_FILE = "cmd_history.txt"
PROMPT_IDLE = "Příkaz:"
GUI_HISTORY = ("undo", "redo")      # v GUI drží historii QUndoStack – UNDO/REDO z řádku jdou přes něj
OUTPUT_LINES = 3


class CommandInput(QLineEdit):
    """Vstup řádku: Enter / mezera potvrdí, Esc zruší, ↑/↓ historie, Tab doplní (Tab nepřeskočí na další widget)."""
    submitted = Signal(str)
    cancelled = Signal()
    completion = Signal()
    history_step = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.prompt_kind: str | None = None          # druh aktuální výzvy (mezera v textové výzvě nepotvrzuje)

    def event(self, ev):
        if ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            self.completion.emit()
            return True
        return super().event(ev)

    def keyPressEvent(self, ev):
        k = ev.key()
        if k in (Qt.Key_Return, Qt.Key_Enter):
            self.submitted.emit(self.text())
        elif k == Qt.Key_Escape:
            self.cancelled.emit()
        elif k == Qt.Key_Space and not ev.modifiers() & ~Qt.ShiftModifier \
                and parse.space_submits(self.text(), self.prompt_kind):
            self.submitted.emit(self.text())
        elif k == Qt.Key_Up:
            self.history_step.emit(-1)
        elif k == Qt.Key_Down:
            self.history_step.emit(1)
        else:
            super().keyPressEvent(ev)


class CommandLine(QWidget):
    """Výstup (3 řádky, F2 přepne delší), výzva a vstup. `run_line(text)` spustí příkaz jako z klávesnice."""

    def __init__(self, host, registry: Registry, parent=None):
        super().__init__(parent)
        self.host, self.registry = host, registry
        self.runner: CommandRunner | None = None
        self.session: Session | None = None
        self.last_word: str | None = None             # Enter na prázdném řádku zopakuje poslední příkaz
        self.history: list[str] = self._load_history()
        self._hist_pos = len(self.history)
        self._pick_scene = None                        # scéna ve výzvě bodu (Mode.PICK)
        self._identity: dict[str, tuple] = {}
        self.output = QPlainTextEdit(readOnly=True)
        self.output.setMaximumBlockCount(500)
        self.output.setObjectName("cmd_output")
        self.prompt = QLabel(PROMPT_IDLE)
        self.input = CommandInput()
        self.input.setObjectName("cmd_input")
        self.input.setPlaceholderText("příkaz (Tab doplní, ↑ historie)")
        self.input.submitted.connect(self.submit)
        self.input.cancelled.connect(self.cancel)
        self.input.completion.connect(self.complete)
        self.input.history_step.connect(self._history_step)
        self._completer = QCompleter(self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setWidget(self.input)
        self._completer.activated.connect(self.input.setText)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.prompt)
        row.addWidget(self.input, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(2)
        lay.addWidget(self.output, 1)
        lay.addLayout(row)
        self._set_output_lines(OUTPUT_LINES)

    # ---- výstup -------------------------------------------------------------------------------------------------
    def _set_output_lines(self, n: int) -> None:
        fm = self.output.fontMetrics()
        self.output.setFixedHeight(fm.lineSpacing() * n + 2 * self.output.frameWidth() + 6)

    def toggle_history(self) -> None:
        """F2: delší výstup (historie) / zpět na 3 řádky."""
        big = self.output.height() > self.output.fontMetrics().lineSpacing() * (OUTPUT_LINES + 2)
        self._set_output_lines(OUTPUT_LINES if big else 15)

    def echo(self, text: str, error: bool = False) -> None:
        body = html.escape(text)
        self.output.appendHtml(f'<span style="color:#d0453a">{body}</span>' if error else body)

    # ---- spuštění -----------------------------------------------------------------------------------------------
    def _runner(self) -> CommandRunner:
        project = self.host.project
        if self.runner is None or self.runner.project is not project:     # nový / otevřený projekt
            self.runner = CommandRunner(project, self.host.library, self.registry)
        return self.runner

    def submit(self, text: str) -> None:
        """Enter: hodnota pro čekající výzvu, jinak nový příkaz; prázdný řádek zopakuje poslední příkaz."""
        self.input.clear()
        if self.session is not None:
            self.echo(f"{self.prompt.text()} {text}".rstrip())
            self._sync_selection()
            self.session.send(text)
            self._advance()
            return
        text = text.strip()
        if not text:
            if not self.last_word:
                return
            text = self.last_word
        self._remember(text)
        self.echo(f"{PROMPT_IDLE} {text}")
        self.run_line(text)

    def run_line(self, line: str) -> None:
        """Spustí řádek (příkaz a argumenty); chybějící hodnoty se doptají výzvami."""
        try:
            toks = parse.tokenize(line)
        except ParseError as ex:
            self.echo(str(ex), error=True)
            return
        if not toks:
            return
        cmd = self.registry.resolve(toks[0])
        if cmd is None:
            self.echo(f"Neznámý příkaz „{toks[0]}“ – Tab doplní", error=True)
            return
        self.last_word = toks[0]
        args = toks[1:]
        if cmd.name in GUI_HISTORY:
            self._undo_redo(cmd.name, args)
            return
        if cmd.name == "save":
            if args:
                self.echo("SAVE v programu bez cesty – jinam Soubor → Uložit jako…", error=True)
            else:
                self._trigger(cmd.gui_fallback or "save", cmd.title)
            return
        gui_only = cmd.run is None or cmd.needs_gui
        if gui_only or (not args and cmd.gui_fallback and cmd.gui_fallback in self.host.actions):
            # bez argumentů dnešní interaktivní režim (WIRE → kreslení myší, INSERT → knihovna, F7 → panel)
            if args:
                self.echo(f"{cmd.name.upper()} nebere argumenty", error=True)
            else:
                self._trigger(cmd.gui_fallback or cmd.name, cmd.title)
            return
        r = self._runner()
        r.ctx.sheet = self.host.current_sheet
        self._sync_selection()
        self._identity = self._snapshot_identity()
        s = r.start(line, interactive=True)
        if isinstance(s, Result):
            self._finish(s)
            return
        self.session = s
        self._advance()

    def _trigger(self, key: str, title: str) -> None:
        a = self.host.actions.get(key)
        if a is None:
            self.echo(f"{title}: v programu není", error=True)
        elif not a.isEnabled():
            self.echo(f"{title}: teď není dostupné", error=True)
        else:
            a.trigger()

    def _undo_redo(self, name: str, args: list[str]) -> None:
        if len(args) > 1 or (args and not parse.is_number(args[0])):
            self.echo(f"{name.upper()} [počet]", error=True)
            return
        n = max(1, min(int(parse.parse_number(args[0])) if args else 1, 10_000))
        stack = self.host.undo
        can, step = (stack.canUndo, stack.undo) if name == "undo" else (stack.canRedo, stack.redo)
        k = 0
        while k < n and can():
            step()
            k += 1
        if k:
            self.echo(f"{'Zpět' if name == 'undo' else 'Znovu'}: {k}")
        else:
            self.echo("Není co vrátit" if name == "undo" else "Není co zopakovat")

    def cancel(self) -> None:
        """Esc: zruší čekající příkaz (model zůstane), jinak vymaže rozepsaný řádek."""
        if self.session is None:
            self.input.clear()
            return
        s, self.session = self.session, None
        self._finish(s.cancel())

    def reset(self) -> None:
        """Nový / otevřený projekt, zavření okna: rozpracovaný příkaz zrušit, runner patří starému projektu."""
        self.cancel()
        self.runner = None

    def view_changed(self) -> None:
        """Přepnutí záložky: výzva bodu ve skryté scéně se zruší (příkaz by pak přepínal zpět na svůj list)."""
        if self.session is not None and self._pick_scene is not None and self._pick_scene is not self.host.draw_scene:
            self.cancel()

    # ---- průběh výzev -------------------------------------------------------------------------------------------
    def _advance(self) -> None:
        s = self.session
        if s is None:
            return
        if s.done:
            self.session = None
            self._finish(s.result)
            return
        p = s.prompt
        self.prompt.setText(p.prompt + (" (vyberte ve výkresu, Enter)" if p.kind == "selection" else ""))
        self.input.prompt_kind = p.kind
        sc = self.host.draw_scene
        self._end_pick()
        if p.kind in ("point", "port") and sc is not None and hasattr(sc, "start_pick"):
            sc.start_pick(self._picked, base=p.base)
            self._pick_scene = sc
            sc.mode_changed.connect(self._pick_mode_changed)
        self.input.setFocus()

    def _picked(self, pt: tuple[float, float]) -> None:
        if self.session is None:
            return
        self.echo(f"{self.prompt.text()} {pt[0]:g},{pt[1]:g}")
        self.session.send_value(pt)
        self._advance()

    def _pick_mode_changed(self, mode) -> None:
        if mode != Mode.PICK and self.session is not None:      # Esc / pravé tlačítko ve výkresu
            self.cancel()

    def _end_pick(self) -> None:
        sc, self._pick_scene = self._pick_scene, None
        if sc is None:
            return
        sc.mode_changed.disconnect(self._pick_mode_changed)
        if sc.mode == Mode.PICK:
            sc.set_mode(Mode.SELECT)

    def _finish(self, res: Result) -> None:
        self._end_pick()
        self.prompt.setText(PROMPT_IDLE)
        self.input.prompt_kind = None
        for m in res.messages:
            self.echo(m, error=not res.ok and m == res.error)
        r = self.runner
        if r is None or r.project is not self.host.project:      # projekt se mezitím vyměnil – nic nepushovat
            return
        if res.changeset is not None:
            from envocad.ui import commands
            cs = res.changeset
            self.host.undo.push(commands.SheetsStateCommand(self.host.project, cs.before, cs.after, cs.label,
                                                            on_change=self.host.sheets_changed))
        elif not res.ok:
            stale = [sid for sid, ident in self._snapshot_identity().items() if self._identity.get(sid) != ident]
            if stale:                                   # chyba po změně: listy obnovené ze snímku jsou nové objekty
                self.host.sheets_changed(stale)
        if r.ctx.sheet is not None and r.ctx.sheet is not self.host.current_sheet:
            self.host.open_sheet(r.ctx.sheet)
        self._apply_selection(r.ctx.selection)

    # ---- výběr mezi scénou a příkazem ---------------------------------------------------------------------------
    def _scene_ids(self) -> list[str]:
        sc = self.host.draw_scene
        if sc is None:
            return []
        out = []
        for it in sc.selectedItems():
            obj = getattr(it, "element", None) or getattr(it, "wire", None)
            if obj is not None and getattr(obj, "id", None):
                out.append(obj.id)
        return out

    def _sync_selection(self) -> None:
        """Výběr pro příkaz = výběr kreslicí scény; v pohledu bez ní (rozložení, svorkovnice) prázdný – starý výběr
        z jiné záložky by jinak tiše platil (DELETE by smazal nevybraný prvek)."""
        if self.runner is not None:
            self.runner.ctx.selection = self._scene_ids()

    def _apply_selection(self, ids: list[str]) -> None:
        sc = self.host.draw_scene
        if sc is None or ids == self._scene_ids():
            return
        sc.clearSelection()
        items = {**getattr(sc, "element_items", {}), **getattr(sc, "wire_items", {})}
        for i in ids:
            if i in items:
                items[i].setSelected(True)

    def _snapshot_identity(self) -> dict[str, tuple]:
        """Identita objektů prvků a vodičů listů – po chybě se přestaví jen listy obnovené ze snímku."""
        return {s.id: tuple(map(id, s.elements)) + tuple(map(id, s.wires)) for s in self.host.project.sheets}

    # ---- doplňování a historie ----------------------------------------------------------------------------------
    def complete(self) -> None:
        if self.session is not None:
            return
        r = self._runner()
        r.ctx.sheet = self.host.current_sheet
        self._sync_selection()
        text = self.input.text()
        cands = self.registry.complete(text, r.ctx)
        if not cands:
            return
        if len(cands) == 1:
            self.input.setText(cands[0] + ("" if cands[0].endswith("=") else " "))
            return
        self._completer.setModel(QStringListModel(cands, self._completer))
        self._completer.setCompletionPrefix(text)
        self._completer.complete()

    def _remember(self, line: str) -> None:
        if not self.history or self.history[-1] != line:
            self.history.append(line)
            del self.history[:-HISTORY_MAX]
            self._save_history()
        self._hist_pos = len(self.history)

    def _history_step(self, d: int) -> None:
        if not self.history or self.session is not None:
            return
        self._hist_pos = max(0, min(len(self.history), self._hist_pos + d))
        self.input.setText(self.history[self._hist_pos] if self._hist_pos < len(self.history) else "")

    @staticmethod
    def _history_path():
        from envocad.library.store import home_dir
        return home_dir() / HISTORY_FILE

    def _load_history(self) -> list[str]:
        try:
            return self._history_path().read_text(encoding="utf-8").splitlines()[-HISTORY_MAX:]
        except (OSError, UnicodeDecodeError):
            return []

    def _save_history(self) -> None:
        try:
            self._history_path().write_text("\n".join(self.history) + "\n", encoding="utf-8")
        except OSError as ex:
            log.warning("historii příkazů nelze uložit: %s", ex)


class CanvasTyping(QObject):
    """Režim kláves „zwcad“: psaní ve výkresu jde do příkazového řádku (znak, Enter, mezera = Enter). Zkratky
    s Ctrl/Alt a Delete/šipky zůstávají výkresu; Esc navíc zruší rozpracovaný příkaz. Při vkládání značky (náhled)
    s prázdným řádkem dostane klávesy scéna (R / M otočí a zrcadlí náhled). Skrytý dok se při psaní ukáže.
    Filtr na QApplication, jen pro pohledy okna `window`."""

    def __init__(self, window, cmdline: CommandLine, dock=None, typing: bool = True):
        super().__init__(window)
        self.window, self.cmdline, self.dock = window, cmdline, dock
        self.typing = typing                             # False = klávesy „envocad“: jen Esc ruší příkaz
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() != QEvent.KeyPress or not isinstance(obj, QGraphicsView) or obj.window() is not self.window:
            return False
        if ev.key() == Qt.Key_Escape:
            if self.cmdline.session is not None:
                self.cmdline.cancel()
            return False                                 # scéna dál vrátí Mode.SELECT
        if not self.typing:
            return False
        text = ev.text()
        mods = ev.modifiers()
        altgr = bool(mods & Qt.ControlModifier and mods & Qt.AltModifier) and len(text) == 1 and text.isprintable()
        if mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier) and not altgr:
            return False                                 # zkratky; AltGr (Ctrl+Alt na Windows) píše @ # & [ {
        inp = self.cmdline.input
        sc = obj.scene()
        if not inp.text() and self.cmdline.session is None and getattr(sc, "mode", None) == Mode.PLACE:
            return False                                 # náhled vkládání: R otočí, M zrcadlí
        if self.dock is not None and not self.dock.isVisible():
            self.dock.show()
            self.dock.raise_()
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            if not inp.text() and self.cmdline.session is None and not self.cmdline.last_word:
                return False
            self.cmdline.submit(inp.text())
            return True
        if len(text) == 1 and text.isprintable() and not text.isspace():
            inp.setFocus()
            inp.insert(text)
            return True
        return False
