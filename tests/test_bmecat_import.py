"""Import artiklů z BMEcat (issue #84, 1. krok): parser, zápis CSV, import do knihovny, CLI. Bez Qt.

Testy běží na vlastních smyšlených souborech `tests/data/bmecat/` (žádná data výrobce)."""
import json
import re
from pathlib import Path

import pytest

from envocad.library import bmecat_import as bm
from envocad.library import components
from envocad.library.store import LibraryStore

DATA = Path(__file__).parent / "data" / "bmecat"
XML_12 = DATA / "smysleny_1_2.xml"
XML_2005 = DATA / "smysleny_2005.xml"
ID_RE = re.compile(r"[a-z0-9][a-z0-9._+-]*")

MCB = ("Fiktiv GmbH", "FK-MCB-B16-3")
TERM = ("Smyšlený Elektro s.r.o.", "FK-TERM-4")


@pytest.fixture
def store(tmp_path):
    s = LibraryStore(tmp_path / "lib.db", load_builtin=False)
    yield s
    s.close()


@pytest.fixture(scope="module")
def parsed_12():
    return bm.parse_bmecat(XML_12)


def by_pn(comps):
    return {c.part_number: c for c in comps}


def wrap_12(articles: str, supplier: str = "Fiktiv GmbH") -> str:
    """Minimální BMEcat 1.2 se zadanými `<ARTICLE>` (pro parametrizované a okrajové testy)."""
    sup = f"<SUPPLIER><SUPPLIER_NAME>{supplier}</SUPPLIER_NAME></SUPPLIER>" if supplier else ""
    return ('<?xml version="1.0" encoding="UTF-8"?><BMECAT version="1.2"><HEADER>'
            f"{sup}</HEADER><T_NEW_CATALOG>{articles}</T_NEW_CATALOG></BMECAT>")


def article(aid: str | None = "FK-X-1", name: str | None = "Smyšlený artikl", extra: str = "") -> str:
    a = f"<SUPPLIER_AID>{aid}</SUPPLIER_AID>" if aid else ""
    d = f"<DESCRIPTION_SHORT>{name}</DESCRIPTION_SHORT>" if name else ""
    return f"<ARTICLE>{a}<ARTICLE_DETAILS>{d}</ARTICLE_DETAILS>{extra}</ARTICLE>"


def features(*items: tuple[str, str, str | None]) -> str:
    out = "<ARTICLE_FEATURES>"
    for fname, val, unit in items:
        u = f"<FUNIT>{unit}</FUNIT>" if unit else ""
        out += f"<FEATURE><FNAME>{fname}</FNAME><FVALUE>{val}</FVALUE>{u}</FEATURE>"
    return out + "</ARTICLE_FEATURES>"


def write(tmp_path, text: str, name: str = "k.xml") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ---- parse_bmecat: BMEcat 1.2 ----------------------------------------------------------------------------------
def test_parse_12_with_doctype_returns_valid_articles(parsed_12):
    comps, warns = parsed_12
    assert sorted(c.part_number for c in comps) == ["FK-LOCALDS-9", "FK-MCB-B16-3", "FK-NONAME-7", "FK-TERM-4",
                                                    "FK-WEIRD-1"]
    assert warns and all(isinstance(w, str) for w in warns)


def test_parse_12_common_fields(parsed_12):
    comps, _ = parsed_12
    for c in comps:
        assert isinstance(c, components.Component)
        assert c.source == "user"
        assert c.category in components.CATEGORIES
        assert ID_RE.fullmatch(c.id), c.id
        assert "import BMEcat – ověřit" in c.params["note"]
    assert len({c.id for c in comps}) == len(comps)


def test_parse_12_full_article(parsed_12):
    c = by_pn(parsed_12[0])["FK-MCB-B16-3"]
    assert (c.manufacturer, c.name) == ("Fiktiv GmbH", "Jistič 3P B16 smyšlený")
    assert c.params["gtin"] == "4000000000017"
    assert c.datasheet_url == "https://example.com/ds/fk-mcb-b16-3.pdf"
    assert c.category == "mcb"
    assert "fk-mcb-b16-3" in c.id and c.id.startswith("fiktiv")


