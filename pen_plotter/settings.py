from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
DEFAULT_RECENTS_PATH = CONFIG_DIR / "recents.yaml"
DOWNLOADS_DIR = Path.home() / "Downloads"
TARGET_DOWNLOADS = "Downloads"
MAX_RECENT_FILES = 10
OUTPUT_FILENAME_PREFIX = "[ops]"
LEGACY_OUTPUT_FILENAME_PREFIX = "[pen_plotter]"


def target_directory_path(target_directory: str | None = None) -> Path:
    if not target_directory or target_directory.strip().casefold() == TARGET_DOWNLOADS.casefold():
        return DOWNLOADS_DIR

    path = Path(target_directory.strip()).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def default_output_filename(source_path: Path) -> str:
    return f"{OUTPUT_FILENAME_PREFIX} {source_path.stem}.gcode"


def normalize_output_filename(source_path: Path, filename: str | None = None) -> str:
    cleaned = (filename or "").strip()
    if not cleaned:
        return default_output_filename(source_path)
    cleaned = Path(cleaned).name
    legacy_prefix = f"{LEGACY_OUTPUT_FILENAME_PREFIX} "
    if cleaned.startswith(legacy_prefix):
        cleaned = f"{OUTPUT_FILENAME_PREFIX} {cleaned[len(legacy_prefix):]}"
    if Path(cleaned).suffix.lower() != ".gcode":
        cleaned += ".gcode"
    return cleaned


def default_gcode_path(
    source_path: Path,
    target_directory: str | None = None,
    output_filename: str | None = None,
) -> Path:
    return target_directory_path(target_directory) / normalize_output_filename(
        source_path,
        output_filename,
    )


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
    recent_files: list[str] = field(default_factory=list)
    device_id: str = "CE3PRO"
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
    bounding_box_speed: float = 41.666667
    draw_speed: float = 20.0
    travel_speed: float = 83.333333
    curve_tolerance: float = 0.35
    target_directory: str = TARGET_DOWNLOADS
    clear_before_write: bool = False
    eject_after_write: bool = False
    output_filename: str | None = None
    crop: CropBox | None = field(default=None)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "PlotterSettings":
        settings = cls()
        if not data:
            return settings

        for name in (
            "device_id",
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
            "bounding_box_speed",
            "draw_speed",
            "travel_speed",
            "curve_tolerance",
            "target_directory",
            "clear_before_write",
            "eject_after_write",
        ):
            if name not in data:
                continue
            value = data[name]
            if name == "device_id":
                settings.device_id = str(value) if value else "CE3PRO"
            elif name == "target_directory":
                settings.target_directory = str(value) if value else TARGET_DOWNLOADS
            elif name == "clear_before_write":
                settings.clear_before_write = _bool_from_value(value)
            elif name == "eject_after_write":
                settings.eject_after_write = _bool_from_value(value)
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
        self.bounding_box_speed = max(self.bounding_box_speed, 0.001)
        self.draw_speed = max(self.draw_speed, 0.001)
        self.travel_speed = max(self.travel_speed, 0.001)
        self.curve_tolerance = max(self.curve_tolerance, 0.01)
        if self.output_filename is not None:
            self.output_filename = self.output_filename.strip() or None
        self.clear_before_write = bool(self.clear_before_write)
        self.eject_after_write = bool(self.eject_after_write)
        self.recent_files = _clean_recent_files(self.recent_files)
        if self.crop:
            self.crop = self.crop.normalized()

    def to_mapping(self) -> dict[str, Any]:
        self.validate()
        data = asdict(self)
        data.pop("active_file", None)
        data.pop("recent_files", None)
        data.pop("output_filename", None)
        for key in (
            "home_x",
            "home_y",
            "home_z",
            "z_hop",
            "z_safe_height",
            "draw_speed",
            "travel_speed",
        ):
            data.pop(key, None)
        if self.crop is None:
            data["crop"] = None
        return data


def _clean_recent_files(recent_files: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in recent_files:
        text = str(value).strip()
        if not text:
            continue
        key = _settings_path_key(text)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= MAX_RECENT_FILES:
            break
    return cleaned


def _settings_path_key(value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path.absolute()).casefold()


def _bool_from_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().casefold()
    return text in {"1", "true", "yes", "on"}


def load_file_history(
    path: Path = DEFAULT_RECENTS_PATH,
) -> tuple[str | None, list[str], str | None]:
    if not path.exists():
        return None, [], None
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        return None, [], None
    active_file = str(data["active_file"]) if data.get("active_file") else None
    output_filename = (
        str(data["output_filename"]).strip() if data.get("output_filename") else None
    )
    recent_files = data.get("recent_files", [])
    if not isinstance(recent_files, list):
        recent_files = []
    cleaned = _clean_recent_files(
        ([active_file] if active_file else []) + [str(item) for item in recent_files]
    )
    active_file = active_file if active_file in cleaned else (cleaned[0] if cleaned else None)
    return active_file, cleaned, output_filename or None


def load_recent_files(path: Path = DEFAULT_RECENTS_PATH) -> list[str]:
    return load_file_history(path)[1]


def save_recent_files(
    recent_files: list[str],
    path: Path = DEFAULT_RECENTS_PATH,
    output_filename: str | None = None,
) -> None:
    cleaned = _clean_recent_files(recent_files)
    output_filename = output_filename.strip() if output_filename else None
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            {
                "active_file": cleaned[0] if cleaned else None,
                "output_filename": output_filename or None,
                "recent_files": cleaned,
            },
            handle,
            sort_keys=False,
            default_flow_style=False,
        )


def load_settings(path: Path = DEFAULT_SETTINGS_PATH) -> PlotterSettings:
    active_file, recent_files, output_filename = load_file_history()
    if not path.exists():
        settings = PlotterSettings()
        settings.active_file = active_file
        settings.recent_files = recent_files
        settings.output_filename = output_filename
        return settings
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        settings = PlotterSettings()
    else:
        settings = PlotterSettings.from_mapping(data)
    settings.active_file = active_file
    settings.recent_files = recent_files
    settings.output_filename = output_filename
    return settings


def save_settings(
    settings: PlotterSettings, path: Path = DEFAULT_SETTINGS_PATH
) -> None:
    settings.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            settings.to_mapping(),
            handle,
            sort_keys=False,
            default_flow_style=False,
        )
