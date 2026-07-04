#!/usr/bin/env python3
"""Visual editor for PopTracker world-map pins and check grouping.

- Drag pin groups on the map
- Create custom pin groups
- Move checks between groups or make them standalone pins
- Save, then run: python tools/generate_pack.py
"""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

TOOLS_DIR = Path(__file__).resolve().parent
PACK_ROOT = TOOLS_DIR.parent

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from map_layout import (  # noqa: E402
    STANDARD_AREAS,
    MapLayout,
    build_editor_layout,
    save_layout,
)

ZOOM_OPTIONS = (
    ("12%", 8),
    ("25%", 4),
    ("50%", 2),
    ("100%", 1),
)

GROUP_FILL = "#daa520"
GROUP_FILL_SELECTED = "#ff8c00"
STANDALONE_FILL = "#40c4ff"
STANDALONE_FILL_SELECTED = "#00bcd4"
PIN_OUTLINE = "#1a1a1a"
PIN_OUTLINE_SELECTED = "#ffffff"


def import_coords_module(pack_root: Path):
    tools = pack_root / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import world_map_coords as wmc  # noqa: WPS433

    return importlib.reload(wmc)


def pin_size_for_checks(check_count: int) -> int:
    if check_count >= 20:
        return 28
    if check_count >= 8:
        return 24
    if check_count >= 3:
        return 20
    return 18


def ordered_area_names(coords: dict[str, tuple[int, int]]) -> list[str]:
    names: list[str] = []
    for name in STANDARD_AREAS:
        if name in coords and name not in names:
            names.append(name)
    for name in sorted(coords):
        if name not in names:
            names.append(name)
    return names


