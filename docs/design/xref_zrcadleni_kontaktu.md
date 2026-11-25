# Návrh: zrcadlení kontaktů a křížové odkazy přerušovacích bodů (hvězda a řetěz)

Návrh agenta `architekt` (10/2026), schválil orchestrátor. Roadmapa „Z rešerše EPLAN 2026“, bod Zrcadlení kontaktů.
**Formát projektu se nemění (zůstává v8)** – vše přes nepovinné atributy prvku (`contacts`, `mirror`, `star_source`),
atributy v JSON značek a nepovinný sloupec CSV artiklů. Nový modul `envocad/model/xref.py`.

## 0. Chyby dnešního stavu (návrh je řeší)
1. `fve.contactor` K1 + `ctl.coil` K1 + `ctl.contact_no` K1 na listu: 2× `dup_ref`, `coil_of(kontakt)` vrátí stykač
   (je dřív), zrcadlo cívky je prázdné, `contact_ambiguous` mlčí.
2. Výkon: `contacts_of(ref, coil)` volá pro každý kontakt `coil_of` (celý projekt) při každém `compute_layout`.
3. `ctl.contact_power` má `poles=3`, ale `contact_terminals` vrátí jen „1/2“.
4. `interrupt_partner` při 3+ bodech vrací „prvního jiného“ – závislé na pořadí.
5. Dva NO kontakty téhož K1 mají oba výchozí „13/14“ bez nálezu.

## 1. Zrcadlo kontaktů (tabulka pod hostitelem)
```python
# envocad/model/xref.py
KIND_POWER, KIND_NO, KIND_NC = "power", "no", "nc"
COLUMN_ORDER = (KIND_POWER, KIND_NO, KIND_NC)        # vlevo → vpravo; osa mezi NO a NC

@dataclass(frozen=True)
class MirrorRow:
    kind: str; pair: str                 # "13/14", "1/2", "DO1"
    ref: str                             # "/3.B4", "+RDC1/3.B4"; "" = rezerva z kontaktního obrazu
    sheet_id: str = ""; element_id: str = ""

@dataclass
class ContactMirror:
    host_id: str
    columns: dict[str, list[MirrorRow]]  # jen neprázdné sloupce, řádky přirozeně podle pair
    @property
    def empty(self) -> bool: ...

def contact_table(project, host_sheet, host, index=None) -> ContactMirror
def place_ref(project, from_sheet, from_target, to_sheet, to_target) -> str
    # '/3.B4'; odlišné aspekty cíle předřadí: '+RDC1/3.B4'; anonymní rozvaděč → jen '/3.B4'
```
- Řádek = pár svorek; silový kontakt `poles=3` → 1/2, 3/4, 5/6 se stejným odkazem. Rezervy (páry z obrazu bez
  kontaktu) s prázdným `ref`, zařazené přirozeně.
- `contact_mirror(project, coil)` v `project.py` zůstává jako obal (`list[(pair, ref)]`, bez rezerv).

### Geometrie (Qt i DXF stejně)
```python
@dataclass
class MirrorGeometry:            # pole jako FrameGeometry → draw_frame() / DXF helper beze změny
    lines: list[tuple[float, float, float, float]]
    texts: list[tuple[float, float, str, float, str]]
    boxes: list[Box]             # obálky textů pro textlayout / překryvy
    bounds: Box
def mirror_geometry(e, sym, mirror) -> MirrorGeometry
```
- Osa `x0` = střed obálky otočené značky (`textlayout.symbol_box`) na mřížce (cívka rot 0 → `e.x`).
- Horní hrana = spodek obálky − 2,5 mm (dolů na mřížku); tabulka vždy pod značkou.
- Sloupce: vlevo silové a NO (NO u osy), vpravo NC; jen neprázdné; šířka `max(10, ceil_grid(len×CHAR_W×1,8 + 2))`.
- Hlavička 5 mm s piktogramem (NO, NC, silový) z čar natvrdo v `xref.py`; vodorovná čára pod hlavičkou.
- Řádky `f"{pair} {ref}"` (rezerva jen `pair`), výška 1,8, rozteč 3,0, vlevo na `x_sloupce + 1`; text nezasáhne osu.
- Svislé dělicí čáry, na ose vždy; bez vnějšího rámečku. Prázdné zrcadlo = žádná geometrie. `mirror="0"` potlačí.

