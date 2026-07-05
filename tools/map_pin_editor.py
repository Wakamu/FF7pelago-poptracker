#!/usr/bin/env python3
"""Visual editor for PopTracker maps, tabs, pin groups, and standalone checks.

Supports multiple map tabs (world overview + detailed area maps).
Run after save: python tools/generate_pack.py
"""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

TOOLS_DIR = Path(__file__).resolve().parent
PACK_ROOT = TOOLS_DIR.parent

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from map_layout import (  # noqa: E402
    STANDARD_AREAS,
    WORLD_MAP_ID,
    MapDefinition,
    MapLayout,
    MapPins,
    build_editor_layout,
    copy_map_image,
    pins_for_map,
    save_layout,
    slugify_map_id,
    pool_code_from_section,
    pool_code_from_visibility,
)

ZOOM_OPTIONS = (("12%", 8), ("25%", 4), ("50%", 2), ("100%", 1))
SNAP_GRID_SIZE = 10
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


def ordered_area_names(group_names: set[str]) -> list[str]:
    names: list[str] = []
    for name in STANDARD_AREAS:
        if name in group_names and name not in names:
            names.append(name)
    for name in sorted(group_names):
        if name not in names:
            names.append(name)
    return names


def write_world_map_coords(path: Path, world_groups: dict[str, tuple[int, int]], map_width: int, map_height: int) -> None:
    lines = [
        '"""Pixel coordinates for FF7 regions on images/worldmap.png (3200 x 2400)."""',
        "",
        "from __future__ import annotations",
        "",
        f"MAP_WIDTH = {map_width}",
        f"MAP_HEIGHT = {map_height}",
        "",
        "REGION_WORLD_COORDS: dict[str, tuple[int, int]] = {",
    ]
    for name in ordered_area_names(set(world_groups)):
        if name not in STANDARD_AREAS:
            continue
        x, y = world_groups[name]
        lines.append(f'    "{name}": ({x}, {y}),')
    lines.extend(
        [
            "}",
            "",
            'WORLD_MAP_ID = "world"',
            'WORLD_MAP_IMAGE = "images/worldmap.png"',
            "",
            "def world_area_name(region: str) -> str:",
            '    if region.startswith("Shops - "):',
            '        return region.removeprefix("Shops - ")',
            "    return region",
            "",
            "def area_hub(area: str) -> tuple[int, int]:",
            '    return REGION_WORLD_COORDS.get(area, REGION_WORLD_COORDS["Other Fields"])',
            "",
            "def area_pin_size(check_count: int) -> int:",
            "    if check_count >= 20: return 28",
            "    if check_count >= 8: return 24",
            "    if check_count >= 3: return 20",
            "    return 18",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


class ManageMapsDialog(tk.Toplevel):
    def __init__(self, parent: MapPinEditor) -> None:
        super().__init__(parent)
        self.parent = parent
        self.title("Manage map tabs")
        self.geometry("520x360")
        self.transient(parent)
        self.grab_set()

        ttk.Label(
            self,
            text="Each map becomes a PopTracker tab with its own background image. Tab order here is the PopTracker tab order.",
            wraplength=480,
        ).pack(anchor=tk.W, padx=10, pady=(10, 6))

        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=10)
        list_frame = ttk.Frame(frame)
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(list_frame, activestyle="none")
        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        order_btns = ttk.Frame(frame, padding=(8, 0))
        order_btns.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Button(order_btns, text="Move up", width=10, command=lambda: self._move_map(-1)).pack(pady=(0, 4))
        ttk.Button(order_btns, text="Move down", width=10, command=lambda: self._move_map(1)).pack()
        self.refresh()

        btns = ttk.Frame(self)
        btns.pack(fill=tk.X, padx=10, pady=8)
        ttk.Button(btns, text="Add map...", command=self.add_map).pack(side=tk.LEFT)
        ttk.Button(btns, text="Rename", command=self.rename_map).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="Change image...", command=self.change_image).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="Remove", command=self.remove_map).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="Close", command=self.destroy).pack(side=tk.RIGHT)

    def refresh(self) -> None:
        self.listbox.delete(0, tk.END)
        for map_def in self.parent.layout.maps:
            suffix = " [built-in]" if map_def.builtin else ""
            self.listbox.insert(tk.END, f"{map_def.title} ({map_def.id}){suffix}")

    def _selected_index(self) -> int | None:
        idx = self.listbox.curselection()
        return idx[0] if idx else None

    def _selected_map(self) -> MapDefinition | None:
        i = self._selected_index()
        if i is None:
            return None
        return self.parent.layout.maps[i]

    def _move_map(self, direction: int) -> None:
        i = self._selected_index()
        if i is None:
            return
        j = i + direction
        maps = self.parent.layout.maps
        if j < 0 or j >= len(maps):
            return
        maps[i], maps[j] = maps[j], maps[i]
        self.parent.dirty = True
        self.parent._refresh_map_selector()
        self.refresh()
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(j)
        self.listbox.activate(j)
        self.listbox.see(j)

    def add_map(self) -> None:
        title = simpledialog.askstring("Add map tab", "Tab title:", parent=self)
        if not title:
            return
        title = title.strip()
        if not title:
            return
        map_id = slugify_map_id(title)
        existing = {m.id for m in self.parent.layout.maps}
        if map_id in existing:
            base = map_id
            n = 2
            while f"{base}_{n}" in existing:
                n += 1
            map_id = f"{base}_{n}"

        image_path = filedialog.askopenfilename(
            parent=self,
            title="Choose background image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp"), ("All", "*.*")],
        )
        if not image_path:
            return
        rel = copy_map_image(self.parent.pack_root, Path(image_path), map_id)
        self.parent.layout.maps.append(MapDefinition(id=map_id, title=title, image=rel))
        self.parent.layout.pins[map_id] = MapPins()
        self.parent.dirty = True
        self.parent._refresh_map_selector()
        self.refresh()

    def rename_map(self) -> None:
        map_def = self._selected_map()
        if not map_def:
            return
        title = simpledialog.askstring("Rename tab", "Tab title:", initialvalue=map_def.title, parent=self)
        if not title or not title.strip():
            return
        map_def.title = title.strip()
        self.parent.dirty = True
        self.parent._refresh_map_selector()
        self.refresh()

    def change_image(self) -> None:
        map_def = self._selected_map()
        if not map_def:
            return
        image_path = filedialog.askopenfilename(
            parent=self,
            title="Choose background image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp"), ("All", "*.*")],
        )
        if not image_path:
            return
        map_def.image = copy_map_image(self.parent.pack_root, Path(image_path), map_def.id)
        self.parent.dirty = True
        if self.parent.active_map_id == map_def.id:
            self.parent._load_active_map_image()

    def remove_map(self) -> None:
        map_def = self._selected_map()
        if not map_def:
            return
        if map_def.builtin:
            messagebox.showwarning("Remove map", "The world map tab cannot be removed.", parent=self)
            return
        if not messagebox.askyesno("Remove map", f"Remove tab '{map_def.title}' and its pin placements?", parent=self):
            return
        self.parent.layout.maps = [m for m in self.parent.layout.maps if m.id != map_def.id]
        self.parent.layout.pins.pop(map_def.id, None)
        if self.parent.active_map_id == map_def.id:
            self.parent.active_map_id = WORLD_MAP_ID
        self.parent.dirty = True
        self.parent._refresh_map_selector()
        self.parent._load_active_map_image()
        self.parent._redraw()
        self.refresh()


