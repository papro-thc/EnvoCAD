<!-- Společné jádro TZ a DSPS. Údaj, který model nemá, se vypíše jako „neuvedeno“ nebo se sekce vynechá. -->
# {{§}} Identifikační údaje

- Stavba: {{projekt.nazev}}
- Místo stavby: {{projekt.misto}}
- Investor: {{projekt.investor}}
- Číslo zakázky: {{projekt.zakazka}}
- Druh objektu: {{projekt.objekt}}
- Zpracovatel dokumentace: {{projekt.firma}}, {{projekt.zpracoval}}
- Datum: {{projekt.datum}}

# {{§}} Předmět dokumentace a podklady

Předmětem dokumentace je elektrotechnická část fotovoltaické elektrárny (FVE) o instalovaném výkonu
{{fve.p_dc_kwp}} kWp (DC) a {{fve.p_ac_kw}} kW (AC) pracující paralelně s distribuční soustavou (DS).
Údaje v této zprávě jsou převzaty z výkresové části (model EnvoCAD); údaje, které výkresová část neobsahuje,
jsou označeny „neuvedeno“ a doplní je projektant.

Návrh vychází zejména z ČSN 33 2000-7-712 (fotovoltaické napájecí systémy), ČSN 33 2000-4-41, ČSN 33 2000-4-43,
ČSN 33 2000-5-52, ČSN 33 2000-5-54, ČSN 33 2000-5-534, ČSN EN 61439-1, -2, ČSN EN 62305, Pravidel provozování
distribučních soustav (PPDS, příloha 4), ČSN EN 50549-1, -2 a podnikových norem PNE pro připojení výroben.

# {{§}} Základní údaje FVE

- Instalovaný výkon DC: {{fve.p_dc_kwp}} kWp
- Výkon střídačů AC: {{fve.p_ac_kw}} kW (poměr DC/AC {{fve.pomer_dc_ac}})
- Fotovoltaické moduly: {{fve.moduly_pocet}} ks, typ {{fve.modul_typ}}, {{fve.modul_p_w}} Wp
- Počet stringů: {{fve.stringy_pocet}}
- Střídače: {{fve.stridace_pocet}} ks – {{fve.stridace_popis}}, {{fve.faze}}
{% if fve.optimizery_pocet %}
- Optimizéry: {{fve.optimizery_pocet}} ks, typ {{fve.optimizer_typ}}
{% endif %}
{% if fve.baterie %}
- Akumulace: {{fve.baterie}}
{% endif %}
{% if fve.zalohovani %}
- Záložní napájení: hybridní střídač s výstupem pro zálohované okruhy (EPS)
{% endif %}

## {{§}} Údaje pro žádost o připojení

{{tabulka.zakladni_udaje}}

# {{§}} Topologie a řetězec rozvaděčů

{% if topologie.retezec %}
Výkonový řetězec FVE od stringů k distribuční soustavě: {{topologie.retezec}}.
{% else %}
Řetězec rozvaděčů: neuvedeno.
{% endif %}

{% if rozvadece %}
Rozvaděče s výkresem:
{% for r in rozvadece %}
- {{r.nazev}} – soustava {{r.sit}}, {{r.un}}; oteplení: {{r.otepleni}}
{% endfor %}
{% endif %}

# {{§}} Stejnosměrná (DC) část

Moduly jsou zapojeny do {{fve.stringy_pocet}} stringů. Napětí stringů je ověřeno pro návrhové teploty článků
{{dc.t_min}} °C (Uoc) a {{dc.t_max}} °C (Umpp) dle ČSN 33 2000-7-712.
{% if dc.t_predpoklad %}
Nejnižší návrhová teplota není ve vlastnostech projektu zadána – použita výchozí hodnota programu, projektant ji
ověří pro lokalitu stavby.
{% endif %}

- Nejvyšší napětí naprázdno stringu Uoc při {{dc.t_min}} °C: {{dc.uoc_max_v}} V
- Nejnižší napětí Umpp při {{dc.t_max}} °C: {{dc.umpp_min_v}} V
- Soustava DC: {{dc.soustava}}, {{dc.sit}}
- Výsledek kontroly stringů: {{dc.vyhovuje}}
- Kabely DC: {{dc.kabely}}
{% if dc.chybi_1500 %}
- Soustava 1500 V DC nepoužita – v katalogu chybí: {{dc.chybi_1500}}
{% endif %}

## {{§}} Fotovoltaické pole

{{tabulka.stringy}}

## {{§}} Kontrola stringů proti střídači

{{blok.kontrola_stringu}}

## {{§}} Jištění stringů

{% if dc.jisteni_stringu %}
Stringy jsou jištěny pojistkami: {{dc.jisteni_stringu}}.