### textlayout
- `SheetTextLayout.mirrors: dict[host_id, MirrorGeometry]`; `compute_layout(..., index=None)` postaví jednou
  `DeviceIndex`, po čarách značek a trasách spočítá zrcadla a **rezervuje** místo (čáry `_add_line(... owner=id+"#mirror")`,
  boxy `grid.add(b, "text", id+"#mirror")`) před rozmístěním popisků. Pevná poloha.
- `element_xref` pro hostitele zrcadla vrací `""` (upravit test `tests/test_model.py` ~ř. 251).
- `text_overlaps`: boxy zrcadel s vlastníkem `host.id` (kolize s vlastní značkou se nehlásí).

### Kreslení
- Qt: `SchematicScene.drawForeground` → `draw_frame(painter, g, c.ink)` pro `text_layout().mirrors` (PDF tím také).
- DXF: vrstva `TEXTY`; společný helper `_draw_geometry(msp, g, layer)` pro rámeček, revize a zrcadla.
- Vícepól: ne (YAGNI).

## 2. Kontaktní obraz – atribut `contacts`
| Odkud | Jak |
|---|---|
| artikl (CSV, nepovinný sloupec `contacts`) | `PARAM_TO_ATTR["contacts"] = "contacts"` v `library/components.py`, `apply_to` |
| výchozí značky | běžný atribut v `attributes` JSON u `ctl.coil` a `fve.contactor` (`show: false`) |
| ručně | panel Vlastnosti |

Formát: páry oddělené mezerou/čárkou, volitelná předpona druhu:
`"1/2 3/4 5/6 13/14 21/22"`, `"NO:11/14 NC:11/12"`, `"NO:DO1 NO:DO2"`. Bez předpony podle IEC 60947-5-1:
jednomístné = silový; dvoumístné s funkční číslicí 3/4 nebo 7/8 = NO, 1/2 nebo 5/6 = NC; jinak chyba.
```python
@dataclass(frozen=True)
class ContactSlot:
    kind: str; pair: str
def parse_contact_image(text) -> tuple[list[ContactSlot], list[str]]   # (sloty, chybné tokeny)
def contact_image(group) -> list[ContactSlot] | None                     # None = nezadán → bez kontrol a rezerv
def contact_pairs(e) -> list[str]     # attrs["terminals"] (i víc párů), jinak výchozí; silový → f"{2i-1}/{2i}" pro poles
def contact_kind(e) -> str | None     # podle CONTACT_KIND / DUAL_ROLE
```
`contact_terminals(e)` = `" ".join(contact_pairs(e))`. Obraz z `group.device.attrs["contacts"]`, jinak z hostitele.

Kontroly (`checks.py`):
| kód | závažnost | kdy |
|---|---|---|
| `contact_dup` | varování | dva kontakty/póly téhož přístroje se stejným párem (vždy) |
| `contact_count` | varování | použito víc kontaktů druhu X než v obrazu („K1: použity 2 rozpínací kontakty, kontaktní obraz má 1“) |
| `contact_unknown` | varování | pár není v obrazu („Kontakt 33/34 není v kontaktním obrazu K1“) |
| `contact_image_syntax` | varování | nečitelný token v `contacts` |

Rezervy jen u přístroje se zadaným obrazem. YAGNI: zápis počtem („3P+1NO“), obraz z příslušenství, nový klíč JSON,
zpožděné kontakty.

## 3. Hostitelé zrcadla (cívka, jistič, NS ochrana, RTU)
Hostitele určuje **skupina (prostor označení, ref)**, ne `COIL_SYMBOLS` ani `function_class`.
```python
CONTACT_KIND = {"ctl.contact_no": "no", "ctl.contact_nc": "nc", "ctl.contact_power": "power"}
CONTACT_SYMBOLS = set(CONTACT_KIND)
COIL_SYMBOLS = {"ctl.coil"}
DUAL_ROLE = {"fve.contactor": "power"}   # bez cívky hlavní přístroj; s cívkou = silové kontakty cívky

@dataclass
class DeviceGroup:
    scope: tuple[str, str]; ref: str
    host: tuple[Sheet, Element]              # cívka, jinak první ne-kontakt
    device: tuple[Sheet, Element]            # položka výkazu/artikl/rozložení
    secondary: list[tuple[Sheet, Element]]   # DUAL_ROLE prvek při existenci cívky
    contacts: list[tuple[Sheet, Element]]

@dataclass
class DeviceIndex:
    groups: dict[tuple[str, str, str], DeviceGroup]
    by_element: dict[str, DeviceGroup]
    @classmethod
    def build(cls, project) -> DeviceIndex       # O(N)
    def group_of(self, e) -> DeviceGroup | None
    def is_bom_device(self, e) -> bool            # False pro cívku, má-li skupina jiné device
```
- Kontakt → skupina dnešním pravidlem (ref, přednost stejný scope_key, jinak první); kandidáti jen hostitelé.
- Zrcadlo dostane hostitel s ≥1 kontaktem nebo zadaným obrazem (i jistič, relé, RTU, stykač bez cívky).
- `dup_ref`: ve skupině smí být ≤1 cívka a ≤1 DUAL_ROLE prvek.
- Výkazy (`devices`, `device_list`, `bom`), rozložení (`Layout.used_modules`, auto-rozmístění), `thermal`,
  `no_article` vynechají cívku, když skupina má jiné `device`. Sloupec Kontakty z `group.contacts` + `secondary`.
