"""Blok rozvaděče bez listu s porty z atributů (`ports_in` / `ports_out`, formát v15) a jištění portů `protect`
(docs/NAVRH_TOPOLOGIE.md, kap. 8 bod 12): blokové schéma bez listů stávajících rozvaděčů a RFVE.AC bez mustru."""
from __future__ import annotations

import functools

from envocad.model.checks import ERROR, INFO, WARNING, check_project
from envocad.model.project import (
    Element,
    Project,
    Wire,
    WireEnd,
    block_port_names,
    block_protect,
    element_symbol,
    is_block_only,
)


@functools.cache
def _lib():
    from envocad.library.store import LibraryStore
    return LibraryStore()


def _project():
    p = Project(name="Bloky")
    s = p.sheets[0]
    hr = Element("fve.switchboard", 100, 150, attrs={"ref": "HR", "desc": "hlavní rozvaděč",
                                                     "ports_in": "XIN", "ports_out": "X1 X2",
                                                     "protect": "X1=63"})
    grid = Element("fve.grid", 200, 150, attrs={"ref": ""})
    load = Element("fve.load", 100, 100, attrs={"ref": "", "desc": "spotřeba"})
    s.elements += [hr, grid, load]
    s.wires.append(Wire(WireEnd(hr.id, "XIN"), WireEnd(grid.id, "1"), conductors=["L1", "L2", "L3", "N", "PE"],
                        attrs={"ref": "W1", "cable": "CYKY-J 5x35", "cross": "35", "length": "10"}))
    s.wires.append(Wire(WireEnd(hr.id, "X2"), WireEnd(load.id, "1"), conductors=["L1"], attrs={"ref": ""}))
    return p, hr


def test_block_port_names_and_protect():
    e = Element("fve.switchboard", 0, 0, attrs={"ports_in": "XIN, X1;X1", "ports_out": "X1 X2  XOUT",
                                                "protect": "X1=63, X2 = 40,5; XOUT=?; =10"})
    assert block_port_names(e) == (["XIN", "X1"], ["X2", "XOUT"])     # duplicity a port v obou seznamech jednou
    assert block_protect(e) == {"X1": 63.0, "X2": 40.5}
    assert block_port_names(Element("fve.switchboard", 0, 0)) == ([], [])


def test_block_without_sheet_has_ports_from_attrs():
    p, hr = _project()
    sym = element_symbol(p, hr, _lib())
    ports = {pt.name: pt for pt in sym.ports}
    assert set(ports) == {"XIN", "X1", "X2"} and not sym.orphan_ports
    assert ports["XIN"].dir == "W" and ports["X1"].dir == "E" and ports["X2"].dir == "E"
    assert all(abs(pt.y / 2.5 - round(pt.y / 2.5)) < 1e-9 for pt in sym.ports)       # porty na mřížce
    assert is_block_only(p, hr)


def test_block_only_no_sheet_warning_and_ports_ok():
    """Blok jen s porty z atributů: žádné `no_sheet` ani `bad_port`, jen INFO `block_only`."""
    p, hr = _project()
    found = check_project(p, _lib(), standard_paper="A4")
    codes = {f.code: f.severity for f in found}
    assert "no_sheet" not in codes and "bad_port" not in codes
    assert codes.get("block_only") == INFO
    del hr.attrs["ports_in"], hr.attrs["ports_out"]
    codes = {(f.code, f.severity) for f in check_project(p, _lib(), standard_paper="A4")}
    assert ("no_sheet", WARNING) in codes and ("bad_port", ERROR) in codes     # bez atributů jako dřív


def test_block_with_sheet_adds_missing_ports():
    """List rozvaděče má přednost; porty z atributů, které list nemá, se přidají za ně."""
    from envocad.library.templates import _feed
    p, hr = _project()
    sb = p.create_switchboard_sheet(hr)
    f = _feed(p, sb, "in", 60, 200, "")
    f.attrs["ref"] = "XIN"
    sym = element_symbol(p, hr, _lib())
    assert [pt.name for pt in sym.ports if pt.dir == "W"] == ["XIN"]
    assert [pt.name for pt in sym.ports if pt.dir == "E"] == ["X1", "X2"]
    assert not is_block_only(p, hr)
