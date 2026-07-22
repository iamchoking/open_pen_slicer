from __future__ import annotations

import os
from functools import lru_cache
from math import cos, isfinite, radians, sin
from pathlib import Path

from ezdxf import path as ez_path
from ezdxf.fonts import fonts, shapefile

from .settings import PROJECT_ROOT

Point = tuple[float, float]
Stroke = list[Point]

KOREAN_SHX_FONTS = ("whgtxt.shx", "whgdtxt.shx")
REGULAR_SHX_FONTS = ("txt.shx", "simplex.shx")


def render_text(
    text: str,
    insert: Point,
    height: float,
    rotation: float = 0.0,
    width_factor: float = 0.75,
    line_spacing: float = 1.25,
    anchor: str = "nw",
) -> list[Stroke]:
    engine = _text_engine()
    height = max(height, 0.001)
    width_factor = max(width_factor, 0.1)
    lines = text.splitlines() or [""]
    line_widths = [engine.text_width(line, height, width_factor) for line in lines]
    block_width = max(line_widths, default=0.0)
    block_height = height + max(0, len(lines) - 1) * height * max(line_spacing, 0.1)
    anchor_x, anchor_y = _anchor_offset(anchor, block_width, block_height)

    angle = radians(rotation)
    ca = cos(angle)
    sa = sin(angle)
    x0, y0 = insert
    strokes: list[Stroke] = []

    for line_index, line in enumerate(lines):
        if not line:
            continue
        line_x = anchor_x + _line_x_offset(anchor, block_width, line_widths[line_index])
        line_y = anchor_y + block_height - height - line_index * height * line_spacing
        cursor = 0.0
        for char in line:
            glyph_strokes, advance = engine.render_char(char, height, width_factor)
            for glyph_stroke in glyph_strokes:
                transformed: Stroke = []
                for gx, gy in glyph_stroke:
                    if not isfinite(gx) or not isfinite(gy):
                        continue
                    lx = line_x + cursor + gx
                    ly = line_y + gy
                    transformed.append(
                        (x0 + lx * ca - ly * sa, y0 + lx * sa + ly * ca)
                    )
                if len(transformed) > 1:
                    strokes.append(transformed)
            cursor += advance
    return strokes


class ShxTextEngine:
    def __init__(self, korean_font: "BigFontEngine | ShapeFontEngine") -> None:
        self.korean_font = korean_font
        self.regular_font = ShapeFontEngine(_preferred_regular_shx_path())

    def text_width(self, text: str, height: float, width_factor: float) -> float:
        return sum(self.advance(char, height, width_factor) for char in text)

    def advance(self, char: str, height: float, width_factor: float) -> float:
        if char.isspace():
            return self.regular_font.space_width(height, width_factor)
        if self.korean_font.has_char(char):
            return self.korean_font.advance(char, height, width_factor)
        return self.regular_font.advance(char, height, width_factor)

    def render_char(
        self, char: str, height: float, width_factor: float
    ) -> tuple[list[Stroke], float]:
        if char.isspace():
            return [], self.regular_font.space_width(height, width_factor)
        if self.korean_font.has_char(char):
            return self.korean_font.render_char(char, height, width_factor)
        return self.regular_font.render_char(char, height, width_factor)


class ShapeFontEngine:
    def __init__(self, font_path: Path) -> None:
        self.font_path = font_path
        fonts.font_manager.scan_folder(font_path.parent)
        try:
            cache_entry = fonts.font_manager._font_cache[font_path.name]
        except KeyError as exc:
            raise FileNotFoundError(f"SHX font was found but not registered: {font_path}") from exc
        if cache_entry.file_path.resolve() != font_path.resolve():
            raise RuntimeError(
                f"SHX font name collision: expected {font_path}, "
                f"registered {cache_entry.file_path}."
            )
        self.font = fonts.ShapeFileFont(font_path.name, cap_height=1.0, width_factor=1.0)

    def has_char(self, char: str) -> bool:
        if len(char) != 1:
            return False
        try:
            self.font.glyph_cache.font.get_codes(ord(char))
        except Exception:
            return False
        return True

    def text_width(self, text: str, height: float, width_factor: float) -> float:
        return self.font.text_width_ex(text, height, width_factor)

    def advance(self, char: str, height: float, width_factor: float) -> float:
        return self.text_width(char, height, width_factor)

    def space_width(self, height: float, width_factor: float) -> float:
        return max(self.font.space_width() * height * width_factor, height * 0.25)

    def render_char(
        self, char: str, height: float, width_factor: float
    ) -> tuple[list[Stroke], float]:
        path = self.font.text_path_ex(char, height, width_factor)
        return _path_to_strokes(path), self.advance(char, height, width_factor)


