"""Svorky střídače mimo DC/AC: záložní výstup, generátor, komunikace a řízení výkonu (blok typu střídače).

Značka střídače (`project.inverter_symbol`) přidá vpravo pod AC port pro každou svorku z atributu `io` prvku
(„BACKUP BMS METER RS485 DRM“), a když atribut chybí, z profilu řady podle výrobce a typu (`PROFILES`); hybridní
střídač má pak vždy i záložní výstup BACKUP (vedle baterie BAT ze značky `fve.inverter_hybrid`).
Profily jsou orientační – podle datasheetů a instalačních návodů výrobce (`source`), čísla pinů a varianty trhu
(DRED jen AU/NZ, dálkové vypnutí jen EU…) je nutné ověřit v návodu konkrétního modelu. Ručně zadaný `io` má
přednost, prázdná mezera „-“ svorky vypne. Komunikační svorky jsou nepovinné (kontrola je nehlásí jako
nezapojené). Bez Qt."""
from __future__ import annotations

import re
from dataclasses import dataclass

# název svorky → (popis, výchozí žíly vodiče; None = výkonový AC výstup – žíly podle fází jako AC)
TERMINALS: dict[str, tuple[str, list[str] | None]] = {
    "BACKUP": ("záložní výstup AC (EPS / backup)", None),
    "GEN": ("vstup generátoru", None),
    "BMS": ("komunikace s baterií (BMS, CAN/RS485)", ["H", "L"]),
    "CAN": ("CAN (baterie, paralelní zapojení)", ["H", "L"]),
    "METER": ("elektroměr / CT v přípojném bodě (RS485)", ["A", "B"]),
    "RS485": ("RS485 / Modbus RTU (datalogger, EMS)", ["A", "B"]),
    "RS485-1": ("RS485 sběrnice 1", ["A", "B"]),
    "RS485-2": ("RS485 sběrnice 2", ["A", "B"]),
    "LAN": ("Ethernet", ["LAN"]),
    "DI": ("digitální vstupy – řízení výkonu (HDO, RCR, DRM)", ["DI"]),
    "DO": ("digitální / reléový výstup", ["DO"]),
    "DIDO": ("digitální vstupy a výstupy", ["DI", "DO"]),
    "DRM": ("řízení výkonu DRM / DRED", ["DRM"]),
    "RSD": ("dálkové vypnutí (remote shutdown)", ["RSD"]),
}
POWER_TERMINALS = {k for k, (_d, cores) in TERMINALS.items() if cores is None}


@dataclass(frozen=True)
class Profile:
    manufacturer: str
    pattern: str              # regulární výraz na typ (atribut `type`, objednací číslo), bez rozlišení velikosti
    io: str                   # svorky v pořadí shora dolů
    series: str
    source: str
    note: str = ""


