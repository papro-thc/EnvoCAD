"""Charakterizační testy výkazů (`envocad/export/reports.py`): zachycují SOUČASNÝ výstup funkcí `bom`, `cables`,
`terminals`, `labels`, `cable_plan`, `wiring_list` a `production_wiring_list` na malých projektech z generátoru
(`tests/generate_snapshot.py`) a na ručně složených projektech pro větve, které generátor netrefí.

Netestují oborovou správnost – když se výstup úmyslně změní, test se upraví. Podezřelé chování je označené
`xfail(strict=True)` (viz konec souboru). Projekty se staví jednou na modul; výkazy je nemění (kromě idempotentního
`sync_cables`, to hlídá `test_reports_are_repeatable`)."""
from __future__ import annotations

import pytest
from generate_snapshot import build_case
from test_reports import _proj  # malý rozvaděč AC z šablony (ruční svorky, můstky)

from envocad.export import reports
from envocad.library.store import LibraryStore
from envocad.model.project import Element, Project, Sheet, Wire, WireEnd

HEADS = {
    "bom": ["Pol.", "Přístroj", "Typ", "Výrobce", "Parametry", "Ks", "Označení"],
    "cables": ["Označení", "Odkud", "Kam", "Typ kabelu", "Průřez [mm²]", "Žíly", "Délka [m]", "Trasa", "Rozvaděč", "List"],
    "terminals": ["Svorkovnice", "Svorka", "Žíla", "Kabel", "Připojeno na", "Můstek", "Popis", "List"],
    "labels": ["Štítek", "Popis", "List"],
    "cable_plan": ["Kabel", "Typ", "Průřez [mm²]", "Žíla", "Č.", "Barva", "Odkud", "Kam", "Stínění", "Délka [m]", "List"],
    "wiring_list": ["List", "Kabel / vodič", "Žíla", "Barva", "Průřez [mm²]", "Odkud", "Kam", "Poznámka"],
    "production_wiring_list": ["Č.", "Označení", "Žíla", "Odkud", "Kam", "Průřez [mm²]", "Barva", "Typ vodiče", "Délka [mm]",
                               "Koncovka odkud", "Koncovka kam", "Návlečka odkud", "Návlečka kam", "Poznámka", "List"],
}
FUNCS = list(HEADS)
BLOCK = "Blokové schéma"
RDC1 = "RDC1 – DC rozvaděč po trase T1"
RFVE = "RFVE – rozvaděč FVE (DC + AC)"
RE = "RE – elektroměrový rozvaděč"


def run(fn: str, project, lib, sheet=None, **kw):
    return getattr(reports, fn)(project, lib, sheet, **kw)


# výrobní seznam vynechává sloupce prázdné ve všech řádcích (Označení, návlečky) – ostatní hlavičky jsou pevné
PRODUCTION_OPTIONAL = {"Označení", "Návlečka odkud", "Návlečka kam"}


def assert_head(fn: str, head: list[str]) -> None:
    if fn == "production_wiring_list":
        assert head == [h for h in HEADS[fn] if h in head] and set(HEADS[fn]) - set(head) <= PRODUCTION_OPTIONAL
    else:
        assert head == HEADS[fn]


# ---------------------------------------------------------------- fixtures (rozsah modulu)

