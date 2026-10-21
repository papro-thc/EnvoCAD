# Návrh: DXF vícepólu, JPS na víc listů, změny modelu mimo undo

Stav: návrh (architekt, 10/2026), k implementaci `core-dev` / `gui-dev`. Formát projektu zůstává **v9** u všech tří bodů.
Bod B implementován 10/2026 (`generator.jps._place_jps` / `_split_jps`, `xref.through_interrupt`, `tests/test_jps_split.py`).

## A) Export vícepólového schématu do DXF

**Stav.** `export_sheet_dxf` kreslí jen pohled listu (u rozvaděče jednopólovou editační podobu). `multipole_geometry`
dává póly, žíly, sběrnice, sběrné čáry, štítky, nadpis, ale texty jen jako obálky (`texts: (Box, owner, what)`).
Jen scéna (`ui/multipole_view.py`) kreslí: můstky (`_add_bridges`, :841), tečky odboček sběrnice (`BusItem`, :293)
a můstků, šipky přerušení (`PageBreakItem`, :213), šipky na koncích sběrnice, podtržení nadpisu, styl čar (čárkovaná
vazba pólů a můstek, tloušťky). PDF jde přes `scene.render` (`export/doc_pdf.py:353`), DXF proto nemá z čeho kreslit.

**Návrh: jeden kreslicí seznam v modelu.** `_build` už každou čáru a text zapisuje přes `line()` / `text()`. Tyto
helpery budou plnit ještě seznam primitiv (jediný zdroj pravdy). Obálky pro F7 se dál odvozují z textů.
```python
# model/multipole_geometry.py (bez Qt)
@dataclass(frozen=True)
class Prim:
    kind: str; page: int               # line|text|dot|poly|symbol; souřadnice LOKÁLNÍ na straně (Y nahoru)
    pts: tuple[Point, ...] = ()        # line/poly: body; dot/symbol/text: (bod,)
    text: str = ""; h: float = 0.0; align: str = "left"; rot: float = 0.0; r: float = 0.0
    layer: str = "VODICE"; style: str = "solid"; weight: str = "thin"   # dashed | thin/wire/bus/fan
    symbol_id: str = ""                # instance značky pólu (oblouky přesně)
MultipoleGeometry.prims: list[Prim]       # nové pole
MultipoleGeometry.bridges: list[Bridge]   # Bridge(strip, group, page, pts) – logika přesunutá ze scény
def page_prims(g: MultipoleGeometry, k: int) -> list[Prim]
```
- Značky pólů jsou `Prim("symbol")` (oblouky a kružnice zůstanou přesné, DXF použije zobecněné `_draw_symbol(msp, x, y,
  rot, sym)`), společná spoušť stejně. Porty se do DXF nekreslí, stejně jako u JPS.
- Doplnit do modelu: `mp.bridge_paths(sheet, poles, page_of)` (přesun z `_add_bridges`), tečky (odbočky sběrnice,
  sběrné čáry, můstky), šipky přerušení a šipky sběrnice jako `line`, podtržení nadpisu, skutečné texty štítků kabelů
  a čísel svorek. Čáry můstků se nově zapíšou i do `g.lines`, takže je F7 (`mp_text_overlap`) uvidí. Tím se může
  změnit počet nálezů. Je to záměr, testy se upraví.
- Scéna: v 1. kroku jen převezme `g.bridges` a body šipek z modelu. Interaktivní položky (`PoleItem`,
  `ConductorItem`) zůstanou. Ve 2. kroku lze statické dekorace (sběrnice, štítky, přerušení, nadpis) kreslit jedním
  `PrimItem` z `prims`.

