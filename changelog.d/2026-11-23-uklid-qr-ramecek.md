- **Úklid: zbytky QR kódu v rámečku** – po odebrání QR kódu zůstalo v kódu nikdy neplněné pole `rects`
  (`FrameGeometry`, `MirrorGeometry`) a jeho kreslení (Qt `ui/render.py`, DXF `_draw_geometry` → SOLID); odstraněno,
  komentáře o QR opraveny. Výstup výkresu, PDF ani DXF se nemění. Testy `test_switchboard_a4.py`, `test_xref.py`.