def test_parse_12_udx_dimensions_in_mm_without_float_noise(parsed_12):
    p = by_pn(parsed_12[0])["FK-MCB-B16-3"].params
    # UDX.EDXF.* jsou v metrech; má přednost před FEATURE „Šířka 99 mm“
    assert (p["width_mm"], p["height_mm"], p["depth_mm"], p["weight_kg"]) == ("52.5", "85", "69.5", "0.35")


def test_parse_12_etim_class_version_and_features(parsed_12):
    p = by_pn(parsed_12[0])["FK-MCB-B16-3"].params
    assert p["etim_class"] == "EC000042"
    assert p["etim_version"] == "9.0"
    assert json.loads(p["etim_features"]) == [{"f": "EF000001", "v": ["16"], "u": "A"},
                                              {"f": "EF000002", "v": ["B", "C"]}]
    for k in ("in_", "p_loss_w", "poles", "un_v"):   # žádné mapování ETIM → parametry knihovny
        assert k not in p


def test_parse_12_dimensions_from_features_with_units(parsed_12):
    c = by_pn(parsed_12[0])["FK-TERM-4"]
    assert (c.params["width_mm"], c.params["height_mm"], c.params["weight_kg"]) == ("6.2", "50", "0.012")
    assert "etim_class" not in c.params


def test_parse_12_manufacturer_from_article_and_pn_from_manufacturer_aid(parsed_12):
    c = by_pn(parsed_12[0])["FK-TERM-4"]
    assert c.manufacturer == "Smyšlený Elektro s.r.o."          # ne hlavička „Fiktiv GmbH“
    assert "INT-0004" not in (c.part_number, c.id)               # MANUFACTURER_AID má přednost před SUPPLIER_AID
    assert c.id.isascii() and c.id.startswith("smyslen")         # bez diakritiky, malá písmena
    assert c.category == "terminal"


def test_parse_12_manufacturer_falls_back_to_header_supplier(parsed_12):
    c = by_pn(parsed_12[0])["FK-WEIRD-1"]
    assert c.manufacturer == "Fiktiv GmbH"


def test_parse_12_unknown_unit_ignored_with_warning(parsed_12):
    comps, warns = parsed_12
    p = by_pn(comps)["FK-WEIRD-1"].params
    assert "width_mm" not in p
    assert p["depth_mm"] == "10"
    assert any("FK-WEIRD-1" in w and "furlong" in w for w in warns)


def test_parse_12_missing_part_number_skipped_with_warning(parsed_12):
    comps, warns = parsed_12
    assert not any(c.params.get("gtin") == "4000000000048" for c in comps)
    assert any("objednac" in w.lower() for w in warns)


def test_parse_12_missing_name_uses_part_number_with_warning(parsed_12):
    comps, warns = parsed_12
    c = by_pn(comps)["FK-NONAME-7"]
    assert c.name == "FK-NONAME-7"
    assert any("FK-NONAME-7" in w and "název" in w.lower() for w in warns)


def test_parse_12_duplicate_in_file_keeps_first_only(parsed_12):
    comps, warns = parsed_12
    assert sum(1 for c in comps if c.part_number.strip().lower() == "fk-mcb-b16-3") == 1
    assert not any("Duplicitní jistič" in c.name for c in comps)
    assert any("FK-MCB-B16-3" in w.upper() and "duplic" in w.lower() for w in warns)


def test_parse_12_non_http_datasheet_ignored_with_warning(parsed_12):
    comps, warns = parsed_12
    assert by_pn(comps)["FK-LOCALDS-9"].datasheet_url == ""
    assert any("FK-LOCALDS-9" in w for w in warns)


def test_parse_is_deterministic():
    a, _ = bm.parse_bmecat(XML_12)
    b, _ = bm.parse_bmecat(str(XML_12))     # i řetězcová cesta
    assert [(c.id, c.params) for c in a] == [(c.id, c.params) for c in b]


# ---- parse_bmecat: BMEcat 2005 ---------------------------------------------------------------------------------
def test_parse_2005_namespace_products():
    comps, warns = bm.parse_bmecat(XML_2005)
    d = by_pn(comps)
    assert sorted(d) == ["FK-CASE-2", "FK-RCD-40-30"]
    assert not any(c.params.get("note") is None for c in comps)
    rcd = d["FK-RCD-40-30"]
    assert rcd.manufacturer == "Fiktiv GmbH"
    assert rcd.params["gtin"] == "04000000000079"
    assert rcd.params["etim_class"] == "EC001234" and rcd.params["etim_version"] == "8.0"
    assert json.loads(rcd.params["etim_features"]) == [{"f": "EF000003", "v": ["30"], "u": "mA"}]
    assert rcd.datasheet_url == "https://example.com/ds/fk-rcd-40-30.pdf"
    assert rcd.category in ("rcd", "rcbo")
    assert isinstance(warns, list)


