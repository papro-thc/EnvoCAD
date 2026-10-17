# UX audit a návrh lišt – EnvoCAD GUI

Stav: **návrh** (kód se nemění). Podnět: „víc uživatelské GUI, lištu s funkcemi“. Cílovka: projektant FVE z EPLAN/AutoCAD.
Screenshoty (offscreen, projekt `route2_terminals` z `tests/generate_snapshot.py`, světlé téma), skript `shots.py` v téže složce:
`/tmp/claude-0/-home-user-EnvoCAD/218ef7e0-ef83-5cc1-9211-57e519398ff2/scratchpad/ux/`
- `00_prazdny_stav.png` prázdný start, `01_hlavni_okno.png` JPS, `02_jps_rozvadec.png`, `03_multipole.png`,
  `04_layout.png` dispozice, `05_terminals.png` plán svorkovnice, `06_f7_dialog.png` kontrola, `menu_0..9.png` jednotlivá menu.

## 1. Inventura (`main_window._build_actions`)
- Menu: Soubor (15 akcí), Úpravy (14), Kreslit (3), Zobrazit (8), Projekt (1), List (9), Výstupy (8), Knihovna (8), Nápověda (2),
  plugin „Nástroje“. Zkratky: Ctrl+N/O/S/Q, Ctrl+Shift+N/S/E/T/K/M/P, Ctrl+Z/Y, Ctrl+T/F/M/J/L/K/D, F7, Home, Del, R (menu);
  W/R/N/Del/Esc se řeší ještě zvlášť v `keyPressEvent` canvasu a vícepólu.
- Jediná lišta „Hlavní“ (`main_toolbar`), 14 položek, **jen text, bez ikon**: Nový, Otevřít, Uložit | Zpět, Znovu | Kontrola projektu |
  Vodič, Výběr, Připomínka | Přizpůsobit list, Vícepólový pohled, Rozložení, Skříň rozvaděče, Celá dokumentace (PDF).
  Při 1400 px už přetéká do „»“ (`01_hlavni_okno.png`); při užším okně zmizí Skříň a PDF.
- Panely: Knihovna, Navigátor (Prvky | Připomínky), Vlastnosti. Záložky listů: každý list ×3 pohledy (schéma, vícepól, rozložení) =
  záložky přetékají (viz `03_multipole.png`).

## 2. Nalezené problémy (podle závažnosti)
**Chyby (ne jen vzhled)**
1. Kolize zkratek: `Ctrl+Shift+S` je současně „Uložit jako…“ i „Uložit výběr jako makro…“ → Qt hlásí nejednoznačnou zkratku, nefunguje ani jedno.
   `Ctrl+K` (Skříň rozvaděče) blokuje obvyklé „paleta příkazů“. `Ctrl+Y` je Znovu, `Ctrl+D` tmavý režim (v AutoCADu duplikát/dist.).
2. Zpět/Znovu nemají ikony ani zkratku v popisku; tooltipy jsou jen název akce bez zkratky (`TOOLBAR … toolTip == text`).

**Lišty a nástroje**
3. Žádné ikony nikde (ani v menu, navigátoru, knihovně, záložkách) – hůř se hledá a lišta je široká.
4. Lišta není kontextová: nástroje kreslení (Vodič/Výběr/Připomínka) jsou aktivní i v Rozložení či Plánu svorkovnice (jen nic neudělají);
   `draw_scene` funguje jen v JPS/vícepólu. Chybí: **Vložit značku** (jen dvojklik v panelu Knihovna), **Otočit**, **Zrcadlit**
   (geometrické zrcadlení symbolu v modelu zjevně není – `Element` má jen rotaci, ověřit; „zrcadlo kontaktů“ je jiná věc), **Přerušení/xref**, **Text**, Kopírovat/Vložit, Smazat, Najít, Zoom +/−, mřížka/snap, Narovnat vodič (N, jen klávesa).
5. Nástroje nemají stav „zapnuto“ (checkable, exclusive) – aktivní režim je vidět jen jako text ve stavovém řádku.
6. Mnoho důležitých akcí jen v menu a bez zkratky: Export DXF/PDF/xlsx, Uzavřít revizi, Svorky/Kabel, Strukturní označení, Nový list,
   Vložit šablonu rozvaděče, Vlastnosti projektu, Importy knihovny. „Výstupy“ nemají ani jedno tlačítko kromě „Celá dokumentace“.

**Stavový řádek a zpětná vazba**
7. Stavový řádek ukazuje jen text režimu/hlášky (`_show_mode`, `showMessage`); chybí souřadnice kurzoru v mm, mřížka (2,5 mm), zoom %,
   aktivní list + počet nálezů F7, indikace neuložených změn mimo titulek. Texty nápovědy se přepisují hláškami „Exportováno…“.
8. F7 „Kontrola projektu“ je **modální dialog** (`ChecksDialog.exec`, `06_f7_dialog.png`) – nelze opravovat a zároveň vidět seznam; po opravě se
   neobnoví. Vhodnější nemodální dok „Kontrola“ (Chyby/Varování/Info) s filtrem a počtem ve stavovém řádku.
