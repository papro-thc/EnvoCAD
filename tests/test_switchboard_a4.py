"""Schéma rozvaděče (vícepól) a plán svorkovnice na stranách A4: volba formátu, rozmístění po logických skupinách
(string = svorky X + pojistka FU + SPD, vývod se svými přístroji se nerozdělí), sběrnice a PE přes strany
s křížovými odkazy, rámeček s popisovým polem na každé straně, PDF listu i dokumentace se smíšenými formáty."""
from __future__ import annotations

import pytest

from envocad.generate import build_project
from envocad.library.store import LibraryStore
from envocad.library.templates import apply_template
from envocad.model import multipole as mp
from envocad.model import multipole_geometry as mg
from envocad.model.frame import (
    MARGIN,
    MARGIN_LEFT,
    frame_geometry,
    inner_box,
    page_label,
    qr_fits,
    title_block_box,
)
from envocad.model.project import Element, Project, Sheet
from envocad.model.textlayout import boxes_overlap, segment_hits_box

INV = {"p_ac": 100, "mppt": 6, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}
A4_PT = (841.89, 595.28)     # A4 na šířku v bodech PDF
A3_PT = (1190.55, 841.89)


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return LibraryStore(tmp_path_factory.mktemp("lib") / "l.db")


@pytest.fixture
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _settings(**kw) -> None:
    from envocad.settings import load_settings, save_settings
    s = load_settings()
    for k, v in kw.items():
        if k == "switchboard_paper":
            s["standard"][k] = v
        else:
            s[k] = v
    save_settings(s)


def _dc(n: int):
    p = build_project({"name": f"DC {n}", "inverters": [{"ref": "T1", **INV, "strings": [20] * n}],
                       "dc": {"route_boxes": 0}})
    return p, p.switchboards()[0]


def _tpl(tid: str, params: dict):
    p = Project()
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, tid, params)
    return p, sb


CASES = {
    "dc4": lambda: _dc(4),
    "dc21": lambda: _dc(21),
    "ac9_bus": lambda: _tpl("ac_fve", {"distribution": "bus", "n_out": "9"}),
    "ac9_svorky": lambda: _tpl("ac_fve", {"distribution": "terminals", "n_out": "9"}),
    "dc9_sablona": lambda: _tpl("dc", {"n_strings": "9"}),
}


