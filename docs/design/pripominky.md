# Návrh: připomínkování (redlining), formát v9

Návrh agenta `architekt` (10/2026), schválil orchestrátor. Roadmapa „Z rešerše EPLAN 2026“, bod Připomínkování.

## 0. Výchozí stav
- Vzor: revize (`Project.revisions`, `RevisionMark` se `sheet_id`/`target_id`, geometrie v modelu, `draw_revision_marks`,
  DXF vrstva `REVIZE`, undo `ReplaceRevisionsCommand`).
- PDF vzniká přes `QPdfWriter` + `scene.render()` (`export/pdf_export.py`, `export/doc_pdf.py` – `DocBuilder._sheet`
  vytváří vlastní `SchematicScene`). QPdfWriter neumí anotace → post-processing hotového PDF.
- Žádná PDF knihovna v `pyproject.toml`.
- Vedlejší chyba: `DocBuilder.export` nepočítá strany vícepólu (`_sheet` volá `writer.newPage()` sám) → nesedí
  „3/16“ i vrácený počet stran; pro anotace je potřeba přesný fyzický index strany.

## 1. Datový model – `Project.notes: list[Note]`
(ne `Sheet.notes`: kopírování listu by duplikovalo, smazání listu by ztratilo, panel by procházel listy)
```python
NOTE_STATUSES = ("open", "resolved")          # UI „otevřeno“ / „vyřešeno“
@dataclass
class Note:
    """Připomínka (redline) – interní poznámka, není součástí dokumentace (diff/otisk ji ignorují)."""
    sheet_id: str
    x: float; y: float           # mm, Y nahoru, na mřížce; bod = kotva, obdélník = levý dolní roh
    text: str = ""
    no: int = 0                  # pořadové číslo v projektu, nepřečíslovává se
    w: float = 0.0; h: float = 0.0   # 0 = bod; > 0 = obdélník
    target_id: str = ""; is_wire: bool = False   # informativní (skok, popis), poloha absolutní
    author: str = ""; created: str = ""           # ISO „2026-10-16T14:05“
    status: str = "open"
    reply: str = ""; resolved_by: str = ""; resolved: str = ""
    id: str = field(default_factory=_uid)
```
Barva podle stavu (otevřeno purpurová – odlišná od červené revize, vyřešeno šedá), neukládá se.
**`FORMAT_VERSION = 9`**, migrace `d.setdefault("notes", [])` – starší program v9 odmítne místo tichého zahození
připomínek při uložení. Opravit `docs/ARCHITECTURE.md` („aktuálně 8“).

`envocad/model/notes.py` (bez Qt): `next_note_no`, `note`, `notes_on_sheet`, `put_note(project, n, index=None)`,
`remove_note(project, id) -> (Note, index) | None`, `resolve(n, by, when, reply="")`, `reopen(n)`, `orphan_notes`,
`note_target_label`. `settings.current_user()` = `standard["author"]`, jinak `getpass.getuser()`.

## 2. Geometrie (Qt i DXF)
```python
FLAG_H = 5.0; TEXT_H = 2.5
@dataclass
class NoteShape:
    note_id: str; status: str
    lines: list[tuple[float, float, float, float]]
    polylines: list[list[tuple[float, float]]]
    texts: list[tuple[float, float, str, float, str]]
    bbox: tuple[float, float, float, float]
def note_shape(n, with_text=False) -> NoteShape
def notes_geometry(project, sheet, statuses=("open",), with_text=False) -> list[NoteShape]
```
Bod: křížek 1 mm v kotvě, odkazová čára do (x+2,5; y+2,5), praporek `max(5, 1,6·len+3)` × 5 s číslem – na mřížce.
Obdélník: obrys (Qt čárkovaně, DXF plně), praporek na pravém horním rohu. `with_text` (DXF) přidá text zalomený na 40 znaků.
Editor: `NoteItem`, přepínač Zobrazit → Připomínky (QSettings `view/notes`). Exportní scény `notes_visible = False`
(do obsahu PDF se nevypalují). DXF `notes=False` → vrstva `PRIPOMINKY` (ACI 6). GUI: „Přidávat připomínky do exportu“
(QSettings `export/notes`, výchozí vypnuto), jen otevřené.

