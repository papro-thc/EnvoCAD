<!-- Vestavěná šablona dokumentace skutečného provedení (DSPS). Syntaxe: docs/design/tz_dsps.md. -->
#! Dokumentace skutečného provedení – {{projekt.nazev}}

Elektrotechnická část – fotovoltaická elektrárna

@include _hlavicka.md

# {{§}} Údaje o provedení

- Datum provedení: {{dsps.datum_provedeni}}
- Zhotovitel: {{dsps.zhotovitel}}
- Výchozí revize elektrické instalace: {{dsps.revizni_zprava}}

Dokumentace skutečného provedení vychází z projektové dokumentace a zachycuje stav instalace po dokončení. Změny
proti projektové dokumentaci jsou uvedeny v následující kapitole.

# {{§}} Změny proti projektové dokumentaci

{% if dsps.porovnano_s %}
Porovnáno s projektem: {{dsps.porovnano_s}}. Souhrn: {{dsps.zmeny_souhrn}}.
{% endif %}

{{tabulka.zmeny}}

{% if zmenovy_list %}
## {{§}} Změnový list

{{tabulka.zmenovy_list}}
{% endif %}

@include _jadro.md
