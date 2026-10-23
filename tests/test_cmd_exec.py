"""Příkazový řádek headless: vestavěné příkazy, transakce (ChangeSet, návrat při chybě / Esc), historie UNDO/REDO,
interaktivní průběh pro GUI (Session) – bez Qt."""
import json

import pytest

from envocad.cmd import CommandDef, CommandError, CommandRunner, Journal, Param, SaveOptions, default_registry
from envocad.cmd.runner import ChangeSet, Session, sync_derived
from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, Sheet, Wire, WireEnd, restore_sheets_state, sheets_state


@pytest.fixture(scope="module")
def lib():
    return LibraryStore()


def _project() -> Project:
    p = Project(name="Cmd")
    s = p.sheets[0]
    g = Element("fve.pv_string", 30, 150, attrs={"ref": "G1"})
    q = Element("fve.dc_disconnect", 70, 150, attrs={"ref": "Q1"})
    t = Element("fve.inverter", 120, 150, attrs={"ref": "T1"})
    f = Element("fve.breaker_mcb", 170, 150, attrs={"ref": "F1", "in_": "80 A", "desc": "od T1"})
    s.elements += [g, q, t, f]
    s.wires += [
        Wire(WireEnd(g.id, "DC"), WireEnd(q.id, "1"), attrs={"ref": "W1"}),
        Wire(WireEnd(q.id, "2"), WireEnd(t.id, "DC1"), points=[(95.0, 155.0)]),
        Wire(WireEnd(t.id, "AC"), WireEnd(f.id, "1"), attrs={"ref": "W2"}),
    ]
    p.sheets.append(Sheet(name="Druhý list"))
    return Project.from_dict(p.to_dict())      # jako načtený soubor (souřadnice float)


def _state(p: Project) -> str:
    return json.dumps(p.to_dict(), sort_keys=True, ensure_ascii=False)


def _el(p: Project, ref: str, sheet: int = 0) -> Element:
    return next(e for e in p.sheets[sheet].elements if e.ref == ref)


@pytest.fixture
def run(lib):
    p = _project()
    r = CommandRunner(p, lib, journal=Journal())

    def do(line: str, ok: bool = True):
        res = r.execute(line)
        assert res.ok == ok, (line, res.messages)
        return res
    do.p, do.r = p, r
    return do


# ---- jednotlivé příkazy -------------------------------------------------------------------------------------------
def test_insert_defaults_ref_grid_and_attrs(run):
    p = run.p
    res = run("INSERT fve.breaker_mcb 51,100")
    e = p.sheets[0].elements[-1]
    assert (e.x, e.y, e.rotation, e.ref) == (50.0, 100.0, 0, "F2")      # na mřížce, další volné označení
    assert e.attrs["in_"] == "" and "zaokrouhlen" in res.messages[0]
    assert res.changed_sheets == [p.sheets[0].id] and run.r.ctx.selection == [e.id]
    run("I fve.breaker_mcb 10.5,20 ref=F9 rot=-90 mirror=ano in_=16")
    e = p.sheets[0].elements[-1]
    assert (e.x, e.y, e.rotation, e.mirror, e.ref, e.attrs["in_"]) == (10.0, 20.0, 270, True, "F9", "16")


@pytest.mark.parametrize("line, msg", [
    ("INSERT fve.neni 0,0", "není"),
    ("INSERT fve.breaker_mcb 0,0 nesmysl=1", "nemá atribut nesmysl"),
    ("INSERT fve.breaker_mcb 0,0 ref=T1", "už v projektu"),
    ("INSERT fve.breaker_mcb 0,0 rot=45", "násobek 90"),
    ("INSERT fve.breaker_mcb 0,0 mirror=možná", "ano/ne"),
    ("INSERT fve.breaker_mcb", "chybí Bod vložení"),
    ("INSERT fve.breaker_mcb 0,0 navic", "nadbytečné"),
])
def test_insert_errors_change_nothing(run, line, msg):
    before = _state(run.p)
    res = run(line, ok=False)
    assert msg in res.error and _state(run.p) == before and res.changeset is None


