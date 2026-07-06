"""Free Roam access rules for FF7pelago, mirroring worlds/ff7/__init__.py."""

from __future__ import annotations

# AP location code -> required item name (Kalm Traveler trades, etc.)
LOCATION_ITEM_GATES: dict[int, str] = {
    200300: "Guide Book",
    200301: "Earth Harp",
    200302: "Earth Harp",
    310092: "Earth Harp",
    200304: "Desert Rose",
    310070: "Tifa",
    200337: "Leviathan Scales",
    200338: "Leviathan Scales",
    200346: "Leviathan Scales",
}

BOSS_TIERS: dict[str, str] = {
    "Defeat Ultimate Weapon": "ocean",
    "Defeat Emerald Weapon": "underwater",
    "Defeat Ruby Weapon": "ocean",
}

PARTY_MEMBERS = ("Barret", "Tifa", "Aerith", "Red XIII", "Cait Sith", "Cid")
HUGE_MATERIA = (
    "Huge Materia (Fort Condor)",
    "Huge Materia (Corel)",
    "Huge Materia (Underwater)",
    "Huge Materia (Rocket)",
)

TRAVERSAL_ITEMS = {
    "green": "Green Chocobo",
    "blue": "Blue Chocobo",
    "black": "Black Chocobo",
    "gold": "Gold Chocobo",
    "highwind": "Highwind",
    "submarine": "Submarine",
    "gold_ticket": "Gold Ticket",
    "key_sector_5": "Key to Sector 5",
    "basement_key": "Basement Key",
    "lunar_harp": "Lunar Harp",
    "snowboard": "Snowboard",
    "glacier_map": "Glacier Map",
}


def build_item_codes(items: list[dict]) -> dict[str, str]:
    return {item["name"]: f"item_{item['code']}" for item in items}


def rule_or(*codes: str) -> list[list[str]]:
    return [[code] for code in codes]


def rule_and(*codes: str) -> list[list[str]]:
    return [[",".join(codes)]]


def rule_each_with_all(bases: tuple[str, ...], *required: str) -> list[list[str]]:
    return [[",".join((base, *required))] for base in bases]


def endgame_item_codes(item_codes: dict[str, str]) -> list[str]:
    return [
        item_codes[TRAVERSAL_ITEMS["highwind"]],
        *[item_codes[name] for name in PARTY_MEMBERS],
        *[item_codes[name] for name in HUGE_MATERIA],
    ]


def build_rule_sets(item_codes: dict[str, str]) -> dict[str, list[list[str]]]:
    def ref(name: str) -> str:
        return item_codes[name]

    mountain = (
        ref(TRAVERSAL_ITEMS["green"]),
        ref(TRAVERSAL_ITEMS["black"]),
        ref(TRAVERSAL_ITEMS["gold"]),
        ref(TRAVERSAL_ITEMS["highwind"]),
    )
    ocean = (
        ref(TRAVERSAL_ITEMS["blue"]),
        ref(TRAVERSAL_ITEMS["black"]),
        ref(TRAVERSAL_ITEMS["gold"]),
        ref(TRAVERSAL_ITEMS["highwind"]),
    )
    sub = (
        ref(TRAVERSAL_ITEMS["submarine"]),
        ref(TRAVERSAL_ITEMS["blue"]),
        ref(TRAVERSAL_ITEMS["black"]),
        ref(TRAVERSAL_ITEMS["gold"]),
        ref(TRAVERSAL_ITEMS["highwind"]),
    )
    plateau = (
        ref(TRAVERSAL_ITEMS["black"]),
        ref(TRAVERSAL_ITEMS["gold"]),
        ref(TRAVERSAL_ITEMS["highwind"]),
    )
    underwater = (ref(TRAVERSAL_ITEMS["submarine"]),)
    highwind = (ref(TRAVERSAL_ITEMS["highwind"]),)

    return {
        "none": [],
        "mountain": rule_or(*mountain),
        "ocean": rule_or(*ocean),
        "sub": rule_or(*sub),
        "plateau": rule_or(*plateau),
        "underwater": rule_or(*underwater),
        "highwind": rule_or(*highwind),
        "gold_saucer": [["$ff7_gold_saucer"]],
        "shinra_basement": [["$ff7_shinra_basement"]],
        "lunar_harp": [["$ff7_lunar_harp"]],
        "great_glacier": [["$ff7_great_glacier"]],
        "key_sector_5": [["$ff7_key_sector_5"]],
        "endgame": [["$ff7_endgame"]],
    }


