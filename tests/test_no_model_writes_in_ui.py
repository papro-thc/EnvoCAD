"""Statická kontrola (AST, bez Qt): GUI mění model jen přes `QUndoCommand` (CLAUDE.md, `ui/commands.py`).

V `envocad/ui/` mimo `commands.py` se hlásí zápisy do polí objektů modelu:
- přiřazení `X.attrs = …`, `X.conductors = …`, `X.terminals = …`, `X.mp_pos = …`, `X.points = …`, `X.port = …`
  (i v n-tici, `+=`, `del`) a `X.attrs[k] = …` / `X.conductors[i] = …`;
- volání `X.attrs.update/pop/setdefault/clear/popitem(…)` (totéž u ostatních polí).
Přiřazení do `self.<pole>` se nehlásí – `self` v `ui/` je vždy objekt GUI (položka scény, dialog), ne model.

Výjimka (živý náhled tažení, nový objekt před `Add*Command`, dočasná změna se snímkem a návratem) se označí
komentářem `# model-write-ok: <důvod>` na stejném řádku nebo nejvýš tři řádky nad zápisem. Pragmatická kontrola:
nehlídá zápisy přes jiná jména polí (`e.x`, `sheet.name`) ani přes `setattr` – ty pokrývají testy undo."""
import ast
import re
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "envocad" / "ui"
FIELDS = {"attrs", "conductors", "terminals", "mp_pos", "points", "port"}
MUTATORS = {"update", "pop", "setdefault", "clear", "popitem"}
OK = re.compile(r"#\s*model-write-ok:\s*\S")
NEAR = 3      # komentář výjimky smí být až tři řádky nad zápisem (víceřádkový blok nového objektu)



def model_writes(src: str) -> list[tuple[str, str, int]]:
    """Zápisy do polí modelu: (funkce, druh zápisu, řádek)."""
    out: list[tuple[str, str, int]] = []

    def visit(node: ast.AST, fn: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            check(child, name)
            visit(child, name)

    def field_of(node: ast.AST) -> str | None:
        """Jméno pole modelu `X.<pole>` (ne `self.<pole>`), jinak None."""
        on_self = isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self"
        return node.attr if isinstance(node, ast.Attribute) and node.attr in FIELDS and not on_self else None

    def check(n: ast.AST, fn: str) -> None:
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
                out.append((fn, f".{field_of(t)} =", t.lineno))
            elif isinstance(t, ast.Subscript) and field_of(t.value):
                out.append((fn, f".{field_of(t.value)}[…] =", t.lineno))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in MUTATORS \
                and field_of(n.func.value):
            out.append((fn, f".{field_of(n.func.value)}.{n.func.attr}()", n.lineno))

    visit(ast.parse(src), "<module>")
    return sorted(out, key=lambda x: x[2])


def test_model_writes_detector():
    samples = {
        "def f(w):\n    w.conductors = []\n": [("f", ".conductors =")],
        "def f(e):\n    e.attrs['ref'] = 'X'\n": [("f", ".attrs[…] =")],
        "def f(e):\n    e.attrs.update({})\n    e.attrs.pop('a', None)\n": [("f", ".attrs.update()"),
                                                                        ("f", ".attrs.pop()")],
        "def f(w):\n    w.a.port = 'X1'\n": [("f", ".port =")],
        "def f(e):\n    e.mp_pos, e.x = None, 0\n": [("f", ".mp_pos =")],
        "def f(w):\n    del w.terminals['L1']\n": [("f", ".terminals[…] =")],
        "class A:\n    def g(self, it):\n        it.wire.points += [(0, 0)]\n": [("g", ".points =")],
        "def f():\n    g = lambda e: e.attrs.clear()\n": [("f", ".attrs.clear()")],
    }
    for code, expected in samples.items():
        assert [w[:2] for w in model_writes(code)] == expected, code
    # stav objektu GUI (`self.points`), čtení a zápis do jiných polí se nehlásí
    assert model_writes("class A:\n    def g(self):\n        self.points = []\n        self.attrs['a'] = 1\n"
                        "        x = self.e.attrs.get('a')\n        self.e.name = 'x'\n") == []


def test_no_model_writes_outside_undo_commands():
    """Každý zápis do modelu v `envocad/ui/` mimo `commands.py` má komentář `# model-write-ok: <důvod>`."""
    bad = []
    for path in sorted(UI.glob("*.py")):
        if path.name == "commands.py":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for fn, what, lineno in model_writes("\n".join(lines)):
            near = lines[max(0, lineno - 1 - NEAR):lineno]
            if not any(OK.search(ln) for ln in near):
                bad.append(f"{path.name}:{lineno} {fn}: {what} – {lines[lineno - 1].strip()}")
    assert not bad, "Zápis do modelu mimo undo příkaz (chybí `# model-write-ok: <důvod>`):\n" + "\n".join(bad)
