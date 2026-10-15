# Changelog

## 0.6.0 – 2026-10-15
- Vícepólový pohled (`Zobrazit → Vícepólový pohled`, `Ctrl+M`): odvozená scéna nad stejným listem – každá žíla vodiče (`Wire.conductors`) je samostatná čára, průchozí prvky (jistič, odpínač, chránič, SPD…) se opakují pro spínané póly, N/PE jdou kolem; neprůchozí prvky (střídač, svorky, sběrnice) mají sběrnou čárku přes žíly. Pozice z JPS roztažené 2×, symboly ve skutečné velikosti. Žádná data se nekopírují – změna v JPS se hned promítne (`Ctrl+J` zpět na JPS).
- Dialog vodiče má pole „Žíly“ s předvolbami (L1 L2 L3 N PE, DC+ DC-, …); nové vodiče dostanou výchozí žíly podle portů a pólů připojených prvků.
- Svorky: dvojklik na žílu ve vícepólu nebo `Ctrl+T` otevře tabulku svorek vodiče (X1:3 / F2:1 per žíla a konec), `Úpravy → Očíslovat svorky automaticky` doplní chybějící čísla na svorkovnicích, přívodech, vývodech a PE liště. Vše přes undo.
- Výkaz svorkovnice a export PDF berou vícepól v úvahu; `tests/test_multipole.py` + GUI smoke test.

## 0.5.1 – 2026-10-15
- Knihovna artiklů z PDF katalogů dodaných uživatelem (celkem 460 artiklů): Eaton 253 (xPole PL/PLHT/AZ, PF/PFIM/FRCmM/dRCM, SPD, xComfort skříně), OEZ 143 (Minia LTN/LFN/LFE/OLI/SVBC, 3VA10–3VA24 vč. odpínačů, motorových pohonů MO310/MO320/SEO520 a spínačů do dutin, pojistkové odpínače OPVP/OPVF, rozvodnice RZA), Schneider 35 (skříně S1868), Hager 11, SMA 5, SolaX 6, Huawei 3, BMR 4 (PLA33RXE…). Každý řádek má odkaz na zdroj a stranu katalogu v poznámce.
- Úklid: staré řádky 3VA v `oez.csv` nahrazeny `oez_3va.csv`, duplicity ze `seed.csv` odstraněny (dřívější chyba: `seed.csv` se načítal jako poslední a přepisoval katalogová data), přiřazení motorových pohonů a spínače EAS k rámům ověřeno proti tabulkám B12/B19 katalogu MO01-2022.
- Test `tests/test_components_builtin.py`: validace všech vestavěných CSV, zákaz duplicitních id napříč soubory.
- Známé mezery: ztrátové výkony 3VA (potřeba OEZ „3VA Parametry“), OPVF10 DC (chybějící strany B12–B14 v OPVP PDF), význam přípon BMR C/D/R, montážní desky Schneider.

## 0.5.0 – 2026-10-15
- Instalační skripty `scripts/install.ps1|sh`, `run.*`, balení `scripts/build.*` + `envocad.spec` (PyInstaller, ověřeno na Linuxu). Python omezen na 3.11–3.13.
- Import značek QElectroTech (`library/qet_import.py`): 673 značek IEC 60617 (jednopól + vícepólové jištění, spínání, transformátory, střídače, zdroje, svorky, relé, kabely) v kategoriích „QET …“, s uvedením autorství (CC BY 3.0, `builtin/qet/ATTRIBUTION.md`).
- Import z EPLAN exportů (`library/eplan_import.py`): obchodní CSV z Data Portalu, XML artiklů z P8, DXF ZIP → footprinty; heuristické mapování sloupců s `--dump`.
- Modularita: uživatelské balíčky knihovny v `~/.envocad/library/` (JSON + CSV, bez kódu), pluginy `~/.envocad/plugins/*.py` s `register(ctx)` (menu, šablony, importéry, výkazy); menu Knihovna → Otevřít složku knihovny a pluginů.
- Knihovna se načítá jen při změně souborů (start 0,02 s místo 1,3 s); panel Knihovna má QET kategorie sbalené.
- `docs/SOURCES.md`: přehled zdrojů dat a komunitních nástrojů (EPLAN Data Portal API, .epdz/E3D, QET).

## 0.4.0 – 2026-10-15
- Knihovna artiklů: formát CSV v2 (`docs/COMPONENTS.md`), validátor (`python -m envocad.library.components validate …`), vestavěné CSV v `library/builtin/components/` načítané při startu, import vlastních CSV z menu Knihovna.
- Výběr artiklu v dialogu prvku (filtr výrobce / In / póly / charakteristika, odkaz na datasheet) – parametry se propíší do prvku; prohlížeč artiklů v menu Knihovna; výběr skříně z knihovny v panelu rozložení.
- Rozložení: generický footprint modulového přístroje (páčky podle pólů, svorky), footprint z DXF přes `footprint_id`.
- Startovní data: 77 artiklů (OEZ Minia LTN/LFN/OLI/SVBC + 3VA, Hager MBN/MCN/CDA/Volta, SMA STP X, Huawei, SolaX X3-ULTRA, BMR PLA33) – každý s odkazem na zdroj.

