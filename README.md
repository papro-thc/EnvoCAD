# EnvoCAD

Interní nástroj ENVO pro kreslení jednopólových schémat FVE a správu vlastní knihovny elektro prvků.
Cíl: nahradit EPLAN pro naše potřeby, s jedním modelem, ze kterého se generují schémata, výkazy a dokumentace.

## Instalace (Windows i Linux)

Doporučený Python 3.11–3.13 (3.14 je nový a PySide6 na něm není prověřené).

```
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
scripts\run.ps1

# Linux (Fedora/Ubuntu)
bash scripts/install.sh
scripts/run.sh            # Wayland potíže: QT_QPA_PLATFORM=xcb scripts/run.sh
```

Ručně: `python -m venv .venv`, aktivovat, `pip install -e .[dev]`, `python -m envocad`.

## Samostatná aplikace (bez Pythonu, pro kolegy)

`scripts\build.ps1` (Windows) / `scripts/build.sh` (Linux) sestaví přes PyInstaller složku `dist/EnvoCAD`
s binárkou `EnvoCAD.exe` / `EnvoCAD` (~260 MB, obsahuje Qt). Složku zabalte do ZIP a rozdejte; data
uživatele (knihovna, pluginy, logy) jsou v `~/.envocad/`, takže aktualizace = přepsat složku aplikace.
Build pro Windows se musí dělat na Windows, pro Linux na Linuxu.

## Stav

v0.5 – jednopólové schéma FVE, listy rozvaděčů (schéma + fyzické rozložení na DIN lištách, parametry skříně, odhad oteplení),
šablony rozvaděčů, výkazy (xlsx) a protokol kusového ověření (docx), export DXF/PDF, vícepól jako svorkové schéma (automatické rozmístění + posun myší), plán svorkovnice, rámeček s popisovým polem, knihovna 460 artiklů (OEZ, Eaton,
Schneider, Hager, SMA, SolaX, Huawei, BMR) + 673 značek QElectroTech, import DXF/EPLAN, pluginy, tmavý režim.

Dokumentace: **`docs/MANUAL.md` (uživatelská příručka)**, `docs/ARCHITECTURE.md`, `docs/LIBRARY_FORMAT.md`, `docs/ROADMAP.md`, `docs/COMPONENTS.md`.
Nastavení a firemní standard: `~/.envocad/settings.json` (menu Knihovna), sdílená knihovna = síťová složka s JSON/CSV.
Pokyny pro agenty: `CLAUDE.md`.

## Ovládání editoru