def test_move_relative_points_and_bends(run):
    p = run.p
    t, q = _el(p, "T1"), _el(p, "Q1")
    bend = p.sheets[0].wires[1]
    res = run("MOVE T1 0,0 @10,-4")                     # -4 → mřížka -5
    assert (t.x, t.y) == (130.0, 145.0) and "zaokrouhlen" in res.messages[0]
    assert bend.points == [(95.0, 150.0)]                # lom u posunutého konce jde s ním (svislý vývod W)
    run("M Q1 T1:AC @0,0")                               # ref:port jako bod, nulový posun nic nezmění
    assert (q.x, q.y) == (70.0, 150.0)
    run("SELECT Q1 T1")
    run("MOVE 0,0 5,5")                                  # předvýběr
    assert (q.x, q.y, t.x, t.y) == (75.0, 155.0, 135.0, 150.0)
    assert bend.points == [(100.0, 155.0)]               # oba konce stejně → celý vodič


def test_copy_new_refs_and_inner_wires(run):
    p = run.p
    s = p.sheets[0]
    n_el, n_w = len(s.elements), len(s.wires)
    res = run("COPY Q1 T1 0,0 0,-50")
    new = s.elements[n_el:]
    assert [e.ref for e in new] == ["Q2", "T2"] and [(e.x, e.y) for e in new] == [(70.0, 100.0), (120.0, 100.0)]
    assert len(s.wires) == n_w + 1                       # jen vodič mezi kopírovanými
    w = s.wires[-1]
    assert {w.a.element_id, w.b.element_id} == {e.id for e in new} and w.points == [(95.0, 105.0)]
    assert run.r.ctx.selection == [e.id for e in new] and "Q2, T2" in res.messages[-1]


def test_rotate_mirror_delete(run):
    p = run.p
    run("RO T1")
    assert _el(p, "T1").rotation == 90
    run("ROTATE T1 -180")
    assert _el(p, "T1").rotation == 270
    run("ROTATE T1 45", ok=False)
    run("MI Q1 F1")
    assert _el(p, "Q1").mirror and _el(p, "F1").mirror
    run("E T1")
    s = p.sheets[0]
    assert "T1" not in {e.ref for e in s.elements} and len(s.wires) == 1    # vodiče T1 pryč, zbyl W1
    run("DELETE W1")                                      # vodič podle označení
    assert s.wires == [] and run.r.ctx.selection == []
    run("MOVE 0,0 1,1", ok=False)                         # prázdný výběr


def test_rotate_about_base_point(run):
    """ROTATE jako v ZWCAD: se základním bodem se otáčí i polohy a ruční lomy mezi otáčenými prvky."""
    p, s = run.p, run.p.sheets[0]
    q, t, f = _el(p, "Q1"), _el(p, "T1"), _el(p, "F1")
    bend = next(w for w in s.wires if w.points)
    res = run("RO Q1 T1 F1 120,150 90")
    assert [(e.x, e.y, e.rotation) for e in (q, t, f)] == [(120.0, 100.0, 90), (120.0, 150.0, 90),
                                                           (120.0, 200.0, 90)]
    assert bend.points == [(115.0, 125.0)] and "kolem 120,150" in res.messages[-1]
    run("UNDO")                                           # UNDO obnoví listy ze snímku – prvky znovu podle ref

    def tf():
        return _el(p, "T1"), _el(p, "F1")
    ac = run.r.ctx.port_position("T1", "AC")[2]
    run("RO T1 F1 T1:AC -90")                             # bod jako ref:port; lom Q1–T1 drží (Q1 se neotáčí)
    t, f = tf()
    assert run.r.ctx.port_position("T1", "AC")[2] == ac and t.rotation == f.rotation == 270
    assert next(w for w in p.sheets[0].wires if w.points).points == [(95.0, 155.0)]
    run("UNDO")
    res = run("RO F1 171,151 180")                         # bod mimo mřížku se zaokrouhlí
    t, f = tf()
    assert (f.x, f.y) == (170.0, 150.0) and any("zaokrouhlen" in m for m in res.messages)
    run("UNDO")
    run("RO T1 F1 180")                                    # bez bodu každý kolem svého počátku
    t, f = tf()
    assert (t.x, t.y, f.x, f.y) == (120.0, 150.0, 170.0, 150.0) and t.rotation == f.rotation == 180
    s2 = run.r.start("RO F1")                              # GUI: číslo ve výzvě bodu = úhel
    s2.send("270")
    t, f = tf()
    assert s2.done and s2.result.ok and f.rotation == 90 and (f.x, f.y) == (170.0, 150.0)


