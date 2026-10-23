"""Technická zpráva a DSPS ze šablony (docs/design/tz_dsps.md): engine šablony, složky šablon, obsah z modelu."""
from __future__ import annotations

import copy

import pytest
from docx import Document
from docx.oxml.ns import qn

from envocad.export import doc_template as dt
from envocad.export.tz_export import export_report_docx, export_tz_docx, save_template_docx
from envocad.generate import build_project
from envocad.library import doc_templates
from envocad.library.store import LibraryStore
from envocad.model.project import Project

_INV = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}
SPECS = {
    "firma": {"name": "FVE Firma", "meta": {"investor": "Firma s.r.o.", "place": "Brno"},
              "inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}, {"ref": "T2", **_INV, "strings": [18]}],
              "grid": {"dso": "EG.D"}},
    "rd": {"building": "house", "inverters": [{"ref": "T1", **_INV, "strings": [16, 16]}],
           "battery": {"e_kwh": 10, "p_kw": 5, "type": "BYD HVS 10.2"}},
    "vn": {"inverters": [{"ref": "T1", **_INV, "strings": [20, 20]}],
           "connection": {"level": "vn", "station": "kiosk", "loop": True, "metering": "nn"}},
}


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


@pytest.fixture(scope="module")
def projects():
    return {k: build_project(copy.deepcopy(v)) for k, v in SPECS.items()}


def _text(path) -> str:
    """Celý text dokumentu v pořadí těla (odstavce i buňky tabulek) + záhlaví a zápatí."""
    d = Document(str(path))
    out = ["".join(t.text or "" for t in el.iter(qn("w:t"))) for el in d.element.body.iter(qn("w:p"))]
    for sec in d.sections:
        out += [p.text for p in sec.header.paragraphs] + [p.text for p in sec.footer.paragraphs]
    return "\n".join(out)


def _doc(*paragraphs: str):
    d = Document()
    for p in paragraphs:
        d.add_paragraph(p)
    return d


def _ptexts(d) -> list[str]:
    return [p.text for p in d.paragraphs]


# ---- engine ----------------------------------------------------------------------------------------------------
def test_substitute_fields_missing_and_default():
    ctx = {"a": {"b": 2.5, "c": "", "l": ["x", "", "y"], "t": True}}
    assert dt.substitute("{{a.b}} kWp", ctx) == "2,5 kWp"
    assert dt.substitute("{{a.c}}|{{a.nic.dal}}", ctx) == "neuvedeno|neuvedeno"
    assert dt.substitute("[{{a.c|–}}][{{a.c|}}]", ctx) == "[–][]"
    assert dt.substitute("{{ a.l }} {{a.t}}", ctx) == "x, y ano"
    assert dt.substitute("{{§}} Nadpis", ctx) == "{{§}} Nadpis"     # číslo kapitoly až po vynechání sekcí
    # jednotka za chybějícím údajem se vynechá, za vyplněným zůstane; „V“ na začátku slova jednotka není
    assert dt.substitute("{{a.c}} kWp, {{a.b}} kWp, {{a.c}} %.", ctx) == "neuvedeno, 2,5 kWp, neuvedeno."
    assert dt.substitute("{{a.c}} Voc", ctx) == "neuvedeno Voc"


def test_field_split_across_runs_is_merged():
    d = Document()
    p = d.add_paragraph()
    for part in ("Výkon {{fve.", "p_dc", "_kwp}} kWp"):
        p.add_run(part)
    dt.render(d, {"fve": {"p_dc_kwp": 26.1}})
    assert d.paragraphs[0].text == "Výkon 26,1 kWp"


def test_conditions_loops_and_nesting():
    d = _doc("{% if x %}", "x ano", "{% else %}", "x ne", "{% endif %}",
             "{% if not y %}", "y prázdné", "{% endif %}",
             '{% if u == "vn" %}', "přípojka vn", "{% endif %}",
             "{% for s in items %}", "{% if s.on %}", "* {{s.name}}", "{% endif %}", "{% endfor %}", "konec")
    dt.render(d, {"x": "", "y": None, "u": "vn",
                  "items": [{"name": "A", "on": True}, {"name": "B", "on": False}, {"name": "C", "on": True}]})
    assert _ptexts(d) == ["x ne", "y prázdné", "přípojka vn", "* A", "* C", "konec"]


def test_loop_repeats_tables_and_fields_in_cells():
    d = _doc("{% for r in rows %}")
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "{{r.k}}", "{{r.v|-}}"
    d.add_paragraph("{% endfor %}")
    dt.render(d, {"rows": [{"k": "a", "v": "1"}, {"k": "b"}]})
    assert [[c.text for c in tb.rows[0].cells] for tb in d.tables] == [["a", "1"], ["b", "-"]]


