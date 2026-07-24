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
class RecentFileSettings:
    scale: float | None = None
    crop: CropBox | None = None
    origin_x: float | None = None
    origin_y: float | None = None

    def has_values(self) -> bool:
        return (
            self.scale is not None
            or self.crop is not None
            or self.origin_x is not None
            or self.origin_y is not None
        )


@dataclass
class PlotterSettings:
    active_file: str | None = None
    recent_files: list[str] = field(default_factory=list)
    recent_file_settings: dict[str, RecentFileSettings] = field(default_factory=dict)
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
            "z_hop",
            "z_safe_height",
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
        self.recent_file_settings = _clean_recent_file_settings(
            self.recent_files,
            self.recent_file_settings,
        )
        if self.crop:
            self.crop = self.crop.normalized()

    def to_mapping(self) -> dict[str, Any]:
        self.validate()
        data = asdict(self)
        data.pop("active_file", None)
        data.pop("recent_files", None)
        data.pop("recent_file_settings", None)
        data.pop("output_filename", None)
        for key in (
            "home_x",
            "home_y",
            "home_z",
            "origin_x",
            "origin_y",
            "z_hop",
            "z_safe_height",
            "scale",
            "draw_speed",
            "travel_speed",
            "crop",
        ):
            data.pop(key, None)
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


def _clean_recent_file_settings(
    recent_files: list[str],
    file_settings: dict[str, RecentFileSettings] | None,
) -> dict[str, RecentFileSettings]:
    if not file_settings:
        return {}

    settings_by_key: dict[str, RecentFileSettings] = {}
    for file_text, state in file_settings.items():
        if not file_text:
            continue
        if state is None or not state.has_values():
            continue
        settings_by_key[_settings_path_key(str(file_text))] = state

    cleaned: dict[str, RecentFileSettings] = {}
    for file_text in _clean_recent_files(recent_files):
        state = settings_by_key.get(_settings_path_key(file_text))
        if state is not None and state.has_values():
            cleaned[file_text] = state
    return cleaned


def _settings_path_key(value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path.absolute()).casefold()


