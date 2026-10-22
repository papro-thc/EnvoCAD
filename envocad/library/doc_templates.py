"""Šablony dokumentů (technická zpráva, DSPS) – vyhledání ve složkách knihovny. Bez Qt.

Stejně jako makra a topologie: vestavěné `library/builtin/doc_templates/`, sdílené `<shared_library_dir>/doc_templates/`,
vlastní `~/.envocad/doc_templates/`; pozdější složka přebíjí stejný název souboru (bez přípony). Soubory `.docx`
(firemní šablona Word s poli `{{…}}`) a `.md` (zdroj vestavěných šablon). Druh podle předpony názvu: `tz…` = technická
zpráva, `dsps…` = dokumentace skutečného provedení, jiné se nabídnou u obou; `_…` = vkládaná část (`@include`),
v seznamu není. Syntaxe `docs/design/tz_dsps.md`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("envocad.library")

BUILTIN_DIR = Path(__file__).parent / "builtin" / "doc_templates"
DIR_NAME = "doc_templates"
SUFFIXES = (".docx", ".md")
KINDS = ("tz", "dsps")


@dataclass(frozen=True)
class DocTemplate:
    name: str          # název souboru bez přípony (klíč přebíjení)
    path: Path
    source: str        # vestavěná | sdílená | vlastní

    @property
    def kind(self) -> str:
        """„tz“ / „dsps“ podle předpony názvu, jinak „“ (obecná)."""
        low = self.name.lower()
        return next((k for k in ("dsps", "tz") if low.startswith(k)), "")

    @property
    def label(self) -> str:
        return f"{self.name} ({self.source}, {self.path.suffix.lstrip('.')})"


def user_dir() -> Path:
    from envocad.settings import settings_path
    return settings_path().parent / DIR_NAME


def shared_dir() -> Path | None:
    try:
        from envocad.settings import shared_library_dir
        d = shared_library_dir()
    except Exception:  # noqa: BLE001 – vadné nastavení nesmí shodit vestavěné
        return None
    return (Path(d) / DIR_NAME) if d else None


def template_dirs() -> list[tuple[Path, str]]:
    out = [(BUILTIN_DIR, "vestavěná")]
    sd = shared_dir()
    if sd:
        out.append((sd, "sdílená"))
    out.append((user_dir(), "vlastní"))
    return out


def list_templates(kind: str | None = None) -> list[DocTemplate]:
    """Šablony seřazené podle názvu; `kind` = jen daného druhu a obecné. Nedostupná složka se přeskočí."""
    found: dict[str, DocTemplate] = {}
    for d, source in template_dirs():
        try:
            files = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in SUFFIXES
                           and not p.name.startswith(("~$", ".", "_")))
        except OSError:
            continue
        for p in files:
            found[p.stem.lower()] = DocTemplate(p.stem, p, source)
    out = sorted(found.values(), key=lambda t: t.name.lower())
    if kind:
        out = [t for t in out if t.kind in (kind, "")]
    return out


def builtin_template(kind: str) -> Path:
    """Vestavěná šablona druhu (`tz.md`, `dsps.md`)."""
    if kind not in KINDS:
        raise ValueError(f"Neznámý druh šablony: {kind}")
    return BUILTIN_DIR / f"{kind}.md"


def default_template(kind: str) -> DocTemplate:
    """Šablona, kterou dialog nabídne jako první: přebitá vestavěná (stejný název ve sdílené / vlastní složce),
    jinak vestavěná."""
    for t in list_templates(kind):
        if t.name.lower() == kind:
            return t
    return DocTemplate(kind, builtin_template(kind), "vestavěná")
