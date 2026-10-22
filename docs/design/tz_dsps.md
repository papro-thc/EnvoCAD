# Technická zpráva a DSPS ze šablony

Roadmapa: „Generování částí TZ/DSPS z modelu (šablony)“. Dnes `export/tz_export.py` skládá TZ kódem (pevné kapitoly,
tabulky z `calc`/`reports`, text kapitol „Doplnit…“), GUI Výstupy → „Technická zpráva (docx)…“ bez volby šablony.

## Mechanismus šablony (bez nové závislosti)
Vlastní malý engine nad python-docx (`export/doc_template.py`). docxtpl + jinja2 zamítnuty: dvě závislosti navíc
(i do PyInstaller balíčku), jinja v Wordu svádí k logice v šabloně a chybová hlášení jsou pro projektanta nečitelná;
potřebujeme jen pole, podmínku, opakování a vložení vygenerované tabulky.

- **Pole** `{{projekt.nazev}}`, `{{fve.p_dc_kwp}}` – kdekoli v textu, v buňkách tabulek, v záhlaví a zápatí. Tečková
  cesta do kontextu; chybějící / prázdný údaj → „neuvedeno“, `{{cesta|výchozí}}` vlastní náhrada (`{{x|}}` = nic).
  Pole rozdělené Wordem do více runů se sloučí (formát odstavce podle prvního runu).
- **Řídicí odstavce** (celý odstavec = značka): `{% if cesta %}` / `{% if not cesta %}` / `{% if cesta == "vn" %}`,
  `{% else %}`, `{% endif %}`; `{% for x in seznam %}` … `{% endfor %}` (opakuje odstavce i tabulky mezi značkami,
  `{{x.pole}}`). Vnořování povoleno. Podmínkou se vynechá celá sekce, když model údaj nemá.
- **Vložené bloky** – odstavec `{{tabulka.<jméno>}}` / `{{blok.<jméno>}}` se nahradí tabulkou / více odstavci
  a tabulkami z modelu: `tabulka.` zakladni_udaje, stringy, stridace, jisteni_stringu, svodice, kabely, selektivita,
  listy, revize, zmenovy_list, zmeny; `blok.` kontrola_stringu, rozvadece (hlavička, oteplení, přístroje), vykazy
  (na šířku – patří na konec šablony). Neznámý / selhaný blok → „neuvedeno“, export nespadne.
- **Číslování kapitol** `{{§}}` v nadpisu → 1, 1.1 … podle úrovně (vynechaná sekce nevytvoří mezeru v číslování).

## Šablony a složky (jako makra / topologie)
`library/doc_templates.py`: vestavěné `library/builtin/doc_templates/`, sdílené `<shared_library_dir>/doc_templates/`,
vlastní `~/.envocad/doc_templates/`; stejné jméno souboru přebíjí. Formáty `.docx` (firemní šablona – styly, logo,
záhlaví) a `.md` (zdroj vestavěných šablon: `#` nadpisy, `-` odrážky, prázdný řádek = odstavec; převede se do
docx a pak stejně vyplní; `@include _cast.md` vloží společnou část, soubory `_…` se nenabízejí). Vestavěné:
`tz.md`, `dsps.md` se společným `_jadro.md` a `_hlavicka.md`. Druh (TZ / DSPS) podle předpony názvu `tz*` / `dsps*`,
jiné se nabídnou u obou. GUI umí uložit vestavěnou šablonu jako .docx – základ firemní šablony.

## Kontext z modelu (`export/tz_data.py`, bez Qt)
Jen údaje, které model má; nic se nedopočítává odhadem, co chybí, je `None` (→ „neuvedeno“ nebo vynechaná sekce).
- `projekt`: nazev, investor, misto, zakazka, zpracoval, datum, revize, objekt (meta `building`), firma; `dnes`, `druh`.
- `fve`: p_dc_kwp, p_ac_kw, pomer_dc_ac, moduly_pocet, modul_typ, modul_p_w, stringy_pocet, stridace_pocet,
  stridace_popis, hybrid, faze, optimizery_pocet, optimizer_typ, baterie, baterie_kwh, baterie_kw, zalohovani.
- `topologie`: id, retezec (meta `topology_chain`), uroven (nn/vn). Seznamy pro `for`: `rozvadece` (oznaceni, nazev,
  sit, un, in_, skrin, rozmery, kryti, icw, otepleni), `stridace`, `listy`, `revize`, `zmenovy_list`.
- `dc`: t_min, t_max, t_predpoklad, uoc_max_v, umpp_min_v, soustava, sit, jisteni_stringu, svodice, kabely, vyhovuje,
  chybi_1500.
- `ac`: hlavni_vypinac, jisteni_stridacu, vyvod_fve, kabely, svodice, chranice, selektivita.
- `ds`: distributor, napeti, uroven, uroven_text, mereni, hranice (HDS `boundary`), hds, transformator, stanice, rvn,
  kabel, hlavni_jisteni.
- `ochrana.sit` (sítě z hlaviček rozvaděčů), `sitova_ochrana` (hranice_kwp, pozadovana, stav, nastaveni, pusobi_na),
  `uzemneni` (hop, vodic), `zkrat` (ik_ka, zdroj – `ratings.upstream_ik`), `vypocty` (kabely_pocet, nevyhovuje, du_max).
- `meta.<klíč>` – libovolné metadato projektu (vlastní pole šablony), `pole.<klíč>` – hodnoty z exportního dialogu.

## DSPS
Stejné jádro + `dsps`: datum_provedeni, revizni_zprava, zhotovitel (meta `dsps_date`, `dsps_inspection_report`,
`dsps_contractor` – řetězce, formát projektu se nemění), porovnano_s, zmeny_pocet, zmeny_souhrn; bloky
`tabulka.zmeny` (z `model/diff.diff_projects(projekt dle PD .ecp, skutečnost)`, bez posunů ve výkresu) a
`tabulka.zmenovy_list` (řádky `meta["changes"]`). Bez porovnávaného souboru se použije jen změnový list.

## GUI
Výstupy → „Technická zpráva…“ a „DSPS…“: dialog (`ui/doc_template_dialog.py`) – výběr šablony (vestavěná / sdílená /
vlastní / soubor .docx…), u DSPS soubor projektu dle PD a pole DSPS; „Uložit šablonu jako .docx…“. Pole DSPS
se do meta zapíší `SetProjectMetaCommand` (undo). `ui/dialogs.py` se nemění.

## Kompatibilita
`export_tz_docx(project, lib, path, template=None)` zůstává (vestavěná šablona; `template` = .docx/.md šablona EnvoCAD,
dřívější „podkladový“ .docx bez značek se vyplní celou vestavěnou osnovou za svůj obsah). Formát projektu beze změny.
