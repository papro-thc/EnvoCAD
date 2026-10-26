"""Záznamy změn v `changelog.d/` (paralelní PR nepřepisují CHANGELOG.md) a jejich přenos do CHANGELOG při vydání."""
import re
from pathlib import Path

import pytest

from envocad import updater

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*\.md$")


@pytest.mark.parametrize("path", updater.fragment_files(ROOT / "changelog.d"), ids=lambda p: p.name)
def test_fragment_format(path):
    assert NAME.match(path.name), f"{path.name}: jméno RRRR-MM-DD-nazev.md (malá písmena bez diakritiky)"
    text = path.read_text(encoding="utf-8").strip()
    assert text.startswith("- **"), f"{path.name}: jedna odrážka „- **Název** – …“"
    assert all(not ln or ln.startswith("  ") for ln in text.splitlines()[1:]), f"{path.name}: další řádky odsazené"
    assert "## " not in text


def test_fragments_go_to_unreleased_newest_first(tmp_path):
    d = tmp_path / "changelog.d"
    d.mkdir()
    (d / "README.md").write_text("# nic", encoding="utf-8")
    (d / "2026-10-20-starsi.md").write_text("- **Starší** – a\n", encoding="utf-8")
    (d / "2026-10-26-novejsi.md").write_text("- **Novější** – b\n  pokračování\n", encoding="utf-8")
    files = updater.fragment_files(d)
    assert [p.name for p in files] == ["2026-10-26-novejsi.md", "2026-10-20-starsi.md"]
    log = "# Changelog\n\n## Nevydáno\n- **Ruční** – c\n\n## 0.11.0 – 2026-10-01\n- **A** – d\n"
    out = updater.add_fragments(log, [p.read_text(encoding="utf-8") for p in files])
    assert out.index("Novější") < out.index("pokračování") < out.index("Starší") < out.index("Ruční") < out.index("0.11.0")
    cut = updater.cut_release(out, "0.12.0", "2026-10-27")
    notes = updater.release_notes(cut, "0.11.0")
    assert notes.startswith("## 0.12.0 – 2026-10-27\n- **Novější**") and "Ruční" in notes
    assert updater.add_fragments(log, []) == log
    with pytest.raises(ValueError):
        updater.add_fragments(log, ["bez odrážky"])
    assert updater.fragment_files(tmp_path / "neni") == []
