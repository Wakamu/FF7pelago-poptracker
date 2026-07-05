"""Persistent map layout: check grouping, multi-map tabs, and pin positions."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

LAYOUT_FILENAME = "map_layout.json"
LAYOUT_VERSION = 2
WORLD_MAP_ID = "world"
WORLD_MAP_IMAGE = "images/worldmap.png"
POOL_RULE_RE = re.compile(r"^\$ff7_pool_(\d+)$")

STANDARD_AREAS = (
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
    "Costa del Sol",
    "Mt. Corel",
    "Gongaga",
    "Cosmo Canyon",
    "Nibelheim",
    "Mt. Nibel",
    "Rocket Town",
    "Ancient Forest",
    "Wutai",
    "Chocobo Sage",
    "Bone Village",
    "Sleeping Forest",
    "Forgotten Capital",
    "Corel Valley",
    "Great Glacier",
    "Icicle Inn",
    "Northern Crater",
    "Northern Cave",
    "Whirlwind Maze",
    "Mideel",
    "Underwater Reactor",
    "Gelnika",
    "Shinra Mansion Basement",
    "Temple of the Ancients",
    "Other Fields",
    "Bosses",
)


@dataclass
class MapDefinition:
    id: str
    title: str
    image: str
    builtin: bool = False


@dataclass
class MapPins:
    groups: dict[str, tuple[int, int]] = field(default_factory=dict)
    standalone: dict[int, tuple[int, int]] = field(default_factory=dict)


@dataclass
class MapLayout:
    check_areas: dict[int, str] = field(default_factory=dict)
    maps: list[MapDefinition] = field(default_factory=list)
    pins: dict[str, MapPins] = field(default_factory=dict)

    # Legacy v1 fields (loaded then migrated).
    pin_coords: dict[str, tuple[int, int]] = field(default_factory=dict)
    standalone_checks: dict[int, tuple[int, int]] = field(default_factory=dict)


def layout_path(pack_root: Path) -> Path:
    return pack_root / "tools" / LAYOUT_FILENAME


def load_canonical_default_areas(pack_root: Path) -> dict[int, str]:
    """Default pin group per check from APWorld (same baseline as generate_pack)."""
    from generate_pack import DEFAULT_APWORLD, VICTORY_LOCATION, load_region_map, region_for_location
    from world_map_coords import world_area_name

    apworld = DEFAULT_APWORLD
    if not apworld.exists():
        return {}

    data_dir = apworld / "data"
    field_locations = json.loads((data_dir / "locations.json").read_text(encoding="utf-8"))
    shops = json.loads((data_dir / "shops.json").read_text(encoding="utf-8"))
    region_map = load_region_map(apworld)
    shops_by_code = {shop["code"]: shop for shop in shops}

    defaults: dict[int, str] = {}
    for loc in field_locations:
        if loc["name"] == VICTORY_LOCATION:
            continue
        region = region_for_location(loc, region_map, shops_by_code)
        defaults[loc["code"]] = world_area_name(region)
    for shop in shops:
        region = region_for_location(
            {"code": shop["code"], "category": "shop"},
            region_map,
            shops_by_code,
        )
        defaults[shop["code"]] = world_area_name(region)
    return defaults


def slugify_map_id(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", title.strip().lower()).strip("_")
    return slug or "map"


def pool_code_from_visibility(obj: dict) -> int | None:
    for group in obj.get("visibility_rules") or []:
        for rule in group:
            match = POOL_RULE_RE.match(str(rule))
            if match:
                return int(match.group(1))
    return None


def pool_code_from_section(section: dict) -> int | None:
    return pool_code_from_visibility(section)


def _import_world_coords(pack_root: Path) -> dict[str, tuple[int, int]]:
    tools = pack_root / "tools"
    import sys

    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import world_map_coords as wmc  # noqa: WPS433

    return dict(wmc.REGION_WORLD_COORDS)


def default_layout(pack_root: Path) -> MapLayout:
    world_pins = MapPins(groups=_import_world_coords(pack_root))
    return MapLayout(
        maps=[
            MapDefinition(
                id=WORLD_MAP_ID,
                title="World Map",
                image=WORLD_MAP_IMAGE,
                builtin=True,
            )
        ],
        pins={WORLD_MAP_ID: world_pins},
    )


def _migrate_v1(data: dict, pack_root: Path) -> MapLayout:
    layout = default_layout(pack_root)
    layout.check_areas = {int(k): v for k, v in data.get("check_areas", {}).items()}
    layout.pin_coords = {
        name: (int(value[0]), int(value[1]))
        for name, value in data.get("pin_coords", {}).items()
    }
    layout.standalone_checks = {
        int(code): (int(value[0]), int(value[1]))
        for code, value in data.get("standalone_checks", {}).items()
    }
    world = layout.pins[WORLD_MAP_ID]
    world.groups.update(layout.pin_coords)
    world.standalone.update(layout.standalone_checks)
    return layout


def load_layout(pack_root: Path) -> MapLayout:
    path = layout_path(pack_root)
    if not path.exists():
        return default_layout(pack_root)

    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version", 1) < LAYOUT_VERSION:
        return _migrate_v1(data, pack_root)

    maps = [
        MapDefinition(
            id=entry["id"],
            title=entry["title"],
            image=entry["image"],
            builtin=bool(entry.get("builtin", False)),
        )
        for entry in data.get("maps", [])
    ]
    pins: dict[str, MapPins] = {}
    for map_id, payload in data.get("pins", {}).items():
        pins[map_id] = MapPins(
            groups={
                name: (int(value[0]), int(value[1]))
                for name, value in payload.get("groups", {}).items()
            },
            standalone={
                int(code): (int(value[0]), int(value[1]))
                for code, value in payload.get("standalone", {}).items()
            },
        )

    layout = MapLayout(
        check_areas={int(code): area for code, area in data.get("check_areas", {}).items()},
        maps=maps or default_layout(pack_root).maps,
        pins=pins,
    )
    if WORLD_MAP_ID not in layout.pins:
        layout.pins[WORLD_MAP_ID] = MapPins(groups=_import_world_coords(pack_root))
    elif not layout.pins[WORLD_MAP_ID].groups:
        layout.pins[WORLD_MAP_ID].groups.update(_import_world_coords(pack_root))
    return layout


def save_layout(
    pack_root: Path,
    layout: MapLayout,
    *,
    check_areas: dict[int, str],
    default_areas: dict[int, str],
) -> None:
    """Persist grouping overrides relative to APWorld defaults, not world.json."""
    grouped_overrides = {
        code: area
        for code, area in check_areas.items()
        if default_areas.get(code) != area
    }
    payload = {
        "version": LAYOUT_VERSION,
        "check_areas": {str(code): area for code, area in sorted(grouped_overrides.items())},
        "maps": [
            {
                "id": map_def.id,
                "title": map_def.title,
                "image": map_def.image,
                **({"builtin": True} if map_def.builtin else {}),
            }
            for map_def in layout.maps
        ],
        "pins": {
            map_id: {
                "groups": {
                    name: [x, y] for name, (x, y) in sorted(pins.groups.items())
                },
                "standalone": {
                    str(code): [x, y] for code, (x, y) in sorted(pins.standalone.items())
                },
            }
            for map_id, pins in sorted(layout.pins.items())
            if pins.groups or pins.standalone
        },
    }
    layout_path(pack_root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def standalone_members(layout: MapLayout) -> set[int]:
    codes: set[int] = set()
    for pins in layout.pins.values():
        codes.update(pins.standalone.keys())
    codes.update(layout.standalone_checks.keys())
    return codes


def merged_group_coords(pack_root: Path, map_id: str = WORLD_MAP_ID) -> dict[str, tuple[int, int]]:
    layout = load_layout(pack_root)
    if map_id in layout.pins and layout.pins[map_id].groups:
        return dict(layout.pins[map_id].groups)
    if map_id == WORLD_MAP_ID:
        coords = _import_world_coords(pack_root)
        coords.update(layout.pin_coords)
        return coords
    return {}


def pins_for_map(layout: MapLayout, map_id: str) -> MapPins:
    return layout.pins.setdefault(map_id, MapPins())


def group_on_map(layout: MapLayout, map_id: str, group: str) -> tuple[int, int] | None:
    return pins_for_map(layout, map_id).groups.get(group)


def standalone_on_map(layout: MapLayout, map_id: str, code: int) -> tuple[int, int] | None:
    return pins_for_map(layout, map_id).standalone.get(code)


def collect_group_map_locations(
    layout: MapLayout,
    pack_root: Path,
    area: str,
    check_count: int,
    pin_size_fn,
) -> list[dict]:
    locations: list[dict] = []
    for map_def in layout.maps:
        pos = group_on_map(layout, map_def.id, area)
        if pos is None and map_def.id == WORLD_MAP_ID:
            pos = merged_group_coords(pack_root, WORLD_MAP_ID).get(area)
        if pos is None:
            continue
        locations.append(
            {
                "map": map_def.id,
                "x": pos[0],
                "y": pos[1],
                "size": pin_size_fn(check_count),
            }
        )
    return locations


def collect_standalone_map_locations(
    layout: MapLayout,
    code: int,
    pin_size: int = 18,
) -> list[dict]:
    locations: list[dict] = []
    for map_def in layout.maps:
        pos = standalone_on_map(layout, map_def.id, code)
        if pos is None:
            continue
        locations.append({"map": map_def.id, "x": pos[0], "y": pos[1], "size": pin_size})
    return locations


def copy_map_image(pack_root: Path, source: Path, map_id: str) -> str:
    dest_dir = pack_root / "images" / "maps"
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower() or ".png"
    dest = dest_dir / f"{map_id}{suffix}"
    shutil.copy2(source, dest)
    return f"images/maps/{dest.name}"


def load_checks_from_world(pack_root: Path) -> list[dict]:
    world_json = pack_root / "locations" / "world.json"
    if not world_json.exists():
        return []

    checks: list[dict] = []
    for area_entry in json.loads(world_json.read_text(encoding="utf-8")):
        area_name = area_entry["name"]
        sections = area_entry.get("sections") or area_entry.get("children") or []
        map_locations = area_entry.get("map_locations") or [{}]
        map_loc = map_locations[0]
        pin_x = int(map_loc.get("x", 0))
        pin_y = int(map_loc.get("y", 0))

        if len(sections) == 1:
            section = sections[0]
            if section.get("ref"):
                continue
            code = pool_code_from_section(section)
            if code is not None and section["name"] == area_name:
                checks.append(
                    {
                        "code": code,
                        "name": sections[0]["name"],
                        "default_area": area_name,
                        "default_standalone": True,
                        "default_standalone_xy": (pin_x, pin_y),
                    }
                )
                continue

        for section in sections:
            code = pool_code_from_section(section)
            if code is None:
                continue
            checks.append(
                {
                    "code": code,
                    "name": section["name"],
                    "default_area": area_name,
                    "default_standalone": False,
                }
            )
    checks.sort(key=lambda entry: (entry["name"].lower(), entry["code"]))
    return checks


def build_editor_layout(
    pack_root: Path,
) -> tuple[MapLayout, dict[int, str], dict[int, str], list[dict]]:
    checks = load_checks_from_world(pack_root)
    layout = load_layout(pack_root)
    check_names = {record["code"]: record["name"] for record in checks}
    world_defaults = {record["code"]: record["default_area"] for record in checks}
    canonical_areas = load_canonical_default_areas(pack_root)
    default_areas = canonical_areas or world_defaults

    check_areas: dict[int, str] = {}
    for record in checks:
        code = record["code"]
        if code in layout.check_areas:
            check_areas[code] = layout.check_areas[code]
        else:
            world_area = world_defaults.get(code)
            canonical_area = default_areas.get(code)
            if (
                world_area
                and canonical_area
                and world_area != canonical_area
            ):
                # Recover moves lost when overrides were cleared after a prior save.
                check_areas[code] = world_area
            else:
                check_areas[code] = default_areas.get(code, record["default_area"])
        record["default_area"] = default_areas.get(code, record["default_area"])

    for area in set(check_areas.values()):
        for map_def in layout.maps:
            layout.pins.setdefault(map_def.id, MapPins())

    return layout, check_areas, check_names, checks


def standalone_proxy_name(map_id: str, section_name: str, code: int, used: set[str]) -> str:
    """Unique PopTracker location name for a per-map ref pin."""
    base = f"{section_name} [{map_id}]"
    if base not in used:
        used.add(base)
        return base
    unique = f"{section_name} [{map_id}/{code}]"
    used.add(unique)
    return unique


def ordered_map_ids(layout: MapLayout) -> list[str]:
    return [map_def.id for map_def in layout.maps]
