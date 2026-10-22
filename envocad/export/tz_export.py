"""Technická zpráva a dokumentace skutečného provedení (docx) ze šablony + data pro žádost o připojení k DS.

Šablona (`library/doc_templates.py`: vestavěná `tz.md` / `dsps.md`, sdílená, vlastní nebo libovolný .docx) se vyplní
kontextem z modelu (`tz_data.report_context`) a bloky tabulek (`tz_data.BLOCKS`) – engine `doc_template.py`, návrh
`docs/design/tz_dsps.md`. Chybějící údaj = „neuvedeno“ / vynechaná sekce, export kvůli němu nespadne.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path

from docx.shared import Pt

from envocad.export import doc_template
from envocad.export.docx_export import doc_author, setup_document
from envocad.export.tz_data import (  # noqa: F401 – dřívější API modulu
    BLOCKS,
    _cz,
    _f,
    dso_data,
    report_context,
)
from envocad.library.doc_templates import builtin_template
from envocad.library.store import LibraryStore
from envocad.model.project import Project, without_dangling

TITLES = {"tz": "Technická zpráva", "dsps": "Dokumentace skutečného provedení"}


def export_report_docx(project: Project, lib: LibraryStore, path: Path | str, *, kind: str = "tz",
                       template: Path | str | None = None, old: Project | None = None,
                       fields: Mapping[str, str] | None = None, company: str | None = None,
                       today: date | None = None) -> None:
    """TZ (`kind="tz"`) nebo DSPS (`kind="dsps"`) do .docx. `template` = .docx / .md šablona (None = vestavěná;
    .docx bez polí = podklad se styly, vyplní se vestavěnou osnovou), `old` = projekt dle PD pro změny DSPS,
    `fields` = hodnoty pole.* a dsps_*, `company` = název firmy (None = z firemního standardu)."""
    if kind not in TITLES:
        raise ValueError(f"Neznámý druh dokumentu: {kind}")
    project = without_dangling(project)   # vodiče na neexistující prvek (poškozený soubor) se do zprávy nedostanou
    if old is not None:
        old = without_dangling(old)
    if company is None:
        try:
            from envocad.settings import company as standard_company
            company = standard_company()
        except Exception:  # noqa: BLE001 – vadné nastavení: bez názvu firmy
            company = ""
    doc = doc_template.load_template(template, builtin_template(kind))
    if template is None:
        st = doc.styles["Normal"]
        st.font.name = "Calibri"
        st.font.size = Pt(10)
    m = project.meta
    setup_document(doc, f"{TITLES[kind]} – {project.name}", doc_author(project),
                   " ".join(x for x in (m.get("order", ""), m.get("place", "")) if x))
    ctx = report_context(project, lib, kind=kind, old=old, fields=fields, company=company, today=today)
    doc_template.render(doc, ctx, BLOCKS)
    doc.save(str(path))


def export_tz_docx(project: Project, lib: LibraryStore, path: Path | str, template: Path | str | None = None) -> None:
    """Technická zpráva (dřívější API): vestavěná šablona, nebo `template`."""
    export_report_docx(project, lib, path, kind="tz", template=template)


def export_dsps_docx(project: Project, lib: LibraryStore, path: Path | str, template: Path | str | None = None,
                     old: Project | None = None, fields: Mapping[str, str] | None = None) -> None:
    export_report_docx(project, lib, path, kind="dsps", template=template, old=old, fields=fields)


def save_template_docx(kind: str, path: Path | str) -> None:
    """Vestavěná šablona jako .docx s poli a značkami – základ firemní šablony (upraví se ve Wordu)."""
    doc = doc_template.load_template(builtin_template(kind))
    setup_document(doc, f"Šablona – {TITLES[kind]}")
    doc.save(str(path))
