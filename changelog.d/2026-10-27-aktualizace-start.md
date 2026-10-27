- **Oprava: aktualizace při startu se opravdu volá** – `app.main` nově spouští nabídku nové verze samostatné aplikace
  (sdílená složka, `latest.json`) a po otevření okna oznámí výsledek aktualizace (i selhání v klonu s odkazem na
  `update.log`); dřív zůstalo zapojení mimo start a obojí byl mrtvý kód. `pypdfium2` ve vývojových závislostech;
  ROADMAP: export DXF vícepólu a příkazový řádek jsou hotové.
