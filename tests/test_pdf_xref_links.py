"""Klikací křížové odkazy v PDF „Celá dokumentace“ (#73): `xref.sheet_xref_links` (model, bez Qt),
`pdf_annots.add_link_annotations` (pypdf) a jejich použití v `DocBuilder.export` – anotace `/Link` v oblasti textu
odkazu (přerušovací bod, odkaz kontaktu na hostitele, řádek zrcadla kontaktů) mířící na stranu cílového listu."""
import json
import os

import pypdf
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from envocad.export.pdf_annots import MM_TO_PT, PageMap
from envocad.library.store import LibraryStore
from envocad.model import xref as X
from envocad.model.frame import doc_page_key
from envocad.model.project import Element, Project, Sheet

TOL_PT = 2 / 25.4 * 72 * 1.5        # ~3 mm: tolerance polohy anotace proti boxu textu


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


# ---- projekty --------------------------------------------------------------------------------------------------
def _interrupt_pair():
    p = Project(name="Odkazy", sheets=[Sheet(name="L1"), Sheet(name="L2")])
    a = Element("fve.interrupt", 100, 150, attrs={"ref": "L1"})
    b = Element("fve.interrupt", 200, 120, attrs={"ref": "L1"})
    p.sheets[0].elements.append(a)
    p.sheets[1].elements.append(b)
    return p, a, b


def _coil_contact():
    """Cívka K1 s kontaktním obrazem na listu A, její kontakt na listu B."""
    p = Project(name="Kontakty", sheets=[Sheet(name="A"), Sheet(name="B")])
    coil = Element("ctl.coil", 150, 200, attrs={"ref": "K1", "contacts": "13/14"})
    contact = Element("ctl.contact_no", 150, 150, attrs={"ref": "K1", "terminals": "13/14"})
    p.sheets[0].elements.append(coil)
    p.sheets[1].elements.append(contact)
    return p, coil, contact


# ---- pomocné funkce ---------------------------------------------------------------------------------------------
def _export(p, lib, path):
    from envocad.export.doc_pdf import export_documentation_pdf
    nums: list = []
    export_documentation_pdf(p, lib, path, page_numbers=nums)
    pages = json.loads(nums[0])["pages"]
    return pypdf.PdfReader(path), {s.id: pages[doc_page_key("schematic", s.id)] - 1 for s in p.sheets}


def _links(reader, page_idx):
    out = []
    for a in reader.pages[page_idx].get("/Annots") or []:
        a = a.get_object()
        if a.get("/Subtype") == "/Link":
            out.append(a)
    return out


def _dest_page(reader, annot) -> int:
    """Index strany, na kterou míří `/Dest` (první prvek pole = nepřímý odkaz na objekt strany)."""
    ref = annot["/Dest"][0]
    for i, pg in enumerate(reader.pages):
        if pg.indirect_reference.idnum == ref.idnum:
            return i
    raise AssertionError("/Dest nemíří na žádnou stranu")


def _expected_rect_pt(reader, page_idx, sheet, box):
    """Box textu (mm listu, Y nahoru) → obdélník na straně (pt) jako u připomínek v `doc_pdf._sheet`."""
    mb = reader.pages[page_idx].mediabox
    w_pt, h_pt = float(mb.width), float(mb.height)
    pm = PageMap.fit(sheet.width, sheet.height, w_pt / MM_TO_PT, h_pt / MM_TO_PT, center=False)
    xs, ys = [], []
    for x, y in ((box[0], box[1]), (box[2], box[3])):
        u, v = pm.to_page_mm(x, y)
        xs.append(u * MM_TO_PT + float(mb.left))
        ys.append(h_pt - v * MM_TO_PT + float(mb.bottom))
    return min(xs), min(ys), max(xs), max(ys)