def test_set_attrs_elements_and_wires(run):
    p = run.p
    run('SET F1 in_=16 desc="Hlavní jistič"')
    f = _el(p, "F1")
    assert f.attrs["in_"] == "16" and f.attrs["desc"] == "Hlavní jistič"
    res = run("ATTR in_=16")
    assert "beze změny" in res.messages[0] and res.changeset is None
    run("SET W2 cross=10")
    assert p.sheets[0].wires[2].attrs["cross"] == "10"
    assert "nemá atribut" in run("SET F1 nesmysl=1", ok=False).error
    assert "jednomu" in run("SET Q1 F1 ref=X", ok=False).error
    assert "už v projektu" in run("SET F1 ref=Q1", ok=False).error
    assert "chybí" in run("SET F1", ok=False).error


def test_set_ref_renames_followups(run):
    """SET ref=: navázané automatické texty („od T1“ → „od T7“) jako přejmenování v GUI (`rename_followups`)."""
    p = run.p
    run("SET T1 ref=T7")
    assert _el(p, "T7") and _el(p, "F1").attrs["desc"] == "od T7"
    run("UNDO")
    assert _el(p, "F1").attrs["desc"] == "od T1" and _el(p, "T1")


def test_wire_ports_points_and_bends(run, lib):
    p = run.p
    s = p.sheets[0]
    run("INSERT fve.breaker_mcb 200,100 ref=F5")
    n = len(s.wires)
    run("WIRE F1:2 F5:1")
    w = s.wires[n]
    f1, f5 = _el(p, "F1"), _el(p, "F5")
    assert (w.a.element_id, w.a.port, w.b.element_id, w.b.port) == (f1.id, "2", f5.id, "1")
    assert w.attrs["ref"] == "W3" and w.conductors and w.points == []
    # body: start = port do 2,5 mm (177.5,150 = F1:2), lomy na mřížce, cíl = port F5:2 (207.5,100)
    run("L 178,151 190,150 190,101 207.5,100 ref=W9 cross=4")
    w = s.wires[-1]
    assert (w.a.port, w.b.element_id, w.b.port) == ("2", f5.id, "2")
    assert w.points == [(190.0, 150.0), (190.0, 100.0)] and w.attrs["cross"] == "4" and w.attrs["ref"] == "W9"
    assert "musí končit" in run("WIRE F1:2 300,300", ok=False).error
    assert "není port" in run("WIRE 300,300 F1:1", ok=False).error
    assert "stejný port" in run("WIRE F1:2 F1:2", ok=False).error
    assert "nemá port" in run("WIRE F1:9 F5:1", ok=False).error


def test_select_forms(run):
    p = run.p
    s = p.sheets[0]
    r = run.r
    run("SELECT Q* T1")
    assert r.ctx.selection == [_el(p, "Q1").id, _el(p, "T1").id]
    run("SELECT all")
    assert len(r.ctx.selection) == len(s.elements) + len(s.wires)
    run("VYBER none")
    assert r.ctx.selection == []
    run("SELECT W 0,0 100,200")                            # okno: G1, Q1 celé uvnitř + vodič mezi nimi
    assert set(r.ctx.selection) == {_el(p, "G1").id, _el(p, "Q1").id, s.wires[0].id}
    run("SELECT symbol=fve.breaker*")
    assert r.ctx.selection == [_el(p, "F1").id]
    run("SELECT F* in_=80*")
    assert r.ctx.selection == [_el(p, "F1").id]
    assert "nic neodpovídá" in run("SELECT symbol=fve.inverter in_=1", ok=False).error
    assert "není" in run("SELECT X9", ok=False).error
    assert r.ctx.selection == [_el(p, "F1").id]            # chyba výběr nemění


def test_sheet_switch(run):
    p, r = run.p, run.r
    res = run("SHEET")
    assert res.messages == ["* 1: Blokové schéma", "  2: Druhý list"]
    run("SELECT F1")
    run("LIST 2")
    assert r.ctx.sheet is p.sheets[1] and r.ctx.selection == []
    run("INSERT fve.breaker_mcb 10,10")
    assert p.sheets[1].elements[-1].ref == "F2"
    run('SHEET "blokové"')
    assert r.ctx.sheet is p.sheets[0]
    run("SHEET 9", ok=False)
    run("SHEET xyz", ok=False)


