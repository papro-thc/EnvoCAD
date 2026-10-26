"""Registr příkazů příkazového řádku (bez Qt): definice, aliasy (ZWCAD/AutoCAD + české), doplňování.

Jméno příkazu (`CommandDef.name`) = id akce v `MainWindow.actions`, kde akce existuje. Porovnání jmen a aliasů je bez
diakritiky a velikosti písmen (`norm`); úvodní „_“ / „-“ / „'“ (anglický prefix a řádková verze v ZWCAD) se ignoruje.
"""
from __future__ import annotations

import json
import logging
import unicodedata
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger("envocad.cmd")

ParamKind = Literal["point", "port", "selection", "number", "text", "symbol", "choice", "kv"]
PARAM_KINDS = ("point", "port", "selection", "number", "text", "symbol", "choice", "kv")
ALIASES_FILE = Path(__file__).with_name("aliases.json")


def norm(text: str) -> str:
    """Bez diakritiky, malými písmeny, bez úvodního `_ - '` (OTOČIT = otocit = _otocit)."""
    t = unicodedata.normalize("NFKD", text.strip().casefold())
    return "".join(c for c in t if not unicodedata.combining(c)).lstrip("_-'")


@dataclass(frozen=True)
class Param:
    """Výzva příkazu. Generátor příkazu ji vrací `yield` a dostane zpět hodnotu:
    point → (x, y) mm; port → (prvek, port) nebo („bod“, (x, y)) mimo port u výzvy `allow_point`; selection → seznam id;
    number → float; text / symbol / choice → str; kv → dict[str, str] (prázdný u volitelné výzvy bez hodnot).
    `base` = základní bod pro gumovou čáru v GUI."""
    name: str
    kind: ParamKind
    prompt: str
    optional: bool = False
    choices: tuple[str, ...] = ()
    default: Any = None
    base: tuple[float, float] | None = None
    allow_point: bool = False

    def __post_init__(self):
        if self.kind not in PARAM_KINDS:
            raise ValueError(f"neznámý druh výzvy {self.kind!r}")


Prompt = Param
SUGGEST_LIMIT = 12
SUGGEST_CONTAINS = 3      # od kolika znaků hledat i uvnitř jmen a českých názvů („otoc“ → ROTATE), kratší jen začátek


@dataclass(frozen=True)
class Suggestion:
    """Návrh našeptávače: `word` = co se zapíše do řádku (jméno nebo alias), `name` = příkaz, `title` = česky."""
    word: str
    name: str
    title: str


@dataclass
class CommandDef:
    name: str                                   # kanonické id (= id akce v MainWindow.actions, kde existuje)
    title: str                                  # česky pro výstup a paletu
    aliases: tuple[str, ...] = ()               # aliasy z kódu (výchozí jsou v aliases.json)
    params: tuple[Param, ...] = ()              # popis argumentů pro nápovědu a doplňování
    run: Callable[[Any], Generator[Param, Any, str | None]] | None = None   # None = jen GUI akce
    gui_fallback: str | None = None             # bez argumentů v GUI spustit existující akci / režim
    needs_gui: bool = False                     # dialogy, pohledy – headless hlásí „jen v GUI“
    transaction: bool = True                    # běh v transakci se snímkem listů (ChangeSet) a zápisem do historie
    usage: str = ""                             # nápověda syntaxe („MOVE [výběr] základní cíl“)