class MapPinEditor(tk.Tk):
    def __init__(self, pack_root: Path, from_world: bool, regenerate: bool) -> None:
        super().__init__()
        self.title("FF7 Pelago Map Pin Editor")
        self.geometry("1480x940")
        self.minsize(1100, 700)

        self.pack_root = pack_root
        self.regenerate_on_save = regenerate
        self.coords_path = pack_root / "tools" / "world_map_coords.py"

        wmc = import_coords_module(pack_root)
        self.default_map_width = wmc.MAP_WIDTH
        self.default_map_height = wmc.MAP_HEIGHT

        self.layout, self.check_areas, self.check_names, self.check_records = build_editor_layout(pack_root)
        self.default_areas = {r["code"]: r["default_area"] for r in self.check_records}
        self.active_map_id = self.layout.maps[0].id if self.layout.maps else WORLD_MAP_ID

        if from_world:
            self._import_positions_from_world_json()

        self.map_width = self.default_map_width
        self.map_height = self.default_map_height
        self.subsample = 4
        self.scale = 0.25
        self.photo = None
        self.selected_area: str | None = None
        self.selected_standalone: set[int] = set()
        self.drag_area: str | None = None
        self.drag_standalone: int | None = None
        self.drag_offset = (0, 0)
        self.dirty = False

        self._build_ui()
        self._load_active_map_image()
        self._redraw()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    @property
    def current_pins(self) -> MapPins:
        return pins_for_map(self.layout, self.active_map_id)

    def _active_map(self) -> MapDefinition:
        for map_def in self.layout.maps:
            if map_def.id == self.active_map_id:
                return map_def
        return self.layout.maps[0]

    def _map_image_path(self) -> Path:
        rel = self._active_map().image
        path = self.pack_root / rel
        if not path.exists() and rel == "images/worldmap.png":
            return self.pack_root / "worldmap.png"
        return path

    def _is_standalone_on_tab(self, code: int) -> bool:
        return code in self.current_pins.standalone

    def _checks_for_area(self, area: str) -> list[int]:
        return sorted(
            code for code, assigned in self.check_areas.items()
            if assigned == area
        )

    def _check_count(self, area: str) -> int:
        return len(self._checks_for_area(area))

    def _is_custom_group(self, area: str) -> bool:
        return area not in STANDARD_AREAS

    def _all_group_names(self) -> set[str]:
        names = set(self.check_areas.values())
        names.update(self.current_pins.groups)
        return names

    def _view_center_map(self) -> tuple[int, int]:
        x0 = self.canvas.canvasx(0)
        y0 = self.canvas.canvasy(0)
        x1 = self.canvas.canvasx(max(1, self.canvas.winfo_width()))
        y1 = self.canvas.canvasy(max(1, self.canvas.winfo_height()))
        return int((x0 + x1) / 2 / self.scale), int((y0 + y1) / 2 / self.scale)

    def _import_positions_from_world_json(self) -> None:
        world_json = self.pack_root / "locations" / "world.json"
        if not world_json.exists():
            return
        world_pins = pins_for_map(self.layout, WORLD_MAP_ID)
        for entry in json.loads(world_json.read_text(encoding="utf-8")):
            name = entry["name"]
            for map_loc in entry.get("map_locations") or []:
                map_id = map_loc.get("map", WORLD_MAP_ID)
                pos = (int(map_loc.get("x", 0)), int(map_loc.get("y", 0)))
                target = pins_for_map(self.layout, map_id)
                if map_id == WORLD_MAP_ID and name in STANDARD_AREAS:
                    target.groups[name] = pos
                elif len(entry.get("sections") or []) == 1:
                    section = (entry.get("sections") or [{}])[0]
                    if section.get("ref"):
                        code = pool_code_from_visibility(entry)
                    else:
                        code = pool_code_from_section(section)
                    if code:
                        target.standalone[code] = pos
                else:
                    target.groups[name] = pos

            for section in entry.get("sections") or []:
                code = pool_code_from_section(section)
                if code is None:
                    continue
                for map_loc in section.get("map_locations") or []:
                    map_id = map_loc.get("map", WORLD_MAP_ID)
                    if map_id == WORLD_MAP_ID:
                        continue
                    pos = (int(map_loc.get("x", 0)), int(map_loc.get("y", 0)))
                    pins_for_map(self.layout, map_id).standalone[code] = pos

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.pack(fill=tk.X)

        ttk.Label(toolbar, text="Map tab:").pack(side=tk.LEFT)
        self.map_var = tk.StringVar()
        self.map_selector = ttk.Combobox(toolbar, textvariable=self.map_var, state="readonly", width=24)
        self.map_selector.pack(side=tk.LEFT, padx=(4, 8))
        self.map_selector.bind("<<ComboboxSelected>>", self._on_map_changed)
        ttk.Button(toolbar, text="Manage tabs...", command=self._manage_maps).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Label(toolbar, text="Zoom:").pack(side=tk.LEFT)
        self.zoom_var = tk.StringVar(value="25%")
        zoom_box = ttk.Combobox(toolbar, textvariable=self.zoom_var, values=[l for l, _ in ZOOM_OPTIONS], state="readonly", width=8)
        zoom_box.pack(side=tk.LEFT, padx=(4, 12))
        zoom_box.bind("<<ComboboxSelected>>", self._on_zoom_changed)

        ttk.Button(toolbar, text="Save", command=self._save).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Reload", command=self._reload).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Center view", command=self._center_view).pack(side=tk.LEFT, padx=4)

        self.status_var = tk.StringVar(
            value="Gold = groups on this tab. Cyan = standalone on this tab. Hold Shift while dragging to snap to grid."
        )
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
        group_btns = ttk.Frame(side)
        group_btns.pack(fill=tk.X, pady=(4, 4))
        ttk.Button(group_btns, text="New group...", command=self._new_pin_group).pack(side=tk.LEFT)
        ttk.Button(group_btns, text="Add to this tab", command=self._add_group_to_tab).pack(side=tk.LEFT, padx=6)
        ttk.Button(group_btns, text="Remove from tab", command=self._remove_group_from_tab).pack(side=tk.LEFT)

        area_frame = ttk.Frame(side)
        area_frame.pack(fill=tk.X)
        self.area_list = tk.Listbox(area_frame, exportselection=False, activestyle="none", height=7)
        area_scroll = ttk.Scrollbar(area_frame, orient=tk.VERTICAL, command=self.area_list.yview)
        self.area_list.configure(yscrollcommand=area_scroll.set)
        self.area_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        area_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.area_list.bind("<<ListboxSelect>>", self._on_area_select)

        ttk.Separator(side, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
        ttk.Label(side, text="Checks in group", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)

        check_frame = ttk.Frame(side)
        check_frame.pack(fill=tk.BOTH, expand=True)
        self.check_list = tk.Listbox(check_frame, exportselection=False, activestyle="none", selectmode=tk.EXTENDED)
        check_scroll = ttk.Scrollbar(check_frame, orient=tk.VERTICAL, command=self.check_list.yview)
        self.check_list.configure(yscrollcommand=check_scroll.set)
        self.check_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        check_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        move_row = ttk.Frame(side)
        move_row.pack(fill=tk.X, pady=(8, 4))
        ttk.Label(move_row, text="Move to:").pack(side=tk.LEFT)
        self.move_target = ttk.Combobox(move_row, state="readonly", width=20)
        self.move_target.pack(side=tk.LEFT, padx=(6, 6), fill=tk.X, expand=True)
        ttk.Button(move_row, text="Move", command=self._move_selected_checks).pack(side=tk.LEFT)

        action_row = ttk.Frame(side)
        action_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(action_row, text="Standalone on tab", command=self._make_standalone).pack(side=tk.LEFT)
        ttk.Button(action_row, text="Remove from tab", command=self._remove_standalone_from_tab).pack(side=tk.LEFT, padx=6)
        ttk.Button(action_row, text="Reset checks", command=self._reset_selected_checks).pack(side=tk.LEFT)

        self.detail_var = tk.StringVar(value="")
        ttk.Label(side, textvariable=self.detail_var, wraplength=280, justify=tk.LEFT).pack(anchor=tk.W, pady=(10, 0))

        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.bind("<Left>", lambda _e: self._nudge(-1, 0))
        self.bind("<Right>", lambda _e: self._nudge(1, 0))
        self.bind("<Up>", lambda _e: self._nudge(0, -1))
        self.bind("<Down>", lambda _e: self._nudge(0, 1))

        self._refresh_map_selector()

    def _refresh_map_selector(self) -> None:
        labels = [f"{m.title} ({m.id})" for m in self.layout.maps]
        self.map_selector.configure(values=labels)
        for map_def in self.layout.maps:
            if map_def.id == self.active_map_id:
                self.map_var.set(f"{map_def.title} ({map_def.id})")
                break

    def _on_map_changed(self, _event: tk.Event | None = None) -> None:
        label = self.map_var.get()
        map_id = label.rsplit("(", 1)[-1].rstrip(")")
        self.active_map_id = map_id
        self.selected_area = None
        self.selected_standalone.clear()
        self._load_active_map_image()
        self._redraw()
        self.status_var.set(f"Editing tab: {self._active_map().title}")

    def _manage_maps(self) -> None:
        ManageMapsDialog(self)

    def _display_size(self) -> tuple[int, int]:
        return int(self.map_width * self.scale), int(self.map_height * self.scale)

    def _load_active_map_image(self) -> None:
        path = self._map_image_path()
        if not path.exists():
            messagebox.showerror("Missing map", f"Background not found:\n{path}")
            return
        source = tk.PhotoImage(file=str(path))
        self.map_width = source.width()
        self.map_height = source.height()
        self.photo = source.subsample(self.subsample, self.subsample) if self.subsample > 1 else source
        self.canvas.delete("map")
        w, h = self._display_size()
        self.canvas.create_image(0, 0, image=self.photo, anchor=tk.NW, tags=("map",))
        self.canvas.configure(scrollregion=(0, 0, w, h))

    def _redraw(self) -> None:
        self._draw_group_pins()
        self._draw_standalone_pins()
        self._refresh_area_list()
        self._update_detail()

    def _draw_group_pins(self) -> None:
        self.canvas.delete("group")
        pins = self.current_pins
        for area, (x, y) in pins.groups.items():
            if self._check_count(area) == 0 and self._is_custom_group(area):
                continue
            count = max(self._check_count(area), 1)
            size = pin_size_for_checks(count)
            sx, sy = x * self.scale, y * self.scale
            ds = max(8, size * self.scale)
            x0, y0 = sx - ds / 2, sy - ds / 2
            selected = area == self.selected_area and not self.selected_standalone
            label = area + (" [custom]" if self._is_custom_group(area) else "")
            self.canvas.create_rectangle(
                x0, y0, x0 + ds, y0 + ds,
                fill=GROUP_FILL_SELECTED if selected else GROUP_FILL,
                outline=PIN_OUTLINE_SELECTED if selected else PIN_OUTLINE,
                width=2 if selected else 1,
                tags=("group", f"group:{area}"),
            )
            self.canvas.create_text(
                sx, y0 + ds + 8, text=f"{label} ({self._check_count(area)})",
                fill="#ffffff", font=("Segoe UI", 8, "bold"), anchor=tk.N, tags=("group",),
            )

    def _draw_standalone_pins(self) -> None:
        self.canvas.delete("standalone")
        for code, (x, y) in self.current_pins.standalone.items():
            sx, sy = x * self.scale, y * self.scale
            ds = max(7, 14 * self.scale)
            x0, y0 = sx - ds / 2, sy - ds / 2
            selected = code in self.selected_standalone
            name = self.check_names.get(code, str(code))
            short = name if len(name) <= 28 else name[:25] + "..."
            self.canvas.create_rectangle(
                x0, y0, x0 + ds, y0 + ds,
                fill=STANDALONE_FILL_SELECTED if selected else STANDALONE_FILL,
                outline=PIN_OUTLINE_SELECTED if selected else PIN_OUTLINE,
                width=2 if selected else 1,
                tags=("standalone", f"standalone:{code}"),
            )
            self.canvas.create_text(
                sx, y0 + ds + 8, text=short, fill="#b3e5fc",
                font=("Segoe UI", 7), anchor=tk.N, tags=("standalone",),
            )

    def _refresh_area_list(self) -> None:
        self.area_list.delete(0, tk.END)
        names = ordered_area_names(self._all_group_names())
        for name in names:
            on_tab = name in self.current_pins.groups
            marker = "" if on_tab else " (not on tab)"
            self.area_list.insert(tk.END, f"{name} [{self._check_count(name)}]{marker}")
        self.move_target.configure(values=names)
        self._refresh_check_list()

    def _refresh_check_list(self) -> None:
        self.check_list.delete(0, tk.END)
        if not self.selected_area:
            return
        for code in self._checks_for_area(self.selected_area):
            name = self.check_names.get(code, str(code))
            on_tab = code in self.current_pins.standalone
            suffix = " [on tab]" if on_tab else ""
            if self.default_areas.get(code) != self.selected_area:
                suffix += " *"
            self.check_list.insert(tk.END, f"{name}{suffix}")

    def _selected_check_codes(self) -> list[int]:
        if not self.selected_area:
            return []
        codes = self._checks_for_area(self.selected_area)
        return [codes[i] for i in self.check_list.curselection()]

    def _update_detail(self) -> None:
        map_def = self._active_map()
        lines = [f"Tab: {map_def.title} ({map_def.id})", f"Image: {map_def.image}"]
        if self.selected_standalone:
            lines.append(f"{len(self.selected_standalone)} standalone on this tab")
            for code in sorted(self.selected_standalone):
                x, y = self.current_pins.standalone[code]
                lines.append(f"  {self.check_names.get(code, code)} @ {x},{y}")
        elif self.selected_area:
            x, y = self.current_pins.groups.get(self.selected_area, (0, 0))
            on_tab = self.selected_area in self.current_pins.groups
            lines.append(f"Group: {self.selected_area}")
            lines.append(f"On this tab: {'yes' if on_tab else 'no'}")
            if on_tab:
                lines.append(f"Position: {x}, {y}")
            lines.append(f"Checks: {self._check_count(self.selected_area)}")
        self.detail_var.set("\n".join(lines))

    def _select_area(self, area: str | None, *, focus: bool = False) -> None:
        self.selected_area = area
        self.selected_standalone.clear()
        self._redraw()
        if area and focus:
            pos = self.current_pins.groups.get(area)
            if pos:
                sx, sy = pos[0] * self.scale, pos[1] * self.scale
                self.canvas.xview_moveto(max(0.0, min(1.0, (sx - 200) / max(1, self._display_size()[0]))))
                self.canvas.yview_moveto(max(0.0, min(1.0, (sy - 200) / max(1, self._display_size()[1]))))

    def _select_standalone(self, code: int | None, *, focus: bool = False) -> None:
        self.selected_area = None
        self.selected_standalone = {code} if code is not None else set()
        self.area_list.selection_clear(0, tk.END)
        self._redraw()
        if code is not None and focus:
            x, y = self.current_pins.standalone[code]
            sx, sy = x * self.scale, y * self.scale
            self.canvas.xview_moveto(max(0.0, min(1.0, (sx - 200) / max(1, self._display_size()[0]))))
            self.canvas.yview_moveto(max(0.0, min(1.0, (sy - 200) / max(1, self._display_size()[1]))))

    def _new_pin_group(self) -> None:
        name = simpledialog.askstring("New pin group", "Group name:", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        cx, cy = self._view_center_map()
        self.current_pins.groups[name] = (cx, cy)
        self.dirty = True
        self._select_area(name, focus=True)

    def _add_group_to_tab(self) -> None:
        if not self.selected_area:
            messagebox.showwarning("Add to tab", "Select a pin group first.")
            return
        if self.selected_area in self.current_pins.groups:
            return
        self.current_pins.groups[self.selected_area] = self._view_center_map()
        self.dirty = True
        self._redraw()

    def _remove_group_from_tab(self) -> None:
        if not self.selected_area:
            return
        self.current_pins.groups.pop(self.selected_area, None)
        self.dirty = True
        self._redraw()

    def _move_selected_checks(self) -> None:
        target = self.move_target.get().strip()
        codes = self._selected_check_codes()
        if not target or not codes:
            return
        for code in codes:
            self.check_areas[code] = target
        self.dirty = True
        self._select_area(target)

    def _make_standalone(self) -> None:
        codes = self._selected_check_codes()
        if not codes:
            return
        base = self.current_pins.groups.get(self.selected_area or "", self._view_center_map())
        for i, code in enumerate(codes):
            self.current_pins.standalone[code] = (base[0] + i * 24, base[1] + i * 24)
        self.dirty = True
        self._select_standalone(codes[0], focus=True)

    def _remove_standalone_from_tab(self) -> None:
        codes = list(self.selected_standalone) or self._selected_check_codes()
        for code in codes:
            self.current_pins.standalone.pop(code, None)
        self.selected_standalone.clear()
        self.dirty = True
        self._redraw()

    def _reset_selected_checks(self) -> None:
        codes = self._selected_check_codes()
        if not codes:
            return
        for code in codes:
            for pins in self.layout.pins.values():
                pins.standalone.pop(code, None)
            default = self.default_areas.get(code)
            if default:
                self.check_areas[code] = default
        self.dirty = True
        self._select_area(self.selected_area)

    def _clamp_map_pos(self, x: int, y: int) -> tuple[int, int]:
        return (
            max(0, min(self.map_width, x)),
            max(0, min(self.map_height, y)),
        )

    def _snap_map_pos(self, x: int, y: int) -> tuple[int, int]:
        return self._clamp_map_pos(
            int(round(x / SNAP_GRID_SIZE)) * SNAP_GRID_SIZE,
            int(round(y / SNAP_GRID_SIZE)) * SNAP_GRID_SIZE,
        )

    def _canvas_to_map(self, cx: float, cy: float, *, snap: bool = False) -> tuple[int, int]:
        x = int(round(cx / self.scale))
        y = int(round(cy / self.scale))
        if snap:
            return self._snap_map_pos(x, y)
        return self._clamp_map_pos(x, y)

    def _on_canvas_press(self, event: tk.Event) -> None:
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        for item in reversed(self.canvas.find_overlapping(cx, cy, cx, cy)):
            for tag in self.canvas.gettags(item):
                if tag.startswith("standalone:"):
                    code = int(tag.split(":", 1)[1])
                    self._select_standalone(code)
                    px, py = self.current_pins.standalone[code]
                    self.drag_standalone = code
                    self.drag_area = None
                    self.drag_offset = (cx - px * self.scale, cy - py * self.scale)
                    return
        for item in reversed(self.canvas.find_overlapping(cx, cy, cx, cy)):
            for tag in self.canvas.gettags(item):
                if tag.startswith("group:"):
                    area = tag.split(":", 1)[1]
                    self._select_area(area)
                    px, py = self.current_pins.groups[area]
                    self.drag_area = area
                    self.drag_standalone = None
                    self.drag_offset = (cx - px * self.scale, cy - py * self.scale)
                    return
        self.selected_standalone.clear()
        self.selected_area = None
        self._update_detail()

    def _on_canvas_drag(self, event: tk.Event) -> None:
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        snap = bool(event.state & 0x0001) or "Shift" in self.state()
        pos = self._canvas_to_map(cx - self.drag_offset[0], cy - self.drag_offset[1], snap=snap)
        if self.drag_standalone is not None:
            self.current_pins.standalone[self.drag_standalone] = pos
        elif self.drag_area:
            self.current_pins.groups[self.drag_area] = pos
        else:
            return
        self.dirty = True
        self._redraw()

    def _on_canvas_release(self, _event: tk.Event) -> None:
        self.drag_area = None
        self.drag_standalone = None

    def _on_area_select(self, _event: tk.Event) -> None:
        sel = self.area_list.curselection()
        if not sel:
            return
        name = ordered_area_names(self._all_group_names())[sel[0]]
        self._select_area(name, focus=True)

    def _nudge(self, dx: int, dy: int) -> None:
        shift = "Shift" in self.state()
        step = SNAP_GRID_SIZE if shift else 1
        if self.selected_standalone:
            for code in self.selected_standalone:
                x, y = self.current_pins.standalone[code]
                nx, ny = x + dx * step, y + dy * step
                if shift:
                    nx, ny = self._snap_map_pos(nx, ny)
                else:
                    nx, ny = self._clamp_map_pos(nx, ny)
                self.current_pins.standalone[code] = (nx, ny)
        elif self.selected_area and self.selected_area in self.current_pins.groups:
            x, y = self.current_pins.groups[self.selected_area]
            nx, ny = x + dx * step, y + dy * step
            if shift:
                nx, ny = self._snap_map_pos(nx, ny)
            else:
                nx, ny = self._clamp_map_pos(nx, ny)
            self.current_pins.groups[self.selected_area] = (nx, ny)
        else:
            return
        self.dirty = True
        self._redraw()

    def _on_zoom_changed(self, _event: tk.Event | None = None) -> None:
        for label, sub in ZOOM_OPTIONS:
            if label == self.zoom_var.get():
                self.subsample = sub
                self.scale = 1.0 / sub
                break
        self._load_active_map_image()
        self._redraw()

    def _center_view(self) -> None:
        self.canvas.xview_moveto(0.35)
        self.canvas.yview_moveto(0.25)

    def _reload(self) -> None:
        if self.dirty and not messagebox.askyesno("Reload", "Discard unsaved changes?"):
            return
        self.layout, self.check_areas, self.check_names, self.check_records = build_editor_layout(self.pack_root)
        self.default_areas = {r["code"]: r["default_area"] for r in self.check_records}
        self.active_map_id = WORLD_MAP_ID
        self.dirty = False
        self._refresh_map_selector()
        self._load_active_map_image()
        self._redraw()

    def _save(self) -> None:
        world_groups = pins_for_map(self.layout, WORLD_MAP_ID).groups
        write_world_map_coords(
            self.coords_path,
            world_groups,
            self.default_map_width,
            self.default_map_height,
        )
        save_layout(
            self.pack_root,
            self.layout,
            check_areas=self.check_areas,
            default_areas=self.default_areas,
        )
        import_coords_module(self.pack_root)
        self.dirty = False

        if self.regenerate_on_save:
            subprocess.run([sys.executable, str(self.pack_root / "tools" / "generate_pack.py")], cwd=self.pack_root, check=True)
            note = "\n\nPack regenerated."
        else:
            note = "\n\nRun: python tools/generate_pack.py"

        messagebox.showinfo("Saved", f"Updated world_map_coords.py and map_layout.json{note}")

    def _on_close(self) -> None:
        if self.dirty and not messagebox.askyesno("Quit", "Save before quitting?"):
            if messagebox.askyesno("Quit", "Quit without saving?"):
                self.destroy()
            return
        if self.dirty:
            self._save()
        self.destroy()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pack", type=Path, default=PACK_ROOT)
    p.add_argument("--from-world", action="store_true")
    p.add_argument("--regenerate", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    pack_root = args.pack.resolve()
    if not (pack_root / "locations" / "world.json").exists():
        raise SystemExit("Run python tools/generate_pack.py first.")
    MapPinEditor(pack_root, args.from_world, args.regenerate).mainloop()


if __name__ == "__main__":
    main()