# ---- transakce a historie -----------------------------------------------------------------------------------------
def test_undo_redo_restore_exact(run):
    p = run.p
    states = [_state(p)]
    for line in ["INSERT fve.breaker_mcb 50,50", "MOVE F1 0,0 10,0", "RO Q1", "MI T1", "SET F1 in_=6",
                 "WIRE Q1:2 F2:1", "COPY G1 0,0 0,-20", "E T1"]:
        run(line)
        states.append(_state(p))
    assert len(run.r.journal.done) == 8
    run("UNDO 3")
    assert _state(p) == states[-4]
    run("U")
    assert _state(p) == states[-5]
    run("REDO 2")
    assert _state(p) == states[-3]
    run("UNDO 99")
    assert _state(p) == states[0]
    assert "Není co" in run("UNDO").messages[0]
    run("ZNOVU 99")
    assert _state(p) == states[-1]
    run("UNDO")
    run("SELECT G1")                                    # bez změny modelu – historie zůstane
    run("REDO")
    assert _state(p) == states[-1]
    run("UNDO")
    run("RO G1")                                        # nová změna zahodí redo
    assert "Není co" in run("REDO").messages[0]


def test_changeset_only_changed_sheets(run):
    p = run.p
    before = sheets_state(p)
    res = run("MOVE F1 0,0 10,0")
    cs = res.changeset
    assert cs.label == "Posunout" and cs.changed_sheets == [p.sheets[0].id]
    assert set(cs.before["sheets"]) == {p.sheets[0].id} == set(cs.after["sheets"])
    after = _state(p)
    restore_sheets_state(p, cs.before)
    assert cs.before["sheets"] == {p.sheets[0].id: before["sheets"][p.sheets[0].id]}
    restore_sheets_state(p, cs.after)
    assert _state(p) == after
    assert ChangeSet.between("x", before, before) is None


def _registry_with(*cmds):
    reg = default_registry(user_aliases=False)
    for c in cmds:
        reg.add(c)
    return reg


def test_error_mid_command_rolls_back(lib):
    """Příkaz, který model změní a pak spadne: transakce vrátí stav „před“ (i výběr a aktivní list)."""
    def broken(ctx):
        ctx.sheet.elements[0].x = 999
        ctx.selection = ["x"]
        ctx.sheet = ctx.project.sheets[1]
        yield Param("p", "point", "Bod:")
        raise CommandError("schválně")

    p = _project()
    r = CommandRunner(p, lib, _registry_with(CommandDef("broken", "Rozbitý", run=broken)), journal=Journal())
    before = _state(p)
    res = r.execute("BROKEN 1,1")
    assert not res.ok and res.error == "schválně" and _state(p) == before
    assert r.ctx.selection == [] and r.ctx.sheet is p.sheets[0] and r.journal.done == []
    res = r.execute("BROKEN")                              # chybějící argument po změně → také návrat
    assert "chybí Bod" in res.error and _state(p) == before


def test_unexpected_exception_is_reported(lib):
    def boom(ctx):
        ctx.sheet.elements[0].x = 1
        raise RuntimeError("bum")
    p = _project()
    r = CommandRunner(p, lib, _registry_with(CommandDef("boom", "B", run=boom)))
    before = _state(p)
    res = r.execute("boom")
    assert res.error == "bum" and _state(p) == before


def test_unknown_gui_only_and_security(run):
    assert "Neznámý příkaz „XY“" in run("XY 1", ok=False).error
    assert "jen v GUI" in run("ZOOM", ok=False).error
    assert "Neznámý" in run("__import__('os').system('echo x')", ok=False).error
    assert "uvozovky" in run('SET desc="x', ok=False).error