def test_parse_2005_ean_pid_and_un_ece_units():
    case = by_pn(bm.parse_bmecat(XML_2005)[0])["FK-CASE-2"]
    assert case.manufacturer == "Fiktiv GmbH"                 # z hlavičky
    assert case.params["gtin"] == "4000000000086"
    assert (case.params["width_mm"], case.params["height_mm"], case.params["weight_kg"]) == ("45", "90", "0.25")


# ---- jednotky a názvy vlastností (parametrizovaně) -------------------------------------------------------------
@pytest.mark.parametrize("fname, val, unit, key, expected", [
    ("Breite", "12", "mm", "width_mm", "12"),
    ("Width", "1.2", "cm", "width_mm", "12"),
    ("Šířka", "0.0175", "m", "width_mm", "17.5"),
    ("Höhe", "0.09", "MTR", "height_mm", "90"),
    ("Výška", "9", "CMT", "height_mm", "90"),
    ("Height", "85", "MMT", "height_mm", "85"),
    ("Tiefe", "4", "cm", "depth_mm", "40"),
    ("Hloubka", "7.5", "mm", "depth_mm", "7.5"),
    ("Depth", "0.05", "m", "depth_mm", "50"),
    ("Gewicht", "250", "g", "weight_kg", "0.25"),
    ("Hmotnost", "1.5", "kg", "weight_kg", "1.5"),
    ("Weight", "120", "GRM", "weight_kg", "0.12"),
    ("Weight", "2", "KGM", "weight_kg", "2"),
])
def test_feature_dimension_units(tmp_path, fname, val, unit, key, expected):
    comps, warns = bm.parse_bmecat(write(tmp_path, wrap_12(article(extra=features((fname, val, unit))))))
    assert comps[0].params[key] == expected
    assert not any("jednotk" in w.lower() for w in warns)


@pytest.mark.parametrize("fname, unit, key", [
    ("Breite", "inch", "width_mm"),
    ("Höhe", "ft", "height_mm"),
    ("Tiefe", "yd", "depth_mm"),
    ("Gewicht", "lb", "weight_kg"),
    ("Weight", "g/cm3", "weight_kg"),
])
def test_feature_unknown_unit_dropped_with_warning(tmp_path, fname, unit, key):
    comps, warns = bm.parse_bmecat(write(tmp_path, wrap_12(article("FK-U-1", extra=features((fname, "5", unit))))))
    assert key not in comps[0].params
    assert any("FK-U-1" in w and unit in w for w in warns)


def test_t_update_products_transaction_is_read(tmp_path):
    text = wrap_12(article()).replace("T_NEW_CATALOG", "T_UPDATE_PRODUCTS")
    comps, _ = bm.parse_bmecat(write(tmp_path, text))
    assert [c.part_number for c in comps] == ["FK-X-1"]


# ---- chybějící povinná pole ------------------------------------------------------------------------------------
def test_missing_manufacturer_everywhere_skipped_with_warning(tmp_path):
    comps, warns = bm.parse_bmecat(write(tmp_path, wrap_12(article("FK-NOMAN-1"), supplier="")))
    assert comps == []
    assert any("FK-NOMAN-1" in w and "výrobc" in w.lower() for w in warns)


def test_id_is_ascii_lowercase_for_odd_characters(tmp_path):
    text = wrap_12(article("ŘÍZENÍ/ABC 12", "Název"), supplier="Příliš Žluťoučký Kůň s.r.o.")
    c = bm.parse_bmecat(write(tmp_path, text))[0][0]
    assert ID_RE.fullmatch(c.id) and c.id.isascii() and c.id == c.id.lower()


# ---- bezpečnost a chyby ----------------------------------------------------------------------------------------
def test_invalid_xml_raises_valueerror(tmp_path):
    with pytest.raises(ValueError) as ei:
        bm.parse_bmecat(write(tmp_path, "<BMECAT><ARTICLE>"))
    assert str(ei.value)