| Akce | Jak |
|---|---|
| Vložit symbol | dvojklik v panelu Knihovna, klik do výkresu, vyplnit parametry v dialogu (Esc zruší režim) |
| Upravit parametry | dvojklik na prvek nebo vodič |
| Posun | tažení myší (snap na mřížku 2,5 mm) |
| Rotace | `R` (o 90°) |
| Vodič | `W`, klik na port → klik na port, vyplnit parametry (označení, kabel, průřez) |
| Smazat | `Delete` |
| Zoom / posun pohledu | kolečko / střední tlačítko |
| Undo / redo | `Ctrl+Z` / `Ctrl+Y` |
| Tmavý / světlý režim | `Ctrl+D` |
| Otevřít rozvaděč | dvojklik na blok ROZVADĚČ (poprvé nabídne šablonu) – otevře vícepólové schéma; `Ctrl+J` přepne na jednopólovou editaci (vkládání, vodiče) |
| Rozložení rozvaděče | `Ctrl+L` na listu rozvaděče; přístroje přetáhnout na DIN lišty; parametry skříně a oteplení v panelu vpravo (`Ctrl+K`) |
| Výkazy / protokol | menu Výstupy (xlsx, docx) |
| Vícepól | `Ctrl+M` otevře vícepólový pohled listu (odvozený z JPS, `Ctrl+J` zpět); žíly vodiče se zadávají v dialogu vodiče („Žíly“), dvojklik na žílu / `Ctrl+T` = svorky, Úpravy → Očíslovat svorky |
| Svorkovnice a můstky | `Ctrl+Shift+T` – tabulka svorek vybrané svorkovnice, můstky jako „1-6-11“ (jedna skupina na řádek); skupina svorek v JPS = prvek Svorky s čísly v atributu „terminal“ |
| Plán svorkovnice | `Ctrl+Shift+M` – kreslený plán svorkovnice (export PDF), totéž jako list ve výkazech |
| Kopírovat / vložit | `Ctrl+C` / `Ctrl+V` – prvky i vodiče mezi nimi, nová označení |
| T-odbočka | v režimu Vodič klik na vodič → uzel, odbočka z něj (vodič z vodiče) |
| Potenciály | sítě přes vodiče, uzly, svorky, můstky, přívody; kontrola zkratů v F7, potenciál žíly ve Vlastnostech, výkaz Potenciály |
| Makra | `Ctrl+Shift+S` uloží výběr jako makro, uzel Makra v knihovně – dvojklik vloží |
| Vazba na JPS | u přívodu/vývodu rozvaděče v dialogu „Vodič v JPS“ – přebere kabel a žíly, křížový odkaz u vodiče |
| Kontrola / navigace | `F7` kontrola projektu (dvojklik na nález skočí do výkresu), `Ctrl+F` najít označení, dok Navigátor |
| Kabely | `Ctrl+Shift+K` kabel vybraného vodiče: žíly, čísla, barvy, stínění, artikl; výkazy Kabelový plán a Zapojovací seznam |
| Dokumentace | `Ctrl+Shift+E` celá dokumentace do jednoho PDF (titulní list, obsah, listy, výkazy, změnový list) |
| Ovládací obvody | značky Cívka / Kontakt NO / NC / silový (Relé a stykače); kontakt dostane označení cívky, pod cívkou se kreslí zrcadlo kontaktů |
| Výpočty | `F7` ukáže i výpočty (stringy, Iz, In ≤ Iz, úbytky, selektivita); výkaz Výpočty; uložení kabelu v atributu „Uložení dle ČSN“ nebo v textu trasy (zem, vzduch, trubka, stěna) |
| Nový projekt | `Ctrl+Shift+N` průvodce (stringy, střídače, DC rozvaděče po trase a u technologie, kabely) nebo `Soubor → ze specifikace (JSON)`; CLI `python -m envocad.generate spec.json out.ecp` |
| Revize | `Soubor → Porovnat s revizí` → změnový list; `Soubor → Vlastnosti` revize/datum |
| TZ / DS | `Výstupy → Technická zpráva (docx)`, výkaz Data pro DS |
| Artikl z knihovny | v dialogu prvku „Vybrat artikl z knihovny…“; menu Knihovna → Prohlížet / Importovat CSV |

## Když program spadne

Log každého běhu je v `~/.envocad/log/envocad.log` (Windows: `C:\Users\<jméno>\.envocad\log\`),
předchozí běhy `envocad.log.1` … `.5`. Otevře ho menu Nápověda → Otevřít složku s logy.
Neošetřená chyba se zapíše do logu a zobrazí v dialogu; program většinou běží dál – uložte práci.

## Licence

Kód EnvoCAD je pod licencí **MIT** (viz `LICENSE`). Součástí repozitáře jsou i data třetích stran:

- značky `envocad/library/builtin/qet/` jsou převedené z kolekce QElectroTech, **CC BY 3.0**, autorství viz
  `envocad/library/builtin/qet/ATTRIBUTION.md`;
- artikly v `envocad/library/builtin/components/*.csv` jsou technické parametry opsané z veřejných katalogů
  výrobců (OEZ, Eaton, Schneider, Hager, Weidmüller, Elektro Bečov, ELEMAN, SMA, SolaX, Huawei, BMR) – u každého
  řádku je zdroj a strana; katalogy samotné v repozitáři nejsou. Hodnoty jsou bez záruky, před použitím v projektu
  je ověřte u výrobce;
- tabulky v `envocad/model/thermal.py` a `envocad/model/calc.py` (IEC TR 60890, ČSN 33 2000-5-52) jsou orientační
  přepisy, ne text norem.

Název firmy v popisovém poli se nastavuje v `~/.envocad/settings.json` (`standard.company`), výchozí je ENVO s.r.o.
