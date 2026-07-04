"""Pixel coordinates for FF7 regions on images/worldmap.png (3200 x 2400)."""

from __future__ import annotations

MAP_WIDTH = 3200
MAP_HEIGHT = 2400

# Tuned to the labeled world map art shipped with this pack.
REGION_WORLD_COORDS: dict[str, tuple[int, int]] = {
    "Midgar (Opening)": (2005, 1161),
    "Midgar (Fields)": (2005, 1194),
    "Midgar Sector 5": (2037, 1162),
    "Kalm": (2241, 1112),
    "Mythril Mines": (2342, 1458),
    "Chocobo Farm": (2650, 1322),
    "Fort Condor": (2232, 1616),
    "Junon Lower": (1888, 1443),
    "Junon Upper": (1890, 1402),
    "Corel": (1164, 1212),
    "Gold Saucer Area": (1288, 1508),
    "Costa del Sol": (1532, 1214),
    "Mt. Corel": (1334, 1260),
    "Gongaga": (1204, 1740),
    "Cosmo Canyon": (916, 1628),
    "Nibelheim": (980, 1304),
    "Mt. Nibel": (992, 1200),
    "Rocket Town": (872, 1172),
    "Ancient Forest": (964, 1716),
    "Wutai": (344, 880),
    "Chocobo Sage": (1592, 676),
    "Bone Village": (1704, 876),
    "Sleeping Forest": (1724, 828),
    "Forgotten Capital": (1752, 744),
    "Corel Valley": (1774, 800),
    "Great Glacier": (1476, 516),
    "Icicle Inn": (1384, 684),
    "Northern Crater": (1418, 360),
    "Northern Cave": (1420, 408),
    "Whirlwind Maze": (1464, 360),
    "Mideel": (2427, 1927),
    "Underwater Reactor": (1780, 1364),
    "Gelnika": (1440, 1470),
    "Shinra Mansion Basement": (1024, 1304),
    "Temple of the Ancients": (1848, 1744),
    "Other Fields": (2106, 1092),
    "Bosses": (904, 564),
    # Shop tabs share their region's hub with a small eastward shift applied in code.
}

WORLD_MAP_ID = "world"
WORLD_MAP_IMAGE = "images/worldmap.png"


def world_area_name(region: str) -> str:
    """Map AP regions (and shop tabs) to a single world-map pin."""
    if region.startswith("Shops - "):
        return region.removeprefix("Shops - ")
    return region


def area_hub(area: str) -> tuple[int, int]:
    return REGION_WORLD_COORDS.get(area, REGION_WORLD_COORDS["Other Fields"])


def area_pin_size(check_count: int) -> int:
    if check_count >= 20:
        return 28
    if check_count >= 8:
        return 24
    if check_count >= 3:
        return 20
    return 18
