from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from .settings import CONFIG_DIR, CropBox, PlotterSettings


DEFAULT_DEVICES_DIR = CONFIG_DIR / "devices"
DEFAULT_PRINTER_PATH = DEFAULT_DEVICES_DIR
SAFETY_WARNING_EPSILON_MM = 1e-2


@dataclass(frozen=True)
class PrinterProfile:
    key: str = "CE3PRO"
    name: str = "Creality Ender 3 Pro"
    config_path: Path | None = None
    home_x: float = 0.0
    home_y: float = 0.0
    home_z: float = 0.0
    z_hop: float = 5.0
    z_safe_height: float = 10.0
    draw_speed: float = 20.0
    travel_speed: float = 83.333333
    boundary_x: float = 235.0
    boundary_y: float = 235.0
    boundary_z: float = 250.0
    safety_margin: float = 5.0

    def with_home(self, x: float, y: float, z: float) -> "PrinterProfile":
        return replace(self, home_x=x, home_y=y, home_z=z)

    def with_motion(
        self,
        z_hop: float,
        z_safe_height: float,
        draw_speed: float,
        travel_speed: float,
    ) -> "PrinterProfile":
        return replace(
            self,
            z_hop=z_hop,
            z_safe_height=z_safe_height,
            draw_speed=draw_speed,
            travel_speed=travel_speed,
        )

    def absolute_x_max(self, settings: PlotterSettings) -> float:
        return self.boundary_x

    def absolute_y_max(self, settings: PlotterSettings) -> float:
        return self.boundary_y

    def relative_safety_x_min(self, settings: PlotterSettings) -> float:
        return max(self.safety_margin, self.safety_margin - settings.home_x)

    def relative_safety_y_min(self, settings: PlotterSettings) -> float:
        return max(self.safety_margin, self.safety_margin - settings.home_y)

    def relative_safety_x_max(self, settings: PlotterSettings) -> float:
        return min(
            self.boundary_x - self.safety_margin,
            self.boundary_x - self.safety_margin - settings.home_x,
        )

    def relative_safety_y_max(self, settings: PlotterSettings) -> float:
        return min(
            self.boundary_y - self.safety_margin,
            self.boundary_y - self.safety_margin - settings.home_y,
        )

    def safety_x_min(self, settings: PlotterSettings) -> float:
        return settings.home_x + self.relative_safety_x_min(settings)

    def safety_y_min(self, settings: PlotterSettings) -> float:
        return settings.home_y + self.relative_safety_y_min(settings)

    def safety_x_max(self, settings: PlotterSettings) -> float:
        return settings.home_x + self.relative_safety_x_max(settings)

    def safety_y_max(self, settings: PlotterSettings) -> float:
        return settings.home_y + self.relative_safety_y_max(settings)

    def relative_safety_width(self, settings: PlotterSettings) -> float:
        return max(0.0, self.relative_safety_x_max(settings) - self.relative_safety_x_min(settings))

    def relative_safety_height(self, settings: PlotterSettings) -> float:
        return max(0.0, self.relative_safety_y_max(settings) - self.relative_safety_y_min(settings))


@dataclass(frozen=True)
class BoundaryCheck:
    blocking_issues: tuple[str, ...] = ()
    warning_issues: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        return bool(self.blocking_issues)

    @property
    def warning(self) -> bool:
        return bool(self.warning_issues)

    @property
    def message(self) -> str:
        if self.blocked:
            return "Out of absolute printer bounds: " + ", ".join(self.blocking_issues)
        if self.warning:
            return "Inside safety margin: " + ", ".join(self.warning_issues)
        return ""


def load_printer_profile(
    device_id: str | None = None,
    path: Path = DEFAULT_PRINTER_PATH,
) -> PrinterProfile:
    profiles = load_printer_profiles(path)
    if device_id and device_id in profiles:
        return profiles[device_id]
    return next(iter(profiles.values()))


def load_printer_profiles(path: Path = DEFAULT_PRINTER_PATH) -> dict[str, PrinterProfile]:
    if not path.exists():
        default = PrinterProfile(config_path=path / "CE3PRO.yaml")
        return {default.key: default}

    profiles: dict[str, PrinterProfile] = {}
    for device_path in sorted(
        item
        for item in path.iterdir()
        if item.is_file() and item.suffix.lower() in {".yaml", ".yml"}
    ):
        profile = load_printer_profile_from_file(device_path)
        profiles[profile.key] = profile

    if profiles:
        return profiles

    default = PrinterProfile(config_path=path / "CE3PRO.yaml")
    return {default.key: default}


def load_printer_profile_from_file(path: Path) -> PrinterProfile:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        data = {}
    return _profile_from_mapping(path.stem, data, path)


def save_printer_profile(profile: PrinterProfile) -> None:
    profile_path = profile.config_path or DEFAULT_DEVICES_DIR / f"{profile.key}.yaml"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    with profile_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            _profile_to_mapping(profile),
            handle,
            sort_keys=False,
            default_flow_style=False,
        )


