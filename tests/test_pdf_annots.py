"""Anotace připomínek v PDF (pypdf, bez Qt): převod souřadnic, /Text a /Square, popup, odpověď u vyřešených."""
import pypdf
import pytest

from envocad.export.pdf_annots import (
    MM_TO_PT,
    PageMap,
    add_note_annotations,
    note_rect_pt,
    pdf_date,
)
from envocad.model.project import Note

A3_W, A3_H = 420 * MM_TO_PT, 297 * MM_TO_PT


def _blank_pdf(path, n_pages=2, w=A3_W, h=A3_H):
    wr = pypdf.PdfWriter()
    for _ in range(n_pages):
        wr.add_blank_page(width=w, height=h)
    with open(path, "wb") as f:
        wr.write(f)


def _annots(path, page):
    r = pypdf.PdfReader(path)
    return [a.get_object() for a in (r.pages[page].get("/Annots") or [])]


def test_pagemap_flips_y():
    pm = PageMap(1.0, 0.0, 0.0, 297.0)
    assert pm.to_page_mm(0, 297) == (0, 0)        # levý horní roh listu = levý horní roh strany
    assert pm.to_page_mm(10, 0) == (10, 297)
    pm2 = PageMap(0.5, 5.0, 7.0, 100.0)
    assert pm2.to_page_mm(20, 40) == (15.0, 37.0)


def test_pagemap_fit_top_left_like_scene_render():
    # QGraphicsScene.render(KeepAspectRatio) nevystředí: list u levého horního rohu strany (ověřeno
    # rasterizací v test_export_content.py::test_scene_pdf_note_annotations_match_render)
    pm = PageMap.fit(480, 297, 420, 297)          # list 480×297 na A3: zmenšit podle šířky, dole volno
    assert pm.scale == pytest.approx(420 / 480) and pm.tx == 0 and pm.ty == 0
    assert pm.to_page_mm(0, 297) == pytest.approx((0, 0))                  # levý horní roh listu = roh strany
    assert pm.to_page_mm(480, 0) == pytest.approx((420, 297 * 420 / 480))  # pravý dolní nad spodkem strany
    pm = PageMap.fit(420, 297, 297, 210)          # A3 na A4: omezí výška, vpravo volno
    assert pm.scale == pytest.approx(210 / 297) and pm.tx == 0 and pm.ty == 0
    # vystředění jen na vyžádání (cíl renderu by musel být vystředěný)
    pm = PageMap.fit(480, 297, 420, 297, center=True)
    assert pm.tx == 0 and pm.ty == pytest.approx((297 - 297 * 420 / 480) / 2)
    assert PageMap.fit(420, 297, 297, 210, center=True).tx == pytest.approx((297 - 420 * 210 / 297) / 2)


def test_note_rect_pt():
    pm = PageMap(1.0, 0.0, 0.0, 297.0)
    x0, y0, x1, y1 = note_rect_pt(Note("s", 10, 20, w=30, h=15), pm, A3_H)
    # model Y nahoru = PDF Y nahoru: levý dolní roh listu (0, 0) je levý dolní roh strany
    assert (x0, y0) == pytest.approx((10 * MM_TO_PT, 20 * MM_TO_PT))
    assert (x1, y1) == pytest.approx((40 * MM_TO_PT, 35 * MM_TO_PT))
    px0, py0, px1, py1 = note_rect_pt(Note("s", 10, 20), pm, A3_H)
    assert (px0, py0) == pytest.approx((10 * MM_TO_PT, 20 * MM_TO_PT)) and px1 > px0 and py1 > py0


def test_pdf_date():
    assert pdf_date("2026-10-16T14:05") == "D:202610161405"
    assert pdf_date("") == "" and pdf_date("nic") == ""


def test_annotations_on_blank_pdf(tmp_path):
    f = tmp_path / "a.pdf"
    _blank_pdf(f)
    pm = PageMap(1.0, 0.0, 0.0, 297.0)
    point = Note("s", 100, 200, "Zkontrolovat průřez", no=1, author="Patrik Ř.", created="2026-10-16T14:05")
    rect = Note("s", 50, 50, "Obdélník", no=2, w=40, h=20)
    n = add_note_annotations(f, [(1, pm, [point, rect])], project_name="FVE Test")
    assert n == 2
    assert _annots(f, 0) == []
    an = _annots(f, 1)
    main = [a for a in an if a["/Subtype"] in ("/Text", "/Square")]
    popups = [a for a in an if a["/Subtype"] == "/Popup"]
    assert len(main) == 2 and len(popups) == 2
    t = next(a for a in main if a["/Subtype"] == "/Text")
    assert t["/Contents"] == "Zkontrolovat průřez" and t["/T"] == "Patrik Ř."
    assert t["/Subj"] == "Připomínka č. 1" and t["/NM"] == f"envocad:{point.id}"
    assert t["/M"] == "D:202610161405" and t["/F"] == 4 and "/Popup" in t
    assert t["/Popup"].get_object()["/Parent"].get_object()["/NM"] == t["/NM"]
    assert [float(v) for v in t["/Rect"][:2]] == pytest.approx([100 * MM_TO_PT, 200 * MM_TO_PT], abs=0.01)
    sq = next(a for a in main if a["/Subtype"] == "/Square")
    assert sq["/T"] == "FVE Test"                 # bez autora → název projektu
    assert [float(v) for v in sq["/Rect"]] == pytest.approx(
        [50 * MM_TO_PT, 50 * MM_TO_PT, 90 * MM_TO_PT, 70 * MM_TO_PT], abs=0.01)
    assert not any("/IRT" in a for a in an)       # otevřené nemají odpověď


def test_resolved_gets_completed_reply(tmp_path):
    f = tmp_path / "r.pdf"
    _blank_pdf(f, 1)
    n = Note("s", 10, 10, "Opravit", no=5, status="resolved", reply="Opraveno v rev. B", resolved_by="JN",
             resolved="2026-10-17T08:00")
    assert add_note_annotations(f, [(0, PageMap(1, 0, 0, 297), [n])]) == 1
    an = _annots(f, 0)
    reply = next(a for a in an if "/IRT" in a)
    assert reply["/IRT"].get_object()["/NM"] == f"envocad:{n.id}"
    assert reply["/StateModel"] == "Review" and reply["/State"] == "Completed"
    assert reply["/Contents"] == "Opraveno v rev. B" and reply["/T"] == "JN" and reply["/M"] == "D:202610170800"


def test_page_height_from_mediabox(tmp_path):
    """Y se otáčí podle výšky strany v MediaBoxu (A4 na šířku), ne podle předpokladu A3."""
    f = tmp_path / "a4.pdf"
    h = 210 * MM_TO_PT
    _blank_pdf(f, 1, w=297 * MM_TO_PT, h=h)
    pm = PageMap(1.0, 0.0, 0.0, 210.0)
    add_note_annotations(f, [(0, pm, [Note("s", 0, 210, "roh", w=10, h=0.0)])])
    t = _annots(f, 0)[0]
    assert float(t["/Rect"][1]) == pytest.approx(h, abs=0.01)


def test_nothing_to_add_keeps_file(tmp_path):
    f = tmp_path / "e.pdf"
    _blank_pdf(f, 1)
    before = f.read_bytes()
    assert add_note_annotations(f, []) == 0
    assert add_note_annotations(f, [(0, PageMap(1, 0, 0, 297), [])]) == 0
    assert f.read_bytes() == before
    with pytest.raises(IndexError):
        add_note_annotations(f, [(3, PageMap(1, 0, 0, 297), [Note("s", 0, 0)])])
