# Kontroly F7 z údajů artiklů

Roadmapa „Knihovna → program“: kontroly z dat artiklů. Kód `envocad/model/ratings.py` (bez Qt), napojení
`checks.rating_findings`; I2 v `calc.check_cables`, napětí DC v `calc.dc_voltages`.

## Co už bylo (nezdvojovat)
- `calc.check_cables` (`calc_cable`): proud vs. Iz, **In jištění ≤ Iz** kabelu JPS i vodiče listu rozvaděče s průřezem
  (jištění na konci vodiče, za vývodem bloku, `protect` bloku bez listu), úbytek.
- `check_selectivity` / `check_selectivity_tree`, `fuse_over_holder`, kontrola stringů vs. střídač a modul, oteplení.

## Zásady
- Údaj = neprázdný atribut prvku, jinak parametr artiklu (`Data`: atribut > `lib.component(component_id)`).
- Chybějící údaj nic nehlásí (nejvýš jedna INFO na list, kde jde o horní odhad / ověření).
- Ruční projekt bez artiklů a bez údajů: beze změny.

## Kontroly
1. **I2 ≤ 1,45·Iz** (doplněk `calc_cable`, chyba): I2/In podle přístroje – jistič EN 60898 1,45, MCCB 1,3, gPV 1,45,
   gG 2,1 / 1,9 / 1,6 (In < 4 / < 16 / ≥ 16 A), aM a neznámé bez kontroly. Hlásí se jen, když In ≤ Iz platí.
   Vodiče listu rozvaděče bez průřezu: nic (průřez výrobních dat se odvozuje z In – přetížený být nemůže).
2. **Zkrat** (jen AC jističe `mcb`/`mccb`/`rcbo`, Icu = `icu` / `icu_ka`):
   Ik rozvaděče = atribut bloku `ik_ka` > parametr skříně `ik_ka`; Icw = parametr skříně `icw` > atribut bloku.
   `sc_icu` (varování, kaskádu nehodnotíme) Icu < Ik; `sc_icw` (chyba) Icw < Ik; `sc_icu_icw` (varování) Icu < Icw,
   když Ik chybí. Horní odhad projektu `meta["ik_ka"]`, jinak Ik na svorkách nn TR = Sn / (√3·400 V·uk) →
   `sc_upstream` (INFO na list). Skříně v katalogu mají `ik` = mechanická odolnost IK, ne zkrat – nepoužívá se.
3. **Svodiče**: AC Uc ≥ 1,1·Uo (TN, TT), ≥ √3·Uo (IT); síť a Uo z parametrů listu `network` / `un` (AC část,
   výchozí TN 230 V) → `spd_uc` (chyba). DC: Ucpv (`ucpv`, artikl `ucpv_v`, dočasně „Ucpv NNN V“ z poznámky artiklu)
   ≥ Uoc stringu při t_min → `spd_ucpv` (varování); známé jen Uc pod Uoc → INFO „ověřte Ucpv“. Up ≤ Uw střídače
   (`uw` / `uw_kv`) → `spd_up`. Parametr skříně `wire_spd_lps` = yes a svodič bez typu 1 → `spd_lps` (INFO).
4. **Svorky**: průřez vodiče (`cross`) > `cross_max` prvku (i navázaný kabel JPS přívodu/vývodu) → `terminal_cross`
   (chyba); In svorky < In nejbližšího jištění (přes vodiče a svorky, ne PE) → `terminal_in` (varování).
5. **Un**: přístroje jištění/spínání/svorky (`un` / `un_v`, největší číslo „230/400“). AC: 3f (póly ≥ 3 nebo žíly
   L1–L3) ≥ sdružené, jinak ≥ Uo → `un_ac` (chyba); artikl s poznámkou „DC…“ v AC obvodu se nehodnotí. DC: ≥ Uoc
   stringů, které prvkem vedou, při t_min → `un_dc` (varování – závisí na návrhové teplotě).

Nálezy z Uoc při t_min (`un_dc`, `spd_ucpv`): bez `meta["pv_t_min"]` (předpoklad −10 °C) jen INFO na list.

## Napětí DC v místě prvku (`calc.dc_voltages`)
String → `_find_inverter` (s `trail`) → průchozí prvky JPS + bloky DC rozvaděčů s portem vstupu; v listu rozvaděče
prvky dosažitelné z přívodu (`_board_reach`, stop na přívodech/vývodech a sběrnicích). Napětí: n·Uoc(t_min),
režim optimizer `_uoc_capped`, fixed_voltage `u_string` střídače. Na prvku maximum ze stringů.

## Soustava DC 1000 / 1500 V (`model/dc_system.py`, `generator/dc_voltage.py`)
- Un DC přístroje: svodič Ucpv (`ucpv`, artikl `ucpv_v` / poznámka), jinak Uc; ostatní `un` / `un_v`.
- Asistent (průvodce) i F7 `calc_string`: n_max = ⌊min(Umax střídače, Umax systému modulu, Un DC přístrojů) / Uoc(t_min)⌋;
  průvodce z artiklů `dc.fuse_component` (jen s RFVE.DC) a `dc.spd_component`, projekt z prvků cesty stringu
  (`calc.string_device_limits`; v F7 jen se zadanou návrhovou t_min, jinak `un_dc` jako INFO). „Navrhnout stringy“ mez dodrží.
- Generátor po `pv.build`: `dc.system_v` > standard `dc_system_v` > 1000. 1500 → sada 1500 V; 1000 → když Uoc stringu
  > Un DC přístrojů a katalog má sadu 1500 V (2p `fve.fuse_disconnect` – 1p držák by ve výkazu chyběl – a svodič DC
  stejného typu), automaticky 1500 V; popis rozvaděče „max. 1500 V DC“. Bez sady: 1000 V, string ze zadání se nemění,
  log + F7 `dc_1500_missing` (INFO). Bez DC rozvaděčů se mez neuplatní.

## Otevřené / data
- Pojistkové vložky gPV 1500 V generátor jako artikl nedává (prvek nese jen In, vložka není samostatný prvek).
- Katalog má zatím jen 1p držáky 1500 V (ETI EFH 10/14) – automatika je nepoužije, chybí 2p (nebo dvojice 1p ve výkazu).
- Sloupce `ucpv_v` (DC SPD), `uw_kv` (střídače), `icw_ka`/`ipk_ka` (skříně) v katalogu chybí; Ik rozvaděče a
  `ik_ka` nejsou v dialogu skříně ani ve Vlastnostech projektu (jen atribut / parametr).
- Kaskáda (záložní jištění) a Ipk vs. ip se nehodnotí; umístění SPD (vstup do objektu) neznáme.
