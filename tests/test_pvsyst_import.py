"""Import FV modulů (.PAN) a střídačů (.OND) z PVsyst do artiklů (issue #86). Headless, bez Qt.
Testy vznikly PŘED implementací `envocad/library/pvsyst_import.py`. Soubory v tests/data/pvsyst jsou smyšlené."""
import re
from pathlib import Path

import pytest

from envocad.library import components
from envocad.library.pvsyst_import import import_pvsyst, write_components_csv
from envocad.library.store import LibraryStore

DATA = Path(__file__).parent / "data" / "pvsyst"
PAN = DATA / "smysleny_modul.PAN"
OND = DATA / "smysleny_stridac.OND"
ID_RE = re.compile(r"[a-z0-9._+-]+")

PAN_COMMERCIAL = {"Comment": "Test", "Manufacturer": "Solarni Dilna", "Model": "SD-430M",
                  "Width": "1.134", "Height": "1.722", "Depth": "0.030", "Weight": "21.50"}
PAN_BODY = {"Technol": "mtSiMono", "NCelS": "54", "GRef": "1000", "PNom": "430.0", "Isc": "13.900",
            "Voc": "38.80", "Imp": "13.150", "Vmp": "32.70", "muISC": "6.26", "muVocSpec": "-100.9",
            "muPmpReq": "-0.300", "VMaxIEC": "1500"}
OND_COMMERCIAL = {"Manufacturer": "Solarni Dilna", "Model": "SD-10K-T2",
                  "Width": "0.525", "Height": "0.470", "Depth": "0.262", "Weight": "27.00"}
OND_CONV = {"PNomConv": "10.000", "PMaxOUT": "11.000", "VOutConv": "400.0", "VMppMin": "160", "VMPPMax": "950",
            "VAbsMax": "1100", "EfficMax": "98.60", "EfficEuro": "98.10", "MonoTri": "Tri", "PNomDC": "10.200",
            "PMaxDC": "15.000", "IMaxDC": "44.0", "INomAC": "14.5", "IMaxAC": "16.9"}


def _block(d: dict, drop=(), over=None) -> list[str]:
    d = {**d, **(over or {})}
    low = {k.lower() for k in drop}
    return [f"    {k}={v}" for k, v in d.items() if k.lower() not in low]


def pan_text(drop=(), over=None, comm=None, nl="\n") -> str:
    lines = ["PVObject_=pvModule", "  Version=7.2", "  PVObject_Commercial=pvCommercial",
             *[ln for ln in _block({**PAN_COMMERCIAL, **(comm or {})}, drop)],
             "  End of PVObject pvCommercial"]
    lines += [ln[2:] for ln in _block(PAN_BODY, drop, over)]
    lines += ["End of PVObject pvModule", ""]
    return nl.join(lines)


def ond_text(drop=(), over=None, comm=None, top=None) -> str:
    lines = ["PVObject_=pvGInverter", "  Version=7.2", "  PVObject_Commercial=pvCommercial",
             *_block({**OND_COMMERCIAL, **(comm or {})}, drop), "  End of PVObject pvCommercial",
             "  Transfo=Without", "  PVObject_Converter=TConverter",
             *_block(OND_CONV, drop, over), "  End of PVObject TConverter"]
    t = {"NbInputs": "4", "NbMPPT": "2", **(top or {})}
    lines += [f"  {k}={v}" for k, v in t.items() if k.lower() not in {x.lower() for x in drop}]
    lines += ["End of PVObject pvGInverter", ""]
    return "\n".join(lines)


def write(tmp_path, name, text, encoding="utf-8") -> Path:
    p = tmp_path / name
    p.write_bytes(text.encode(encoding))
    return p


