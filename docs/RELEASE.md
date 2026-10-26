# Vydání verze a aktualizace

EnvoCAD se kolegům aktualizuje jen na **vydané verze** – git tagy `vX.Y.Z` na `main`. Rozpracovaný `main` ani
vývojové větve se nikomu automaticky nenabídnou. Logika je v `envocad/updater.py` (bez Qt), dialogy
v `envocad/ui/update_prompt.py`, vydání dělá `tools/release.py`.

## Jak se aktualizuje

**Klon repozitáře** (`scripts\run.cmd`, `run.ps1`, `run.sh`):

1. spouštěč zavolá `python -m envocad.updater check` – porovná **lokální** tagy s běžící verzí (start nečeká na síť);
2. je-li novější tag, zeptá se „Aktualizovat / Teď ne“ (s výpisem z CHANGELOG); „Teď ne“ = znovu za 24 h;
3. bez souhlasu spustí na pozadí `git fetch --tags`, takže nová verze se nabídne při **druhém** startu po vydání;
4. po souhlasu `python -m envocad.updater apply` (nový proces bez Qt): `git switch --detach vX.Y.Z`,
   při změně `pyproject.toml` `pip install -e .`; když pip selže, vrátí původní stav;
5. program po startu ukáže výsledek ve stavovém řádku (chybu dialogem).

Aktualizace se nabídne jen, když je pracovní strom čistý (nesledované soubory nevadí), HEAD je na `main` nebo na
tagu a je předkem nového tagu. Vývojář na své větvi nebo s commity navíc na `main` dotaz nedostane.

**Samostatná aplikace** (PyInstaller, bez Pythonu) nainstalovaná ze sdílené složky:

- instalace: kolega spustí `Instalovat EnvoCAD.cmd` ze sdílené složky vydání → `%LOCALAPPDATA%\Programs\EnvoCAD\`
  (`versions\<verze>\`, `current.txt`, spouštěč `EnvoCAD.cmd`, zástupce na ploše a ve Startu, `update_source.txt`);
- při startu aplikace přečte `latest.json` ze sdílené složky (nejdéle 3 s), nabídne novou verzi, zkopíruje ZIP
  s průběhem, ověří SHA-256, rozbalí vedle běžící verze, přepne `current.txt` a spustí novou verzi; starší verze
  (kromě právě běžící) smaže.

**Vypnutí:** `"auto_update": false` v `~/.envocad/settings.json`, nebo proměnná `ENVOCAD_NO_UPDATE=1`.
Jiná sdílená složka: `"update_dir": "\\\\server\\envocad\\release"`.

**Návrat na předchozí verzi** (klon): `.venv\Scripts\python.exe -m envocad.updater rollback`.
Stav: `python -m envocad.updater status`. Log: `~/.envocad/log/update.log`, stav: `~/.envocad/update.json`.

## Jak vydat verzi

```
python tools/release.py prepare 0.12.0   # verze v pyproject.toml + envocad/__init__.py; záznamy z changelog.d/
                                         # + „## Nevydáno“ → „## 0.12.0 – datum“ (soubory changelog.d/ smaže)
# zkontrolovat CHANGELOG, commit „Vydání 0.12.0“, PR do main, merge
git switch main && git pull
python tools/release.py tag              # ověří main = origin/main, verze, CHANGELOG, pytest + ruff; tag v0.12.0 + push
python tools/release.py publish \\server\envocad\release
                                         # PyInstaller z tagu, ZIP + latest.json + instalátor do sdílené složky
```

`publish` zapisuje `latest.json` až po zkopírování ZIPu, takže aplikace nikdy nevidí poloviční vydání.

Změna formátu projektu (`FORMAT_VERSION`) patří do vydání vždy – starší verze projekt z novější neotevře a hláška
uživateli poradí aktualizovat.