class BigFontEngine:
    def __init__(self, font_path: Path) -> None:
        self.font_path = font_path
        self.data = font_path.read_bytes()
        if not self.data.startswith(b"AutoCAD-86 bigfont 1.0"):
            raise RuntimeError(f"Expected an AutoCAD BigFont SHX file: {font_path}")

        signature_index = self.data.index(b"\x1a")
        entry_count = int.from_bytes(
            self.data[signature_index + 3 : signature_index + 5], "little"
        )
        table_start = signature_index + 11
        self.codes: dict[int, tuple[int, ...]] = {}
        self.above = 96.0
        self.below = 0.0

        for index in range(entry_count):
            offset = table_start + index * 8
            shape_number = int.from_bytes(self.data[offset : offset + 2], "big")
            byte_count = int.from_bytes(self.data[offset + 2 : offset + 4], "little")
            record_offset = int.from_bytes(self.data[offset + 4 : offset + 8], "little")
            if byte_count <= 0 or record_offset <= 0:
                continue
            record = self.data[record_offset : record_offset + byte_count]
            if not record:
                continue
            name_end = record.find(b"\x00")
            if name_end < 0:
                continue
            shape_data = record[name_end + 1 :]
            try:
                codes = tuple(
                    shapefile.parse_shape_codes(shapefile.DataReader(shape_data))
                )
            except (IndexError, shapefile.ShapeFileException):
                continue
            self.codes[shape_number] = codes

        header_codes = self.codes.pop(0, ())
        if len(header_codes) >= 2:
            self.above = float(header_codes[0] or self.above)
            self.below = float(header_codes[1])
        if not self.codes:
            raise RuntimeError(f"No drawable BigFont glyphs were parsed from {font_path}")

    def has_char(self, char: str) -> bool:
        shape_number = self._shape_number(char)
        return shape_number is not None and shape_number in self.codes

    def advance(self, char: str, height: float, width_factor: float) -> float:
        path = self._render_path(char)
        scale_y = height / max(self.above, 1.0)
        return max(float(path.end.x) * scale_y * width_factor, height * 0.5)

    def render_char(
        self, char: str, height: float, width_factor: float
    ) -> tuple[list[Stroke], float]:
        path = self._render_path(char)
        scale_y = height / max(self.above, 1.0)
        sx = scale_y * width_factor
        strokes = [
            [(x * sx, y * scale_y) for x, y in stroke]
            for stroke in _path_to_strokes(path)
        ]
        return strokes, self.advance(char, height, width_factor)

    def _shape_number(self, char: str) -> int | None:
        if len(char) != 1:
            return None
        try:
            encoded = char.encode("cp949")
        except UnicodeEncodeError:
            return None
        if len(encoded) != 2:
            return None
        return int.from_bytes(encoded, "little")

    def _render_path(self, char: str) -> ez_path.Path:
        shape_number = self._shape_number(char)
        if shape_number is None or shape_number not in self.codes:
            raise RuntimeError(
                f"Glyph {char!r} is not present in required BigFont {self.font_path}."
            )
        path = ez_path.Path()
        renderer = shapefile.ShapeRenderer(
            path,
            get_codes=self._get_codes,
            pen_down=True,
            stacked=False,
        )
        renderer.render(shape_number, reset_to_baseline=True)
        return path

    def _get_codes(self, shape_number: int) -> tuple[int, ...]:
        try:
            return self.codes[shape_number]
        except KeyError:
            raise shapefile.UnsupportedShapeNumber(shape_number)


@lru_cache(maxsize=1)
def _text_engine() -> ShxTextEngine:
    korean_font_path = _preferred_korean_shx_path()
    if korean_font_path.read_bytes().startswith(b"AutoCAD-86 bigfont 1.0"):
        korean_font: BigFontEngine | ShapeFontEngine = BigFontEngine(korean_font_path)
    else:
        korean_font = ShapeFontEngine(korean_font_path)
    return ShxTextEngine(korean_font)


