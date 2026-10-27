- **Vodiče v rozvaděči bez průřezu** – v listu rozvaděče dialog vodiče i panel vlastností nabízejí jen výrobní údaje
  (barva, koncovky, výrobní seznam); označení, typ kabelu, průřez, délka a uložení jsou jen u propojení mezi
  rozvaděči, technologií a panely (blokové schéma). Průřez vnitřních vodičů dál dopočte výrobní zapojovací seznam
  podle jištění. `model/project.py` (`wire_attributes`), `ui/canvas.py`, `ui/panels.py`, `ui/multipole_view.py`;
  test `test_switchboard_wire_attributes_without_cross`.
