# Výkresový styl ENVO (z dodaných vzorů)

Zdroj: `Desktop/vzor/D.1.4.1 BD Ostrava-Poruba.dwg` (D.603.1 Jednopólové schéma – montáž), `1p schema - Nas svet.pdf`
(JPS pro distributora), `DPS vzor ENVO.dwg` (ZWCAD – načte se jen částečně, potřeba export do PDF/DXF).
Slouží jako zadání pro makra a generátor – výkresy ladí projektant, program je opakuje.

## Rozvaděč RFVE.DC
- Tok shora dolů; nad skříní FV panel („Fotovoltaický panel / 450Wp / 7x“), optimizér („TS4-A-O / Optimizér TIGO
  700W (1:1) / 7ks“), symbol bezdrátu.
- Na hraně skříně **štítek kabelu**: rámeček o 3 řádcích – číslo (`1.1`), název (`STRING 1.1`), typ (`2xFLEX-SOL 6`).
  Stejný štítek na vstupu i výstupu.
- Skříň čárkovaně, hlavička **svisle vlevo**: `RFVE.DC` (podtrženo) / `DC IT/ max. 1000VDC` / `Plastová skříň, nástěnná, IP44/20`.
- Číslování podle střídač.string: vstupní svorky `XSp1.1` (1, 2), pojistkové odpínače `FU1.1` (OPVF10-2, 32A (1000 VDC),
  PC10 20A pV, 20A), přepěťovka `SPD-DC1.1` (rámeček se 3 varistory +/PE/−, „SPD T1+T2 (DC) / FLP-PV1000 V/Y / 1000VDC“),
  výstupní svorky `XS1.1`.
- PE svodičů vodičem `H07V-K 16` na vodorovnou PE přípojnici dole přes celou skříň.

## Rozvaděč RFVE.AC (u rodinného domu RFVE)
- Označení v generátoru: AC rozvaděč FVE `RFVE.AC`, DC u technologie `RFVE.DC` (na střídač `RFVE.DC1`…), po trase
  `RDC1`…, hlavní rozvaděč nn u vn `HR`, rodinný dům jeden `RFVE` (`docs/NAVRH_TOPOLOGIE.md`, kap. 8 bod 9).
- Hlavička vlevo nahoře (ve vzoru): `RFVE2` / `3NPE, 50Hz, In = 3x63A, Ik''=10kA` / `Ocelplechová skříň, nástěnná, IP66/20`.
- Nahoře vodorovně **BLOKOVÉ SVORKY L1, L2, L3** (sběrnice), z ní dolů: ODPÍNAČ PŘEP. OCHRANY (80A gG PV22) → SPD.AC
  (SLP-275 V, SPD T2, Imax=40kA, Up≤1,5kV); ROZPADOVÉ MÍSTO KM.N0%; FA.N0% (LTN-6B-1 6A); FU.U-f (2A gG PV10) → U-f guard;
  HLAVNÍ JISTIČ (50B-3 40A). Fáze jednopólově (čárky pólů), N a PE jako vodorovné přípojnice dole s popisem na koncích.
- Vývod kabelu = „vidlička“ ze svorek N a PE do jedné čáry; štítky dole: `WL-STR / CYKY-J 5x16`, `WL.SIT / CYKY-J 5x16`,
  `WL.STOP / PraFlaDur-O 2x1,5`, `PPV.SPD.AC / H07V-K 16 zž`, `PPV.RFVE.AC / H07V-K 10 zž` (PPV = pospojování, čárkovaně).
- Tlačítko STOP FVE (1x rozpínací) pod skříní; DC pojistky FU1.1…FU1.4 stringů „SMĚR STŘÍDAČ“.

## JPS pro distributora („Náš svět“)
- String svisle jako řada modulů s přerušením „//“, nad ním optimizér; texty „Optimizéry / 700W / 20 kusů (1:1 na každý
  panel)“, „Fotovoltaické panely / LEAPTON SOLAR 450W / 20 kusů / 450Wp / Celkem 9,00 kWp“.
- Střídač: „Střídač - Hybridní / Growatt SPH-10KTL3 / 3L/N/PE/400V/15,2A/10kVA“; Rozpadové místo, Blokace (galvanická),
  QUIDO vysílač/přijímač, HDO, EMR 4Q, tabulka nastavení ochran (PPDS příl. 4), instalovaný a rezervovaný výkon,
  způsob provozu výrobny.

## Co už EnvoCAD dělá podle toho
- Štítky kabelů na přívodech/vývodech ve vícepólu (označení / název / typ), nadpis výkresu rozvaděče vlevo nahoře
  na každé straně (`switchboard_title`: označení, soustava, Un, In, Ik'', skříň, montáž, krytí z parametrů skříně).
- Proměnné maker `{i}` (střídač) a `{j}` (string u střídače) – vestavěná DC makra číslují `FU{i}.{j}`, `SPD-DC{i}.{j}`.
- PE svodičů na ekvipotenciální svorkovnici, sběrnice potenciálů s názvy na koncích.

## Zbývá (návrhy)
- Zobrazení AC rozvaděče „jednopólově se sběrnicí“ (fáze jednou čarou, N/PE přípojnice) jako alternativa k plnému vícepólu.
- Symbol stringu jako řada modulů s přerušením (JPS pro distributora), symbol optimizéru, bezdrát, QUIDO, U-f guard.
- Štítky kabelů i v JPS (rámeček místo textu u vodiče).
