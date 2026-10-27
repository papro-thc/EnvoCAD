- **Velikost papíru z pravého tlačítka, rozvodnice ETI, výběr svodičů** – pravé tlačítko na prázdném místě listu
  nebo na záložce nabídne **Formát listu** (ve vícepólu / plánu svorkovnice **Formát stran schématu**): A4…A0 na
  šířku i na výšku, volný A4 a **Vlastní…** (šířka × výška v mm), krokem undo. Katalog: 33 rozvodnic **ETI ETIBOX**
  (ECT, ECM, ECG, ECH, MB – z katalogu ETIBOX DIDO a produktových stránek ETI, `enclosures_eti.csv`). Oprava: výběr
  artiklu u svodiče přepětí už nefiltruje podle pólů značky (výchozí 3 skrylo AC svodiče 3+NPE Eaton a OEZ).
  `ui/main_window.py`, `ui/dialogs.py`; testy `test_formaty_stran.py`, `test_gui_smoke.py`.
