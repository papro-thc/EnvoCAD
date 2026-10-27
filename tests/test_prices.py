"""Ceník artiklů (`library/prices.py`) a výkaz materiálu s cenami (`reports.priced_bom`, mimo PDF dokumentaci)."""
import pytest

from envocad.export import reports
from envocad.generate import build_project
from envocad.library.prices import PriceBook, price_key, read_prices
from envocad.library.store import LibraryStore


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def test_read_prices(tmp_path):
    f = tmp_path / "ceny.csv"
    f.write_text("id;manufacturer;part_number;price_czk\neti-ect12pt;;;1 250,50\n;Eaton;SPCT2-335/4;3200\n"
                 ";X;Y;\n;X;Z;abc\n", encoding="utf-8")
    prices, errs = read_prices(f)
    assert prices == {"eti-ect12pt": 1250.5, price_key("Eaton", "SPCT2-335/4"): 3200.0}
    assert errs and "abc" in errs[0]
    bad = tmp_path / "bad.csv"
    bad.write_text("typ;cena\nA;1\n", encoding="utf-8")
    assert read_prices(bad)[1] and read_prices(tmp_path / "neni.csv") == ({}, [])


def test_price_book_prefers_price_list(lib):
    book = PriceBook(lib, {"eti-ect12pt": 999.0, price_key("Eaton", "SPCT2-335/4"): 3200.0})
    assert book.price("ETI", "ECT12PT") == 999.0                       # přes id artiklu katalogu
    assert book.price("eaton", "spct2-335/4") == 3200.0                # výrobce + typ, bez velikosti písmen
    assert book.price("ETI", "ECT24PT") is None and book.price("ETI", "") is None


def test_priced_bom(lib, tmp_path, monkeypatch):
    p = build_project({"inverters": [{"ref": "T1", "p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200,
                                      "u_mppt_max": 1000, "i_mppt_max": 30, "strings": [18, 18]}]})
    _head, rows = reports.bom(p, lib, None)
    priced = next(r for r in rows if r[2] and r[3])                   # položka s typem a výrobcem
    f = tmp_path / "ceny.csv"
    f.write_text(f"manufacturer;part_number;price_czk\n{priced[3]};{priced[2]};100\n", encoding="utf-8")
    monkeypatch.setattr(reports, "prices_path", lambda: f)
    head2, rows2 = reports.priced_bom(p, lib, None)
    assert head2[-2:] == ["Cena/ks [Kč]", "Celkem [Kč]"] and len(rows2) == len(rows) + 1
    row = next(r for r in rows2 if r[2] == priced[2] and r[3] == priced[3])
    assert row[-2] == "100,00" and row[-1] == f"{100 * priced[5]:,.2f}".replace(",", " ").replace(".", ",")
    assert rows2[-1][1] == "Celkem bez DPH" and "bez ceny" in rows2[-1][4]
    assert "Výkaz materiálu s cenami" in reports.NOT_IN_DOC
