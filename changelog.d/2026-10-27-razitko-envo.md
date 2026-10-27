- **Razítko ENVO v popisovém poli** – popisové pole všech listů (JPS, vícepól, plán svorkovnice, jednopólové schéma,
  PDF i DXF) má rozložení razítka ENVO z `Razítko fixed.dwg` zhuštěné do 180 × 32 mm: logo ENVO (barevné, v DXF
  šrafy) s adresou, stavba, investor, místo, vypracoval, zodpovědný projektant, název výkresu,
  stupeň, zakázkové a archivní číslo, datum, formát, měřítko, revize a číslo výkresu se stranou dokumentace. Nová
  pole ve Vlastnostech projektu (`responsible`, `stage`, `archive`, `scale`). Logo
  `resources/envo_logo.json`. Rámeček s razítkem je nově **ve výchozím nastavení zapnutý** (export bez razítka jen
  po vypnutí v Zobrazit → Rámeček a popisové pole). `model/frame.py`, `settings.py`, `ui/render.py`,
  `export/dxf_export.py`, `ui/dialogs.py`.
