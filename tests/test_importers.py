"""Importéry knihovny na realistických vstupech: EPLAN (CSV, XML, EDZ/ZIP), QET (složka, CLI), DXF (CLI), artikly CSV."""
import json
import zipfile

import ezdxf
import pytest

from envocad.library import components, dxf_import, eplan_import, qet_import
from envocad.model.symbol import Symbol

ELMT = """<definition version="0.100.0" type="element" width="30" height="60" hotspot_x="15" hotspot_y="30">
<names><name lang="cs">{name}</name><name lang="en">{name}</name></names>
<kindInformations><kindInformation name="type">protection</kindInformation></kindInformations>
<description>
<line x1="0" y1="-30" x2="0" y2="30" style="" antialias="false"/>
<terminal x="0" y="-30" orientation="n" name="1"/>
<terminal x="0" y="30" orientation="s" name="2"/>
</description></definition>"""


def _dxf(path, size=10.0):
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (size, 0), (size, size * 4), (0, size * 4)], close=True)
    msp.add_circle((size / 2, size), 2)
    msp.add_arc((size / 2, size * 2), 3, 0, 180)
    msp.add_text("Q1", dxfattribs={"height": 2.5}).set_placement((1, 1))
    doc.saveas(path)


# ---- EPLAN --------------------------------------------------------------------------------------------
def test_eplan_commercial_csv_semicolon_and_comma(tmp_path):
    rows_txt = [
        ["Part number", "Manufacturer", "Description", "Product group", "Width", "Rated current", "Price"],
        ["5SL6116-7", "Siemens", "Jistič 1P B16", "Miniature circuit breaker", "17,5 mm", "16 A", "1 234,50 Kč"],
        ["5SV3344-6", "Siemens", "Chránič 4P 40A 30mA", "Residual current device", "70", "40", ""],
        ["", "Bez čísla", "řádek bez čísla se přeskočí", "", "", "", ""],
    ]
    for delim in (";", ","):
        src = tmp_path / f"c{ord(delim)}.csv"
        src.write_text("﻿" + "\n".join(delim.join(f'"{c}"' for c in r) for r in rows_txt), encoding="utf-8")
        rows, mapping = eplan_import.rows_from_commercial_csv(src)
        assert mapping["part_number"] == "Part number" and mapping["width_mm"] == "Width"
        assert [r["part_number"] for r in rows] == ["5SL6116-7", "5SV3344-6"]
        mcb, rcd = rows
        assert (mcb["category"], mcb["modules"], mcb["in_"], mcb["width_mm"]) == ("mcb", "1", "16", "17.5")
        assert (rcd["category"], rcd["modules"]) == ("rcd", "4")
        assert mcb["id"] == "siemens-5sl6116-7"
        assert mcb["price_czk"] == "1234.50"             # mezera jako oddělovač tisíců
        out = tmp_path / f"out{ord(delim)}.csv"
        assert eplan_import.write_components_csv(rows, out) == 2
        assert components.validate(out) == []          # výstup projde validací knihovny artiklů
        assert [c.id for c in components.read_csv(out)] == [r["id"] for r in rows]