@dataclass
class Registry:
    commands: dict[str, CommandDef] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)       # norm(alias) → jméno příkazu
    alias_labels: dict[str, str] = field(default_factory=dict)  # norm(alias) → alias, jak je zapsaný

    def add(self, cmd: CommandDef, replace: bool = False) -> None:
        key = norm(cmd.name)
        if key in self.commands and not replace:
            raise ValueError(f"Příkaz {cmd.name} už je registrovaný")
        self.commands[key] = cmd
        for a in cmd.aliases:
            self.add_alias(a, cmd.name)

    def add_alias(self, alias: str, target: str) -> bool:
        """Alias → příkaz. Kanonická jména se aliasem nepřepíší, alias na neznámý příkaz se odmítne (False)."""
        a, t = norm(alias), norm(target)
        if not a or t not in self.commands or (a in self.commands and a != t):
            return False
        self.aliases[a] = self.commands[t].name
        self.alias_labels[a] = alias.strip().upper()
        return True

    def load_aliases(self, path: Path | str) -> list[str]:
        """Načte aliasy ze souboru `{"aliases": {"M": "move", …}}` (přepisují dřívější aliasy). Vrací varování
        (neznámý příkaz, kolize s kanonickým jménem); chybějící soubor = nic."""
        p = Path(path)
        if not p.is_file():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as ex:
            return [f"{p}: aliasy nelze načíst – {ex}"]
        items = data.get("aliases", {}) if isinstance(data, dict) else None
        if not isinstance(items, dict):
            return [f"{p}: aliasy nelze načíst – položka „aliases“ musí být objekt"]
        bad = []
        for alias, target in items.items():
            if not isinstance(target, str) or not self.add_alias(str(alias), target):
                bad.append(f"{p.name}: alias {alias} → {target} ignorován")
        for w in bad:
            log.warning(w)
        return bad

    def resolve(self, word: str) -> CommandDef | None:
        k = norm(word)
        if k in self.commands:
            return self.commands[k]
        name = self.aliases.get(k)
        return self.commands[norm(name)] if name else None

    def aliases_of(self, name: str) -> list[str]:
        n = self.resolve(name)
        if n is None:
            return []
        return sorted(self.alias_labels[a] for a, t in self.aliases.items() if t == n.name)

    def names(self) -> list[str]:
        return sorted(c.name for c in self.commands.values())

    def suggest(self, text: str, limit: int = SUGGEST_LIMIT) -> list[Suggestion]:
        """Našeptávač při psaní prvního slova (jako ZWCAD): příkazy, jejichž jméno nebo alias začíná napsaným textem
        (přesná shoda první, pak kratší), za nimi (od `SUGGEST_CONTAINS` znaků) příkazy, které text obsahují ve
        jménu, aliasu nebo českém názvu.
        Každý příkaz jednou – se slovem, které se zapíše (alias, když ho uživatel píše, jinak jméno)."""
        if not text.strip() or " " in text.strip():
            return []
        k = norm(text)
        if not k:
            return []
        words: dict[str, list[tuple[str, str]]] = {}              # příkaz → [(norm slova, slovo)]
        for key, c in self.commands.items():
            words.setdefault(c.name, []).append((key, c.name.upper()))
        for a, target in self.aliases.items():
            words.setdefault(target, []).append((a, self.alias_labels[a]))
        ranked: list[tuple[tuple, Suggestion]] = []
        for name, ws in words.items():
            cmd = self.commands[norm(name)]
            pref = [(len(n), n != k, w) for n, w in ws if n.startswith(k)]
            if pref:
                ln, inexact, w = min(pref, key=lambda t: (t[1], t[0]))
                ranked.append(((0, inexact, ln, w), Suggestion(w, cmd.name, cmd.title)))
            elif len(k) >= SUGGEST_CONTAINS and (any(k in n for n, _w in ws) or k in norm(cmd.title)):
                ranked.append(((1, True, len(name), name), Suggestion(cmd.name.upper(), cmd.name, cmd.title)))
        return [s for _r, s in sorted(ranked, key=lambda t: t[0])[:limit]]

    def complete(self, text: str, ctx=None) -> list[str]:
        """Doplňování (Tab): první slovo → jména příkazů a aliasy; INSERT → id značek knihovny; SET/ATTR → klíče
        atributů výběru („in_a=“). Vrací celé nové znění řádku seřazené."""
        if " " not in text.lstrip():
            k = norm(text)
            out = {c.name.upper() for kk, c in self.commands.items() if kk.startswith(k)}
            out |= {self.alias_labels[a] for a in self.aliases if a.startswith(k)}
            return sorted(out)
        head, _, rest = text.lstrip().partition(" ")
        cmd = self.resolve(head)
        if cmd is None or ctx is None:
            return []
        words = rest.split(" ")
        last = words[-1]
        prefix = text[: len(text) - len(last)]
        cands: list[str] = []
        if cmd.name == "insert" and len(words) == 1 and ctx.library is not None:
            cands = [sid for sid, _n, _c in ctx.library.list_symbols() if sid.startswith(last)]
        elif cmd.name == "set":
            keys = set()
            for e in ctx.selected_elements():
                keys |= set(e.attrs)
                sym = ctx.symbol_of(e)
                if sym is not None:
                    keys |= {a.key for a in sym.attributes}
            cands = [f"{k}=" for k in sorted(keys) if k.startswith(last)]
        elif cmd.name == "sheet":
            cands = [f'"{s.name}"' if " " in s.name else s.name for s in ctx.project.sheets
                     if norm(s.name).startswith(norm(last))]
        return [prefix + c for c in sorted(cands)]
