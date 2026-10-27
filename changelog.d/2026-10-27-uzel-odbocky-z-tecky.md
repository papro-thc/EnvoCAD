- **Oprava: odbočka z uzlu bez „kytičky“** – uzel odbočky (`sb.junction`) má porty ve středu tečky, takže vodiče
  i odbočka vycházejí přímo z tečky; nový vodič z uzlu dostane volný port na straně k cíli (dřív první volný –
  vodič vyšel nahoru a obloukem se vracel přes tečku). `ui/canvas.py`, `tools/gen_builtin_fve.py`, test
  `test_junction_wires_leave_from_dot`.
