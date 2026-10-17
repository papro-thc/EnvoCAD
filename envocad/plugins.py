"""Zásuvné moduly (pluginy) EnvoCAD.

Plugin = soubor `*.py` ve složce `~/.envocad/plugins/` (nebo balíček `envocad/plugins_builtin/`) s funkcí

    def register(ctx: PluginContext) -> None: ...

Přes `ctx` může plugin:
- `ctx.add_menu_action("Nástroje", "Můj příkaz…", callback)` – položka menu; callback dostane MainWindow
- `ctx.add_template(Template)`              – šablona rozvaděče (viz envocad/library/templates.py)
- `ctx.add_importer("Název…", callback)`     – položka v menu Knihovna → Importovat, callback(main_window)
- `ctx.add_report("Název", fn)`              – výkaz (hlavička, řádky) do xlsx exportu (viz export/reports.py)
- `ctx.library`, `ctx.log`                   – knihovna a logger

Knihovna (symboly *.json, artikly *.csv) se rozšiřuje bez kódu – stačí soubory v `~/.envocad/library/`.
Pluginy běží s plnými právy uživatele – instalujte jen vlastní / prověřené.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("envocad.plugins")


@dataclass
class PluginContext:
    """Registrace pluginu. Při načítání se každý plugin registruje do vlastního kontextu a do společného se
    položky přenesou až po úspěšném `register` – plugin, který spadne v půlce, nezanechá nic (transakčně)."""
    library: object
    menu_actions: list[tuple[str, str, Callable]] = field(default_factory=list)
    importers: list[tuple[str, Callable]] = field(default_factory=list)
    loaded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)   # (plugin, chyba) – hlásí okno po startu
    templates: list = field(default_factory=list)                 # čekající šablony / výkazy (do commit)
    reports: list[tuple[str, Callable]] = field(default_factory=list)
    live: bool = True        # False = zatím jen sbírat (plugin se právě registruje)
    log = log

    def add_menu_action(self, menu: str, text: str, callback: Callable) -> None:
        if not callable(callback):
            raise TypeError(f"položka menu „{text}“: callback není funkce")
        self.menu_actions.append((str(menu), str(text), callback))

    def add_importer(self, text: str, callback: Callable) -> None:
        if not callable(callback):
            raise TypeError(f"importér „{text}“: callback není funkce")
        self.importers.append((str(text), callback))

    def add_template(self, template) -> None:
        if not isinstance(getattr(template, "id", None), str):
            raise TypeError("šablona musí mít textové `id` (viz envocad/library/templates.py)")
        if self.live:
            _apply_template(template)
        else:
            self.templates.append(template)

    def add_report(self, name: str, fn: Callable) -> None:
        if not callable(fn):
            raise TypeError(f"výkaz „{name}“: fn není funkce")
        if self.live:
            _apply_report(str(name), fn)
        else:
            self.reports.append((str(name), fn))


def _apply_template(template) -> None:
    from envocad.library.templates import TEMPLATES
    TEMPLATES[:] = [t for t in TEMPLATES if t.id != template.id] + [template]


def _apply_report(name: str, fn: Callable) -> None:
    from envocad.export import reports
    reports.ALL_REPORTS[:] = [r for r in reports.ALL_REPORTS if r[0] != name] + [(name, fn)]


def plugin_dirs() -> list[Path]:
    from envocad.library.store import home_dir
    dirs = [Path(__file__).parent / "plugins_builtin", home_dir() / "plugins"]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def load_plugins(library) -> PluginContext:
    """Načte pluginy. Chyba pluginu (i SyntaxError, SystemExit…) start neshodí: plugin se přeskočí, jeho
    registrace se zahodí a skončí v `ctx.failed`. Jen KeyboardInterrupt se propustí."""
    ctx = PluginContext(library=library)
    for d in plugin_dirs():
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_"):
                continue
            name = f"envocad_plugin_{f.stem}"
            sub = PluginContext(library=library, live=False)
            try:
                spec = importlib.util.spec_from_file_location(name, f)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod
                spec.loader.exec_module(mod)
                if not hasattr(mod, "register"):
                    continue
                mod.register(sub)
            except KeyboardInterrupt:
                raise
            except BaseException as ex:
                sys.modules.pop(name, None)
                log.error("plugin %s selhal: %s: %s", f, type(ex).__name__, ex, exc_info=not isinstance(ex, SystemExit))
                ctx.failed.append((f.stem, f"{type(ex).__name__}: {ex}"))
                continue
            ctx.menu_actions += sub.menu_actions
            ctx.importers += sub.importers
            for t in sub.templates:
                _apply_template(t)
            for rname, fn in sub.reports:
                _apply_report(rname, fn)
            sub.templates.clear()
            sub.reports.clear()
            sub.live = True     # pozdější registrace (mimo register) už platí hned
            ctx.loaded.append(f.stem)
            log.info("plugin načten: %s", f)
    return ctx


def failed_message(ctx: PluginContext) -> str:
    """Stavová zpráva po startu: „Plugin X se nenačetl (viz log)“ / „Pluginy X, Y se nenačetly (viz log)“."""
    names = [n for n, _ in ctx.failed]
    if not names:
        return ""
    if len(names) == 1:
        return f"Plugin {names[0]} se nenačetl (viz log)"
    return f"Pluginy {', '.join(names)} se nenačetly (viz log)"
