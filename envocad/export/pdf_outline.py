"""Záložky (osnova) hotového PDF – post-processing přes pypdf. Bez Qt. QPdfWriter osnovu neumí, proto se doplní
do souboru až po vykreslení (`doc_pdf`: jedna záložka na každý řádek obsahu dokumentace)."""
from __future__ import annotations

import io
from pathlib import Path


def add_bookmarks(path: Path | str, items: list[tuple[str, int]]) -> int:
    """Doplní do hotového PDF `path` plochou (jednoúrovňovou) osnovu v pořadí `items` = (název, index fyzické
    strany od 0). Soubor se přepíše jen pokud je co přidat. Vrací počet záložek. Index mimo stránky PDF → `IndexError`
    (nic se nezapíše)."""
    if not items:
        return 0
    from pypdf import PdfReader, PdfWriter

    p = Path(path)
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(p.read_bytes())))
    n_pages = len(writer.pages)
    for _title, page_idx in items:
        if not 0 <= page_idx < n_pages:
            raise IndexError(f"PDF nemá stranu {page_idx + 1}")
    for title, page_idx in items:
        writer.add_outline_item(title=title, page_number=page_idx)
    buf = io.BytesIO()
    writer.write(buf)
    p.write_bytes(buf.getvalue())
    return len(items)
