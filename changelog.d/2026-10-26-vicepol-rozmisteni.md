- **Vícepól: rozmístění ručně kresleného listu rozvaděče** (`model/multipole.py`, `model/multipole_geometry.py`,
  `ui/multipole_view.py`): řadu přístroje určuje silový tok (`_power_depth`) – vodič na svorku cívky (A1/A2,
  `is_control_wire`) ani lišta N/PE nezkrátí cestu od přívodu, tok přístrojem jde z jedné strany na druhou a soutok
  (přepínač sítí I-0-II) je pod nejhlubším přívodem. AC větev se tak kreslí shora dolů jako DC stringy (přívod →
  jistič → stykač → přepínač → jistič → vývod v jednom sloupci); když se taková kresba na výšku strany nevejde ani po
  zhuštění, použije se mělčí rozmístění. Pokračování toku jde přímo pod rodiče, odbočka bokem: DC string X → FU → X
  dál je jedna svislá linie a přepěťová ochrana (odbočka ze svorek odpínače) stojí vedle něj. Uzel (`sb.junction`) má
  ve vícepólu port k přívodu nahoře, hlavní větev dolů a odbočky doprava (`junction_view_symbols`, jen pohled) a žíly
  končí i začínají ve středu tečky. Strom silově napojený na jiný (záložní přívod do přepínače) jde hned za něj a
  nesouvisející strom (ovládání) zaplní volné místo na dřívější straně; podstrom se nerozdělí tak, že by rodič zůstal
  sám na konci strany. Řada jen s uzly má menší mezeru. Lišty ve stejné řadě se nekreslí přes sebe
  (`_clear_of_bars`) a když se kresba nevejde, řada lišt se zvedne nad popisové pole vedle přístrojů; přerušení na
  okraji strany nejde pod spodní okraj. Popisek přístroje přes cizí žílu nebo text se přesune vedle prvku
  (`_place_element_label` → `ElementPoles.label_lines`, `MultipoleGeometry.element_labels`; scéna, DXF i F7 kreslí
  stejnou polohu). Na obrazovce je každá strana vícepólu samostatný papír s obrysem (i bez rámečku), mezery mezi
  stranami bez mřížky; tisk a export beze změny. Regresní projekt `tests/data/vicepol_rfve_rucne.ecp` (překryvy
  textů A3 bez ručních poloh 26 → 4, s ručními 23 → 17, A4 37 → 26 / 29 → 11, A4 na výšku 48 → 24 / 38 → 9);
  vícepól generovaných projektů beze změny překryvů, RE s nepřímým měřením 2 překryvy místo 3. Formát se nemění.
  Test `test_multipole_rucne.py`.
