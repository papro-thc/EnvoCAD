"""Lišta PE/N (`sb.pe_bar`): popisek u lišty podle atributu `kind`, ne pevné „PE“ ze značky."""
from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, element_symbol


def _texts(sym) -> list[str]:
    return [p["text"] for p in sym.primitives if p.get("type") == "text"]


def test_pe_bar_label_follows_kind(tmp_path):
    lib = LibraryStore(tmp_path / "l.db")
    p = Project()
    bar = Element("sb.pe_bar", 100, 100, attrs={"ref": "X6", "kind": "N"})
    p.sheets[0].elements.append(bar)
    assert _texts(element_symbol(p, bar, lib)) == ["N"]
    bar.attrs["kind"] = "PE"
    assert _texts(element_symbol(p, bar, lib)) == ["PE"]
    bar.attrs["kind"] = ""
    assert _texts(element_symbol(p, bar, lib)) == ["PE"]     # bez druhu = PE jako dřív
    assert _texts(lib.get_symbol("sb.pe_bar")) == ["PE"]      # značka v knihovně se nemění