def _profile_to_mapping(profile: PrinterProfile) -> dict[str, Any]:
    return {
        "name": profile.name,
        "home": {
            "x": profile.home_x,
            "y": profile.home_y,
            "z": profile.home_z,
        },
        "z_height": {
            "hop": profile.z_hop,
            "safe": profile.z_safe_height,
        },
        "speed": {
            "draw": profile.draw_speed,
            "travel": profile.travel_speed,
        },
        "boundary": {
            "x": profile.boundary_x,
            "y": profile.boundary_y,
            "z": profile.boundary_z,
        },
        "safety_margin": profile.safety_margin,
    }


def _profile_from_mapping(
    key: str,
    data: dict[str, Any],
    config_path: Path | None = None,
) -> PrinterProfile:
    boundary = data.get("boundary") or {}
    if not isinstance(boundary, dict):
        boundary = {}
    home = data.get("home") or {}
    if not isinstance(home, dict):
        home = {}
    z_height = data.get("z_height") or {}
    if not isinstance(z_height, dict):
        z_height = {}
    speed = data.get("speed") or {}
    if not isinstance(speed, dict):
        speed = {}

    return PrinterProfile(
        key=key,
        name=str(data.get("name") or key),
        config_path=config_path,
        home_x=_float_from_mapping(home, "x", 0.0),
        home_y=_float_from_mapping(home, "y", 0.0),
        home_z=_float_from_mapping(home, "z", 0.0),
        z_hop=max(_float_from_mapping(z_height, "hop", 5.0), 0.0),
        z_safe_height=max(_float_from_mapping(z_height, "safe", 10.0), 0.0),
        draw_speed=max(_float_from_mapping(speed, "draw", 20.0), 0.001),
        travel_speed=max(_float_from_mapping(speed, "travel", 83.333333), 0.001),
        boundary_x=_float_from_mapping(boundary, "x", 235.0),
        boundary_y=_float_from_mapping(boundary, "y", 235.0),
        boundary_z=_float_from_mapping(boundary, "z", 250.0),
        safety_margin=max(_float_from_mapping(data, "safety_margin", 5.0), 0.0),
    )


def check_gcode_bounds(
    xy_bounds: CropBox,
    settings: PlotterSettings,
    printer: PrinterProfile,
) -> BoundaryCheck:
    bounds = xy_bounds.normalized()
    z_values = (
        settings.home_z,
        settings.home_z + settings.z_hop,
        settings.home_z + settings.z_safe_height,
    )
    z_min = min(z_values)
    z_max = max(z_values)

    blocking: list[str] = []
    warning: list[str] = []

    _append_below(blocking, "X min", bounds.xmin, 0.0)
    _append_below(blocking, "Y min", bounds.ymin, 0.0)
    _append_below(blocking, "Z min", z_min, 0.0)
    _append_above(blocking, "X max", bounds.xmax, printer.absolute_x_max(settings))
    _append_above(blocking, "Y max", bounds.ymax, printer.absolute_y_max(settings))
    _append_above(blocking, "Z max", z_max, printer.boundary_z)

    _append_below(
        warning,
        "X min",
        bounds.xmin,
        printer.safety_x_min(settings),
        SAFETY_WARNING_EPSILON_MM,
    )
    _append_below(
        warning,
        "Y min",
        bounds.ymin,
        printer.safety_y_min(settings),
        SAFETY_WARNING_EPSILON_MM,
    )
    _append_below(
        warning, "Z min", z_min, printer.safety_margin, SAFETY_WARNING_EPSILON_MM
    )
    _append_above(
        warning,
        "X max",
        bounds.xmax,
        printer.safety_x_max(settings),
        SAFETY_WARNING_EPSILON_MM,
    )
    _append_above(
        warning,
        "Y max",
        bounds.ymax,
        printer.safety_y_max(settings),
        SAFETY_WARNING_EPSILON_MM,
    )
    _append_above(
        warning,
        "Z max",
        z_max,
        max(printer.boundary_z - printer.safety_margin, printer.safety_margin),
        SAFETY_WARNING_EPSILON_MM,
    )

    return BoundaryCheck(tuple(blocking), tuple(warning))


def _float_from_mapping(data: dict[str, Any], key: str, fallback: float) -> float:
    try:
        return float(data.get(key, fallback))
    except (TypeError, ValueError):
        return fallback


def _append_below(
    issues: list[str],
    label: str,
    value: float,
    limit: float,
    tolerance: float = 0.0,
) -> None:
    if value < limit - tolerance:
        issues.append(f"{label} {_fmt(value)} < {_fmt(limit)}")


def _append_above(
    issues: list[str],
    label: str,
    value: float,
    limit: float,
    tolerance: float = 0.0,
) -> None:
    if value > limit + tolerance:
        issues.append(f"{label} {_fmt(value)} > {_fmt(limit)}")


def _fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")