{{tabulka.jisteni_stringu}}
{% else %}
Jištění stringů pojistkami gPV není ve výkresové části navrženo.
{% endif %}

# {{§}} Střídače a akumulace

{{tabulka.stridace}}

# {{§}} Střídavá (AC) část

- Jištění přívodů střídačů: {{ac.jisteni_stridacu}}
- Hlavní vypínač výrobny: {{ac.hlavni_vypinac}}
- Vývod FVE: {{ac.vyvod_fve}}
- Kabely AC: {{ac.kabely}}
- Selektivita jištění: {{ac.selektivita}}

## {{§}} Selektivita

{{tabulka.selektivita}}

# {{§}} Připojení k distribuční soustavě

{% if ds.uroven %}
Výrobna je připojena k distribuční soustavě {{ds.uroven_text}} a pracuje paralelně s DS. Podmínky připojení
stanoví provozovatel DS ve smlouvě o připojení.
{% endif %}

- Provozovatel DS: {{ds.distributor}}
- Napěťová soustava: {{ds.napeti}}
- Hlavní jištění objektu: {{ds.hlavni_jisteni}}
- Měření: {{ds.mereni}}
- Hranice vlastnictví: {{ds.hranice}}
- Připojovací kabel: {{ds.kabel}}
{% if ds.hds %}
- Hlavní domovní skříň: {{ds.hds}}
{% endif %}

{% if ds.uroven == "vn" %}
## {{§}} Přípojka vn a transformace

- Transformátor: {{ds.transformator}}
- Stanice: {{ds.stanice}}
- Rozvaděč vn: {{ds.rvn}}
{% endif %}

# {{§}} Ochrana před úrazem elektrickým proudem

Ochrana je navržena dle ČSN 33 2000-4-41 a ČSN 33 2000-7-712.

- Soustava AC (dle hlaviček rozvaděčů): {{ochrana.sit}}
- Soustava DC: {{dc.sit}}
{% if ac.chranice %}
- Proudové chrániče: {{ac.chranice}}
{% endif %}

Na straně AC se uplatní ochrana automatickým odpojením od zdroje; na straně DC se dle ČSN 33 2000-7-712
přednostně použije ochrana dvojitou nebo zesílenou izolací.

# {{§}} Ochrana před přepětím

- Svodiče přepětí DC: {{dc.svodice}}
- Svodiče přepětí AC: {{ac.svodice}}

{{tabulka.svodice}}

{% if sitova_ochrana.pozadovana %}
# {{§}} Síťová ochrana

Instalovaný výkon {{fve.p_dc_kwp}} kWp převyšuje hranici {{sitova_ochrana.hranice_kwp}} kWp – výrobna musí mít
síťovou ochranu dle PPDS (příloha 4) a ČSN EN 50549-1.

- Stav v projektu: {{sitova_ochrana.stav}}
- Působí na vazební prvek: {{sitova_ochrana.pusobi_na}}
- Nastavení: {{sitova_ochrana.nastaveni}}
{% else %}
{% if sitova_ochrana.stav %}
# {{§}} Síťová ochrana

- Stav v projektu: {{sitova_ochrana.stav}}
- Nastavení: {{sitova_ochrana.nastaveni}}
{% endif %}
{% endif %}

# {{§}} Uzemnění a pospojování

{% if uzemneni.hop %}
- Hlavní ochranná přípojnice: {{uzemneni.hop}}
- Vodič ochranného pospojování: {{uzemneni.vodic}}
{% else %}
Uzemnění a pospojování: neuvedeno.
{% endif %}

# {{§}} Výpočty

## {{§}} Kabely a jištění

{{tabulka.kabely}}

{% if vypocty.nevyhovuje %}
Nevyhovující kabely (doplnit nebo opravit údaje): {{vypocty.nevyhovuje}}.
{% endif %}
{% if vypocty.du_max %}
Největší vypočtený úbytek napětí: {{vypocty.du_max}} %.
{% endif %}

{% if zkrat.ik_ka %}
## {{§}} Zkratové poměry

Počáteční souměrný zkratový proud Ik'' = {{zkrat.ik_ka}} kA {{zkrat.zdroj}}. Vypínací schopnost přístrojů
a zkratová odolnost rozvaděčů musí být nejméně tato hodnota.
{% endif %}

# {{§}} Rozvaděče a oteplení

{{blok.rozvadece}}

# {{§}} Výkaz materiálu

Výkaz materiálu a seznam kabelů jsou přílohou této zprávy (kapitola Přílohy).

# {{§}} Seznam výkresů

{{tabulka.listy}}

# {{§}} Revize dokumentace

{{tabulka.revize}}

# {{§}} Přílohy

{{blok.vykazy}}
