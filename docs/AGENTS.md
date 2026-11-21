# Tým agentů pro vývoj EnvoCAD

Vývoj řídí jeden orchestrátor (Fable), který rozděluje práci specializovaným agentům.
Každý agent má přiřazený model podle náročnosti úlohy – drahé modely jen tam, kde je potřeba úsudek,
levné na objemovou práci. Definice agentů jsou v `.claude/agents/*.md` (frontmatter `model:`),
takže je Claude Code / Cowork načte automaticky.

| Agent | Model | Role | Typické úkoly |
|---|---|---|---|
| `orchestrator` (hlavní session) | **Fable** | Řídí projekt i noční běh: vybere issue, rozplánuje, deleguje, hlídá výsledek | Plánování, delegace, ověření testů, PR; v cloudu `agent-nightly.yml` |
| `implementer` | Sonnet | Výchozí implementace kódu podle zadání orchestrátora | Malé issue v jádru i GUI; při dvojím neúspěchu eskalace na `core-dev` |
| `architekt` | Opus | Návrh datových struktur a rozhraní před implementací | Formát knihovny, model rozvaděče, strategie undo/redo, migrace formátu |
| `core-dev` | Opus | Implementace jádra (model, knihovna, export) | Nové funkce v `envocad/model`, `library`, `export`; refaktoring |
| `gui-dev` | Sonnet | PySide6 GUI | Panely, dialogy, nástroje editoru, interakce myší, klávesové zkratky |
| `symbol-author` | Sonnet | Tvorba a úprava symbolů | JSON symboly dle IEC 60617 / zvyklostí ENVO, porty, label_pos; kontrola `validate()` |
| `dxf-converter` | Haiku | Objemová konverze DXF od výrobců | Dávkový import DXF → JSON, čištění, škálování, zařazení do kategorií (bez úsudku, dle checklistu) |
| `data-entry` (datový agent) | Haiku | Sběr parametrů artiklů z veřejných datasheetů | CSV `builtin/components`, kontrola jednotek; nikdy data EPLAN Data Portalu ani PDF v gitu |
| `tester` | Sonnet | Testy a QA | Test podmínky hotovo před implementací, pokrytí existujícího kódu, offscreen GUI testy, reprodukce chyb |
| `reviewer` | Opus | Nezávislé review diffu proti `CLAUDE.md` | Architektura, model bez Qt, undo, formát souborů, licence dat, rozsah issue |
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

## Napojení na ECC (affaan-m/ECC)

Agenti EnvoCAD jsou projektová vrstva nad pluginem **ECC** (`ecc@ecc`, marketplace `https://github.com/affaan-m/ECC.git`).
Lokálně ho máš nainstalovaný; v GitHub Actions ho instaluje `claude-code-action` (`plugin_marketplaces` / `plugins`).

| Odkud | Kdo ho volá | Na co |
|---|---|---|
| `ecc:python-reviewer` | orchestrátor, souběžně s `reviewer` | obecná kvalita Pythonu (PEP 8, typy, idiomy) |
| `ecc:security-reviewer` | orchestrátor u vstupů z uživatele/souborů | bezpečnost importů a exportů |
| `ecc:code-explorer` | orchestrátor při plánování | mapování neznámé části kódu |
| skill `ecc:tdd-workflow` | `tester`, `implementer` | test nejdřív, musí selhat, pak implementace |
| skill `ecc:python-testing`, `ecc:python-patterns` | `tester`, `implementer` | pytest a styl Pythonu |

Pravidla `CLAUDE.md` mají vždy přednost před obecnými pravidly ECC. Subagent nemůže volat dalšího subagenta,
proto ECC agenty volá jen orchestrátor (hlavní session). Hook GateGuard z ECC je v CI vypnutý (`ECC_GATEGUARD=off`),
v neinteraktivním běhu by blokoval první Bash/Write.

## Automatický vývoj nad GitHubem

```
issue (šablona „Úkol pro agenta“) ──člověk přidá agent-ready──▶ agent-nightly.yml (01:00 UTC, 1 issue za noc)
   orchestrátor (Fable) → tester → implementer → reviewer + ecc:python-reviewer → commit
   workflow: kontrola větve agent/issue-N-*, check_licensed_data, push, PR „Closes #N“
        │
        ├─ nejasnost → komentář v issue + agent-question (bez PR) → odpovíš, odebereš štítek
        ▼
CI (ci.yml): licence + ruff → pytest Linux/Windows → PyInstaller build Linux/Windows
        ├─ červené → agent-fix-ci.yml (Sonnet, max 2 pokusy, pak agent-failed)
        ▼
ráno: projdeš PR, stáhneš build z artefaktů, sloučíš – nebo napíšeš „@claude …“ (agent-mention.yml) a agent přepracuje
```

**Proč Claude v nočním běhu nemá právo pushovat:** repo je soukromé na plánu Free, kde nejde zapnout ochrana větve
`main`. Proto má Claude jen token pro čtení, commituje lokálně a větev pushne až krok workflow, který ověří,
že se jmenuje `agent/issue-<N>-…`. Do `main` se tak agent nedostane, ani kdyby chtěl.

### Jednorázové nastavení
1. Štítky: `tools/setup_agent_labels.sh`
2. Secrets (Settings → Secrets and variables → Actions):
   - `OMNIROUTE_BASE_URL` – **veřejná** HTTPS adresa OmniRoute. `http://localhost:20128` z cloudu GitHubu nefunguje,
     OmniRoute musí být vystavený (např. Cloudflare Tunnel / Tailscale Funnel) s vlastním API klíčem.
   - `OMNIROUTE_API_KEY` – klíč OmniRoute (posílá se jako `x-api-key`).
   - `AGENT_GH_TOKEN` – fine-grained PAT jen na `papro-thc/EnvoCAD`: Contents RW, Pull requests RW, Issues RW.
     (PR založený výchozím `GITHUB_TOKEN` by nespustil CI.)
3. Variables (volitelné, když OmniRoute pojmenovává modely jinak): `AGENT_MODEL_ORCHESTRATOR` (výchozí
   `claude-fable-5-2`), `AGENT_MODEL_OPUS` (`claude-opus-5-5`), `AGENT_MODEL_SONNET` (`claude-sonnet-5-5`),
   `AGENT_MODEL_HAIKU` (`claude-haiku-5-5`), `AGENT_MAX_TURNS` (150). Pole `model:` v `.claude/agents/*.md`
   (`opus`/`sonnet`/`haiku`) se na ně mapují přes `ANTHROPIC_DEFAULT_*_MODEL`.
4. Ruční zkouška: Actions → „Agent – noční issue“ → Run workflow (lze zadat číslo issue).

### Limity spotřeby
Jedna issue za noc (`concurrency: agent`), `--max-turns 150`, timeout 150 min; oprava CI max 2 pokusy po 60 turnech;
`@claude` jen od vlastníka repa, max 80 turnů.
