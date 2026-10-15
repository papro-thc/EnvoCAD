# Changelog

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
