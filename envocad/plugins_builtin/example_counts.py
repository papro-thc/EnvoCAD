"""Ukázkový plugin: položka menu Nástroje → Statistika projektu. Slouží jako vzor pro vlastní pluginy."""
from __future__ import annotations


def register(ctx) -> None:
    def show_stats(win) -> None:
        from PySide6.QtWidgets import QMessageBox
        p = win.project
        n_el = sum(len(s.elements) for s in p.sheets)
        n_w = sum(len(s.wires) for s in p.sheets)
        QMessageBox.information(win, "Statistika projektu",
                                f"{p.name}\n{len(p.sheets)} listů, {n_el} prvků, {n_w} vodičů, "
                                f"{len(p.switchboards())} rozvaděčů")

    ctx.add_menu_action("Nástroje", "Statistika projektu", show_stats)
