- **Souřadnicová síť rámečku podle velikosti listu, zodpovědný projektant v průvodci** – síť v okraji rámečku
  se na větším listu rozšiřuje polí stejné velikosti jako na A3 (A2 12 × 9, A1 17 × 12, A0 24 × 18, vlastní formát
  obdobně; nejméně 8 × 6, sloupce bez I a O, za Z AA…), křížové odkazy používají stejnou síť. Průvodce novým
  projektem má pole **Zodpovědný projektant** (`meta["responsible"]`, do razítka). `model/frame.py`
  (`grid_dims`, `grid_col_label`), `ui/dialogs.py`; testy `test_doc_pages.py`, `test_wizard_battery.py`.