def test_eplan_parts_xml_and_edz(tmp_path, capsys):
    xml = """<?xml version="1.0" encoding="utf-8"?>
<EplanPxfRoot><O76 P_ARTICLE_PARTNR="ABB.S201-B16" P_ARTICLE_MANUFACTURER="ABB" P_ARTICLE_DESCR1="Jistič S201 B16"
 P_ARTICLE_PRODUCTGROUP="Leitungsschutzschalter" P_ARTICLE_WIDTH="17.5" P_ARTICLE_MACRO="ABB.S201.ema"/>
<O76 P_ARTICLE_PARTNR="ABB.OVR-T2" P_ARTICLE_MANUFACTURER="ABB" P_ARTICLE_DESCR1="Svodič přepětí"
 P_ARTICLE_PRODUCTGROUP="Überspannungsschutz" P_ARTICLE_WIDTH="36"/><Other x="1"/></EplanPxfRoot>"""
    (tmp_path / "parts.xml").write_text(xml, encoding="utf-8")
    rows, _ = eplan_import.rows_from_parts_xml(tmp_path / "parts.xml")
    assert [(r["category"], r.get("modules")) for r in rows] == [("mcb", "1"), ("spd", "2")]
    assert "makro ABB.S201.ema" in rows[0]["note"]
    # EDZ: XML artiklů + DXF pohledy, i ve stejně pojmenovaných podsložkách
    _dxf(tmp_path / "a.dxf")
    edz = tmp_path / "balik.edz"
    with zipfile.ZipFile(edz, "w") as z:
        z.write(tmp_path / "parts.xml", "items/parts.xml")
        z.write(tmp_path / "a.dxf", "dxf/S201 front.dxf")
        z.writestr("dxf/broken.dxf", "tohle není DXF")
    fp, out = tmp_path / "fp", tmp_path / "edz.csv"
    assert eplan_import.main([str(edz), "--footprints", str(fp), "-o", str(out)]) == 0
    written = sorted(p.name for p in fp.glob("*.json"))
    assert written == ["fp.eplan.s201-front.json"]               # rozbitý DXF se přeskočí, nespadne
    assert not list(fp.glob("*.dxf")) and not list(fp.glob("*.xml"))   # dočasné soubory uklizené
    sym = Symbol.from_dict(json.loads((fp / written[0]).read_text(encoding="utf-8")))
    assert sym.primitives and sym.category == "Rozložení/EPLAN"
    assert len(components.read_csv(out)) == 2
    assert "přeskočeno" in capsys.readouterr().err


def test_eplan_cli_dump(tmp_path, capsys):
    src = tmp_path / "c.csv"
    src.write_text("Order number;Hersteller;Bezeichnung\nX-1;Hager;Stykač 25A\n", encoding="utf-8")
    assert eplan_import.main([str(src), "--dump"]) == 0
    out = capsys.readouterr().out
    assert "part_number" in out and "Order number" in out and "Načteno 1" in out


def test_eplan_zip_requires_footprints(tmp_path):
    z = tmp_path / "x.zip"
    zipfile.ZipFile(z, "w").close()
    with pytest.raises(SystemExit):
        eplan_import.main([str(z)])


# ---- QET ----------------------------------------------------------------------------------------------
def test_qet_import_dir_tree(tmp_path, capsys):
    src = tmp_path / "elements"
    (src / "10_electric" / "20_protection" / "11_circuit_breakers").mkdir(parents=True)
    (src / "10_electric" / "30_measuring").mkdir(parents=True)
    (src / "10_electric" / "20_protection" / "11_circuit_breakers" / "disj.elmt").write_text(
        ELMT.format(name="Jistič"), encoding="utf-8")
    (src / "10_electric" / "30_measuring" / "volt.elmt").write_text(ELMT.format(name="Voltmetr"), encoding="utf-8")
    (src / "10_electric" / "bad.elmt").write_text("<definition", encoding="utf-8")
    out = tmp_path / "out"
    assert qet_import.main(["--dir", str(src), "--prefix", "qet.ap", "-o", str(out)]) == 0
    syms = {p.stem: Symbol.from_dict(json.loads(p.read_text(encoding="utf-8"))) for p in out.glob("*.json")}
    # id z relativní cesty (na Windows i Linuxu stejné), kategorie podle druhu ve stromu
    assert set(syms) == {"qet.ap.10-electric-20-protection-11-circuit-breakers-disj",
                         "qet.ap.10-electric-30-measuring-volt"}
    cats = {s.name: s.category for s in syms.values()}
    assert cats == {"Jistič": "Jištění/QET", "Voltmetr": "Měření/QET"}
    assert all(s.validate() == [] for s in syms.values())
    assert "přeskočeno" in capsys.readouterr().err
    # limit
    assert len(qet_import.import_dir(src, "qet.x", "QET", tmp_path / "lim", limit=1)) == 1


