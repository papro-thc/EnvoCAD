# EnvoCAD

Interní nástroj ENVO pro kreslení jednopólových schémat FVE a správu vlastní knihovny elektro prvků.
Cíl: nahradit EPLAN pro naše potřeby, s jedním modelem, ze kterého se generují schémata, výkazy a dokumentace.

## Instalace (Windows i Linux)

```
python -m venv .venv
.venv\Scripts\activate        # Windows   |   source .venv/bin/activate   # Linux
pip install -e .[dev]
python -m envocad
```

## Stav

v0.1 – editor jednopólového schématu: knihovna symbolů FVE, vkládání, vodiče, vlastnosti,
uložení projektu (`.ecp`), export DXF/PDF, import symbolů z DXF.

Dokumentace: `docs/ARCHITECTURE.md`, `docs/LIBRARY_FORMAT.md`, `docs/ROADMAP.md`.
Pokyny pro agenty: `CLAUDE.md`.

## Ovládání editoru

| Akce | Jak |
|---|---|
| Vložit symbol | dvojklik v panelu Knihovna, pak klik do výkresu (Esc zruší) |
| Posun | tažení myší (snap na mřížku 2,5 mm) |
| Rotace | `R` (o 90°) |
| Vodič | `W`, klik na port → klik na port |
| Smazat | `Delete` |
| Zoom / posun pohledu | kolečko / střední tlačítko |
| Undo / redo | `Ctrl+Z` / `Ctrl+Y` |
