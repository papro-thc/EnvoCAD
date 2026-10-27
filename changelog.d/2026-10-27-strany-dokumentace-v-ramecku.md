- **Strana dokumentace v popisovém poli** – vedle čísla listu (sedí s křížovými odkazy) ukazuje popisové pole
  **Strana n/N** celé PDF dokumentace u listů JPS, vícepólů, plánů svorkovnic a jednopólového schématu, i v editoru
  a samostatných exportech PDF / DXF. Čísla stran se uloží (krokem undo) při exportu dokumentace nebo příkazem
  **Projekt → Přečíslovat strany dokumentace**. `model/frame.py` (`doc_page`), `export/doc_pdf.py`
  (`documentation_page_numbers`), pohledy a DXF; test `test_doc_pages.py`.
