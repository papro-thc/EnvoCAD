"""Rozmístění blokového schématu (JPS) na list a jeho rozdělení na listy střídačů (bez Qt). Návrh
`docs/design/dluhy_dxf_jps.md`, bod B; přesun 1:1 z `generate.py` (refaktoring F1, krok 3)."""
from __future__ import annotations

import re

from envocad.generator import context
from envocad.generator.context import _s
from envocad.model.project import Element, Project, Sheet, Wire, WireEnd


def jps_max_paper() -> str:
    """Největší formát jednoho listu JPS z firemního standardu (`standard.jps_max_paper`, výchozí „A2“)."""
    from envocad.settings import load_settings
    try:
        return str(load_settings()["standard"].get("jps_max_paper") or "A2")
    except (OSError, ValueError, KeyError, TypeError):
        return "A2"


JPS_AC_SUFFIX = "AC a připojení"
JPS_AC_SHEET_NAME = "Blokové schéma – " + JPS_AC_SUFFIX   # list generátoru se jmenuje „Blokové schéma“
INTERRUPT_GAP_INV = 15.0   # AC port střídače → port přerušovacího bodu na listu střídače (mm)
INTERRUPT_GAP_BLOCK = 30.0  # port bloku rozvaděče v řadě střídače → přerušovací bod (místo pro odkaz vazby vývodu)
INTERRUPT_GAP_AC = 60.0    # port přerušovacího bodu → port bloku AC rozvaděče (místo pro popisek AC kabelu)


def _place_jps(p: Project, s: Sheet, opts: dict, rows: list[list[Element]], ac_wires: list[Wire],
               blk: Element) -> None:
    """Rozmístí JPS na list (`frame.fit_placement`). Přesáhl by jeden list `jps.max_paper` (jinak standard
    `jps_max_paper`, výchozí A2) a `jps.split` není „none“, rozdělí se JPS na listy formátu `jps.paper` (výchozí
    = limit; jen při 2+ střídačích): první list „AC a připojení“ (blok AC rozvaděče, síť, HOP) jako přehled, za ním
    listy střídačů (stringy → DC rozvaděče → střídač, baterie) balené hladově, dokud se vejdou. Řez vede AC kabelem:
    pár `fve.interrupt` „AC-T1“; údaje kabelu nese jen úsek u bloku AC rozvaděče, úsek u střídače je pokračování bez
    označení a kabelu (`xref.is_blank_wire`).

    Výjimka: řada jednoho střídače (DC řetězec se nedělí), která se sama nevejde ani na `jps.paper`, dostane svůj
    list v nejmenším normalizovaném formátu, do kterého se vejde (A1, A0, jinak „vlastní“) – limit tedy platí pro
    balení řad, ne pro jednu přerostlou řadu (např. 3 střídače × 12 stringů: listy střídačů A1, AC list A2)."""
    from envocad.model.frame import PAPER_SIZES, apply_placement, fit_placement, paper_exceeds
    from envocad.model.textlayout import sheet_content_boxes
    lib = context._lib()
    boxes = sheet_content_boxes(p, s, lib)
    if not boxes:
        return
    placement = fit_placement(boxes)
    limit = _s(opts.get("max_paper")) or jps_max_paper()
    if (_s(opts.get("split")) or "auto") == "none" or len(rows) < 2 or not paper_exceeds(placement[0], limit):
        apply_placement(s, placement)     # jeden střídač: DC řetězec se nedělí, oddělit jen AC část nemá smysl
        return
    paper = _s(opts.get("paper")) or limit
    sizes = [x for x in PAPER_SIZES if x[0] == paper] or [x for x in PAPER_SIZES if x[0] == "A2"]
    sheets = _split_jps(p, s, rows, ac_wires, blk, sizes)
    for sh in [s, *sheets]:
        bx = sheet_content_boxes(p, sh, lib)
        if bx:
            pl = fit_placement(bx, sizes)
            if pl[0] == "vlastní":        # řada střídače sama přesahuje formát listu → nejmenší normalizovaný
                pl = fit_placement(bx)
            apply_placement(sh, pl)


