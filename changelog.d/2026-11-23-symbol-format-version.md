- **Verze formátu symbolu** – JSON symbolu nově nese `format_version` (chybí = 1, `SYMBOL_FORMAT_VERSION`); značka z novější
  verze EnvoCAD se nenačte potichu špatně, ale ohlásí česky (knihovna ji přeskočí s varováním, archiv ji odmítne, import
  ji nepřepíše, editor ji bere jako jen pro čtení). Test `test_symbol_format_version.py`.
