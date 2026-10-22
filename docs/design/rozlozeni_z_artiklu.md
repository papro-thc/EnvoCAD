# Rozložení rozvaděče z dat artiklů (návrh, 10/2026)

## Dnes
- Šířka přístroje v rozložení = `Element.modules` (atribut `modules`, výchozí hodnota značky – MCCB „6“); skupina
  svorek `sb.terminal_block` bez `modules` = počet svorek × 6,2 mm (`TERMINAL_WIDTH_MM`). Výška pevně
  `DEVICE_HEIGHT_MM` = 45 mm, hloubka se nesleduje.
- Artikl se do rozložení dostane jen přes `apply_to` (propíše `modules`, `p_loss_w`); `width_mm`, `height_mm`,
  `depth_mm` z katalogu se nikde nepoužijí. Footprint (`footprint_id`) má v katalogu 0 artiklů.
- Oteplení: `p_loss_w` jen z atributu, jinak odhad z In; zdroj se neukazuje.
- Kontroly rozložení (`checks.layout_problems`): přetečení řady a překryvy v modulech.

## Návrh
1. **`model/device_size.py`** (bez Qt): `device_size(e, lib=None) -> DeviceSize(width_mm, height_mm, depth_mm,
   modules, shape, source)`. Knihovna duck-typed (`lib.component(id)`), jako `thermal._limit`; bez knihovny se
   chová přesně jako dnes (jen atributy).
   - Priorita šířky: ruční `width_mm` prvku > výslovné `modules="0"` (mimo rozložení) > ruční `modules` (liší-li se
     od artiklu, který moduly má) > artikl
     (`modules`, jinak `width_mm`) > atribut `modules` (výchozí značky / starý projekt) > nic (není přístroj).
   - Výška a hloubka: atribut `height_mm` / `depth_mm` > artikl > výchozí 45 mm / neznámá.
   - Tvar `shape`: `din` (modulový), `box` (artikl bez `modules` s `width_mm` – kompaktní jistič 3VA, MCCB,
     odpínač 3VA – generický obdélník š × v), `terminal` (skupina svorek).
   - Zdroj `source`: „artikl“, „ruční“, „výchozí“.
2. **Svorkovnice**: šířka = počet svorek × `width_mm` artiklu svorky + `end_mm` (atribut skupiny – koncová deska /
   zarážky; katalog jejich šířku nemá, proto bez konstanty, výchozí 0). Bez artiklu nebo bez `width_mm`
   (Bečov, Eleman) 6,2 mm jako dnes. Ruční `modules` skupiny má přednost.
   **Můstky**: atribut `bridge_id` skupiny svorek = artikl můstku (katalog: Weidmüller ZQV/WQV, Bečov propojky,
   `terminal_kind=mustek`, nabídka v panelu z `bridge_candidates`), po skupinách můstku (`model/bridges.py`):
   póly artiklu = skupina → typ, víc → „zkrátit“, míň / neznámé / není můstek → bez typu + F7 `bridge_article`.
   Automatický výběr můstku podle svorky se nedělá (katalog nemá vazbu svorka → můstek).
3. **Rozhraní** `Layout.devices/used_modules`, `checks.layout_problems`, `wiring.terminal_point`, výkaz přístrojů
   (sloupec Moduly) dostanou volitelné `lib`; volající s knihovnou (GUI, F7, výkazy) ji předají.
   Rozložení (`ui/layout_view.py`) kreslí přístroj ve skutečné šířce a výšce, svisle na střed osy lišty;
   `box` jako obdélník s pákou, svorky jako úzké obdélníky po svorkách. Popisek dole: „4 M“ / „76 × 130 mm“.
4. **Oteplení**: `thermal.device_loss(e, comp)` → (Pv při In, zdroj „artikl“/„ruční“/„odhad“); atribut shodný
   s artiklem = „artikl“, jiný = „ruční“, bez atributu artikl, jinak odhad z In. `ThermalResult.losses` + souhrn
   zdrojů v panelu skříně, TZ a protokolu („Pv: 3× artikl, 1× ruční, 2× odhad“).
5. **Kontroly F7** (`device_size.size_problems`, volané z `checks.layout_findings`): WARNING
   `layout_height` (výška přístroje > rozteč řad – zasahuje do sousední řady), `layout_enclosure` (přístroj je
   širší než užitná šířka; svisle stačí rozteč – řady jsou v obrysu `Layout.outline_mm` na střed), `layout_depth`
   (hloubka přístroje > hloubka skříně, jen se zadanou `depth_mm` skříně). Artikly přes `memo_lib` (jedno čtení).
6. Změna artiklu prvku vymaže ruční rozměry (`size_resets_for_component`, jeden krok undo). Délky vodičů
   (`wiring.terminal_point`) se skutečnou výškou z artiklu.

## Zpětná kompatibilita
- Prvek bez artiklu: šířka, výška 45 mm, tvar a kontroly beze změny; bez `lib` vše jako dnes.
- Formát projektu se nemění (nové věci jsou jen atributy prvků `width_mm`, `height_mm`, `depth_mm`, `end_mm`,
  `bridge_id`), `FORMAT_VERSION` zůstává 15.
- Prvek s artiklem se změní záměrně (3VA11 76,2 mm místo výchozích 6 M; svorka A2C 1.5 3,5 mm místo 6,2 mm).

## Otevřené
- Footprinty z DXF výrobců (`footprint_id`) – kreslí se jako dřív, pokud jsou; katalog žádné nemá.
- Šířka koncových desek / zarážek (AEP, AEB) a rozměry svorek Bečov / Eleman v katalogu chybí.
- Šablony (`templates._place_sequential`) rozmísťují dál podle `Element.modules` (bez knihovny).
