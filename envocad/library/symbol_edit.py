"""Úpravy portů a atributů existující značky (editor symbolů, fáze 1) – čistá logika bez Qt.

Pracuje se vždy s pracovní kopií (`editable_copy`); kresba (primitiva) se needituje. Chyby uživatele jsou
`SymbolEditError` s českou hláškou. Uložení (`save_user_symbol`) vestavěnou ani souborovou značku nepřepíše, uloží kopii.
"""
from __future__ import annotations

import copy
import json
import math
import os

from envocad.model.grid import snap
from envocad.model.symbol import DIRS, Attribute, Port, Symbol, SymbolVersionError


class SymbolEditError(ValueError):
    """Nepovolená úprava značky; text je určený uživateli (česky)."""


def free_symbol_id(library, sid: str) -> str:
    """První volné ID ve tvaru `<sid>_2`, `<sid>_3`…"""
    n = 2
    while library.has_symbol(f"{sid}_{n}"):
        n += 1
    return f"{sid}_{n}"


def editable_copy(sym: Symbol) -> Symbol:
    """Hluboká kopie značky (porty, atributy, primitiva, vícepól, třídy označení); originál se nemění."""
    return Symbol.from_dict(copy.deepcopy(sym.to_dict()))


def _find_port(sym: Symbol, name: str) -> Port:
    for p in sym.ports:
        if p.name == name:
            return p
    raise SymbolEditError(f"Port „{name}“ na značce není.")


def _check_direction(direction: str) -> None:
    if direction not in DIRS:
        raise SymbolEditError(f"Neplatný směr portu „{direction}“ (povoleno N, E, S, W).")


def _check_finite(*values: float) -> None:
    if not all(math.isfinite(v) for v in values):
        raise SymbolEditError("Souřadnice musí být konečné číslo.")


def add_port(sym: Symbol, name: str, x: float, y: float, direction: str = "E") -> Port:
    name = (name or "").strip()
    if not name:
        raise SymbolEditError("Název portu nesmí být prázdný.")
    if any(p.name == name for p in sym.ports):
        raise SymbolEditError(f"Port „{name}“ už na značce je.")
    _check_direction(direction)
    _check_finite(x, y)
    port = Port(name, snap(x), snap(y), direction)
    sym.ports.append(port)
    return port


def move_port(sym: Symbol, name: str, x: float, y: float) -> Port:
    port = _find_port(sym, name)
    _check_finite(x, y)
    port.x, port.y = snap(x), snap(y)
    return port


def update_port(sym: Symbol, name: str, *, new_name: str | None = None, direction: str | None = None) -> Port:
    port = _find_port(sym, name)
    if new_name is not None:
        new_name = new_name.strip()
        if not new_name:
            raise SymbolEditError("Název portu nesmí být prázdný.")
        if new_name != name and any(p.name == new_name for p in sym.ports):
            raise SymbolEditError(f"Port „{new_name}“ už na značce je.")
    if direction is not None:
        _check_direction(direction)
    if new_name is not None:
        port.name = new_name
    if direction is not None:
        port.dir = direction
    return port


def remove_port(sym: Symbol, name: str) -> None:
    sym.ports.remove(_find_port(sym, name))


def set_attribute(sym: Symbol, key: str, *, label: str | None = None, default: str | None = None,
                  show: bool | None = None) -> Attribute:
    key = (key or "").strip()
    if not key:
        raise SymbolEditError("Klíč atributu nesmí být prázdný.")
    attr = next((a for a in sym.attributes if a.key == key), None)
    if attr is None:
        attr = Attribute(key, key, "", False)
        sym.attributes.append(attr)
    if label is not None:
        attr.label = label
    if default is not None:
        attr.default = default
    if show is not None:
        attr.show = bool(show)
    return attr


def remove_attribute(sym: Symbol, key: str) -> None:
    if key == "ref":
        raise SymbolEditError("Atribut „ref“ je povinný a nejde smazat.")
    attr = next((a for a in sym.attributes if a.key == key), None)
    if attr is None:
        raise SymbolEditError(f"Atribut „{key}“ na značce není.")
    sym.attributes.remove(attr)


def check(sym: Symbol) -> list[str]:
    """Problémy značky (prázdný seznam = lze uložit): `Symbol.validate()` + povinný `ref`, duplicitní klíče
    atributů a prázdné názvy portů."""
    issues = list(sym.validate())
    keys = [a.key for a in sym.attributes]
    if "ref" not in keys:
        issues.append("chybí povinný atribut „ref“")
    dups = sorted({k for k in keys if keys.count(k) > 1})
    if dups:
        issues.append("duplicitní klíče atributů: " + ", ".join(dups))
    if any(not p.name.strip() for p in sym.ports):
        issues.append("port s prázdným názvem")
    return issues


def removed_ports(old: Symbol, new: Symbol) -> list[str]:
    """Seřazená jména portů, které `old` má a `new` ne (smazané i přejmenované)."""
    have = {p.name for p in new.ports}
    return sorted({p.name for p in old.ports} - have)


def _id_in_library_files(store, sid: str) -> bool:
    from envocad.library.store import NON_SYMBOL_DIRS, _rel, symbol_sources
    for root, _tag in symbol_sources(store.path):
        try:
            files = sorted(root.rglob("*.json"))
        except OSError:
            continue
        for f in files:
            try:
                if NON_SYMBOL_DIRS & set(_rel(f, root).split(os.sep)):
                    continue
                if Symbol.from_json(f).id == sid:
                    return True
            except SymbolVersionError:
                # soubor z novější verze: synchronizace ho přeskočila, ale id mu patří – přepsat ho nelze
                try:
                    if json.loads(f.read_text(encoding="utf-8-sig")).get("id") == sid:
                        return True
                except Exception:  # noqa: BLE001, S112
                    continue
            except Exception:  # noqa: BLE001, S112 – vadný soubor se přeskočí jako při synchronizaci
                continue
    return False


def is_read_only(store, sid: str) -> bool:
    """Značku nelze přepsat pod jejím id: je vestavěná, nebo pochází ze souboru ve zdrojích knihovny (uživatelská /
    sdílená složka) – další synchronizace by řádek znovu načetla ze souboru a úpravu by zahodila."""
    return bool(store.is_builtin(sid)) or _id_in_library_files(store, sid)


def save_user_symbol(store, sym: Symbol) -> Symbol:
    """Uloží značku do uživatelské knihovny. Vestavěnou ani souborovou (`is_read_only`) nepřepíše – uloží kopii pod prvním volným `<id>_N`.
    Při chybě (`check`) se nic neuloží. Vrací uloženou značku (u vestavěné / souborové kopii s novým id)."""
    issues = check(sym)
    if issues:
        raise SymbolEditError("Značku nelze uložit: " + "; ".join(issues) + ".")
    to_save = editable_copy(sym)
    if is_read_only(store, sym.id):
        to_save.id = free_symbol_id(store, sym.id)
    store.put_symbol(to_save)
    return to_save
