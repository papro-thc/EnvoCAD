"""Zásuvné moduly (pluginy) EnvoCAD.

Plugin = soubor `*.py` ve složce `~/.envocad/plugins/` (nebo balíček `envocad/plugins_builtin/`) s funkcí

    def register(ctx: PluginContext) -> None: ...

Přes `ctx` může plugin:
- `ctx.add_menu_action("Nástroje", "Můj příkaz…", callback)` – položka menu; callback dostane MainWindow
- `ctx.add_template(Template)`              – šablona rozvaděče (viz envocad/library/templates.py)
- `ctx.add_importer("Název…", callback)`     – položka v menu Knihovna → Importovat, callback(main_window)
- `ctx.add_report("Název", fn)`              – výkaz (hlavička, řádky) do xlsx exportu (viz export/reports.py);
                                               fn(project, lib, sheet) dostane projekt bez visících vodičů
- `ctx.add_command(CommandDef(...))`         – příkaz příkazového řádku (dok v okně, skripty .ecs, CLI s --plugins);
                                               `run(ctx)` je generátor výzev jako vestavěné příkazy (envocad/cmd/builtin.py),
                                               model mění přes `envocad.cmd.edits`; jméno nesmí kolidovat s vestavěným
- `ctx.add_check(fn)`                        – kontrola projektu (F7, příkaz CHECKS); fn(project, lib) vrací seznam
                                               `envocad.model.checks.Finding` (nebo None), dostane projekt bez visících
                                               vodičů; výjimka / vadný návrat = nález ERROR `plugin_check`, nespadne
                                               (vzor: `plugins_builtin/example_check.py`)
- `ctx.library`, `ctx.log`                   – knihovna a logger

Verze API: `API_VERSION` (číslo). Plugin může mít na úrovni modulu `REQUIRES_API = <int>` – vyžaduje-li novější
API, než má tento EnvoCAD, nenačte se (`register` se nezavolá) a hlášení je v `ctx.failed`.

Registrace je transakční jen pro položky přes `ctx.add_*` (menu, importéry, šablony, výkazy, kontroly, příkazy):
plugin, který v `register` spadne, po sobě nezanechá žádnou z nich. **Změny knihovny transakce nepokrývá** – co plugin zapíše
přes `ctx.library.put_symbol(...)` (nebo jinou metodu knihovny), zůstane v knihovně i po pádu pluginu; v logu je
pak varování se seznamem zapsaných značek. Plugin, který knihovnu mění, ať to dělá až na konci `register`.

Přívod / vývod rozvaděče je od formátu v13 jedna značka `sb.feed` se směrem v atributu `dir` ("in" / "out";
`envocad.model.feed.FEED_SYMBOL`, šablony `templates._feed`). Starší id `sb.feed_in` / `sb.feed_out` už knihovna nemá:
šablona pluginu (`ctx.add_template`), která je ještě vkládá, se po `build` převede (`feed.normalize_legacy_objects`,
přívod se pootočí o 180° – port zůstane na místě); callback menu, který prvky vkládá sám, musí použít `sb.feed`
(jinak se nakreslí zástupná značka „?“ a kontrola ji hlásí).

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

API_VERSION = 1                    # verze API pro pluginy; plugin může vyžadovat `REQUIRES_API` (int)
CHECKS: list[Callable] = []        # kontroly pluginů (`ctx.add_check`); volající je předají do `check_project`


def plugin_checks() -> list[Callable]:
    """Kopie registru kontrol pluginů – pro `check_project(..., extra_checks=plugin_checks())`."""
    return list(CHECKS)


@dataclass
class PluginContext:
    """Registrace pluginu. Při načítání se každý plugin registruje do vlastního kontextu a do společného se
    položky přenesou až po úspěšném `register` – plugin, který spadne v půlce, nezanechá nic (transakčně).
    Výjimka: zápisy do knihovny (`library.put_symbol`) transakce nepokrývá, jen se zalogují."""
    library: object
    menu_actions: list[tuple[str, str, Callable]] = field(default_factory=list)
    importers: list[tuple[str, Callable]] = field(default_factory=list)
    loaded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)   # (plugin, chyba) – hlásí okno po startu
    templates: list = field(default_factory=list)                 # čekající šablony / výkazy (do commit)
    reports: list[tuple[str, Callable]] = field(default_factory=list)
    checks: list[Callable] = field(default_factory=list)          # čekající kontroly (do commit)
    commands: list = field(default_factory=list)                  # CommandDef příkazového řádku (registruje je volající)
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

    def add_command(self, cmd) -> None:
        """Příkaz příkazového řádku. Kolize s vestavěným příkazem nebo s příkazem jiného pluginu = chyba registrace
        (plugin se celý zahodí). Do registru ho přidá okno / CLI (`register_plugin_commands`)."""
        from envocad.cmd import CommandDef
        from envocad.cmd.registry import norm
        if not isinstance(cmd, CommandDef):
            raise TypeError("add_command čeká envocad.cmd.CommandDef")
        if cmd.run is not None and not callable(cmd.run):
            raise TypeError(f"příkaz {cmd.name}: run není funkce")
        words = [norm(cmd.name), *(norm(a) for a in cmd.aliases)]
        taken = _builtin_command_words() | {w for c in self.commands for w in _command_words(c)}
        clash = [w for w in words if not w or w in taken]
        if clash:      # ani alias: plugin nesmí přesměrovat M, I, SAVE… vestavěných příkazů na svůj kód
            raise ValueError(f"příkaz {cmd.name}: jméno / alias {', '.join(clash) or '(prázdné)'} už existuje "
                             "(vestavěný příkaz nebo alias)")
        self.commands.append(cmd)

    def add_check(self, fn: Callable) -> None:
        """Kontrola projektu `fn(project, lib)` → seznam `Finding` / None (viz `check_project`)."""
        if not callable(fn):
            raise TypeError("kontrola: fn není funkce")
        if self.live:
            _apply_check(fn)
        else:
            self.checks.append(fn)

    def add_report(self, name: str, fn: Callable) -> None:
        if not callable(fn):
            raise TypeError(f"výkaz „{name}“: fn není funkce")
        if self.live:
            _apply_report(str(name), fn)
        else:
            self.reports.append((str(name), fn))


def _command_words(cmd) -> set[str]:
    from envocad.cmd.registry import norm
    return {norm(cmd.name), *(norm(a) for a in cmd.aliases)}


def _builtin_command_words() -> set[str]:
    """Jména vestavěných příkazů a výchozí aliasy (`cmd/aliases.json`) – plugin je nesmí obsadit."""
    from envocad.cmd import default_registry
    reg = default_registry(user_aliases=False)
    return set(reg.commands) | set(reg.aliases)


def _apply_template(template) -> None:
    from envocad.library.templates import TEMPLATES
    TEMPLATES[:] = [t for t in TEMPLATES if t.id != template.id] + [template]


def _apply_report(name: str, fn: Callable) -> None:
    from envocad.export import reports
    fn = reports.over_clean(fn)   # i výkaz pluginu počítá nad projektem bez visících vodičů
    reports.ALL_REPORTS[:] = [r for r in reports.ALL_REPORTS if r[0] != name] + [(name, fn)]


def _apply_check(fn: Callable) -> None:
    if fn not in CHECKS:
        CHECKS.append(fn)


class _LibraryWrites:
    """Po dobu `register` zaznamenává `put_symbol` na knihovně (stín instance, identita knihovny se nemění) –
    změny knihovny nejsou součástí transakce, po pádu pluginu se aspoň zapíšou do logu."""

    def __init__(self, library):
        self.library, self.ids = library, []

    def __enter__(self):
        orig = getattr(self.library, "put_symbol", None)
        if callable(orig):
            def put_symbol(sym, *a, **k):
                orig(sym, *a, **k)
                self.ids.append(str(getattr(sym, "id", sym)))
            try:
                self.library.put_symbol = put_symbol
            except (AttributeError, TypeError):
                pass
        return self

    def __exit__(self, *exc):
        if "put_symbol" in getattr(self.library, "__dict__", {}):
            del self.library.put_symbol
        return False


def plugin_dirs() -> list[Path]:
    from envocad.library.store import home_dir
    dirs = [Path(__file__).parent / "plugins_builtin", home_dir() / "plugins"]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def _check_api(mod) -> None:
    """`REQUIRES_API` modulu: chybí = OK; musí být int (ne bool) a nesmí být vyšší než `API_VERSION`."""
    need = getattr(mod, "REQUIRES_API", None)
    if need is None and not hasattr(mod, "REQUIRES_API"):
        return
    if not isinstance(need, int) or isinstance(need, bool):
        raise TypeError(f"REQUIRES_API musí být celé číslo, ne {need!r}")
    if need > API_VERSION:
        raise RuntimeError(f"plugin vyžaduje API {need}, tento EnvoCAD má API {API_VERSION} – aktualizujte EnvoCAD")


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
            writes = _LibraryWrites(library)
            try:
                with writes:
                    spec = importlib.util.spec_from_file_location(name, f)
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[name] = mod
                    spec.loader.exec_module(mod)
                    _check_api(mod)
                    if not hasattr(mod, "register"):
                        continue
                    mod.register(sub)
            except KeyboardInterrupt:
                raise
            except BaseException as ex:
                sys.modules.pop(name, None)
                log.error("plugin %s selhal: %s: %s", f, type(ex).__name__, ex, exc_info=not isinstance(ex, SystemExit))
                if writes.ids:
                    log.warning("plugin %s před chybou zapsal do knihovny značky %s – změny knihovny se nevracejí",
                                f, ", ".join(writes.ids))
                ctx.failed.append((f.stem, f"{type(ex).__name__}: {ex}"))
                continue
            clash = {w for c in sub.commands for w in _command_words(c)} & \
                {w for c in ctx.commands for w in _command_words(c)}
            if clash:                               # stejné jméno jako příkaz dříve načteného pluginu
                msg = f"příkaz {', '.join(sorted(clash))} už registroval jiný plugin"
                log.error("plugin %s selhal: %s", f, msg)
                ctx.failed.append((f.stem, msg))
                sys.modules.pop(name, None)
                continue
            ctx.menu_actions += sub.menu_actions
            ctx.importers += sub.importers
            ctx.commands += sub.commands
            for t in sub.templates:
                _apply_template(t)
            for rname, fn in sub.reports:
                _apply_report(rname, fn)
            for fn in sub.checks:
                _apply_check(fn)
            sub.checks.clear()
            sub.templates.clear()
            sub.reports.clear()
            sub.live = True     # pozdější registrace (mimo register) už platí hned
            ctx.loaded.append(f.stem)
            log.info("plugin načten: %s", f)
    return ctx


def register_plugin_commands(ctx: PluginContext, registry) -> list[str]:
    """Příkazy pluginů do registru příkazového řádku; vrací varování (kolize se jménem, které mezitím přibylo –
    např. akce menu okna)."""
    import dataclasses

    from envocad.cmd.registry import norm
    bad = []
    for cmd in ctx.commands:
        keep = [a for a in cmd.aliases if norm(a) not in registry.aliases and norm(a) not in registry.commands]
        for a in set(cmd.aliases) - set(keep):            # alias už patří jinému příkazu (i uživatelský) – nepřepsat
            bad.append(f"příkaz pluginu {cmd.name}: alias {a} už je obsazený – ignorován")
        try:
            registry.add(dataclasses.replace(cmd, aliases=tuple(keep)))
        except ValueError as ex:
            bad.append(str(ex))
    for w in bad:
        log.warning("%s", w)
    return bad


def failed_message(ctx: PluginContext) -> str:
    """Stavová zpráva po startu: „Plugin X se nenačetl (viz log)“ / „Pluginy X, Y se nenačetly (viz log)“."""
    names = [n for n, _ in ctx.failed]
    if not names:
        return ""
    if len(names) == 1:
        return f"Plugin {names[0]} se nenačetl (viz log)"
    return f"Pluginy {', '.join(names)} se nenačetly (viz log)"
