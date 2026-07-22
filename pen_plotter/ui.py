from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .gcode import generate_gcode, plot_bounds_including_preflight
from .geometry import (
    Drawing,
    crop_box_center,
    clip_strokes_to_crop,
    load_dxf_drawing,
    rotate_crop_box_ccw,
    rotate_drawing_ccw,
    rotate_drawing_quarters,
    transform_strokes,
)
from .settings import (
    DEFAULT_SETTINGS_PATH,
    DOWNLOADS_DIR,
    PROJECT_ROOT,
    TARGET_DOWNLOADS,
    CropBox,
    PlotterSettings,
    default_gcode_path,
    load_settings,
    save_settings,
    target_directory_path,
)
from .target_directories import TargetDirectoryChoice, list_target_directories
from .printer import BoundaryCheck, check_gcode_bounds, load_printer_profile


RAW_DIR = PROJECT_ROOT / "raw"


class PlotterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Ender 3 Pro Pen Plotter")
        self.geometry("1180x760")
        self.minsize(980, 640)

        self.settings = load_settings()
        self.printer = load_printer_profile()
        self.dxf_files: list[Path] = []
        self.current_file: Path | None = None
        self.drawing: Drawing | None = None
        self.crop: CropBox | None = None
        self.view_bounds = CropBox(0, 0, 100, 100)
        self.view_scale = 1.0
        self.view_margin = 28
        self.drag_mode: str | None = None
        self.drag_start_source = (0.0, 0.0)
        self.drag_start_canvas = (0.0, 0.0)
        self.drag_start_crop: CropBox | None = None
        self.drag_start_buildplate: CropBox | None = None
        self.drag_start_view: CropBox | None = None
        self.canvas_mode_var = tk.StringVar(value="pan")
        self.rotation_quarters = self.settings.rotation_quarters
        self.target_directory_choices: dict[str, TargetDirectoryChoice] = {}

        self._line_item_ids: list[int] = []
        self._text_item_ids: list[int] = []
        self._buildplate_item_ids: list[int] = []
        self._crop_item_ids: list[int] = []

        self._build_style()
        self._build_layout()
        self._set_canvas_mode()
        self._refresh_target_directories()
        self._refresh_file_list()
        self._select_initial_file()

        self.canvas.bind("<Configure>", lambda _event: self._redraw_canvas())
        self.after(50, self._load_current_file)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#f3f4f6")
        style.configure("Panel.TFrame", background="#ffffff")
        style.configure("TLabel", background="#ffffff", foreground="#1f2937")
        style.configure("Muted.TLabel", background="#ffffff", foreground="#6b7280")
        style.configure("Metric.TLabel", background="#ffffff", foreground="#111827")
        style.configure("Warning.TLabel", background="#ffffff", foreground="#b91c1c")
        style.configure("Section.TLabelframe", background="#ffffff", borderwidth=1)
        style.configure(
            "Section.TLabelframe.Label",
            background="#ffffff",
            foreground="#374151",
        )
        style.configure("TButton", padding=(10, 6))
        style.configure("Mode.TButton", padding=(10, 6))
        style.configure("ActiveMode.TButton", padding=(10, 6), background="#dbeafe")
        style.configure("Generate.TButton", padding=(12, 9))

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        self.rowconfigure(0, weight=1)

        canvas_frame = ttk.Frame(self, padding=14)
        canvas_frame.grid(row=0, column=0, sticky="nsew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            canvas_frame,
            bg="#fbfbfa",
            highlightthickness=1,
            highlightbackground="#d1d5db",
            cursor="crosshair",
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<Control-MouseWheel>", self._on_ctrl_mousewheel)
        self.canvas.bind("<Control-Button-4>", lambda event: self._zoom_at(event, 1 / 1.15))
        self.canvas.bind("<Control-Button-5>", lambda event: self._zoom_at(event, 1.15))

        panel = ttk.Frame(self, style="Panel.TFrame", padding=16)
        panel.grid(row=0, column=1, sticky="ns")
        panel.columnconfigure(0, weight=1)

        self.home_x_var = self._field_var(self.settings.home_x)
        self.home_y_var = self._field_var(self.settings.home_y)
        self.home_z_var = self._field_var(self.settings.home_z)
        self.origin_x_var = self._field_var(self.settings.origin_x)
        self.origin_y_var = self._field_var(self.settings.origin_y)
        self.target_directory_var = tk.StringVar()
        self.z_hop_var = self._field_var(self.settings.z_hop)
        self.z_safe_height_var = self._field_var(self.settings.z_safe_height)
        self.scale_var = self._field_var(self.settings.scale)
        self.bounding_box_repeat_var = self._field_var(self.settings.bounding_box_repeat)
        self.bounding_box_offset_var = self._field_var(self.settings.bounding_box_offset)
        self.bounding_box_feed_var = self._field_var(self.settings.bounding_box_feed)
        self.draw_feed_var = self._field_var(self.settings.draw_feed)
        self.travel_feed_var = self._field_var(self.settings.travel_feed)
        self.crop_readout_var = tk.StringVar(value="Crop (mm): -")
        self.origin_readout_var = tk.StringVar(value="Origin (mm): -")
        self.plot_size_var = tk.StringVar(value="Plot: -")
        self.plot_bounds_var = tk.StringVar(value="Bounds: -")
        self.bounds_warning_var = tk.StringVar(value="")
        self.entity_var = tk.StringVar(value="No DXF loaded")
        self.status_var = tk.StringVar(value="Drop a DXF into raw/ and reload.")

        row = 0

        def add_section(title: str, pady: tuple[int, int] = (0, 5)) -> ttk.LabelFrame:
            nonlocal row
            section = ttk.LabelFrame(
                panel,
                text=title,
                style="Section.TLabelframe",
                padding=(7, 5),
            )
            section.grid(row=row, column=0, sticky="ew", pady=pady)
            section.columnconfigure(0, weight=1)
            section.columnconfigure(1, weight=1)
            row += 1
            return section

        file_group = ttk.LabelFrame(
            panel,
            text="DXF File",
            style="Section.TLabelframe",
            padding=(7, 5),
        )
        file_group.grid(row=row, column=0, sticky="ew", pady=(0, 5))
        file_group.columnconfigure(1, weight=1)
        file_group.columnconfigure(2, weight=0)
        row += 1

        self.file_var = tk.StringVar()
        self.file_menu = ttk.OptionMenu(file_group, self.file_var, "")
        self.file_menu.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        ttk.Button(file_group, text="Reload", width=7, command=self._load_current_file).grid(
            row=0, column=2, sticky="e", padx=(6, 0), pady=(0, 5)
        )
        ttk.Label(file_group, text="Scale").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(file_group, textvariable=self.scale_var, width=9).grid(
            row=1, column=1, sticky="ew"
        )
        ttk.Button(file_group, text="Rotate", width=7, command=self._rotate_drawing_ccw).grid(
            row=1, column=2, sticky="e", padx=(6, 0)
        )

        crop_group = add_section("Crop")
        crop_group.columnconfigure(2, weight=1)
        ttk.Label(crop_group, textvariable=self.crop_readout_var, style="Metric.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 5)
        )
        self.crop_button = ttk.Button(
            crop_group,
            text="Crop",
            style="Mode.TButton",
            command=self._toggle_crop_mode,
        )
        self.crop_button.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(crop_group, text="Reset Crop", command=self._reset_crop).grid(
            row=1, column=1, sticky="ew", padx=(0, 6)
        )
        ttk.Button(crop_group, text="Max Crop", command=self._max_crop).grid(
            row=1, column=2, sticky="ew"
        )

        origin_group = add_section("Origin")
        ttk.Label(origin_group, textvariable=self.origin_readout_var, style="Metric.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 5)
        )
        self.origin_button = ttk.Button(
            origin_group,
            text="Origin",
            style="Mode.TButton",
            command=self._toggle_origin_mode,
        )
        self.origin_button.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(origin_group, text="Reset Origin", command=self._reset_origin).grid(
            row=1, column=1, sticky="ew"
        )

        home_frame = add_section("Home")
        for index, (label, variable) in enumerate(
            [
                ("X", self.home_x_var),
                ("Y", self.home_y_var),
                ("Z", self.home_z_var),
            ]
        ):
            home_frame.columnconfigure(index * 2 + 1, weight=1)
            ttk.Label(home_frame, text=label).grid(
                row=0,
                column=index * 2,
                sticky="w",
                padx=(0 if index == 0 else 7, 3),
            )
            ttk.Entry(home_frame, textvariable=variable, width=7).grid(
                row=0,
                column=index * 2 + 1,
                sticky="ew",
            )

        z_frame = add_section("Z Height")
        for index, (label, variable) in enumerate(
            [
                ("Hop", self.z_hop_var),
                ("Safe", self.z_safe_height_var),
            ]
        ):
            z_frame.columnconfigure(index * 2 + 1, weight=1)
            ttk.Label(z_frame, text=label).grid(
                row=0,
                column=index * 2,
                sticky="w",
                padx=(0 if index == 0 else 7, 3),
            )
            ttk.Entry(z_frame, textvariable=variable, width=9).grid(
                row=0,
                column=index * 2 + 1,
                sticky="ew",
            )

        feed_frame = add_section("Feed")
        for index, (label, variable) in enumerate(
            [
                ("Draw", self.draw_feed_var),
                ("Travel", self.travel_feed_var),
            ]
        ):
            feed_frame.columnconfigure(index * 2 + 1, weight=1)
            ttk.Label(feed_frame, text=label).grid(
                row=0,
                column=index * 2,
                sticky="w",
                padx=(0 if index == 0 else 7, 3),
            )
            ttk.Entry(feed_frame, textvariable=variable, width=9).grid(
                row=0,
                column=index * 2 + 1,
                sticky="ew",
            )

        bounding_box_frame = add_section("Bounding Box")
        for index, (label, variable) in enumerate(
            [
                ("Repeat", self.bounding_box_repeat_var),
                ("Offset", self.bounding_box_offset_var),
                ("Feed", self.bounding_box_feed_var),
            ]
        ):
            bounding_box_frame.columnconfigure(index * 2 + 1, weight=1)
            ttk.Label(bounding_box_frame, text=label).grid(
                row=0,
                column=index * 2,
                sticky="w",
                padx=(0 if index == 0 else 6, 3),
            )
            ttk.Entry(bounding_box_frame, textvariable=variable, width=7).grid(
                row=0,
                column=index * 2 + 1,
                sticky="ew",
            )

        preview_group = add_section("Preview")
        ttk.Label(preview_group, textvariable=self.plot_size_var, style="Metric.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 3)
        )
        ttk.Label(preview_group, textvariable=self.plot_bounds_var, style="Metric.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 5)
        )
        ttk.Label(
            preview_group,
            textvariable=self.bounds_warning_var,
            style="Warning.TLabel",
            wraplength=260,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 5))
        ttk.Label(
            preview_group,
            textvariable=self.entity_var,
            style="Muted.TLabel",
            wraplength=260,
        ).grid(row=3, column=0, columnspan=2, sticky="w")

        output_group = add_section("Output", pady=(0, 0))
        ttk.Label(output_group, text="Target Directory").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        self.target_directory_menu = ttk.Combobox(
            output_group,
            textvariable=self.target_directory_var,
            state="readonly",
        )
        self.target_directory_menu.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(3, 6)
        )
        self.target_directory_menu.bind(
            "<Button-1>", lambda _event: self._refresh_target_directories(prefer_current=True)
        )

        ttk.Button(
            output_group,
            text="Generate",
            style="Generate.TButton",
            command=self._generate,
        ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        ttk.Label(
            output_group,
            textvariable=self.status_var,
            style="Muted.TLabel",
            wraplength=260,
        ).grid(
            row=3, column=0, columnspan=2, sticky="sw"
        )
        output_group.rowconfigure(3, weight=1)
        panel.rowconfigure(row - 1, weight=1)

    def _field_var(self, value: float) -> tk.StringVar:
        variable = tk.StringVar(value=f"{value:g}")
        variable.trace_add("write", lambda *_args: self._update_dimension_readout())
        return variable

    def _toggle_crop_mode(self) -> None:
        self.canvas_mode_var.set("pan" if self.canvas_mode_var.get() == "crop" else "crop")
        self._set_canvas_mode()

    def _toggle_origin_mode(self) -> None:
        self.canvas_mode_var.set("pan" if self.canvas_mode_var.get() == "origin" else "origin")
        self._set_canvas_mode()

    def _set_canvas_mode(self) -> None:
        self.drag_mode = None
        mode = self.canvas_mode_var.get()
        cursor = "fleur" if mode in {"origin", "pan"} else "crosshair"
        self.canvas.configure(cursor=cursor)
        if hasattr(self, "crop_button"):
            self.crop_button.configure(
                style="ActiveMode.TButton" if mode == "crop" else "Mode.TButton"
            )
        if hasattr(self, "origin_button"):
            self.origin_button.configure(
                style="ActiveMode.TButton" if mode == "origin" else "Mode.TButton"
            )

    def _refresh_file_list(self) -> None:
        RAW_DIR.mkdir(exist_ok=True)
        DOWNLOADS_DIR.mkdir(exist_ok=True)
        self.dxf_files = sorted(
            path for path in RAW_DIR.iterdir() if path.suffix.lower() == ".dxf"
        )

        menu = self.file_menu["menu"]
        menu.delete(0, "end")
        if not self.dxf_files:
            self.file_var.set("")
            return

        for path in self.dxf_files:
            menu.add_command(
                label=path.name,
                command=lambda selected=path.name: self._on_file_selected(selected),
            )

    def _refresh_target_directories(self, prefer_current: bool = False) -> None:
        current_value = self._selected_target_directory_value()
        preferred = current_value if prefer_current else self.settings.target_directory
        choices = list_target_directories()
        self.target_directory_choices = {choice.label: choice for choice in choices}
        labels = [choice.label for choice in choices]
        self.target_directory_menu.configure(values=labels)

        selected_label = self._target_label_for_value(preferred)
        if selected_label is None:
            selected_label = self._target_label_for_value(TARGET_DOWNLOADS)
        if selected_label is None and labels:
            selected_label = labels[0]
        self.target_directory_var.set(selected_label or "")

    def _target_label_for_value(self, value: str | None) -> str | None:
        wanted_path = _normalized_path_text(target_directory_path(value))
        for label, choice in self.target_directory_choices.items():
            if choice.settings_value == value:
                return label
            if _normalized_path_text(choice.path) == wanted_path:
                return label
        return None

    def _selected_target_directory_value(self) -> str:
        if not hasattr(self, "target_directory_var"):
            return self.settings.target_directory
        choice = self.target_directory_choices.get(self.target_directory_var.get())
        if choice is None:
            return TARGET_DOWNLOADS
        return choice.settings_value

    def _select_initial_file(self) -> None:
        if not self.dxf_files:
            return

        active = _resolve_project_path(self.settings.active_file)
        if active and active.exists() and active.suffix.lower() == ".dxf":
            self.current_file = active
        else:
            self.current_file = self.dxf_files[0]
        self.file_var.set(self.current_file.name)

    def _on_file_selected(self, name: str) -> None:
        selected = next((path for path in self.dxf_files if path.name == name), None)
        if selected is None:
            return
        self.current_file = selected
        self.file_var.set(name)
        self._load_current_file()

    def _load_current_file(self) -> None:
        self.printer = load_printer_profile()
        self._refresh_file_list()
        if self.current_file is None and self.dxf_files:
            self.current_file = self.dxf_files[0]
            self.file_var.set(self.current_file.name)

        if self.current_file is None:
            self.status_var.set("No DXF files found in raw/.")
            return

        try:
            tolerance = self._float_from_var(
                self.scale_var, self.settings.scale, minimum=0.0001
            )
            tolerance = max(0.05, self.settings.curve_tolerance / max(tolerance, 0.0001))
            self.status_var.set(f"Loading {self.current_file.name}...")
            self.update_idletasks()
            drawing = load_dxf_drawing(self.current_file, curve_tolerance=tolerance)
            self.drawing = rotate_drawing_quarters(drawing, self.rotation_quarters)
        except Exception as exc:
            self.drawing = None
            messagebox.showerror("DXF load failed", str(exc))
            self.status_var.set("DXF load failed.")
            return

        if self.settings.crop and self.current_file == _resolve_project_path(self.settings.active_file):
            self.crop = self.settings.crop.normalized()
        else:
            self.crop = self.drawing.bounds.normalized()

        self._fit_view_to_drawing()
        self._redraw_canvas()
        self._update_dimension_readout()
        skipped = sum(self.drawing.skipped_counts.values())
        self.entity_var.set(
            f"{self.drawing.stroke_count} strokes, "
            f"{self.drawing.segment_count} segments, "
            f"{len(self.drawing.text_labels)} text labels"
            + (f"; skipped {skipped} non-plot entities" if skipped else "")
        )
        self.status_var.set(f"Loaded {self.current_file.name}.")

    def _rotate_drawing_ccw(self) -> None:
        if not self.drawing:
            return

        pivot = crop_box_center(self.drawing.bounds)
        self.drawing = rotate_drawing_ccw(self.drawing, pivot)
        if self.crop:
            self.crop = rotate_crop_box_ccw(self.crop, pivot)
        self.rotation_quarters = (self.rotation_quarters + 1) % 4
        self._fit_view_to_drawing()
        self._redraw_canvas()
        self._update_dimension_readout()
        if self.current_file:
            self.status_var.set(
                f"Rotated {self.current_file.name} CCW 90 deg. Origin unchanged."
            )

    def _fit_view_to_drawing(self) -> None:
        if not self.drawing:
            self.view_bounds = CropBox(0, 0, 100, 100)
            return

        bounds = self.drawing.bounds.normalized()
        pad_x = max(bounds.width * 0.04, 1.0)
        pad_y = max(bounds.height * 0.04, 1.0)
        self.view_bounds = CropBox(
            bounds.xmin - pad_x,
            bounds.ymin - pad_y,
            bounds.xmax + pad_x,
            bounds.ymax + pad_y,
        )

    def _reset_crop(self) -> None:
        if not self.drawing:
            return
        self.crop = self.drawing.bounds.normalized()
        self._redraw_canvas()
        self._update_dimension_readout()

    def _max_crop(self) -> None:
        if not self.drawing:
            return

        settings = self._settings_from_ui(update_crop=False)
        scale = max(settings.scale, 0.0001)
        max_width = max(self.printer.relative_safety_width(settings), 0.01)
        max_height = max(self.printer.relative_safety_height(settings), 0.01)
        if self.crop:
            box = self.crop.normalized()
            xmin, ymin = box.xmin, box.ymin
        else:
            bounds = self.drawing.bounds.normalized()
            xmin, ymin = bounds.xmin, bounds.ymin
        self.crop = CropBox(
            xmin=xmin,
            ymin=ymin,
            xmax=xmin + max_width / scale,
            ymax=ymin + max_height / scale,
        )
        self.bounding_box_offset_var.set("0")
        self._redraw_canvas()
        self._update_dimension_readout()

    def _reset_origin(self) -> None:
        if not self.crop:
            self.origin_x_var.set("0")
            self.origin_y_var.set("0")
            self._update_dimension_readout()
            return

        settings = self._settings_from_ui(update_crop=False)
        scale = max(settings.scale, 0.0001)
        crop = self.crop.normalized()
        self.origin_x_var.set(
            _format_number(crop.xmin - self.printer.relative_safety_x_min(settings) / scale)
        )
        self.origin_y_var.set(
            _format_number(crop.ymin - self.printer.relative_safety_y_min(settings) / scale)
        )
        self._update_dimension_readout()

    def _redraw_canvas(self) -> None:
        self.canvas.delete("all")
        self._line_item_ids.clear()
        self._text_item_ids.clear()
        self._buildplate_item_ids.clear()
        self._crop_item_ids.clear()
        self._update_view_transform()

        if not self.drawing:
            self.canvas.create_text(
                self.canvas.winfo_width() / 2,
                self.canvas.winfo_height() / 2,
                text="No DXF loaded",
                fill="#6b7280",
                font=("Segoe UI", 14),
            )
            return

        for preview_stroke in self.drawing.preview_strokes:
            stroke = preview_stroke.points
            if len(stroke) < 2:
                continue
            coords: list[float] = []
            for point in stroke:
                coords.extend(self._source_to_canvas(point))
            self._line_item_ids.append(
                self.canvas.create_line(
                    *coords,
                    fill=preview_stroke.color,
                    width=1,
                    capstyle=tk.ROUND,
                    joinstyle=tk.ROUND,
                )
            )

        self._draw_buildplate()
        self._draw_crop_box()

    def _draw_text_labels(self) -> None:
        if not self.drawing:
            return

        for label in self.drawing.text_labels:
            x, y = self._source_to_canvas((label.x, label.y))
            font_size = int(round(label.height * self.view_scale * 0.75))
            font_size = max(6, min(font_size, 22))
            self._text_item_ids.append(
                self.canvas.create_text(
                    x,
                    y,
                    text=label.text,
                    fill=label.color,
                    anchor=label.anchor,
                    angle=label.rotation,
                    font=("Malgun Gothic", font_size),
                )
            )

    def _draw_buildplate(self) -> None:
        settings = self._settings_from_ui(update_crop=False)
        plate = self._buildplate_source_box(settings)
        if plate is None:
            return

        box = plate.normalized()
        x1, y_bottom = self._source_to_canvas((box.xmin, box.ymin))
        x2, y_top = self._source_to_canvas((box.xmax, box.ymax))
        left, right = sorted((x1, x2))
        top, bottom = sorted((y_top, y_bottom))
        boundary_check = self._plot_boundary_check(settings)
        if boundary_check.blocked:
            plate_color = "#b91c1c"
        elif boundary_check.warning:
            plate_color = "#d97706"
        else:
            plate_color = "#16a34a"
        home_color = "#2563eb"

        self._buildplate_item_ids.append(
            self.canvas.create_rectangle(
                left,
                top,
                right,
                bottom,
                outline=plate_color,
                width=2,
                dash=(10, 5),
            )
        )

        printable = self._printable_source_box(settings).normalized()
        p_x1, p_y_bottom = self._source_to_canvas((printable.xmin, printable.ymin))
        p_x2, p_y_top = self._source_to_canvas((printable.xmax, printable.ymax))
        p_left, p_right = sorted((p_x1, p_x2))
        p_top, p_bottom = sorted((p_y_top, p_y_bottom))
        self._buildplate_item_ids.append(
            self.canvas.create_rectangle(
                p_left,
                p_top,
                p_right,
                p_bottom,
                outline="#0891b2",
                width=2,
                dash=(2, 4),
            )
        )

        origin_x, origin_y = self._source_to_canvas((settings.origin_x, settings.origin_y))
        self._buildplate_item_ids.extend(
            [
                self.canvas.create_rectangle(
                    origin_x - 6,
                    origin_y - 6,
                    origin_x + 6,
                    origin_y + 6,
                    fill=home_color,
                    outline="#ffffff",
                    width=2,
                ),
                self.canvas.create_line(
                    origin_x,
                    origin_y,
                    origin_x + 24,
                    origin_y,
                    fill=home_color,
                    width=2,
                    arrow=tk.LAST,
                ),
                self.canvas.create_line(
                    origin_x,
                    origin_y,
                    origin_x,
                    origin_y - 24,
                    fill=home_color,
                    width=2,
                    arrow=tk.LAST,
                ),
            ]
        )

    def _update_view_transform(self) -> None:
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        bounds = self.view_bounds.normalized()
        usable_width = max(width - self.view_margin * 2, 1)
        usable_height = max(height - self.view_margin * 2, 1)
        scale_x = usable_width / max(bounds.width, 0.001)
        scale_y = usable_height / max(bounds.height, 0.001)
        self.view_scale = min(scale_x, scale_y)

    def _draw_crop_box(self) -> None:
        if not self.crop:
            return

        box = self.crop.normalized()
        x1, y_bottom = self._source_to_canvas((box.xmin, box.ymin))
        x2, y_top = self._source_to_canvas((box.xmax, box.ymax))
        left, right = sorted((x1, x2))
        top, bottom = sorted((y_top, y_bottom))

        rect = self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            outline="#d9480f",
            width=2,
            dash=(7, 4),
        )
        fill = self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            outline="",
            fill="#f97316",
            stipple="gray75",
        )
        self.canvas.tag_lower(fill)
        self._crop_item_ids.extend([fill, rect])

        scale = self._current_scale()
        width_label = f"{box.width * scale:.1f} mm"
        height_label = f"{box.height * scale:.1f} mm"
        label_y = max(top - 13, 12)
        label_x = min(right + 14, self.canvas.winfo_width() - 12)
        self._crop_item_ids.append(
            self.canvas.create_text(
                (left + right) / 2,
                label_y,
                text=width_label,
                fill="#9a3412",
                font=("Segoe UI", 10, "bold"),
            )
        )
        self._crop_item_ids.append(
            self.canvas.create_text(
                label_x,
                (top + bottom) / 2,
                text=height_label,
                fill="#9a3412",
                angle=90,
                font=("Segoe UI", 10, "bold"),
            )
        )

        for name, x, y in self._handle_positions_canvas(box):
            size = 4 if len(name) == 1 else 5
            self._crop_item_ids.append(
                self.canvas.create_rectangle(
                    x - size,
                    y - size,
                    x + size,
                    y + size,
                    fill="#ffffff",
                    outline="#d9480f",
                    width=2,
                )
            )

    def _handle_positions_canvas(self, crop: CropBox) -> list[tuple[str, float, float]]:
        x1, y_bottom = self._source_to_canvas((crop.xmin, crop.ymin))
        x2, y_top = self._source_to_canvas((crop.xmax, crop.ymax))
        left, right = sorted((x1, x2))
        top, bottom = sorted((y_top, y_bottom))
        mid_x = (left + right) / 2
        mid_y = (top + bottom) / 2
        return [
            ("nw", left, top),
            ("n", mid_x, top),
            ("ne", right, top),
            ("e", right, mid_y),
            ("se", right, bottom),
            ("s", mid_x, bottom),
            ("sw", left, bottom),
            ("w", left, mid_y),
        ]

    def _on_canvas_press(self, event) -> None:
        if not self.drawing or not self.crop:
            return
        self.drag_start_source = self._canvas_to_source((event.x, event.y))
        self.drag_start_canvas = (float(event.x), float(event.y))
        self.drag_start_crop = self.crop.normalized()
        self.drag_start_buildplate = self._buildplate_source_box()
        self.drag_start_view = self.view_bounds.normalized()

        if self.canvas_mode_var.get() == "pan":
            self.drag_mode = "pan"
            return

        if self.canvas_mode_var.get() == "origin":
            self.drag_mode = "buildplate"
            return

        handle = self._hit_handle(event.x, event.y)
        if handle:
            self.drag_mode = f"resize:{handle}"
        elif self._point_in_crop_canvas(event.x, event.y):
            self.drag_mode = "move"
        else:
            self.drag_mode = "new"
            x, y = self._clamp_to_drawing(self.drag_start_source)
            self.crop = CropBox(x, y, x, y)
            self._redraw_canvas()

    def _on_canvas_drag(self, event) -> None:
        if not self.drawing or not self.crop or not self.drag_mode:
            return

        raw_point = self._canvas_to_source((event.x, event.y))
        point = raw_point if self.drag_mode == "buildplate" else self._clamp_to_drawing(raw_point)
        start_box = self.drag_start_crop or self.crop.normalized()

        if self.drag_mode == "pan" and self.drag_start_view:
            self._pan_view(event.x, event.y)
        elif self.drag_mode == "move":
            start_point = self.drag_start_source
            dx = point[0] - start_point[0]
            dy = point[1] - start_point[1]
            self.crop = self._move_crop(start_box, dx, dy)
        elif self.drag_mode == "new":
            start_x, start_y = self._clamp_to_drawing(self.drag_start_source)
            self.crop = CropBox(start_x, start_y, point[0], point[1]).normalized()
        elif self.drag_mode.startswith("resize:"):
            handle = self.drag_mode.split(":", 1)[1]
            self.crop = self._resize_crop(start_box, handle, point)
        elif self.drag_mode == "buildplate" and self.drag_start_buildplate:
            dx = point[0] - self.drag_start_source[0]
            dy = point[1] - self.drag_start_source[1]
            start_plate = self.drag_start_buildplate.normalized()
            moved_plate = CropBox(
                start_plate.xmin + dx,
                start_plate.ymin + dy,
                start_plate.xmax + dx,
                start_plate.ymax + dy,
            )
            self._set_origin_from_buildplate(moved_plate)

        self._redraw_canvas()
        if self.drag_mode != "pan":
            self._update_dimension_readout()

    def _on_canvas_release(self, _event) -> None:
        crop_drag = self.drag_mode in {"move", "new"} or (
            self.drag_mode is not None and self.drag_mode.startswith("resize:")
        )
        if self.crop and crop_drag:
            self.crop = self._minimum_crop_size(self.crop.normalized())
            self._redraw_canvas()
            self._update_dimension_readout()
        self.drag_mode = None
        self.drag_start_crop = None
        self.drag_start_buildplate = None
        self.drag_start_view = None

    def _pan_view(self, x: float, y: float) -> None:
        if not self.drag_start_view:
            return
        start_x, start_y = self.drag_start_canvas
        dx = (float(x) - start_x) / max(self.view_scale, 0.0001)
        dy = (float(y) - start_y) / max(self.view_scale, 0.0001)
        bounds = self.drag_start_view.normalized()
        self.view_bounds = CropBox(
            bounds.xmin - dx,
            bounds.ymin + dy,
            bounds.xmax - dx,
            bounds.ymax + dy,
        )

    def _on_ctrl_mousewheel(self, event) -> None:
        if event.delta == 0:
            return
        factor = 1 / 1.15 if event.delta > 0 else 1.15
        self._zoom_at(event, factor)

    def _zoom_at(self, event, factor: float) -> None:
        if not self.drawing:
            return
        anchor = self._canvas_to_source((event.x, event.y))
        bounds = self.view_bounds.normalized()
        new_width = max(bounds.width * factor, 1.0)
        new_height = max(bounds.height * factor, 1.0)
        rx = (anchor[0] - bounds.xmin) / max(bounds.width, 0.0001)
        ry = (anchor[1] - bounds.ymin) / max(bounds.height, 0.0001)
        self.view_bounds = CropBox(
            anchor[0] - rx * new_width,
            anchor[1] - ry * new_height,
            anchor[0] + (1 - rx) * new_width,
            anchor[1] + (1 - ry) * new_height,
        )
        self._redraw_canvas()

    def _move_crop(self, crop: CropBox, dx: float, dy: float) -> CropBox:
        if not self.drawing:
            return crop
        bounds = self.drawing.bounds.normalized()
        width = crop.width
        height = crop.height
        xmin = min(max(crop.xmin + dx, bounds.xmin), bounds.xmax - width)
        ymin = min(max(crop.ymin + dy, bounds.ymin), bounds.ymax - height)
        return CropBox(xmin, ymin, xmin + width, ymin + height)

    def _resize_crop(self, crop: CropBox, handle: str, point: tuple[float, float]) -> CropBox:
        xmin, ymin, xmax, ymax = crop.xmin, crop.ymin, crop.xmax, crop.ymax
        x, y = point
        if "w" in handle:
            xmin = x
        if "e" in handle:
            xmax = x
        if "s" in handle:
            ymin = y
        if "n" in handle:
            ymax = y
        return self._minimum_crop_size(CropBox(xmin, ymin, xmax, ymax).normalized())

    def _minimum_crop_size(self, crop: CropBox) -> CropBox:
        min_size = 0.01
        if crop.width < min_size:
            crop.xmax = crop.xmin + min_size
        if crop.height < min_size:
            crop.ymax = crop.ymin + min_size
        return crop.normalized()

    def _hit_handle(self, x: float, y: float) -> str | None:
        if not self.crop:
            return None
        for name, hx, hy in self._handle_positions_canvas(self.crop.normalized()):
            if abs(x - hx) <= 9 and abs(y - hy) <= 9:
                return name
        return None

    def _hit_buildplate(self, x: float, y: float) -> bool:
        plate = self._buildplate_source_box()
        if plate is None:
            return False

        box = plate.normalized()
        x1, y_bottom = self._source_to_canvas((box.xmin, box.ymin))
        x2, y_top = self._source_to_canvas((box.xmax, box.ymax))
        left, right = sorted((x1, x2))
        top, bottom = sorted((y_top, y_bottom))
        near_origin = abs(x - left) <= 12 and abs(y - bottom) <= 12
        near_vertical = (abs(x - left) <= 7 or abs(x - right) <= 7) and top <= y <= bottom
        near_horizontal = (abs(y - top) <= 7 or abs(y - bottom) <= 7) and left <= x <= right
        return near_origin or near_vertical or near_horizontal

    def _point_in_crop_canvas(self, x: float, y: float) -> bool:
        if not self.crop:
            return False
        box = self.crop.normalized()
        x1, y_bottom = self._source_to_canvas((box.xmin, box.ymin))
        x2, y_top = self._source_to_canvas((box.xmax, box.ymax))
        left, right = sorted((x1, x2))
        top, bottom = sorted((y_top, y_bottom))
        return left <= x <= right and top <= y <= bottom

    def _clamp_to_drawing(self, point: tuple[float, float]) -> tuple[float, float]:
        if not self.drawing:
            return point
        bounds = self.drawing.bounds.normalized()
        return (
            min(max(point[0], bounds.xmin), bounds.xmax),
            min(max(point[1], bounds.ymin), bounds.ymax),
        )

    def _source_to_canvas(self, point: tuple[float, float]) -> tuple[float, float]:
        x, y = point
        bounds = self.view_bounds.normalized()
        canvas_width = max(self.canvas.winfo_width(), 1)
        canvas_height = max(self.canvas.winfo_height(), 1)
        drawing_width = bounds.width * self.view_scale
        drawing_height = bounds.height * self.view_scale
        origin_x = (canvas_width - drawing_width) / 2
        origin_y = (canvas_height + drawing_height) / 2
        return (
            origin_x + (x - bounds.xmin) * self.view_scale,
            origin_y - (y - bounds.ymin) * self.view_scale,
        )

    def _canvas_to_source(self, point: tuple[float, float]) -> tuple[float, float]:
        x, y = point
        bounds = self.view_bounds.normalized()
        canvas_width = max(self.canvas.winfo_width(), 1)
        canvas_height = max(self.canvas.winfo_height(), 1)
        drawing_width = bounds.width * self.view_scale
        drawing_height = bounds.height * self.view_scale
        origin_x = (canvas_width - drawing_width) / 2
        origin_y = (canvas_height + drawing_height) / 2
        return (
            bounds.xmin + (x - origin_x) / self.view_scale,
            bounds.ymin + (origin_y - y) / self.view_scale,
        )

    def _current_scale(self) -> float:
        return self._float_from_var(self.scale_var, self.settings.scale, minimum=0.0001)

    def _buildplate_source_box(
        self, settings: PlotterSettings | None = None
    ) -> CropBox | None:
        settings = settings or self._settings_from_ui(update_crop=False)
        return self._source_box_for_buildplate_box(
            0.0,
            0.0,
            self.printer.boundary_x,
            self.printer.boundary_y,
            settings,
        )

    def _printable_source_box(
        self, settings: PlotterSettings | None = None
    ) -> CropBox:
        settings = settings or self._settings_from_ui(update_crop=False)
        return self._source_box_for_buildplate_box(
            self.printer.relative_safety_x_min(settings),
            self.printer.relative_safety_y_min(settings),
            self.printer.relative_safety_x_max(settings),
            self.printer.relative_safety_y_max(settings),
            settings,
        )

    def _source_box_for_buildplate_box(
        self,
        xmin: float,
        ymin: float,
        xmax: float,
        ymax: float,
        settings: PlotterSettings,
    ) -> CropBox:
        scale = max(settings.scale, 0.0001)
        return CropBox(
            xmin=settings.origin_x + xmin / scale,
            ymin=settings.origin_y + ymin / scale,
            xmax=settings.origin_x + xmax / scale,
            ymax=settings.origin_y + ymax / scale,
        ).normalized()

    def _origin_source_point(
        self, settings: PlotterSettings | None = None
    ) -> tuple[float, float]:
        settings = settings or self._settings_from_ui(update_crop=False)
        return (settings.origin_x, settings.origin_y)

    def _set_origin_from_buildplate(self, plate: CropBox) -> None:
        plate = plate.normalized()
        settings = self._settings_from_ui(update_crop=False)
        scale = max(settings.scale, 0.0001)
        self.origin_x_var.set(_format_number(plate.xmin))
        self.origin_y_var.set(_format_number(plate.ymin))

    def _plot_boundary_check(
        self, settings: PlotterSettings | None = None
    ) -> BoundaryCheck:
        if not self.crop:
            return BoundaryCheck()

        settings = settings or self._settings_from_ui(update_crop=False)
        bounds = plot_bounds_including_preflight(self.crop, settings)
        return check_gcode_bounds(bounds, settings, self.printer)

    def _update_dimension_readout(self) -> None:
        if not hasattr(self, "crop_readout_var") or not self.crop:
            return
        scale = self._current_scale()
        settings = self._settings_from_ui(update_crop=False)
        plot_bounds = plot_bounds_including_preflight(self.crop, settings)
        crop = self.crop.normalized()
        self.crop_readout_var.set(
            "Crop (mm): "
            f"X {_format_number(crop.xmin)} / "
            f"Y {_format_number(crop.ymin)} / "
            f"Xlen {_format_number(crop.width)} / "
            f"Ylen {_format_number(crop.height)}"
        )
        origin = self._origin_source_point(settings)
        self.origin_readout_var.set(
            "Origin (mm): "
            f"X {_format_number(origin[0])} / "
            f"Y {_format_number(origin[1])}"
        )
        self.plot_size_var.set(
            f"Plot: {self.crop.width * scale:.2f} x {self.crop.height * scale:.2f} mm"
        )
        self.plot_bounds_var.set(
            "Bounds: "
            f"X {_format_number(plot_bounds.xmin)}..{_format_number(plot_bounds.xmax)}, "
            f"Y {_format_number(plot_bounds.ymin)}..{_format_number(plot_bounds.ymax)}"
        )
        boundary_check = self._plot_boundary_check(settings)
        self.bounds_warning_var.set(boundary_check.message)
        if self.drawing:
            self._redraw_overlays_only()

    def _redraw_overlays_only(self) -> None:
        for item_id in self._buildplate_item_ids:
            self.canvas.delete(item_id)
        self._buildplate_item_ids.clear()
        for item_id in self._crop_item_ids:
            self.canvas.delete(item_id)
        self._crop_item_ids.clear()
        self._draw_buildplate()
        self._draw_crop_box()

    def _settings_from_ui(self, update_crop: bool = True) -> PlotterSettings:
        settings = PlotterSettings(
            active_file=_project_relative(self.current_file) if self.current_file else None,
            home_x=self._float_from_var(self.home_x_var, self.settings.home_x),
            home_y=self._float_from_var(self.home_y_var, self.settings.home_y),
            home_z=self._float_from_var(self.home_z_var, self.settings.home_z),
            origin_x=self._float_from_var(self.origin_x_var, self.settings.origin_x),
            origin_y=self._float_from_var(self.origin_y_var, self.settings.origin_y),
            z_hop=self._float_from_var(self.z_hop_var, self.settings.z_hop, minimum=0.0),
            z_safe_height=self._float_from_var(
                self.z_safe_height_var, self.settings.z_safe_height, minimum=0.0
            ),
            scale=self._float_from_var(self.scale_var, self.settings.scale, minimum=0.0001),
            rotation_quarters=self.rotation_quarters,
            bounding_box_repeat=self._int_from_var(
                self.bounding_box_repeat_var,
                self.settings.bounding_box_repeat,
                minimum=0,
            ),
            bounding_box_offset=self._float_from_var(
                self.bounding_box_offset_var,
                self.settings.bounding_box_offset,
                minimum=0.0,
            ),
            bounding_box_feed=self._float_from_var(
                self.bounding_box_feed_var,
                self.settings.bounding_box_feed,
                minimum=1.0,
            ),
            draw_feed=self._float_from_var(self.draw_feed_var, self.settings.draw_feed, minimum=1.0),
            travel_feed=self._float_from_var(
                self.travel_feed_var, self.settings.travel_feed, minimum=1.0
            ),
            curve_tolerance=self.settings.curve_tolerance,
            target_directory=self._selected_target_directory_value(),
            crop=self.crop.normalized() if update_crop and self.crop else self.crop,
        )
        settings.validate()
        return settings

    def _float_from_var(
        self, variable: tk.StringVar, fallback: float, minimum: float | None = None
    ) -> float:
        try:
            value = float(variable.get())
        except ValueError:
            value = fallback
        if minimum is not None:
            value = max(value, minimum)
        return value

    def _int_from_var(
        self, variable: tk.StringVar, fallback: int, minimum: int | None = None
    ) -> int:
        try:
            value = int(float(variable.get()))
        except ValueError:
            value = fallback
        if minimum is not None:
            value = max(value, minimum)
        return value

    def _generate(self) -> None:
        if not self.current_file or not self.drawing or not self.crop:
            messagebox.showwarning("Nothing to generate", "Load a DXF file first.")
            return

        self.printer = load_printer_profile()
        settings = self._settings_from_ui()
        cropped = clip_strokes_to_crop(self.drawing.strokes, self.crop)
        if not cropped:
            messagebox.showwarning("Empty crop", "The crop box does not contain plot geometry.")
            return

        transformed = transform_strokes(cropped, self.crop, settings)
        boundary_check = self._plot_boundary_check(settings)
        if boundary_check.blocked:
            self.bounds_warning_var.set(boundary_check.message)
            messagebox.showerror(
                "Plot exceeds Ender 3 Pro bounds",
                boundary_check.message
                + "\n\nG-code was not written because this can drive the print head "
                "outside the absolute printer boundary.",
            )
            return
        if boundary_check.warning:
            self.bounds_warning_var.set(boundary_check.message)

        self._refresh_target_directories(prefer_current=True)
        settings.target_directory = self._selected_target_directory_value()
        output_path = default_gcode_path(self.current_file, settings.target_directory)
        try:
            summary = generate_gcode(
                source_path=self.current_file,
                strokes=transformed,
                crop=self.crop,
                settings=settings,
                output_path=output_path,
            )
            self.settings = settings
            save_settings(self.settings, DEFAULT_SETTINGS_PATH)
        except Exception as exc:
            messagebox.showerror("Generation failed", str(exc))
            self.status_var.set("Generation failed.")
            return

        warning_text = boundary_check.message if boundary_check.warning else ""
        self.status_var.set(
            f"Wrote {summary.output_path} "
            f"({summary.stroke_count} strokes, {summary.segment_count} segments)."
            + (f" Warning: {warning_text}" if warning_text else "")
        )
        messagebox.showinfo(
            "G-code generated",
            f"Wrote {summary.output_path}\n\n"
            f"Plot size: {summary.plot_bounds.width:.2f} x {summary.plot_bounds.height:.2f} mm\n"
            f"Draw length: {summary.draw_length_mm:.1f} mm"
            + (f"\n\nWarning: {warning_text}" if warning_text else ""),
        )


def _resolve_project_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _project_relative(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _normalized_path_text(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path.absolute()).casefold()


def _format_number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def main() -> None:
    app = PlotterApp()
    app.mainloop()
