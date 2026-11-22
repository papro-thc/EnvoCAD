# EnvoCAD – pokyny pro AI agenty

Interní CAD nástroj ENVO pro elektro-dokumentaci FVE (náhrada EPLAN). Python 3.11+, PySide6, ezdxf, SQLite.

## Než začneš
- Přečti `docs/ARCHITECTURE.md` a `docs/LIBRARY_FORMAT.md`.
- Úkoly a priority: `docs/ROADMAP.md`; konkrétní práce pro agenty = GitHub Issues se štítkem `agent-ready`.
- Tým agentů a přiřazené modely: `docs/AGENTS.md` (definice v `.claude/agents/`). Orchestrátor = hlavní session (Fable),
  jeho postup je v `.claude/agents/orchestrator.md`.

## Architektura v kostce
```
envocad/
  model/       čistá data (Symbol, Project → Sheet → Element + Wire, topologie) – BEZ Qt
  library/     knihovna prvků: SQLite store, importy DXF/QET/EPLAN CSV, builtin/ JSON symboly a artikly – BEZ Qt
  generator/   generátor FVE podle topologie (build, pv, chain, boards/) – BEZ Qt
  cmd/         příkazový řádek (GUI, CLI, skripty, agenti) – BEZ Qt (hlídá tests/test_model_pure.py)
  export/      DXF, PDF, xlsx, docx
  ui/          PySide6 GUI, žádná business logika
tests/         pytest; GUI testy běží offscreen
changelog.d/   jeden soubor na změnu (ne CHANGELOG.md)
```
Podrobně: `docs/ARCHITECTURE.md`.

## Pravidla
- `envocad/model/` a `envocad/library/` **nesmí importovat Qt**. Vše tam musí jít otestovat headless.
- Jednotky: mm, Y nahoru (CAD konvence). Mřížka 2,5 mm. Převod na Qt souřadnice dělá jen `ui/`.
- Každá změna modelu z GUI jde přes `QUndoCommand` (viz `ui/commands.py`).
- Nové symboly = JSON do `envocad/library/builtin/<obor>/`, porty na mřížce, atribut `ref` povinný.
- Texty v UI česky, identifikátory v kódu anglicky.
- Nepřidávej závislosti bez důvodu; pokud ano, zapiš do `pyproject.toml`.

## Spuštění a testy
```
pip install -e ".[dev]"
python -m envocad                                  # GUI
QT_QPA_PLATFORM=offscreen pytest -q                # všechny testy (CI je spouští takhle na Linuxu i Windows)
QT_QPA_PLATFORM=offscreen pytest tests/test_x.py   # jeden soubor
ruff check .
python tools/check_licensed_data.py                # žádná licencovaná data výrobců v gitu
```

## Před odevzdáním
- `pytest` zelené, `ruff check .` bez chyb, `python tools/check_licensed_data.py` OK.
- Pokud jsi změnil formát projektu nebo symbolu, zvedni `FORMAT_VERSION` a doplň migraci.
- Záznam změny **nepiš do `CHANGELOG.md`**, ale jako nový soubor `changelog.d/RRRR-MM-DD-nazev.md`
  (jedna odrážka, viz `changelog.d/README.md`) – paralelní PR si pak nepřekážejí.

## Git a GitHub – tvrdá pravidla pro agenty
- **Nikdy nepushuj do `main`**, nedělej `git push --force` a neslučuj PR. Main slučuje jen člověk.
- Jedna issue = jedna větev `agent/issue-<číslo>-<kratky-nazev>` = jeden PR s `Closes #<číslo>`.
- Pracuj **jen na issue se štítkem `agent-ready`**. Neber issue se štítkem `agent-in-progress` nebo `agent-question`.
- Drž se rozsahu issue. Co najdeš navíc, zapiš do PR jako „Mimo rozsah“, neopravuj to.
- Nemaž ani neoslabuj existující testy, aby prošly. Červený test = chyba v kódu, ne v testu (pokud issue neříká jinak).

## Oborová rozhodnutí dělá člověk
Elektro, normy a zvyklosti ENVO (jištění, průřezy, značení IEC 81346, výběr artiklu, vzhled výkresu…) **nedomýšlej**.
Když zadání nestačí: napiš do issue komentář s otázkou (co přesně, jaké varianty vidíš, co doporučuješ a proč),
přidej štítek `agent-question`, odeber `agent-in-progress` a skonči bez PR. Totéž, když je issue zjevně
na víc než pár hodin práce – navrhni rozdělení na menší issue.

## Licencovaná data – repo nesmí obsahovat
- Nic z **EPLAN Data Portalu** (obchodní data CSV, DXF/E3D makra, `.edz`, `.ema`, `.epdz`) – složka `EPLAN/` je v `.gitignore`.
- PDF datasheety a katalogy výrobců, jejich obrázky a výkresy (`katalogy/`, `datasheets/` jsou v `.gitignore`).
- Do knihovny smí jen **fakta** (parametry: V, A, kW, rozměry, Pv…) zapsaná vlastním formátem + odkaz `url` na zdroj.
  Nekopíruj texty, tabulky ani grafiku 1:1. Licence zdrojů: `docs/SOURCES.md`.
- CI to hlídá skriptem `tools/check_licensed_data.py`; pokud ho tvá změna rozbije, data do gitu nepatří.
- Značky `envocad/library/builtin/qet/` (QElectroTech, CC BY 3.0): licence kolekce zakazuje použití jako dat pro trénink
  modelů strojového učení; při přidávání dalších značek zachovat atribuci (`ATTRIBUTION.md`).