- `coil_candidates`, `coil_of`, `contacts_of` zůstanou jako obaly (stejné výsledky pro dnešní testy), parametr `index=None`.

## 4. Přerušovací body: dvojice, řetěz, hvězda
- Ve skupině (stejné `ref` v projektu) bod s `attrs["star_source"] == "1"` → **hvězda** (zdroj = první takový);
  jinak **řetěz** (2 body = dnešní dvojice). Řazení `(index listu, x, -y, id)`.
```python
@dataclass(frozen=True)
class InterruptLink:
    mode: str      # alone | pair | chain | star_source | star_target
    prev=None; next=None; source=None; targets: tuple = ()
def interrupt_groups(project) -> dict[str, list[tuple[Sheet, Element]]]
def interrupt_link(project, sheet, e, groups=None) -> InterruptLink
def interrupt_xref(project, sheet, e, groups=None) -> str
```
`interrupt_partner` (obal) vrací next, jinak prev, jinak source, jinak první cíl.

| režim | text |
|---|---|
| pair | `→ /2.C3` u obou; do jiného umístění/funkce se předřadí aspekty cíle (`→ +RH/2.D3`, jako EPLAN) |
| chain | `← /1.A2` a `→ /4.C1` na samostatných řádcích; krajní jen jeden |
| star_source | `→ /2.A2, /3.B1, /4.C5`, max 3 na řádek, další řádky odsazené 2 mezerami |
| star_target | `← /1.F3` |
| alone | `→ ?` |

Odkazy přes `place_ref` (u všech režimů: cíl v jiném umístění/funkci → `+RH/2.D3`, anonymní rozvaděč jen `/2.D3`).
`dup_ref`: body se stejným `ref` v prostoru jsou jedna položka (mezi sebou duplicitou nejsou), kolize s přístrojem
nebo vodičem téhož prostoru je duplicita. Kontroly: `interrupt_alone` zůstává; nový `interrupt_star_multi` (varování).
Zamítnuto: režim v settings (výkres by se lišil podle PC), v `meta` (YAGNI), seskupení podle scope, `xref_mode` na bodu.

## 5. Formát
Beze změny (v8). Nové rezervované atributy prvku `contacts`, `mirror`, `star_source` → `docs/LIBRARY_FORMAT.md`.
Viditelné změny: silový kontakt `poles=3` = 3 řádky; zrcadla u jističů/relé; zrcadlo cívky = tabulka;
2× výchozí 13/14 → `contact_dup`.

## 6. Undo a pořadí
- Žádné nové `QUndoCommand` – vstupy jsou atributy, artikl, poloha; vše ostatní je odvozené.
  `_on_undo_changed` už invaliduje `text_layout` všech scén.
- Pořadí: (1) `xref.py` index, páry, obraz, obaly v project.py, oprava dup_ref/coil_of; (2) `contact_table`,
  `place_ref`, `mirror_geometry`, textlayout, DXF; (3) GUI kreslení; (4) výkazy/rozložení/teplo přes
  `is_bom_device`, kontroly kontaktů, `PARAM_TO_ATTR`, atributy JSON; (5) přerušovací body + zaškrtávátko
  `star_source` v panelu; (6) dokumentace.

## YAGNI
Zrcadlo ve vícepólu a plánu svorkovnice; skok kliknutím z řádku zrcadla (data v MirrorRow jsou připravená);
automatické doplnění dalšího volného páru (`next_contact_pair` v API, napojení volitelné); značka přepínacího
kontaktu; výchozí režim přerušovacích bodů; vlastní vrstva DXF pro odkazy; odkaz jen na sloupec (`/3.4`);
klíč `contact` v JSON značky.