def test_not_bmecat_raises_valueerror(tmp_path):
    with pytest.raises(ValueError):
        bm.parse_bmecat(write(tmp_path, '<?xml version="1.0"?><parts><part P_ARTICLE_PARTNR="1"/></parts>'))


def test_external_entity_is_rejected_and_never_read(tmp_path):
    secret = tmp_path / "tajne.txt"
    secret.write_text("TAJNY-OBSAH-12345", encoding="utf-8")
    text = (f'<?xml version="1.0"?><!DOCTYPE BMECAT [<!ENTITY xxe SYSTEM "{secret.as_uri()}">]>'
            + wrap_12(article("FK-XXE-1", "&xxe;")).split("?>", 1)[1])
    with pytest.raises(ValueError) as ei:
        bm.parse_bmecat(write(tmp_path, text))
    assert "TAJNY-OBSAH" not in str(ei.value)


def test_internal_entity_declaration_is_rejected(tmp_path):
    text = ('<?xml version="1.0"?><!DOCTYPE BMECAT [<!ENTITY x "abc">]>'
            + wrap_12(article("FK-ENT-1", "&x;")).split("?>", 1)[1])
    with pytest.raises(ValueError):
        bm.parse_bmecat(write(tmp_path, text))


def test_billion_laughs_is_rejected(tmp_path):
    ents = '<!ENTITY a "lol">' + "".join(
        f'<!ENTITY {chr(98 + i)} "{"&" + chr(97 + i) + ";"}{"&" + chr(97 + i) + ";"}{"&" + chr(97 + i) + ";"}">'
        for i in range(8))
    text = (f'<?xml version="1.0"?><!DOCTYPE BMECAT [{ents}]>'
            + wrap_12(article("FK-LOL-1", "&i;")).split("?>", 1)[1])
    with pytest.raises(ValueError):
        bm.parse_bmecat(write(tmp_path, text))


def test_does_not_fetch_dtd(tmp_path):
    """DOCTYPE SYSTEM s nedostupnou DTD (běžné u 1.2) se načte bez pokusu o stažení."""
    text = ('<?xml version="1.0"?><!DOCTYPE BMECAT SYSTEM "http://127.0.0.1:9/bmecat_new_catalog_1_2.dtd">'
            + wrap_12(article()).split("?>", 1)[1])
    comps, _ = bm.parse_bmecat(write(tmp_path, text))
    assert len(comps) == 1


# ---- write_components_csv ------------------------------------------------------------------------------------
def test_write_components_csv_is_valid_v2(tmp_path, parsed_12):
    comps = parsed_12[0]
    out = tmp_path / "o.csv"
    assert bm.write_components_csv(comps, out) == len(comps)
    assert components.validate(out) == []
    back = {c.id: c for c in components.read_csv(out)}
    src = by_pn(comps)["FK-MCB-B16-3"]
    assert back[src.id].params["etim_class"] == "EC000042"
    assert back[src.id].params["width_mm"] == "52.5"
    assert back[src.id].datasheet_url == src.datasheet_url
    assert out.read_text(encoding="utf-8-sig").splitlines()[0].count(";") >= 7


# ---- import_bmecat -------------------------------------------------------------------------------------------
def test_import_into_empty_library(store, tmp_path):
    out_dir = tmp_path / "nova" / "slozka"
    r = bm.import_bmecat(store, XML_12, out_dir)
    assert r.imported == 5 and r.skipped == 0
    assert r.csv_path == out_dir / "smysleny_1_2.csv" and r.csv_path.exists()
    assert components.validate(r.csv_path) == []
    assert any("furlong" in w for w in r.warnings)          # varování parseru se přenesou
    assert len(store.components()) == 5
    mcb = next(c for c in store.components() if c.part_number == "FK-MCB-B16-3")
    assert mcb.params["gtin"] == "4000000000017"
    assert mcb.params["etim_class"] == "EC000042"
    assert mcb.params["weight_kg"] == "0.35"
    assert mcb.datasheet_url == "https://example.com/ds/fk-mcb-b16-3.pdf"
    assert store.component(mcb.id).id == mcb.id


