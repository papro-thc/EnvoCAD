"""Generátor projektu FVE podle topologie řetězce (bez Qt). Návrh `docs/design/topologie_f1_f2.md`, kap. 1.3;
přehled modulů v `docs/ARCHITECTURE.md`. Veřejné API `build_project` (re-export i v `envocad.generate`)."""

__all__ = ["build_project"]


def __getattr__(name: str):
    # líně – podmoduly importují `envocad.generator.context` a balíček nesmí při importu tahat celé sestavení
    if name == "build_project":
        from envocad.generator.build import build_project
        return build_project
    raise AttributeError(name)


def __dir__() -> list[str]:
    # líný `build_project` (není v globals, dokud se nenačte) – doplňování v IDE / `dir()` ho uvidí
    return sorted({*globals(), *__all__})
