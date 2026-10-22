"""Kontroly z údajů artiklů (model/ratings.py, docs/design/kontroly_artiklu.md) – bez Qt."""
import pytest

from envocad.library.components import Component
from envocad.model import calc, ratings
from envocad.model.checks import ERROR, INFO, WARNING, check_project
from envocad.model.project import Element, Project, Wire, WireEnd

AC3 = ["L1", "L2", "L3", "N", "PE"]
DC = ["L+", "L-"]
RATING_CODES = {"sc_icu", "sc_icw", "sc_icu_icw", "sc_upstream", "spd_uc", "spd_ucpv", "spd_up", "spd_lps",
                "terminal_cross", "terminal_in", "un_ac", "un_dc"}


class FakeLib:
    """Knihovna jen s artikly (bez značek) – `Data.comp` volá `component(id)`."""

    def __init__(self, *comps):
        self.comps = {c.id: c for c in comps}

    def component(self, cid):
        return self.comps.get(cid)


def _comp(cid, category, **params):
    return Component(cid, "X", cid.upper(), cid, category, "", params={k: str(v) for k, v in params.items()})


def _wire(s, a, pa, b, pb, conds, **attrs):
    w = Wire(WireEnd(a.id, pa), WireEnd(b.id, pb), attrs=dict(attrs), conductors=list(conds))
    s.wires.append(w)
    return w


def _board(params=None, block_attrs=None):
    """Projekt s blokem rozvaděče R1 a jeho listem; vrací (projekt, list rozvaděče, blok)."""
    p = Project(name="T")
    blk = Element("fve.switchboard", 100, 100, attrs={"ref": "R1", **(block_attrs or {})})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    sb.layout.params.update(params or {})
    return p, sb, blk


def _ac_breaker(sb, ref="F1", **attrs):
    """Jistič zapojený mezi dvěma svorkami v trojfázovém obvodu."""
    x1 = Element("sb.terminal_block", 0, 0, attrs={"ref": "X1"})
    x2 = Element("sb.terminal_block", 50, 0, attrs={"ref": "X2"})
    f = Element("fve.breaker_mcb", 20, 0, attrs={"ref": ref, **attrs})
    sb.elements += [x1, f, x2]
    _wire(sb, x1, "2", f, "1", AC3)
    _wire(sb, f, "2", x2, "1", AC3)
    return f


def _codes(fs, *codes):
    return [f for f in fs if f.code in codes]


# ---- data -------------------------------------------------------------------------------------------------------
def test_number_parsing():
    assert ratings.first_num("6 kA") == 6 and ratings.first_num("3,8") == 3.8 and ratings.first_num("1000 V DC") == 1000
    assert ratings.max_num("230/400 V") == 400 and ratings.first_num("") is None and ratings.max_num(None) is None


def test_attribute_wins_over_article_and_article_fills_gap():
    lib = FakeLib(_comp("mcb", "mcb", icu_ka=6, un_v=400))
    e = Element("fve.breaker_mcb", 0, 0, attrs={"ref": "F1", "icu": "10"}, component_id="mcb")
    d = ratings.Data(lib)
    assert d.num(e, "icu", "icu_ka") == 10 and d.num(e, "un", "un_v") == 400
    assert ratings.Data(None).num(e, "un", "un_v") is None      # bez knihovny jen atributy


def test_board_network_and_uo():
    p, sb, _ = _board({"network": "3NPE, 50 Hz / DC IT", "un": "230/400 V AC / max. 1000 V DC"})
    b = ratings.board_of(p, sb)
    assert (b.network, b.uo) == ("TN", 230)          # „DC IT“ je DC část – AC zůstává TN
    sb.layout.params.update({"network": "IT", "un": "400 V"})
    b = ratings.board_of(p, sb)
    assert b.network == "IT" and b.uo == pytest.approx(230.9, abs=0.1)
    assert ratings.board_of(p, p.sheets[0]).network == "TN"