9. Chybí paleta příkazů / hledání akcí: menu má ~70 položek, dlouhé názvy („Kabel vybraného vodiče (žíly, barvy, stínění)…“).

**Ostatní**
10. Kontextová menu (pravé tlačítko) existují jen v připomínkách (`notes_view.py`); v canvasu pravé tl. jen ukončí režim. Chybí: Vlastnosti,
    Otočit, Smazat, Svorky/Kabel u vodiče, Přejít na rozvaděč u bloku ROZVADĚČ, Uložit jako makro.
11. Prázdný stav (`00_prazdny_stav.png`): prázdný list bez nápovědy; průvodce/otevřít poslední projekt jen v menu.
    Žádné `saveGeometry/saveState` – okno se vždy otevře 1400×900 s výchozím rozložením doků a lišty (uživatel si nic nezapamatuje).
12. Přepínání listů/pohledů jen záložkami a navigátorem; chybí přepínač pohledu (Schéma | Vícepól | Rozložení | Svorky) v lišťce a Ctrl+Tab/PgUp.

## 3. Návrh

### 3.1 Lišty (QToolBar, `objectName` pro `saveState`)
| Lišta | Obsah | Viditelnost |
|---|---|---|
| Soubor | Nový, Otevřít, Uložit, Export PDF, Export DXF | vždy |
| Úpravy | Zpět, Znovu, Kopírovat, Vložit, Smazat, Najít | vždy (Kopírovat/Vložit/Smazat enabled podle výběru) |
| Pohled | Přizpůsobit, Zoom +/−, Mřížka, Pohledy: Schéma/Vícepól/Rozložení/Svorky (exclusive skupina), Tmavý režim | vždy; zoom jen v grafickém pohledu |
| Kreslení | Výběr, Vodič, Vložit značku (menu s posledními + Knihovna), Přerušení, Text, Připomínka, Otočit, Zrcadlit, Narovnat | JPS a vícepól; v Rozložení se skryje, v Rozložení místo ní „Dispozice“ (Automaticky rozmístit, Skříň…) |
| Kontrola/Výstupy | Kontrola F7 (s odznakem počtu), Výkazy, Dokumentace PDF, Štítky | vždy |
Kontextovost: `_tab_changed` volá `toolbar.setVisible()`/`action.setEnabled()` podle `_kind_of(view)`; akce Kreslení sdílí `QActionGroup` (exclusive,
checkable) a synchronizuje se přes `mode_changed`. Akce jsou členy `self.actions` (slovník id→QAction), aby je znala i paleta příkazů.

### 3.2 Ikony
- **Doporučení: Lucide (ISC) jako SVG soubory v `envocad/resources/icons/<id>.svg`** (stroke `currentColor`, 24 px mřížka, jednotná tloušťka 1,75 px).
  Licence ISC (+LICENSE soubor do složky) je kompatibilní s interním použitím; Tabler (MIT) je záložní varianta. Chybějící CAD ikony
  (vodič, přerušení, vícepól, DIN lišta, svorkovnice) nakreslit vlastní SVG ve stejném stylu (~10 kusů).
- Zbarvení pro světlé/tmavé téma: načíst SVG, nahradit `currentColor` barvou z palety (`theme.colors().ink` / `QPalette.ButtonText`),
  vyrenderovat do `QPixmap` (QSvgRenderer – v PySide6 je `QtSvg`, bez nové pip závislosti, nutno ověřit v `envocad.spec` excludes).
  Cache `icon(name)` v nové `ui/icons.py`; po `theme.apply()` přegenerovat ikony (`MainWindow.set_dark`). Disabled stav doplní `QIcon.Disabled`.
- Velikost 24 px (HiDPI 2×) v hlavních lištách, 16 px v menu a stromech; **popisek pod ikonou ne** (zabere místo) – `ToolButtonIconOnly`
  s tooltipem „Vodič (W)“; text vedle ikony (`TextBesideIcon`) jen u klíčových tlačítek (Kontrola, PDF) a volitelně přepínačem v nastavení.
- Tooltip generovat jednotně: `název (zkratka)` + řádek stavové nápovědy (`setStatusTip`).
- Balení: `pyproject.toml` `package-data` += `resources/icons/*.svg`; `envocad.spec` `collect_data_files(... includes=[..., "resources/icons/*.svg"])`.

### 3.3 Ribbon: **ne**
Qt nemá nativní ribbon; 3rd-party (QtRibbon, PyQtRibbon) = nová závislost, údržba a špatná shoda s docky. EPLAN P8 ribbon má, ale Kreslit/
Vložit/Kontrola se do kontextových tabů dá nahradit **kontextovými QToolBar + paletou příkazů** za zlomek ceny. Menu ponechat (hledání, zkratky, pluginy).