def test_qet_cli_single_and_errors(tmp_path):
    f = tmp_path / "one.elmt"
    f.write_text(ELMT.format(name="Pojistka"), encoding="utf-8")
    out = tmp_path / "one.json"
    assert qet_import.main([str(f), "-o", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["id"] == "qet.one"
    with pytest.raises(SystemExit):
        qet_import.main(["-o", str(out)])


def test_qet_kind_rules():
    assert qet_import.kind_for_path("electric/protection/fuses") == "Jištění"
    assert qet_import.kind_for_path("něco úplně jiného") == "Ostatní"
    assert qet_import.slug("Ž!!") == "x"


# ---- DXF ----------------------------------------------------------------------------------------------
def test_dxf_cli_blocks_and_scale(tmp_path, capsys):
    src = tmp_path / "v.dxf"
    _dxf(src)
    doc = ezdxf.readfile(src)
    doc.blocks.new("DEV").add_line((0, 0), (5, 0))
    doc.saveas(src)
    dxf_import.main([str(src), "--list-blocks"])
    assert "DEV" in capsys.readouterr().out.split()
    out = tmp_path / "v.json"
    dxf_import.main([str(src), "--id", "fp.v", "--name", "V", "--scale", "2", "--snap", "-o", str(out)])
    sym = Symbol.from_dict(json.loads(out.read_text(encoding="utf-8")))
    assert {p["type"] for p in sym.primitives} >= {"polyline", "circle", "arc", "text"}
    circ = next(p for p in sym.primitives if p["type"] == "circle")
    assert circ["r"] == pytest.approx(4.0)                 # měřítko 2×
    with pytest.raises(SystemExit):
        dxf_import.main([str(src)])                         # chybí --id/--name


# ---- artikly CSV --------------------------------------------------------------------------------------
def test_components_validate_reports_errors(tmp_path):
    f = tmp_path / "c.csv"
    head = ";".join(components.REQUIRED + ["in_"])
    f.write_text("\n".join([
        head,
        "ok-1;ABB;S201;Jistič;mcb;;https://abb.com/x;catalog;16",
        "Spatne ID;ABB;S2;Jistič;mcb;;https://x;catalog;",
        "ok-1;ABB;S3;Jistič;mcb;;https://x;catalog;",
        "ok-3;;S4;;neznama;;;catalog;šestnáct",
    ]), encoding="utf-8")
    errs = components.validate(f)
    joined = "\n".join(errs)
    for frag in ("id 'Spatne ID'", "duplicitní id 'ok-1'", "prázdné 'manufacturer'", "prázdné 'name'",
                 "neznámá kategorie 'neznama'", "datasheet_url musí být", "'in_' musí být číslo"):
        assert frag in joined, frag
    assert components.main(["validate", str(f)]) == 1
    (tmp_path / "bad.csv").write_text("id;name\nx;y\n", encoding="utf-8")
    assert "chybí sloupce" in components.validate(tmp_path / "bad.csv")[0]


def test_components_stats_and_unknown_symbol(tmp_path, capsys):
    f = tmp_path / "c.csv"
    f.write_text(";".join(components.REQUIRED + ["in_"]) + "\n"
                 "a;ABB;1;J;mcb;neexistuje.sym;https://x;catalog;16\nb;ABB;2;J;mcb;;https://x;catalog;\n",
                 encoding="utf-8")
    assert any("neznámý symbol_id" in e for e in components.validate(f, known_symbols={"fve.inverter"}))
    st = components.stats(f)
    assert st["count"] == 2 and st["in_"] == 50
    assert components.main(["stats", str(f)]) == 0
    assert "count: 2" in capsys.readouterr().out
