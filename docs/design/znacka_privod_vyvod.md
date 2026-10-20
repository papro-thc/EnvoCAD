# Návrh: jedna značka přívodu a vývodu rozvaděče (`sb.feed`)

Požadavek: „u rozvaděčů – přívod a vývod budou schématicky přicházet vždy zespodu … sjednotit pod jednu značku“.
Stav (offscreen snímky, `origin/main`): `sb.feed_out` už „sedí“ (port nahoře `N`, kabelový výběžek a „VÝVOD“ dole).
`sb.feed_in` je zrcadlově obrácený (port dole `S`, výběžek a „PŘÍVOD“ nahoře, kabel shora) a generátor ho dává nad
první přístroj (RFVE.DC/RFVE.AC/HR/RE). Výjimka je RVN: `sb.feed_in` s `rot=180` dole. Tam je ale ve vícepólu chyba:
strana štítku kabelu se odvozuje ze `symbol_id` (`multipole_geometry.py:554`, `multipole_view.py:775`), ne z
otočení, takže štítek W15 překrývá svorky XDS1. Vícepól jinak kreslí přívody vždy nahoře (zdroj toku, `auto_layout`).

## 1. Značka `sb.feed` „Přívod / vývod“ (`builtin/switchboard/sb.feed.json`)
- Při `rot=0` je port `1` NAHOŘE `(0, 5) dir N`. Svorka = kroužek r 1,5 v `(0, 0)`. Vývod k portu `(0,1,5)–(0,5)`, kabelový
  výběžek dolů `(0,−1,5)–(0,−7,5)`. Šipka směru toku na výběžku (IEC 60617-02) je otevřená, široká 2 mm: `in` = hrot
  `(0,−3,5)` k portu, `out` = hrot `(0,−6,5)` od portu. Text „PŘÍVOD“/„VÝVOD“ `(0,−10)` h 2 na střed. `label_pos (5, 2,5)`:
  ref X…, popis, odkud/kam a kabel vpravo vedle svorky. Port je na mřížce 2,5 mm, texty se kreslí vždy svisle (jako dnes).
- Atributy: `ref`, **`dir`** (`in`|`out`, výchozí `in`, skrytý), `desc`, `from`, `to`, `cable`, `terminal`. Klíče
  `from`/`to` zůstávají (vazby, xref, `terminal_plan`, výkazy se nemění). Zobrazí se jen ten, který patří k `dir`.
- `multipole.pole`: jako dnešní `sb.feed_out` (kroužek `(0, 2,5)`, port nahoře, výběžek dolů).
- Obrázek podle `dir`: odvozená značka `feed_symbol(e, base)` v `element_symbol` (precedens `inverter_symbol`). Základní
  JSON = `in` (náhled při vkládání `get_symbol`), pro `out` se vymění šipka, text a zobrazený atribut.
- Formát knihovny: nepovinný klíč atributu `choices` (`[["in","přívod"],["out","vývod"]]`) → combobox ve Vlastnostech.
  Starší program ho ignoruje, verze symbolu se nemění (jako `function_class`).
- **Zamítnuto:** a) dvě značky se společnou geometrií – nesplní „jednu značku“, `symbol_id` dál nese sémantiku;
  b) skryté varianty `sb.feed@in/out` v knihovně – směr by byl v id, přepnutí = výměna prvku (rozbíjí vazby a undo);
  c) dosazování atributů do textu primitiva („{dir}“) – obecná šablonová vrstva kvůli jedné značce (YAGNI);
  d) jeden klíč `remote` místo `from`/`to` – migruje atributy a mění xref i výkazy bez přínosu pro uživatele.

## 2. Model: jediné místo pravdy `envocad/model/feed.py` (bez Qt)
`FEED_SYMBOL = "sb.feed"`; `is_feed(e)`, `feed_dir(e) -> "in"|"out"` (prázdné/neznámé → `in`, F7 `feed_dir` varování),
`is_feed_in/out(e)`, `feed_link_key(e) -> "from"|"to"`. Dál `LEGACY_FEEDS = {"sb.feed_in": ("in", 180), "sb.feed_out":
("out", 0)}` a `normalize_legacy_element(d: dict) -> bool` (pracuje se slovníkem prvku: id, `attrs.dir`, `rotation`).
Všech ~25 míst s `"sb.feed_in"`/`"sb.feed_out"` (project, multipole*, single_line, calc, checks, wiring, designation,
reports, macros, templates, generate, `ui/multipole_view`) přejde na predikáty. Množiny id (`SOURCE_SYMBOLS`,
`TERMINAL_SYMBOLS`…) dostanou `sb.feed` a zdroj/cíl se pozná přes `feed_dir`. `SHORT_NAMES` řeší `element_name` podle směru.