# ---- 1. In / I2 vs. Iz (calc.check_cables) ------------------------------------------------------------------------
def test_conventional_trip_factor():
    f = calc.conventional_trip_factor
    assert f(Element("fve.breaker_mcb", 0, 0)) == 1.45 and f(Element("fve.breaker_mccb", 0, 0)) == 1.3
    assert f(Element("fve.fuse", 0, 0, attrs={"char": "gG", "in_": "2"})) == 2.1
    assert f(Element("fve.fuse", 0, 0, attrs={"char": "gG", "in_": "10"})) == 1.9
    assert f(Element("fve.fuse", 0, 0, attrs={"char": "gG", "in_": "125"})) == 1.6
    assert f(Element("fve.fuse", 0, 0, attrs={"char": "gPV", "in_": "16"})) == 1.45
    assert f(Element("fve.fuse", 0, 0, attrs={"char": "aM", "in_": "16"})) is None


def _cable_case(symbol, **attrs):
    p = Project()
    s = p.sheets[0]
    prot = Element(symbol, 0, 0, attrs={"ref": "F1", **attrs})
    load = Element("fve.load", 100, 0, attrs={"ref": "M1"})
    s.elements += [prot, load]
    _wire(s, prot, "2", load, "1", AC3, ref="W1", cross="50", method="B1", length="10")
    return next(c for c in calc.check_cables(p) if c.ref == "W1")


def test_cable_i2_for_gg_fuse():
    cc = _cable_case("fve.fuse", in_="125", char="gG")            # Iz 134 A (B1), In 125 A ≤ Iz
    assert cc.iz == 134 and not any("In jističe" in m for m in cc.issues)
    assert any(m.startswith("I2 jištění F1 = 1,6·In = 200 A > 1,45·Iz = 194,3 A") for m in cc.issues), cc.issues
    assert not any("I2" in m for m in _cable_case("fve.breaker_mcb", in_="125").issues)     # jistič: I2 = 1,45·In
    assert not any("I2" in m for m in _cable_case("fve.fuse", in_="125", char="aM").issues)  # aM: bez kontroly
    over = _cable_case("fve.fuse", in_="160", char="gG")          # In > Iz – jen jedna hláška (In ≤ Iz)
    assert any("In jističe" in m for m in over.issues) and not any("I2" in m for m in over.issues)


# ---- 2. zkratová odolnost -----------------------------------------------------------------------------------------
def test_icu_below_board_ik():
    p, sb, _ = _board(block_attrs={"ik_ka": "10"})
    f = _ac_breaker(sb, icu="6")
    _ac_breaker(sb, ref="F2", icu="10")
    fs = ratings.short_circuit_findings(p, ratings.Data())
    assert [(x.code, x.severity, x.ref) for x in fs] == [("sc_icu", WARNING, "F1")]
    assert "Icu 6 kA < Ik 10 kA" in fs[0].text and fs[0].target_id == f.id


def test_icw_below_ik_and_icu_below_icw():
    p, sb, _ = _board({"ik_ka": "10", "icw": "6"})
    fs = ratings.short_circuit_findings(p, ratings.Data())
    assert [(x.code, x.severity) for x in fs] == [("sc_icw", ERROR)]
    p, sb, _ = _board({"icw": "10"})                  # Ik nezadán: přístroj pod Icw rozvaděče
    _ac_breaker(sb, icu="6")
    fs = ratings.short_circuit_findings(p, ratings.Data())
    assert [(x.code, x.severity) for x in fs] == [("sc_icu_icw", WARNING)]


def test_short_circuit_from_article_and_missing_data():
    lib = FakeLib(_comp("mcb6", "mcb", icu_ka=6))
    p, sb, _ = _board(block_attrs={"ik_ka": "10"})
    f = _ac_breaker(sb)
    assert ratings.short_circuit_findings(p, ratings.Data(lib)) == []   # bez Icu nic
    f.component_id = "mcb6"
    assert [x.code for x in ratings.short_circuit_findings(p, ratings.Data(lib))] == ["sc_icu"]
    p, sb, _ = _board()                                # bez Ik i Icw: nic
    _ac_breaker(sb, icu="6")
    assert ratings.short_circuit_findings(p, ratings.Data()) == []


def test_dc_breaker_skips_short_circuit():
    p, sb, _ = _board(block_attrs={"ik_ka": "10"})
    a = Element("sb.feed", 0, 0, attrs={"ref": "X1", "dir": "in"})
    f = Element("fve.breaker_mcb", 20, 0, attrs={"ref": "F1", "icu": "6"})
    sb.elements += [a, f]
    _wire(sb, a, "1", f, "1", DC)
    assert ratings.short_circuit_findings(p, ratings.Data()) == []


