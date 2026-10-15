# Roadmap

## v0.1 – MVP: jednopólové schéma FVE  ← tento repozitář
- [x] Datový model (symbol, element, vodič, list, projekt), JSON projekt
- [x] Startovní knihovna symbolů FVE (~12 symbolů)
- [x] Import symbolů z DXF
- [x] Editor: vkládání z knihovny, posun, rotace, kreslení vodičů port→port, snap na mřížku, undo/redo
- [x] Panel vlastností (atributy elementu/vodiče)
- [x] Uložit/načíst projekt
- [x] Export DXF, PDF
- [ ] Rámeček a popisové pole listu (šablona ENVO)
- [ ] Automatické číslování označení (T1, F1, Q1…) s kontrolou duplicit

## v0.2 – Knihovna a výkazy
- [ ] Editor symbolů (porty, atributy) přímo v GUI
- [ ] Správa artiklů (výrobci, parametry, ceny), CSV import, přiřazení k elementu
- [ ] Výkaz materiálu (.xlsx) a seznam kabelů z modelu
- [ ] Hromadný import DXF knihoven výrobců (SMA, Huawei, SolarEdge, Eaton, Schneider, OEZ…)

## v0.3 – Rozvaděče
- [ ] Pohled rozvaděče: DIN lišty, moduly, rozměry přístrojů z artiklu
- [ ] Svorkovnice generované z vodičů
- [ ] Štítky, seznam přístrojů

## v0.4 – Vícelistové projekty a dokumentace
- [ ] Křížové odkazy mezi listy
- [ ] Generování částí TZ/DSPS z modelu (šablony)
- [ ] Sdílená knihovna pro celé ENVO (PostgreSQL nebo sdílený soubor)

## Později
- Další obory (HVAC, MaR, silnoproud budov)
- Kontroly (dimenzování kabelů, selektivita) – propojení s výpočty