def test_bad_markers_do_not_raise():
    d = _doc("{% if x %}", "bez konce", "{% for a b %}", "{% endfor %}", "{% endif?? %}", "{% else %}")
    dt.render(d, {"x": "1"})
    text = "\n".join(_ptexts(d))
    assert "chyba šablony" in text and "bez konce" in text


def test_blocks_inserted_at_marker_and_failures_contained():
    def ok(doc, ctx):
        doc.add_paragraph("z bloku")
        doc.add_table(rows=1, cols=1).cell(0, 0).text = "buňka"

    def bad(doc, ctx):
        doc.add_paragraph("rozpracováno")
        raise RuntimeError("chyba")

    d = _doc("před", "{{tabulka.ok}}", "mezi", "{{blok.spatny}}", "{{tabulka.neznama}}", "za")
    dt.render(d, {}, {"tabulka.ok": ok, "blok.spatny": bad})
    body = ["".join(t.text or "" for t in el.iter(qn("w:t"))) for el in d.element.body if el.tag != qn("w:sectPr")]
    assert body == ["před", "z bloku", "buňka", "mezi", "neuvedeno (výpočet „blok.spatny“ selhal)", "neuvedeno", "za"]


def test_heading_numbers_skip_removed_sections():
    d = Document()
    d.add_heading("{{§}} Úvod", 1)
    d.add_paragraph("{% if vn %}")
    d.add_heading("{{§}} Přípojka vn", 1)
    d.add_paragraph("{% endif %}")
    d.add_heading("{{§}} Ochrana", 1)
    d.add_heading("{{§}} Přepětí", 2)
    dt.render(d, {"vn": None})
    assert _ptexts(d) == ["1. Úvod", "2. Ochrana", "2.1. Přepětí"]


def test_header_and_footer_fields():
    d = _doc("tělo")
    d.sections[0].header.is_linked_to_previous = False
    d.sections[0].header.paragraphs[0].text = "Zakázka {{projekt.zakazka}}"
    d.sections[0].footer.is_linked_to_previous = False
    d.sections[0].footer.paragraphs[0].text = "{{projekt.nazev}}"
    dt.render(d, {"projekt": {"zakazka": "Z-1", "nazev": "FVE"}})
    assert d.sections[0].header.paragraphs[0].text == "Zakázka Z-1"
    assert d.sections[0].footer.paragraphs[0].text == "FVE"


def test_markdown_source_and_include(tmp_path):
    (tmp_path / "_cast.md").write_text("## Vložená část\n\n- bod {{x}}\n", encoding="utf-8")
    (tmp_path / "hlavni.md").write_text("<!-- komentář -->\n#! Titul\n\nřádek jedna\nřádek dvě\n\n"
                                        "@include _cast.md\n@include chybi.md\n{{tabulka.t}}\n", encoding="utf-8")
    d = dt.load_template(tmp_path / "hlavni.md")
    texts = _ptexts(d)
    assert texts[:4] == ["Titul", "řádek jedna řádek dvě", "Vložená část", "bod {{x}}"]
    assert d.paragraphs[0].style.name == "Title" and d.paragraphs[3].style.name == "List Bullet"
    assert any("nelze vložit chybi.md" in t for t in texts) and "{{tabulka.t}}" in texts
    assert not any("komentář" in t for t in texts)


def test_docx_without_markers_is_base_for_builtin_outline(tmp_path):
    base = Document()
    base.add_paragraph("Logo ENVO")
    base.save(tmp_path / "podklad.docx")
    d = dt.load_template(tmp_path / "podklad.docx", doc_templates.builtin_template("tz"))
    texts = _ptexts(d)
    assert texts[0] == "Logo ENVO" and any("{{tabulka.stringy}}" in t for t in texts)
    assert dt.has_markers(d) and not dt.has_markers(base)