def write_world_map_coords(
    path: Path,
    coords: dict[str, tuple[int, int]],
    map_width: int,
    map_height: int,
) -> None:
    lines = [
        '"""Pixel coordinates for FF7 regions on images/worldmap.png (3200 x 2400)."""',
        "",
        "from __future__ import annotations",
        "",
        f"MAP_WIDTH = {map_width}",
        f"MAP_HEIGHT = {map_height}",
        "",
        "# Tuned to the labeled world map art shipped with this pack.",
        "REGION_WORLD_COORDS: dict[str, tuple[int, int]] = {",
    ]
    for name in ordered_area_names(coords):
        if name not in STANDARD_AREAS:
            continue
        x, y = coords[name]
        lines.append(f'    "{name}": ({x}, {y}),')
    lines.extend(
        [
            "    # Shop tabs share their region's hub with a small eastward shift applied in code.",
            "}",
            "",
            'WORLD_MAP_ID = "world"',
            'WORLD_MAP_IMAGE = "images/worldmap.png"',
            "",
            "",
            "def world_area_name(region: str) -> str:",
            '    """Map AP regions (and shop tabs) to a single world-map pin."""',
            '    if region.startswith("Shops - "):',
            '        return region.removeprefix("Shops - ")',
            "    return region",
            "",
            "",
            "def area_hub(area: str) -> tuple[int, int]:",
            '    return REGION_WORLD_COORDS.get(area, REGION_WORLD_COORDS["Other Fields"])',
            "",
            "",
            "def area_pin_size(check_count: int) -> int:",
            "    if check_count >= 20:",
            "        return 28",
            "    if check_count >= 8:",
            "        return 24",
            "    if check_count >= 3:",
            "        return 20",
            "    return 18",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


class MapPinEditor(tk.Tk):
    def __init__(self, pack_root: Path, from_world: bool, regenerate: bool) -> None:
        super().__init__()
        self.title("FF7 Pelago Map Pin Editor")
        self.geometry("1440x920")
        self.minsize(1100, 700)

        self.pack_root = pack_root
        self.regenerate_on_save = regenerate
        self.coords_path = pack_root / "tools" / "world_map_coords.py"
        self.map_path = pack_root / "images" / "worldmap.png"
        if not self.map_path.exists():
            self.map_path = pack_root / "worldmap.png"

        wmc = import_coords_module(pack_root)
        self.map_width = wmc.MAP_WIDTH
        self.map_height = wmc.MAP_HEIGHT

        self.layout, self.check_areas, self.check_names, self.check_records = build_editor_layout(
            pack_root
        )
        self.default_areas = {record["code"]: record["default_area"] for record in self.check_records}
        self.standalone_checks: dict[int, tuple[int, int]] = dict(self.layout.standalone_checks)

        self.group_coords: dict[str, tuple[int, int]] = dict(wmc.REGION_WORLD_COORDS)
        self.group_coords.update(self.layout.pin_coords)
        for area in set(self.check_areas.values()):
            self.group_coords.setdefault(area, (1600, 1200))

        if from_world:
            self._load_coords_from_world_json()

        self.subsample = 4
        self.scale = 1.0 / self.subsample
        self.photo = None
        self.selected_area: str | None = None
        self.selected_standalone: set[int] = set()
        self.drag_area: str | None = None
        self.drag_standalone: int | None = None
        self.drag_offset = (0, 0)
        self.dirty = False

        self._build_ui()
        self._load_map_image()
        self._redraw()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_coords_from_world_json(self) -> None:
        world_json = self.pack_root / "locations" / "world.json"
        if not world_json.exists():
            return
        for entry in json.loads(world_json.read_text(encoding="utf-8")):
            map_loc = (entry.get("map_locations") or [{}])[0]
            self.group_coords[entry["name"]] = (int(map_loc.get("x", 0)), int(map_loc.get("y", 0)))

    def _is_standalone(self, code: int) -> bool:
        return code in self.standalone_checks

    def _checks_for_area(self, area: str) -> list[int]:
        return sorted(
            code
            for code, assigned in self.check_areas.items()
            if assigned == area and not self._is_standalone(code)
        )

    def _check_count(self, area: str) -> int:
        return len(self._checks_for_area(area))

    def _is_custom_group(self, area: str) -> bool:
        return area not in STANDARD_AREAS

    def _view_center_map(self) -> tuple[int, int]:
        x0 = self.canvas.canvasx(0)
        y0 = self.canvas.canvasy(0)
        x1 = self.canvas.canvasx(self.canvas.winfo_width())
        y1 = self.canvas.canvasy(self.canvas.winfo_height())
        return int((x0 + x1) / 2 / self.scale), int((y0 + y1) / 2 / self.scale)

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.pack(fill=tk.X)

        ttk.Label(toolbar, text="Zoom:").pack(side=tk.LEFT)
        self.zoom_var = tk.StringVar(value="25%")
        zoom_box = ttk.Combobox(
            toolbar,
            textvariable=self.zoom_var,
            values=[label for label, _ in ZOOM_OPTIONS],
            state="readonly",
            width=8,
        )
        zoom_box.pack(side=tk.LEFT, padx=(4, 12))
        zoom_box.bind("<<ComboboxSelected>>", self._on_zoom_changed)

        ttk.Button(toolbar, text="Save", command=self._save).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Reload", command=self._reload).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Center view", command=self._center_view).pack(side=tk.LEFT, padx=4)

        self.status_var = tk.StringVar(value="Gold = groups, cyan = standalone checks.")
        ttk.Label(toolbar, textvariable=self.status_var).pack(side=tk.LEFT, padx=(16, 0))

        body = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        map_frame = ttk.Frame(body)
        body.add(map_frame, weight=4)

        self.canvas = tk.Canvas(map_frame, background="#202020", highlightthickness=0)
        x_scroll = ttk.Scrollbar(map_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        y_scroll = ttk.Scrollbar(map_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        map_frame.rowconfigure(0, weight=1)
        map_frame.columnconfigure(0, weight=1)

        side = ttk.Frame(body, padding=(8, 0))
        body.add(side, weight=1)

        ttk.Label(side, text="Pin groups", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        ttk.Label(
            side,
            text="Gold squares = groups. Drag to reposition.\nCustom groups show [custom].",
            wraplength=280,
        ).pack(anchor=tk.W, pady=(0, 4))

        group_btn_row = ttk.Frame(side)
        group_btn_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(group_btn_row, text="New group...", command=self._new_pin_group).pack(side=tk.LEFT)
        ttk.Button(group_btn_row, text="Delete group", command=self._delete_selected_group).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        area_frame = ttk.Frame(side)
        area_frame.pack(fill=tk.X)
        self.area_list = tk.Listbox(area_frame, exportselection=False, activestyle="none", height=8)
        area_scroll = ttk.Scrollbar(area_frame, orient=tk.VERTICAL, command=self.area_list.yview)
        self.area_list.configure(yscrollcommand=area_scroll.set)
        self.area_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        area_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.area_list.bind("<<ListboxSelect>>", self._on_area_select)

        ttk.Separator(side, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        ttk.Label(side, text="Checks in selected group", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)

        check_frame = ttk.Frame(side)
        check_frame.pack(fill=tk.BOTH, expand=True)
        self.check_list = tk.Listbox(
            check_frame,
            exportselection=False,
            activestyle="none",
            selectmode=tk.EXTENDED,
        )
        check_scroll = ttk.Scrollbar(check_frame, orient=tk.VERTICAL, command=self.check_list.yview)
        self.check_list.configure(yscrollcommand=check_scroll.set)
        self.check_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        check_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        move_row = ttk.Frame(side)
        move_row.pack(fill=tk.X, pady=(8, 4))
        ttk.Label(move_row, text="Move to:").pack(side=tk.LEFT)
        self.move_target = ttk.Combobox(move_row, state="readonly", width=22)
        self.move_target.pack(side=tk.LEFT, padx=(6, 6), fill=tk.X, expand=True)
        ttk.Button(move_row, text="Move", command=self._move_selected_checks).pack(side=tk.LEFT)

        action_row = ttk.Frame(side)
        action_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(action_row, text="Make standalone pin", command=self._make_standalone).pack(
            side=tk.LEFT
        )
        ttk.Button(action_row, text="Reset to default", command=self._reset_selected_checks).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        ttk.Label(
            side,
            text="Cyan squares = standalone checks (own pin, not in a group popup).",
            wraplength=280,
        ).pack(anchor=tk.W, pady=(10, 0))

        self.detail_var = tk.StringVar(value="")
        ttk.Label(side, textvariable=self.detail_var, wraplength=280, justify=tk.LEFT).pack(
            anchor=tk.W, pady=(8, 0)
        )

        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.bind("<Left>", lambda _e: self._nudge(-1, 0))
        self.bind("<Right>", lambda _e: self._nudge(1, 0))
        self.bind("<Up>", lambda _e: self._nudge(0, -1))
        self.bind("<Down>", lambda _e: self._nudge(0, 1))

    def _display_size(self) -> tuple[int, int]:
        return int(self.map_width * self.scale), int(self.map_height * self.scale)

    def _load_map_image(self) -> None:
        if not self.map_path.exists():
            messagebox.showerror("Missing map", f"Could not find world map image:\n{self.map_path}")
            self.destroy()
            return

        source = tk.PhotoImage(file=str(self.map_path))
        self.photo = source.subsample(self.subsample, self.subsample) if self.subsample > 1 else source
        self.canvas.delete("map")
        width, height = self._display_size()
        self.canvas.create_image(0, 0, image=self.photo, anchor=tk.NW, tags=("map",))
        self.canvas.configure(scrollregion=(0, 0, width, height))
        self._center_view()

    def _redraw(self) -> None:
        self._draw_group_pins()
        self._draw_standalone_pins()
        self._refresh_area_list()
        self._update_detail()

    def _draw_group_pins(self) -> None:
        self.canvas.delete("group")
        for area, (x, y) in self.group_coords.items():
            count = self._check_count(area)
            if count == 0 and self._is_custom_group(area):
                continue
            size = pin_size_for_checks(max(count, 1))
            sx, sy = x * self.scale, y * self.scale
            display_size = max(8, size * self.scale)
            x0, y0 = sx - display_size / 2, sy - display_size / 2
            x1, y1 = sx + display_size / 2, sy + display_size / 2
            selected = area == self.selected_area and not self.selected_standalone
            label = area
            if self._is_custom_group(area):
                label += " [custom]"
            self.canvas.create_rectangle(
                x0,
                y0,
                x1,
                y1,
                fill=GROUP_FILL_SELECTED if selected else GROUP_FILL,
                outline=PIN_OUTLINE_SELECTED if selected else PIN_OUTLINE,
                width=2 if selected else 1,
                tags=("group", f"group:{area}"),
            )
            self.canvas.create_text(
                sx,
                y1 + 8,
                text=f"{label} ({count})",
                fill="#ffffff",
                font=("Segoe UI", 8, "bold"),
                anchor=tk.N,
                tags=("group", f"glabel:{area}"),
            )

    def _draw_standalone_pins(self) -> None:
        self.canvas.delete("standalone")
        for code, (x, y) in self.standalone_checks.items():
            sx, sy = x * self.scale, y * self.scale
            size = max(7, 14 * self.scale)
            x0, y0 = sx - size / 2, sy - size / 2
            x1, y1 = sx + size / 2, sy + size / 2
            selected = code in self.selected_standalone
            name = self.check_names.get(code, str(code))
            short = name if len(name) <= 28 else name[:25] + "..."
            self.canvas.create_rectangle(
                x0,
                y0,
                x1,
                y1,
                fill=STANDALONE_FILL_SELECTED if selected else STANDALONE_FILL,
                outline=PIN_OUTLINE_SELECTED if selected else PIN_OUTLINE,
                width=2 if selected else 1,
                tags=("standalone", f"standalone:{code}"),
            )
            self.canvas.create_text(
                sx,
                y1 + 8,
                text=short,
                fill="#b3e5fc",
                font=("Segoe UI", 7),
                anchor=tk.N,
                tags=("standalone", f"slabel:{code}"),
            )

    def _refresh_area_list(self) -> None:
        self.area_list.delete(0, tk.END)
        for name in ordered_area_names(self.group_coords):
            x, y = self.group_coords[name]
            checks = self._check_count(name)
            suffix = " [custom]" if self._is_custom_group(name) else ""
            self.area_list.insert(tk.END, f"{name}{suffix}  ({x}, {y})  [{checks}]")
        self.move_target.configure(values=ordered_area_names(self.group_coords))
        if self.selected_area and self.selected_area in self.group_coords:
            idx = ordered_area_names(self.group_coords).index(self.selected_area)
            self.area_list.selection_clear(0, tk.END)
            self.area_list.selection_set(idx)
            self.area_list.see(idx)
        self._refresh_check_list()

    def _refresh_check_list(self) -> None:
        self.check_list.delete(0, tk.END)
        if not self.selected_area:
            return
        for code in self._checks_for_area(self.selected_area):
            name = self.check_names.get(code, f"Check {code}")
            suffix = ""
            if self.default_areas.get(code) != self.selected_area:
                suffix = " *"
            self.check_list.insert(tk.END, f"{name}{suffix}")

    def _selected_check_codes(self) -> list[int]:
        if not self.selected_area:
            return []
        area_codes = self._checks_for_area(self.selected_area)
        return [area_codes[i] for i in self.check_list.curselection()]

    def _update_detail(self) -> None:
        if self.selected_standalone:
            lines = [f"{len(self.selected_standalone)} standalone check(s)"]
            for code in sorted(self.selected_standalone):
                x, y = self.standalone_checks[code]
                lines.append(f"{self.check_names.get(code, code)}")
                lines.append(f"  {x}, {y}")
            self.detail_var.set("\n".join(lines))
            return
        if not self.selected_area:
            self.detail_var.set(
                f"{len(self.standalone_checks)} standalone pin(s)\n"
                f"{sum(1 for a in self.group_coords if self._check_count(a) > 0)} active groups"
            )
            return
        x, y = self.group_coords[self.selected_area]
        checks = self._check_count(self.selected_area)
        kind = "custom group" if self._is_custom_group(self.selected_area) else "group"
        self.detail_var.set(f"{self.selected_area} ({kind})\n{x}, {y}\n{checks} grouped checks")

    def _select_area(self, area: str | None, *, focus_canvas: bool = False) -> None:
        self.selected_area = area
        self.selected_standalone.clear()
        self._redraw()
        if area and focus_canvas:
            x, y = self.group_coords[area]
            sx, sy = x * self.scale, y * self.scale
            self.canvas.xview_moveto(max(0.0, min(1.0, (sx - 200) / max(1, self._display_size()[0]))))
            self.canvas.yview_moveto(max(0.0, min(1.0, (sy - 200) / max(1, self._display_size()[1]))))

    def _select_standalone(self, code: int | None, *, focus_canvas: bool = False) -> None:
        self.selected_area = None
        self.selected_standalone = {code} if code is not None else set()
        self.area_list.selection_clear(0, tk.END)
        self._redraw()
        if code is not None and focus_canvas:
            x, y = self.standalone_checks[code]
            sx, sy = x * self.scale, y * self.scale
            self.canvas.xview_moveto(max(0.0, min(1.0, (sx - 200) / max(1, self._display_size()[0]))))
            self.canvas.yview_moveto(max(0.0, min(1.0, (sy - 200) / max(1, self._display_size()[1]))))

    def _new_pin_group(self) -> None:
        name = simpledialog.askstring("New pin group", "Group name:", parent=self)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in self.group_coords:
            messagebox.showwarning("New group", "A group with that name already exists.")
            return
        cx, cy = self._view_center_map()
        self.group_coords[name] = (cx, cy)
        self.dirty = True
        self._select_area(name, focus_canvas=True)
        self.status_var.set(f"Created pin group: {name}")

    def _delete_selected_group(self) -> None:
        if not self.selected_area:
            messagebox.showwarning("Delete group", "Select a pin group first.")
            return
        area = self.selected_area
        if not self._is_custom_group(area):
            messagebox.showwarning(
                "Delete group",
                "Only custom groups can be deleted.\nStandard AP regions stay in the pack.",
            )
            return
        if self._check_count(area) > 0:
            messagebox.showwarning(
                "Delete group",
                "Move or ungroup all checks before deleting this group.",
            )
            return
        if not messagebox.askyesno("Delete group", f"Delete empty custom group '{area}'?"):
            return
        del self.group_coords[area]
        self.selected_area = None
        self.dirty = True
        self._redraw()
        self.status_var.set(f"Deleted group: {area}")

    def _move_selected_checks(self) -> None:
        target = self.move_target.get().strip()
        if not target:
            messagebox.showwarning("Move checks", "Choose a destination pin group.")
            return
        codes = self._selected_check_codes()
        if not codes:
            messagebox.showwarning("Move checks", "Select one or more checks first.")
            return
        for code in codes:
            self.standalone_checks.pop(code, None)
            self.check_areas[code] = target
        self.dirty = True
        self._select_area(target)
        self.status_var.set(f"Moved {len(codes)} check(s) to {target}")

    def _make_standalone(self) -> None:
        codes = self._selected_check_codes()
        if not codes:
            messagebox.showwarning("Standalone pin", "Select one or more checks in a group first.")
            return
        if self.selected_area:
            base_x, base_y = self.group_coords[self.selected_area]
        else:
            base_x, base_y = self._view_center_map()
        for index, code in enumerate(codes):
            offset = index * 24
            self.standalone_checks[code] = (base_x + offset, base_y + offset)
        self.dirty = True
        self._select_standalone(codes[0], focus_canvas=True)
        self.status_var.set(f"Created {len(codes)} standalone pin(s)")

    def _reset_selected_checks(self) -> None:
        codes = self._selected_check_codes()
        if not codes:
            messagebox.showwarning("Reset checks", "Select one or more checks first.")
            return
        for code in codes:
            self.standalone_checks.pop(code, None)
            default_area = self.default_areas.get(code)
            if default_area:
                self.check_areas[code] = default_area
        self.dirty = True
        self._select_area(self.selected_area)
        self.status_var.set(f"Reset {len(codes)} check(s) to default layout")

    def _canvas_to_map(self, canvas_x: float, canvas_y: float) -> tuple[int, int]:
        x = int(round(canvas_x / self.scale))
        y = int(round(canvas_y / self.scale))
        return max(0, min(self.map_width, x)), max(0, min(self.map_height, y))

    def _hit_standalone(self, canvas_x: float, canvas_y: float) -> int | None:
        hits = self.canvas.find_overlapping(canvas_x, canvas_y, canvas_x, canvas_y)
        for item in reversed(hits):
            for tag in self.canvas.gettags(item):
                if tag.startswith("standalone:"):
                    return int(tag.split(":", 1)[1])
        return None

    def _hit_group(self, canvas_x: float, canvas_y: float) -> str | None:
        hits = self.canvas.find_overlapping(canvas_x, canvas_y, canvas_x, canvas_y)
        for item in reversed(hits):
            for tag in self.canvas.gettags(item):
                if tag.startswith("group:"):
                    return tag.split(":", 1)[1]
        return None

    def _on_canvas_press(self, event: tk.Event) -> None:
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        standalone_code = self._hit_standalone(canvas_x, canvas_y)
        if standalone_code is not None:
            self._select_standalone(standalone_code)
            px, py = self.standalone_checks[standalone_code]
            self.drag_standalone = standalone_code
            self.drag_area = None
            self.drag_offset = (canvas_x - px * self.scale, canvas_y - py * self.scale)
            return

        area = self._hit_group(canvas_x, canvas_y)
        self._select_area(area)
        if area is None:
            self.selected_standalone.clear()
            self._update_detail()
            return
        px, py = self.group_coords[area]
        self.drag_area = area
        self.drag_standalone = None
        self.drag_offset = (canvas_x - px * self.scale, canvas_y - py * self.scale)

    def _on_canvas_drag(self, event: tk.Event) -> None:
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        map_x, map_y = self._canvas_to_map(
            canvas_x - self.drag_offset[0],
            canvas_y - self.drag_offset[1],
        )
        if self.drag_standalone is not None:
            self.standalone_checks[self.drag_standalone] = (map_x, map_y)
        elif self.drag_area:
            self.group_coords[self.drag_area] = (map_x, map_y)
        else:
            return
        self.dirty = True
        self._redraw()

    def _on_canvas_release(self, _event: tk.Event) -> None:
        self.drag_area = None
        self.drag_standalone = None

    def _on_area_select(self, _event: tk.Event) -> None:
        selection = self.area_list.curselection()
        if not selection:
            return
        name = ordered_area_names(self.group_coords)[selection[0]]
        self._select_area(name, focus_canvas=True)

    def _nudge(self, dx: int, dy: int) -> None:
        step = 10 if ("Shift" in self.state()) else 1
        if self.selected_standalone:
            for code in self.selected_standalone:
                x, y = self.standalone_checks[code]
                self.standalone_checks[code] = (
                    max(0, min(self.map_width, x + dx * step)),
                    max(0, min(self.map_height, y + dy * step)),
                )
            self.dirty = True
            self._redraw()
            return
        if not self.selected_area:
            return
        x, y = self.group_coords[self.selected_area]
        self.group_coords[self.selected_area] = (
            max(0, min(self.map_width, x + dx * step)),
            max(0, min(self.map_height, y + dy * step)),
        )
        self.dirty = True
        self._redraw()

    def _on_zoom_changed(self, _event: tk.Event | None = None) -> None:
        for option_label, subsample in ZOOM_OPTIONS:
            if option_label == self.zoom_var.get():
                self.subsample = subsample
                self.scale = 1.0 / subsample
                break
        self._load_map_image()
        self._redraw()

    def _center_view(self) -> None:
        self.canvas.xview_moveto(0.35)
        self.canvas.yview_moveto(0.25)

    def _reload(self) -> None:
        if self.dirty and not messagebox.askyesno("Reload", "Discard unsaved changes?"):
            return
        wmc = import_coords_module(self.pack_root)
        self.group_coords = dict(wmc.REGION_WORLD_COORDS)
        self.layout, self.check_areas, self.check_names, self.check_records = build_editor_layout(
            self.pack_root
        )
        self.default_areas = {record["code"]: record["default_area"] for record in self.check_records}
        self.standalone_checks = dict(self.layout.standalone_checks)
        self.group_coords.update(self.layout.pin_coords)
        self.selected_area = None
        self.selected_standalone.clear()
        self.dirty = False
        self._redraw()
        self.status_var.set("Reloaded layout from disk.")

    def _save(self) -> None:
        write_world_map_coords(
            self.coords_path,
            self.group_coords,
            self.map_width,
            self.map_height,
        )
        save_layout(
            self.pack_root,
            check_areas=self.check_areas,
            default_areas=self.default_areas,
            standalone_checks=self.standalone_checks,
            pin_coords=self.group_coords,
        )
        import_coords_module(self.pack_root)
        self.dirty = False

        regen_note = ""
        if self.regenerate_on_save:
            subprocess.run(
                [sys.executable, str(self.pack_root / "tools" / "generate_pack.py")],
                cwd=self.pack_root,
                check=True,
            )
            regen_note = "\n\nPack regenerated automatically."
        else:
            regen_note = "\n\nRun: python tools/generate_pack.py"

        messagebox.showinfo(
            "Saved",
            "Updated:\n"
            "  tools/world_map_coords.py\n"
            "  tools/map_layout.json"
            f"{regen_note}",
        )

    def _on_close(self) -> None:
        if self.dirty and not messagebox.askyesno("Quit", "Save changes before quitting?"):
            if messagebox.askyesno("Quit", "Quit without saving?"):
                self.destroy()
            return
        if self.dirty:
            self._save()
        self.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=PACK_ROOT)
    parser.add_argument(
        "--from-world",
        action="store_true",
        help="Start pin coords from locations/world.json",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Run tools/generate_pack.py automatically after saving",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pack_root = args.pack.resolve()
    if not (pack_root / "tools" / "world_map_coords.py").exists():
        raise SystemExit(f"Not a pack root: {pack_root}")
    if not (pack_root / "locations" / "world.json").exists():
        raise SystemExit("Missing locations/world.json — run python tools/generate_pack.py first.")

    MapPinEditor(pack_root, from_world=args.from_world, regenerate=args.regenerate).mainloop()


if __name__ == "__main__":
    main()