def test_reimport_updates_same_ids_without_new_rows(store, tmp_path):
    first = bm.import_bmecat(store, XML_12, tmp_path / "o")
    ids = sorted(c.id for c in store.components())
    second = bm.import_bmecat(store, XML_12, tmp_path / "o")
    assert second.imported == first.imported == 5 and second.skipped == 0
    assert sorted(c.id for c in store.components()) == ids


def test_import_skips_article_already_in_library_under_other_id(store, tmp_path):
    store.put_component("rucne.fk-mcb", "Fiktiv GmbH", "FK-MCB-B16-3", "Ruční jistič", None, {"category": "mcb"})
    r = bm.import_bmecat(store, XML_12, tmp_path / "o")
    assert r.skipped == 1 and r.imported == 4
    assert any("FK-MCB-B16-3" in w for w in r.warnings)
    mine = store.component("rucne.fk-mcb")
    assert mine.name == "Ruční jistič" and "gtin" not in mine.params     # stávající beze změny
    same = [c for c in store.components() if c.part_number == "FK-MCB-B16-3"]
    assert [c.id for c in same] == ["rucne.fk-mcb"]
    assert "FK-MCB-B16-3" not in {c.part_number for c in components.read_csv(r.csv_path)}   # ani do CSV


def test_import_matches_existing_ignoring_case_and_spaces(store, tmp_path):
    store.put_component("x.1", " FIKTIV GmbH ", "fk-mcb-b16-3 ", "Ruční", None, {})
    r = bm.import_bmecat(store, XML_12, tmp_path / "o")
    assert r.skipped == 1


def test_import_2005(store, tmp_path):
    r = bm.import_bmecat(store, XML_2005, tmp_path / "o")
    assert r.imported == 2 and r.skipped == 0
    assert components.validate(r.csv_path) == []


def test_import_nothing_to_write_has_no_csv(store, tmp_path):
    p = write(tmp_path, wrap_12(article(None)))
    r = bm.import_bmecat(store, p, tmp_path / "o")
    assert r.imported == 0 and r.csv_path is None and r.warnings
    assert store.components() == []


def test_import_invalid_xml_raises_and_keeps_library(store, tmp_path):
    with pytest.raises(ValueError):
        bm.import_bmecat(store, write(tmp_path, "<BMECAT>"), tmp_path / "o")
    assert store.components() == []


# ---- CLI -----------------------------------------------------------------------------------------------------
def test_cli_dump(capsys):
    assert bm.main([str(XML_12), "--dump"]) == 0
    out = capsys.readouterr().out
    assert "FK-MCB-B16-3" in out and "FK-TERM-4" in out


def test_cli_writes_csv(tmp_path, capsys):
    out = tmp_path / "vystup.csv"
    assert bm.main([str(XML_2005), "-o", str(out)]) == 0
    assert out.exists() and components.validate(out) == []
    assert len(components.read_csv(out)) == 2