def _assert_rect_matches(reader, page_idx, annot, sheet, box):
    rect = [float(v) for v in annot["/Rect"]]
    exp = _expected_rect_pt(reader, page_idx, sheet, box)
    assert rect == pytest.approx(exp, abs=TOL_PT)
    mb = reader.pages[page_idx].mediabox
    assert float(mb.left) <= rect[0] < rect[2] <= float(mb.right)
    assert float(mb.bottom) <= rect[1] < rect[3] <= float(mb.top)


def _blank_pdf(path, n_pages=2, w=300.0, h=200.0):
    wr = pypdf.PdfWriter()
    for _ in range(n_pages):
        wr.add_blank_page(width=w, height=h)
    with open(path, "wb") as f:
        wr.write(f)


def _contents(path):
    # prázdná strana (add_blank_page) nemá /Contents → b""
    return [c.get_data() if (c := p.get_contents()) is not None else b"" for p in pypdf.PdfReader(path).pages]


# ---- model: sheet_xref_links (headless) --------------------------------------------------------------------------
def test_sheet_xref_links_interrupt_pair(lib):
    p, a, b = _interrupt_pair()
    la = X.sheet_xref_links(p, p.sheets[0], lib)
    lb = X.sheet_xref_links(p, p.sheets[1], lib)
    assert [(l.sheet_id, l.element_id) for l in la] == [(p.sheets[1].id, b.id)]
    assert [(l.sheet_id, l.element_id) for l in lb] == [(p.sheets[0].id, a.id)]
    for lk, s in ((la[0], p.sheets[0]), (lb[0], p.sheets[1])):
        assert isinstance(lk, X.XrefLink) and lk.text.startswith("→")
        x0, y0, x1, y1 = lk.box
        assert x1 > x0 and y1 > y0
        assert 0 <= x0 and x1 <= s.width and 0 <= y0 and y1 <= s.height


def test_sheet_xref_links_accepts_index_and_layout(lib):
    from envocad.model.textlayout import compute_layout
    p = _interrupt_pair()[0]
    idx = X.DeviceIndex.build(p)
    plain = X.sheet_xref_links(p, p.sheets[0], lib)
    with_args = X.sheet_xref_links(p, p.sheets[0], lib, layout=compute_layout(p, p.sheets[0], lib, index=idx), index=idx)
    assert with_args == plain and len(plain) == 1


def test_sheet_xref_links_contact_and_mirror(lib):
    p, coil, contact = _coil_contact()
    a, b = p.sheets
    # kontakt na listu B → hostitel (cívka) na listu A
    lb = X.sheet_xref_links(p, b, lib)
    assert [(l.sheet_id, l.element_id) for l in lb] == [(a.id, coil.id)]
    # cívka na listu A: řádek zrcadla „13/14 /2.…“ → kontakt na listu B
    la = X.sheet_xref_links(p, a, lib)
    assert [(l.sheet_id, l.element_id) for l in la] == [(b.id, contact.id)]
    assert "13/14" in la[0].text
    # box řádku zrcadla leží v geometrii zrcadla hostitele
    geom = X.sheet_mirrors(p, a, lib)[coil.id]
    bx0, by0, bx1, by1 = geom.bounds
    x0, y0, x1, y1 = la[0].box
    assert x1 > x0 and y1 > y0
    assert bx0 - 0.5 <= x0 and x1 <= bx1 + 0.5 and by0 - 0.5 <= y0 and y1 <= by1 + 0.5