# ---- modul (.PAN) ----------------------------------------------------------------------------------------------
def test_pan_sample_file_mapping():
    c, warns = import_pvsyst(PAN)
    assert c.category == "pv_module" and c.symbol_id == "fve.pv_string" and c.source == "user"
    assert c.manufacturer == "Solární Dílna Pribram" and c.part_number == "SD-430M"
    assert c.id == "solarni-dilna-pribram-sd-430m"
    assert c.name == "Solární Dílna Pribram SD-430M" and c.datasheet_url == ""
    assert ID_RE.fullmatch(c.id)
    assert c.num("width_mm") == pytest.approx(1134) and c.num("height_mm") == pytest.approx(1722)
    assert c.num("depth_mm") == pytest.approx(30) and c.num("weight_kg") == pytest.approx(21.5)
    assert c.num("p_wp") == pytest.approx(430) and c.num("voc_v") == pytest.approx(38.8)
    assert c.num("vmp_v") == pytest.approx(32.7) and c.num("isc_a") == pytest.approx(13.9)
    assert c.num("imp_a") == pytest.approx(13.15) and c.num("u_sys_max_v") == pytest.approx(1500)
    assert c.num("beta_voc") == pytest.approx(-0.260, abs=1e-9)
    assert c.num("alpha_isc") == pytest.approx(0.045, abs=1e-9)
    assert c.num("gamma_pmax") == pytest.approx(-0.300)
    assert c.num("noct_c") is None and c.params.get("noct_c", "") == ""
    assert "import PVsyst" in c.params["note"]
    assert warns == []


def test_pan_coefficients_rounded_to_3_decimals(tmp_path):
    p = write(tmp_path, "a.PAN", pan_text(over={"muVocSpec": "-101.23456", "muISC": "6.789012", "muPmpReq": "-0.30123"}))
    c, _ = import_pvsyst(p)
    assert c.num("beta_voc") == pytest.approx(-0.261, abs=1e-9)
    assert c.num("alpha_isc") == pytest.approx(0.049, abs=1e-9)
    assert c.num("gamma_pmax") == pytest.approx(-0.301, abs=1e-9)


@pytest.mark.parametrize("key,target", [("muVocSpec", "beta_voc"), ("muISC", "alpha_isc")])
@pytest.mark.parametrize("mode", ["missing", "zero"])
def test_pan_missing_or_zero_coefficient_warns(tmp_path, key, target, mode):
    text = pan_text(drop=(key,)) if mode == "missing" else pan_text(over={key: "0"})
    c, warns = import_pvsyst(write(tmp_path, "a.PAN", text))
    assert c.num(target) is None
    assert any(target in w or key in w for w in warns)


@pytest.mark.parametrize("key", ["Voc", "Isc"])
def test_pan_missing_required_value_raises(tmp_path, key):
    with pytest.raises(ValueError) as ei:
        import_pvsyst(write(tmp_path, "a.PAN", pan_text(drop=(key,))))
    assert str(ei.value).strip()


def test_missing_model_raises(tmp_path):
    with pytest.raises(ValueError):
        import_pvsyst(write(tmp_path, "a.PAN", pan_text(drop=("Model",))))
    with pytest.raises(ValueError):
        import_pvsyst(write(tmp_path, "b.OND", ond_text(drop=("Model",))))


# ---- střídač (.OND) --------------------------------------------------------------------------------------------
def test_ond_sample_file_mapping():
    c, warns = import_pvsyst(OND)
    assert c.category == "inverter" and c.symbol_id == "fve.inverter" and c.source == "user"
    assert c.manufacturer == "Solární Dílna Příbram" and c.part_number == "SD-10K-T2"
    assert c.name == "Solární Dílna Příbram SD-10K-T2" and ID_RE.fullmatch(c.id) and c.datasheet_url == ""
    assert c.num("width_mm") == pytest.approx(525) and c.num("height_mm") == pytest.approx(470)
    assert c.num("depth_mm") == pytest.approx(262) and c.num("weight_kg") == pytest.approx(27)
    expected = {"p_ac_kw": 10, "mppt": 2, "phases": 3, "un_v": 400, "i_ac_max_a": 16.9,
                "u_dc_max_v": 1100, "u_mppt_min_v": 160, "u_mppt_max_v": 950, "eff_max_pct": 98.6,
                "eff_eu_pct": 98.1}
    for k, v in expected.items():
        assert c.num(k) == pytest.approx(v), k
    # IMaxDC je proud celého střídače, ne jednoho MPPT; NbInputs a PMaxDC se nemapují
    for k in ("i_mppt_max_a", "strings_per_mppt", "isc_mppt_max_a", "p_dc_max_kwp"):
        assert c.num(k) is None, k
    assert "import PVsyst" in c.params["note"] and "IMaxDC" in c.params["note"] and "44" in c.params["note"]
    assert "PMaxDC 15 kW" in c.params["note"] and "NbInputs 4" in c.params["note"]
    assert any("i_mppt_max_a" in w for w in warns)


