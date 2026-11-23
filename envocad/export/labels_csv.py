"""Export štítků do CSV (čistá data, bez Qt): středník, UTF-8 s BOM – Excel i tiskárny štítků to otevřou přímo."""
from __future__ import annotations

import csv
from pathlib import Path

from envocad.export import reports
from envocad.library.store import LibraryStore
from envocad.model.project import Project


def write_labels_csv(project: Project, lib: LibraryStore, path: str | Path) -> int:
    """Zapíše štítky projektu do `path`; vrací počet řádků bez hlavičky."""
    head, rows = reports.labels(project, lib, None)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(head)
        w.writerows(rows)
    return len(rows)
