- **Generátor: volitelné značení rozvaděčů** – ve specifikaci `board_prefix` (druh rozvaděče → předpona:
  `dc_route`, `dc_tech`, `ac`, `main`, `mv`, `meter`); rozvaděče po trase a u technologie na střídač dostanou předponu
  + číslo (RDS1, RDS2…), ostatní předponu. Značení se propíše do bloku na JPS, listu (`loc`) i textů vývodů; bez volby
  zůstává dnešní značení (RDC, RFVE.DC, RFVE.AC, HR, RVN, RE). Neplatná předpona nebo kolize → česká chyba.
  Zadané `chain.<role>.ref` má přednost. Test `test_generator_board_marking.py`.
