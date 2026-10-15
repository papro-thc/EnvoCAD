# EnvoCAD – architektura

Interní nástroj ENVO pro elektro-dokumentaci FVE (a později dalších oborů).
Náhrada EPLAN pro naše potřeby: jednopólová schémata, rozvaděče, výkazy, vlastní knihovna prvků.

## Technologický stack a proč

| Vrstva | Volba | Důvod |
|---|---|---|
| Jazyk | Python 3.11+ | Agenti ho píší nejspolehlivěji, snadná údržba bez profi vývojáře |
| GUI | PySide6 (Qt 6) | Cross-platform Windows/Linux, `QGraphicsScene` je přímo stavěná na 2D editory schémat (zoom, výběr, hit-test, undo) |
| DXF | ezdxf | Zralá knihovna pro čtení/zápis DXF (import symbolů od výrobců, export do ZWCAD) |
| Úložiště knihovny | SQLite (+ JSON soubory symbolů v gitu) | Bez serveru, jeden soubor, později lze přepnout na PostgreSQL pro sdílení v ENVO |
| Formát projektu | JSON (`.ecp`) | Čitelné, diffovatelné v gitu, snadno strojově generovatelné |
| Balení | PyInstaller | Jeden .exe / AppImage |

Zvažované a zamítnuté: Tauri/Electron (slabší DXF ekosystém v JS, složitější build), nadstavba nad ZWCAD (vendor lock-in, nelze provozovat bez licence ZWCAD).

## Vrstvy

```
envocad/
  model/      čistá data, žádné Qt  → testovatelné headless
    symbol.py   Symbol = grafická primitiva + porty + atributy
    project.py  Project → Sheet → Element (instance symbolu) + Wire
  library/    knihovna prvků
    store.py       SQLite úložiště symbolů a komponent (artiklů)
    dxf_import.py  DXF → Symbol
    builtin/       startovní symboly (JSON), verzované v gitu
  ui/         PySide6 GUI (nikdy neobsahuje business logiku)
    canvas.py       QGraphicsView – mřížka, zoom, snap
    items.py        QGraphicsItem obaly nad Element/Wire
    main_window.py  okno, panely, akce
  export/     DXF, PDF, (později výkaz materiálu .xlsx)
```

Zásada: **model nezávisí na UI.** Vše, co lze, se testuje bez spuštění Qt.

## Klíčové pojmy

- **Symbol** – grafická definice (čáry, kružnice, oblouky, texty) v jednotkách mm na mřížce 2,5 mm,
  s pojmenovanými **porty** (připojovací body) a sadou **atributů** (označení, typ, Un, In…).
  Nezávislý na konkrétním výrobku.
- **Komponenta (artikl)** – konkrétní výrobek (např. `SMA STP 50-40`) s parametry a odkazem na symbol.
  Jeden symbol střídače → stovky artiklů.
- **Element** – instance symbolu na listu: pozice, rotace, hodnoty atributů, volitelně přiřazený artikl.
- **Wire** – vodič mezi dvěma porty (element.port → element.port), má atributy (průřez, typ kabelu, označení).
- **Sheet** – list výkresu (formát, rámeček, popisové pole).
- **Project** – zakázka: metadata (název, investor, číslo zakázky), seznam listů.

Z tohoto modelu se generuje vše ostatní (výkaz materiálu, seznam kabelů, svorkovnice) – to je hlavní
přidaná hodnota oproti ručnímu kreslení v ZWCAD.

## Souřadnice a jednotky

- Model i symboly v **mm**, Y nahoru jako v CADu (ve scéně Qt se jen převrátí osa).
- Mřížka 2,5 mm (jako EPLAN), snap na mřížku standardně zapnutý.
- Porty symbolů musí ležet na mřížce.

## Formát symbolu (JSON)

Viz `docs/LIBRARY_FORMAT.md`.

## Undo/redo

`QUndoStack` v UI; každá změna modelu je `QUndoCommand` (přidat/smazat/posunout element, přidat vodič,
změnit atribut). Model sám o undo neví.

## Rozšiřitelnost na další obory

Nic v modelu není specifické pro FVE – „FVE“ je jen sada symbolů, šablon listů a generátorů výstupů.
Další obor = další složka v `library/builtin/` + případně vlastní exportní šablony.

## Jednopól ↔ vícepól (návrh)

Jeden model, dva pohledy nad stejnými daty:

- **Jednopólové schéma (JPS)** – kreslí se první. `Wire` je jedna čára, ale nese `conductors`
  (např. `["L1","L2","L3","N","PE"]`) a `Element` má `poles`.
- **Vícepólové schéma** – odvozený pohled: každá žíla z `conductors` se rozkreslí jako samostatná čára
  mezi póly přístrojů (pól = port + index žíly). Uživatel zde přiřazuje svorky: `Wire.terminals[žíla] =
  {"a": "X1:3", "b": "F2:1"}`. Nic se nekopíruje – změna typu kabelu v JPS se projeví i ve vícepólu a naopak.
- Přepínání pohledu = jiný `QGraphicsScene` nad stejným `Sheet`; symboly pro vícepól se generují z jednopólových
  (N× opakovaný pólový symbol + společná spoušť), vlastní vícepólové symboly v knihovně jsou volitelné.
- Svorkovnice a seznam kabelů se generují z `Wire.conductors` + `Wire.terminals`.
