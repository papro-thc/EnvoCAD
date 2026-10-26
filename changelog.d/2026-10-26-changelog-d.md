- **Záznamy změn v `changelog.d/`** – každý PR přidá vlastní soubor `changelog.d/RRRR-MM-DD-nazev.md` místo úpravy
  `CHANGELOG.md`, takže si paralelní PR nepřekážejí. `tools/release.py prepare` je při vydání přenese do sekce verze
  (nejnovější nahoře) a smaže. Pravidlo v `CLAUDE.md`, popis v `changelog.d/README.md`, test `test_changelog_d.py`.
