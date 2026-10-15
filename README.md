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

v0.2 – jednopólové schéma FVE, listy rozvaděčů (schéma + fyzické rozložení na DIN lištách), šablony rozvaděčů,
výkazy (xlsx) a protokol kusového ověření (docx), export DXF/PDF, import symbolů z DXF, tmavý režim.

Dokumentace: `docs/ARCHITECTURE.md`, `docs/LIBRARY_FORMAT.md`, `docs/ROADMAP.md`.
Pokyny pro agenty: `CLAUDE.md`.

## Ovládání editoru

| Akce | Jak |
|---|---|
| Vložit symbol | dvojklik v panelu Knihovna, klik do výkresu, vyplnit parametry v dialogu (Esc zruší režim) |
| Upravit parametry | dvojklik na prvek nebo vodič |
| Posun | tažení myší (snap na mřížku 2,5 mm) |
| Rotace | `R` (o 90°) |
| Vodič | `W`, klik na port → klik na port, vyplnit parametry (označení, kabel, průřez) |
| Smazat | `Delete` |
| Zoom / posun pohledu | kolečko / střední tlačítko |
| Undo / redo | `Ctrl+Z` / `Ctrl+Y` |
| Tmavý / světlý režim | `Ctrl+D` |
| Otevřít rozvaděč | dvojklik na blok ROZVADĚČ (poprvé nabídne šablonu) |
| Rozložení rozvaděče | `Ctrl+L` na listu rozvaděče; přístroje přetáhnout na DIN lišty |
| Výkazy / protokol | menu Výstupy (xlsx, docx) |
