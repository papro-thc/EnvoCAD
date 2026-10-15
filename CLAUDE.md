# EnvoCAD – pokyny pro AI agenty

Interní CAD nástroj ENVO pro elektro-dokumentaci FVE (náhrada EPLAN). Python 3.11+, PySide6, ezdxf, SQLite.

## Než začneš
- Přečti `docs/ARCHITECTURE.md` a `docs/LIBRARY_FORMAT.md`.
- Úkoly a priority: `docs/ROADMAP.md`.
- Tým agentů a přiřazené modely: `docs/AGENTS.md` (definice v `.claude/agents/`). Orchestrátor = hlavní session (Fable).

## Pravidla
- `envocad/model/` a `envocad/library/` **nesmí importovat Qt**. Vše tam musí jít otestovat headless.
- Jednotky: mm, Y nahoru (CAD konvence). Mřížka 2,5 mm. Převod na Qt souřadnice dělá jen `ui/`.
- Každá změna modelu z GUI jde přes `QUndoCommand` (viz `ui/commands.py`).
- Nové symboly = JSON do `envocad/library/builtin/<obor>/`, porty na mřížce, atribut `ref` povinný.
- Texty v UI česky, identifikátory v kódu anglicky.
- Nepřidávej závislosti bez důvodu; pokud ano, zapiš do `pyproject.toml`.

## Spuštění a testy
```
pip install -e .
python -m envocad              # GUI
pytest                         # headless testy
QT_QPA_PLATFORM=offscreen pytest tests/test_gui_smoke.py
```

## Před odevzdáním
- `pytest` zelené, `ruff check .` bez chyb.
- Pokud jsi změnil formát projektu nebo symbolu, zvedni `FORMAT_VERSION` a doplň migraci.