**DXF** (`export/dxf_export.py`): `export_multipole_dxf(project, sheet, lib, path, split_pages=False)`. Menu Export DXF
na záložce vícepólu volá tuto funkci, na JPS beze změny.
- Vrstvy: stávající `SYMBOLY`, `VODICE`, `TEXTY`, `RAMECEK` a nové `SBERNICE` (sběrnice, sběrné čáry, tečky),
  `MUSTKY` (čárkovaně), `VAZBY` (vazba pólů, čárkovaně), `ODKAZY` (šipky přerušení a odkazy „/3.2.B4“), `STITKY`
  (štítky kabelů). Čárkování se řeší linetypem `DASHED` (`ezdxf.new(setup=True)`), tloušťky lineweightem
  (thin 0.18, wire 0.35, bus/fan 0.50).
- Stránkování: **jeden soubor**. Strany leží v modelspace vedle sebe (`x + k·(W + 20)`, lokální Y) a každá má vlastní
  paperspace layout „Strana k“ (`page_setup` podle `mp.page_size`, např. A4 297 × 210, viewport 1 : 1). Rámeček strany
  je `frame_geometry(…, w, h, "vícepólové schéma", page_label(k, n), paper)`. `split_pages=True` uloží
  `<název>_s<k>.dxf` (stejná primitiva, posun 0).
- Zamítnuto: (1) render Qt scény do DXF (vlastní QPaintEngine nebo SVG→DXF): export by potřeboval Qt, texty by se
  rozpadly na křivky a nebyly by vrstvy. (2) Vlastní kreslení vícepólu v `dxf_export`: logika by se rozešla se scénou
  i s F7. (3) Hned celá scéna z `prims`: příliš velký zásah do interaktivních položek. (4) Strany pod sebou jako ve
  scéně bez layoutů: v ZWCAD se pak nedá tisknout po stranách.

**Testy (headless):** `test_dxf_multipole.py` (AC rozvaděč se svorkami, můstky, 2+ strany): vrstvy, počet layoutů =
`g.pages`, texty obsahují odkazy přerušení a popisky žil, čárkované LINE na `MUSTKY` = úseky `g.bridges`, počet
teček = odbočky, entity v rámečku své strany, export bez PySide6 (subprocess, `sys.modules`). Paritní GUI test (offscreen) ověří, že polohy `PageBreakItem` a `BridgeItem` = model. Undo se netýká (jen čtení).

## B) Rozdělení velkého JPS na víc listů

**Ověřený stav.** Generátor dá celé JPS na `p.sheets[0]` a `fit_sheet_to_content` zvětší formát. Z `build_project`
(4 stringy na střídač): 2 střídače A2, 4 A1, 6 A0, 8 **vlastní 505 × 1615**. Přetékání je tedy opravené jen
zvětšením formátu, rozdělení na listy chybí.

**Návrh (jen generátor a odvozené funkce, formát beze změny).** Nový klíč specifikace
`"jps": {"split": "auto"|"none", "paper": "A3"}`. `auto` rozdělí jen tehdy, když by jeden list přesáhl
`standard.jps_max_paper` (výchozí „A2“ zachová snapshoty malých projektů).
- Řez vede **na AC straně**. List „JPS – T1, T2“ obsahuje řady střídačů (stringy → DC rozvaděče → střídač),
  baterii a bloky DC rozvaděčů. Střídače se do listu balí hladově podle `row_h` proti vnitřní výšce `paper`. Poslední
  list „JPS – AC a připojení“ obsahuje blok AC rozvaděče, síť a HOP. DC řetězec zůstane na jednom listu, takže
  `_find_inverter`, kontroly stringů, MPPT i `_block_exit` fungují beze změny. Řez na DC straně je zamítnutý:
  přerušení by bylo na každém stringu a kontroly stringů by vyžadovaly hledání přes listy.
- Přes řez vede pár `fve.interrupt` se stejným `ref` (např. „AC-T1“). Odkaz „→ /3.B4“ už umí `xref.interrupt_xref`.
  **Kabel je jeden vodič s daty**: vodič `přerušení → blok:X1` na AC listu nese `ref`, `cable`, `cross`, `length`,
  `method` (tam ho hledá `feed_wire_by_port` a štítek přívodu). Úsek `T1:AC → přerušení` je jen pokračování:
  stejné `conductors`, bez `ref`/`cable`. `sync_cables`, `reports.cables` i kusovník tak vidí jeden kabel.