## 0.3.1 – 2026-10-15
- List rozvaděče má vlevo nahoře informační blok s parametry skříně (skříň, rozměry, moduly, Un, In, Icw, síť, IP/IK, montáž, materiál) – živě z panelu skříně, stejně v PDF i DXF.

## 0.3.0 – 2026-10-15
- Oprava chybového dialogu při zavírání programu (signál výběru na likvidované scéně rozložení).
- Panel skříně přímo v záložce rozložení: označení, řady, moduly, rozměry (š/v/h), rozteč řad, IP/IK, montáž, materiál, dveře, Un/In/Icw, síť, rezerva, teplota okolí, RDF. Změny se projeví hned; dvojklik do prázdné plochy skočí do panelu; `Ctrl+K` otevře totéž jako dialog.
- Rozložení kreslí skříň ve skutečných rozměrech a ukazuje obsazenost/rezervu modulů.
- Odhad oteplení dle IEC 60890 (ČSN EN 61439-1 čl. 10.10.4.3): ΣPv přístrojů (atribut `p_loss_w`, jinak odhad z In a pólů) × RDF², chladicí plocha Ae podle montáže, Δt střed/horní část, hodnocení. Orientační – viz `envocad/model/thermal.py`.
- Protokol kusového ověření přebírá parametry skříně.

## 0.2.4 – 2026-10-15
- Oprava pádu (access violation): panel Vlastnosti mazal editační pole uvnitř jeho vlastního signálu `editingFinished` (při ztrátě fokusu – klik jinam, přepnutí záložky). Mazání i zápis do modelu jsou odložené.
- Popisky vodičů ve stylu EPLAN: vodorovný úsek → nad čarou, svislý → vodorovně vedle čáry se šikmou značkou. Stejně v DXF.

## 0.2.2 – 2026-10-15
- Dialogy parametrů (vložení prvku, vodiče, dvojklik) se otevírají až po doběhnutí události myši – oprava pádu na Windows.
- Do logu se zapisují akce (režim, dialogy, záložky), aby šel pád dohledat.

## 0.2.1 – 2026-10-15
- Logování do `~/.envocad/log/` (rotace 5 běhů), dialog při chybě, `crash.log` pro nativní pády (faulthandler).
- Oprava pravděpodobného pádu v pohledu rozložení (přestavba scény během obsluhy myši); otevření rozvaděče z dvojkliku je odložené mimo obsluhu události.

## 0.2.0 – 2026-10-15
- Rozvaděče: dvojklik na blok ROZVADĚČ založí/otevře jeho list (schéma) – šablony AC rozvaděč FVE, DC rozvaděč, prázdný.
- Pohled rozložení (Ctrl+L): řady DIN lišt, přístroje v modulech (17,5 mm), přetahování se snapem 0,5 modulu, undo.
- Záložky listů, menu List (nový/přejmenovat/odstranit, nastavení skříně, vložit šablonu).
- Nové symboly: hlavní vypínač, proudový chránič, jistič s chráničem, sběrnice, přívod, vývod, svorkovnice, PE/N můstek.
- Přístroje mají atributy výrobce, póly, šířka v modulech.
- Model: příprava na vícepól – `Wire.conductors` (žíly) a `Wire.terminals` (svorky per žíla), `Sheet.kind`, `Layout`; formát projektu v2 s migrací.
- Výstupy (menu Výstupy): výkaz přístrojů, výkaz materiálu, kabely, svorkovnice, štítky do xlsx; protokol kusového ověření (ČSN EN 61439-1) do docx.
- Nové závislosti: openpyxl, python-docx → `pip install -e .[dev]`.

## 0.1.2 – 2026-10-15
- Tmavý režim (výchozí), přepínání Zobrazit → Tmavý režim / Ctrl+D, volba se pamatuje. PDF export vždy černá na bílé.

## 0.1.1 – 2026-10-15
- Dialog s parametry při vložení prvku i vodiče; dvojklik = úprava parametrů (undo jako jeden krok).
- Vodiče: automatické označení W1, W2…; ve výkresu se zobrazuje označení + typ kabelu + průřez.

## 0.1.0 – 2026-10-15
- První kostra: model, knihovna 18 symbolů FVE, editor jednopólového schématu, undo/redo, export DXF/PDF, import DXF.
