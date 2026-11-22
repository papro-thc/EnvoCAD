# Převod rešerše EnvoCAD do GitHub issues

Jsi orchestrátor (model: Fable). Tvým úkolem je přenést výsledky rešerše
z `docs/research/` do GitHub issues repozitáře papro-thc/EnvoCAD. Nepíšeš žádný
kód aplikace – výstupem jsou jen issues a jeden souhrnný soubor.

## Vstupy
- `docs/research/03_doporuceni.md` – hlavní zdroj. Kap. 0 = opravy a rozpory,
  kap. 2 = seřazený backlog, kap. 3 = issues k zavření / sloučení / přeformulování,
  kap. 6 = hotové texty nových issues (NEW-1 až NEW-20), kap. 7 = otázky pro projektanta.
- `docs/research/01b_issues.md` – přehled stávajících issues. Pozor: je starší než
  PR #105–#109 a mylně označuje #65 za nedořešenou; platí kap. 0 souboru 03.
- `docs/research/02_*.md` – podklady, na které se issues odkazují.
- `CLAUDE.md` a `changelog.d/README.md` – pravidla projektu.

## Krok 1 – Příprava (jen čtení)
1. Ověř `gh auth status`. Když není přihlášeno, zastav se a napiš mi, co mám udělat.
2. Načti aktuální stav: `gh issue list --state all --limit 500`, `gh pr list --state open`,
   `gh label list`. Stav se od rešerše mohl změnit – řiď se tím, co je na GitHubu teď.
3. U každého návrhu NEW-1 až NEW-20 zjisti, jestli už neexistuje issue nebo PR se
   stejným obsahem (hledej podle klíčových slov i dotčených souborů). Duplicitu nezakládej.
4. U každého návrhu ověř v kódu na `main`, že popsaný problém stále platí
   (soubor existuje, chování odpovídá). Co už neplatí, vyřaď a uveď proč.

## Krok 2 – Plán ke schválení
Než cokoli změníš na GitHubu, vypiš mi tabulku a POČKEJ na moje „ano“:
- nové issues: pracovní označení (NEW-x), název, štítky, závislosti, `agent-ready` ano/ne
- úpravy stávajících issues podle kap. 3: číslo, co přesně se změní (nový text těla,
  rozdělení na menší, změna štítků) a proč
- co jsi vyřadil a proč
Schválit mohu i jen část; proveď pouze schválené řádky.

## Krok 3 – Založení nových issues
- Texty ber z kap. 6 souboru 03; uprav jen to, co se od rešerše změnilo.
- Každá issue: kontext, co a proč, dotčené soubory, akceptační kritéria jako
  `- [ ]` checklist, sekce „Mimo rozsah“, odkaz na podklad
  (`docs/research/<soubor>.md`, sekce). Rozsah na pár hodin práce; větší rozděl.
- Závislosti piš jako „Blokováno: #číslo“ – zakládej proto v pořadí backlogu (kap. 2),
  aby čísla blokujících issues už existovala.
- Štítky: použij jen existující. Štítek `agent-ready` dej pouze tam, kde podle kap. 6
  není potřeba oborové rozhodnutí a issue není blokovaná jinou.
- Issues vyžadující oborové rozhodnutí (NEW-12 až NEW-17): založ bez `agent-ready`,
  se štítkem `agent-question`, a na začátek těla dej konkrétní otázku pro projektanta
  z kap. 7 (jaké varianty, co rešerše doporučuje a proč).
- Zakládej přes `gh issue create --body-file <soubor ve scratchpadu>`, ne přes
  dlouhý `--body` v příkazové řádce.

## Krok 4 – Úpravy stávajících issues (jen schválené)
- Přeformulování: uprav tělo (`gh issue edit --body-file`) a přidej komentář,
  co se změnilo a proč, s odkazem na rešerši. Původní text zachovej v komentáři.
- Rozdělení: založ dílčí issues, do původní přidej checklist s odkazy na ně.
- Komentář vlastníka u #71 (volitelné značení rozvaděčů v generátoru) přenes do těla
  nebo do samostatné issue.
- Zastaralý štítek `agent-in-progress` bez PR sundej jen u issues, které jsem schválil.

## Co NEDĚLAT
- Nezavírej žádnou issue, neslučuj a nezavírej PR, nic nemaž. Návrhy na zavření
  jen vypiš v závěrečném souhrnu.
- Neslučuj větev `feature/papir-eti-svodice` do `main` a nic nepushuj – merge dělá člověk.
  Můžeš založit issue, která to popíše jako úkol pro mě.
- Neměň kód, testy ani dokumentaci mimo `docs/research/`.
- Nedomýšlej oborová rozhodnutí (jištění, průřezy, normy, značení, výběr artiklu,
  vzhled výkresu). Co nevíš, formuluj jako otázku.
- Nezakládej štítky ani milníky bez mého souhlasu.

## Výstup
Zapiš `docs/research/05_issues_zalozeno.md`:
- tabulka NEW-x → číslo issue → štítky → závislosti
- upravené stávající issues a co se změnilo
- vyřazené návrhy s důvodem
- issues doporučené k zavření a PR čekající na moje review (jen seznam)
- otázky pro projektanta seřazené podle počtu blokovaných issues
- doporučené pořadí, v jakém pouštět agenty na `agent-ready` issues

Na konci vypiš shrnutí (max 10 řádků). Piš česky, názvy souborů a funkcí nech v originále.