def test_upstream_ik_transformer_and_meta_is_info():
    assert ratings.transformer_ik_ka(630, 6) == pytest.approx(15.2, abs=0.05)
    p, sb, blk = _board()
    _ac_breaker(sb, icu="6")
    _ac_breaker(sb, ref="F2", icu="25")
    p.sheets[0].elements.append(Element("fve.transformer", 0, 50, attrs={"ref": "TR1", "sn": "630", "uk": "6"}))
    fs = ratings.short_circuit_findings(p, ratings.Data())
    assert [(x.code, x.severity) for x in fs] == [("sc_upstream", INFO)]
    assert "TR1" in fs[0].text and "F1 Icu 6 kA" in fs[0].text and "F2" not in fs[0].text
    p.meta["ik_ka"] = "4"                              # zadané Ik místa připojení má přednost před TR
    assert ratings.short_circuit_findings(p, ratings.Data()) == []
    blk.attrs["ik_ka"] = "8"
    p.meta["ik_ka"] = "20"                             # Ik rozvaděče přebíjí horní odhad
    assert [x.code for x in ratings.short_circuit_findings(p, ratings.Data())] == ["sc_icu"]


# ---- 3. svodiče ----------------------------------------------------------------------------------------------------
def _ac_spd(params=None, **attrs):
    p, sb, _ = _board(params)
    x = Element("sb.terminal_block", 0, 0, attrs={"ref": "X1"})
    spd = Element("fve.spd", 20, 0, attrs={"ref": "F3", **attrs})
    sb.elements += [x, spd]
    _wire(sb, x, "2", spd, "L", ["L1", "L2", "L3", "N"])
    return p, sb, spd


def test_ac_spd_uc_vs_network():
    assert ratings.spd_uc_required("TN", 230) == 253 and ratings.spd_uc_required("IT", 230) == pytest.approx(398.4)
    p, _sb, _ = _ac_spd(uc="275", spd_type="T2")
    assert ratings.spd_findings(p, ratings.Data()) == []
    p, _sb, _ = _ac_spd(uc="230", spd_type="T2")
    fs = ratings.spd_findings(p, ratings.Data())
    assert [(x.code, x.severity) for x in fs] == [("spd_uc", ERROR)] and "1,1·Uo = 253 V" in fs[0].text
    p, _sb, _ = _ac_spd({"network": "IT"}, uc="275")
    assert [x.code for x in ratings.spd_findings(p, ratings.Data())] == ["spd_uc"]
    p, _sb, _ = _ac_spd({"network": "IT"}, uc="440")
    assert ratings.spd_findings(p, ratings.Data()) == []
    p, _sb, _ = _ac_spd()                              # bez Uc nic
    assert ratings.spd_findings(p, ratings.Data()) == []


def test_spd_lps_needs_type1():
    p, _sb, _ = _ac_spd({"wire_spd_lps": "yes"}, uc="275", spd_type="T2")
    fs = ratings.spd_findings(p, ratings.Data())
    assert [(x.code, x.severity) for x in fs] == [("spd_lps", INFO)] and "F3 (T2)" in fs[0].text
    p, _sb, _ = _ac_spd({"wire_spd_lps": "yes"}, uc="275", spd_type="T1+T2")
    assert ratings.spd_findings(p, ratings.Data()) == []
    p, _sb, _ = _ac_spd({"wire_spd_lps": "no"}, uc="275", spd_type="T2")
    assert ratings.spd_findings(p, ratings.Data()) == []