def _local(y: float, height: float) -> tuple[int, float]:
    """Strana a souřadnice y uvnitř strany (strany pod sebou s mezerou)."""
    pitch = height + mp.MP_PAGE_GAP
    k = max(0, int((height - y) // pitch))
    return k, y + k * pitch


def _is_pe_only(w) -> bool:
    return all(c in mp.NEVER_SWITCHED for c in mp.wire_conductors(w))


# ---- volba formátu ------------------------------------------------------------------------------------------------
def test_paper_choice_default_standard_sheet_and_legacy():
    p, sb = _tpl("dc", {"n_strings": "2"})
    assert mp.paper_choice(sb) == "A4" and mp.page_size(sb) == (297.0, 210.0) and mp.page_paper_label(sb) == "A4"
    _settings(switchboard_paper="A4 na výšku")
    assert mp.page_size(sb) == (210.0, 297.0) and mp.page_paper_label(sb) == "A4"
    _settings(switchboard_paper="A3")
    assert mp.page_size(sb) == (420.0, 297.0)
    _settings(switchboard_paper="Letter")                     # neplatná hodnota → výchozí A4
    assert mp.paper_choice(sb) == "A4"
    sb.mp_paper = "A3"                                        # volba listu má přednost před standardem
    assert mp.page_size(sb) == (420.0, 297.0)
    sb.mp_paper = "list"
    assert mp.page_size(sb) == (sb.width, sb.height)
    sb.mp_paper = ""
    # starší list s ručně nastaveným formátem nebo s ručními polohami ve vícepólu si nechá rozměr listu
    sb.width = 500.0
    assert mp.paper_choice(sb) == mp.SHEET_PAPER and mp.page_size(sb) == (500.0, 297.0)
    sb.width = 420.0
    sb.elements[0].mp_pos = (100.0, 100.0)
    assert mp.paper_choice(sb) == mp.SHEET_PAPER and mp.page_size(sb) == (420.0, 297.0)
    # vícepól listu JPS (není rozvaděč) má rozměr listu jako dřív
    assert mp.paper_choice(p.sheets[0]) == mp.SHEET_PAPER


def test_sheet_mp_paper_optional_key_roundtrip():
    s = Sheet(kind="switchboard")
    assert "mp_paper" not in s.to_dict()                      # nepovinný klíč – stávající soubory beze změny
    s.mp_paper = "A4 na výšku"
    d = s.to_dict()
    assert d["mp_paper"] == "A4 na výšku" and Sheet.from_dict(d).mp_paper == "A4 na výšku"
    old = Project().to_dict()
    assert Project.from_dict(old).sheets[0].mp_paper == ""


def test_frame_qr_only_when_it_fits_and_page_label():
    p, sb = _tpl("dc", {"n_strings": "2"})
    assert qr_fits(297.0) and qr_fits(420.0) and not qr_fits(210.0)
    land = frame_geometry(p, sb, 297.0, 210.0, "vícepólové schéma", "x", "A4")
    port = frame_geometry(p, sb, 210.0, 297.0, "vícepólové schéma", "x", "A4")
    assert land.rects and not port.rects                     # A4 na výšku: popisové pole přes celou šířku, bez QR
    assert title_block_box(210.0, 297.0)[0] >= MARGIN_LEFT
    assert title_block_box(297.0, 210.0)[0] >= MARGIN_LEFT
    assert any(t[2] == "A4" for t in land.texts)             # formát strany v popisovém poli
    no = page_label(p, sb, 1, 3)
    assert no.endswith("str. 2/3") and no.startswith("2/2") and page_label(p, sb, 0, 1) == "2/2"


# ---- rozmístění po skupinách, rámeček A4 --------------------------------------------------------------------------
@pytest.mark.parametrize("case", list(CASES))
def test_groups_not_split_and_drawing_inside_a4_frame(case, lib):
    _settings(frame=True)
    p, sb = CASES[case]()
    g = mg.multipole_geometry(p, sb, lib)
    W, H = g.page_size
    assert (W, H) == (297.0, 210.0) and g.paper == "A4"
    # žádná skupina mezi stranami: vodič s jinou žílou než PE vede vždy v rámci strany (mimo sběrnici)
    els = {e.id: e for e in sb.elements}
    for w in sb.wires:
        if mp.BUS_SYMBOL in (els[w.a.element_id].symbol_id, els[w.b.element_id].symbol_id) or _is_pe_only(w):
            continue
        assert g.page_of[w.a.element_id] == g.page_of[w.b.element_id], (case, els[w.a.element_id].ref,
                                                                       els[w.b.element_id].ref)
    # všechny texty a čáry uvnitř vnitřního rámečku A4 a mimo popisové pole s QR kódem
    x0, y0, x1, y1 = inner_box(W, H)
    tb = title_block_box(W, H)
    for box, owner, what in g.texts:
        k, ya = _local(box[1], H)
        yb = box[3] + k * (H + mp.MP_PAGE_GAP)
        assert x0 - 1e-6 <= box[0] and box[2] <= x1 + 1e-6 and y0 - 1e-6 <= ya and yb <= y1 + 1e-6, (case, what)
        assert not boxes_overlap((box[0], ya, box[2], yb), tb, 0.0), (case, what)
    for a, b, owner, what in g.lines:
        k, ya = _local(max(a[1], b[1]), H)
        d = k * (H + mp.MP_PAGE_GAP)
        pa, pb = (a[0], a[1] + d), (b[0], b[1] + d)
        for x, y in (pa, pb):
            assert x0 - 1e-6 <= x <= x1 + 1e-6 and y0 - 1e-6 <= y <= y1 + 1e-6, (case, what)
        assert not segment_hits_box(pa, pb, tb, 0.0), (case, what)
    # kontrola překryvů (F7 mp_text_overlap) nad stejnou geometrií nic nehlásí
    assert mg.multipole_text_overlaps(p, sb, lib, g) == [], case


def test_dc_string_fuse_and_spd_on_same_page(lib):
    """Otevřený problém: velký DC rozvaděč (21 stringů) rozdělil pojistku a SPD jednoho stringu na různé strany."""
    p, sb = _dc(21)
    g = mg.multipole_geometry(p, sb, lib)
    els = {e.id: e for e in sb.elements}
    pairs = 0
    for w in sb.wires:
        a, b = els[w.a.element_id], els[w.b.element_id]
        if {a.symbol_id, b.symbol_id} == {"fve.fuse_disconnect", "fve.spd"}:
            assert g.page_of[a.id] == g.page_of[b.id], (a.ref, b.ref)
            pairs += 1
    assert pairs == 21
    assert g.pages == 7                                       # A4 na šířku: 3 stringy na stranu


def test_expected_page_counts(lib):
    assert mg.multipole_geometry(*_dc(4), lib).pages == 2
    assert mg.multipole_geometry(*_tpl("ac_fve", {"distribution": "bus", "n_out": "9"}), lib).pages == 3


# ---- přerušení a křížové odkazy -----------------------------------------------------------------------------------
def test_pe_rail_continues_over_pages_with_refs_to_neighbours(lib):
    p, sb = _dc(21)
    g = mg.multipole_geometry(p, sb, lib)
    no = "2"                                                  # list rozvaděče je 2. list projektu
    rails = sorted(g.rails, key=lambda r: r.page)
    assert [r.page for r in rails] == list(range(g.pages))   # PE sběrná čára na každé straně
    for r in rails:
        for x, y, at_right, ref in r.breaks:
            target = r.page + 1 if at_right else r.page - 1
            assert ref.startswith(f"/{no}.{target + 1}."), (r.page, ref)
            assert (x > 200) == at_right
    assert [b[2] for b in rails[0].breaks] == [True] and [b[2] for b in rails[-1].breaks] == [False]
    # všech 21 PE ze svodičů vede do sběrné čáry, žádné samostatné přerušení PE
    assert len(g.rail_taps) == 21 and not any(c == "PE" for (_w, c) in g.page_breaks)


def test_bus_refs_to_neighbouring_pages(lib):
    p, sb = _tpl("ac_fve", {"distribution": "bus", "n_out": "9"})
    g = mg.multipole_geometry(p, sb, lib)
    (_bus_id, refs), = g.bus_refs.items()
    pages = sorted({k for k, *_ in refs})
    assert pages == list(range(g.pages))
    for k, x, _y, text, align in refs:
        target = k - 1 if align == "right" else k + 1        # vlevo zpět, vpravo dál
        assert text.startswith(f"/2.{target + 1}."), (k, text)
        assert (x < 100) == (align == "right")
    # odkazy jsou na prvních a posledních stranách jen na jedné straně čáry
    assert not [r for r in refs if r[0] == 0 and r[4] == "right"]
    assert not [r for r in refs if r[0] == g.pages - 1 and r[4] == "left"]


def test_single_cross_page_conductor_break_refs(lib):
    p, sb = _dc(4)
    g = mg.multipole_geometry(p, sb, lib)
    assert g.page_breaks                                     # PE 4. stringu do XPE na první straně
    for (wid, _c), ((xa, _ya, ra, ref_a), (xb, _yb, rb, ref_b)) in g.page_breaks.items():
        w = next(x for x in sb.wires if x.id == wid)
        ka, kb = g.page_of[w.a.element_id], g.page_of[w.b.element_id]
        assert ref_a.startswith(f"/2.{kb + 1}.") and ref_b.startswith(f"/2.{ka + 1}.")
        assert ra == (ka < kb) and rb == (not ra)


def test_legacy_sheet_keeps_its_size(lib):
    p, sb = _dc(4)
    sb.elements[0].mp_pos = (60.0, 200.0)                    # starší projekt s ruční polohou ve vícepólu
    g = mg.multipole_geometry(p, sb, lib)
    assert g.page_size == (420.0, 297.0) and g.paper == "A3"


# ---- plán svorkovnice ---------------------------------------------------------------------------------------------
def test_terminal_plan_pages_a4(lib):
    from envocad.model.terminal_plan import BOTTOM_PAD, T_H, sheet_plan_pages, terminal_plan
    p, sb = _dc(21)
    size, pages = sheet_plan_pages(p, sb)
    assert size == (297.0, 210.0)
    x0, y0, x1, y1 = inner_box(*size)
    tb = title_block_box(*size)
    placed = sorted((c.strip, r.number) for pg in pages for c in pg for r in c.rows)
    assert placed == sorted((pl.strip, r.number) for pl in terminal_plan(p, sb) for r in pl.rows)
    for pg in pages:
        for c in pg:
            assert x0 < c.x and c.x + c.width <= x1 + 1e-6
            assert c.top + c.ext_h <= y1 and c.top - T_H - c.int_h >= y0 + BOTTOM_PAD - 1e-6
            assert c.top - T_H - c.int_h > tb[3]                # nad popisovým polem
    # krátké texty DC rozvaděče: dva pásy na stranu A4
    assert any(len({c.top for c in pg}) >= 2 for pg in pages)


# ---- scéna = geometrie, PDF ---------------------------------------------------------------------------------------
def test_scene_uses_model_geometry(qapp, lib):
    from PySide6.QtGui import QUndoStack

    from envocad.ui.multipole_view import MultipoleScene, PageBreakItem, RailItem
    p, sb = _dc(21)
    g = mg.multipole_geometry(p, sb, lib)
    sc = MultipoleScene(p, sb, lib, QUndoStack())
    assert sc.paper_size == (297.0, 210.0) and len(sc.pages) == g.pages
    assert {eid: ep.origin for eid, ep in sc._poles.items()} == g.origins
    items = sc.items()
    texts = sorted(it.text for it in items if isinstance(it, PageBreakItem))
    expect = sorted([b[3] for r in g.rails for b in r.breaks] + [b[3] for v in g.page_breaks.values() for b in v])
    assert texts == expect
    assert len([it for it in items if isinstance(it, RailItem)]) == len(g.rails)


def test_sheet_pdf_pages_are_a4(qapp, lib, tmp_path):
    import pypdf
    from PySide6.QtGui import QUndoStack

    from envocad.export.pdf_export import export_scene_pdf
    from envocad.ui.multipole_view import MultipoleScene
    from envocad.ui.terminal_plan_view import TerminalPlanScene
    p, sb = _dc(21)
    for cls, n in ((MultipoleScene, 7), (TerminalPlanScene, None)):
        sc = cls(p, sb, lib, QUndoStack())
        out = tmp_path / f"{cls.__name__}.pdf"
        export_scene_pdf(sc, out)
        pages = pypdf.PdfReader(out).pages
        assert len(pages) == (n or len(sc.pages))
        for pg in pages:
            assert (round(float(pg.mediabox.width)), round(float(pg.mediabox.height))) == \
                (round(A4_PT[0]), round(A4_PT[1]))


def test_documentation_mixed_formats_and_page_counts(qapp, lib, tmp_path):
    import pypdf

    from envocad.export.doc_pdf import DocBuilder
    _settings(frame=True)
    p, _sb = _dc(4)
    b = DocBuilder(p, lib)
    out = tmp_path / "dok.pdf"
    n = b.export(out)
    pages = pypdf.PdfReader(out).pages
    assert n == len(pages) == sum(b.page_counts)
    assert b.page_starts == [1 + sum(b.page_counts[:i]) for i in range(len(b.pages))]
    for (kind, _name, data), start, cnt in zip(b.pages, b.page_starts, b.page_counts):
        want = A4_PT if kind == "sheet" and data[1] in ("multipole", "terminals") else A3_PT
        for i in range(start - 1, start - 1 + cnt):
            box = pages[i].mediabox
            assert (round(float(box.width)), round(float(box.height))) == (round(want[0]), round(want[1])), \
                (kind, _name, i)
    mp_items = [c for (k, _n, d), c in zip(b.pages, b.page_counts) if k == "sheet" and d[1] == "multipole"]
    assert mp_items[0] == 2                                   # 4 stringy: 3 + 1 na A4


def test_documentation_page_footer_on_a4_pages(qapp, lib, tmp_path):
    """Bez rámečku: „strana n/N“ v pravém dolním rohu i na stranách A4 (uvnitř strany)."""
    import pypdf

    from envocad.export.doc_pdf import DocBuilder
    _settings(frame=False)
    p, _sb = _dc(4)
    b = DocBuilder(p, lib)
    out = tmp_path / "dok.pdf"
    n = b.export(out)
    r = pypdf.PdfReader(out)
    i = next(s for (k, _n, d), s in zip(b.pages, b.page_starts) if k == "sheet" and d[1] == "multipole") - 1
    assert f"strana {i + 1}/{n}" in " ".join(r.pages[i].extract_text().split())


def test_render_a4_page_with_pdfium(qapp, lib, tmp_path):
    """Vyrenderovaná strana vícepólu A4: kresba je uvnitř strany a není prázdná (pypdfium2)."""
    import pypdfium2 as pdfium
    from PySide6.QtGui import QUndoStack

    from envocad.export.pdf_export import export_scene_pdf
    from envocad.ui.multipole_view import MultipoleScene
    _settings(frame=True)
    p, sb = _dc(21)
    out = tmp_path / "mp.pdf"
    export_scene_pdf(MultipoleScene(p, sb, lib, QUndoStack()), out)
    doc = pdfium.PdfDocument(str(out))
    assert len(doc) == 7
    img = doc[3].render(scale=1.0).to_pil().convert("L")
    w, h = img.size
    assert abs(w / h - 297 / 210) < 0.01
    dark = img.point(lambda v: 255 if v < 64 else 0).getbbox()     # šedý obrys papíru scény se nepočítá
    assert dark is not None
    # tmavé pixely jen uvnitř strany (rámeček 10 mm od okraje, souřadnicová síť v okraji)
    mm = w / 297.0
    assert dark[0] >= 5 * mm and dark[2] <= w - 3 * mm and dark[1] >= 3 * mm and dark[3] <= h - 3 * mm


# ---- GUI: formát u listu přes undo, ruční poloha zapíše formát ------------------------------------------------------
def test_sheet_props_paper_undo_and_pin_on_manual_move(qapp, lib):
    from envocad.ui import commands
    from envocad.ui.main_window import MainWindow
    p, sb = _dc(4)
    w = MainWindow(lib, p)
    try:
        w.open_sheet(sb, "multipole")
        sc = w.view.scene()
        assert sc.paper_size == (297.0, 210.0)
        assert w.set_sheet_props(sb, sb.name, sb.func, sb.loc, mp_paper="A3")
        assert sb.mp_paper == "A3" and sc.paper_size == (420.0, 297.0)
        w.undo.undo()
        assert sb.mp_paper == "" and sc.paper_size == (297.0, 210.0)
        # ruční poloha ve vícepólu zapíše k listu platný formát (pozdější změna standardu ji neposune)
        e = sb.elements[0]
        w.undo.push(commands.MoveMultipoleCommand(sc, {e.id: (None, (60.0, 150.0))}))
        assert e.mp_pos == (60.0, 150.0) and sb.mp_paper == "A4" and mp.page_size(sb) == (297.0, 210.0)
        _settings(switchboard_paper="A3")
        assert mp.page_size(sb) == (297.0, 210.0)
        w.undo.undo()
        assert e.mp_pos is None and sb.mp_paper == ""
    finally:
        w.undo.setClean()
        w.close()


def test_sheet_props_dialog_offers_paper_only_for_switchboard(qapp):
    from envocad.ui.dialogs import SheetPropsDialog
    p, sb = _dc(2)
    d = SheetPropsDialog(sb)
    assert d.mp_paper() == ""
    d.paper.setCurrentIndex(d.paper.findData("A4 na výšku"))
    assert d.mp_paper() == "A4 na výšku"
    assert SheetPropsDialog(p.sheets[0]).mp_paper() is None


def test_break_texts_inside_frame_constants():
    """Odkaz přerušení je před šipkou směrem do strany – uvnitř vnitřního rámečku i u pravého okraje."""
    W = 297.0
    x, _y, align = mg.break_text_pos(W - MARGIN - mg.BREAK_INSET, 0.0, True)
    assert align == "right" and x < W - MARGIN
    x, _y, align = mg.break_text_pos(MARGIN_LEFT + mg.BREAK_INSET, 0.0, False)
    assert align == "left" and x > MARGIN_LEFT