def test_interactive_session_for_gui(run):
    """GUI: příkaz bez argumentů se doptá výzvami; klik dodá bod, Esc vrátí stav."""
    p, r = run.p, run.r
    t = _el(p, "T1")
    s = r.start("MOVE T1")
    assert isinstance(s, Session) and not s.done and s.prompt.kind == "point" and s.prompt.prompt == "Základní bod:"
    s.send("0,0")
    assert s.prompt.base == (0.0, 0.0) and s.prompt.prompt == "Cílový bod:"
    s.send_value((10.0, 0.0))                              # klik
    assert s.done and s.result.ok and (t.x, t.y) == (130.0, 150.0)
    assert s.result.changeset is not None and r.journal.done[-1] is s.result.changeset
    # předvýběr platí bez výzvy, Enter na volitelné výzvě = výchozí hodnota
    r.execute("SELECT T1")
    s = r.start("RO")
    assert s.prompt.kind == "point" and s.prompt.optional          # základní bod – Enter = počátek prvku
    s.send("")
    assert s.prompt.kind == "number" and s.prompt.optional
    s.send("")
    assert s.done and t.rotation == 90 and (t.x, t.y) == (130.0, 150.0)
    # Esc uprostřed: nic nezůstane
    before = _state(p)
    s = r.start("WIRE T1:AC")
    assert s.prompt.allow_point
    s.send("300,300")                                      # lom
    res = s.cancel()
    assert not res.ok and "zrušen" in res.error and _state(p) == before
    # port kliknutím (bod u portu)
    s = r.start("WIRE")
    q = _el(p, "Q1")
    s.send_value((q.x + 7.5, q.y + 1))
    s.send("F1:2")
    s.send("")                                             # atributy vodiče – Enter
    assert s.done and s.result.ok and p.sheets[0].wires[-1].a.element_id == q.id
    # chyba při rozboru vstupu ukončí příkaz a vrátí stav
    before = _state(p)
    s = r.start("MOVE F1")
    s.send("1,,2")
    assert s.done and not s.result.ok and _state(p) == before


def test_checks_output_and_data(run):
    res = run("F7")
    assert res.data and {"severity", "sheet", "ref", "text", "code"} <= set(res.data[0])
    assert res.messages[-1].startswith("Kontrola:") and res.changeset is None


def test_save_policy(run, tmp_path):
    r = run.r
    assert "není povoleno" in run(f"SAVE {tmp_path / 'a.ecp'}", ok=False).error
    r.save = SaveOptions(target=tmp_path / "out.ecp", allow=True)
    run("SAVE")
    assert Project.load(tmp_path / "out.ecp").to_dict()["sheets"][0]["elements"]
    other = tmp_path / "jiny.ecp"
    other.write_text("{}", encoding="utf-8")
    assert "existuje" in run(f"SAVE {other}", ok=False).error
    assert "čekám soubor .ecp" in run(f"SAVE {tmp_path / 'profil.txt'}", ok=False).error
    (tmp_path / "slozka.ecp").mkdir()
    assert "složka" in run(f'SAVE "{tmp_path / "slozka.ecp"}"', ok=False).error
    assert not (tmp_path / "profil.txt").exists()
    run(f"SAVE {tmp_path / 'novy.ecp'}")
    r.save = SaveOptions(target=tmp_path / "out.ecp", allow=False, dry_run=True)
    assert "dry-run" in run("SAVE").messages[0]


def test_save_relative_to_base_dir(lib, tmp_path):
    p = _project()
    r = CommandRunner(p, lib, base_dir=tmp_path, save=SaveOptions(target=None, allow=True))
    assert r.execute("ULOZ vystup.ecp").ok and (tmp_path / "vystup.ecp").is_file()
    assert "chybí cesta" in r.execute("SAVE").error


def test_complete_symbols_and_keys(run):
    reg, ctx = run.r.registry, run.r.ctx
    assert "INSERT fve.breaker_mcb" in reg.complete("INSERT fve.break", ctx)
    run("SELECT F1")
    assert "SET in_=" in reg.complete("SET in", ctx)
    assert reg.complete("SHEET dru", ctx) == ['SHEET "Druhý list"']


def test_on_change_and_messages(lib):
    p = _project()
    msgs, changes = [], []
    r = CommandRunner(p, lib, on_message=msgs.append, on_change=changes.append)
    r.execute("RO T1")
    r.execute("SELECT F1")
    assert msgs == ["Otočeno: 1 prvek o 90°", "Vybráno 1: F1"] and changes == [p]
    with pytest.raises(CommandError):
        r.undo()                                           # bez Journal (GUI má vlastní undo)


def test_sync_derived_cables(lib):
    p = _project()
    sync_derived(p)
    assert {c.ref for c in p.cables} >= {"W1", "W2"}