- Nová funkce modelu (obor-nezávislá): `xref.through_interrupt(project, sheet, element, port) ->
  tuple[Sheet, Element, str] | None`. Pro přerušovací bod ve dvojici vrátí skutečný konec za protějškem (jediný
  vodič na protějšku), jinak None. Kdo ji použije:
  `reports._port_text`/`_end_text` (Odkud „T1:AC“), `calc._source_current` a `check_cables` (proud z P_AC),
  `feed_link_attrs` („W3 T1:AC /2.C4“), `wiring_list`/`cable_plan` (úsek pokračování přeskočí), `potential.nets`
  (sjednotí dvojici, řetěz i hvězdu – uzavře i dluh „Křížové odkazy potenciálů mezi listy JPS“).
- F7: `no_cable` (INFO) přeskočí úsek pokračování. Nová kontrola `cable_split` (WARNING): údaje kabelu jsou na obou
  úsecích přes přerušení, což znamená riziko zdvojení kabelu. `interrupt_alone` a `dup_ref` platí beze změny.
  Kontrola textů běží per list jako dnes.
- Generátor: `_align_bends` (dnes `project.sheets[0]`) přejde na všechny listy JPS. `fit_sheet_to_content` se volá na
  každém listu. Pořadí listů: JPS listy, pak listy rozvaděčů jako dnes. Snapshoty `tests/generate_snapshot.py` se
  změní jen pro projekty nad limitem.
- Diff a revize: `diff_projects` porovnává per `sheet.id`. U nově generovaného projektu nic nového, existující
  soubory se nemigrují. Ruční přesun prvku na jiný list se dnes ukáže jako „odebráno“ + „přidáno“. Doporučuji
  párovat prvky podle id napříč listy („přesunuto na list X“), jde to ale mimo rozsah návrhu.
- Zamítnuto: (1) stránkovaný pohled jednoho velkého listu (jako vícepól): JPS je volně editovatelný list
  s absolutními polohami, `position_ref` je per list a tisk i navigace by byly matoucí. (2) Vodič přes listy
  (`WireEnd` se `sheet_id`): mění formát a rozbíjí invariant „vodič je na listu“ ve všech modulech. (3) Atribut
  `cont_of` u úseku: zbytečný, vazbu dává pár přerušení. (4) Kopie střídače na AC listu (skupina přístroje):
  `DeviceGroup.dup` by hlásil duplicitu.
- Testy: 8 střídačů → víc listů, každý ≤ A3 a bez „vlastní“; počet `Cable` = počet vodičů s `ref`; `reports.cables`
  bez duplicit a „Odkud“ = T1:AC; `check_cables` má proud AC kabelu; `check_project` bez `interrupt_alone` a
  `cable_split`; `nets` spojí T1:AC s blokem.

## C) Změny modelu z GUI mimo QUndoCommand