def test_sheet_xref_links_skip_unresolved(lib):
    # osamělý přerušovací bod („→ ?“)
    p = Project(sheets=[Sheet(name="L1")])
    p.sheets[0].elements.append(Element("fve.interrupt", 100, 150, attrs={"ref": "L1"}))
    assert X.sheet_xref_links(p, p.sheets[0], lib) == []
    # rezerva kontaktního obrazu bez kontaktu (řádek zrcadla bez odkazu) + osamělý kontakt („→ ?“)
    q = Project(sheets=[Sheet(name="A")])
    q.sheets[0].elements.append(Element("ctl.coil", 150, 200, attrs={"ref": "K1", "contacts": "13/14 21/22"}))
    assert X.sheet_mirrors(q, q.sheets[0], lib)                      # zrcadlo s rezervami se kreslí…
    assert X.sheet_xref_links(q, q.sheets[0], lib) == []            # …ale nic nelinkuje
    q.sheets[0].elements.append(Element("ctl.contact_no", 50, 50, attrs={"ref": "Q9", "terminals": "13/14"}))
    assert X.sheet_xref_links(q, q.sheets[0], lib) == []


def test_sheet_xref_links_chain_has_both_directions(lib):
    p = Project(sheets=[Sheet(name=f"L{i}") for i in range(3)])
    pts = [Element("fve.interrupt", 100 + 10 * i, 150, attrs={"ref": "N"}) for i in range(3)]
    for s, e in zip(p.sheets, pts, strict=True):
        s.elements.append(e)
    mid = X.sheet_xref_links(p, p.sheets[1], lib)
    assert {(l.sheet_id, l.element_id) for l in mid} == {(p.sheets[0].id, pts[0].id), (p.sheets[2].id, pts[2].id)}


# ---- add_link_annotations (jednotkově) ---------------------------------------------------------------------------
def test_add_link_annotations_rect_dest_and_count(tmp_path):
    from envocad.export.pdf_annots import add_link_annotations
    f = tmp_path / "a.pdf"
    _blank_pdf(f, 3)
    h_mm = 200 / MM_TO_PT
    pm = PageMap(1.0, 0.0, 0.0, h_mm)
    n = add_link_annotations(f, [(0, pm, [((10, 20, 30, 25), 2), ((40, 50, 60, 55), 1)]), (1, pm, [((5, 5, 15, 9), 0)])])
    assert n == 3
    r = pypdf.PdfReader(f)
    a0 = _links(r, 0)
    assert len(a0) == 2 and _links(r, 2) == []
    assert [_dest_page(r, a) for a in a0] == [2, 1]
    assert [float(v) for v in a0[0]["/Rect"]] == pytest.approx([10 * MM_TO_PT, 20 * MM_TO_PT, 30 * MM_TO_PT, 25 * MM_TO_PT], abs=0.01)
    a1 = _links(r, 1)
    assert len(a1) == 1 and _dest_page(r, a1[0]) == 0
    for a in a0 + a1:
        assert a["/Subtype"] == "/Link"
        assert a["/Dest"][1] in ("/XYZ", "/Fit")
        assert [float(v) for v in a["/Border"]] == [0, 0, 0]


def test_add_link_annotations_scaled_pagemap(tmp_path):
    from envocad.export.pdf_annots import add_link_annotations
    f = tmp_path / "s.pdf"
    _blank_pdf(f, 2)
    pm = PageMap.fit(420, 297, 300 / MM_TO_PT, 200 / MM_TO_PT)       # list A3 zmenšený na stranu 300×200 pt
    assert add_link_annotations(f, [(0, pm, [((0, 0, 420, 297), 1)])]) == 1
    rect = [float(v) for v in _links(pypdf.PdfReader(f), 0)[0]["/Rect"]]
    s = pm.scale
    assert rect == pytest.approx([0, 200 - 297 * s * MM_TO_PT, 420 * s * MM_TO_PT, 200], abs=0.01)


def test_add_link_annotations_nothing_to_add_keeps_file(tmp_path):
    from envocad.export.pdf_annots import add_link_annotations
    f = tmp_path / "e.pdf"
    _blank_pdf(f, 2)
    raw = f.read_bytes()
    pm = PageMap(1.0, 0.0, 0.0, 70.0)
    assert add_link_annotations(f, []) == 0
    assert add_link_annotations(f, [(0, pm, [])]) == 0
    assert f.read_bytes() == raw