### 3.4 Paleta příkazů
Paleta na **`Ctrl+K`** (zvyk z VS Code/Slacku; `Ctrl+Shift+P` je už Připomínka); Skříň rozvaděče přesunout na `Ctrl+Alt+K` (Ctrl+Shift+K je Kabel).
Dialog `QDialog` s `QLineEdit` + `QListView` (fuzzy filtr přes všechny QAction menu rekurzivně, včetně pluginových; zobrazí cestu menu a zkratku;
`Enter` spustí). Zdroj = procházení `menuBar()` – nové akce se zařadí automaticky. Rozsah ~150 řádků. Rozšíření: hledání prvku (dnes Ctrl+F v navigátoru).

### 3.5 Stavový řádek
Trvalé widgety vpravo (`addPermanentWidget`): `X: 120,0  Y: 85,0 mm` | `Mřížka 2,5` (klik = přepnout snap) | `Zoom 125 %` (klik = Přizpůsobit)
| `List: RDC1` | `F7: 2 chyby, 5 varování` (klik otevře dok Kontrola) | `● neuloženo`. Vlevo zůstane nápověda k aktivnímu nástroji (stálá, hlášky s timeoutem
se po vypršení vrátí k nápovědě). Souřadnice z `mouseMoveEvent` pohledu přes `sp()` zpětně → signál `cursor_moved(x_mm, y_mm)` ze scén (model Y nahoru).

### 3.6 Kontextová menu a ostatní
- Pravé tlačítko v canvasu (pokud není aktivní režim): Otočit, Zrcadlit, Smazat, Kopírovat, Vlastnosti, u vodiče Svorky/Kabel, u bloku ROZVADĚČ „Otevřít rozvaděč“;
  v režimu zůstává „ukončit režim“. Všechno přes existující akce (`QUndoCommand` beze změny).
- Prázdný stav: v prázdném projektu přes list překryv (QLabel v `viewport`) s odkazy „Nový z průvodce“, „Otevřít“, „Poslední projekty“, „Vložit značku (dvojklik v Knihovně)“.
- Uložení rozložení: `QSettings("ENVO","EnvoCAD")` klíče `ui/geometry`, `ui/state` (`saveGeometry`/`saveState` v `closeEvent`, `restoreState` na konci `__init__`;
  `objectName` mají lišty i docky). Verzovat `saveState(version)`; položka „Zobrazit → Obnovit rozložení“. Kolidující testy nastavují izolovaný `HOME` (`test_settings_isolation`).
- Docky Knihovna/Navigátor sloučit do záložek (méně svislého tlačítkového šumu); F7 jako spodní dok.

## 4. Priorita a rozsah
| # | Položka | Typ | Odhad | Dopad na testy |
|---|---|---|---|---|
| 1 | Oprava kolize `Ctrl+Shift+S` (makro → např. `Ctrl+Alt+M`) | rychlá výhra | 5 min | smoke: test unikátnosti zkratek |
| 2 | Tooltipy „název (zkratka)“, statustipy, `setObjectName` všem lištám | rychlá | 0,5 d | smoke: `tb.toolTip` obsahuje zkratku |
| 3 | `saveGeometry/saveState` + „Obnovit rozložení“ | rychlá | 0,5 d | izolovaný QSettings; test restore |
| 4 | Stavový řádek: souřadnice, mřížka, zoom, F7 odznak | střední | 1 d | smoke: `cursor_moved`, text widgetů |
| 5 | Ikony (`ui/icons.py`, SVG sada, téma) + checkable nástroje | střední | 2 d | smoke: ikony nenulové v obou tématech; pozor na `grab()` screenshot |
| 6 | Rozdělení lišt + kontextová viditelnost podle záložky | střední | 1,5 d | upravit testy, co hledají akce `toolbar.actions()`; nový test podle `_kind_of` |
| 7 | Chybějící nástroje v liště: Vložit značku, Otočit, Zrcadlit*, Text*, Přerušení* | střední–velké | 1–3 d | *Zrcadlit/Text/Přerušení vyžadují změnu modelu/formátu (FORMAT_VERSION + migrace) → nejdřív Otočit a Vložit značku |
| 8 | Paleta příkazů `Ctrl+K` | střední | 1 d | test: filtr najde akci, Enter ji spustí |
| 9 | Nemodální dok „Kontrola“ místo `ChecksDialog.exec` | střední | 1 d | stávající testy `run_checks` (dialog) přepsat |
| 10 | Kontextová menu canvasu + prázdný stav | střední | 1,5 d | nové testy přes `contextMenuEvent`/`QMenu` stub |

Doporučené pořadí: 1–3 (jeden commit, bez rizika), pak 5+6 (viditelný efekt „lišta s funkcemi“), 4, 8, 7, 9, 10.
Dopady: testy sahající na `win.menuBar()` (test_gui_smoke:245) zůstanou platné; přidat do `test_gui_smoke.py` testy zkratek, ikon (dark/light),
`saveState` round-trip a viditelnosti lišt po přepnutí záložky; `ruff` – nové soubory v `ui/` bez Qt importu v `model/`.
