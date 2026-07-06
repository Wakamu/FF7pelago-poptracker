"""Pixel coordinates for FF7 regions on images/worldmap.png (3200 x 2400)."""

from __future__ import annotations

MAP_WIDTH = 3200
MAP_HEIGHT = 2400

REGION_WORLD_COORDS: dict[str, tuple[int, int]] = {
    "Midgar (Opening)": (1970, 1230),
    "Midgar (Fields)": (2000, 1260),
    "Midgar Sector 5": (2000, 1230),
    "Kalm": (2190, 1180),
    "Mythril Mines": (2330, 1620),
    "Chocobo Farm": (2600, 1440),
    "Fort Condor": (2210, 1780),
    "Junon Lower": (1850, 1510),
    "Junon Upper": (1890, 1510),
    "Corel": (1190, 1320),
    "Gold Saucer Area": (1310, 1620),
    "Costa del Sol": (1530, 1310),
    "Mt. Corel": (1250, 1290),
    "Gongaga": (1230, 1920),
    "Cosmo Canyon": (970, 1830),
    "Nibelheim": (1000, 1430),
    "Mt. Nibel": (1020, 1330),
    "Rocket Town": (910, 1260),
    "Ancient Forest": (1000, 1880),
    "Wutai": (400, 930),
    "Chocobo Sage": (1590, 720),
    "Bone Village": (1690, 940),
    "Sleeping Forest": (1730, 880),
    "Forgotten Capital": (1740, 790),
    "Corel Valley": (1770, 860),
    "Great Glacier": (1480, 550),
    "Icicle Inn": (1400, 740),
    "Northern Crater": (1410, 350),
    "Northern Cave": (1410, 400),
    "Whirlwind Maze": (1460, 350),
    "Mideel": (2400, 2080),
    "Underwater Reactor": (1760, 1490),
    "Gelnika": (1450, 1590),
    "Shinra Mansion Basement": (960, 1400),
    "Temple of the Ancients": (1850, 1920),
    "Other Fields": (2238, 908),
    "Bosses": (960, 770),
}

WORLD_MAP_ID = "world"
WORLD_MAP_IMAGE = "images/worldmap.png"

def world_area_name(region: str) -> str:
    if region.startswith("Shops - "):
        return region.removeprefix("Shops - ")
    return region

def area_hub(area: str) -> tuple[int, int]:
    return REGION_WORLD_COORDS.get(area, REGION_WORLD_COORDS["Other Fields"])

def area_pin_size(check_count: int) -> int:
    if check_count >= 20: return 28
    if check_count >= 8: return 24
    if check_count >= 3: return 20
    return 18
