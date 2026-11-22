- **Dokumentace odpovídá kódu** – `docs/ARCHITECTURE.md` a `docs/LIBRARY_FORMAT.md` uvádějí formát projektu v18
  (A0, formáty na výšku, vlastní rozměr); `docs/ROADMAP.md` bez odkazu na neexistující soubor, bez QR v popisovém
  poli a s doplněným logem ENVO; `docs/design/ux_lista.md` má stav „realizováno“. Nový test
  `tests/test_docs_format_version.py` hlídá, aby se číslo verze v dokumentaci nerozešlo s `FORMAT_VERSION`.
