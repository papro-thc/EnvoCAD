- **Razítko ENVO v popisovém poli** – popisové pole všech listů (JPS, vícepól, plán svorkovnice, jednopólové schéma,
  PDF i DXF) má rozložení razítka ENVO z `Razítko fixed.dwg` zhuštěné do 180 × 32 mm: logo ENVO (barevné, v DXF
  šrafy) s adresou, stavba, investor, místo, vypracoval, schválil, zodpovědný projektant, koordinátor, název výkresu,
  stupeň, zakázkové a archivní číslo, datum, formát, měřítko, revize a číslo výkresu se stranou dokumentace. Nová
  pole ve Vlastnostech projektu (`approved`, `responsible`, `coordinator`, `stage`, `archive`, `scale`). Logo
  `resources/envo_logo.json`. `model/frame.py`, `ui/render.py`, `export/dxf_export.py`, `ui/dialogs.py`.
