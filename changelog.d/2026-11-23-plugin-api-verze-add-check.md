- **Plugin API: verze API a kontroly pluginů** – `plugins.API_VERSION` a `REQUIRES_API` v pluginu (novější API = plugin
  se nenačte a okno to ohlásí); nové `ctx.add_check(fn)` přidá vlastní kontrolu do Kontroly (F7) a příkazu CHECKS,
  chyba pluginu se změní na nález místo pádu. Vzor `plugins_builtin/example_check.py`. Test `test_plugin_api.py`.