| Místo | Co zapisuje | Hodnocení |
|---|---|---|
| `ui/main_window.py:937-939` `_on_undo_changed` → `_sync_links_and_blocks` (:1038-1042) | `sync_feed_links` a `sync_cables` po každém kroku undo/redo | **chyba**, viz níže |
| `ui/main_window.py:844-849` `_sheets_changed`; :756, :873 (pouhé otevření listu rozvaděče) | totéž | totéž |
| `model/project.py:1713-1716` (volá se z výše uvedených) | `end.port = f.ref`: přejmenuje port vodiče JPS (primární data) | mimo undo |
| `model/project.py:1724-1727` | `sw.conductors = w.conductors` u vodičů přívodu (primární data) | **ověřená chyba**: undo vložení vodiče JPS na blok:X1 nevrátí žíly vodičů přívodu (`["L1","N","PE"]` zůstane `L1…PE`) |
| `ui/main_window.py:1134-1135` `edit_cable` | `sync_cables` před dialogem (vytvoří `Cable`) | jen odvozené, přijatelné |
| `ui/main_window.py:1374-1381` porovnání s revizí | `apply_changes` a `meta["changes"]` → snímek → restore → příkaz | správný vzor, ale chybí `try/finally`: výjimka nechá model napůl změněný (šablona :833-839 to ošetřuje) |
| `ui/canvas.py:281`, `:299`, `:377` | živý náhled tažení prvku, lomů a úseku | v pořádku, uzavírá ho příkaz :672/:692. Doporučení: při Esc nebo ztrátě fokusu během tažení vrátit polohy z `_move_start` |
| `ui/canvas.py:391`, `:418-426`, `:493-494`, `:519`; `ui/multipole_view.py:473`, `:491`, `:526-527` | nové objekty před `Add*Command` | v pořádku |
| skříň (`EnclosureDialog` na kopii, `SetLayoutCommand`), `SetPlacementCommand` (`layout_view.py:250`) | — | vyřešeno |

**Řešení.**
1. Rozdělit `sync_feed_links` na **čistě odvozenou** část (`wire_id`, `from`/`to`, `cable` přívodu; idempotentní,
   smí běžet mimo undo) a **primární follow-upy**, které půjdou jen příkazem:
   přejmenování portu bloku → `rename_followups` (`TextChange` na `WireEnd.port`, stávající `TextChangesCommand`);
   kopie žil → `feed_conductor_followups(project, wire) -> list[ConductorChange]` volaná v `AddWireCommand`,
   `SetConductorsCommand`, `SetAttrCommand(wire_id)` a vracená v jejich `undo`.
2. Synchronizaci po otevření listu (:873) zrušit, stačí po změně modelu.
3. `try/finally` kolem mutace v porovnání s revizí (vzor ze šablony).
4. Statický test jako `test_no_undo_reset_outside_allowed_places`: v `ui/` mimo `commands.py` zakázat
   `.attrs[..] =`, `.attrs.update/pop`, `.conductors =`, `.terminals =`, `.mp_pos =`, `.points =`, `.port =`.
   Výjimky se označí komentářem `# model-write-ok: <důvod>` (náhled tažení, nové objekty).

Zamítnuto: zabalit `sync_*` do každého příkazu jako snímek celého projektu (paměť a výkon u 800 vodičů, slučování
příkazů) a nechat sync mimo undo s tím, že „je to odvozené“ (port i žíly jsou primární data, `to_dict` po undo nesedí).

## Otevřené otázky
1. DXF: jeden soubor s layouty, nebo raději soubor na stranu (EPLAN exportuje po stranách)? Ověřit v ZWCAD.
2. B: limit pro `auto` (A2 nebo A3) a cílový formát listů JPS – firemní standard ENVO?
3. B: jmenná konvence přerušení („AC-T1“) a pořadí listů (AC list jako přehled první, nebo poslední)?
4. B: má se rozdělení nabízet i pro ruční projekty (příkaz „Rozdělit list“ = `SheetsStateCommand`), nebo jen v generátoru?
5. Plán svorkovnice (`terminal_plan_view`) do DXF stejným mechanismem `prims` – v tomto kroku, nebo později?

## Rozhodnutí (10/2026)
- A: výchozí jeden DXF se stranami vedle sebe a layoutem na stranu, `split_pages=True` = soubor na stranu; plán
  svorkovnice později. DWG export není potřeba (uživatel).
- B (uživatel): dělit, když by list JPS přesáhl A2; listy A2. AC list (AC rozvaděč, síť, HOP) **na začátek** jako
  přehled, za ním listy střídačů. Dělení jen v generátoru (příkaz „Rozdělit list“ YAGNI).
- B, PDF (uživatel): volba při exportu PDF „Skutečný formát listu / Zmenšit na A3“, výchozí podle firemního standardu
  (nový klíč standardu, výchozí „zmenšit na A3“ = dnešní chování).
