# Symboly QElectroTech

Soubory `qet.*.json` v této složce jsou **upravené** prvky z kolekce QElectroTech
(https://github.com/qelectrotech/qelectrotech-elements), autor: The QElectroTech team a přispěvatelé
(uvádí-li originál autora, je v popisu symbolu; jinak platí The QElectroTech team a přispěvatelé).
Převzat je jen výběr z kolekce (673 značek).

Tato složka **není pod licencí MIT** jako zbytek repozitáře.

## Licence

Kolekce je poskytována „tak jak je“, bez záruky. Podmínky jsou v souboru `ELEMENTS.LICENSE`:
https://github.com/qelectrotech/qelectrotech-elements/blob/main/ELEMENTS.LICENSE

- použití, úprava a začlenění prvků do elektrických schémat je bez podmínek;
- šíření celé kolekce nebo její části (i upravené) mimo schéma podléhá licenci **CC BY 3.0**
  (https://creativecommons.org/licenses/by/3.0/): je nutné uvést autora, odkaz na licenci a u odvozeného díla
  uvést, že bylo upraveno.

EnvoCAD značky šíří s tímto uvedením autorství.

## Úpravy

Značky jsou oproti originálu upravené převodem `envocad/library/qet_import.py` a skriptem
`tools/recategorize_qet.py`:

- převod XML `.elmt` do formátu JSON používaného v EnvoCAD;
- měřítko 10 px → 2,5 mm (SCALE 0,25), osa Y převrácena (Y nahoru), počátek zůstává v hotspotu;
- porty (terminal) zaokrouhlené na mřížku 2,5 mm;
- elipsy a eliptické oblouky nahrazeny lomenou čárou;
- `dynamic_text` se nepřebírá (jen poloha popisku), přidány atributy `ref` a `type`;
- texty přeformátovány (velikost, zarovnání vlevo, jeden řádek), mnohoúhelníky převedeny na lomenou čáru;
- primitiva s neplatnými souřadnicemi jsou vynechána;
- název z české verze originálu (jinak en/fr), u vícepólových značek přípona „[vícepól]“; vlastní kategorie
  a ID `qet.*`.

## Zákaz použití pro strojové učení

Licence kolekce **nepovoluje** použít kolekci ani související soubory (tedy ani tyto značky) jako vzorová
data pro tvorbu modelů strojového učení. Značky se nesmí použít k tréninku takových modelů.