REGION_LOGIC: dict[str, str] = {
    # Foot-reachable eastern continent
    "Kalm": "none",
    "Mythril Mines": "none",
    "Chocobo Farm": "none",
    "Fort Condor": "none",
    "Midgar (Opening)": "none",
    "Midgar (Fields)": "none",
    "Other Fields": "none",
    # Mountain crossing
    "Junon Lower": "mountain",
    "Junon Upper": "mountain",
    # Submarine / western approach
    "Corel": "sub",
    "Gold Saucer Area": "gold_saucer",
    # Open ocean continents
    "Costa del Sol": "ocean",
    "Mt. Corel": "ocean",
    "Gongaga": "ocean",
    "Cosmo Canyon": "ocean",
    "Nibelheim": "ocean",
    "Mt. Nibel": "ocean",
    "Rocket Town": "ocean",
    "Wutai": "ocean",
    "Bone Village": "ocean",
    "Sleeping Forest": "ocean",
    "Icicle Inn": "ocean",
    "Mideel": "ocean",
    # Plateau / special gates
    "Chocobo Sage": "plateau",
    "Ancient Forest": "plateau",
    "Shinra Mansion Basement": "shinra_basement",
    "Forgotten Capital": "lunar_harp",
    "Corel Valley": "lunar_harp",
    "Great Glacier": "great_glacier",
    # Endgame
    "Whirlwind Maze": "highwind",
    "Northern Cave": "endgame",
    "Underwater Reactor": "underwater",
    "Gelnika": "underwater",
    "Midgar Sector 5": "key_sector_5",
    "Bosses": "none",
    "Temple of the Ancients": "ocean",
}


def region_access_rules(region: str, rule_sets: dict[str, list[list[str]]]) -> list[list[str]]:
    if region.startswith("Shops - "):
        base = region.removeprefix("Shops - ")
        logic_key = REGION_LOGIC.get(base, "none")
    else:
        logic_key = REGION_LOGIC.get(region, "none")
    return rule_sets.get(logic_key, [])


def location_extra_rules(
    location_code: int,
    item_codes: dict[str, str],
) -> list[list[str]]:
    gate_item = LOCATION_ITEM_GATES.get(location_code)
    if gate_item is None:
        return []
    return rule_or(item_codes[gate_item])


def boss_access_rules(
    boss_name: str,
    rule_sets: dict[str, list[list[str]]],
) -> list[list[str]]:
    tier = BOSS_TIERS.get(boss_name, "ocean")
    return rule_sets.get(tier, [])


def combine_region_and_item_rules(
    region: str,
    location_code: int,
    rule_sets: dict[str, list[list[str]]],
    item_codes: dict[str, str],
) -> list[list[str]]:
    region_rules = region_access_rules(region, rule_sets)
    item_rules = location_extra_rules(location_code, item_codes)
    if not item_rules:
        return region_rules
    gate_code = item_rules[0][0]
    if not region_rules:
        return item_rules
    return [[f"{group[0]},{gate_code}"] for group in region_rules]


def child_access_rules(
    region: str,
    location: dict,
    rule_sets: dict[str, list[list[str]]],
    item_codes: dict[str, str],
) -> list[list[str]]:
    if region == "Bosses":
        return boss_access_rules(location["name"], rule_sets)
    return combine_region_and_item_rules(region, location["code"], rule_sets, item_codes)