def _split_jps(p: Project, s: Sheet, rows: list[list[Element]], ac_wires: list[Wire], blk: Element,
               sizes) -> list[Sheet]:
    """Přesune řady střídačů z `s` na nové listy (hned za `s`) a vodiče mezi řadou a zbytkem listu (AC kabel; u
    rodinného domu i DC vodiče přes rozvaděč FVE, který zůstává na listu „AC a připojení“) přeruší párem
    přerušovacích bodů; `s` zůstane listem „AC a připojení“. Vrací listy střídačů v pořadí."""
    from envocad.model.frame import fit_placement
    from envocad.model.project import INTERRUPT_SYMBOL, element_symbol
    from envocad.model.symbol import rotate_dir
    from envocad.model.textlayout import sheet_content_boxes
    lib = context._lib()
    base = s.name or "Blokové schéma"
    s.name = f"{base} – {JPS_AC_SUFFIX}"
    sym_int = lib.get_symbol(INTERRUPT_SYMBOL)
    port_dx = sym_int.port("1").x            # port přerušovacího bodu vlevo od jeho středu (rotace 0)
    ac_ids = {w.id for w in ac_wires}

    def side(e: Element, port: str) -> tuple[float, float, int]:
        """Poloha portu a směr ven (+1 vpravo, −1 vlevo) – přerušovací bod stojí ve směru vodiče od portu."""
        sym = element_symbol(p, e, lib)
        x, y = e.port_pos(sym, port)
        d = rotate_dir(sym.port(port).dir, e.rotation)
        if e.mirror and d in ("E", "W"):
            d = "W" if d == "E" else "E"
        return x, y, (-1 if d == "W" else 1)

    def interrupt(e: Element, port: str, ref: str, gap: float) -> Element:
        x, y, sgn = side(e, port)
        # rotace 0: port vlevo, šipka vpravo (bod vpravo od portu); 180: port vpravo, šipka vlevo
        i = Element(INTERRUPT_SYMBOL, x + sgn * (gap - port_dx), y, rotation=0 if sgn > 0 else 180,
                    attrs={"ref": ref})
        return i

    moves: list[tuple[set[str], list[Wire]]] = []       # (id prvků řady, vodiče řady) pro každý střídač
    for row in rows:
        t = row[0]
        row_ids = {e.id for e in row}
        new_ids: set[str] = set()
        # každý vodič mezi řadou a zbytkem listu (AC kabel k bloku AC rozvaděče; u rodinného domu i DC vodiče
        # stringů do rozvaděče FVE a z něj do střídače) se přeruší párem přerušovacích bodů; údaje kabelu zůstávají
        # u úseku mimo řadu (list „AC a připojení“), úsek u řady je prázdné pokračování
        for w in [w for w in s.wires if (w.a.element_id in row_ids) != (w.b.element_id in row_ids)]:
            inside, outside = (w.a, w.b) if w.a.element_id in row_ids else (w.b, w.a)
            e_in, e_out = s.element(inside.element_id), s.element(outside.element_id)
            ref = f"AC-{t.ref}" if w.id in ac_ids else f"{e_out.ref or 'P'}-{outside.port}"
            # u bloku rozvaděče (DC rozvaděč po trase) má úsek odkaz vazby na vývod („/5.A1“) – delší úsek
            i_in = interrupt(e_in, inside.port, ref,
                             INTERRUPT_GAP_BLOCK if e_in.symbol_id == "fve.switchboard" else INTERRUPT_GAP_INV)
            i_out = interrupt(e_out, outside.port, ref, INTERRUPT_GAP_AC)
            s.elements += [i_in, i_out]
            s.wires.append(Wire(WireEnd(e_in.id, inside.port), WireEnd(i_in.id, "1"), conductors=list(w.conductors),
                                attrs={"ref": ""}))
            if inside is w.a:
                w.a = WireEnd(i_out.id, "1")
            else:
                w.b = WireEnd(i_out.id, "1")
            w.points = []                    # přerušovací bod stojí na výšce portu – vodič vede rovně
            new_ids.add(i_in.id)
        ids = row_ids | new_ids
        moves.append((ids, [w for w in s.wires if w.a.element_id in ids and w.b.element_id in ids]))

    def move(src: Sheet, dst: Sheet, ids: set[str], wires: list[Wire]) -> None:
        dst.elements += [e for e in src.elements if e.id in ids]
        src.elements = [e for e in src.elements if e.id not in ids]
        wset = {w.id for w in wires}
        dst.wires += [w for w in src.wires if w.id in wset]
        src.wires = [w for w in src.wires if w.id not in wset]

    def new_sheet(after: Sheet) -> Sheet:
        sh = Sheet(name=base, func=s.func, loc=s.loc)
        p.sheets.insert(p.sheets.index(after) + 1, sh)
        return sh

    def fits(sh: Sheet) -> bool:
        bx = sheet_content_boxes(p, sh, lib)
        return not bx or fit_placement(bx, sizes)[0] != "vlastní"

    sheets: list[Sheet] = []
    groups: list[list[int]] = []
    for i, (ids, wires) in enumerate(moves):
        if not sheets:
            sheets.append(new_sheet(s))
            groups.append([])
        cur = sheets[-1]
        move(s, cur, ids, wires)
        groups[-1].append(i)
        if len(groups[-1]) > 1 and not fits(cur):     # řada se nevešla – začne nový list
            nxt = new_sheet(cur)
            move(cur, nxt, ids, wires)
            groups[-1].pop()
            sheets.append(nxt)
            groups.append([i])
    for sh, grp in zip(sheets, groups):
        sh.name = f"{base} – " + ref_ranges([rows[i][0].ref for i in grp])
    return sheets


def ref_ranges(refs: list[str]) -> str:
    """Označení do názvu listu: souvislé řady 3+ stejné předpony jako rozsah („T1–T9“), jinak výčet
    („T1, T2“, „T1–T3, T5“). Pořadí se zachová."""
    out: list[str] = []
    run: list[tuple[str, int, str]] = []          # (předpona, číslo, označení)

    def flush() -> None:
        if len(run) >= 3:
            out.append(f"{run[0][2]}–{run[-1][2]}")
        else:
            out.extend(r[2] for r in run)
        run.clear()

    for ref in refs:
        m = re.fullmatch(r"(.*?)(\d+)", ref)
        if m and run and run[-1][0] == m.group(1) and run[-1][1] + 1 == int(m.group(2)):
            run.append((m.group(1), int(m.group(2)), ref))
            continue
        flush()
        if m:
            run.append((m.group(1), int(m.group(2)), ref))
        else:
            out.append(ref)
    flush()
    return ", ".join(out)
