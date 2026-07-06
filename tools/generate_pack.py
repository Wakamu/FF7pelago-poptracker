#!/usr/bin/env python3
"""Generate a PopTracker pack from FF7pelago APWorld data."""

from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from pathlib import Path

from logic_rules import (
    boss_access_rules,
    build_item_codes,
    build_rule_sets,
    endgame_item_codes,
    location_extra_rules,
    region_access_rules,
)
from map_layout import (
    MapLayout,
    WORLD_MAP_ID,
    collect_group_map_locations,
    load_layout,
    standalone_proxy_name,
)
from slot_data_export import load_slot_constants, write_logic_pool_lua, write_logic_seed_lua
from world_map_coords import (
    WORLD_MAP_ID,
    WORLD_MAP_IMAGE,
    area_hub,
    area_pin_size,
    world_area_name,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APWORLD = Path(r"C:\Users\User\Projects\FF7pelago-ref\worlds\ff7")
VICTORY_LOCATION = "Northern Crater - Defeat Sephiroth"

# PopTracker @area/section/ paths treat "/" as a separator — escape in section names.
POPTRACKER_SLASH = "\u2044"


def poptracker_section_name(check_name: str) -> str:
    return check_name.replace("/", POPTRACKER_SLASH)


def section_ref(region: str, check_name: str) -> str:
    return f"@{region}/{poptracker_section_name(check_name)}/"


def section_ref_target(region: str, check_name: str) -> str:
    """PopTracker JSON section ref path (no @ prefix)."""
    return f"{region}/{poptracker_section_name(check_name)}"


def make_solid_png(width: int, height: int, rgba: tuple[int, int, int, int]) -> bytes:
    """Minimal uncompressed RGBA PNG writer (no external deps)."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b""
    row = bytes(rgba) * width
    for _ in range(height):
        raw += b"\x00" + row
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def write_images(image_dir: Path) -> None:
    image_dir.mkdir(parents=True, exist_ok=True)
    world_src = ROOT / "worldmap.png"
    world_dst = image_dir / "worldmap.png"
    if world_src.exists():
        world_dst.write_bytes(world_src.read_bytes())
    elif not world_dst.exists():
        world_dst.write_bytes(make_solid_png(3200, 2400, (24, 36, 64, 255)))
    (image_dir / "chest.png").write_bytes(make_solid_png(16, 16, (218, 165, 32, 255)))
    (image_dir / "chest_open.png").write_bytes(make_solid_png(16, 16, (96, 96, 96, 255)))
    (image_dir / "item.png").write_bytes(make_solid_png(32, 32, (70, 130, 180, 255)))

REGION_ORDER = [
    "Midgar (Opening)",
    "Midgar (Fields)",
    "Midgar Sector 5",
    "Kalm",
    "Mythril Mines",
    "Chocobo Farm",
    "Fort Condor",
    "Junon Lower",
    "Junon Upper",
    "Corel",
    "Gold Saucer Area",
    "Gongaga",
    "Cosmo Canyon",
    "Nibelheim",
    "Mt. Nibel",
    "Rocket Town",
    "Wutai",
    "Temple of the Ancients",
    "Forgotten Capital",
    "Great Glacier",
    "Icicle Inn",
    "Northern Crater",
    "Northern Cave",
    "Ancient Forest",
    "Corel Valley",
    "Whirlwind Maze",
    "Gelnika",
    "Midgar",
    "Bosses",
    "Other Fields",
]


def load_region_map(apworld: Path) -> dict[str, str]:
    text = (apworld / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r"FREE_ROAM_REGION_MAP: dict\[str, str\] = (\{.*?\n\})", text, re.S)
    if not match:
        raise RuntimeError("Could not parse FREE_ROAM_REGION_MAP from __init__.py")
    return ast.literal_eval(match.group(1))


def slug(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()


def item_code(code: int) -> str:
    return f"item_{code}"


def region_for_location(loc: dict, region_map: dict[str, str], shops_by_code: dict[int, dict]) -> str:
    code = loc["code"]
    if loc.get("category") == "shop":
        shop = shops_by_code.get(code)
        if shop and shop.get("region"):
            return f"Shops - {shop['region']}"
        return "Shops"
    if loc.get("category") == "boss":
        return "Bosses"
    region = region_map.get(loc.get("map", ""))
    if region:
        return region
    # Early Midgar field maps and other unmapped maps go to a catch-all bucket.
    early_midgar = {
        "gnmk", "md8_3", "mds7_w2", "mds7st1", "mds7st2",
        "nmkin_1", "nmkin_3", "nmkin_5", "nrthmk",
        "sbwy4_6", "smkin_1", "smkin_5",
    }
    map_id = loc.get("map", "")
    if map_id in early_midgar:
        return "Midgar (Opening)"
    if map_id.startswith(("md", "gn", "sm", "nm", "sb", "nr")):
        return "Midgar (Fields)"
    return "Other Fields"


def wrap_freeroam_access_rules(rules: list[list[str]]) -> list[list[str]]:
    """Linear mode bypasses Free Roam traversal gates."""
    if not rules:
        return []
    return [["$ff7_linear"]] + rules


def pool_visibility_rules(location_code: int) -> list[list[str]]:
    return [[f"$ff7_pool_{location_code}"]]


def area_visibility_rules(location_codes: list[int]) -> list[list[str]]:
    """Hide a map pin unless at least one check in the area is in this seed."""
    return [[f"$ff7_pool_{code}"] for code in location_codes]


def primary_area_region(area_regions: set[str]) -> str | None:
    non_shop = sorted(region for region in area_regions if not region.startswith("Shops - "))
    if non_shop:
        return non_shop[0]
    if area_regions:
        return sorted(area_regions)[0]
    return None


OPTION_ITEMS = [
    {
        "name": "Free Roam (seed)",
        "type": "toggle",
        "codes": "opt_free_roam",
        "img": "images/item.png",
        "initial_active_state": True,
    },
    {
        "name": "Weapon Fight Checks",
        "type": "toggle",
        "codes": "opt_weapon_fight_checks",
        "img": "images/item.png",
        "initial_active_state": True,
    },
    {
        "name": "Gold Saucer Checks",
        "type": "toggle",
        "codes": "opt_gold_saucer_checks",
        "img": "images/item.png",
        "initial_active_state": True,
    },
    {
        "name": "Fort Condor Checks",
        "type": "toggle",
        "codes": "opt_fort_condor_checks",
        "img": "images/item.png",
        "initial_active_state": True,
    },
]


def build_items(items: list[dict]) -> tuple[list[dict], dict[int, tuple[str, str]], list[str]]:
    pop_items: list[dict] = []
    mapping: dict[int, tuple[str, str]] = {}

    display_names: list[str] = []
    for item in items:
        code = item["code"]
        tracker_code = item_code(code)
        classification = item.get("classification", "filler")
        if classification == "progression":
            item_type = "toggle"
        elif classification == "useful":
            item_type = "toggle"
        else:
            item_type = "consumable"
        mapping[code] = (tracker_code, item_type)

        entry = {
            "name": item["name"],
            "type": item_type,
            "codes": tracker_code,
            "img": "images/item.png",
        }
        if item_type == "consumable":
            entry["min_quantity"] = 0
            entry["increment"] = 1
        pop_items.append(entry)

        if classification in {"progression", "useful"}:
            display_names.append(tracker_code)
        elif any(
            keyword in item["name"]
            for keyword in (
                "Chocobo",
                "Tiny Bronco",
                "Highwind",
                "Submarine",
                "Snowboard",
                "Keycard",
                "Coupon",
                "PHS",
                "Battery",
                "Lunar Harp",
                "Keystone",
                "Huge Materia",
            )
        ):
            display_names.append(tracker_code)

    return OPTION_ITEMS + pop_items, mapping, display_names


def build_locations(
    field_locations: list[dict],
    shops: list[dict],
    region_map: dict[str, str],
    rule_sets: dict[str, list[list[str]]],
    item_codes: dict[str, str],
    layout: MapLayout | None = None,
    pack_root: Path | None = None,
) -> tuple[dict, dict[int, str], dict[str, list[dict]], dict[int, dict[str, str]]]:
    shops_by_code = {shop["code"]: shop for shop in shops}
    all_locations: list[dict] = []
    layout = layout or MapLayout()
    overrides = layout.check_areas

    for loc in field_locations:
        if loc["name"] == VICTORY_LOCATION:
            continue
        all_locations.append(loc)

    for shop in shops:
        all_locations.append(
            {
                "name": shop["name"],
                "code": shop["code"],
                "map": shop.get("region", ""),
                "category": "shop",
            }
        )

    location_mapping: dict[int, str] = {}
    location_meta: dict[int, dict[str, str]] = {}
    by_area: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    code_to_area: dict[int, str] = {}

    for loc in sorted(all_locations, key=lambda x: (x["name"].lower(), x["code"])):
        code = loc["code"]
        region = region_for_location(loc, region_map, shops_by_code)
        area = overrides.get(code, world_area_name(region))
        location_mapping[code] = section_ref(area, loc["name"])
        location_meta[code] = {"region": region}
        code_to_area[code] = area
        by_area[area].append((region, loc))

    world_regions: list[dict] = []
    for area in sorted(by_area.keys(), key=lambda a: (REGION_ORDER.index(a) if a in REGION_ORDER else 999, a)):
        entries = by_area[area]
        sections: list[dict] = []
        area_regions = {region for region, _ in entries}

        area_codes = [loc["code"] for _, loc in entries]

        for full_region, loc in entries:
            if area == "Bosses":
                section_rules = wrap_freeroam_access_rules(
                    boss_access_rules(loc["name"], rule_sets)
                )
            else:
                section_rules = wrap_freeroam_access_rules(
                    location_extra_rules(loc["code"], item_codes)
                )
            section_entry = {
                "name": poptracker_section_name(loc["name"]),
                "item_count": 1,
                "visibility_rules": pool_visibility_rules(loc["code"]),
            }
            if section_rules:
                section_entry["access_rules"] = section_rules
            sections.append(section_entry)

        parent_rules: list[list[str]] = []
        primary_region = primary_area_region(area_regions)
        if primary_region is not None:
            parent_rules = wrap_freeroam_access_rules(
                region_access_rules(primary_region, rule_sets)
            )

        hub_x, hub_y = area_hub(area)
        map_locations = collect_group_map_locations(
            layout, pack_root or ROOT, area, len(sections), area_pin_size
        )
        if not map_locations:
            map_locations = [
                {
                    "map": WORLD_MAP_ID,
                    "x": hub_x,
                    "y": hub_y,
                    "size": area_pin_size(len(sections)),
                }
            ]
        region_entry = {
            "name": area,
            "chest_unopened_img": "images/chest.png",
            "chest_opened_img": "images/chest_open.png",
            "overlay_background": "#CC000000",
            "sections": sections,
            "map_locations": map_locations,
        }
        if parent_rules:
            region_entry["access_rules"] = parent_rules
        region_entry["visibility_rules"] = area_visibility_rules(area_codes)
        world_regions.append(region_entry)

    used_proxy_names: set[str] = set()
    for map_def in layout.maps:
        if map_def.id == WORLD_MAP_ID:
            continue
        pins = layout.pins.get(map_def.id)
        if not pins:
            continue
        for code, (x, y) in sorted(pins.standalone.items()):
            area = code_to_area.get(code)
            if area is None:
                continue
            loc = next((l for _, l in by_area.get(area, []) if l["code"] == code), None)
            if loc is None:
                continue
            section_name = poptracker_section_name(loc["name"])
            ref = section_ref_target(area, loc["name"])
            proxy_name = standalone_proxy_name(map_def.id, section_name, code, used_proxy_names)
            proxy_entry = {
                "name": proxy_name,
                "chest_unopened_img": "images/chest.png",
                "chest_opened_img": "images/chest_open.png",
                "overlay_background": "#CC000000",
                "sections": [{"ref": ref}],
                "map_locations": [
                    {"map": map_def.id, "x": x, "y": y, "size": 18},
                ],
                "access_rules": [[f"@{area}"]],
                "visibility_rules": pool_visibility_rules(code),
            }
            world_regions.append(proxy_entry)

    world_payload = {
        "file": "locations/world.json",
        "payload": world_regions,
    }

    return world_payload, location_mapping, by_area, location_meta


def write_lua_mapping(path: Path, table_name: str, mapping: dict[int, object]) -> None:
  lines = [f"{table_name} = {{"]
  for key in sorted(mapping):
      value = mapping[key]
      if isinstance(value, tuple):
          lines.append(f"    [{key}] = {{ \"{value[0]}\", \"{value[1]}\" }},")
      else:
          lines.append(f"    [{key}] = \"{value}\",")
  lines.append("}")
  path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_layout(display_item_codes: list[str], layout: MapLayout) -> dict:
    progression_rows = []
    row: list[str] = []
    for code in display_item_codes:
        row.append(code)
        if len(row) == 8:
            progression_rows.append(row)
            row = []
    if row:
        progression_rows.append(row)

    map_tabs = [
        {
            "title": map_def.title,
            "content": {"type": "map", "maps": [map_def.id]},
        }
        for map_def in layout.maps
    ]
    tabs = [
        {
            "title": "Items",
            "content": {
                "type": "array",
                "orientation": "vertical",
                "content": [
                    {
                        "type": "group",
                        "header": "Progression & Key Items",
                        "content": {
                            "type": "itemgrid",
                            "rows": progression_rows or [["item_100000"]],
                            "item_size": 32,
                        },
                    }
                ],
            },
        },
        *map_tabs,
    ]

    return {
        "tracker_default": {
            "type": "tabbed",
            "tabs": tabs,
        }
    }


def write_maps(layout: MapLayout) -> list[dict]:
    return [
        {
            "name": map_def.id,
            "location_size": 16,
            "location_border_thickness": 2,
            "img": map_def.image,
        }
        for map_def in layout.maps
    ]


def write_if_missing(path: Path, content: str) -> None:
    if path.exists():
        return
    path.write_text(content, encoding="utf-8")


def generate(apworld: Path = DEFAULT_APWORLD) -> None:
    data_dir = apworld / "data"
    items = json.loads((data_dir / "items.json").read_text(encoding="utf-8"))
    field_locations = json.loads((data_dir / "locations.json").read_text(encoding="utf-8"))
    shops = json.loads((data_dir / "shops.json").read_text(encoding="utf-8"))
    region_map = load_region_map(apworld)
    item_codes = build_item_codes(items)
    rule_sets = build_rule_sets(item_codes)

    pop_items, item_mapping, display_item_codes = build_items(items)
    layout = load_layout(ROOT)
    world_payload, location_mapping, by_area, location_meta = build_locations(
        field_locations,
        shops,
        region_map,
        rule_sets,
        item_codes,
        layout,
        ROOT,
    )
    slot_constants = load_slot_constants(apworld)

    (ROOT / "items").mkdir(parents=True, exist_ok=True)
    (ROOT / "locations").mkdir(parents=True, exist_ok=True)
    for old_file in (ROOT / "locations").glob("*.json"):
        old_file.unlink()

    (ROOT / "maps").mkdir(parents=True, exist_ok=True)
    (ROOT / "layouts").mkdir(parents=True, exist_ok=True)
    (ROOT / "images").mkdir(parents=True, exist_ok=True)
    (ROOT / "scripts" / "autotracking").mkdir(parents=True, exist_ok=True)

    write_images(ROOT / "images")

    (ROOT / "items" / "items.json").write_text(
        json.dumps(pop_items, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    (ROOT / world_payload["file"]).write_text(
        json.dumps(world_payload["payload"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    (ROOT / "maps" / "maps.json").write_text(
        json.dumps(write_maps(layout), indent=2) + "\n",
        encoding="utf-8",
    )

    (ROOT / "layouts" / "tracker.json").write_text(
        json.dumps(write_layout(display_item_codes, layout), indent=2) + "\n",
        encoding="utf-8",
    )

    write_lua_mapping(ROOT / "scripts" / "autotracking" / "item_mapping.lua", "ITEM_MAPPING", item_mapping)
    write_lua_mapping(
        ROOT / "scripts" / "autotracking" / "location_mapping.lua",
        "LOCATION_MAPPING",
        location_mapping,
    )
    write_logic_seed_lua(
        ROOT / "scripts" / "logic_seed.lua",
        slot_constants,
        location_meta,
        endgame_item_codes(item_codes),
    )
    write_logic_pool_lua(
        ROOT / "scripts" / "logic_pool.lua",
        sorted(location_meta.keys()),
    )

    manifest = {
        "name": "Final Fantasy VII Pelago",
        "game_name": "Final Fantasy VII",
        "package_uid": "ff7pelago-poptracker",
        "package_version": "0.4.5",
        "author": "FF7 Pelago Community",
        "platform": "pc",
        "variants": {
            "standard": {
                "display_name": "Standard",
                "flags": ["ap"],
            }
        },
        "min_poptracker_version": "0.25.5",
        "target_poptracker_version": "0.35.1",
    }
    write_if_missing(
        ROOT / "manifest.json",
        json.dumps(manifest, indent=2) + "\n",
    )

    settings = {
        "smooth_map_scaling": True,
        "smooth_scaling": True,
    }
    (ROOT / "settings.json").write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    init_lines = [
        'Tracker:AddItems("items/items.json")',
        "",
        'ScriptHost:LoadScript("scripts/logic_seed.lua")',
        'ScriptHost:LoadScript("scripts/logic.lua")',
        'ScriptHost:LoadScript("scripts/logic_pool.lua")',
        "",
        'Tracker:AddLocations("locations/world.json")',
        "",
        'Tracker:AddMaps("maps/maps.json")',
        'Tracker:AddLayouts("layouts/tracker.json")',
        "",
        'ScriptHost:LoadScript("scripts/autotracking/init.lua")',
        "",
    ]
    (ROOT / "scripts" / "init.lua").write_text("\n".join(init_lines), encoding="utf-8")

    autotracking_init = '''require("scripts/autotracking/item_mapping")
require("scripts/autotracking/location_mapping")

CUR_INDEX = -1
RECEIVED_ITEMS = {}
LAST_SEED_NAME = nil

local function sanitize_section_ref(code)
    if not code or code:sub(1, 1) ~= "@" then
        return code
    end
    local trimmed = code:sub(2)
    if trimmed:sub(-1) == "/" then
        trimmed = trimmed:sub(1, -2)
    end
    local slash_pos = trimmed:find("/")
    if not slash_pos then
        return code
    end
    local area = trimmed:sub(1, slash_pos - 1)
    local section = trimmed:sub(slash_pos + 1)
    if not section:find("/", 1, true) then
        return code
    end
    -- PopTracker treats "/" as a path separator inside @area/section/ refs.
    section = section:gsub("/", "__FRACTION_SLASH__")
    return "@" .. area .. "/" .. section .. "/"
end

local function find_tracker_object(code)
    local obj = Tracker:FindObjectForCode(code)
    if obj then
        return obj
    end
    local sanitized = sanitize_section_ref(code)
    if sanitized ~= code then
        obj = Tracker:FindObjectForCode(sanitized)
        if obj then
            return obj
        end
    end
    if not code or code:sub(1, 1) ~= "@" then
        return nil
    end
    if code:sub(-1) == "/" then
        return Tracker:FindObjectForCode(code:sub(1, -2))
    end
    return Tracker:FindObjectForCode(code .. "/")
end

local function location_code_for_id(location_id)
    local id = normalize_location_id(location_id)
    return LOCATION_MAPPING[id]
end

local function clear_location(code)
    local obj = find_tracker_object(code)
    if not obj then
        return
    end
    if code:sub(1, 1) == "@" then
        obj.AvailableChestCount = obj.ChestCount
    else
        obj.Active = false
    end
end

local function mark_location(code)
    local obj = find_tracker_object(code)
    if not obj then
        return
    end
    if code:sub(1, 1) == "@" then
        obj.AvailableChestCount = 0
    else
        obj.Active = true
    end
end

local function apply_received_item(item_id)
    local mapping = ITEM_MAPPING[item_id]
    if not mapping then
        return
    end
    local tracker_code = mapping[1]
    local item_type = mapping[2]
    local obj = Tracker:FindObjectForCode(tracker_code)
    if not obj then
        return
    end
    if item_type == "toggle" then
        obj.Active = true
    elseif item_type == "consumable" then
        obj.AcquiredCount = obj.AcquiredCount + obj.Increment
    end
end

local function sync_checked_locations()
    if not Archipelago.CheckedLocations then
        return
    end
    for _, location_id in ipairs(Archipelago.CheckedLocations) do
        local code = location_code_for_id(location_id)
        if code then
            mark_location(code)
        end
    end
end

local function sync_received_items()
    for item_id, _ in pairs(RECEIVED_ITEMS) do
        apply_received_item(item_id)
    end
end

function onClear(slot_data)
    local seed_name = slot_data and slot_data.seed_name
    if seed_name and seed_name ~= LAST_SEED_NAME then
        RECEIVED_ITEMS = {}
        LAST_SEED_NAME = seed_name
    end
    CUR_INDEX = -1
    Tracker.BulkUpdate = true

    apply_slot_data(slot_data)

    for _, code in pairs(LOCATION_MAPPING) do
        clear_location(code)
    end
    for _, mapping in pairs(ITEM_MAPPING) do
        local tracker_code = mapping[1]
        local item_type = mapping[2]
        if tracker_code:sub(1, 4) ~= "opt_" then
            local obj = Tracker:FindObjectForCode(tracker_code)
            if obj then
                if item_type == "toggle" then
                    obj.Active = false
                elseif item_type == "consumable" then
                    obj.AcquiredCount = 0
                end
            end
        end
    end

    sync_received_items()
    sync_checked_locations()

    Tracker.BulkUpdate = false
end

function onItem(index, item_id, item_name, player_number)
    if index <= CUR_INDEX then
        return
    end
    CUR_INDEX = index
    RECEIVED_ITEMS[item_id] = true
    apply_received_item(item_id)
end

function onLocation(location_id, location_name)
    local code = location_code_for_id(location_id)
    if not code then
        return
    end
    mark_location(code)
end

Archipelago:AddClearHandler("ff7 clear", onClear)
Archipelago:AddItemHandler("ff7 item", onItem)
Archipelago:AddLocationHandler("ff7 location", onLocation)
'''
    (ROOT / "scripts" / "autotracking" / "init.lua").write_text(
        autotracking_init.replace("__FRACTION_SLASH__", POPTRACKER_SLASH),
        encoding="utf-8",
    )

    readme = f"""# FF7 Pelago PopTracker

PopTracker pack for [FF7pelago](https://github.com/blazerwazey/FF7pelago) with Archipelago autotracking.

## Setup

1. Install [PopTracker](https://github.com/black-sliver/PopTracker/releases).
2. Copy this folder into your PopTracker `packs/` directory, or load it as an external pack.
3. Open the pack in PopTracker and enable **AP** autotracking from the menu.
4. Connect to your Archipelago room while playing Final Fantasy VII.

## Regenerating from APWorld data

```bash
python tools/generate_pack.py
```

By default this reads APWorld data from `C:/Users/User/Projects/FF7pelago-ref/worlds/ff7`.

## Pack contents

- {len(pop_items)} tracked items
- {len(location_mapping)} tracked locations on the world map
- Archipelago item/location ID mappings in `scripts/autotracking/`

Map checks are grouped into one pin per area on `images/worldmap.png` (hover/click the pin to see every check in that area).

## Logic (Free Roam)

Region access mirrors the APWorld Free Roam gates in `worlds/ff7/__init__.py`:

- **Foot regions** (Kalm, Mythril Mines, Chocobo Farm, Fort Condor): always reachable
- **Mountain** (Junon): Green / Black / Gold Chocobo or Highwind
- **Sub** (Corel): Submarine or any ocean-capable transport
- **Gold Saucer**: above + Gold Ticket
- **Ocean** (most western continent areas): Blue / Black / Gold Chocobo or Highwind
- **Plateau** (Chocobo Sage, Ancient Forest): Black / Gold Chocobo or Highwind
- **Special keys**: Lunar Harp, Basement Key, Snowboard + Glacier Map, Key to Sector 5
- **Endgame** (Northern Cave): Highwind + full party + 4 Huge Materia
- **Per-check gates**: Kalm Traveler trades, Leviathan Scales (Wutai statue), etc.

PopTracker colors: **green** = logically reachable, **red** = not yet. Toggle items on the Items tab to preview logic.

### Slot data (Archipelago)

When connected with AP autotracking, `onClear` reads the server's `slot_data` payload:

- `free_roam` and `options.*` drive seed settings (weapon bosses, Gold Saucer, Fort Condor)
- `biton_map` + `shops` define the **exact location pool** for this seed (checks not in the pool are hidden)
- `CheckedLocations` re-applies checks already sent to the server on reconnect
- UI hints show seed name, player, and mode

Without a connection, visibility falls back to the static option rules above.

Edit `tools/logic_rules.py` / `scripts/logic.lua` and rerun the generator to adjust rules.
"""
    write_if_missing(ROOT / "README.md", readme)

    print(
        f"Generated pack with {len(pop_items)} items and "
        f"{len(location_mapping)} locations on the world map."
    )


if __name__ == "__main__":
    generate()
