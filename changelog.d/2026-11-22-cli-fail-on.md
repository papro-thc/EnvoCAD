- **CLI: návratový kód podle nálezů F7 (`--fail-on`)** – `python -m envocad.cmd … --fail-on chyba` vrátí kód 3,
  když kontrola F7 najde chybu, `--fail-on varování` i při varování (`info` nikdy); skript nebo agent tak pozná
  projekt s nálezy bez čtení textu. Bez volby se kód nemění, chyba příkazu (1) má přednost. `envocad/cmd/__main__.py`,
  `docs/MANUAL.md`, test `test_cmd_fail_on.py`.