@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return LibraryStore(tmp_path_factory.mktemp("lib") / "lib.db")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Projekty z generátoru; `_isolated_home` z conftestu je funkční (běží až po modulových fixtures), proto si
    modul izoluje ENVOCAD_HOME sám – generátor nesmí číst nastavení ani knihovnu uživatele."""
    from envocad.library import topologies
    mp = pytest.MonkeyPatch()
    mp.setenv("ENVOCAD_HOME", str(tmp_path_factory.mktemp("envohome_mod")))
    topologies.clear_cache()
    try:
        names = ("house_code_battery", "default_1inv", "apartment_optimizer", "with_component")
        yield {n: build_case(n) for n in names}
    finally:
        mp.undo()
        topologies.clear_cache()


@pytest.fixture(scope="module")
def house(built):
    """Rodinný dům, hybridní střídač + baterie, 5 listů (JPS + 4 rozvaděče)."""
    return built["house_code_battery"]


def sheet_of(project, prefix: str) -> Sheet:
    return next(s for s in project.sheets if s.name.startswith(prefix))


# ---------------------------------------------------------------- tvar výstupu

@pytest.mark.parametrize("case", ["house_code_battery", "default_1inv", "apartment_optimizer", "with_component"])
@pytest.mark.parametrize("fn", FUNCS)
def test_head_and_row_shape(built, lib, case, fn):
    head, rows = run(fn, built[case], lib)
    assert_head(fn, head)
    assert rows and all(len(r) == len(head) for r in rows)


@pytest.mark.parametrize("fn", FUNCS)
def test_sheet_variant_shape(house, lib, fn):
    for s in house.sheets:
        head, rows = run(fn, house, lib, s)
        assert_head(fn, head)
        assert all(len(r) == len(head) for r in rows)


def test_row_counts_whole_project(built, lib):
    counts = {n: {f: len(run(f, p, lib)[1]) for f in FUNCS} for n, p in built.items()}
    assert counts == {
        "house_code_battery": {"bom": 19, "cables": 12, "terminals": 79, "labels": 49, "cable_plan": 35,
                               "wiring_list": 171, "production_wiring_list": 111},
        "default_1inv": {"bom": 14, "cables": 12, "terminals": 73, "labels": 51, "cable_plan": 29,
                         "wiring_list": 144, "production_wiring_list": 95},
        "apartment_optimizer": {"bom": 16, "cables": 13, "terminals": 78, "labels": 56, "cable_plan": 34,
                                "wiring_list": 157, "production_wiring_list": 103},
        "with_component": {"bom": 16, "cables": 15, "terminals": 85, "labels": 61, "cable_plan": 35,
                           "wiring_list": 170, "production_wiring_list": 115},
    }


def test_row_counts_per_sheet_house(house, lib):
    got = {s.name: {f: len(run(f, house, lib, s)[1]) for f in FUNCS} for s in house.sheets}
    assert got[BLOCK] == {"bom": 4, "cables": 12, "terminals": 0, "labels": 9, "cable_plan": 35, "wiring_list": 60,
                          "production_wiring_list": 0}
    assert got[RDC1] == {"bom": 3, "cables": 0, "terminals": 12, "labels": 7, "cable_plan": 0, "wiring_list": 10,
                         "production_wiring_list": 10}
    assert got[RFVE]["bom"] == 10 and got[RFVE]["terminals"] == 32 and got[RFVE]["production_wiring_list"] == 59
    assert got[RE] == {"bom": 4, "cables": 0, "terminals": 10, "labels": 5, "cable_plan": 0, "wiring_list": 15,
                       "production_wiring_list": 15}


def test_reports_are_repeatable(house, lib):
    """`cable_plan`/`wiring_list` volají `sync_cables` – opakované volání nesmí výstup měnit (sdílený projekt modulu)."""
    first = {f: run(f, house, lib) for f in FUNCS}
    second = {f: run(f, house, lib) for f in FUNCS}
    assert first == second


# ---------------------------------------------------------------- bom

def test_bom_whole_project_house(house, lib):
    _, rows = reports.bom(house, lib)
    assert [r[0] for r in rows] == list(range(1, 20))                 # Pol. průběžně od 1
    names = [r[1] for r in rows]
    assert names == sorted(names)                                    # řazení podle názvu přístroje
    assert rows[0] == [1, "Bateriové úložiště", "BYD HVS 10.2", "", "10 kWh", 1, "G3"]
    assert [2, "Elektroměr", "", "", "", 1, "+RE-P1"] in rows
    assert [3, "FV modul", "", "", "450 Wp", 32, "G1 (16), G2 (16)"] in rows
    assert [7, "Hybridní střídač", "", "", "25 kW", 1, "T1"] in rows
    assert rows[-1][:6] == [19, "Řadová svorka", "", "", "", 72]


def test_bom_merges_equal_items_and_sorts_refs_naturally(house, lib):
    _, rows = reports.bom(house, lib)
    by = {(r[1], r[4]): r for r in rows}
    # dva stejné jističe se slučují; označení řazená přirozeně (F10 až za F8)
    assert by[("Jistič", "50 A, B, 3p")][5:] == [2, "+RD-Q4, +RFVE-F3"]
    assert by[("Pojistkový odpínač", "25 A, gPV, 2p")][2:] == ["EFH 10 DC 2p", "ETI", "25 A, gPV, 2p", 2,
                                                              "+RFVE-F8, +RFVE-F10"]
    # stejný přístroj s jinými parametry = jiná položka, řazeno podle parametrů přirozeně
    jistice = [r[4] for r in rows if r[1] == "Jistič"]
    assert jistice == ["50 A, B, 3p", "50 A, B, 4p", "B, 3p"]
    spd = [r for r in rows if r[1].startswith("Svodič")]
    assert [(r[4], r[5]) for r in spd] == [("3p, T1+T2 DC, 1000 V DC V", 4), ("4p, T1+T2", 1)]


def test_bom_terminal_strips_summed_per_strip(house, lib):
    _, rows = reports.bom(house, lib)
    term = rows[-1]
    assert term[5] == 72
    assert term[6].startswith("+RD-X1 (5), +RD-X2 (5), +RD-XB1 (5)")
    assert "+RDC1-X1 (2)" in term[6] and term[6].endswith("+RFVE-XPE (1)")
    # součet kusů v závorkách = Ks
    assert sum(int(t.rsplit("(", 1)[1].rstrip(")")) for t in term[6].split(", ")) == 72


def test_bom_single_sheet_variants(house, lib):
    _, rows = reports.bom(house, lib, sheet_of(house, "RDC1"))
    assert rows == [
        [1, "PE/N můstek", "", "", "", 1, "+RDC1-X5"],
        [2, "Svodič přepětí (SPD)", "VPU PV I+II 3 1000", "Weidmüller", "3p, T1+T2 DC, 1000 V DC V", 2,
         "+RDC1-F1, +RDC1-F2"],
        [3, "Řadová svorka", "", "", "", 8, "+RDC1-X1 (2), +RDC1-X2 (2), +RDC1-X3 (2), +RDC1-X4 (2)"],
    ]
    _, rows = reports.bom(house, lib, sheet_of(house, "RE"))
    assert rows == [
        [1, "Elektroměr", "", "", "", 1, "+RE-P1"],
        [2, "Hlavní vypínač", "", "", "4p", 1, "+RE-Q6"],
        [3, "Jistič", "", "", "B, 3p", 1, "+RE-Q5"],
        [4, "Řadová svorka", "", "", "", 10, "+RE-XIN (5), +RE-XOUT (5)"],
    ]
    _, rows = reports.bom(house, lib, sheet_of(house, "Blokové"))
    assert [r[1:] for r in rows] == [
        ["Bateriové úložiště", "BYD HVS 10.2", "", "10 kWh", 1, "G3"],
        ["FV modul", "", "", "450 Wp", 32, "G1 (16), G2 (16)"],
        ["Hlavní domovní skříň (HDS)", "", "", "gG, 3p", 1, "HDS"],
        ["Hybridní střídač", "", "", "25 kW", 1, "T1"],
    ]


def test_bom_sheet_quantities_add_up_to_project(house, lib):
    """Součet Ks přes listy = Ks celého projektu pro položky bez můstků (stejný klíč položky)."""
    total: dict[tuple, int] = {}
    for s in house.sheets:
        for r in reports.bom(house, lib, s)[1]:
            total[(r[1], r[2], r[3], r[4])] = total.get((r[1], r[2], r[3], r[4]), 0) + r[5]
    whole = {(r[1], r[2], r[3], r[4]): r[5] for r in reports.bom(house, lib)[1]}
    assert total == whole


def test_bom_optimizer_and_component_cases(built, lib):
    _, rows = reports.bom(built["apartment_optimizer"], lib)
    assert [9, "Optimizér", "S440-1GM4MRM", "SolarEdge", "", 58, "G1 (20), G2 (20), G3 (18)"] in rows
    assert [2, "FV modul", "", "", "450 Wp", 58, "G1 (20), G2 (20), G3 (18)"] in rows   # moduly vedle optimizérů
    assert [13, "Střídač", "", "", "25 kW", 2, "T1, T2"] in rows
    _, rows = reports.bom(built["with_component"], lib)
    assert [12, "Střídač", "STP 25-50", "SMA", "25 kW", 1, "T1"] in rows               # typ a výrobce z artiklu
    assert [15, "Síťová ochrana", "", "", "", 1, "+RFVE.AC-F3"] in rows
    assert [2, "FV modul", "", "", "450 Wp", 76, "G1 (20), G2 (20), G3 (18), G4 (18)"] in rows


# ---------------------------------------------------------------- cables

def test_cables_house(house, lib):
    _, rows = reports.cables(house, lib)
    assert [r[0] for r in rows] == [f"W{i}" for i in range(1, 13)]      # přirozené řazení (W10 za W9)
    assert rows[0] == ["W1", "G1:DC", "+RDC1-X1", "H1Z2Z2-K 1x6", "6", "L+ L-", "30", "", "RDC1:X1 /2.A2", BLOCK]
    assert rows[6] == ["W7", "T1:AC", "+RFVE-X1", "CYKY-J 5x16", "16", "L1 L2 L3 N PE", "30", "",
                       "RFVE:X1 /3.B4", BLOCK]
    assert rows[7][8] == ""                                             # W8 baterie: bez odkazu na rozvaděč
    assert rows[8][1:3] == ["+RFVE-XOUT", "+RD-X1"] and rows[8][8] == "RFVE:XOUT /3.C4, RD:X1 /4.A5"
    assert rows[11][6] == ""                                            # W12 bez zadané délky
    assert {r[9] for r in rows} == {BLOCK}


def test_cables_only_wires_with_ref_or_cable(house, lib):
    # vodiče rozvaděčů nemají ref ani kabel → v seznamu kabelů nejsou; na JPS jich je víc než kabelů
    assert sum(len(s.wires) for s in house.sheets) > 12
    assert len(reports.cables(house, lib, sheet_of(house, "RFVE"))[1]) == 0
    assert len(reports.cables(house, lib, sheet_of(house, "Blokové"))[1]) == 12


# ---------------------------------------------------------------- terminals

def test_terminals_house_sheet_rd(house, lib):
    _, rows = reports.terminals(house, lib)
    assert rows[:3] == [
        ["X1", "1", "L1", "", "Q4:2", "", "k RFVE (FVE)", "RD – domovní rozvaděč"],
        ["X1", "2", "L2", "", "Q4:4", "", "k RFVE (FVE)", "RD – domovní rozvaděč"],
        ["X1", "3", "L3", "", "Q4:6", "", "k RFVE (FVE)", "RD – domovní rozvaděč"],
    ]
    assert len(rows) == 79 and {r[0] for r in rows} == {"X1", "X2", "X3", "X4", "X5", "XB1", "XE1", "XIN", "XOUT", "XPE"}
    assert all(r[5] == "" for r in rows)                                # generátor můstky nezadává


def test_terminals_sheet_re_and_dc_multi_row_terminal(house, lib):
    _, rows = reports.terminals(house, lib, sheet_of(house, "RE"))
    assert [r[:3] + r[4:7] for r in rows[:5]] == [
        ["XIN", "1", "L1", "Q5:1", "", "od HDS"], ["XIN", "2", "L2", "Q5:3", "", "od HDS"],
        ["XIN", "3", "L3", "Q5:5", "", "od HDS"], ["XIN", "4", "N", "Q5:N", "", "od HDS"],
        ["XIN", "5", "PE", "Q5:PE", "", "od HDS"]]
    assert [r[4] for r in rows[5:]] == ["Q6:2", "Q6:4", "Q6:6", "Q6:8", "Q6:PE"]
    _, rows = reports.terminals(house, lib, sheet_of(house, "RDC1"))
    # jedna svorka může mít víc řádků (víc připojení): X1:1 jde na X3:1 i na F1:L+
    assert [r[4] for r in rows[:4]] == ["X3:1", "F1:L+", "X3:2", "F1:L-"]
    assert [r[1] for r in rows[:4]] == ["1", "1", "2", "2"]
    # PE svorkovnice: tři+ spojení na jednu svorku, řazeno stabilně
    _, xpe = reports.terminals(house, lib, sheet_of(house, "RFVE"))
    assert [r[4] for r in xpe if r[0] == "XPE"] == ["F4:PE", "1PE", "F7:PE", "F9:PE"]


def test_terminals_jps_sheet_is_empty(house, lib):
    assert reports.terminals(house, lib, sheet_of(house, "Blokové"))[1] == []


# ---------------------------------------------------------------- labels

def test_labels_house(house, lib):
    _, rows = reports.labels(house, lib)
    assert len(rows) == 49
    assert rows[:9] == [
        ["G1", "FV string", BLOCK], ["G2", "FV string", BLOCK], ["G3", "Bateriové úložiště", BLOCK],
        ["HDS", "hlavní domovní skříň", BLOCK], ["+RD", "domovní rozvaděč", BLOCK],
        ["+RDC1", "DC rozvaděč po trase T1", BLOCK], ["+RE", "elektroměrový rozvaděč", BLOCK],
        ["+RFVE", "rozvaděč FVE (DC + AC)", BLOCK], ["T1", "Hybridní střídač", BLOCK]]
    tags = [r[0] for r in rows]
    assert tags.index("+RFVE-F9") < tags.index("+RFVE-F10")             # přirozené řazení
    assert ["+RFVE-F3", "Jistič 50 A", RFVE] in rows                    # popis z In, když chybí `desc`
    assert ["+RE-Q5", "hlavní jistič před elektroměrem", RE] in rows    # `desc` má přednost
    assert ["+RFVE-F8", "Pojistkový odpínač 25 A", RFVE] in rows


def test_labels_one_label_per_terminal_strip(house, lib):
    """Skupiny svorek jedné svorkovnice mají jediný štítek „Přívod / vývod“."""
    _, rows = reports.labels(house, lib, sheet_of(house, "RE"))
    assert [r[0] for r in rows] == ["+RE-P1", "+RE-Q5", "+RE-Q6", "+RE-XIN", "+RE-XOUT"]
    assert [r[1] for r in rows[3:]] == ["Přívod / vývod", "Přívod / vývod"]


# ---------------------------------------------------------------- cable_plan

def test_cable_plan_house(house, lib):
    _, rows = reports.cable_plan(house, lib)
    assert len(rows) == 35
    assert rows[0] == ["W1", "H1Z2Z2-K 1x6", "6", "L+", "1", "červená", "G1:DC", "+RDC1-X1", "", "30", BLOCK]
    assert rows[1] == ["W1", "H1Z2Z2-K 1x6", "6", "L-", "2", "černá", "G1:DC", "+RDC1-X1", "", "30", BLOCK]
    assert rows[-1] == ["W12", "CYKY-J 5x16", "16", "PE", "5", "zelenožlutá", "+RFVE-XB1", "+RD-XE1", "", "", BLOCK]
    # řádek na žílu, čísla žil 1..n; PE kabel s jedinou žílou
    w10 = [r for r in rows if r[0] == "W10"]
    assert [r[3:6] for r in w10] == [["PE", "1", "zelenožlutá"]]
    w9 = [r for r in rows if r[0] == "W9"]
    assert [r[3] for r in w9] == ["L1", "L2", "L3", "N", "PE"] and [r[4] for r in w9] == ["1", "2", "3", "4", "5"]
    assert [r[0] for r in rows] == sorted((r[0] for r in rows), key=lambda x: int(x[1:]))


def test_cable_plan_skips_switchboard_sheets(house, lib):
    assert reports.cable_plan(house, lib, sheet_of(house, "RE"))[1] == []
    assert len(reports.cable_plan(house, lib, sheet_of(house, "Blokové"))[1]) == 35


# ---------------------------------------------------------------- wiring_list

def test_wiring_list_jps_and_switchboard(house, lib):
    _, rows = reports.wiring_list(house, lib)
    assert len(rows) == 171
    assert rows[0] == [BLOCK, "W1", "L+", "červená", "6", "G1:DC", "+RDC1-X1", "H1Z2Z2-K 1x6"]
    # vnitřní vodiče rozvaděčů: označení „vodič“, bez průřezu, sloučené nespínané N/PE
    _, re_rows = reports.wiring_list(house, lib, sheet_of(house, "RE"))
    assert len(re_rows) == 15
    assert re_rows[3] == [RE, "vodič", "N", "modrá", "", "+RE-XIN:4", "+RE-Q6:7", "vede kolem Q5, P1"]
    assert re_rows[4] == [RE, "vodič", "PE", "zelenožlutá", "", "+RE-XIN:5", "+RE-XOUT:5", "vede kolem Q5, P1, Q6"]
    assert re_rows[0] == [RE, "vodič", "L1", "hnědá", "", "+RE-Q5:2", "+RE-P1:1", ""]
    assert sorted({r[0] for r in rows}) == sorted([BLOCK, "RD – domovní rozvaděč", RDC1, RE, RFVE])


def test_wiring_list_sorted_by_sheet_then_ref(house, lib):
    _, rows = reports.wiring_list(house, lib)
    assert rows[0][0] == BLOCK                                         # „Blokové schéma“ před „RD – …“
    jps = [r[1] for r in rows if r[0] == BLOCK]
    assert jps[:2] == ["W1", "W1"] and jps.index("W9") < jps.index("W10")


# ---------------------------------------------------------------- production_wiring_list

def test_production_wiring_list_sheet_re(house, lib):
    head, rows = reports.production_wiring_list(house, lib, sheet_of(house, "RE"))
    # sloupec Označení je prázdný všude → vynechán; návlečky (adresné) zůstávají
    assert head == [h for h in HEADS["production_wiring_list"] if h != "Označení"]
    assert len(rows) == 15 and [r[0] for r in rows] == list(range(1, 16))
    assert rows[0] == [1, "L1", "+RE-Q5:1", "+RE-XIN:1", 1.5, "hnědá", "H07V-K", 1100, "dutinka 1,5/8 černá",
                       "dutinka 1,5/8 černá", "XIN:1", "Q5:1", "průřez výchozí – ověřit; délka odhadem – XIN neumístěn", RE]
    # neumístěný elektroměr → délka prázdná (ne 0)
    assert rows[1][6] == "H07V-K" and rows[1][7] == "" and rows[1][12] == "průřez výchozí – ověřit; neumístěno: P1"
    assert rows[14][1:3] == ["PE", "+RE-XIN:5"] and rows[14][7] == 250


def test_production_wiring_list_whole_project_and_numbers_as_numbers(house, lib):
    head, rows = reports.production_wiring_list(house, lib)
    assert len(head) == 14 and len(rows) == 111
    assert [r[0] for r in rows] == list(range(1, 112))                  # průběžné číslování přes rozvaděče
    assert {r[-1] for r in rows} == {"RD – domovní rozvaděč", RDC1, RE, RFVE}
    assert all(r[4] == "" or isinstance(r[4], (int, float)) for r in rows)   # průřez je číslo (u SPD prázdný)
    spd = [r for r in rows if r[4] == ""]
    assert [r[0] for r in spd] == [75, 76, 77, 78] and all("SPD – průřez určí projektant" in r[12] for r in spd)
    assert all(r[7] == "" or isinstance(r[7], (int, float)) for r in rows)
    assert rows[0][1:4] == ["L1", "+RD-Q3:1", "+RD-XIN:1"]
    assert rows[-1][1:4] == ["PE", "+RFVE-Q2:3/PE", "+RFVE-XB1:5"]
    assert rows[-1][4:7] == [10, "zelenožlutá", "H07V-K"]


def test_production_wiring_list_jps_sheet_has_no_rows(house, lib):
    head, rows = reports.production_wiring_list(house, lib, sheet_of(house, "Blokové"))
    assert rows == [] and len(head) == 12                               # prázdné sloupce se vynechají i bez řádků


def test_production_wiring_list_base_param_and_markers(house, lib):
    sheet = sheet_of(house, "RE")
    head, rows = reports.production_wiring_list(house, lib, sheet, base={"wire_type": "H07Z-K", "wire_marking": "none"})
    assert "Návlečka odkud" not in head and "Návlečka kam" not in head   # bez návleček → sloupce zmizí
    assert {r[head.index("Typ vodiče")] for r in rows} == {"H07Z-K"}
    base_head, _ = reports.production_wiring_list(house, lib, sheet, base={})
    assert "Návlečka odkud" in base_head


def test_wiring_base_survives_broken_settings(monkeypatch):
    from envocad import settings
    for exc in (OSError("x"), ValueError("x"), KeyError("standard"), TypeError("x")):
        def boom(exc=exc):
            raise exc
        monkeypatch.setattr(settings, "load_settings", boom)
        assert reports.wiring_base() == {}
    monkeypatch.setattr(settings, "load_settings", lambda: {"standard": {"wiring": ["není", "slovník"]}})
    assert reports.wiring_base() == {}
    monkeypatch.setattr(settings, "load_settings", lambda: {"standard": {"wiring": {"wire_type": "X"}}})
    assert reports.wiring_base() == {"wire_type": "X"}


# ---------------------------------------------------------------- ručně složené projekty (větve BOM a přerušení)

def _el(sheet: Sheet, symbol: str, **attrs) -> Element:
    e = Element(symbol, 0, 0, attrs=attrs)
    sheet.elements.append(e)
    return e


@pytest.fixture()
def manual():
    p = Project(name="Ruční")
    s = p.sheets[0]
    _el(s, "fve.pv_string", ref="G1", type="JKM450", n_modules="20", p_module="450", manufacturer="Jinko",
        optimizer="S440", n_optimizers="20", opt_manufacturer="SolarEdge")
    _el(s, "fve.pv_string", ref="G2", type="JKM450", n_modules="x", p_module="450")          # nečíselný počet
    _el(s, "fve.pv_string", ref="G3", type="JKM450", n_modules="10,5", p_module="450", manufacturer="Jinko")
    _el(s, "fve.battery", ref="B1", type="HVS", slave_type="HVM", n_modules="3", manufacturer="BYD", bms="BMU")
    _el(s, "fve.battery", ref="B2", type="PWR", n_modules="2", manufacturer="Pylon")
    _el(s, "fve.battery", ref="B3", type="LUNA", bms="BMS-1", manufacturer="Huawei", e_kwh="5")
    _el(s, "x.unknown", ref="U1", type="T")
    return p


def test_bom_pv_string_modules_and_optimizers(manual, lib):
    _, rows = reports.bom(manual, lib)
    assert [r for r in rows if r[1] == "FV modul"] == [[5, "FV modul", "JKM450", "Jinko", "450 Wp", 30, "G1 (20), G3 (10)"]]
    assert [r for r in rows if r[1] == "Optimizér"] == [[7, "Optimizér", "S440", "SolarEdge", "", 20, "G1 (20)"]]
    # G2 s nečíselným počtem modulů se do výkazu nedostane (ValueError → 0)
    assert not any("G2" in r[6] for r in rows)


def test_bom_battery_tower_slave_and_bms(manual, lib):
    _, rows = reports.bom(manual, lib)
    bat = [r for r in rows if r[1] in ("Bateriové úložiště", "Řídicí jednotka baterie")]
    assert bat == [
        [1, "Bateriové úložiště", "HVS", "BYD", "", 1, "B1 (1)"],                      # věž s přídavným modulem: master 1 ks
        [2, "Bateriové úložiště", "PWR", "Pylon", "", 2, "B2 (2)"],                    # věž bez slave: n kusů stejného typu
        [3, "Bateriové úložiště", "LUNA", "Huawei", "5 kWh", 1, "B3"],                 # jeden modul
        [4, "Bateriové úložiště", "HVM", "BYD", "přídavný modul", 2, "B1 (2)"],
        [8, "Řídicí jednotka baterie", "BMS-1", "Huawei", "", 1, "B3"],               # jednomodulová baterie + BMS
        [9, "Řídicí jednotka baterie", "BMU", "BYD", "", 1, "B1 (1)"],                 # BMS věže
    ]


def test_bom_and_labels_unknown_symbol_uses_placeholder(manual, lib):
    _, rows = reports.bom(manual, lib)
    assert [6, "Neznámá značka x.unknown", "T", "", "", 1, "U1"] in rows
    _, lab = reports.labels(manual, lib)
    assert ["U1", "Neznámá značka x.unknown", BLOCK] in lab


def test_labels_skip_interrupt_points_and_elements_without_ref(manual, lib):
    s = manual.sheets[0]
    _el(s, "fve.interrupt", ref="P1")
    _el(s, "fve.pv_string", type="JKM450")                                # bez označení
    _, lab = reports.labels(manual, lib)
    assert [r[0] for r in lab] == ["B1", "B2", "B3", "G1", "G2", "G3", "U1"]


@pytest.fixture()
def interrupted():
    """G1 → přerušení P1 (list 1, kabel W1) … P1 (list 2, prázdný vodič) → T1: kabel vede přes dvě dvojice bodů."""
    p = Project(name="Přerušení")
    s1 = p.sheets[0]
    s2 = Sheet(name="List 2")
    p.sheets.append(s2)
    g1 = _el(s1, "fve.pv_string", ref="G1", type="JKM450", n_modules="20")
    i1 = _el(s1, "fve.interrupt", ref="P1")
    i2 = _el(s2, "fve.interrupt", ref="P1")
    t1 = _el(s2, "fve.inverter", ref="T1")
    s1.wires.append(Wire(WireEnd(g1.id, "DC"), WireEnd(i1.id, "1"),
                         attrs={"ref": "W1", "cable": "CYKY", "cross": "4", "route": "žlab"}, conductors=["L+", "L-"]))
    s2.wires.append(Wire(WireEnd(i2.id, "1"), WireEnd(t1.id, "DC1"), conductors=["L+", "L-"]))
    return p


def test_cables_through_interrupt_resolves_far_end(interrupted, lib):
    _, rows = reports.cables(interrupted, lib)
    # druhý konec není „P1:1“, ale skutečný cíl za protějším přerušovacím bodem; úsek pokračování řádek nemá
    assert rows == [["W1", "G1:DC", "T1:DC1", "CYKY", "4", "L+ L-", "", "žlab", "", BLOCK]]


def test_cable_plan_and_wiring_list_through_interrupt(interrupted, lib):
    _, plan = reports.cable_plan(interrupted, lib)
    assert plan == [
        ["W1", "CYKY", "4", "L+", "1", "červená", "G1:DC", "T1:DC1", "", "", BLOCK],
        ["W1", "CYKY", "4", "L-", "2", "černá", "G1:DC", "T1:DC1", "", "", BLOCK],
    ]
    _, wl = reports.wiring_list(interrupted, lib)
    # pokračování kabelu (List 2) se přeskakuje – žádné řádky navíc
    assert wl == [[BLOCK, "W1", "L+", "červená", "4", "G1:DC", "T1:DC1", "CYKY"],
                  [BLOCK, "W1", "L-", "černá", "4", "G1:DC", "T1:DC1", "CYKY"]]


def test_bom_bridges_and_terminals_bridge_column(lib):
    p, s = _proj()
    p.set_bridges("X1", [["1", "2", "3"], ["4", "9"]], s)                 # skupina 4-9 míří na neexistující svorku 9
    _, rows = reports.bom(p, lib, s)
    assert [r for r in rows if r[1] == "Můstek svorek"] == [[3, "Můstek svorek", "", "", "3 pólů", 1, "+R1-X1:1-2-3"]]
    _, rows_all = reports.bom(p, lib)                                     # celý projekt – stejný výsledek
    assert [r[1:] for r in rows_all] == [r[1:] for r in rows]
    _, term = reports.terminals(p, lib, s)
    by = {(r[0], r[1], r[2]): r for r in term}
    assert by[("X1", "3", "L3")][5] == "1-2-3"                            # odvozená svorka X1:3 je v můstku
    assert by[("X1", "4", "N")][5] == "4-9"                               # můstek se vykáže i s neexistující svorkou
    assert by[("X1", "5", "PE")][5] == ""


def test_terminals_manual_terminals_and_cable_column(lib):
    p, s = _proj()
    _, rows = reports.terminals(p, lib, s)
    x1 = [r for r in rows if r[0] == "X1"]
    assert [r[:5] for r in x1] == [
        ["X1", "1", "L1", "W1", "Q1:1"], ["X1", "2", "L2", "W1", "Q1:3"], ["X1", "3", "L3", "W1", "Q1:5"],
        ["X1", "4", "N", "W1", "Q1:7"], ["X1", "5", "PE", "W1", "Q1:PE"]]
    assert x1[0][6:] == ["od střídače", "R1 – AC"]


def test_terminals_without_conductors_uses_other_end_port(lib):
    """Vodič bez žil na svorku: jeden řádek bez čísla žíly, druhý konec jako prvek:port."""
    p = Project(name="Bez žil")
    s = Sheet(name="R", kind="switchboard", loc="R")
    p.sheets.append(s)
    x = _el(s, "sb.terminal_block", ref="X1", terminal="7")
    f = _el(s, "sb.terminal_block", ref="X2")
    s.wires.append(Wire(WireEnd(x.id, "1"), WireEnd(f.id, "1"), attrs={"cable": "CYKY"}))
    _, rows = reports.terminals(p, lib, s)
    assert [r[0] for r in rows] == ["X1", "X2"]
    assert all(r[2] == "" for r in rows)                                   # bez žíly
    assert rows[0][3] == "CYKY" and rows[0][4].endswith("X2:1")


# ---------------------------------------------------------------- ostatní výkazy (pomocné pro sedm hlavních)

def test_device_list_house(house, lib):
    head, rows = reports.device_list(house, lib)
    assert head == ["Označení", "Přístroj", "Typ", "Výrobce", "Parametry", "Kontakty", "Moduly", "Řada", "Pozice", "List"]
    assert [r[0] for r in rows][:12] == ["G1", "G2", "G3", "HDS", "T1", "+RD-1", "+RD-Q3", "+RD-Q4", "+RDC1-F1",
                                        "+RDC1-F2", "+RDC1-X5", "+RE-P1"]
    assert len(rows) == 25 and all(len(r) == 10 for r in rows)
    assert rows[2] == ["G3", "Bateriové úložiště", "BYD HVS 10.2", "", "10 kWh", "", "", "", "", BLOCK]
    # přístroj v rozvaděči: moduly z rozměru, řada a pozice z rozložení
    assert ["+RE-Q5", "Jistič", "", "", "B, 3p", "", 3.0, 1, 0.0, RE] in rows
    assert ["+RE-Q6", "Hlavní vypínač", "", "", "4p", "", 4.0, 1, 3.0, RE] in rows
    _, only_re = reports.device_list(house, lib, sheet_of(house, "RE"))
    assert [r[0] for r in only_re] == ["+RE-P1", "+RE-Q5", "+RE-Q6"]


def test_device_list_and_labels_merge_terminal_strip_groups(lib):
    """Skupiny svorek jedné svorkovnice (stejné `ref`) = jeden řádek přístrojů a jeden štítek."""
    p = Project(name="Svorky")
    s = Sheet(name="R", kind="switchboard", loc="R")
    p.sheets.append(s)
    for ref, num in (("X1", "1 2 3"), ("X1", "4 5"), ("X2", "1")):
        _el(s, "sb.terminal_block", ref=ref, terminal=num, type="UK 4", manufacturer="Phoenix")
    _, rows = reports.device_list(p, lib, s)
    assert [(r[0], r[2], r[3], r[4]) for r in rows] == [
        ("+R-X1", "UK 4", "Phoenix", "2 svorky, 2 skupiny"), ("+R-X2", "UK 4", "Phoenix", "1 svorka")]
    _, lab = reports.labels(p, lib, s)
    assert [r[0] for r in lab] == ["+R-X1", "+R-X2"]                       # jeden štítek na svorkovnici
    _, bom = reports.bom(p, lib, s)
    assert [r[1:6] for r in bom] == [["Řadová svorka", "UK 4", "Phoenix", "", 3]]
    assert bom[0][6] == "+R-X1 (2), +R-X2 (1)"          # bez vodičů se skupina počítá za 1 svorku (bere se 1. číslo)


def test_cable_material_house(house, lib):
    head, rows = reports.cable_material(house, lib)
    assert head == ["Pol.", "Druh", "Typ", "Průřez [mm²]", "Barva", "Ks", "Délka [m]", "Bez délky", "Označení"]
    assert [r[0] for r in rows] == list(range(1, 33))
    assert rows[:5] == [
        [1, "Kabel", "CYA 16", "16", "", 1, 5.0, 0, "W10"],
        [2, "Kabel", "CYKY-J 5x10", "10", "", 1, 20.0, 0, "W9"],
        [3, "Kabel", "CYKY-J 5x16", "16", "", 3, 60.0, 1, "W7, W11, W12"],       # W12 bez délky → „Bez délky“ 1
        [4, "Kabel", "H1Z2Z2-K 1x25", "25", "", 1, 5.0, 0, "W8"],
        [5, "Kabel", "H1Z2Z2-K 1x6", "6", "", 6, 110.0, 0, "W1, W2, W3, W4, W5, W6"]]
    assert [r[1] for r in rows] == ["Kabel"] * 5 + ["Vodič rozvaděče"] * 22 + ["Dutinka"] * 5
    assert rows[27] == [28, "Dutinka", "dutinka 1,5/8 černá", "", "", 70, "", "", ""]
    assert rows[31][2] == "dvojitá dutinka 2×6/12 žlutá" and rows[31][5] == 16
    _, re_rows = reports.cable_material(house, lib, sheet_of(house, "RE"))
    assert re_rows[0] == [1, "Vodič rozvaděče", "H07V-K", "1.5", "hnědá", 4, 2.1, 2, ""]
    assert len(re_rows) == 6


def test_marking_house(house, lib):
    head, rows = reports.marking(house, lib)
    assert head == ["Druh", "Text", "Druhý řádek", "Umístění", "Vodič / kabel", "Žíla", "List"]
    assert len(rows) == 246 and {r[0] for r in rows} == {"Štítek kabelu", "Návlečka"}
    assert rows[:2] == [["Štítek kabelu", "W1", "→ +RDC1-X1", "G1:DC", "W1", "", BLOCK],
                        ["Štítek kabelu", "W1", "→ G1:DC", "+RDC1-X1", "W1", "", BLOCK]]
    assert sum(1 for r in rows if r[0] == "Štítek kabelu") == 24               # 12 kabelů × 2 konce
    assert rows[-1] == ["Návlečka", "Q2:3/PE", "", "XB1:5", "111", "PE", RFVE]
    _, re_rows = reports.marking(house, lib, sheet_of(house, "RE"))
    assert len(re_rows) == 30 and re_rows[0] == ["Návlečka", "XIN:1", "", "Q5:1", "1", "L1", RE]


def test_potentials_and_terminal_plan_house(house, lib):
    head, rows = reports.potentials(house, lib)
    assert head == ["Potenciál", "Žíly", "Spojů", "Vodiče", "Prvky", "Stav", "List"]
    assert len(rows) == 76 and rows[0][:3] == ["1L1", "L1", 43] and rows[1][:3] == ["1L1", "L1", 11]
    assert all(r[5] == "OK" for r in rows)
    _, re_rows = reports.potentials(house, lib, sheet_of(house, "RE"))
    assert len(re_rows) == 20 and re_rows[0] == ["L1", "L1", 2, "", "+RE-P1:1, +RE-Q5:2", "OK", RE]
    head, plan = reports.terminal_plan_report(house, lib)
    assert head == ["Svorkovnice", "Svorka", "Žíla", "Vnější připojení", "Vnější kabel", "Můstek", "Vnitřní připojení",
                    "Vnitřní kabel", "List"]
    assert len(plan) == 73
    assert plan[0] == ["X1", "1", "L+", "G1:DC", "W1 H1Z2Z2-K 1x6 6", "", "F1:L+", "", RDC1]
    assert plan[-1] == ["XOUT", "5", "PE", "RD:XIN", "", "", "Q6:PE", "", RE]
    assert reports.terminal_plan_report(house, lib, sheet_of(house, "Blokové"))[1] == []


def test_calculations_and_dso_house(house, built, lib):
    head, rows = reports.calculations(house, lib)
    assert head == ["Část", "Prvek", "Hodnoty", "Mez / porovnání", "Výsledek"] and len(rows) == 15
    assert rows[0] == ["String", "G1", "16 modulů, Uoc(-10 °C) = 866.8 V, Umpp(70 °C) = 583.3 V, 1,25·Isc = 17.4 A",
                       "T1: Umax 1100.0 V, MPPT 200.0–1000.0 V, Imax 30.0 A", "OK"]
    assert rows[2] == ["Kabel", "W1", "I = 17.38 A, S = 6.0 mm², L = 30.0 m, uložení E, dc",
                       "Iz = 56.1 A, ΔU = 3.91 V (0.59 %)", "OK"]
    assert rows[4][3] == "Iz = 56.1 A, In RFVE:F8 = 25 A"
    assert reports.calculations(house, lib, sheet_of(house, "RE"))[1] == []      # výpočty patří na list JPS
    # pevné napětí (optimizéry): vlastní text hodnot i mezí
    opt = reports.calculations(built["apartment_optimizer"], lib)[1][0]
    assert opt[:4] == ["String", "G1", "20 modulů, 20 optimizérů, pevné U – V, P stringu 9000 / 11250 W",
                       "T1: optimizérů 16–50, P stringu ≤ 11250 W"]
    assert "chybí údaj pevné napětí stringu střídače" in opt[4]
    head, dso = reports.dso_report(house, lib)
    assert head == ["Údaj", "Hodnota"] and len(dso) == 11 and dso[4][0] == "Instalovaný výkon FV (DC)"
    assert dso[4][1] == "14.4 kWp (32 modulů, 2 stringů)"
    assert reports.dso_report(Project(name="Prázdný"), lib)[1] == []            # bez elektrárny žádné řádky


def test_production_subtitle(house, built):
    lines = reports.production_subtitle(house, sheet_of(house, "RE"), base={})
    assert len(lines) == 3 and lines[0].startswith("Parametry: typ H07V-K, přídavek na konec 100 mm")
    assert lines[1].startswith("Svorky:") and lines[2] == "Č. je pořadí v seznamu, po změně projektu se může změnit."
    # list JPS: žádný rozvaděč → výchozí parametry z `base`
    jps = reports.production_subtitle(house, sheet_of(house, "Blokové"), base={"wire_type": "H07Z-K"})
    assert jps[0].startswith("Parametry: typ H07Z-K,") and len(jps) == 3
    # rozvaděče s různými parametry → řádek za každou skupinu s výčtem listů
    import copy
    q = copy.deepcopy(built["apartment_optimizer"])
    q.sheets[1].layout.params["wire_type"] = "H07Z-K"
    sub = reports.production_subtitle(q, None, base={})
    assert sub[0].startswith("Parametry (RDC1 – DC rozvaděč po trase T1): typ H07Z-K,")
    assert sub[1].startswith("Parametry (RDC2 – DC rozvaděč po trase T2, RFVE.DC")
    assert len(sub) == 4


def test_small_formatting_helpers():
    assert reports._g(None) == "–" and reports._g(750.0) == "750" and reports._g(1.5) == "1.5"
    assert reports._modules(1) == "1 modul" and reports._modules(3) == "3 moduly" and reports._modules(5) == "5 modulů"
    assert reports._number(None) == "" and reports._number(25.0) == 25 and reports._number(1.5) == 1.5
    assert reports._metres("12,5 m") == 12.5 and reports._metres("25") == 25.0
    assert reports._metres("") is None and reports._metres("abc") is None and reports._metres("0") is None
    assert reports._int("3,9") == 3 and reports._int("x") == 0 and reports._int(None) == 0
    assert reports._ref_key("+RDC1-X1") < reports._ref_key("+RDC1-X10") < reports._ref_key("+RDC2-X1")
    assert reports._terminal_word(1) == "svorka" and reports._terminal_word(3) == "svorky" \
        and reports._terminal_word(5) == "svorek"


# ---------------------------------------------------------------- podezřelé chování (xfail)

@pytest.mark.xfail(strict=True, reason="reports.py:313-315 – ruční svorka bez názvu svorkovnice („7“ místo „X1:7“) se "
                                       "parsuje jako strip=„7“, num=„“, takže sloupec Svorka dostane pořadí žíly (1), ne 7")
def test_xfail_terminals_bare_manual_terminal_number(lib):
    p, s = _proj()
    s.wires[0].terminals = {"L1": {"a": "7"}}
    _, rows = reports.terminals(p, lib, s)
    l1 = next(r for r in rows if r[0] == "X1" and r[2] == "L1")
    assert l1[1] == "7"


@pytest.mark.xfail(strict=True, reason="reports.py:313-318 – bez prefixu svorkovnice se můstek hledá pod názvem „1“ "
                                       "(číslo svorky), ne „X1“, takže ruční svorka 1 z můstku 1-2-3 má prázdný sloupec "
                                       "Můstek, zatímco odvozená svorka 3 ho má")
def test_xfail_terminals_bridge_for_manual_bare_terminal(lib):
    p, s = _proj()
    p.set_bridges("X1", [["1", "2", "3"]], s)
    _, rows = reports.terminals(p, lib, s)
    by = {r[2]: r for r in rows if r[0] == "X1"}
    assert by["L1"][5] == by["L3"][5] == "1-2-3"
