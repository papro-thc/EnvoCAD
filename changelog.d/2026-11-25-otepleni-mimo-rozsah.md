- **Oteplení: mimo rozsah metody IEC TR 60890:2022** – skříň s Ae > 11,5 m², šířkou > 1,5 m, více než 5 přepážkami
  nebo teplotou okolí mimo 10–50 °C už nedostane tiché číslo: kontrola F7 hlásí varování `thermal_out_of_scope`
  „mimo rozsah metody IEC TR 60890 – doložit jinak“ s důvodem, výkaz Výpočty a panel skříně místo hodnot a verdiktu
  ukážou totéž. Odkaz v `thermal.py` opraven na vydání 2022. Test `test_thermal_scope.py`.