## 3. Migrace `FORMAT_VERSION` 12 → 13 (`migrate`, `ver < 13`)
`sb.feed_in` rot r → `sb.feed`, `dir=in`, rot (r+180) % 360. `sb.feed_out` → `sb.feed`, `dir=out`, rot beze změny.
**Bezztrátově:** port `1` zůstane na stejném místě se stejným `dir` (S/N), takže vodiče (včetně `points`), `mp_pos`,
`sl_pos`, vazby `wire_id` i porty bloku se nerozpojí a nic se neposouvá. Staré listy vypadají stejně jako dřív (přívod
nahoře s kabelem shora), přibude jen šipka. RVN (rot 180) přejde na rot 0 a už je správně. Ručně umístěné prvky
migrace nepřeskládá: přeskládání je rozhodnutí projektanta (přegenerování, ruční přesun nebo otočení R – vodič
na port drží). Starší program soubor v13 odmítne, takže `sb.feed` tiše nezmizí.
- **Makra (sdílená knihovna, v1/v2):** mapování při načtení v `macros.parse_macro` (fragment přes
  `normalize_legacy_element`). Stejně pro schránku v `paste_fragment`. `MACRO_VERSION` 2 → 3: `save_macro` píše v3,
  aby starší EnvoCAD kolegy makro se `sb.feed` odmítl (log) a nevložil zástupné „?“. Makra v1/v2 se načtou bez změny souboru.
- **Knihovna:** soubory `sb.feed_in/out.json` se smažou. `sync_builtin` smaže z SQLite vestavěné řádky s id z
  `LEGACY_FEEDS`, jinak by v paletě zůstaly (store vestavěné řádky nikdy nemaže).
- **Zamítnuto:** alias v knihovně (`element_symbol` mapuje id za běhu) – směr by se musel odvozovat všude a rotaci
  nelze přemapovat bez úpravy prvku. Alias v souborech maker (přepis na disku) – zápis do cizí sdílené složky.
  Migrace s přeskládáním polohy – posouvá ruční práci a láme `points`.

## 4. Dopady
- **Generátor + šablony** (`generate.py`, `templates.py`, `tools/gen_builtin_macros.py` → přegenerovat `builtin/macros`):
  pomocník `_feed(…, dir)`, přívody ve spodní řadě s vývody, `rot 0`. Rozložení (návrh, maketou ověřena jen zamítnutá stoupačka):
  *AC (RFVE.AC, HR, RHN)* – sběrnice nahoře, přívodní větev pod ní teče **nahoru** (X dole → jistič rot 90 → sběrnice).
  Odpovídá ENVO „vše visí ze sběrnice“ a nic se nekříží. *Sériová větev bez sběrnice (DC string X1→FU→X3)* – „U“:
  levá noha nahoru (přívod, FU), ohyb nahoře, pravá noha dolů (SPD odbočka, vývod). Svislý úsek v pruhu bez popisků.
  Body ohybů generátor zadává do `points`. **Zamítnuto:** stoupačka vedle nezměněného sloupce (maketa: kříží sběrnici,
  PE a SPD odbočky).
- **Spec. pro autora mustrů** (`topologie_f1_f2.md` kap. 3): kotvy `sb.feed` `dir=in` `X{k}` / `dir=out` `X{nk}`, `XOUT`,
  `XPE`, `XE{i}`/`XB{i}`. Pravidlo „port nahoře, přívod i vývod ve spodní řadě“. Staré mustry fungují (load-time mapování).
- **Vazby přívodů:** `feed_link_attrs` klíč podle `feed_dir`. `switchboard_symbol` dělí porty bloku podle `dir`
  (in vlevo W, out vpravo E – beze změny chování). Změna `dir` = `SetAttrCommand` + follow-upy v jednom příkazu
  (`_feed_link_followups(attrs=True)` přepočte `from`↔`to`). Port bloku se jen přesune na druhou stranu, vodič drží.
  Canvas po změně `dir` přestaví `ElementItem` (jako `io` střídače).