def _dc_project(n=20, spd_attrs=None, dev_attrs=None, inv_attrs=None, spd_comp="", t_min=-10):
    """String G1 (n × 49,5 V, β −0,27 %/K) → blok RDC (list: X1 → odpojovač F1 → X2, SPD na F1:2) → střídač T1."""
    p = Project(name="DC")
    s = p.sheets[0]
    p.meta["pv_t_min"] = str(t_min)
    g = Element("fve.pv_string", 0, 0, attrs={"ref": "G1", "n_modules": str(n), "voc": "49.5", "beta_voc": "-0.27"})
    blk = Element("fve.switchboard", 50, 0, attrs={"ref": "RDC"})
    t = Element("fve.inverter", 100, 0, attrs={"ref": "T1", **(inv_attrs or {})})
    s.elements += [g, blk, t]
    _wire(s, g, "DC", blk, "X1", DC, ref="W1")
    _wire(s, blk, "X2", t, "DC1", DC, ref="W2")
    sb = p.create_switchboard_sheet(blk)
    x1 = Element("sb.feed", 0, 0, attrs={"ref": "X1", "dir": "in"})
    x2 = Element("sb.feed", 60, 0, attrs={"ref": "X2", "dir": "out"})
    f = Element("fve.fuse_disconnect", 20, 0, attrs={"ref": "F1", **(dev_attrs or {})})
    spd = Element("fve.spd", 40, 0, attrs={"ref": "F2", "spd_type": "T2 DC", **(spd_attrs or {})},
                  component_id=spd_comp or None)
    sb.elements += [x1, x2, f, spd]
    _wire(sb, x1, "1", f, "1", DC)
    _wire(sb, f, "2", x2, "1", DC)
    _wire(sb, f, "2", spd, "L", DC)
    return p, f, spd, t


def test_dc_voltages_follow_string_into_board():
    p, f, spd, _t = _dc_project()
    v = calc.dc_voltages(p)
    assert v[f.id].u == pytest.approx(1083.6) and v[f.id].string_ref == "G1" and v[f.id].inverter.ref == "T1"
    assert v[spd.id].u == pytest.approx(1083.6)
    p, f, _spd, _t = _dc_project(t_min=-20)             # návrhová teplota z projektu
    assert calc.dc_voltages(p)[f.id].u == pytest.approx(1110.3)
    p, f, _spd, _t = _dc_project(inv_attrs={"string_mode": "fixed_voltage", "u_string": "750"})
    assert calc.dc_voltages(p)[f.id].u == 750


def test_dc_spd_ucpv():
    p, _f, _spd, _t = _dc_project(spd_attrs={"uc": "1000 V DC"})        # jen Uc pod Uoc → informace
    fs = ratings.spd_findings(p, ratings.Data())
    assert [(x.code, x.severity) for x in fs] == [("spd_ucpv", INFO)] and "Ucpv neznámé" in fs[0].text
    p, _f, _spd, _t = _dc_project(spd_attrs={"uc": "1000 V DC", "ucpv": "1100"})
    assert ratings.spd_findings(p, ratings.Data()) == []
    p, _f, _spd, _t = _dc_project(spd_attrs={"ucpv": "1050"})
    fs = ratings.spd_findings(p, ratings.Data())
    assert [(x.code, x.severity) for x in fs] == [("spd_ucpv", WARNING)] and "1083,6 V" in fs[0].text
    lib = FakeLib(_comp("vpu", "spd", uc_v=1000, spd_type="T1+T2 DC", note="DC | Ucpv 1100 V | Up 3,8 kV"))
    p, _f, _spd, _t = _dc_project(spd_comp="vpu")                       # Ucpv z poznámky artiklu
    assert ratings.spd_findings(p, ratings.Data(lib)) == []
    p, _f, _spd, _t = _dc_project(n=18, spd_attrs={"uc": "1000 V DC"})  # 975 V – v pořádku
    assert ratings.spd_findings(p, ratings.Data()) == []


def test_dc_spd_up_vs_inverter_uw():
    p, _f, _spd, _t = _dc_project(n=10, spd_attrs={"up": "3,8"}, inv_attrs={"uw": "2,5"})
    fs = ratings.spd_findings(p, ratings.Data())
    assert [(x.code, x.severity) for x in fs] == [("spd_up", WARNING)] and "T1" in fs[0].text
    p, _f, _spd, _t = _dc_project(n=10, spd_attrs={"up": "2,2"}, inv_attrs={"uw": "2,5"})
    assert ratings.spd_findings(p, ratings.Data()) == []
    p, _f, _spd, _t = _dc_project(n=10, spd_attrs={"up": "3,8"})        # Uw neznámé → nic
    assert ratings.spd_findings(p, ratings.Data()) == []


