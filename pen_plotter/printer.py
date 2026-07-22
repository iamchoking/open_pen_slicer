from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .settings import CropBox, PROJECT_ROOT, PlotterSettings


DEFAULT_PRINTER_PATH = PROJECT_ROOT / "printer.yaml"
SAFETY_WARNING_EPSILON_MM = 1e-2


@dataclass(frozen=True)
class PrinterProfile:
    boundary_x: float = 235.0
    boundary_y: float = 235.0
    boundary_z: float = 250.0
    safety_margin: float = 5.0

    def absolute_x_max(self, settings: PlotterSettings) -> float:
        return self.boundary_x

    def absolute_y_max(self, settings: PlotterSettings) -> float:
        return self.boundary_y

    def safety_x_min(self, settings: PlotterSettings) -> float:
        return max(self.safety_margin, settings.home_x + self.safety_margin)

    def safety_y_min(self, settings: PlotterSettings) -> float:
        return max(self.safety_margin, settings.home_y + self.safety_margin)

    def safety_x_max(self, settings: PlotterSettings) -> float:
        return self.boundary_x - self.safety_margin

    def safety_y_max(self, settings: PlotterSettings) -> float:
        return self.boundary_y - self.safety_margin


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


def load_printer_profile(path: Path = DEFAULT_PRINTER_PATH) -> PrinterProfile:
    if not path.exists():
        return PrinterProfile()

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        return PrinterProfile()

    boundary = data.get("boundary") or {}
    if not isinstance(boundary, dict):
        boundary = {}

    return PrinterProfile(
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
