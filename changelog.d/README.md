# Záznamy změn čekající na vydání

Každá změna (PR) si sem přidá **vlastní soubor** místo úpravy `CHANGELOG.md` – paralelní PR si tak nikdy
nepřekážejí. `python tools/release.py prepare X.Y.Z` při vydání všechny záznamy přenese do `CHANGELOG.md`
(sekce `## X.Y.Z – datum`, nejnovější nahoře) a soubory smaže.

- **Jméno:** `RRRR-MM-DD-kratky-nazev.md`, např. `2026-10-26-lista-pe-popisek.md` (datum = řazení, název bez
  diakritiky a mezer, jedinečný).
- **Obsah:** jedna odrážka ve stylu `CHANGELOG.md` – tučný název, pomlčka, co se změnilo z pohledu uživatele,
  na konci soubory / testy. Další řádky odsazené dvěma mezerami:

```markdown
- **Oprava: popisek lišty PE/N** – lišta `sb.pe_bar` ukazuje u čáry druh z parametru **Druh**; dřív tam bylo
  vždy „PE“. Test `test_pe_bar_label.py`.
```

Formát hlídá `tests/test_changelog_d.py`.
