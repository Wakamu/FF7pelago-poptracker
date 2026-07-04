"""Persistent map layout overrides for pin groups and standalone checks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

LAYOUT_FILENAME = "map_layout.json"
POOL_RULE_RE = re.compile(r"^\$ff7_pool_(\d+)$")

# Areas defined in tools/world_map_coords.py (not custom editor groups).
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
class MapLayout:
    check_areas: dict[int, str] = field(default_factory=dict)
    pin_coords: dict[str, tuple[int, int]] = field(default_factory=dict)
    standalone_checks: dict[int, tuple[int, int]] = field(default_factory=dict)


def layout_path(pack_root: Path) -> Path:
    return pack_root / "tools" / LAYOUT_FILENAME


def pool_code_from_section(section: dict) -> int | None:
    for group in section.get("visibility_rules") or []:
        for rule in group:
            match = POOL_RULE_RE.match(str(rule))
            if match:
                return int(match.group(1))
    return None


def load_layout(pack_root: Path) -> MapLayout:
    path = layout_path(pack_root)
    if not path.exists():
        return MapLayout()
    data = json.loads(path.read_text(encoding="utf-8"))
    return MapLayout(
        check_areas={int(code): area for code, area in data.get("check_areas", {}).items()},
        pin_coords={
            name: (int(value[0]), int(value[1]))
            for name, value in data.get("pin_coords", {}).items()
        },
        standalone_checks={
            int(code): (int(value[0]), int(value[1]))
            for code, value in data.get("standalone_checks", {}).items()
        },
    )


def save_layout(
    pack_root: Path,
    *,
    check_areas: dict[int, str],
    default_areas: dict[int, str],
    standalone_checks: dict[int, tuple[int, int]],
    pin_coords: dict[str, tuple[int, int]],
) -> None:
    """Persist layout overrides (deltas for grouped checks, full custom/standalone data)."""
    grouped_overrides = {
        code: area
        for code, area in check_areas.items()
        if code not in standalone_checks and default_areas.get(code) != area
    }
    custom_pin_coords = {
        name: [x, y]
        for name, (x, y) in pin_coords.items()
        if name not in STANDARD_AREAS
    }
    payload = {
        "check_areas": {str(code): area for code, area in sorted(grouped_overrides.items())},
        "pin_coords": {name: [x, y] for name, (x, y) in sorted(custom_pin_coords.items())},
        "standalone_checks": {
            str(code): [x, y] for code, (x, y) in sorted(standalone_checks.items())
        },
    }
    layout_path(pack_root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def merged_group_coords(pack_root: Path) -> dict[str, tuple[int, int]]:
    """Standard coords from world_map_coords.py plus custom groups from map_layout.json."""
    tools = pack_root / "tools"
    import sys

    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import world_map_coords as wmc  # noqa: WPS433

    coords = dict(wmc.REGION_WORLD_COORDS)
    coords.update(load_layout(pack_root).pin_coords)
    return coords


def load_checks_from_world(pack_root: Path) -> list[dict]:
    """Parse locations/world.json into check records."""
    world_json = pack_root / "locations" / "world.json"
    if not world_json.exists():
        return []

    checks: list[dict] = []
    for area_entry in json.loads(world_json.read_text(encoding="utf-8")):
        area_name = area_entry["name"]
        sections = area_entry.get("sections") or area_entry.get("children") or []
        map_loc = (area_entry.get("map_locations") or [{}])[0]
        pin_x = int(map_loc.get("x", 0))
        pin_y = int(map_loc.get("y", 0))

        if len(sections) == 1:
            code = pool_code_from_section(sections[0])
            if code is not None and sections[0]["name"] == area_name:
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


def build_editor_layout(pack_root: Path) -> tuple[MapLayout, dict[int, str], dict[int, str], list[dict]]:
    """Return (layout, check_areas, check_names, check_records) for the editor."""
    checks = load_checks_from_world(pack_root)
    layout = load_layout(pack_root)
    check_names = {record["code"]: record["name"] for record in checks}
    default_areas = {record["code"]: record["default_area"] for record in checks}

    check_areas: dict[int, str] = {}
    standalone_checks: dict[int, tuple[int, int]] = dict(layout.standalone_checks)

    for record in checks:
        code = record["code"]
        if code in layout.standalone_checks:
            check_areas[code] = default_areas[code]
            continue
        if code in layout.check_areas:
            check_areas[code] = layout.check_areas[code]
        elif record.get("default_standalone"):
            standalone_checks.setdefault(code, record.get("default_standalone_xy", (1600, 1200)))
        else:
            check_areas[code] = default_areas[code]

    merged_layout = MapLayout(
        check_areas=layout.check_areas,
        pin_coords=layout.pin_coords,
        standalone_checks=standalone_checks,
    )
    return merged_layout, check_areas, check_names, checks


def standalone_pin_name(loc_name: str, code: int, used: set[str]) -> str:
    base = loc_name.replace("/", "\u2044")
    if base not in used:
        used.add(base)
        return base
    unique = f"{base} ({code})"
    used.add(unique)
    return unique