# ---- export celé dokumentace -------------------------------------------------------------------------------------
def test_documentation_pdf_interrupt_links(app, lib, tmp_path):
    p = _interrupt_pair()[0]
    r, page_of = _export(p, lib, tmp_path / "ip.pdf")
    for src, dst in ((p.sheets[0], p.sheets[1]), (p.sheets[1], p.sheets[0])):
        links = _links(r, page_of[src.id])
        assert len(links) == 1
        assert _dest_page(r, links[0]) == page_of[dst.id]
        (xl,) = X.sheet_xref_links(p, src, lib)
        _assert_rect_matches(r, page_of[src.id], links[0], src, xl.box)


def test_documentation_pdf_contact_and_mirror_links(app, lib, tmp_path):
    p = _coil_contact()[0]
    sa, sb = p.sheets
    r, page_of = _export(p, lib, tmp_path / "cm.pdf")
    # list B: odkaz kontaktu na hostitele (cívku) na listu A
    lb = _links(r, page_of[sb.id])
    assert len(lb) == 1 and _dest_page(r, lb[0]) == page_of[sa.id]
    (xb,) = X.sheet_xref_links(p, sb, lib)
    _assert_rect_matches(r, page_of[sb.id], lb[0], sb, xb.box)
    # list A: řádek zrcadla pod cívkou → kontakt na listu B
    la = _links(r, page_of[sa.id])
    assert len(la) == 1 and _dest_page(r, la[0]) == page_of[sb.id]
    (xa,) = X.sheet_xref_links(p, sa, lib)
    _assert_rect_matches(r, page_of[sa.id], la[0], sa, xa.box)


def test_documentation_pdf_links_independent_of_notes(app, lib, tmp_path):
    from envocad.export.doc_pdf import export_documentation_pdf
    p = _interrupt_pair()[0]
    f = tmp_path / "nn.pdf"
    export_documentation_pdf(p, lib, f, notes=False)
    r = pypdf.PdfReader(f)
    assert sum(len(_links(r, i)) for i in range(len(r.pages))) == 2


def test_documentation_pdf_without_xrefs_has_no_links(app, lib, tmp_path):
    p = Project(name="Bez odkazů", sheets=[Sheet(name="L1")])
    r, _ = _export(p, lib, tmp_path / "no.pdf")
    assert all(_links(r, i) == [] for i in range(len(r.pages)))


# ---- vzhled se nemění --------------------------------------------------------------------------------------------
def test_add_link_annotations_keeps_page_content(tmp_path):
    from envocad.export.pdf_annots import add_link_annotations
    f = tmp_path / "c.pdf"
    _blank_pdf(f, 2)
    before = _contents(f)
    sizes = [tuple(float(v) for v in pg.mediabox) for pg in pypdf.PdfReader(f).pages]
    assert add_link_annotations(f, [(0, PageMap(1.0, 0.0, 0.0, 70.0), [((10, 10, 40, 14), 1)])]) == 1
    assert _contents(f) == before
    assert [tuple(float(v) for v in pg.mediabox) for pg in pypdf.PdfReader(f).pages] == sizes


def test_documentation_pdf_links_keep_content_and_bookmarks(app, lib, tmp_path):
    from envocad.export.pdf_annots import add_link_annotations
    p = _interrupt_pair()[0]
    f = tmp_path / "k.pdf"
    r, page_of = _export(p, lib, f)
    titles = [o.title for o in r.outline]
    assert "Titulní list" in titles and "Změnový list" in titles
    before = _contents(f)
    pm = PageMap(1.0, 0.0, 0.0, 297.0)
    assert add_link_annotations(f, [(0, pm, [((10, 10, 40, 14), 1)])]) == 1     # další průchod pypdf
    assert _contents(f) == before
    r2 = pypdf.PdfReader(f)
    assert [o.title for o in r2.outline] == titles
    assert len(_links(r2, page_of[p.sheets[0].id])) == 1                          # původní odkazy přežily
