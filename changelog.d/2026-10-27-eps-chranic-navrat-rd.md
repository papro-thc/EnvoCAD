- **EPS rodinného domu: chránič a návrat zálohy do RD** – záloha se kreslí jako v praxi: střídač (BACKUP) → chránič
  30 mA → přepínač sítí → vývod XB{i} (RFVE, vestavěný kód i makro „EPS přepínač sítí“). Je-li v řetězci stávající
  RD / HR, vede XB{i} kabelem přes pár přerušení „EPS-RD“ do RD.XE{i} a „zálohované okruhy“ visí na RD.XB{i} pod
  blokem (v listu RD průchod svorkami). Vícepól: přístroj napájený z přístroje i ze sběrnice visí pod přístrojem
  (jistič síťové strany přepínače). `generator/boards/eps.py`, `generator/chain.py`, `model/multipole.py`,
  `tools/gen_builtin_macros.py`; test `test_eps_changeover_in_house`, snímek generátoru (případy s EPS a baterií).
