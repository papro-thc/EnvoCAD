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
- [ ] Správa artiklů (výrobci, parametry, ceny), CSV import, přiřazení k elementu
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

## v0.3 – Vícepól
- [ ] Vícepólový pohled nad stejným listem (přepínání JPS ↔ vícepól), přiřazení svorek per žíla (`Wire.terminals`)
- [ ] Automatické číslování svorek na svorkovnicích

## v0.4 – Vícelistové projekty a dokumentace
- [ ] Křížové odkazy mezi listy
- [ ] Generování částí TZ/DSPS z modelu (šablony)
- [ ] Sdílená knihovna pro celé ENVO (PostgreSQL nebo sdílený soubor)

## Později
- Další obory (HVAC, MaR, silnoproud budov)
- Kontroly (dimenzování kabelů, selektivita) – propojení s výpočty
