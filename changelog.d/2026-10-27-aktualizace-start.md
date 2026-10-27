- **Oprava: aktualizace při startu se opravdu volá** – `app.main` nově spouští nabídku nové verze samostatné aplikace
  (sdílená složka, `latest.json`) a po otevření okna oznámí výsledek aktualizace (i selhání v klonu s odkazem na
  `update.log`); dřív zůstalo zapojení mimo start a obojí byl mrtvý kód. Přidáno CI (GitHub Actions: ruff + pytest
  na Windows) a `pypdfium2` do vývojových závislostí; ROADMAP: export DXF vícepólu a příkazový řádek jsou hotové.