# ---- 4. svorky -----------------------------------------------------------------------------------------------------
def test_terminal_cross_max():
    p, sb, _ = _board()
    x = Element("sb.terminal_block", 0, 0, attrs={"ref": "X1", "cross_max": "4"})
    load = Element("fve.load", 50, 0, attrs={"ref": "M1"})
    sb.elements += [x, load]
    w = _wire(sb, x, "2", load, "1", AC3, cross="6")
    fs = ratings.terminal_findings(p, ratings.Data())
    assert [(f.code, f.severity) for f in fs] == [("terminal_cross", ERROR)] and "6 mm²" in fs[0].text
    w.attrs["cross"] = "4"
    assert ratings.terminal_findings(p, ratings.Data()) == []


def test_feed_cross_max_vs_linked_cable():
    p, _f, _spd, _t = _dc_project()
    sb = p.switchboard_sheet(p.sheets[0].elements[1].id)
    x1 = next(e for e in sb.elements if e.ref == "X1")
    x1.attrs["cross_max"] = "4"
    w1 = next(w for w in p.sheets[0].wires if w.attrs.get("ref") == "W1")
    w1.attrs["cross"] = "6"
    x1.attrs["wire_id"] = w1.id
    assert [f.code for f in ratings.terminal_findings(p, ratings.Data())] == ["terminal_cross"]


def test_terminal_in_vs_protection():
    lib = FakeLib(_comp("svorka", "terminal", in_=24, cross_max_mm2=4))
    p, sb, _ = _board()
    f = _ac_breaker(sb, in_="32")
    x2 = next(e for e in sb.elements if e.ref == "X2")
    x2.component_id = "svorka"
    fs = ratings.terminal_findings(p, ratings.Data(lib))
    assert [(x.code, x.severity, x.ref) for x in fs] == [("terminal_in", WARNING, "X2")] and "F1 32 A" in fs[0].text
    f.attrs["in_"] = "20"
    assert ratings.terminal_findings(p, ratings.Data(lib)) == []


# ---- 5. jmenovité napětí -------------------------------------------------------------------------------------------
def test_un_ac():
    p, sb, _ = _board()
    f = _ac_breaker(sb, un="230", poles="3")
    fs = ratings.un_findings(p, ratings.Data())
    assert [(x.code, x.severity, x.ref) for x in fs] == [("un_ac", ERROR, "F1")] and "sdružené" in fs[0].text
    f.attrs["un"] = "230/400"
    assert ratings.un_findings(p, ratings.Data()) == []
    p, sb, _ = _board()                                  # 1f jistič 230 V v obvodu L1+N
    x = Element("sb.terminal_block", 0, 0, attrs={"ref": "X1"})
    f1 = Element("fve.breaker_mcb", 20, 0, attrs={"ref": "F1", "un": "230", "poles": "1"})
    sb.elements += [x, f1]
    _wire(sb, x, "2", f1, "1", ["L1", "N"])
    assert ratings.un_findings(p, ratings.Data()) == []


def test_un_ac_skips_dc_article():
    lib = FakeLib(_comp("pl7", "mcb", un_v=250, note="DC | jen DC"))
    p, sb, _ = _board()
    f = _ac_breaker(sb, poles="3")
    f.component_id = "pl7"
    assert ratings.un_findings(p, ratings.Data(lib)) == []


def test_un_dc_vs_string_uoc():
    p, _f, _spd, _t = _dc_project(dev_attrs={"un": "1000"})
    fs = ratings.un_findings(p, ratings.Data())
    assert [(x.code, x.severity, x.ref) for x in fs] == [("un_dc", WARNING, "F1")]
    assert "Un F1 1000 V DC < Uoc stringu G1 1083,6 V" in fs[0].text
    p, _f, _spd, _t = _dc_project(dev_attrs={"un": "1500"})
    assert ratings.un_findings(p, ratings.Data()) == []
    p, _f, _spd, _t = _dc_project(n=18, dev_attrs={"un": "1000"})
    assert ratings.un_findings(p, ratings.Data()) == []


