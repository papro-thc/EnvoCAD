- **Nástroj: přehled artiklů bez teplot** – `python tools/report_missing_temps.py [adresář]` vypíše počty artiklů
  bez `t_min_c` / `t_max_c` podle souboru a výrobce a zvlášť soubory bez těchto sloupců (jen čte, vždy končí
  kódem 0). Nová `read_header` v `library/components.py`. Test `test_report_missing_temps.py`.
