- **Testy: hlídač „bez Qt“ pokrývá i generátor** – pravidlo z `CLAUDE.md`, že `envocad/generator/` nesmí importovat
  Qt ani `envocad.ui`, teď hlídá stejný test jako u `model`, `library` a `cmd` (`QT_FREE` v
  `tests/test_model_pure.py`). Generátor Qt neimportuje, kód se neměnil.