def test_ond_single_mppt_maps_imaxdc(tmp_path):
    c, warns = import_pvsyst(write(tmp_path, "a.OND", ond_text(top={"NbMPPT": "1"})))
    assert c.num("i_mppt_max_a") == pytest.approx(44.0)
    assert not any("i_mppt_max_a" in w for w in warns)


def test_ond_multi_mppt_does_not_divide(tmp_path):
    c, warns = import_pvsyst(write(tmp_path, "a.OND", ond_text(top={"NbMPPT": "3"})))
    assert c.num("i_mppt_max_a") is None
    assert "IMaxDC" in c.params["note"] and "44" in c.params["note"] and "NbInputs 4" in c.params["note"]
    assert any("i_mppt_max_a" in w for w in warns)


def test_ond_keys_case_insensitive(tmp_path):
    text = ond_text()
    assert "VMPPMax=950" in text and "VMppMin=160" in text
    c, _ = import_pvsyst(write(tmp_path, "a.OND", text.replace("VMPPMax=", "VMppMax=")))
    assert c.num("u_mppt_max_v") == pytest.approx(950)
    c, _ = import_pvsyst(write(tmp_path, "b.OND", text.replace("VMppMin=", "VMPPMIN=")))
    assert c.num("u_mppt_min_v") == pytest.approx(160)


@pytest.mark.parametrize("val,phases", [("Mono", "1"), ("Tri", "3")])
def test_ond_phases(tmp_path, val, phases):
    c, _ = import_pvsyst(write(tmp_path, "a.OND", ond_text(over={"MonoTri": val})))
    assert c.num("phases") == pytest.approx(int(phases))


def test_ond_unknown_phases_warns(tmp_path):
    c, warns = import_pvsyst(write(tmp_path, "a.OND", ond_text(over={"MonoTri": "Split"})))
    assert c.num("phases") is None and any("phases" in w or "MonoTri" in w for w in warns)


def test_ond_missing_phases_warns_with_missing_text(tmp_path):
    c, warns = import_pvsyst(write(tmp_path, "a.OND", ond_text(drop=("MonoTri",))))
    assert c.num("phases") is None
    assert any("chybí MonoTri" in w for w in warns) and not any("„“" in w for w in warns)


def test_missing_manufacturer_warns_but_creates(tmp_path):
    c, warns = import_pvsyst(write(tmp_path, "a.PAN", pan_text(drop=("Manufacturer",))))
    assert c.manufacturer == "" and c.part_number == "SD-430M" and c.id == "sd-430m"
    assert any("Manufacturer" in w for w in warns)


def test_unknown_technology_goes_to_note_without_warning(tmp_path):
    c, warns = import_pvsyst(write(tmp_path, "a.PAN", pan_text(over={"Technol": "mtHIT"})))
    assert "technology" not in c.params and "Technol mtHIT" in c.params["note"]
    assert warns == []


# ---- NaN / inf ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("key,val", [("Voc", "nan"), ("Isc", "inf"), ("Voc", "-inf")])
def test_pan_nonfinite_required_value_raises(tmp_path, key, val):
    with pytest.raises(ValueError):
        import_pvsyst(write(tmp_path, "a.PAN", pan_text(over={key: val})))


def test_ond_nonfinite_values_leave_column_empty_with_warning(tmp_path):
    c, warns = import_pvsyst(write(tmp_path, "a.OND", ond_text(over={"PNomConv": "inf"}, comm={"Width": "1e308"})))
    assert c.num("p_ac_kw") is None and c.num("width_mm") is None
    assert any("PNomConv" in w for w in warns) and any("Width" in w for w in warns)


# ---- id ----------------------------------------------------------------------------------------------------------
def test_id_transliterates_diacritics(tmp_path):
    c, _ = import_pvsyst(write(tmp_path, "a.PAN", pan_text(comm={"Manufacturer": "Solární Dílna"})))
    assert c.id == "solarni-dilna-sd-430m"


def test_id_empty_after_transliteration_raises(tmp_path):
    text = pan_text(comm={"Manufacturer": "", "Model": "太阳能"})
    with pytest.raises(ValueError) as ei:
        import_pvsyst(write(tmp_path, "a.PAN", text))
    assert str(ei.value).strip()


