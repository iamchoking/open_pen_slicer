from __future__ import annotations

import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # pragma: no cover - dependency is listed for runtime installs.
    DND_FILES = None
    TkinterDnD = None

from .gcode import (
    bounding_box_corner_l_strokes,
    bounding_box_dotted_strokes,
    generate_gcode,
    plot_bounds_including_preflight,
)
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
    MAX_RECENT_FILES,
    PROJECT_ROOT,
    TARGET_DOWNLOADS,
    CropBox,
    PlotterSettings,
    default_gcode_path,
    default_output_filename,
    load_settings,
    normalize_output_filename,
    save_settings,
    target_directory_path,
)
from .target_directories import (
    TargetDirectoryChoice,
    clear_gcode_files_from_target,
    eject_target_directory,
    list_target_directories,
)
from .printer import (
    BoundaryCheck,
    DEFAULT_DEVICES_DIR,
    PrinterProfile,
    check_gcode_bounds,
    load_printer_profiles,
)


NARROW_ENTRY_WIDTH = 4
SCALE_ENTRY_WIDTH = 7
MENU_WIDTH = 16
OUTPUT_FIELD_WIDTH = 16
SETTINGS_CONTROL_WIDTH = 190


_TkBase = TkinterDnD.Tk if TkinterDnD is not None else tk.Tk


