"""Statická kontrola (AST, bez Qt): GUI mění model jen přes `QUndoCommand` (CLAUDE.md, `ui/commands.py`).

V `envocad/ui/` (rekurzivně) mimo `commands.py` se hlásí zápisy do polí objektů modelu (`FIELDS`: attrs,
conductors, terminals, mp_pos, points, port, bridges, wires, elements, meta, sheets, structures, component_id, x, y,
rotation, name):
- přiřazení `X.<pole> = …` (i v n-tici, `+=`, `del`) a `X.<pole>[k] = …`;
- volání slovníkových a seznamových mutátorů `X.<pole>.update/pop/setdefault/clear/popitem/append/extend/insert/
  remove/sort(…)`.
Přiřazení do `self.<pole>` se nehlásí – `self` v `ui/` je vždy objekt GUI (položka scény, dialog), ne model.

Výjimka (živý náhled tažení, nový objekt před `Add*Command`, dočasná změna se snímkem a návratem) se označí
komentářem `# model-write-ok: <důvod>` na stejném řádku jako začátek příkazu se zápisem, nebo v blokovém komentáři
(souvislé řádky jen s komentářem) bezprostředně nad ním.

Známá omezení (pragmatická kontrola, zbytek pokrývají testy undo): nevidí zápisy přes alias (`a = e.attrs;
a["x"] = 1`, `lst = sheet.wires; lst.append(w)`), přes `setattr`, přes jiná jména polí (`n.w`, `sheet.func`) ani
volání metod modelu, které zapisují uvnitř (`sheet.remove_element`)."""
import ast
import re
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "envocad" / "ui"
FIELDS = {"attrs", "conductors", "terminals", "mp_pos", "points", "port", "bridges", "wires", "elements", "meta",
          "sheets", "structures", "component_id", "x", "y", "rotation", "name"}
MUTATORS = {"update", "pop", "setdefault", "clear", "popitem", "append", "extend", "insert", "remove", "sort"}
OK = re.compile(r"#\s*model-write-ok:\s*\S")


def exempt(lines: list[str], lineno: int) -> bool:
    """Má zápis na řádku `lineno` (1 = první) komentář výjimky – na stejném řádku, nebo v souvislém blokovém
    komentáři bezprostředně nad ním?"""
    if OK.search(lines[lineno - 1]):
        return True
    i = lineno - 2
    while i >= 0 and lines[i].lstrip().startswith("#"):
        if OK.search(lines[i]):
            return True
        i -= 1
    return False


def model_writes(src: str) -> list[tuple[str, str, int]]:
    """Zápisy do polí modelu: (funkce, druh zápisu, řádek)."""
    out: list[tuple[str, str, int]] = []

    def visit(node: ast.AST, fn: str, stmt: int) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            line = child.lineno if isinstance(child, ast.stmt) else stmt   # řádek začátku příkazu se zápisem
            check(child, name, line)
            visit(child, name, line)

    def field_of(node: ast.AST) -> str | None:
        """Jméno pole modelu `X.<pole>` (ne `self.<pole>`), jinak None."""
        on_self = isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self"
        return node.attr if isinstance(node, ast.Attribute) and node.attr in FIELDS and not on_self else None

    def check(n: ast.AST, fn: str, line: int) -> None:
        targets: list[ast.AST] = []
        if isinstance(n, (ast.Assign, ast.Delete)):
            targets = list(n.targets)
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
            targets = [n.target]
        while targets:
            t = targets.pop()
            if isinstance(t, (ast.Tuple, ast.List)):
                targets += t.elts
            elif isinstance(t, ast.Starred):
                targets.append(t.value)
            elif field_of(t):
                out.append((fn, f".{field_of(t)} =", line))
            elif isinstance(t, ast.Subscript) and field_of(t.value):
                out.append((fn, f".{field_of(t.value)}[…] =", line))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in MUTATORS \
                and field_of(n.func.value):
            out.append((fn, f".{field_of(n.func.value)}.{n.func.attr}()", line))

    visit(ast.parse(src), "<module>", 0)
    return sorted(out, key=lambda x: x[2])


