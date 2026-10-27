- **Oprava: druhé spuštění EnvoCADu na Windows** – když log drží už běžící EnvoCAD, start nespadne na rotaci logu
  (`PermissionError`), rotace se přeskočí. `logging_setup.py`, test `test_log_rotation_survives_locked_log`.