class PlotterApp(_TkBase):
    def __init__(self) -> None:
        super().__init__()
        self.title("Open Pen Slicer")
        self.geometry("1100x760")
        self.minsize(900, 640)

        self.settings = load_settings()
        self.printer_profiles = load_printer_profiles()
        self.printer = self._selected_printer_profile()
        self.settings.device_id = self.printer.key
        self._apply_printer_values_to_settings()
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
        self.device_label_to_id: dict[str, str] = {}
        self.file_label_to_path: dict[str, Path] = {}

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
        self._setup_drag_and_drop()

        self.canvas.bind("<Configure>", lambda _event: self._redraw_canvas())
        self.after(50, self._load_current_file)

    def _selected_printer_profile(self) -> PrinterProfile:
        if self.settings.device_id in self.printer_profiles:
            return self.printer_profiles[self.settings.device_id]
        return next(iter(self.printer_profiles.values()))

    def _apply_printer_values_to_settings(self) -> None:
        self.settings.home_x = self.printer.home_x
        self.settings.home_y = self.printer.home_y
        self.settings.home_z = self.printer.home_z
        self.settings.z_hop = self.printer.z_hop
        self.settings.z_safe_height = self.printer.z_safe_height
        self.settings.draw_speed = self.printer.draw_speed
        self.settings.travel_speed = self.printer.travel_speed

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
        style.configure("TButton", padding=(5, 4))
        style.configure("Mode.TButton", padding=(5, 4))
        style.configure("ActiveMode.TButton", padding=(5, 4), background="#dbeafe")
        style.configure("Generate.TButton", padding=(7, 6))

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

        panel = ttk.Frame(self, style="Panel.TFrame", padding=(10, 14))
        self.panel = panel
        panel.grid(row=0, column=1, sticky="ns")
        panel.columnconfigure(0, weight=1)

        self.device_var = tk.StringVar()
        self.home_x_var = self._field_var(self.settings.home_x)
        self.home_y_var = self._field_var(self.settings.home_y)
        self.home_z_var = self._field_var(self.settings.home_z)
        self.boundary_x_var = tk.StringVar()
        self.boundary_y_var = tk.StringVar()
        self.boundary_z_var = tk.StringVar()
        self.origin_x_var = self._field_var(self.settings.origin_x)
        self.origin_y_var = self._field_var(self.settings.origin_y)
        self.output_filename_var = tk.StringVar(value=self.settings.output_filename or "")
        self.target_directory_var = tk.StringVar()
        self.clear_before_write_var = tk.BooleanVar(value=self.settings.clear_before_write)
        self.eject_after_write_var = tk.BooleanVar(value=self.settings.eject_after_write)
        self.device_bounds_var = tk.StringVar()
        self.device_home_var = tk.StringVar()
        self.device_z_height_var = tk.StringVar()
        self.device_speed_var = tk.StringVar()
        self.z_hop_var = self._field_var(self.settings.z_hop)
        self.z_safe_height_var = self._field_var(self.settings.z_safe_height)
        self.scale_var = self._field_var(self.settings.scale)
        self.bounding_box_repeat_var = self._field_var(self.settings.bounding_box_repeat)
        self.bounding_box_offset_var = self._field_var(self.settings.bounding_box_offset)
        self.bounding_box_speed_var = self._field_var(self.settings.bounding_box_speed)
        self.draw_speed_var = self._field_var(self.settings.draw_speed)
        self.travel_speed_var = self._field_var(self.settings.travel_speed)
        self.plot_size_var = tk.StringVar(value="Plot: -")
        self.plot_bounds_var = tk.StringVar(value="Bounds: -")
        self.bounds_warning_var = tk.StringVar(value="")
        self.entity_var = tk.StringVar(value="No DXF loaded")
        self.status_var = tk.StringVar(value="Drop a DXF file into the UI to load it.")

        row = 0

        def add_section(title: str, pady: tuple[int, int] = (0, 5)) -> ttk.LabelFrame:
            nonlocal row
            section = ttk.LabelFrame(
                panel,
                text=title,
                style="Section.TLabelframe",
                padding=(4, 4),
            )
            section.grid(row=row, column=0, sticky="ew", pady=pady)
            row += 1
            return section

        device_group = add_section("Device")
        device_group.columnconfigure(1, weight=1)
        ttk.Label(device_group, text="Device").grid(
            row=0, column=0, sticky="w", padx=(0, 4), pady=(0, 5)
        )
        self.device_menu = ttk.Combobox(
            device_group,
            textvariable=self.device_var,
            state="readonly",
            width=MENU_WIDTH,
        )
        self.device_menu.grid(row=0, column=1, sticky="ew", pady=(0, 5))
        self.device_menu.bind("<<ComboboxSelected>>", self._on_device_selected)

        for row_index, variable in enumerate(
            [
                self.device_bounds_var,
                self.device_home_var,
                self.device_z_height_var,
                self.device_speed_var,
            ],
            start=1,
        ):
            ttk.Label(
                device_group,
                textvariable=variable,
                style="Metric.TLabel",
            ).grid(
                row=row_index,
                column=0,
                columnspan=2,
                sticky="w",
                pady=(0, 2),
            )

        device_buttons = ttk.Frame(device_group, style="Panel.TFrame")
        device_buttons.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        for column_index in range(2):
            device_buttons.columnconfigure(column_index, weight=1, uniform="device_buttons")
        ttk.Button(device_buttons, text="Edit", width=1, command=self._edit_device_yaml).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(device_buttons, text="Reload", width=1, command=self._reload_device_yaml).grid(
            row=0, column=1, sticky="ew"
        )

        self._refresh_device_menu()

        settings_group = add_section("Settings")
        settings_group.columnconfigure(1, minsize=SETTINGS_CONTROL_WIDTH)

        def controls_frame(row_index: int) -> ttk.Frame:
            frame = ttk.Frame(settings_group, style="Panel.TFrame")
            frame.grid(row=row_index, column=1, sticky="ew", pady=(0, 4))
            return frame

        self.file_var = tk.StringVar()
        ttk.Label(settings_group, text="File").grid(
            row=0, column=0, sticky="w", padx=(0, 6), pady=(0, 4)
        )
        file_controls = controls_frame(0)
        file_controls.columnconfigure(0, weight=1)
        self.file_menu = ttk.Combobox(
            file_controls,
            textvariable=self.file_var,
            state="readonly",
            width=MENU_WIDTH,
        )
        self.file_menu.grid(row=0, column=0, sticky="ew")
        self.file_menu.bind("<<ComboboxSelected>>", self._on_file_selected)
        ttk.Button(file_controls, text="Reload", width=7, command=self._load_current_file).grid(
            row=0, column=1, sticky="w", padx=(6, 0)
        )

        ttk.Separator(settings_group, orient="horizontal").grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(1, 5)
        )
        ttk.Label(settings_group, text="Scale").grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(0, 5)
        )
        scale_controls = controls_frame(2)
        scale_controls.columnconfigure(1, weight=1)
        ttk.Entry(scale_controls, textvariable=self.scale_var, width=NARROW_ENTRY_WIDTH).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(scale_controls, text="Rotate", width=7, command=self._rotate_drawing_ccw).grid(
            row=0, column=1, sticky="e", padx=(6, 0)
        )

        ttk.Separator(settings_group, orient="horizontal").grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(1, 5)
        )
        ttk.Label(settings_group, text="Crop").grid(
            row=4, column=0, sticky="w", padx=(0, 6)
        )
        crop_controls = controls_frame(4)
        for column_index in range(3):
            crop_controls.columnconfigure(column_index, weight=1, uniform="crop_buttons")
        self.crop_button = ttk.Button(
            crop_controls,
            text="Crop",
            style="Mode.TButton",
            width=1,
            command=self._toggle_crop_mode,
        )
        self.crop_button.grid(row=0, column=0, sticky="ew")
        ttk.Button(crop_controls, text="Reset", width=1, command=self._reset_crop).grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Button(crop_controls, text="Max", width=1, command=self._max_crop).grid(
            row=0, column=2, sticky="ew"
        )

        ttk.Separator(settings_group, orient="horizontal").grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(6, 5)
        )
        ttk.Label(settings_group, text="Origin").grid(
            row=6, column=0, sticky="w", padx=(0, 6)
        )
        origin_controls = controls_frame(6)
        for column_index in range(2):
            origin_controls.columnconfigure(column_index, weight=1, uniform="origin_buttons")
        self.origin_button = ttk.Button(
            origin_controls,
            text="Set Origin",
            style="Mode.TButton",
            width=1,
            command=self._toggle_origin_mode,
        )
        self.origin_button.grid(row=0, column=0, sticky="ew")
        ttk.Button(origin_controls, text="Center", width=1, command=self._center_origin).grid(
            row=0, column=1, sticky="ew"
        )

        ttk.Separator(settings_group, orient="horizontal").grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=(6, 5)
        )
        ttk.Label(settings_group, text="Box").grid(
            row=8, column=0, sticky="w", padx=(0, 6)
        )
        bbox_controls = controls_frame(8)
        for index, (label, variable) in enumerate(
            [
                ("Num", self.bounding_box_repeat_var),
                ("Pad", self.bounding_box_offset_var),
                ("Spd", self.bounding_box_speed_var),
            ]
        ):
            ttk.Label(bbox_controls, text=label).grid(
                row=0,
                column=index * 2,
                sticky="w",
                padx=(0 if index == 0 else 6, 3),
            )
            ttk.Entry(bbox_controls, textvariable=variable, width=NARROW_ENTRY_WIDTH).grid(
                row=0,
                column=index * 2 + 1,
                sticky="w",
        )

        preview_group = add_section("Preview")
        preview_group.columnconfigure(0, weight=1)
        ttk.Label(preview_group, textvariable=self.plot_size_var, style="Metric.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 3)
        )
        ttk.Button(
            preview_group,
            text="Fit Screen",
            width=9,
            command=self._fit_screen,
        ).grid(
            row=0, column=1, sticky="e", pady=(0, 3)
        )
        ttk.Label(
            preview_group,
            textvariable=self.bounds_warning_var,
            style="Warning.TLabel",
            wraplength=220,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 5))
        ttk.Label(
            preview_group,
            textvariable=self.entity_var,
            style="Muted.TLabel",
            wraplength=220,
        ).grid(row=2, column=0, columnspan=2, sticky="w")

        output_group = add_section("Output", pady=(0, 0))
        output_group.columnconfigure(1, weight=1)
        ttk.Label(output_group, text="Filename").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 5)
        )
        ttk.Entry(output_group, textvariable=self.output_filename_var, width=OUTPUT_FIELD_WIDTH).grid(
            row=0, column=1, sticky="ew", pady=(0, 5)
        )
        ttk.Label(output_group, text="Write To: ").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 6)
        )
        self.target_directory_menu = ttk.Combobox(
            output_group,
            textvariable=self.target_directory_var,
            state="readonly",
            width=OUTPUT_FIELD_WIDTH,
        )
        self.target_directory_menu.grid(
            row=1, column=1, sticky="ew", pady=(0, 6)
        )
        self.target_directory_menu.bind(
            "<Button-1>", lambda _event: self._refresh_target_directories(prefer_current=True)
        )
        self.target_directory_menu.bind(
            "<<ComboboxSelected>>", self._on_target_directory_selected
        )

        output_options = ttk.Frame(output_group, style="Panel.TFrame")
        output_options.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        for column_index in range(2):
            output_options.columnconfigure(column_index, weight=1, uniform="output_options")
        self.clear_before_write_check = ttk.Checkbutton(
            output_options,
            text="Clear Drive",
            variable=self.clear_before_write_var,
        )
        self.clear_before_write_check.grid(row=0, column=0, sticky="w")
        self.eject_after_write_check = ttk.Checkbutton(
            output_options,
            text="Eject",
            variable=self.eject_after_write_var,
        )
        self.eject_after_write_check.grid(row=0, column=1, sticky="w")

        output_buttons = ttk.Frame(output_group, style="Panel.TFrame")
        output_buttons.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        for column_index in range(2):
            output_buttons.columnconfigure(column_index, weight=1, uniform="output_buttons")
        ttk.Button(
            output_buttons,
            text="Save Settings",
            width=1,
            command=self._save_current_settings,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(
            output_buttons,
            text="Write G-code",
            width=1,
            command=self._generate,
        ).grid(row=0, column=1, sticky="ew", padx=(3, 0))

        ttk.Label(
            output_group,
            textvariable=self.status_var,
            style="Muted.TLabel",
            wraplength=220,
        ).grid(
            row=4, column=0, columnspan=2, sticky="ew"
        )
        ttk.Label(
            output_group,
            text="Length unit: mm, Speed unit: mm/s",
            style="Muted.TLabel",
        ).grid(row=5, column=0, columnspan=2, sticky="e")
        output_group.rowconfigure(4, weight=1)
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

    def _refresh_device_menu(self) -> None:
        labels = [profile.name for profile in self.printer_profiles.values()]
        self.device_label_to_id = {
            profile.name: key for key, profile in self.printer_profiles.items()
        }
        self.device_menu.configure(values=labels)
        self.device_var.set(self.printer.name)
        self._set_device_vars_from_printer()

    def _on_device_selected(self, _event=None) -> None:
        device_id = self.device_label_to_id.get(self.device_var.get())
        if not device_id or device_id not in self.printer_profiles:
            return
        self.printer = self.printer_profiles[device_id]
        self.settings.device_id = self.printer.key
        self._apply_printer_values_to_settings()
        self._set_device_vars_from_printer()
        self._update_dimension_readout()

    def _edit_device_yaml(self) -> None:
        path = self.printer.config_path or DEFAULT_DEVICES_DIR / f"{self.printer.key}.yaml"
        if not path.exists():
            messagebox.showerror(
                "Device YAML missing",
                f"Could not find the device YAML file:\n{path}",
            )
            return
        try:
            subprocess.Popen(["notepad.exe", str(path)])
        except OSError as exc:
            messagebox.showerror("Could not open Notepad", str(exc))

    def _reload_device_yaml(self) -> None:
        current_key = self.printer.key
        try:
            profiles = load_printer_profiles()
        except Exception as exc:
            messagebox.showerror("Device reload failed", str(exc))
            self.status_var.set("Device reload failed.")
            return

        self.printer_profiles = profiles
        if current_key in self.printer_profiles:
            self.printer = self.printer_profiles[current_key]
        elif self.settings.device_id in self.printer_profiles:
            self.printer = self.printer_profiles[self.settings.device_id]
        else:
            self.printer = next(iter(self.printer_profiles.values()))

        self.settings.device_id = self.printer.key
        self._apply_printer_values_to_settings()
        self._refresh_device_menu()
        self._redraw_canvas()
        self._update_dimension_readout()
        self.status_var.set(f"Reloaded device settings from {self.printer.config_path}.")

    def _set_device_vars_from_printer(self) -> None:
        self.home_x_var.set(_format_number(self.printer.home_x))
        self.home_y_var.set(_format_number(self.printer.home_y))
        self.home_z_var.set(_format_number(self.printer.home_z))
        self.z_hop_var.set(_format_number(self.printer.z_hop))
        self.z_safe_height_var.set(_format_number(self.printer.z_safe_height))
        self.draw_speed_var.set(_format_number(self.printer.draw_speed))
        self.travel_speed_var.set(_format_number(self.printer.travel_speed))
        self._update_boundary_vars()
        self.device_bounds_var.set(
            "Bounds: "
            f"[{_format_number(self.printer.boundary_x)}, "
            f"{_format_number(self.printer.boundary_y)}, "
            f"{_format_number(self.printer.boundary_z)}] "
            f"(Margin: {self.printer.safety_margin:.1f})"
        )
        self.device_home_var.set(
            "Home: "
            f"[{self.printer.home_x:.1f}, "
            f"{self.printer.home_y:.1f}, "
            f"{self.printer.home_z:.1f}]"
        )
        self.device_z_height_var.set(
            "Z Height: "
            f"Hop {_format_number(self.printer.z_hop)} / "
            f"Safe {_format_number(self.printer.z_safe_height)}"
        )
        self.device_speed_var.set(
            "Speed: "
            f"Draw {_format_number(self.printer.draw_speed)} / "
            f"Travel {_format_number(self.printer.travel_speed)}"
        )

    def _update_boundary_vars(self) -> None:
        self.boundary_x_var.set(_format_number(self.printer.boundary_x))
        self.boundary_y_var.set(_format_number(self.printer.boundary_y))
        self.boundary_z_var.set(_format_number(self.printer.boundary_z))

    def _refresh_file_list(self) -> None:
        paths: list[Path] = []
        for value in [self.settings.active_file, *self.settings.recent_files]:
            path = _resolve_project_path(value)
            if path and path.suffix.lower() == ".dxf":
                paths.append(path)

        self.dxf_files = _dedupe_paths(paths)[:MAX_RECENT_FILES]
        self.file_label_to_path = {
            _file_display_text(path): path for path in self.dxf_files
        }
        labels = list(self.file_label_to_path)
        self.file_menu.configure(values=labels)
        if self.current_file:
            self.file_var.set(_file_display_text(self.current_file))
        elif not labels:
            self.file_var.set("")

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
        self._update_eject_after_write_state()

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
        choice = self._selected_target_directory_choice()
        if choice is None:
            return TARGET_DOWNLOADS
        return choice.settings_value

    def _selected_target_directory_choice(self) -> TargetDirectoryChoice | None:
        if not hasattr(self, "target_directory_var"):
            return None
        return self.target_directory_choices.get(self.target_directory_var.get())

    def _on_target_directory_selected(self, _event=None) -> None:
        self._update_eject_after_write_state()

    def _update_eject_after_write_state(self) -> None:
        if not hasattr(self, "eject_after_write_check"):
            return

        choice = self._selected_target_directory_choice()
        if choice and choice.is_removable:
            self.eject_after_write_check.configure(state="normal")
            self.clear_before_write_check.configure(state="normal")
        else:
            self.eject_after_write_check.configure(state="disabled")
            self.clear_before_write_check.configure(state="disabled")

    def _sync_output_filename_for_file(
        self,
        previous_file: Path | None = None,
        prefer_saved: bool = False,
        force_default: bool = False,
    ) -> None:
        if not self.current_file or not hasattr(self, "output_filename_var"):
            return

        current_value = self.output_filename_var.get().strip()
        previous_default = default_output_filename(previous_file) if previous_file else ""
        if force_default:
            self.output_filename_var.set(default_output_filename(self.current_file))
        elif prefer_saved and self.settings.output_filename:
            self.output_filename_var.set(
                normalize_output_filename(self.current_file, self.settings.output_filename)
            )
        elif not current_value or current_value == previous_default:
            self.output_filename_var.set(default_output_filename(self.current_file))

    def _selected_output_filename(self) -> str | None:
        if not self.current_file or not hasattr(self, "output_filename_var"):
            return None
        filename = normalize_output_filename(
            self.current_file,
            self.output_filename_var.get(),
        )
        self.output_filename_var.set(filename)
        return filename

    def _select_initial_file(self) -> None:
        active = _resolve_project_path(self.settings.active_file)
        if active and active.exists() and active.suffix.lower() == ".dxf":
            self.current_file = active
        else:
            self.current_file = next((path for path in self.dxf_files if path.exists()), None)
        if not self.current_file:
            return
        self.file_var.set(_file_display_text(self.current_file))
        self._sync_output_filename_for_file(prefer_saved=True)

    def _on_file_selected(self, _event=None) -> None:
        label = self.file_var.get()
        selected = self.file_label_to_path.get(label)
        if selected is None:
            return
        if not selected.exists():
            messagebox.showerror("DXF missing", f"Could not find:\n{selected}")
            self.status_var.set("Selected DXF file is missing.")
            return
        previous_file = self.current_file
        self.current_file = selected.resolve()
        self.file_var.set(_file_display_text(self.current_file))
        self._sync_output_filename_for_file(
            previous_file=previous_file,
            force_default=True,
        )
        self._load_current_file()

    def _load_current_file(self) -> None:
        self._refresh_file_list()
        if self.current_file is None:
            self.current_file = next((path for path in self.dxf_files if path.exists()), None)
        if self.current_file is not None:
            self.file_var.set(_file_display_text(self.current_file))
            self._sync_output_filename_for_file()

        if self.current_file is None:
            self.status_var.set("No DXF loaded. Drop a DXF file into the UI.")
            return

        if not self.current_file.exists():
            self.status_var.set("Current DXF file is missing.")
            messagebox.showerror("DXF missing", f"Could not find:\n{self.current_file}")
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

        self._fit_view_to_buildplate()
        self._redraw_canvas()
        self._update_dimension_readout()
        self._remember_current_file(save=True)
        skipped = sum(self.drawing.skipped_counts.values())
        self.entity_var.set(
            f"{self.drawing.stroke_count} strokes, "
            f"{self.drawing.segment_count} segments, "
            f"{len(self.drawing.text_labels)} text labels"
            + (f"; skipped {skipped} non-plot entities" if skipped else "")
        )
        self.status_var.set(f"Loaded {self.current_file.name}.")

    def _setup_drag_and_drop(self) -> None:
        if DND_FILES is None:
            self.status_var.set(
                "Install tkinterdnd2 to enable DXF drag and drop."
            )
            return

        for widget in (self, self.canvas, getattr(self, "panel", None)):
            if widget is None:
                continue
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_file_drop)

    def _on_file_drop(self, event) -> str:
        paths = self._drop_event_paths(event)
        dxf_path = next(
            (path for path in paths if path.suffix.lower() == ".dxf"),
            None,
        )
        if dxf_path is None:
            messagebox.showwarning("No DXF dropped", "Drop a .dxf file to load it.")
            return "break"
        if not dxf_path.exists():
            messagebox.showerror("DXF missing", f"Could not find:\n{dxf_path}")
            return "break"

        previous_file = self.current_file
        self.current_file = dxf_path.resolve()
        self._sync_output_filename_for_file(
            previous_file=previous_file,
            force_default=True,
        )
        self._load_current_file()
        return "break"

    def _drop_event_paths(self, event) -> list[Path]:
        data = getattr(event, "data", "")
        try:
            values = self.tk.splitlist(data)
        except tk.TclError:
            values = (data,)

        paths: list[Path] = []
        for value in values:
            text = str(value).strip()
            if text.startswith("file:///"):
                text = text[8:]
            if text:
                paths.append(Path(text).expanduser())
        return paths

    def _remember_current_file(self, save: bool = False) -> None:
        if not self.current_file:
            return

        file_text = _settings_file_text(self.current_file)
        self.settings.active_file = file_text
        self.settings.recent_files = _recent_file_texts_with(
            file_text,
            self.settings.recent_files,
        )
        self._refresh_file_list()
        self.file_var.set(_file_display_text(self.current_file))

        if not save:
            return
        try:
            settings = self._settings_from_ui()
            settings.active_file = file_text
            settings.recent_files = self.settings.recent_files
            save_settings(settings, DEFAULT_SETTINGS_PATH)
            self.settings = settings
        except Exception as exc:
            self.status_var.set(f"Loaded DXF, but could not save file history: {exc}")

    def _rotate_drawing_ccw(self) -> None:
        if not self.drawing:
            return

        pivot = crop_box_center(self.drawing.bounds)
        self.drawing = rotate_drawing_ccw(self.drawing, pivot)
        if self.crop:
            self.crop = rotate_crop_box_ccw(self.crop, pivot)
        self.rotation_quarters = (self.rotation_quarters + 1) % 4
        self._fit_view_to_buildplate()
        self._redraw_canvas()
        self._update_dimension_readout()
        if self.current_file:
            self.status_var.set(
                f"Rotated {self.current_file.name} CCW 90 deg. Origin unchanged."
            )

    def _fit_view_to_buildplate(self) -> None:
        plate = self._buildplate_source_box()
        if plate is None:
            self.view_bounds = CropBox(0, 0, 100, 100)
            return

        bounds = plate.normalized()
        pad_x = max(bounds.width * 0.04, 1.0)
        pad_y = max(bounds.height * 0.04, 1.0)
        self.view_bounds = CropBox(
            bounds.xmin - pad_x,
            bounds.ymin - pad_y,
            bounds.xmax + pad_x,
            bounds.ymax + pad_y,
        )

    def _fit_screen(self) -> None:
        self._fit_view_to_buildplate()
        self._redraw_canvas()
        self._update_dimension_readout()
        self.status_var.set("Fit buildplate to screen.")

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

    def _center_origin(self) -> None:
        if not self.crop:
            self.origin_x_var.set("0")
            self.origin_y_var.set("0")
            self._update_dimension_readout()
            return

        settings = self._settings_from_ui(update_crop=False)
        scale = max(settings.scale, 0.0001)
        crop = self.crop.normalized()
        crop_center_x = (crop.xmin + crop.xmax) / 2.0
        crop_center_y = (crop.ymin + crop.ymax) / 2.0
        printable_center_x = (
            self.printer.relative_safety_x_min(settings)
            + self.printer.relative_safety_x_max(settings)
        ) / 2.0
        printable_center_y = (
            self.printer.relative_safety_y_min(settings)
            + self.printer.relative_safety_y_max(settings)
        ) / 2.0
        self.origin_x_var.set(
            _format_number(crop_center_x - printable_center_x / scale)
        )
        self.origin_y_var.set(
            _format_number(crop_center_y - printable_center_y / scale)
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

    def _box_canvas_rect(self, box: CropBox) -> tuple[float, float, float, float]:
        box = box.normalized()
        x1, y_bottom = self._source_to_canvas((box.xmin, box.ymin))
        x2, y_top = self._source_to_canvas((box.xmax, box.ymax))
        left, right = sorted((x1, x2))
        top, bottom = sorted((y_top, y_bottom))
        return left, top, right, bottom

    def _dimension_label(self, value: float) -> str:
        return _format_number(value)

    def _clamped_label_point(self, x: float, y: float) -> tuple[float, float]:
        margin = 12
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        return (
            min(max(x, margin), width - margin),
            min(max(y, margin), height - margin),
        )

    def _draw_horizontal_dimension(
        self,
        item_ids: list[int],
        x1: float,
        x2: float,
        y: float,
        value: float,
        color: str,
        text_offset: float = -9,
    ) -> None:
        if abs(x2 - x1) >= 6:
            item_ids.append(
                self.canvas.create_line(
                    x1,
                    y,
                    x2,
                    y,
                    fill=color,
                    width=1,
                    arrow=tk.BOTH,
                )
            )
        for x in (x1, x2):
            item_ids.append(
                self.canvas.create_line(x, y - 4, x, y + 4, fill=color, width=1)
            )
        text_x, text_y = self._clamped_label_point((x1 + x2) / 2, y + text_offset)
        item_ids.append(
            self.canvas.create_text(
                text_x,
                text_y,
                text=self._dimension_label(value),
                fill=color,
                font=("Segoe UI", 9, "bold"),
            )
        )

    def _draw_vertical_dimension(
        self,
        item_ids: list[int],
        x: float,
        y1: float,
        y2: float,
        value: float,
        color: str,
        text_offset: float = 9,
    ) -> None:
        if abs(y2 - y1) >= 6:
            item_ids.append(
                self.canvas.create_line(
                    x,
                    y1,
                    x,
                    y2,
                    fill=color,
                    width=1,
                    arrow=tk.BOTH,
                )
            )
        for y in (y1, y2):
            item_ids.append(
                self.canvas.create_line(x - 4, y, x + 4, y, fill=color, width=1)
            )
        text_x, text_y = self._clamped_label_point(x + text_offset, (y1 + y2) / 2)
        item_ids.append(
            self.canvas.create_text(
                text_x,
                text_y,
                text=self._dimension_label(value),
                fill=color,
                angle=90,
                font=("Segoe UI", 9, "bold"),
            )
        )

    def _draw_buildplate(self) -> None:
        settings = self._settings_from_ui(update_crop=False)
        plate = self._buildplate_source_box(settings)
        if plate is None:
            return

        box = plate.normalized()
        left, top, right, bottom = self._box_canvas_rect(box)
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
        p_left, p_top, p_right, p_bottom = self._box_canvas_rect(printable)
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

        self._draw_horizontal_dimension(
            self._buildplate_item_ids,
            left,
            right,
            bottom + 16,
            self.printer.boundary_x,
            plate_color,
            text_offset=9,
        )
        self._draw_vertical_dimension(
            self._buildplate_item_ids,
            left - 16,
            top,
            bottom,
            self.printer.boundary_y,
            plate_color,
            text_offset=-9,
        )
        self._draw_horizontal_dimension(
            self._buildplate_item_ids,
            p_left,
            p_right,
            p_top - 16,
            self.printer.relative_safety_width(settings),
            "#0891b2",
        )
        self._draw_vertical_dimension(
            self._buildplate_item_ids,
            p_right + 16,
            p_top,
            p_bottom,
            self.printer.relative_safety_height(settings),
            "#0891b2",
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

        settings = self._settings_from_ui(update_crop=False)
        box = self.crop.normalized()
        left, top, right, bottom = self._box_canvas_rect(box)

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

        self._draw_bounding_box_preview(settings)

        scale = max(settings.scale, 0.0001)
        plot_bounds = plot_bounds_including_preflight(self.crop, settings).normalized()
        dimension_box = self._plot_box_to_source_box(plot_bounds, settings).normalized()
        d_left, d_top, d_right, d_bottom = self._box_canvas_rect(dimension_box)
        width_label = self._dimension_label(plot_bounds.width)
        height_label = self._dimension_label(plot_bounds.height)
        label_y = max(d_top - 13, 12)
        label_x = min(d_right + 14, self.canvas.winfo_width() - 12)
        self._crop_item_ids.append(
            self.canvas.create_text(
                (d_left + d_right) / 2,
                label_y,
                text=width_label,
                fill="#9a3412",
                font=("Segoe UI", 10, "bold"),
            )
        )
        self._crop_item_ids.append(
            self.canvas.create_text(
                label_x,
                (d_top + d_bottom) / 2,
                text=height_label,
                fill="#9a3412",
                angle=90,
                font=("Segoe UI", 10, "bold"),
            )
        )

        self._draw_crop_printable_offsets(dimension_box, scale)

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

    def _draw_bounding_box_preview(self, settings: PlotterSettings) -> None:
        if not self.crop:
            return

        for plot_stroke in bounding_box_dotted_strokes(self.crop, settings):
            coords: list[float] = []
            for point in plot_stroke:
                coords.extend(
                    self._source_to_canvas(
                        self._plot_point_to_source_point(point, settings)
                    )
                )
            if len(coords) < 4:
                continue
            self._crop_item_ids.append(
                self.canvas.create_line(
                    *coords,
                    fill="#f87171",
                    width=1,
                    capstyle=tk.ROUND,
                    joinstyle=tk.ROUND,
                )
            )

        for plot_stroke in bounding_box_corner_l_strokes(self.crop, settings):
            coords: list[float] = []
            for point in plot_stroke:
                coords.extend(
                    self._source_to_canvas(
                        self._plot_point_to_source_point(point, settings)
                    )
                )
            if len(coords) < 4:
                continue
            self._crop_item_ids.append(
                self.canvas.create_line(
                    *coords,
                    fill="#ef4444",
                    width=1,
                    capstyle=tk.PROJECTING,
                    joinstyle=tk.MITER,
                )
            )

    def _draw_crop_printable_offsets(self, crop: CropBox, scale: float) -> None:
        settings = self._settings_from_ui(update_crop=False)
        printable = self._printable_source_box(settings).normalized()
        crop = crop.normalized()
        p_left, p_top, p_right, p_bottom = self._box_canvas_rect(printable)
        c_left, c_top, c_right, c_bottom = self._box_canvas_rect(crop)
        color = "#0e7490"

        crop_height = max(c_bottom - c_top, 1.0)
        crop_width = max(c_right - c_left, 1.0)
        self._draw_horizontal_dimension(
            self._crop_item_ids,
            p_left,
            c_left,
            c_top + crop_height * 0.35,
            (crop.xmin - printable.xmin) * scale,
            color,
        )
        self._draw_horizontal_dimension(
            self._crop_item_ids,
            c_right,
            p_right,
            c_top + crop_height * 0.65,
            (printable.xmax - crop.xmax) * scale,
            color,
        )
        self._draw_vertical_dimension(
            self._crop_item_ids,
            c_left + crop_width * 0.35,
            p_top,
            c_top,
            (printable.ymax - crop.ymax) * scale,
            color,
        )
        self._draw_vertical_dimension(
            self._crop_item_ids,
            c_left + crop_width * 0.65,
            c_bottom,
            p_bottom,
            (crop.ymin - printable.ymin) * scale,
            color,
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

    def _plot_box_to_source_box(
        self,
        box: CropBox,
        settings: PlotterSettings,
    ) -> CropBox:
        scale = max(settings.scale, 0.0001)
        box = box.normalized()
        return CropBox(
            xmin=settings.origin_x + (box.xmin - settings.home_x) / scale,
            ymin=settings.origin_y + (box.ymin - settings.home_y) / scale,
            xmax=settings.origin_x + (box.xmax - settings.home_x) / scale,
            ymax=settings.origin_y + (box.ymax - settings.home_y) / scale,
        ).normalized()

    def _plot_point_to_source_point(
        self,
        point: tuple[float, float],
        settings: PlotterSettings,
    ) -> tuple[float, float]:
        scale = max(settings.scale, 0.0001)
        return (
            settings.origin_x + (point[0] - settings.home_x) / scale,
            settings.origin_y + (point[1] - settings.home_y) / scale,
        )

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
        if not self.crop:
            return
        settings = self._settings_from_ui(update_crop=False)
        plot_bounds = plot_bounds_including_preflight(self.crop, settings)
        self.plot_size_var.set(
            f"Plot: {plot_bounds.width:.2f} x {plot_bounds.height:.2f} mm"
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
            active_file=_settings_file_text(self.current_file) if self.current_file else None,
            recent_files=_recent_file_texts_with(
                _settings_file_text(self.current_file) if self.current_file else None,
                self.settings.recent_files,
            ),
            device_id=self.printer.key,
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
            bounding_box_speed=self._float_from_var(
                self.bounding_box_speed_var,
                self.settings.bounding_box_speed,
                minimum=0.001,
            ),
            draw_speed=self._float_from_var(
                self.draw_speed_var,
                self.settings.draw_speed,
                minimum=0.001,
            ),
            travel_speed=self._float_from_var(
                self.travel_speed_var,
                self.settings.travel_speed,
                minimum=0.001,
            ),
            curve_tolerance=self.settings.curve_tolerance,
            target_directory=self._selected_target_directory_value(),
            clear_before_write=bool(self.clear_before_write_var.get()),
            eject_after_write=bool(self.eject_after_write_var.get()),
            output_filename=self._selected_output_filename(),
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

    def _save_current_settings(self) -> None:
        try:
            settings = self._settings_from_ui()
            save_settings(settings, DEFAULT_SETTINGS_PATH)
        except Exception as exc:
            messagebox.showerror("Save settings failed", str(exc))
            self.status_var.set("Save settings failed.")
            return

        self.settings = settings
        self.status_var.set(f"Saved settings to {DEFAULT_SETTINGS_PATH}.")

    def _generate(self) -> None:
        if not self.current_file or not self.drawing or not self.crop:
            messagebox.showwarning("Nothing to generate", "Load a DXF file first.")
            return

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
        target_choice = self._selected_target_directory_choice()
        settings.clear_before_write = (
            bool(self.clear_before_write_var.get())
            and target_choice is not None
            and target_choice.is_removable
        )
        settings.eject_after_write = (
            bool(self.eject_after_write_var.get())
            and target_choice is not None
            and target_choice.is_removable
        )
        settings.output_filename = self._selected_output_filename()
        output_path = default_gcode_path(
            self.current_file,
            settings.target_directory,
            settings.output_filename,
        )
        cleared_count = 0
        if settings.clear_before_write and target_choice is not None:
            try:
                cleared_count = len(clear_gcode_files_from_target(target_choice))
            except Exception as exc:
                messagebox.showerror(
                    "Clear failed",
                    f"G-code was not written because existing .gcode files "
                    f"could not be cleared from:\n{target_choice.path}\n\n{exc}",
                )
                self.status_var.set("Clear before writing failed.")
                return

        try:
            summary = generate_gcode(
                source_path=self.current_file,
                strokes=transformed,
                crop=self.crop,
                settings=settings,
                output_path=output_path,
            )
            self.settings = settings
        except Exception as exc:
            messagebox.showerror("Generation failed", str(exc))
            self.status_var.set("Generation failed.")
            return

        warning_text = boundary_check.message if boundary_check.warning else ""
        eject_text = ""
        if settings.eject_after_write and target_choice is not None:
            try:
                eject_target_directory(target_choice)
                eject_text = f" Ejected {target_choice.label}."
                self._refresh_target_directories(prefer_current=False)
            except Exception as exc:
                eject_text = " Eject failed."
                messagebox.showwarning(
                    "Eject failed",
                    f"Wrote the G-code, but Windows could not eject:\n"
                    f"{target_choice.path}\n\n{exc}",
                )
        self.status_var.set(
            f"Wrote {summary.output_path} "
            f"({summary.stroke_count} strokes, {summary.segment_count} segments)."
            + (
                f" Cleared {cleared_count} old G-code file"
                f"{'' if cleared_count == 1 else 's'}."
                if settings.clear_before_write
                else ""
            )
            + (f" Warning: {warning_text}" if warning_text else "")
            + eject_text
        )
        messagebox.showinfo(
            "G-code generated",
            f"Wrote {summary.output_path}\n\n"
            f"Plot size: {summary.plot_bounds.width:.2f} x {summary.plot_bounds.height:.2f} mm\n"
            f"Draw length: {summary.draw_length_mm:.1f} mm"
            + (
                f"\n\nCleared {cleared_count} old G-code file"
                f"{'' if cleared_count == 1 else 's'}."
                if settings.clear_before_write
                else ""
            )
            + (f"\n\nWarning: {warning_text}" if warning_text else "")
            + ("\n\nEjected target drive." if eject_text.startswith(" Ejected") else ""),
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
        return str(path.resolve())


def _settings_file_text(path: Path | None) -> str | None:
    return _project_relative(path)


def _file_display_text(path: Path) -> str:
    return _settings_file_text(path) or str(path)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = _normalized_path_text(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _recent_file_texts_with(
    first_file: str | None,
    recent_files: list[str],
) -> list[str]:
    values = [first_file, *recent_files] if first_file else list(recent_files)
    recent: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        path = _resolve_project_path(value)
        if path is None or path.suffix.lower() != ".dxf":
            continue
        text = _settings_file_text(path)
        if not text:
            continue
        key = _normalized_path_text(path)
        if key in seen:
            continue
        seen.add(key)
        recent.append(text)
        if len(recent) >= MAX_RECENT_FILES:
            break
    return recent


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