## 3. PDF anotace
- **Nová závislost `pypdf>=5.0`** (čistý Python, BSD-3, bez závislostí, ~1 MB v PyInstalleru; umí upravit existující
  PDF a později číst `/Annots`). Do `pyproject.toml` a ověřit `envocad.spec`. Import lokálně ve funkci.
  Zamítnuto: vlastní inkrementální update PDF (křehké), reportlab (neupraví existující PDF), PyMuPDF (AGPL).
- `envocad/export/pdf_annots.py` (bez Qt):
```python
MM_TO_PT = 72 / 25.4
@dataclass
class PageMap:
    scale: float; tx: float; ty: float; sheet_h: float   # model (mm, Y nahoru) → strana (mm, Y dolů)
    def to_page_mm(self, x, y) -> tuple[float, float]     # (tx + x*s, ty + (sheet_h - y)*s)
def note_rect_pt(n, pm, page_h_pt) -> tuple[float, float, float, float]
def add_note_annotations(path, pages: list[tuple[int, PageMap, list[Note]]], project_name="") -> int
```
- `pdf_export.py`: `s = min(out_w/pw, out_h/ph)`, vystředění; `doc_pdf.py`: `tx = ty = 0`. Výška strany z MediaBoxu.
- Bod → `/Text` (Comment), obdélník → `/Square`; `/Contents`, `/T` autor, `/M`, `/Subj` „Připomínka č. N“, `/C`,
  `/F 4`, `/NM envocad:<id>`, `/Popup`; vyřešená + odpověď `/IRT` se `/StateModel /Review /State /Completed`.
- `DocBuilder`: `self._pdf_page` zvyšovat u každého `newPage()` (oprava počítání stran); připomínky jen u schémat JPS.
- Import odpovědí z PDF: YAGNI (připraveno přes `/NM`).

## 4. GUI
- `ui/notes_view.py` `NoteItem(QGraphicsItem)` (výběr, posun s přichycením, tooltip, dvojklik, kontextové menu
  Upravit / Vyřešit / Znovu otevřít / Smazat).
- `SchematicScene`: `notes_visible`, `note_items`, `set_notes_visible`, `rebuild_notes`; `Mode.NOTE` (klik = bod,
  tah ≥ 1 mřížka = obdélník, `target_id` z prvku/vodiče pod kotvou, pak `NoteDialog`; testy `ask_attributes = False`).
  Posun a Delete vybraných `NoteItem` přes příkaz.
- `ReplaceNoteCommand(project, old, new, text, on_change=None, index=None)` – přidání/smazání/úprava jedním příkazem.
- `NoteDialog` (text, stav, vyřízení, autor a datum jen ke čtení).
- `ui/notes_panel.py` `NotesPanel` (záložka docku navigátoru): filtr Otevřené/Vyřešené/Vše, „jen aktuální list“,
  hledání; sloupce Č., List, Prvek, Text, Autor, Datum, Stav; Vyřešit/Otevřít, Smazat; `goto_note(sheet_id, note_id)`.
- Akce „Připomínka“ v nástrojích.

## 5. Revize, diff, kontroly
- Připomínky nejsou v `diff_projects` ani `sheet_fingerprint` (test).
- Uzavření revize neblokují; MainWindow se zeptá „N otevřených připomínek – přesto uzavřít?“.
- `note_findings`: INFO `note_open` jednou za list, INFO `note_orphan` pro připomínky na smazaném listu.

## 6. Testy a pořadí
`tests/test_notes.py`, `test_migration.py` (v8 → v9), `test_pdf_annots.py` (PageMap, otočení Y, anotace na prázdném
PDF, vyřešená s `/State /Completed`), `test_export_content.py` (správná fyzická strana i za vícepólem, bez `notes`
žádné `/Annots`, DXF vrstva jen s `notes`), `test_undo.py`, `test_gui_mouse.py` (`Mode.NOTE`).
Pořadí: (1) model, v9, notes.py; (2) geometrie, note_findings, DXF; (3) GUI příkaz, NoteItem, Mode.NOTE, dialog;
(4) panel, skok, přepínač, potvrzení při uzavření revize; (5) pdf_annots + pypdf, `_pdf_page`, napojení exportů;
(6) dokumentace.

## YAGNI
Vlákna odpovědí; import komentářů z PDF; připomínky ve vícepólu a plánu svorkovnice; obláček, šipky, barvy;
kotva sledující prvek; vazba na revizi; vypalování do obsahu PDF.
