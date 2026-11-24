- **Import z PVsyst (.PAN/.OND)** – `Knihovna → Importovat z PVsyst…` načte FV modul nebo střídač do artiklů (rozměry
  m → mm, teplotní koeficienty mV/°C a mA/°C → %/K, `i_mppt_max_a` jen u střídače s jedním MPPT); chybějící hodnoty
  hlásí varováním, před přepsáním existujícího artiklu se zeptá, artikl nese poznámku „import PVsyst – ověřit“. Testy `test_pvsyst_import.py`, `test_pvsyst_import_gui.py`.
