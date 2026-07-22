from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "settings.yaml"
DOWNLOADS_DIR = Path.home() / "Downloads"
TARGET_DOWNLOADS = "Downloads"


def target_directory_path(target_directory: str | None = None) -> Path:
    if not target_directory or target_directory.strip().casefold() == TARGET_DOWNLOADS.casefold():
        return DOWNLOADS_DIR

    path = Path(target_directory.strip()).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def default_gcode_path(source_path: Path, target_directory: str | None = None) -> Path:
    return target_directory_path(target_directory) / f"[pen_plotter] {source_path.stem}.gcode"


@dataclass
class CropBox:
    xmin: float = 0.0
    ymin: float = 0.0
    xmax: float = 100.0
    ymax: float = 100.0

    def normalized(self) -> "CropBox":
        return CropBox(
            xmin=min(self.xmin, self.xmax),
            ymin=min(self.ymin, self.ymax),
            xmax=max(self.xmin, self.xmax),
            ymax=max(self.ymin, self.ymax),
        )

    @property
    def width(self) -> float:
        box = self.normalized()
        return max(0.0, box.xmax - box.xmin)

    @property
    def height(self) -> float:
        box = self.normalized()
        return max(0.0, box.ymax - box.ymin)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "CropBox | None":
        if not data:
            return None
        try:
            return cls(
                xmin=float(data["xmin"]),
                ymin=float(data["ymin"]),
                xmax=float(data["xmax"]),
                ymax=float(data["ymax"]),
            ).normalized()
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class PlotterSettings:
    active_file: str | None = None
    home_x: float = 0.0
    home_y: float = 0.0
    home_z: float = 0.0
    origin_x: float = 0.0
    origin_y: float = 0.0
    z_hop: float = 5.0
    z_safe_height: float = 10.0
    scale: float = 0.48
    rotation_quarters: int = 0
    bounding_box_repeat: int = 3
    bounding_box_offset: float = 1.0
    bounding_box_feed: float = 2500.0
    draw_feed: float = 1200.0
    travel_feed: float = 5000.0
    curve_tolerance: float = 0.35
    target_directory: str = TARGET_DOWNLOADS
    crop: CropBox | None = field(default=None)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "PlotterSettings":
        settings = cls()
        if not data:
            return settings

        for name in (
            "active_file",
            "home_x",
            "home_y",
            "home_z",
            "origin_x",
            "origin_y",
            "z_hop",
            "z_safe_height",
            "scale",
            "rotation_quarters",
            "bounding_box_repeat",
            "bounding_box_offset",
            "bounding_box_feed",
            "draw_feed",
            "travel_feed",
            "curve_tolerance",
            "target_directory",
        ):
            if name not in data:
                continue
            value = data[name]
            if name == "active_file":
                settings.active_file = str(value) if value else None
            elif name == "target_directory":
                settings.target_directory = str(value) if value else TARGET_DOWNLOADS
            elif name in {"rotation_quarters", "bounding_box_repeat"}:
                try:
                    setattr(settings, name, int(float(value)))
                except (TypeError, ValueError):
                    pass
            else:
                try:
                    setattr(settings, name, float(value))
                except (TypeError, ValueError):
                    pass

        settings.crop = CropBox.from_mapping(data.get("crop"))

        # Migrate the older offset model:
        # output = x_offset + (source - crop.xmin) * scale
        # New model:
        # output = home_x + (source - origin_x) * scale
        if "home_z" not in data and "z_offset" in data:
            try:
                settings.home_z = float(data["z_offset"])
            except (TypeError, ValueError):
                pass
        if (
            settings.crop
            and ("origin_x" not in data or "origin_y" not in data)
            and ("x_offset" in data or "y_offset" in data)
        ):
            scale = max(settings.scale, 0.0001)
            try:
                x_offset = float(data.get("x_offset", 0.0))
            except (TypeError, ValueError):
                x_offset = 0.0
            try:
                y_offset = float(data.get("y_offset", 0.0))
            except (TypeError, ValueError):
                y_offset = 0.0
            settings.origin_x = settings.crop.xmin - (x_offset - settings.home_x) / scale
            settings.origin_y = settings.crop.ymin - (y_offset - settings.home_y) / scale

        settings.validate()
        return settings

    def validate(self) -> None:
        self.scale = max(self.scale, 0.0001)
        self.z_hop = max(self.z_hop, 0.0)
        self.z_safe_height = max(self.z_safe_height, 0.0)
        self.rotation_quarters = int(self.rotation_quarters) % 4
        self.bounding_box_repeat = max(int(self.bounding_box_repeat), 0)
        self.bounding_box_offset = max(self.bounding_box_offset, 0.0)
        self.bounding_box_feed = max(self.bounding_box_feed, 1.0)
        self.draw_feed = max(self.draw_feed, 1.0)
        self.travel_feed = max(self.travel_feed, 1.0)
        self.curve_tolerance = max(self.curve_tolerance, 0.01)
        if self.crop:
            self.crop = self.crop.normalized()

    def to_mapping(self) -> dict[str, Any]:
        self.validate()
        data = asdict(self)
        if self.crop is None:
            data["crop"] = None
        return data


def load_settings(path: Path = DEFAULT_SETTINGS_PATH) -> PlotterSettings:
    if not path.exists():
        return PlotterSettings()
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        return PlotterSettings()
    return PlotterSettings.from_mapping(data)


def save_settings(
    settings: PlotterSettings, path: Path = DEFAULT_SETTINGS_PATH
) -> None:
    settings.validate()
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            settings.to_mapping(),
            handle,
            sort_keys=False,
            default_flow_style=False,
        )
