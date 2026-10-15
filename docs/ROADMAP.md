# Roadmap

## v0.1 – MVP: jednopólové schéma FVE  ← tento repozitář
- [x] Datový model (symbol, element, vodič, list, projekt), JSON projekt
- [x] Startovní knihovna symbolů FVE (~12 symbolů)
- [x] Import symbolů z DXF
- [x] Editor: vkládání z knihovny, posun, rotace, kreslení vodičů port→port, snap na mřížku, undo/redo
- [x] Panel vlastností (atributy elementu/vodiče)
- [x] Uložit/načíst projekt
- [x] Export DXF, PDF
- [x] Tmavý režim
- [x] Dialog parametrů při vložení prvku/vodiče
- [ ] Rámeček a popisové pole listu (šablona ENVO)
- [ ] Příkazový řádek (styl ZWCAD/CADCraft): každá akce = příkaz, ovladatelné i z agentů
- [ ] Automatické číslování označení (T1, F1, Q1…) s kontrolou duplicit

## v0.2 – Knihovna a výkazy
- [ ] Editor symbolů (porty, atributy) přímo v GUI
- [x] Artikly: CSV formát, validátor, výběr v dialogu prvku, propsání parametrů, skříně z knihovny
- [x] Data z PDF katalogů: OEZ Minia + 3VA + OPVP + RZA, Eaton xPole/xComfort, Schneider skříně, BMR (460 artiklů)
- [ ] Doplnit: ABB, FV moduly, SolarEdge/Fronius/GoodWe, Pv pro 3VA (OEZ „3VA Parametry“), OPVF10 DC – z dalších PDF (web je v prostředí blokovaný)
- [ ] Knihovna → program (analýza 10/2026): 222 artiklů bez rozměrů/modulů, 138 z 266 jističů/chráničů bez Pv, 0 footprintů
  - [ ] rozměry a Pv z Katalogu Minia a „3VA Parametry“ (PDF od uživatele), rozměry svorek Bečov z technických listů
  - [ ] svorkovnice v rozložení: šířka = `width_mm` artiklu × počet svorek (+ koncové desky), místo ručních modulů
  - [ ] generické footprinty podle kategorie a rozměrů (kompaktní jistič = obdélník š×v, svorka = úzký obdélník), ne jen moduly
  - [ ] kontroly z artiklů: In jističe vs. průřez vodiče (základní tabulka), Icu vs. Icw rozvaděče, Uc svodiče vs. síť
- [x] Značky z QElectroTech (673), importéry EPLAN CSV/XML/DXF, pluginy a uživatelské balíčky
- [ ] BMEcat/ETIM importér (volná data výrobců)
- [ ] Footprinty z DXF výrobců (OEZ, Hager) a editor portů importovaných symbolů
- [ ] Ceny v artiklech + výkaz s cenami
- [ ] Výkaz materiálu (.xlsx) a seznam kabelů z modelu
- [ ] Hromadný import DXF knihoven výrobců (SMA, Huawei, SolarEdge, Eaton, Schneider, OEZ…)

## v0.2 – Rozvaděče  ← hotovo v základu
- [x] List rozvaděče z bloku, šablony AC/DC
- [x] Pohled rozložení: DIN lišty, moduly, přetahování
- [x] Výkazy xlsx (přístroje, BOM, kabely, svorkovnice, štítky), protokol kusového ověření docx
- [ ] Šablona ENVO pro protokol (loga, hlavička) – doplnit po dodání .docx
- [x] Parametry skříně v panelu rozložení, odhad oteplení (IEC 60890)
- [ ] Rozměry a ztrátové výkony přístrojů z artiklu (ne ručně v atributech `modules`, `p_loss_w`)
- [ ] Oteplení: přesné tabulky IEC 60890 (k, c, d) místo aproximace; ventilace

## v0.6 – Vícepól  ← hotovo v základu
- [x] Vícepólový pohled nad stejným listem (Ctrl+M / Ctrl+J), žíly z `Wire.conductors`, přiřazení svorek per žíla (`Wire.terminals`, Ctrl+T)
- [x] Automatické číslování svorek na svorkovnicích (Úpravy → Očíslovat svorky)
- [x] Svorkovnice jako v EPLAN: skupiny svorek s čísly, můstky (dialog, vícepól, JPS, výkaz); šablony bez sběrnice
- [ ] Artikl svorky → šířka v rozložení (svorkovnice na DIN liště podle `width_mm`), můstky jako artikl (ZQV…) do BOM
- [ ] Vlastní rozmístění ve vícepólu (dnes jen roztažené pozice z JPS ×2), ruční lomy žil
- [ ] Vícepólové značky z knihovny (QET `qet.ap.*`) místo opakování jednopólové značky; společná spoušť/vazba pólů
- [ ] Export DXF vícepólu (PDF už funguje)

## v0.4 – Vícelistové projekty a dokumentace
- [ ] Křížové odkazy mezi listy
- [ ] Generování částí TZ/DSPS z modelu (šablony)
- [ ] Sdílená knihovna pro celé ENVO (PostgreSQL nebo sdílený soubor)

## Odloženo (analýza 10/2026 – nebrzdí práci)
- Příkazový řádek (styl ZWCAD/CADCraft) – až bude potřeba ovládat program z agentů
- BMEcat/ETIM importér – až budou soubory od výrobců
- Vlastní vícepólové značky z QET (`qet.ap.*`) – opakovaná jednopólová značka je čitelná a EPLAN to kreslí podobně
- Rust – ne

## Později
- Další obory (HVAC, MaR, silnoproud budov)
- Kontroly (dimenzování kabelů, selektivita) – propojení s výpočty
