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
    library: object
    menu_actions: list[tuple[str, str, Callable]] = field(default_factory=list)
    importers: list[tuple[str, Callable]] = field(default_factory=list)
    loaded: list[str] = field(default_factory=list)
    log = log

    def add_menu_action(self, menu: str, text: str, callback: Callable) -> None:
        self.menu_actions.append((menu, text, callback))

    def add_importer(self, text: str, callback: Callable) -> None:
        self.importers.append((text, callback))

    def add_template(self, template) -> None:
        from envocad.library.templates import TEMPLATES
        TEMPLATES[:] = [t for t in TEMPLATES if t.id != template.id] + [template]

    def add_report(self, name: str, fn: Callable) -> None:
        from envocad.export import reports
        reports.ALL_REPORTS[:] = [r for r in reports.ALL_REPORTS if r[0] != name] + [(name, fn)]


def plugin_dirs() -> list[Path]:
    from envocad.library.store import home_dir
    dirs = [Path(__file__).parent / "plugins_builtin", home_dir() / "plugins"]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def load_plugins(library) -> PluginContext:
    ctx = PluginContext(library=library)
    for d in plugin_dirs():
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_"):
                continue
            name = f"envocad_plugin_{f.stem}"
            try:
                spec = importlib.util.spec_from_file_location(name, f)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod
                spec.loader.exec_module(mod)
                if hasattr(mod, "register"):
                    mod.register(ctx)
                    ctx.loaded.append(f.stem)
                    log.info("plugin načten: %s", f)
            except Exception as ex:  # noqa: BLE001 – vadný plugin nesmí shodit start
                log.error("plugin %s selhal: %s", f, ex)
    return ctx