def test_cli_dump_does_not_write_file(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bm.main([str(XML_2005), "--dump"])
    assert list(tmp_path.glob("*.csv")) == []


# ---- regrese z review (#84) ----------------------------------------------------------------------------------
def import_one(store, tmp_path, aid="LX F6.6-H", name="Smyšlený měnič", mfr="GoodWe", extra="", out="o"):
    xml = write(tmp_path, wrap_12(article(aid, name, extra), supplier=mfr), "one.xml")
    return bm.import_bmecat(store, xml, tmp_path / out)


def test_import_never_overwrites_foreign_article_with_same_id_and_key(store, tmp_path):
    store.put_component("goodwe-lx-f6.6-h", "GoodWe", "LX F6.6-H", "Ruční", "sym.x",
                        {"e_kwh": "6.6", "category": "battery"}, 12345.0)
    before = store.get_component("goodwe-lx-f6.6-h")
    r = import_one(store, tmp_path)
    assert r.skipped == 1 and r.imported == 0
    assert any("goodwe-lx-f6.6-h" in w for w in r.warnings)
    assert store.get_component("goodwe-lx-f6.6-h") == before
    assert len(store.components()) == 1


def test_import_same_id_different_key_gets_suffix_and_is_stable(store, tmp_path):
    store.put_component("fiktiv-gmbh-abc-1", "Fiktiv GmbH", "ABC 1", "Ruční", None, {"e_kwh": "1"}, 5.0)
    before = store.get_component("fiktiv-gmbh-abc-1")
    r = import_one(store, tmp_path, aid="ABC-1", mfr="Fiktiv GmbH")
    assert r.imported == 1 and r.skipped == 0
    assert store.get_component("fiktiv-gmbh-abc-1") == before
    assert store.get_component("fiktiv-gmbh-abc-1-2")["part_number"] == "ABC-1"
    r2 = import_one(store, tmp_path, aid="ABC-1", mfr="Fiktiv GmbH")
    assert r2.imported == 1 and r2.skipped == 0
    assert len(store.components()) == 2


def test_reimport_keeps_user_assigned_symbol_and_price(store, tmp_path):
    import_one(store, tmp_path, aid="FK-1", mfr="Fiktiv GmbH")
    cid = store.components()[0].id
    old = store.get_component(cid)
    params = {**old["params"], "footprint_id": "fp.x"}
    store.put_component(cid, "Fiktiv GmbH", "FK-1", old["name"], "sym.moje", params, 999.5, old["url"])
    r = import_one(store, tmp_path, aid="FK-1", name="Nový název", mfr="Fiktiv GmbH")
    assert r.imported == 1 and r.skipped == 0
    c = store.component(cid)
    assert c.symbol_id == "sym.moje" and c.price == 999.5 and c.footprint_id == "fp.x"
    assert c.name == "Nový název" and len(store.components()) == 1


def test_reimport_updates_under_existing_id_not_recomputed(store, tmp_path):
    store.put_component("stare-id", "Fiktiv GmbH", "FK-2", "Dříve", None, {"note": bm.NOTE})
    import_one(store, tmp_path, aid="FK-2", mfr="Fiktiv GmbH")
    assert [c.id for c in store.components()] == ["stare-id"]


@pytest.mark.parametrize("val", ["1E+999999", "1.5e400", "1,234.5", "abc", "-5", "1E-999999"])
def test_unreadable_or_implausible_dimension_dropped_with_warning(tmp_path, val):
    ext = f"<USER_DEFINED_EXTENSIONS><UDX.EDXF.NETWIDTH>{val}</UDX.EDXF.NETWIDTH></USER_DEFINED_EXTENSIONS>"
    comps, warns = bm.parse_bmecat(write(tmp_path, wrap_12(article("FK-OV", extra=ext))))
    assert "width_mm" not in comps[0].params
    assert any("FK-OV" in w and val[:40] in w for w in warns)


def test_overflow_in_feature_value_does_not_escape(tmp_path):
    comps, warns = bm.parse_bmecat(write(tmp_path, wrap_12(
        article("FK-OV2", extra=features(("Breite", "1E+999999", "mm"), ("Höhe", "5000000", "m"))))))
    assert not {"width_mm", "height_mm"} & set(comps[0].params)
    assert len([w for w in warns if w.startswith("Artikl FK-OV2")]) == 2


def test_long_bad_value_is_truncated_in_warning(tmp_path):
    ext = f"<USER_DEFINED_EXTENSIONS><UDX.EDXF.NETWEIGHT>{'9' * 500}</UDX.EDXF.NETWEIGHT></USER_DEFINED_EXTENSIONS>"
    _, warns = bm.parse_bmecat(write(tmp_path, wrap_12(article("FK-LONG", extra=ext))))
    assert warns and max(len(w) for w in warns) < 250


@pytest.mark.parametrize("val", ["", "0"])
def test_empty_or_zero_dimension_dropped_silently(tmp_path, val):
    ext = f"<USER_DEFINED_EXTENSIONS><UDX.EDXF.NETWIDTH>{val}</UDX.EDXF.NETWIDTH></USER_DEFINED_EXTENSIONS>"
    comps, warns = bm.parse_bmecat(write(tmp_path, wrap_12(article("FK-Z", extra=ext))))
    assert "width_mm" not in comps[0].params
    assert not [w for w in warns if w.startswith("Artikl FK-Z")]


def test_non_latin_ids_get_hash_fallback_and_imported_matches_rows(store, tmp_path):
    xml = write(tmp_path, wrap_12(article("日本") + article("語", "Jiný"), supplier="日本"), "jp.xml")
    comps, _ = bm.parse_bmecat(xml)
    assert all(re.fullmatch(r"bmecat-[0-9a-f]{10}", c.id) for c in comps)
    assert comps[0].id != comps[1].id
    assert [c.id for c in bm.parse_bmecat(xml)[0]] == [c.id for c in comps]
    r = bm.import_bmecat(store, xml, tmp_path / "o")
    assert r.imported == 2 == len(store.components())


def test_defused_errors_have_czech_message(tmp_path):
    ent = ('<?xml version="1.0"?><!DOCTYPE BMECAT [<!ENTITY x "abc">]>'
           + wrap_12(article("FK-E", "&x;")).split("?>", 1)[1])
    xxe = ('<?xml version="1.0"?><!DOCTYPE BMECAT [<!ENTITY x SYSTEM "file:///etc/hostname">]>'
           + wrap_12(article("FK-E", "&x;")).split("?>", 1)[1])
    for text in (ent, xxe):
        with pytest.raises(ValueError, match="nepovolenou konstrukci XML"):
            bm.parse_bmecat(write(tmp_path, text))


def test_fallback_warnings_are_summarized_once(tmp_path):
    arts = "".join(f"<ARTICLE><SUPPLIER_AID>FK-{i}</SUPPLIER_AID><ARTICLE_DETAILS>"
                   f"<DESCRIPTION_SHORT>N{i}</DESCRIPTION_SHORT></ARTICLE_DETAILS></ARTICLE>" for i in range(3))
    comps, warns = bm.parse_bmecat(write(tmp_path, wrap_12(arts, supplier="Velkoobchod s.r.o.")))
    assert len(comps) == 3
    mfr = [w for w in warns if "MANUFACTURER_NAME" in w]
    pn = [w for w in warns if "objednací číslo výrobce" in w]
    assert len(mfr) == 1 and "U 3 artiklů" in mfr[0] and "Velkoobchod s.r.o." in mfr[0]
    assert len(pn) == 1 and "U 3 artiklů" in pn[0]


def test_no_fallback_warning_when_manufacturer_fields_present(tmp_path):
    art = ("<ARTICLE><SUPPLIER_AID>S-1</SUPPLIER_AID><ARTICLE_DETAILS><DESCRIPTION_SHORT>N</DESCRIPTION_SHORT>"
           "<MANUFACTURER_AID>M-1</MANUFACTURER_AID><MANUFACTURER_NAME>Fiktiv</MANUFACTURER_NAME>"
           "</ARTICLE_DETAILS></ARTICLE>")
    comps, warns = bm.parse_bmecat(write(tmp_path, wrap_12(art)))
    assert comps[0].part_number == "M-1" and warns == []


def test_large_file_parses_all_articles(tmp_path):
    arts = "".join(article(f"FK-{i}", f"Artikl {i}") for i in range(2000))
    comps, _ = bm.parse_bmecat(write(tmp_path, wrap_12(arts)))
    assert len(comps) == 2000


@pytest.mark.parametrize("url", ['https://x.cz/a"onclick=1', "https://x.cz/<b>", "https://x.cz/a'b", "https://x.cz/>"])
def test_datasheet_url_with_html_chars_rejected_with_warning(tmp_path, url):
    mime = ("<MIME_INFO><MIME><MIME_TYPE>application/pdf</MIME_TYPE><MIME_SOURCE>"
            f"{url.replace('<', '&lt;').replace('>', '&gt;')}</MIME_SOURCE><MIME_PURPOSE>data_sheet</MIME_PURPOSE>"
            "</MIME></MIME_INFO>")
    comps, warns = bm.parse_bmecat(write(tmp_path, wrap_12(article("FK-U", extra=mime))))
    assert comps[0].datasheet_url == ""
    assert any("FK-U" in w and "datasheet" in w for w in warns)


def test_multiple_etim_groups_first_used_with_warning(tmp_path):
    def grp(cls):
        return ("<ARTICLE_FEATURES><REFERENCE_FEATURE_SYSTEM_NAME>ETIM-8.0</REFERENCE_FEATURE_SYSTEM_NAME>"
                f"<REFERENCE_FEATURE_GROUP_ID>{cls}</REFERENCE_FEATURE_GROUP_ID></ARTICLE_FEATURES>")
    comps, warns = bm.parse_bmecat(write(tmp_path, wrap_12(article("FK-ET", extra=grp("EC1") + grp("EC2")))))
    assert comps[0].params["etim_class"] == "EC1"
    assert any("FK-ET" in w and "ETIM" in w for w in warns)