PROFILES: tuple[Profile, ...] = (
    Profile("Huawei", r"^SUN2000-.*(KTL-M\d|MAP0|MB0)", "RS485-1 RS485-2 DI", "SUN2000 KTL-M1/M2/M3, MAP0",
            "Huawei SUN2000-(3KTL-10KTL)-M1 User Manual, kap. Connecting the Signal Cable (COM 16 pinů: RS485-1 "
            "kaskáda/SmartLogger, RS485-2 Smart Power Sensor / baterie, DI řízení výkonu); SUN2000-50KTL-M3 User "
            "Manual, kap. Connecting Signal Cables (RS485, Power Grid Scheduling)",
            "M1: baterie LUNA2000 na DC svorky BAT a RS485-2; M2/M3: piny DI/AI ověřit v návodu"),
    Profile("SolaX", r"^X3-ULT", "BACKUP BMS RS485 METER DRM DIDO", "X3-Ultra",
            "SolaX X3-ULTRA User Manual v14, kap. COM 1 (BMS, RS485, DRM), COM 2, Meter/CT, DIO; SolaX KB – RS485 "
            "na COM1 (dvě sběrnice)", "EPS = záložní výstup; generátor – ověřit v návodu"),
    Profile("SolaX", r"^X[13]-(HYBRID|HYB)", "BACKUP BMS METER RS485 DRM DIDO", "X1/X3-Hybrid G4",
            "SolaX X3-Hybrid G4 User Manual v8, kap. 5.5 Communication Connection; datasheet X3-HYB-G4 PRO "
            "(COM1: BMS, RS485, Meter/CT, paralelní; COM2: DI/DO, DRM)", "EPS = záložní výstup"),
    Profile("GoodWe", r"^GW\d+K?N?-?ET", "BACKUP BMS METER RS485 RSD", "ET / ET Plus+",
            "GoodWe ET datasheet (BMS RS485/CAN, Meter RS485, EMS RS485) a instalační návod ET Plus+ "
            "(DRED jen AU/NZ, dálkové vypnutí EU)"),
    Profile("GoodWe", r"^GW\d+K?T?-(DT|SDT)", "RS485 METER DRM", "DT / SDT G2",
            "GoodWe SDT G2 17–25K Quick Installation (COM2 RS485/Meter: piny 1–4 RS485, 5–6 elektroměr; COM3 DRED)",
            "svorku DRED nevyjímat – bez ní se střídač nepřipojí k síti"),
    Profile("Growatt", r"^MOD\s?\d", "RS485", "MOD-X / MOD-XH",
            "Growatt MOD 3-15KTL3-X rychlý návod (port RS485, USB pro datalogger)",
            "elektroměr a baterie (XH) – ověřit v návodu"),
    Profile("Sigenergy", r"^SIGEN", "RS485 LAN", "Sigen Hybrid / SigenStor",
            "Sigen Hybrid TP datasheet (WLAN / Fast Ethernet / RS485), návod Smart Breaker (RS485-1)",
            "záloha a generátor přes Sigen Gateway – kreslí se samostatně"),
    Profile("SolarEdge", r"^SE\d+K?-?R(WB|WS)", "RS485-1 RS485-2 LAN CAN", "Home Hub (třífázový)",
            "SolarEdge Home Hub datasheet (2× RS485, Ethernet, SolarEdge Home Network; baterie CAN)",
            "RS485-1 = elektroměr; záloha přes Backup Interface"),
    Profile("SolarEdge", r"^SE\d+K?", "RS485-1 RS485-2 LAN", "třífázové střídače SetApp",
            "SolarEdge Modbus / meter application note (RS485-1, RS485-2 pro SetApp, Ethernet)"),
)


def profile_for(manufacturer: str, type_: str) -> Profile | None:
    m = (manufacturer or "").strip().lower()
    t = (type_ or "").strip()
    for p in PROFILES:
        if p.manufacturer.lower() == m and re.search(p.pattern, t, re.IGNORECASE):
            return p
    return None


def parse_io(text: str) -> list[str]:
    """„BACKUP, BMS meter“ → ["BACKUP", "BMS", "METER"] (velkými, bez duplicit); „-“ = žádné svorky."""
    out: list[str] = []
    for tok in re.split(r"[\s,;]+", (text or "").strip()):
        tok = tok.upper()
        if tok and tok != "-" and tok not in out:
            out.append(tok)
    return out


def inverter_io(attrs: dict, hybrid: bool = False) -> list[str]:
    """Svorky střídače: atribut `io` (i „-“ = žádné), jinak profil podle výrobce a typu, jinak žádné. Hybridní
    střídač (`hybrid`) má bez ručního `io` vždy záložní výstup BACKUP – první, když ho profil řady neuvádí."""
    if (attrs.get("io") or "").strip():
        return parse_io(attrs["io"])
    p = profile_for(attrs.get("manufacturer", ""), attrs.get("type", ""))
    io = parse_io(p.io) if p else []
    if hybrid and "BACKUP" not in io:
        io.insert(0, "BACKUP")
    return io


def io_conductors(port: str) -> list[str] | None:
    """Výchozí žíly vodiče na svorku střídače; None = není komunikační svorka (výkonová nebo neznámá)."""
    entry = TERMINALS.get(port.upper())
    if entry is None or entry[1] is None:
        return None
    return list(entry[1])