def test_model_writes_detector():
    samples = {
        "def f(w):\n    w.conductors = []\n": [("f", ".conductors =")],
        "def f(e):\n    e.attrs['ref'] = 'X'\n": [("f", ".attrs[…] =")],
        "def f(e):\n    e.attrs.update({})\n    e.attrs.pop('a', None)\n": [("f", ".attrs.update()"),
                                                                        ("f", ".attrs.pop()")],
        "def f(w):\n    w.a.port = 'X1'\n": [("f", ".port =")],
        "def f(e):\n    e.mp_pos, e.w = None, 0\n": [("f", ".mp_pos =")],
        "def f(s, w):\n    s.wires.append(w)\n    s.elements.insert(0, w)\n": [("f", ".wires.append()"),
                                                                       ("f", ".elements.insert()")],
        "def f(p, s):\n    p.sheets.remove(s)\n    p.structures.sort()\n    s.wires.extend([])\n":
            [("f", ".sheets.remove()"), ("f", ".structures.sort()"), ("f", ".wires.extend()")],
        "def f(p):\n    p.meta['a'] = 1\n": [("f", ".meta[…] =")],
        "def f(s, e):\n    s.bridges = {}\n    e.component_id = None\n    e.rotation = 90\n    s.name = 'A'\n":
            [("f", ".bridges ="), ("f", ".component_id ="), ("f", ".rotation ="), ("f", ".name =")],
        "def f(e):\n    e.x, e.y = 0, 0\n": [("f", ".y ="), ("f", ".x =")],
        "def f(e):\n    g(1,\n      e.attrs.pop('a'))\n": [("f", ".attrs.pop()")],
        "def f(w):\n    del w.terminals['L1']\n": [("f", ".terminals[…] =")],
        "class A:\n    def g(self, it):\n        it.wire.points += [(0, 0)]\n": [("g", ".points =")],
        "def f():\n    g = lambda e: e.attrs.clear()\n": [("f", ".attrs.clear()")],
    }
    for code, expected in samples.items():
        assert [w[:2] for w in model_writes(code)] == expected, code
    # stav objektu GUI (`self.points`), čtení a zápis do jiných polí se nehlásí
    assert model_writes("class A:\n    def g(self):\n        self.points = []\n        self.attrs['a'] = 1\n"
                        "        x = self.e.attrs.get('a')\n        self.e.func = 'x'\n        self.wires.append(1)\n"
                        ) == []
    # řádek víceřádkového příkazu = jeho začátek (komentář výjimky patří nad příkaz)
    assert [w[2] for w in model_writes("def f(e):\n    g(1,\n      e.attrs.pop('a'))\n")] == [2]


def test_exempt_comment_placement():
    """Komentář výjimky platí na stejném řádku nebo v blokovém komentáři těsně nad zápisem – ne přes kód."""
    ok = "# model-write-ok: důvod"
    assert exempt(["e.x = 1  " + ok], 1)
    assert exempt(["    " + ok, "    # pokračování", "    e.x = 1"], 3)
    assert not exempt(["    " + ok, "    y = 2", "    e.x = 1"], 3)
    assert not exempt(["    e.x = 1", "    " + ok], 1)
    assert not exempt(["    " + ok, "", "    e.x = 1"], 3)


def test_no_model_writes_outside_undo_commands():
    """Každý zápis do modelu v `envocad/ui/` mimo `commands.py` má komentář `# model-write-ok: <důvod>`."""
    bad = []
    for path in sorted(UI.rglob("*.py")):
        if path.name == "commands.py":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for fn, what, lineno in model_writes("\n".join(lines)):
            if not exempt(lines, lineno):
                bad.append(f"{path.relative_to(UI)}:{lineno} {fn}: {what} – {lines[lineno - 1].strip()}")
    assert not bad, "Zápis do modelu mimo undo příkaz (chybí `# model-write-ok: <důvod>`):\n" + "\n".join(bad)
