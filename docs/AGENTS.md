# Tým agentů pro vývoj EnvoCAD

Vývoj řídí jeden orchestrátor (Fable), který rozděluje práci specializovaným agentům.
Každý agent má přiřazený model podle náročnosti úlohy – drahé modely jen tam, kde je potřeba úsudek,
levné na objemovou práci. Definice agentů jsou v `.claude/agents/*.md` (frontmatter `model:`),
takže je Claude Code / Cowork načte automaticky.

| Agent | Model | Role | Typické úkoly |
|---|---|---|---|
| **orchestrátor** (hlavní session) | **Fable** | Řídí projekt, drží architekturu, zadává a přijímá práci, rozhoduje | Plánování milníků, review výsledků agentů, zásahy do architektury, komunikace s Patrikem |
| `architekt` | Opus | Návrh datových struktur a rozhraní před implementací | Formát knihovny, model rozvaděče, strategie undo/redo, migrace formátu |
| `core-dev` | Opus | Implementace jádra (model, knihovna, export) | Nové funkce v `envocad/model`, `library`, `export`; refaktoring |
| `gui-dev` | Sonnet | PySide6 GUI | Panely, dialogy, nástroje editoru, interakce myší, klávesové zkratky |
| `symbol-author` | Sonnet | Tvorba a úprava symbolů | JSON symboly dle IEC 60617 / zvyklostí ENVO, porty, label_pos; kontrola `validate()` |
| `dxf-converter` | Haiku | Objemová konverze DXF od výrobců | Dávkový import DXF → JSON, čištění, škálování, zařazení do kategorií (bez úsudku, dle checklistu) |
| `data-entry` | Haiku | Plnění databáze artiklů | CSV z katalogů/datasheetů výrobců → `components`, kontrola jednotek |
| `tester` | Sonnet | Testy a QA | Pytest pro model/export, offscreen GUI smoke testy, reprodukce chyb, screenshoty |
| `reviewer` | Opus | Nezávislé review | Kontrola PR před merge: architektura, model bez Qt, undo, formát souborů, čeština v UI |
| `docs` | Haiku | Dokumentace | README, ROADMAP, uživatelská nápověda, changelog |

## Pravidla orchestrace

1. Orchestrátor nikdy nepíše velké kusy kódu sám – zadává `core-dev` / `gui-dev` a výsledky nechá projít `tester` a u větších změn `reviewer`.
2. Každé zadání agentovi obsahuje: cíl, dotčené soubory, co je už hotové/zamítnuté, jak ověřit (příkaz testu).
3. Změna formátu projektu nebo symbolu jde vždy nejdřív přes `architekt`.
4. Objemové úlohy (stovky DXF, tisíce artiklů) se dávkují po ~20–50 položkách na jednoho `dxf-converter` / `data-entry` agenta, paralelně.
5. Agent s Haiku dostává přesný checklist, ne volné zadání; pokud narazí na nejednoznačnost, vrátí ji orchestrátorovi místo hádání.

## Eskalace modelu

Pokud agent na Sonnetu/Haiku dvakrát neuspěje (testy červené, nejasné zadání), orchestrátor úlohu
zadá znovu agentovi o stupeň výš (Haiku → Sonnet → Opus), ne témuž agentovi potřetí.