# ---- složky šablon --------------------------------------------------------------------------------------------
def test_template_folders_override_and_kind(tmp_path):
    from envocad import settings
    shared = tmp_path / "sdilena"
    (shared / "doc_templates").mkdir(parents=True)
    (shared / "doc_templates" / "tz.docx").write_bytes(b"")          # přebije vestavěnou tz
    (shared / "doc_templates" / "Obecna.docx").write_bytes(b"")
    st = settings.load_settings()
    st["shared_library_dir"] = str(shared)
    settings.save_settings(st)
    user = doc_templates.user_dir()
    user.mkdir(parents=True, exist_ok=True)
    (user / "dsps_envo.docx").write_bytes(b"")
    (user / "~$dsps_envo.docx").write_bytes(b"")                      # zámek Wordu
    (user / "_cast.md").write_text("", encoding="utf-8")              # vkládaná část
    names = {t.name: t for t in doc_templates.list_templates()}
    assert set(names) == {"tz", "dsps", "Obecna", "dsps_envo"}
    assert names["tz"].source == "sdílená" and names["dsps"].source == "vestavěná"
    assert [t.name for t in doc_templates.list_templates("tz")] == ["Obecna", "tz"]
    assert names["dsps_envo"].kind == "dsps" and names["Obecna"].kind == ""
    assert doc_templates.default_template("tz").source == "sdílená"
    assert doc_templates.default_template("dsps").path == doc_templates.builtin_template("dsps")
    with pytest.raises(ValueError):
        doc_templates.builtin_template("xx")


def test_builtin_templates_exist_and_are_packaged():
    import tomllib
    from pathlib import Path
    for kind in doc_templates.KINDS:
        assert doc_templates.builtin_template(kind).is_file()
    py = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert "library/builtin/doc_templates/*.md" in py["tool"]["setuptools"]["package-data"]["envocad"]


# ---- obsah z modelu ---------------------------------------------------------------------------------------------
def test_tz_firma_key_values(projects, lib, tmp_path):
    out = tmp_path / "tz.docx"
    export_report_docx(projects["firma"], lib, out, company="ENVO s.r.o.")
    text = _text(out)
    for needle in ("Technická zpráva – FVE Firma", "Investor: Firma s.r.o.", "Instalovaný výkon DC: 26,1 kWp",
                   "Výkon střídačů AC: 50 kW", "Fotovoltaické moduly: 58 ks", "Střídače: 2 ks",
                   "stringy → RFVE.DC → T → RFVE.AC → HR → RE → HDS → DS", "na hladině nn",
                   "Provozovatel DS: EG.D", "Hranice vlastnictví: HDS", "pojistkami: 3× 25 A gPV",
                   "Kontrola stringů proti střídači", "Uoc při -10 °C [V]", "Seznam výkresů", "Výkaz materiálu",
                   "ENVO s.r.o."):
        assert needle in text, needle
    assert "{{" not in text and "{%" not in text
    assert "Přípojka vn a transformace" not in text and "Akumulace:" not in text   # sekce bez údajů vynechány
    d = Document(str(out))
    assert d.core_properties.title == "Technická zpráva – FVE Firma"
    heads = [p.text for p in d.paragraphs if p.style.name.startswith("Heading 1")]
    assert heads[0] == "1. Identifikační údaje" and all(h.split(".")[0].isdigit() for h in heads)


def test_tz_rd_key_values(projects, lib, tmp_path):
    out = tmp_path / "tz.docx"
    export_tz_docx(projects["rd"], lib, out)
    text = _text(out)
    assert "Druh objektu: rodinný dům" in text and "stringy → RFVE → T → RD → RE → HDS → DS" in text
    assert "Akumulace: G3 BYD HVS 10.2 10 kWh / 5 kW" in text and "zálohované okruhy (EPS)" in text
    assert "Soustava AC (dle hlaviček rozvaděčů): 3NPE, 50 Hz" in text and "Soustava DC: DC IT" in text


def test_tz_vn_key_values(projects, lib, tmp_path):
    out = tmp_path / "tz.docx"
    export_tz_docx(projects["vn"], lib, out)
    text = _text(out)
    assert "na hladině vn" in text and "Přípojka vn a transformace" in text
    assert "Transformátor: TR1 630 kVA 22/0,42 kV Dyn1 uk 6 %" in text
    assert "Ik'' = 15,9 kA na svorkách nn TR1" in text
    assert "Napěťová soustava: 3~ 22 kV, 50 Hz" in text


def test_grid_protection_section_only_when_relevant(lib, tmp_path):
    from envocad.export.tz_data import report_context
    p = build_project({"inverters": [{"ref": "T1", **_INV, "strings": [20, 20, 20, 20]}]})   # 36 kWp > 30
    ctx = report_context(p, lib)
    assert ctx["sitova_ochrana"]["pozadovana"] is True
    export_tz_docx(p, lib, tmp_path / "a.docx")
    assert "Síťová ochrana" in _text(tmp_path / "a.docx") and "převyšuje hranici 30 kWp" in _text(tmp_path / "a.docx")
    small = build_project({"inverters": [{"ref": "T1", **_INV, "strings": [10]}]})
    export_tz_docx(small, lib, tmp_path / "b.docx")
    assert "Síťová ochrana" not in _text(tmp_path / "b.docx")