# ---- kódování, formát řádků ------------------------------------------------------------------------------------
@pytest.mark.parametrize("enc", ["cp1252", "utf-8", "utf-8-sig", "utf-16"])
def test_encodings(tmp_path, enc):
    text = pan_text(comm={"Manufacturer": "Solární Dílna Šýr ü ö", "Comment": "Žlutý"})
    c, _ = import_pvsyst(write(tmp_path, "a.PAN", text, enc))
    assert c.manufacturer == "Solární Dílna Šýr ü ö"
    assert "Ã" not in c.manufacturer and "�" not in c.manufacturer


def test_cp1252_sample_has_no_mojibake():
    c, _ = import_pvsyst(PAN)
    assert "Ã" not in c.manufacturer and "�" not in c.manufacturer and "í" in c.manufacturer


def test_crlf_and_spaces_around_equals(tmp_path):
    text = pan_text(nl="\r\n").replace("Voc=38.80", "Voc = 38.80").replace("Vmp=32.70", "Vmp =32.70")
    c, _ = import_pvsyst(write(tmp_path, "a.PAN", text))
    assert c.num("voc_v") == pytest.approx(38.8) and c.num("vmp_v") == pytest.approx(32.7)
    assert c.part_number == "SD-430M"


def test_value_containing_equals(tmp_path):
    c, _ = import_pvsyst(write(tmp_path, "a.PAN", pan_text(comm={"Comment": "a=b"})))
    assert c.num("voc_v") == pytest.approx(38.8)
    c, _ = import_pvsyst(write(tmp_path, "b.PAN", pan_text(comm={"Model": "SD=430"})))
    assert c.part_number == "SD=430"


def test_type_detected_by_content_not_extension(tmp_path):
    c, _ = import_pvsyst(write(tmp_path, "modul.OND", pan_text()))
    assert c.category == "pv_module"
    c, _ = import_pvsyst(write(tmp_path, "stridac.PAN", ond_text()))
    assert c.category == "inverter"


# ---- chybné soubory --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name,data", [
    ("prazdny.PAN", b""),
    ("mezery.PAN", b"  \r\n \r\n"),
    ("smeti.PAN", bytes(range(256)) * 4),
    ("jiny.PAN", b"PVObject_=pvSite\n  Name=x\nEnd of PVObject pvSite\n"),
    ("text.OND", "Toto není soubor PVsyst.\n".encode()),
])
def test_invalid_files_raise_valueerror(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    with pytest.raises(ValueError) as ei:
        import_pvsyst(p)
    assert str(ei.value).strip()


def test_truncated_pan_without_values_raises(tmp_path):
    with pytest.raises(ValueError):
        import_pvsyst(write(tmp_path, "a.PAN", "PVObject_=pvModule\n  Version=7.2\nEnd of PVObject pvModule\n"))


# ---- CSV a round-trip ------------------------------------------------------------------------------------------
def test_write_csv_roundtrip_validates_and_loads(tmp_path):
    comps = [import_pvsyst(PAN)[0], import_pvsyst(OND)[0]]
    out = tmp_path / "pvsyst.csv"
    assert write_components_csv(comps, out) == 2
    assert components.validate(out) == []
    back = components.read_csv(out)
    assert [c.id for c in back] == [c.id for c in comps]
    assert back[0].num("beta_voc") == pytest.approx(-0.260) and back[1].num("u_mppt_max_v") == pytest.approx(950)
    assert back[0].manufacturer == comps[0].manufacturer and back[1].manufacturer == "Solární Dílna Příbram"
    store = LibraryStore(tmp_path / "t.db", load_builtin=False)
    assert store.import_components_csv_v2(out) == 2
    got = store.component(comps[0].id)
    assert got is not None and got.num("p_wp") == pytest.approx(430) and got.category == "pv_module"


def test_write_csv_single_row_roundtrip(tmp_path):
    c, _ = import_pvsyst(PAN)
    out = tmp_path / "m.csv"
    assert write_components_csv([c], out) == 1
    assert components.validate(out) == []
    store = LibraryStore(tmp_path / "t.db", load_builtin=False)
    assert store.import_components_csv_v2(out) == 1


# ---- bez Qt ----------------------------------------------------------------------------------------------------
def test_module_does_not_import_qt():
    import ast

    from envocad.library import pvsyst_import as m
    names = []
    for n in ast.walk(ast.parse(Path(m.__file__).read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            names += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            names.append(n.module or "")
    assert not [x for x in names if x.split(".")[0] in ("PySide6", "shiboken6") or x.startswith("envocad.ui")]
