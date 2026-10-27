"""Bloky typů střídačů: svorky zálohy a komunikace podle výrobce a řady (model.inverter_io) – bez Qt."""
import pytest

from envocad.library.store import LibraryStore
from envocad.model.checks import check_project
from envocad.model.inverter_io import PROFILES, TERMINALS, inverter_io, io_conductors, parse_io, profile_for
from envocad.model.multipole import default_conductors
from envocad.model.project import Element, Project, Wire, WireEnd, element_symbol


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


@pytest.mark.parametrize(("mfr", "type_", "expected"), [
    ("SolaX", "X3-ULT-20K", "BACKUP BMS RS485 METER DRM DIDO"),
    ("SolaX", "X3-Hybrid-10.0-D", "BACKUP BMS METER RS485 DRM DIDO"),
    ("Huawei", "SUN2000-50KTL-M3", "RS485-1 RS485-2 DI"),
    ("GoodWe", "GW20KT-DT", "RS485 METER DRM"),
    ("GoodWe", "GW10K-ET", "BACKUP BMS METER RS485 RSD"),
    ("Growatt", "MOD 10KTL3-XH", "RS485"),
    ("Sigenergy", "Sigen Hybrid 10.0 TP", "RS485 LAN"),
    ("SolarEdge", "SE10K-RWB48BFN4", "RS485-1 RS485-2 LAN CAN"),
    ("SolarEdge", "SE25K-RW0TEBEN4", "RS485-1 RS485-2 LAN"),
])
def test_profiles_for_used_brands(mfr, type_, expected):
    p = profile_for(mfr, type_)
    assert p is not None and p.io == expected and p.source


def test_profiles_use_known_terminals():
    for p in PROFILES:
        assert set(parse_io(p.io)) <= set(TERMINALS), p.series


def test_io_attribute_overrides_profile():
    assert parse_io("backup, bms;meter BMS") == ["BACKUP", "BMS", "METER"]
    assert inverter_io({"manufacturer": "SolaX", "type": "X3-ULT-20K", "io": "-"}) == []
    assert inverter_io({"manufacturer": "SMA", "type": "STP 25-50", "io": "RS485 LAN"}) == ["RS485", "LAN"]
    assert inverter_io({"manufacturer": "SMA", "type": "STP 25-50"}) == []


def test_symbol_has_terminal_strip_and_io_attribute(lib):
    p = Project()
    t = Element("fve.inverter_hybrid", 100, 100, attrs={"ref": "T1", "manufacturer": "SolaX", "type": "X3-ULT-20K"})
    plain = Element("fve.inverter", 200, 100, attrs={"ref": "T2"})
    p.sheets[0].elements += [t, plain]
    sym = element_symbol(p, t, lib)
    names = [x.name for x in sym.ports]
    assert names[:3] == ["DC1", "DC2", "AC"] and {"BACKUP", "BMS", "METER", "DIDO", "BAT"} <= set(names)
    io_ports = [x for x in sym.ports if x.name in ("BACKUP", "BMS")]
    assert all(x.dir == "E" and x.x == 10 for x in io_ports) and io_ports[0].y - io_ports[1].y == 5
    bat = next(x for x in sym.ports if x.name == "BAT")
    assert bat.y < min(x.y for x in io_ports)            # baterie pod pásem svorek
    assert any(a.key == "io" for a in sym.attributes)
    base = element_symbol(p, plain, lib)                 # bez profilu: značka beze změny, atribut io je
    assert [x.name for x in base.ports] == ["DC1", "DC2", "AC"] and any(a.key == "io" for a in base.attributes)


def test_comm_wire_conductors_and_checks(lib):
    p = Project()
    s = p.sheets[0]
    t = Element("fve.inverter", 100, 100, attrs={"ref": "T1", "manufacturer": "Huawei", "type": "SUN2000-50KTL-M3"})
    m = Element("fve.meter", 160, 80, attrs={"ref": "P1"})
    s.elements += [t, m]
    assert default_conductors(t, "RS485-2", m, "1") == ["A", "B"]
    assert io_conductors("BACKUP") is None and io_conductors("LAN") == ["LAN"]
    s.wires.append(Wire(WireEnd(t.id, "RS485-2"), WireEnd(m.id, "1"), attrs={"ref": "W1"}, conductors=["A", "B"]))
    fs = {(f.code, f.ref): f.text for f in check_project(p, lib, standard_paper="A4")}
    assert ("bad_port", "W1") not in fs
    assert fs[("free_port", "T1")] == "Nezapojené porty: DC1, DC2, AC"     # RS485-1 ani DI se nehlásí


def test_hybrid_always_has_backup():
    """Hybridní střídač: vždy záložní výstup BACKUP (první, když ho profil neuvádí); ruční `io` má přednost."""
    assert inverter_io({"manufacturer": "Deye", "type": "SUN-10K-SG04LP3-EU"}, hybrid=True) == ["BACKUP"]
    assert inverter_io({"manufacturer": "Huawei", "type": "SUN2000-5KTL-M1"}, hybrid=True) ==         ["BACKUP", "RS485-1", "RS485-2", "DI"]
    assert inverter_io({"manufacturer": "SolaX", "type": "X3-ULT-20K"}, hybrid=True).count("BACKUP") == 1
    assert inverter_io({"manufacturer": "Deye", "type": "X", "io": "-"}, hybrid=True) == []
    assert inverter_io({"manufacturer": "Deye", "type": "X", "io": "RS485"}, hybrid=True) == ["RS485"]
    assert inverter_io({"manufacturer": "Deye", "type": "SUN-10K-SG04LP3-EU"}) == []


def test_hybrid_symbol_has_battery_and_backup_ports():
    """Značka hybridního střídače: BAT (baterie) a BACKUP (záloha) i bez profilu řady; síťový střídač BACKUP nemá."""
    from envocad.library.store import LibraryStore
    from envocad.model.checks import check_project
    from envocad.model.project import Element, Project, Sheet, element_symbol
    lib = LibraryStore()
    p = Project()
    s = Sheet(name="JPS")
    p.sheets.append(s)
    th = Element("fve.inverter_hybrid", 0, 0, attrs={"ref": "T1", "manufacturer": "Deye", "type": "SUN-10K"})
    tp = Element("fve.inverter", 100, 0, attrs={"ref": "T2"})
    s.elements += [th, tp]
    names = {pt.name for pt in element_symbol(p, th, lib).ports}
    assert {"BAT", "BACKUP", "AC"} <= names
    assert "BACKUP" not in {pt.name for pt in element_symbol(p, tp, lib).ports}
    free = [f for f in check_project(p, lib, standard_paper="A4") if f.target_id == th.id and f.code == "free_port"]
    assert not any("BACKUP" in f.text for f in free)                  # záloha je nepovinná