def test_assumed_design_temperature_gives_info():
    """Bez návrhové teploty v projektu (předpoklad −10 °C) je Un / Ucpv pod Uoc jen jedna informace na list."""
    p, _f, _spd, _t = _dc_project(dev_attrs={"un": "1000"}, spd_attrs={"ucpv": "1050"}, t_min="")
    assert not ratings.design_t_min_given(p)
    fs = ratings.un_findings(p, ratings.Data()) + ratings.spd_findings(p, ratings.Data())
    assert [(x.code, x.severity) for x in fs] == [("un_dc", INFO), ("spd_ucpv", INFO)]
    assert all("předpokládané t_min −10 °C" in x.text for x in fs) and "F1 Un 1000 V < Uoc 1083,6 V" in fs[0].text


# ---- integrace -----------------------------------------------------------------------------------------------------
def test_manual_project_without_articles_unchanged():
    """Ruční projekt bez artiklů a bez údajů: žádný nový kód (ani informace)."""
    from envocad.library.store import LibraryStore
    from envocad.library.templates import apply_template
    lib = LibraryStore()
    p = Project(name="Ruční")
    blk = Element("fve.switchboard", 120, 150, attrs={"ref": "R1"})
    p.sheets[0].elements.append(blk)
    sb = p.create_switchboard_sheet(blk)
    apply_template(p, sb, "ac_fve", {"distribution": "terminals"})
    p2, _f, _spd, _t = _dc_project()
    for proj in (p, p2):
        assert not _codes(check_project(proj, lib), *RATING_CODES)


def test_check_project_runs_rating_findings():
    p, _f, _spd, _t = _dc_project(dev_attrs={"un": "1000"}, spd_attrs={"ucpv": "1050"})
    from envocad.library.store import LibraryStore
    codes = {f.code for f in check_project(p, LibraryStore())}
    assert {"un_dc", "spd_ucpv"} <= codes


# ---- generované projekty ---------------------------------------------------------------------------------------
_INV25 = {"p_ac": 25, "u_dc_max": 1100, "u_mppt_min": 200, "u_mppt_max": 1000, "i_mppt_max": 30}


def test_generated_projects_only_legit_dc_voltage_findings(ac_builtin_fn):
    """Generátor: stringy 20 × 49,5 V mají Uoc při −10 °C 1083,6 V – odpojovače EFH 10 DC (1000 V DC) jsou pod ním
    (oprávněný nález, svodič VPU PV má Ucpv 1100 V z poznámky artiklu – v pořádku). Bez návrhové teploty jen
    informace, se zadanou (standard −20 °C) varování (i Ucpv 1100 V svodiče). 18 modulů (výchozí průvodce) i RD bez nálezu."""
    from chain_data import build_project

    from envocad.library.store import LibraryStore
    lib = LibraryStore()
    spec = {"inverters": [{"ref": "T1", **_INV25, "strings": [20, 18]}]}
    fs = _codes(check_project(build_project(spec), lib), *RATING_CODES)
    assert [(f.code, f.severity) for f in fs] == [("un_dc", INFO)] and "FU1.1 Un 1000 V < Uoc 1083,6 V" in fs[0].text
    fs = _codes(check_project(build_project({**spec, "site": {"t_min": -20}}), lib), *RATING_CODES)
    # −20 °C: 1110,3 V je nad 1000 V odpojovače i nad Ucpv 1100 V svodičů VPU PV (v RDC1 i RFVE.DC)
    assert sorted((f.code, f.severity, f.sheet_name.split(" ")[0]) for f in fs) == [
        ("spd_ucpv", WARNING, "RDC1"), ("spd_ucpv", WARNING, "RFVE.DC"), ("un_dc", WARNING, "RFVE.DC")]
    assert all("1110,3 V" in f.text for f in fs)
    for ok in ({"inverters": [{"ref": "T1", **_INV25, "strings": [18, 18]}], "site": {"t_min": -20}},
               {"building": "house", "site": {"t_min": -20},
                "inverters": [{"ref": "T1", "p_ac": 10, "u_dc_max": 1000, "u_mppt_min": 160, "u_mppt_max": 950,
                               "i_mppt_max": 16, "strings": [12, 12]}]}):
        assert not _codes(check_project(build_project(ok), lib), *RATING_CODES)
