# Překlady rozhraní

Zdrojové texty v kódu jsou **česky**, překlady jsou v textových katalozích `envocad/resources/i18n/<jazyk>.po`
(zatím `en.po`). Jazyk se volí v `Zobrazit → Jazyk rozhraní` (uloží se do `settings.json`, platí po restartu).

## Proč gettext-styl s `.po`, ne Qt `tr()` / .ts / .qm
- `model/`, `library/`, `generator/` a `cmd/` nesmí importovat Qt, ale jejich hlášky (kontroly F7, generátor) se musí
  překládat stejně jako GUI. Proto jedna funkce `tr()` z `envocad/i18n.py` bez Qt pro celý kód.
- Žádný build krok (lupdate / lrelease / msgfmt) a žádné binárky v gitu: `.po` se čte přímo za běhu. V PyInstalleru je
  to jen datový soubor (`resources/i18n/*.po` v `envocad.spec`). `.po` je standard (jde otevřít v Poedit).
- Standardní dialogy Qt (Ano/Ne/Storno) dál řeší `qtbase_cs.qm`; v angličtině se nenačítá (Qt je anglicky).
- Nevýhody: žádné živé přepnutí (restart); `pyside6-lupdate` texty nesbírá – úplnost katalogu hlídá
  `tests/test_i18n.py`; množná čísla zatím nejsou (až budou potřeba, doplní se `trn()`).

## Jak přidat nebo přeložit text
1. Literál obal `tr("Český text")`. Žádné f-stringy uvnitř `tr` – `tr("Soubor {name} nejde načíst").format(name=…)`.
2. Přidej záznam do `en.po` (`msgid` = český text přesně jako v kódu, `msgstr` = anglicky).
3. Stejný český text s jiným významem odliš kontextem `tr("Konec", "menu")` a v `.po` řádkem `msgctxt "menu"`.
4. Spusť `pytest tests/test_i18n.py` – hlídá, že každé `tr()` v kódu má překlad a že `en.po` nemá nepoužité záznamy.
5. Nepřekládej při importu modulu: konstanta na úrovni modulu se vyhodnotí před `set_language`. Volej `tr()` až
   při použití (v metodě / funkci).

Chybějící nebo prázdný překlad (i záznam `#, fuzzy`) = zobrazí se český originál.

## Co se nepřekládá
Výstupy zůstávají česky: výkresy, výkazy, protokoly a technická zpráva.
Proto `tr()` patří jen na texty, které se **zobrazí v rozhraní** (menu, dialogy, stavový řádek, výpis kontrol F7
v panelu). Nikdy jím neobaluj text, který se zapisuje do projektu, výkresu nebo exportu (texty generátoru na listech,
hlášky kontrol přebírané do technické zprávy) – výstup nesmí záviset na jazyku rozhraní. Kde tentýž text jde do GUI
i do výstupu, překládej až v místě zobrazení v `ui/`.

Jméno `tr` je v balíčku `envocad/` vyhrazené pro překlad (test úplnosti bere každé volání `tr(...)` jako překladové) –
lokální funkce pojmenuj jinak. Parser `.po` je zjednodušený: bez množných čísel (`msgid_plural`) a bez `\r`.

## Další jazyk
Přidej kód do `LANGUAGES` v `envocad/i18n.py` a soubor `envocad/resources/i18n/<kód>.po` (hlavička + záznamy jako
v `en.po`). Menu Jazyk rozhraní ho nabídne samo; test úplnosti je zatím jen pro `en`.