- **Vícepól:** strana štítku a kabelu podle řady a `feed_dir`, ne podle `symbol_id` (opraví RVN). „Přívod dole“ ve
  vícepólu = jiná logika `auto_layout` (přívody v dolní řadě, tok nahoru do sběrnice / smyčka „U“). Samostatný krok 4.
- **F7:** `is_earthing_feed`, `SPD_SOURCES`, `dangling`/`bad_port` beze změny. Nové varování `feed_dir` (neplatný směr).
- **Výkazy / svorkový plán / výroba / DXF:** jen predikáty (`reports.TERMINAL_SYMBOLS`, `wiring.BOTTOM_ESTIMATE`).
  DXF kreslí primitiva z `element_symbol` (bez bloků), takže se změní samo. Dokumentace: `LIBRARY_FORMAT.md` (choices,
  sb.feed), `ARCHITECTURE.md` (v13), `MANUAL.md`, `ENVO_STYL.md` (RFVE.DC už ne „tok shora“, štítky dole), `CHANGELOG`.

## 5. Testy a pořadí
1. `model/feed.py` + migrace v13 + `sb.feed.json` + `choices` + čištění store. Testy: migrace in/out × rot 0/90/180/270
   = stejná poloha a směr portu, vodiče připojené, `from_dict(to_dict)`, vazby po `sync_feed_links` beze změny,
   `bad_port` 0. Makro v1/v2 se `sb.feed_in` → `sb.feed`. v13 ve starší verzi = odmítnutí. Store bez legacy řádků.
2. Náhrada všech použití predikáty (grep `sb.feed_in|sb.feed_out` = 0 mimo `LEGACY_FEEDS` a testy migrace). Snímek
   generátoru se změní jen v id/rot/`dir`. GUI: přepnutí `dir` + undo/redo (atributy, port bloku, `from`/`to`).
3. Rozložení generátoru a maker (AC nahoru do sběrnice, DC „U“). `test_generated_project_f7_clean`, překryvy,
   nový snímek, offscreen snímky.
4. Vícepól: oprava strany štítku (hned), „přívod dole“ až po odsouhlasení uživatelem.

**Větev:** po dokončení přejmenování rozvaděčů na `feature/topologie` odbočit `feature/znacka-privod` a kroky 1–3
vrátit do `feature/topologie` **před** refaktoringem F1 (`generate.py` → `generator/`). F1 vyžaduje snímek beze změny,
tak ať se změní jednou a předem. Samostatně od `main` ne: konflikty v `generate.py`, šablonách a snímku s F0
a s přejmenováním.

## Rozhodnutí (Patrik, 2026-10-20)
1. Jedna značka `sb.feed` (+ `dir`), směr **jen šipkou** – text „PŘÍVOD“ / „VÝVOD“ se nepíše.
2. **DC rozvaděče (RFVE.DC, RDCn) zůstávají rozložením jako dnes** (jen nová značka, bez „U“).
3. **RFVE (RD) a RFVE.AC: vizuálně vše přichází zespodu** (přívody i vývody), přívodní větev tokem nahoru do
   sběrnice. Fyzické umístění určí projektant podle dispozice. HR, RE a RVN beze změny rozložení.
4. Týká se jen listu rozvaděče – vícepól ani blok ROZVADĚČ v blokovém schématu se nemění.
5. Staré projekty: bezztrátový převod, vzhled se nepřeskládá (bez hromadného příkazu).
6. Výchozí směr nové značky z palety: přívod.

## Stav implementace (2026-10-20)
Kroky 1–3 hotové na `feature/topologie` (viz `CHANGELOG.md`). Odchylky od návrhu: popisek zůstává v `(7, 0)` (jako
dřív, ve výkresu vpravo od svorky i u převedeného přívodu otočeného o 180°) místo `(5, 2,5)`, ať se staré listy
nepřeskládají; sběrnice dostala přívody zdola `B1…B12` (B1 = poloha T1, ať vícepól sběrnici umístí jako dřív); PE
svodičů DC části RFVE vede nad sběrnicí do XPE vlevo; XMI/XMU v HR jsou otočené portem dolů (vodič neprochází
kroužkem). Vícepól se nemění: `multipole.sheet_poles` kreslí přívody v geometrii starých značek a přívodní větev
otočenou tokem nahoru otočí zpět (`flow_flipped`); u rozvodu svorkami bez maker se změnil jen port PE lišty, do
kterého vedou PE svodičů (jeden port, ať vodiče v listu nevedou souběžně do různých portů).
