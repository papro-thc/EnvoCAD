"""Vestavěné příkazy příkazového řádku (bez Qt) a výchozí registr.

Příkaz je generátor: `hodnota = yield Param(...)` se doptá na argument (z řádku, v GUI z klávesnice nebo myší),
změny dělá přes `envocad.cmd.edits` a vrací zprávu pro výstup. Transakci, ChangeSet a návrat při chybě řeší runner.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path

from envocad.cmd import edits
from envocad.cmd.registry import ALIASES_FILE, CommandDef, Param, Registry, norm
from envocad.cmd.runner import CommandError, Ctx
from envocad.model.grid import GRID, snap
from envocad.model.project import FEED_SYMBOLS, SWITCHBOARD_WIRE_ATTRIBUTES, WIRE_ATTRIBUTES, feed_link_attrs

COMMON_ELEMENT_KEYS = {"ref", "desc", "func", "loc"}
TRUE_WORDS = {"1", "true", "ano", "yes", "a", "y"}
FALSE_WORDS = {"0", "false", "ne", "no", "n", ""}


def _fmt(v: float) -> str:
    return f"{v:g}"


def _n(n: int, one: str, few: str, many: str) -> str:
    """Číslo s českým tvarem slova (1 prvek, 2 prvky, 5 prvků)."""
    return f"{n} {one if n == 1 else few if 2 <= n <= 4 else many}"


def _els(n: int) -> str:
    return _n(n, "prvek", "prvky", "prvků")


def _wires(n: int) -> str:
    return _n(n, "vodič", "vodiče", "vodičů")


def _pt(p: tuple[float, float]) -> str:
    return f"{_fmt(p[0])},{_fmt(p[1])}"


def _selection(ctx: Ctx, ids: list[str], elements_only: bool = True) -> list[str]:
    s = ctx.require_sheet()
    known = {e.id for e in s.elements} | (set() if elements_only else {w.id for w in s.wires})
    out = [i for i in ids if i in known]
    if not out:
        raise CommandError("Výběr neobsahuje žádný prvek" if elements_only else "Výběr je prázdný")
    return out


def _bool(key: str, v: str) -> bool:
    t = norm(v)
    if t in TRUE_WORDS:
        return True
    if t in FALSE_WORDS:
        return False
    raise CommandError(f"{key}={v}: čekám 1/0 nebo ano/ne")


def _angle(v: float | str) -> int:
    try:
        a = float(v)
        whole = int(a)
    except (ValueError, OverflowError) as ex:                  # „x“, 1e999 (inf)
        raise CommandError(f"Úhel „{v}“ není číslo") from ex
    if a != whole or whole % 90:
        raise CommandError(f"Úhel {v} není násobek 90°")
    return int(a) % 360


def _element_keys(ctx: Ctx, e) -> set[str]:
    sym = ctx.symbol_of(e)
    feed = {"wire_id"} if e.symbol_id in FEED_SYMBOLS else set()     # vazba z dialogu (výběr vodiče JPS)
    return COMMON_ELEMENT_KEYS | feed | set(e.attrs) | ({a.key for a in sym.attributes} if sym is not None else set())


WIRE_KEYS = {a.key for a in WIRE_ATTRIBUTES + SWITCHBOARD_WIRE_ATTRIBUTES} | {"ref"}


def _check_ref(ctx: Ctx, symbol_id: str, ref: str, self_id: str | None = None) -> None:
    """Označení nesmí kolidovat v prostoru označení listu. Sdílené označení je záměr u skupin svorek (svorkovnice),
    kontaktů (nesou označení cívky), přerušení a u cívky se stykačem kresleným jako její silové kontakty
    (`DUAL_ROLE`). GUI jinou duplicitu po potvrzení dovolí – řádek ji odmítne (skript nemá koho se zeptat)."""
    from envocad.model.project import COIL_SYMBOLS, CONTACT_SYMBOLS, DUAL_ROLE, INTERRUPT_SYMBOL
    if not ref or symbol_id in edits.TERMINAL_SYMBOLS or symbol_id in CONTACT_SYMBOLS or symbol_id == INTERRUPT_SYMBOL:
        return
    s = ctx.require_sheet()
    own = s.element(self_id).ref if self_id else None
    if ref == own or ref not in ctx.project.used_refs(s):
        return
    if symbol_id in COIL_SYMBOLS or symbol_id in DUAL_ROLE:
        partner = set(DUAL_ROLE) if symbol_id in COIL_SYMBOLS else COIL_SYMBOLS
        same = [e for sh in ctx.project.sheets for e in sh.elements if e.ref == ref and e.id != self_id]
        wired = any(w.attrs.get("ref") == ref for sh in ctx.project.sheets for w in sh.wires)
        if same and not wired and all(e.symbol_id in partner or e.symbol_id in CONTACT_SYMBOLS for e in same):
            return
    raise CommandError(f"Označení {ref} už v projektu je")


def _validate_ref(ctx: Ctx, ref: str, element=None) -> None:
    """Označení zadané z řádku jako kontrola F7 (`validate_ref`): chyba zápisu (oddělovač, „-“ na začátku) příkaz
    odmítne, třída podle funkce značky, znaky a délka jen upozorní – v GUI je ukáže až kontrola."""
    from envocad.model.designation import LOCATION_SYMBOLS, validate_ref
    from envocad.model.project import INTERRUPT_SYMBOL, is_contact
    classes, name = None, ""
    if element is not None:
        if is_contact(element) or element.symbol_id == INTERRUPT_SYMBOL:
            return                                  # kontakt nese označení cívky, přerušení vlastní číslování
        sym = ctx.symbol_of(element)
        if sym is not None and element.symbol_id not in LOCATION_SYMBOLS:
            classes, name = sym.classes, sym.name
    for issue in validate_ref(ref, classes, is_wire=element is None, name=name):
        if issue.error:
            raise CommandError(issue.text)
        if not issue.info:
            ctx.log(f"Upozornění: {issue.text}")


def _feed_wire_id(ctx: Ctx, value: str) -> str:
    """`wire_id` přívodu/vývodu z řádku: id nebo označení vodiče nadřazeného listu JPS (`wire_choices`, jako výběr
    v dialogu). Prázdná hodnota = bez vazby."""
    from envocad.model.project import parent_sheet, wire_choices
    if not value:
        return ""
    s = ctx.require_sheet()
    ids = [wid for wid, _ in wire_choices(ctx.project, s)]
    if value in ids:
        return value
    ps = parent_sheet(ctx.project, s)
    hit = [w.id for w in (ps.wires if ps is not None else []) if w.attrs.get("ref") == value]
    if len(hit) == 1:
        return hit[0]
    if not ids:
        raise CommandError("wire_id: list nemá nadřazený list JPS s vodiči (jen list rozvaděče)")
    raise CommandError(f"wire_id={value}: vodič na nadřazeném listu „{ps.name}“ není"
                       + (" jednoznačný" if hit else ""))


def _snap_note(ctx: Ctx, raw: tuple[float, float], snapped: tuple[float, float]) -> None:
    if abs(raw[0] - snapped[0]) > 1e-9 or abs(raw[1] - snapped[1]) > 1e-9:
        ctx.log(f"Bod {_pt(raw)} zaokrouhlen na mřížku {_fmt(GRID)} mm: {_pt(snapped)}")


# ---- příkazy -----------------------------------------------------------------------------------------------------
def cmd_insert(ctx: Ctx):
    s = ctx.require_sheet()
    sid = yield Param("symbol", "symbol", "Id značky:")
    raw = yield Param("point", "point", "Bod vložení:")
    kv = yield Param("attrs", "kv", "Atributy (ref=… rot=… mirror=…):", optional=True, default={})
    kv = dict(kv or {})
    rot = _angle(kv.pop("rot", "0") or "0")
    mirror = _bool("mirror", kv.pop("mirror")) if "mirror" in kv else False
    e = edits.new_element(ctx.project, ctx.library, sid, raw[0], raw[1], rot, mirror)
    _snap_note(ctx, raw, (e.x, e.y))
    bad = sorted(set(kv) - _element_keys(ctx, e))
    if bad:
        raise CommandError(f"Značka {sid} nemá atribut {', '.join(bad)}")
    if "ref" in kv:
        _check_ref(ctx, sid, kv["ref"])
        _validate_ref(ctx, kv["ref"], e)
    if "wire_id" in kv:
        kv["wire_id"] = _feed_wire_id(ctx, kv["wire_id"])
    e.attrs.update(kv)
    if e.symbol_id in FEED_SYMBOLS:              # jako dialog vložení: odkud/kam a kabel z navázaného vodiče JPS
        e.attrs.update(feed_link_attrs(ctx.project, s, e, e.attrs.get("wire_id", "")))
    edits.insert_element(ctx.project, s, e)
    ctx.selection = [e.id]
    ctx.last_point = (e.x, e.y)
    return f"Vloženo {e.ref or sid} ({sid}) v {_pt((e.x, e.y))} na list „{s.name}“"


def cmd_wire(ctx: Ctx):
    s = ctx.require_sheet()
    a = yield Param("from", "port", "Počáteční port (ref:port nebo bod):")
    bends: list[tuple[float, float]] = []
    while True:
        hit = yield Param("to", "port", "Lom nebo cílový port:", optional=True, allow_point=True)
        if hit is None:
            raise CommandError("WIRE – vodič musí končit na portu")
        if hit[0] == "bod":
            p = (snap(hit[1][0]), snap(hit[1][1]))
            _snap_note(ctx, hit[1], p)
            bends.append(p)
            continue
        b = hit
        break
    kv = yield Param("attrs", "kv", "Atributy vodiče (ref=… cross=…):", optional=True, default={})
    if a[0] is b[0] and a[1] == b[1]:
        raise CommandError("WIRE – začátek a konec jsou stejný port")
    w = edits.new_wire(ctx.project, s, a[0], a[1], b[0], b[1])
    bad = sorted(set(kv or {}) - WIRE_KEYS - set(w.attrs))
    if bad:
        raise CommandError(f"Vodič nemá atribut {', '.join(bad)}")
    if kv and kv.get("ref") and kv["ref"] in ctx.project.used_refs(s):
        raise CommandError(f"Označení {kv['ref']} už v projektu je")
    if kv and kv.get("ref"):
        _validate_ref(ctx, kv["ref"])
    w.attrs.update(kv or {})
    w.points = bends
    edits.add_wire(ctx.project, s, w)
    ctx.selection = [w.id]
    return f"Vodič {w.attrs.get('ref', '')} {a[0].ref}:{a[1]} → {b[0].ref}:{b[1]}".replace("  ", " ")


def cmd_move(ctx: Ctx):
    s = ctx.require_sheet()
    sel = yield Param("selection", "selection", "Vyberte prvky:")
    ids = _selection(ctx, sel)
    base = yield Param("base", "point", "Základní bod:")
    target = yield Param("target", "point", "Cílový bod:", base=base)
    raw = (target[0] - base[0], target[1] - base[1])
    d = (snap(raw[0]), snap(raw[1]))
    _snap_note(ctx, raw, d)
    n = edits.move_elements(ctx.project, s, ctx.library, ids, d[0], d[1])
    return f"Posunuto: {_els(n)} o {_pt(d)} mm"


def cmd_copy(ctx: Ctx):
    s = ctx.require_sheet()
    sel = yield Param("selection", "selection", "Vyberte prvky:")
    ids = _selection(ctx, sel)
    base = yield Param("base", "point", "Základní bod:")
    target = yield Param("target", "point", "Cílový bod:", base=base)
    raw = (target[0] - base[0], target[1] - base[1])
    d = (snap(raw[0]), snap(raw[1]))
    _snap_note(ctx, raw, d)
    els, wires = edits.copy_elements(ctx.project, s, ctx.library, ids, d[0], d[1])
    ctx.selection = [e.id for e in els]
    refs = ", ".join(e.ref for e in els if e.ref)
    return f"Zkopírováno: {_els(len(els))} a {_wires(len(wires))} o {_pt(d)} mm" + (f" ({refs})" if refs else "")


def cmd_rotate(ctx: Ctx):
    s = ctx.require_sheet()
    sel = yield Param("selection", "selection", "Vyberte prvky:")
    ids = _selection(ctx, sel)
    base = yield Param("base", "point", "Základní bod <počátek prvku>:", optional=True)
    if base is not None:
        b = (snap(base[0]), snap(base[1]))
        _snap_note(ctx, base, b)
        base = b
    a = yield Param("angle", "number", "Úhel (násobek 90°) <90>:", optional=True, default=90.0, base=base)
    n = edits.rotate_elements(s, ids, _angle(a), base)
    return f"Otočeno: {_els(n)} o {_fmt(a)}°" + (f" kolem {_pt(base)}" if base is not None else "")


def cmd_mirror(ctx: Ctx):
    s = ctx.require_sheet()
    sel = yield Param("selection", "selection", "Vyberte prvky:")
    n = edits.mirror_elements(s, _selection(ctx, sel))
    return f"Zrcadleno: {_els(n)}"


def cmd_delete(ctx: Ctx):
    s = ctx.require_sheet()
    sel = yield Param("selection", "selection", "Vyberte prvky / vodiče:")
    ids = set(_selection(ctx, sel, elements_only=False))
    eids = [e.id for e in s.elements if e.id in ids]
    wids = [w.id for w in s.wires if w.id in ids]
    els, wires = edits.remove_items(s, eids, wids)
    ctx.selection = []
    return f"Smazáno: {_els(len(els))} a {_wires(len(wires))}"


def cmd_set(ctx: Ctx):
    s = ctx.require_sheet()
    sel = yield Param("selection", "selection", "Vyberte prvky / vodiče:")
    ids = _selection(ctx, sel, elements_only=False)
    kv = yield Param("attrs", "kv", "klíč=hodnota:")
    els = [e for e in s.elements if e.id in set(ids)]
    wires = [w for w in s.wires if w.id in set(ids)]
    if "ref" in kv and len(els) + len(wires) > 1:
        raise CommandError("ref lze nastavit jen jednomu prvku (vyberte jeden)")
    for e in els:
        bad = sorted(set(kv) - _element_keys(ctx, e))
        if bad:
            raise CommandError(f"{e.ref or e.symbol_id}: značka {e.symbol_id} nemá atribut {', '.join(bad)}")
        if "ref" in kv:
            _check_ref(ctx, e.symbol_id, kv["ref"], e.id)
            if kv["ref"] != e.ref:
                _validate_ref(ctx, kv["ref"], e)
    for w in wires:
        bad = sorted(set(kv) - WIRE_KEYS - set(w.attrs))
        if bad:
            raise CommandError(f"Vodič {w.attrs.get('ref', '')}: neznámý atribut {', '.join(bad)}")
        if kv.get("ref") and kv["ref"] != w.attrs.get("ref") and kv["ref"] in ctx.project.used_refs(s):
            raise CommandError(f"Označení {kv['ref']} už v projektu je")
        if kv.get("ref") and kv["ref"] != w.attrs.get("ref"):
            _validate_ref(ctx, kv["ref"])
    if "wire_id" in kv and els:
        kv["wire_id"] = _feed_wire_id(ctx, kv["wire_id"])
    # vazba přívodu před označením (jako dialog): přejmenování pak přejmenuje port nově navázaného vodiče
    kv = dict(sorted(kv.items(), key=lambda it: it[0] != "wire_id"))
    n = 0
    for e in els:
        for k, v in kv.items():
            n += edits.set_attr(ctx.project, s, e.id, False, k, v)
    for w in wires:
        for k, v in kv.items():
            n += edits.set_attr(ctx.project, s, w.id, True, k, v)
    what = ", ".join(f"{k}={v}" for k, v in kv.items())
    return f"Nastaveno {what} ({_n(n, 'změna', 'změny', 'změn')})" if n else f"{what}: beze změny"


def _bbox(ctx: Ctx, e) -> tuple[float, float, float, float]:
    from envocad.model.symbol import place_point
    sym = ctx.symbol_of(e)
    x0, y0, x1, y1 = sym.bounds() if sym is not None else (-GRID, -GRID, GRID, GRID)
    pts = [place_point(x, y, e.rotation, e.mirror) for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
    xs = [e.x + p[0] for p in pts]
    ys = [e.y + p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def cmd_select(ctx: Ctx):
    s = ctx.require_sheet()
    first = yield Param("what", "text", "Označení / all / none / W (okno) / klíč=glob:")
    w0 = norm(first)
    if w0 in ("none", "nic"):
        ctx.selection = []
        return "Výběr zrušen"
    if w0 in ("all", "vse"):
        ctx.selection = [e.id for e in s.elements] + [w.id for w in s.wires]
        return f"Vybráno vše: {_els(len(s.elements))}, {_wires(len(s.wires))}"
    if w0 in ("w", "okno", "window"):
        a = yield Param("corner1", "point", "První roh okna:")
        b = yield Param("corner2", "point", "Druhý roh okna:", base=a)
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        inside = set()
        for e in s.elements:
            bx0, by0, bx1, by1 = _bbox(ctx, e)
            if bx0 >= x0 - 1e-9 and by0 >= y0 - 1e-9 and bx1 <= x1 + 1e-9 and by1 <= y1 + 1e-9:
                inside.add(e.id)
        wires = [w.id for w in s.wires if w.a.element_id in inside and w.b.element_id in inside]
        ctx.selection = [e.id for e in s.elements if e.id in inside] + wires
        return f"Vybráno oknem: {_els(len(inside))}, {_wires(len(wires))}"
    words = [first]
    while True:
        t = yield Param("more", "text", "Další označení / filtr:", optional=True)
        if t is None:
            break
        words.append(t)
    pats = [x for x in words if "=" not in x]
    filters = [x.split("=", 1) for x in words if "=" in x]
    ids = ctx.find_refs(pats) if pats else [e.id for e in s.elements] + [w.id for w in s.wires]
    out = []
    els = {e.id: e for e in s.elements}
    wires = {w.id: w for w in s.wires}
    for i in ids:
        obj = els.get(i) or wires.get(i)
        ok = True
        for k, g in filters:
            if k in ("symbol", "znacka"):
                val = obj.symbol_id if i in els else "wire"
            else:
                val = obj.attrs.get(k, "")
            ok = ok and fnmatch.fnmatchcase(val, g)
        if ok:
            out.append(i)
    if not out:
        raise CommandError("Výběru nic neodpovídá")
    ctx.selection = out
    refs = [(els.get(i) or wires.get(i)) for i in out]
    names = ", ".join((x.attrs.get("ref") or getattr(x, "symbol_id", "vodič")) for x in refs[:20])
    return f"Vybráno {len(out)}: {names}" + (" …" if len(out) > 20 else "")


def cmd_sheet(ctx: Ctx):
    which = yield Param("sheet", "text", "Název nebo pořadí listu:", optional=True)
    sheets = ctx.project.sheets
    if which is None:
        for i, s in enumerate(sheets, 1):
            ctx.log(f"{'*' if s is ctx.sheet else ' '} {i}: {s.name}")
        return None
    target = None
    if which.isdigit() and 1 <= int(which) <= len(sheets):
        target = sheets[int(which) - 1]
    else:
        exact = [s for s in sheets if norm(s.name) == norm(which)]
        pref = [s for s in sheets if norm(s.name).startswith(norm(which))]
        target = exact[0] if exact else (pref[0] if len(pref) == 1 else None)
        if target is None and len(pref) > 1:
            raise CommandError(f"List „{which}“ není jednoznačný: {', '.join(s.name for s in pref)}")
    if target is None:
        raise CommandError(f"List „{which}“ neexistuje")
    ctx.sheet = target
    ctx.selection = []
    ctx.last_point = None
    return f"Aktivní list {sheets.index(target) + 1}: {target.name}"


def cmd_undo(ctx: Ctx):
    n = yield Param("count", "number", "Počet kroků <1>:", optional=True, default=1.0)
    ctx.require_end()
    k = ctx.runner.undo(max(1, min(int(n), 10_000)))
    _prune_selection(ctx)
    return f"Zpět: {_n(k, 'krok', 'kroky', 'kroků')}" if k else "Není co vrátit"


def cmd_redo(ctx: Ctx):
    n = yield Param("count", "number", "Počet kroků <1>:", optional=True, default=1.0)
    ctx.require_end()
    k = ctx.runner.redo(max(1, min(int(n), 10_000)))
    _prune_selection(ctx)
    return f"Znovu: {_n(k, 'krok', 'kroky', 'kroků')}" if k else "Není co zopakovat"


def _prune_selection(ctx: Ctx) -> None:
    s = ctx.sheet
    if s is not None:
        alive = {e.id for e in s.elements} | {w.id for w in s.wires}
        ctx.selection = [i for i in ctx.selection if i in alive]


def cmd_checks(ctx: Ctx):
    from envocad.model.checks import check_project
    from envocad.settings import switchboard_paper
    findings = check_project(ctx.project, ctx.library, standard_paper=switchboard_paper())
    ctx.data = [{"severity": f.severity, "sheet": f.sheet_name, "ref": f.ref, "text": f.text, "code": f.code}
                for f in findings]
    for f in findings:
        where = f"„{f.sheet_name}“" + (f" {f.ref}" if f.ref else "")
        ctx.log(f"{f.severity}: {where}: {f.text}")
    from collections import Counter
    c = Counter(f.severity for f in findings)
    return "Kontrola: " + (", ".join(f"{k} {v}" for k, v in sorted(c.items())) if findings else "bez nálezů")


WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def _script_path(ctx: Ctx, arg: str, suffix: str) -> Path:
    """Cesta ze skriptu (SAVE, SCRIPT): relativní ke složce skriptu, jen s příponou `suffix` – skript nepřepíše ani
    nepřečte jiný druh souboru (např. `SAVE ~/.bashrc`, `SCRIPT tajne.txt` s obsahem v hláškách chyb). Síťové cesty
    (`\\\\server\\sdílení` – přihlášení SMB) a alternativní datové proudy (`a.txt:x.ecp`) se odmítnou."""
    if arg.startswith(("\\\\", "//")):
        raise CommandError(f"„{arg}“: síťová cesta není povolená")
    p = Path(arg)
    if ":" in p.as_posix()[2 if p.drive else 0:]:
        raise CommandError(f"„{arg}“: neplatná cesta")
    if p.stem.split(".")[0].upper() in WINDOWS_DEVICES:
        raise CommandError(f"„{arg}“: rezervované jméno zařízení Windows")
    if p.suffix.lower() != suffix:
        raise CommandError(f"„{arg}“: čekám soubor {suffix}")
    return p if p.is_absolute() else (ctx.base_dir or Path.cwd()) / p


def cmd_save(ctx: Ctx):
    arg = yield Param("path", "text", "Soubor (.ecp):", optional=True)
    ctx.require_end()
    opts = ctx.runner.save
    target = opts.target
    if arg:
        target = _script_path(ctx, arg, ".ecp")
    if opts.dry_run:
        return f"--dry-run: neuloženo{f' ({target})' if target else ''}"
    if not opts.allow:
        raise CommandError("Ukládání není povoleno – spusťte s -o soubor nebo --in-place")
    if target is None:
        raise CommandError("SAVE – chybí cesta (a není zadané -o)")
    if opts.deferred:          # CLI: jen cíl zvolený operátorem, zapíše se až po úspěšném konci skriptu
        if opts.target is None or target.resolve() != opts.target.resolve():
            raise CommandError(f"SAVE – z CLI jen do {opts.target or 'cíle -o / --in-place'}")
        return f"Uloží se po dokončení skriptu: {opts.target}"
    if target.is_dir():
        raise CommandError(f"SAVE – {target} je složka")
    same = opts.target is not None and target.resolve() == opts.target.resolve()
    if target.exists() and not same and not opts.overwrite:
        raise CommandError(f"Soubor {target} existuje – přepis jen s --in-place")
    from envocad.cmd.runner import sync_derived
    sync_derived(ctx.project)
    ctx.project.save(target)
    return f"Uloženo: {target}"


def cmd_script(ctx: Ctx):
    arg = yield Param("path", "text", "Skript (.ecs):")
    ctx.require_end()
    from envocad.cmd.runner import Journal
    from envocad.cmd.script import run_script_file
    r = ctx.runner
    p = _script_path(ctx, arg, ".ecs")
    root = r.script_root or ctx.base_dir
    if root is not None and not p.resolve().is_relative_to(root.resolve()):
        raise CommandError(f"Skript {arg}: jen ze složky hlavního skriptu ({root})")
    # celý vnořený skript = jedna transakce a jeden krok historie (jako makro v GUI); UNDO uvnitř má vlastní
    journal = r.journal
    r.journal = Journal()      # i v GUI (bez Journal, historii drží QUndoStack): UNDO uvnitř skriptu vrací jeho řádky
    try:
        rep = run_script_file(r, p, stop_on_error=True)
    finally:
        r.journal = journal
    if not rep.ok:
        raise CommandError(f"Skript {p.name}: {rep.first_error}")
    return f"Skript {p.name}: {_n(rep.count, 'příkaz', 'příkazy', 'příkazů')}"


def _export_target(ctx: Ctx, arg: str, suffix: str) -> Path:
    """Cíl exportu (EXPORT_DXF, EXPORT_PDF, DOC_PDF): jen soubor s příponou `suffix`, ne složka. Ze skriptu (CLI i
    Soubor → Spustit skript…) jen do složky hlavního skriptu, nejvýš `runner.max_exports` exportů za běh a existující
    soubor jen ten, který tentýž běh vytvořil (jinak CLI `--force`) – skript nesmí přepsat cizí PDF / DXF na disku.
    Řádek napsaný ručně v doku omezení nemá (cestu zadává uživatel)."""
    p = _script_path(ctx, arg, suffix)
    r = ctx.runner
    if p.is_dir():
        raise CommandError(f"Export – {p} je složka")
    if r.script_depth > 0:
        root = r.script_root or ctx.base_dir or Path.cwd()
        if not p.resolve().is_relative_to(root.resolve()):
            raise CommandError(f"Export {arg}: jen do složky skriptu ({root})")
        if p.exists() and str(p.resolve()) not in r.exported and not r.save.overwrite:
            raise CommandError(f"Export {arg}: soubor už existuje – skript ho nepřepíše (CLI --force)")
        if r.exports_run >= r.max_exports:
            raise CommandError(f"Skript může exportovat nejvýš {r.max_exports}×")
    return p


def _exported(ctx: Ctx, files) -> None:
    r = ctx.runner
    r.exports_run += 1
    r.exported.update(str(Path(f).resolve()) for f in files)


def cmd_export_dxf(ctx: Ctx):
    arg = yield Param("path", "text", "Soubor (.dxf):")
    ctx.require_end()
    s = ctx.require_sheet()
    p = _export_target(ctx, arg, ".dxf")
    if ctx.runner.save.dry_run:
        return f"--dry-run: neexportováno ({p})"
    from envocad.export.dxf_export import export_multipole_dxf, export_sheet_dxf
    if s.is_switchboard:                         # schéma rozvaděče = vícepól po stranách (jako v GUI)
        files = [str(f) for f in export_multipole_dxf(ctx.project, s, ctx.library, p)]
    else:
        export_sheet_dxf(ctx.project, s, ctx.library, p)
        files = [str(p)]
    _exported(ctx, files)
    ctx.data = {"files": files}
    return f"Exportováno DXF listu „{s.name}“: {files[0]}"


def cmd_export_pdf(ctx: Ctx):
    arg = yield Param("path", "text", "Soubor (.pdf):")
    paper = yield Param("paper", "choice", "Formát <skutečný> (A4 / A3):", optional=True, choices=("A4", "A3"))
    ctx.require_end()
    s = ctx.require_sheet()
    p = _export_target(ctx, arg, ".pdf")
    if ctx.runner.save.dry_run:
        return f"--dry-run: neexportováno ({p})"
    from envocad.export.pdf_export import export_sheet_pdf
    export_sheet_pdf(ctx.project, s, ctx.library, p, paper=paper)
    _exported(ctx, [p])
    ctx.data = {"files": [str(p)]}
    return f"Exportováno PDF listu „{s.name}“: {p}"


def cmd_doc_pdf(ctx: Ctx):
    arg = yield Param("path", "text", "Soubor (.pdf):")
    jps = yield Param("jps_page", "choice", "Listy JPS <podle standardu> (A3 / list):", optional=True,
                      choices=("A3", "list"))
    ctx.require_end()
    p = _export_target(ctx, arg, ".pdf")
    if ctx.runner.save.dry_run:
        return f"--dry-run: neexportováno ({p})"
    from envocad.export.doc_pdf import export_documentation_pdf
    from envocad.export.pdf_export import ensure_qt_app
    ensure_qt_app()
    n = export_documentation_pdf(ctx.project, ctx.library, p, jps_page=jps)
    _exported(ctx, [p])
    ctx.data = {"files": [str(p)], "pages": n}
    return f"Exportována dokumentace ({_n(n, 'strana', 'strany', 'stran')}): {p}"


def cmd_help(ctx: Ctx):
    which = yield Param("command", "text", "Příkaz:", optional=True)
    reg = ctx.runner.registry
    if which:
        c = reg.resolve(which)
        if c is None:
            raise CommandError(f"Neznámý příkaz „{which}“")
        al = ", ".join(reg.aliases_of(c.name))
        ctx.log(f"{c.name.upper()} – {c.title}" + (f" (aliasy {al})" if al else ""))
        if c.usage:
            ctx.log(f"  {c.usage}")
        return None
    for c in sorted(reg.commands.values(), key=lambda c: c.name):
        al = ", ".join(reg.aliases_of(c.name))
        ctx.log(f"{c.name.upper():8} {c.title}" + (f" [{al}]" if al else "") + (" – jen GUI" if c.needs_gui else ""))
    return None


BUILTIN = (
    CommandDef("insert", "Vložit značku", run=cmd_insert, gui_fallback="insert_symbol",
               params=(Param("symbol", "symbol", "Id značky:"), Param("point", "point", "Bod vložení:"),
                       Param("attrs", "kv", "Atributy:", optional=True)),
               usage="INSERT id_značky x,y [ref=F1 rot=90 mirror=1 klíč=hodnota …]"),
    CommandDef("wire", "Vodič", run=cmd_wire, gui_fallback="wire",
               params=(Param("from", "port", "Počáteční port:"), Param("to", "port", "Cílový port:")),
               usage="WIRE F1:2 [x,y lomy …] Q1:1 [ref=W5 klíč=hodnota …] (bod = port do 2,5 mm)"),
    CommandDef("move", "Posunout", run=cmd_move,
               usage="MOVE [výběr] základní_bod cílový_bod (MOVE F1 0,0 @10,0)"),
    CommandDef("copy", "Kopírovat", run=cmd_copy,
               usage="COPY [výběr] základní_bod cílový_bod (kopie dostanou nová označení)"),
    CommandDef("rotate", "Otočit", run=cmd_rotate, usage="ROTATE [výběr] [základní bod] [úhel=90]"),
    CommandDef("mirror", "Zrcadlit", run=cmd_mirror, usage="MIRROR [výběr]"),
    CommandDef("delete", "Smazat", run=cmd_delete, usage="DELETE [výběr] (i vodiče prvků)"),
    CommandDef("set", "Nastavit atributy", run=cmd_set, usage="SET [výběr] klíč=hodnota … (SET F1 ref=F7)"),
    CommandDef("select", "Vybrat", run=cmd_select, transaction=False,
               usage="SELECT F1 Q* | all | none | W x1,y1 x2,y2 | symbol=fve.breaker* in_=16*"),
    CommandDef("sheet", "Aktivní list", run=cmd_sheet, transaction=False, usage="SHEET [název | pořadí]"),
    CommandDef("undo", "Zpět", run=cmd_undo, transaction=False, gui_fallback="undo", usage="UNDO [počet]"),
    CommandDef("redo", "Znovu", run=cmd_redo, transaction=False, gui_fallback="redo", usage="REDO [počet]"),
    CommandDef("checks", "Kontrola projektu", run=cmd_checks, transaction=False, gui_fallback="checks",
               usage="CHECKS (nálezy F7)"),
    CommandDef("save", "Uložit", run=cmd_save, transaction=False, gui_fallback="save",
               usage="SAVE [soubor.ecp] (CLI jen s -o / --in-place)"),
    CommandDef("script", "Spustit skript", run=cmd_script, usage="SCRIPT soubor.ecs"),
    CommandDef("export_dxf", "Export DXF listu", run=cmd_export_dxf, transaction=False, gui_fallback="export_dxf",
               usage="EXPORT_DXF soubor.dxf (aktivní list; rozvaděč jako vícepól)"),
    CommandDef("export_pdf", "Export PDF listu", run=cmd_export_pdf, transaction=False, gui_fallback="export_pdf",
               usage="EXPORT_PDF soubor.pdf [A4 | A3]"),
    CommandDef("doc_pdf", "Celá dokumentace (PDF)", run=cmd_doc_pdf, transaction=False, gui_fallback="doc_pdf",
               usage="DOC_PDF soubor.pdf [A3 | list] (listy JPS zmenšit na A3 / skutečný formát)"),
    CommandDef("help", "Nápověda", run=cmd_help, transaction=False, usage="HELP [příkaz]"),
    CommandDef("zoom", "Zoom", needs_gui=True, gui_fallback="zoom_in"),
    CommandDef("fit", "Celý list", needs_gui=True, gui_fallback="fit"),
)


def default_registry(user_aliases: bool = True) -> Registry:
    """Vestavěné příkazy + výchozí aliasy (`aliases.json`) + uživatelské `~/.envocad/aliases.json` (přepisují
    aliasy, kanonická jména ne)."""
    reg = Registry()
    for c in BUILTIN:
        reg.add(c)
    reg.load_aliases(ALIASES_FILE)
    if user_aliases:
        from envocad.library.store import home_dir
        reg.load_aliases(home_dir() / "aliases.json")
    return reg