def test_custom_template_with_own_field(projects, lib, tmp_path):
    d = Document()
    d.add_heading("{{§}} Stavební povolení", 1)
    d.add_paragraph("Číslo SP: {{meta.cislo_sp}}; pole: {{pole.poznamka|bez poznámky}}; DC {{fve.p_dc_kwp}} kWp")
    d.add_paragraph("{% for s in stridace %}")
    d.add_paragraph("Střídač {{s.oznaceni}} – {{s.p_ac_kw}} kW, typ {{s.typ}}")
    d.add_paragraph("{% endfor %}")
    d.add_paragraph("{{tabulka.listy}}")
    d.save(tmp_path / "vlastni.docx")
    p = copy.deepcopy(projects["firma"])
    p.meta["cislo_sp"] = "SP/123/2026"
    out = tmp_path / "out.docx"
    export_report_docx(p, lib, out, template=tmp_path / "vlastni.docx", fields={"poznamka": "test"})
    text = _text(out)
    assert "1. Stavební povolení" in text
    assert "Číslo SP: SP/123/2026; pole: test; DC 26,1 kWp" in text
    assert "Střídač T1 – 25 kW, typ neuvedeno" in text and "Střídač T2 – 25 kW" in text
    assert "Blokové schéma" in text and "Identifikační údaje" not in text   # jen vlastní obsah šablony


def test_missing_data_does_not_break_export(lib, tmp_path):
    out = tmp_path / "prazdny.docx"
    export_report_docx(Project(name=""), lib, out)
    text = _text(out)
    assert "Instalovaný výkon DC: neuvedeno\n" in text and "Řetězec rozvaděčů: neuvedeno." in text
    assert "Stringy v projektu nejsou." in text and "{{" not in text
    export_report_docx(Project(name="x"), lib, tmp_path / "d.docx", kind="dsps")
    assert "nebylo provedeno" in _text(tmp_path / "d.docx")
    with pytest.raises(ValueError):
        export_report_docx(Project(name="x"), lib, tmp_path / "e.docx", kind="nic")


def test_dsps_lists_changes_against_design(projects, lib, tmp_path):
    design = projects["firma"]
    built = copy.deepcopy(design)
    spd = next(e for s in built.sheets for e in s.elements if e.symbol_id == "fve.spd")
    spd.attrs["type"] = "DEHNcube YPV 1000"
    built.meta["dsps_date"] = "15.10.2026"
    built.meta["changes"] = "A | 16.10.2026 | výměna SPD | PR"
    out = tmp_path / "dsps.docx"
    export_report_docx(built, lib, out, kind="dsps", old=design,
                       fields={"dsps_inspection_report": "RZ 42/2026", "dsps_contractor": "ENVO s.r.o."})
    text = _text(out)
    assert "Dokumentace skutečného provedení – FVE Firma" in text
    assert "Datum provedení: 15.10.2026" in text and "Výchozí revize elektrické instalace: RZ 42/2026" in text
    assert "Zhotovitel: ENVO s.r.o." in text and "0 přidáno, 1 změněno, 0 odebráno" in text
    assert "type: VPU PV I+II 3 1000 → DEHNcube YPV 1000" in text and spd.ref in text
    assert "výměna SPD" in text                                   # změnový list z meta
    assert "Instalovaný výkon DC: 26,1 kWp" in text               # společné jádro s TZ
    assert Document(str(out)).core_properties.title.startswith("Dokumentace skutečného provedení")


def test_dsps_without_changes(projects, lib, tmp_path):
    out = tmp_path / "dsps.docx"
    export_report_docx(projects["rd"], lib, out, kind="dsps", old=copy.deepcopy(projects["rd"]))
    assert "Proti projektové dokumentaci beze změn." in _text(out)


def test_saved_builtin_template_round_trip(projects, lib, tmp_path):
    tpl = tmp_path / "tz_envo.docx"
    save_template_docx("tz", tpl)
    assert "{{fve.p_dc_kwp}}" in _text(tpl) and "{{tabulka.stringy}}" in _text(tpl)
    out = tmp_path / "z_sablony.docx"
    export_report_docx(projects["firma"], lib, out, template=tpl)
    text = _text(out)
    assert "Instalovaný výkon DC: 26,1 kWp" in text and "{{" not in text


def test_export_does_not_change_project(projects, lib, tmp_path):
    import json
    p = projects["vn"]
    before = json.dumps(p.to_dict(), sort_keys=True)
    export_report_docx(p, lib, tmp_path / "a.docx", kind="dsps", old=projects["firma"])
    assert json.dumps(p.to_dict(), sort_keys=True) == before