def _optional_float(value: Any, minimum: float | None = None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if minimum is not None:
        parsed = max(parsed, minimum)
    return parsed


def _bool_from_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().casefold()
    return text in {"1", "true", "yes", "on"}


def recent_file_settings_for(
    file_text: str | None,
    file_settings: dict[str, RecentFileSettings] | None,
) -> RecentFileSettings | None:
    if not file_text or not file_settings:
        return None
    wanted_key = _settings_path_key(file_text)
    for candidate_text, state in file_settings.items():
        if _settings_path_key(candidate_text) == wanted_key:
            return state
    return None


def recent_file_settings_with(
    file_text: str | None,
    recent_files: list[str],
    file_settings: dict[str, RecentFileSettings] | None,
    state: RecentFileSettings | None,
) -> dict[str, RecentFileSettings]:
    updated = dict(file_settings or {})
    if file_text and state is not None and state.has_values():
        wanted_key = _settings_path_key(file_text)
        updated = {
            candidate_text: candidate_state
            for candidate_text, candidate_state in updated.items()
            if _settings_path_key(candidate_text) != wanted_key
        }
        updated[file_text] = state
    return _clean_recent_file_settings(recent_files, updated)


def apply_recent_file_settings(
    settings: PlotterSettings,
    state: RecentFileSettings | None,
) -> None:
    if state is None:
        return
    if state.scale is not None:
        settings.scale = state.scale
    if state.origin_x is not None and state.origin_y is not None:
        settings.origin_x = state.origin_x
        settings.origin_y = state.origin_y
    if state.crop is not None:
        settings.crop = state.crop.normalized()
    settings.validate()


def _crop_from_recent_value(value: Any) -> CropBox | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        xmin, xmax, ymin, ymax = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    return CropBox(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax).normalized()


def _crop_to_recent_value(crop: CropBox | None) -> list[float] | None:
    if crop is None:
        return None
    box = crop.normalized()
    return [box.xmin, box.xmax, box.ymin, box.ymax]


def _origin_from_recent_value(value: Any) -> tuple[float, float] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        return float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None


def _origin_to_recent_value(
    origin_x: float | None,
    origin_y: float | None,
) -> list[float] | None:
    if origin_x is None or origin_y is None:
        return None
    return [float(origin_x), float(origin_y)]


def _recent_file_settings_from_lists(
    file_values: list[Any],
    crop_values: list[Any],
    scale_values: list[Any],
    origin_values: list[Any],
) -> tuple[str | None, list[str], dict[str, RecentFileSettings]]:
    recent_files: list[str] = []
    file_settings: dict[str, RecentFileSettings] = {}
    seen: set[str] = set()

    for index, value in enumerate(file_values):
        text = str(value).strip()
        if not text:
            continue
        key = _settings_path_key(text)
        if key in seen:
            continue
        seen.add(key)
        recent_files.append(text)

        state = RecentFileSettings()
        if index < len(crop_values):
            state.crop = _crop_from_recent_value(crop_values[index])
        if index < len(scale_values):
            state.scale = _optional_float(scale_values[index], minimum=0.0001)
        if index < len(origin_values):
            origin = _origin_from_recent_value(origin_values[index])
            if origin is not None:
                state.origin_x, state.origin_y = origin
        if state.has_values():
            file_settings[text] = state

        if len(recent_files) >= MAX_RECENT_FILES:
            break

    return (recent_files[0] if recent_files else None), recent_files, file_settings


def load_file_history(
    path: Path = DEFAULT_RECENTS_PATH,
) -> tuple[str | None, list[str], str | None, dict[str, RecentFileSettings]]:
    if not path.exists():
        return None, [], None, {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        return None, [], None, {}
    file_values = data.get("file", [])
    crop_values = data.get("crop", [])
    scale_values = data.get("scale", [])
    origin_values = data.get("origin", [])
    if not isinstance(file_values, list):
        file_values = []
    if not isinstance(crop_values, list):
        crop_values = []
    if not isinstance(scale_values, list):
        scale_values = []
    if not isinstance(origin_values, list):
        origin_values = []

    active_file, recent_files, file_settings = _recent_file_settings_from_lists(
        file_values,
        crop_values,
        scale_values,
        origin_values,
    )
    return active_file, recent_files, None, file_settings


def load_recent_files(path: Path = DEFAULT_RECENTS_PATH) -> list[str]:
    return load_file_history(path)[1]


def save_recent_files(
    recent_files: list[str],
    path: Path = DEFAULT_RECENTS_PATH,
    file_settings: dict[str, RecentFileSettings] | None = None,
) -> None:
    cleaned = _clean_recent_files(recent_files)
    cleaned_file_settings = _clean_recent_file_settings(cleaned, file_settings)
    crop_values: list[list[float] | None] = []
    scale_values: list[float | None] = []
    origin_values: list[list[float] | None] = []
    for file_text in cleaned:
        state = recent_file_settings_for(file_text, cleaned_file_settings)
        crop_values.append(_crop_to_recent_value(state.crop) if state else None)
        scale_values.append(
            max(float(state.scale), 0.0001)
            if state and state.scale is not None
            else None
        )
        origin_values.append(
            _origin_to_recent_value(state.origin_x, state.origin_y) if state else None
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            {
                "file": cleaned,
                "crop": crop_values,
                "scale": scale_values,
                "origin": origin_values,
            },
            handle,
            sort_keys=False,
            default_flow_style=False,
        )


def load_settings(path: Path = DEFAULT_SETTINGS_PATH) -> PlotterSettings:
    active_file, recent_files, output_filename, recent_file_settings = load_file_history()
    if not path.exists():
        settings = PlotterSettings()
        settings.active_file = active_file
        settings.recent_files = recent_files
        settings.output_filename = output_filename
        settings.recent_file_settings = recent_file_settings
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
    settings.recent_file_settings = recent_file_settings
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
