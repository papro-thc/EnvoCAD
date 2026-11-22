# Zdroje dat a inspirace (reverse engineering formátů)

## Otevřené knihovny symbolů

| Zdroj | Co | Licence | Stav v EnvoCAD |
|---|---|---|---|
| [QElectroTech elements](https://github.com/qelectrotech/qelectrotech-elements) | 8 800+ značek IEC 60617 (.elmt XML), vč. výrobců (ABB, Eaton, Schneider, Siemens) | použití ve schématech bez podmínek; šíření CC BY 3.0 | **importováno 673** (jednopól + vybrané vícepólové skupiny), `library/qet_import.py`, `builtin/qet/ATTRIBUTION.md` |
| KiCad symbol libs | elektronika, ne silnoproud | CC BY-SA 4.0 | nepoužito |

## EPLAN – formáty a komunitní nástroje

| Repozitář | K čemu | Co jsme si vzali |
|---|---|---|
| [covagashi/DataPortal-API](https://github.com/covagashi/DataPortal-API) | Dokumentace REST API EPLAN Data Portal (`api_doc.txt`): PAT token (`Authorization: Bearer PAT:…`), `GET /parts`, `/download/commercial_data/part` (CSV), `/download/dxf_data/part` (ZIP DXF), `/download/e3d_data/{macroVariantId}` (E3D), filtry `filter[...]`, stránkování `page[offset]` | formáty výstupů → `library/eplan_import.py` (CSV obchodních dat, DXF ZIP → footprinty) |
| [covagashi/ecad-view](https://github.com/covagashi/ecad-view) | Prohlížeč .epdz (7-zip: `manifest.db` SQLite + SVG stránky + AutomationML) a binární E3D (`docs/formats.md`) | struktura .epdz pro budoucí import existujících projektů (SVG stránky v mm, Y převrácené; `page_package`, `page_functions`) |
| [Suplanus/EPLAN-Scripting](https://github.com/Suplanus/EPLAN-Scripting), [Suplanus.Sepla](https://github.com/Suplanus/Suplanus.Sepla) | Skriptování P8 v C# – názvy vlastností artiklů `P_ARTICLE_*` (PARTNR, TYPENR, MANUFACTURER, DESCR1, WIDTH/HEIGHT/DEPTH, VOLTAGE, CURRENT, POWERDISSIPATION, MACRO…) | heuristické mapování sloupců v `eplan_import.py` |
| [covagashi/eplan-rag-mcp](https://github.com/covagashi/eplan-rag-mcp) | MCP server nad dokumentací EPLAN API | později pro agenty, pokud budeme číst P8 projekty |

**Licence dat z Data Portalu:** podléhá podmínkám EPLAN/ePulse (vazba na EPLAN produkty, od 2021 Subscription).
Importér slouží k převodu souborů, které si uživatel stáhne vlastním účtem; pro ostrou firemní knihovnu
používejte volně dostupné zdroje níže.

## Data výrobců mimo EPLAN (právně čisté)

- **ETIM / BMEcat** – strukturované katalogy (XML) pro velkoobchod: OEZ, Hager, Eaton, Schneider, ABB je poskytují
  (často ke stažení na webu výrobce v sekci „Data pro partnery“ / „Produktová data“). Stav: parser hotov (`library/bmecat_import.py`, menu Knihovna → Importovat artikly z BMEcat); ETIM třída a vlastnosti se zatím jen uloží do parametrů, mapování ETIM → parametry knihovny je další krok. Katalogy se do gitu nedávají.
- **PDF katalogy** – OEZ Katalog Minia / 3VA Parametry (rozměry, ztrátové výkony), Hager, Eaton xPole, Schneider
  Acti9, ABB System pro M compact. Agenti `data-entry` je přepíší do CSV (čtou PDF přímo).
- **DXF/STEP** výrobců (OEZ „CAD data“, Hager, Eaton) → footprinty přes `dxf_import.py`.
- **Datasheety střídačů a modulů** – SMA, Huawei, SolarEdge, Fronius, SolaX, GoodWe; Jinko, Longi, Trina, JA.

## Další inspirace pro editor

- [storytold/cadcraft](https://github.com/storytold/cadcraft) – „každá akce je příkaz“, příkazový řádek jako AutoCAD, oddělené jádro/UI, rotující logy.
- QElectroTech – kolekce prvků, formát `.elmt`, vícejazyčné názvy, `dynamic_text` pro popisky.