@lru_cache(maxsize=1)
def _preferred_korean_shx_path() -> Path:
    searched_dirs: list[Path] = []
    for directory in _font_search_dirs():
        searched_dirs.append(directory)
        for path in _matching_font_paths(directory, KOREAN_SHX_FONTS):
            if path.is_file():
                return path

    searched = "\n  - ".join(str(path) for path in searched_dirs)
    raise FileNotFoundError(
        "Required Korean SHX font not found. Put whgtxt.shx or whgdtxt.shx in "
        f"{PROJECT_ROOT / 'fonts'} or set PEN_PLOTTER_FONT_DIR.\n"
        f"Searched:\n  - {searched}"
    )


@lru_cache(maxsize=1)
def _preferred_regular_shx_path() -> Path:
    searched_dirs: list[Path] = []
    for directory in _font_search_dirs():
        searched_dirs.append(directory)
        for path in _matching_font_paths(directory, REGULAR_SHX_FONTS):
            if path.is_file():
                return path

    searched = "\n  - ".join(str(path) for path in searched_dirs)
    raise FileNotFoundError(
        "Required regular SHX font not found for ASCII text. Put txt.shx or "
        f"simplex.shx in {PROJECT_ROOT / 'fonts'} or set PEN_PLOTTER_FONT_DIR.\n"
        f"Searched:\n  - {searched}"
    )


def _font_search_dirs() -> list[Path]:
    dirs: list[Path] = []
    env_value = os.environ.get("PEN_PLOTTER_FONT_DIR", "")
    for raw_path in env_value.split(os.pathsep):
        if raw_path.strip():
            dirs.append(Path(raw_path).expanduser())

    dirs.extend(
        [
            PROJECT_ROOT / "fonts",
            PROJECT_ROOT / "raw",
            PROJECT_ROOT,
        ]
    )

    for root in _common_cad_roots():
        if not root.exists():
            continue
        dirs.append(root)
        dirs.extend(root.glob("*/Fonts"))
        dirs.extend(root.glob("*/Support"))

    vscode_extensions = Path.home() / ".vscode" / "extensions"
    if vscode_extensions.exists():
        dirs.extend(vscode_extensions.glob("*/dist/libs/fonts"))

    unique_dirs: list[Path] = []
    seen: set[str] = set()
    for directory in dirs:
        key = str(directory.resolve()) if directory.exists() else str(directory)
        if key.lower() in seen:
            continue
        seen.add(key.lower())
        unique_dirs.append(directory)
    return unique_dirs


def _common_cad_roots() -> list[Path]:
    return [
        Path("C:/Program Files/Autodesk"),
        Path("C:/Program Files (x86)/Autodesk"),
        Path("C:/ProgramData/Autodesk"),
        Path.home() / "AppData/Local/Autodesk",
        Path.home() / "AppData/Roaming/Autodesk",
        Path("C:/Program Files/Bricsys"),
        Path("C:/Program Files (x86)/Bricsys"),
    ]


def _matching_font_paths(directory: Path, font_names: tuple[str, ...]) -> list[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    expected = {name.lower() for name in font_names}
    matches: list[Path] = []
    for path in directory.iterdir():
        if path.name.lower() in expected:
            matches.append(path)
    return sorted(
        matches,
        key=lambda path: font_names.index(path.name.lower()),
    )


def _path_to_strokes(path) -> list[Stroke]:
    strokes: list[Stroke] = []
    for sub_path in path.sub_paths():
        stroke: Stroke = []
        for point in sub_path.flattening(distance=0.01, segments=16):
            if not isfinite(point.x) or not isfinite(point.y):
                continue
            stroke.append((float(point.x), float(point.y)))
        if len(stroke) > 1:
            strokes.append(stroke)
    return strokes


def _line_x_offset(anchor: str, block_width: float, line_width: float) -> float:
    if "e" in anchor:
        return block_width - line_width
    if anchor in {"n", "s", "center"}:
        return (block_width - line_width) / 2
    return 0.0


def _anchor_offset(anchor: str, width: float, height: float) -> Point:
    if "e" in anchor:
        x = -width
    elif anchor in {"n", "s", "center"}:
        x = -width / 2
    else:
        x = 0.0

    if anchor.startswith("n"):
        y = -height
    elif anchor in {"w", "e", "center"}:
        y = -height / 2
    else:
        y = 0.0
    return x, y
