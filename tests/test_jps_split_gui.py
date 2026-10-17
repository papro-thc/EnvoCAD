"""Rozdělené JPS v GUI (offscreen): okno otevře AC list i listy střídačů, přerušovací body kreslí odkaz na protějšek
a otevírání listů nemění model (vazby přívodů přes přerušení jsou ustálené)."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from envocad.generate import build_project
from envocad.library.store import LibraryStore
from envocad.model.project import INTERRUPT_SYMBOL
from envocad.ui.main_window import MainWindow

INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_split_project_opens_all_jps_sheets_without_model_change(app, tmp_path):
    p = build_project({"inverters": [{"ref": f"T{i + 1}", **INV, "strings": [20] * 4} for i in range(3)]})
    before = json.dumps(p.to_dict(), sort_keys=True, ensure_ascii=False)
    w = MainWindow(library=LibraryStore(tmp_path / "lib.db"), project=p)
    w.show()
    w.undo.setClean()
    try:
        jps = [s for s in p.sheets if not s.is_switchboard]
        assert len(jps) == 3
        for s in jps:
            w.open_sheet(s, "schematic")
            app.processEvents()
            assert w.current_sheet is s
            scene = w._jps_scene(s)
            assert any(e.symbol_id == INTERRUPT_SYMBOL for e in s.elements)
            others = [x for x in jps if x is not s]
            for e in (e for e in s.elements if e.symbol_id == INTERRUPT_SYMBOL):
                # odkaz kreslený u přerušení (stejná cesta jako ElementItem) míří na list protějšku
                no = {str(p.sheets.index(x) + 1) for x in others if any(o.ref == e.ref for o in x.elements)}
                xref = scene.element_xref(e)
                assert xref.startswith("→ /") and xref[3:].split(".")[0] in no, (e.ref, xref)
        for s in (x for x in p.sheets if x.is_switchboard and x.loc == "RH"):
            w.open_sheet(s, "multipole")
            app.processEvents()
        assert json.dumps(p.to_dict(), sort_keys=True, ensure_ascii=False) == before
        assert w.undo.isClean()
    finally:
        w.undo.setClean()
        w.close()
