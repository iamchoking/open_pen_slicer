from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from math import atan2, degrees, hypot, isfinite
from pathlib import Path
from typing import Iterable

import ezdxf
from ezdxf.colors import BYBLOCK, BYLAYER, aci2rgb
from ezdxf import path as ez_path

from .settings import CropBox, PlotterSettings
from .text_renderer import render_text

Point = tuple[float, float]
Stroke = list[Point]


@dataclass
class PreviewStroke:
    points: Stroke
    color: str = "#2f3437"


@dataclass
class TextLabel:
    x: float
    y: float
    text: str
    height: float = 2.5
    rotation: float = 0.0
    anchor: str = "nw"
    color: str = "#4b5563"


@dataclass
class Drawing:
    source_path: Path
    strokes: list[Stroke]
    preview_strokes: list[PreviewStroke]
    text_labels: list[TextLabel]
    bounds: CropBox
    entity_counts: Counter[str] = field(default_factory=Counter)
    skipped_counts: Counter[str] = field(default_factory=Counter)

    @property
    def stroke_count(self) -> int:
        return len(self.strokes)

    @property
    def segment_count(self) -> int:
        return sum(max(0, len(stroke) - 1) for stroke in self.strokes)


def load_dxf_drawing(
    source_path: Path,
    curve_tolerance: float = 0.35,
    include_dimensions: bool = True,
) -> Drawing:
    """Read drawable DXF entities and flatten them into XY strokes."""
    doc = ezdxf.readfile(source_path)
    strokes: list[Stroke] = []
    preview_strokes: list[PreviewStroke] = []
    text_labels: list[TextLabel] = []
    entity_counts: Counter[str] = Counter()
    skipped_counts: Counter[str] = Counter()

    for entity in _iter_plot_entities(doc.modelspace(), include_dimensions):
        dxftype = entity.dxftype()
        entity_counts[dxftype] += 1
        if not _entity_is_visible(doc, entity):
            skipped_counts[f"{dxftype}:hidden"] += 1
            continue

        color = _entity_color(doc, entity)
        label = _entity_to_text_label(entity, color)
        if label:
            text_labels.append(label)
            text_strokes = _entity_to_text_strokes(entity, curve_tolerance)
            if text_strokes:
                strokes.extend(text_strokes)
                preview_strokes.extend(
                    PreviewStroke(stroke, color) for stroke in text_strokes
                )
            else:
                skipped_counts[dxftype] += 1
            continue

        try:
            stroke = _entity_to_stroke(entity, curve_tolerance)
        except TypeError:
            preview_stroke = _entity_to_preview_stroke(entity)
            if preview_stroke and _stroke_length(preview_stroke) > 0.001:
                preview_strokes.append(PreviewStroke(preview_stroke, color))
            else:
                skipped_counts[dxftype] += 1
            continue
        except ezdxf.DXFError:
            skipped_counts[dxftype] += 1
            continue

        if stroke and _stroke_length(stroke) > 0.001:
            strokes.append(stroke)
            preview_strokes.append(PreviewStroke(stroke, color))
        else:
            skipped_counts[f"{dxftype}:empty"] += 1

    bounds = compute_bounds([item.points for item in preview_strokes] + strokes)
    return Drawing(
        source_path=source_path,
        strokes=strokes,
        preview_strokes=preview_strokes,
        text_labels=text_labels,
        bounds=bounds,
        entity_counts=entity_counts,
        skipped_counts=skipped_counts,
    )


def compute_bounds(strokes: Iterable[Stroke]) -> CropBox:
    xs: list[float] = []
    ys: list[float] = []
    for stroke in strokes:
        for x, y in stroke:
            xs.append(x)
            ys.append(y)

    if not xs or not ys:
        return CropBox(0.0, 0.0, 100.0, 100.0)

    return CropBox(min(xs), min(ys), max(xs), max(ys))


def rotate_drawing_quarters(drawing: Drawing, quarters: int) -> Drawing:
    rotated = drawing
    for _index in range(int(quarters) % 4):
        rotated = rotate_drawing_ccw(rotated)
    return rotated


def rotate_drawing_ccw(
    drawing: Drawing, pivot: Point | None = None
) -> Drawing:
    pivot = pivot or crop_box_center(drawing.bounds)
    strokes = [_rotate_stroke_ccw(stroke, pivot) for stroke in drawing.strokes]
    preview_strokes = [
        PreviewStroke(
            points=_rotate_stroke_ccw(preview_stroke.points, pivot),
            color=preview_stroke.color,
        )
        for preview_stroke in drawing.preview_strokes
    ]
    text_labels = [
        TextLabel(
            x=rotated_point[0],
            y=rotated_point[1],
            text=label.text,
            height=label.height,
            rotation=(label.rotation + 90.0) % 360.0,
            anchor=label.anchor,
            color=label.color,
        )
        for label in drawing.text_labels
        for rotated_point in [rotate_point_ccw((label.x, label.y), pivot)]
    ]
    bounds = compute_bounds([item.points for item in preview_strokes] + strokes)
    return Drawing(
        source_path=drawing.source_path,
        strokes=strokes,
        preview_strokes=preview_strokes,
        text_labels=text_labels,
        bounds=bounds,
        entity_counts=drawing.entity_counts.copy(),
        skipped_counts=drawing.skipped_counts.copy(),
    )


def rotate_crop_box_ccw(crop: CropBox, pivot: Point) -> CropBox:
    box = crop.normalized()
    points = [
        rotate_point_ccw((box.xmin, box.ymin), pivot),
        rotate_point_ccw((box.xmax, box.ymin), pivot),
        rotate_point_ccw((box.xmax, box.ymax), pivot),
        rotate_point_ccw((box.xmin, box.ymax), pivot),
    ]
    return compute_bounds([points]).normalized()


def rotate_point_ccw(point: Point, pivot: Point) -> Point:
    x, y = point
    px, py = pivot
    return (px - (y - py), py + (x - px))


def crop_box_center(crop: CropBox) -> Point:
    box = crop.normalized()
    return ((box.xmin + box.xmax) / 2.0, (box.ymin + box.ymax) / 2.0)


def clip_strokes_to_crop(strokes: Iterable[Stroke], crop: CropBox) -> list[Stroke]:
    box = crop.normalized()
    clipped_strokes: list[Stroke] = []

    for stroke in strokes:
        active: Stroke = []
        for start, end in zip(stroke, stroke[1:]):
            clipped = clip_segment_to_box(start, end, box)
            if clipped is None:
                if len(active) > 1:
                    clipped_strokes.append(active)
                active = []
                continue

            clipped_start, clipped_end = clipped
            if not active:
                active = [clipped_start, clipped_end]
            elif _same_point(active[-1], clipped_start):
                active.append(clipped_end)
            else:
                if len(active) > 1:
                    clipped_strokes.append(active)
                active = [clipped_start, clipped_end]

        if len(active) > 1:
            clipped_strokes.append(active)

    return [
        _dedupe_stroke(stroke)
        for stroke in clipped_strokes
        if _stroke_length(stroke) > 0.001
    ]


def _rotate_stroke_ccw(stroke: Stroke, pivot: Point) -> Stroke:
    return [rotate_point_ccw(point, pivot) for point in stroke]


def transform_strokes(
    strokes: Iterable[Stroke],
    crop: CropBox,
    settings: PlotterSettings,
) -> list[Stroke]:
    transformed: list[Stroke] = []
    for stroke in strokes:
        transformed.append(
            [
                (
                    settings.home_x + (x - settings.origin_x) * settings.scale,
                    settings.home_y + (y - settings.origin_y) * settings.scale,
                )
                for x, y in stroke
            ]
        )
    return transformed


def plot_bounds_for_crop(crop: CropBox, settings: PlotterSettings) -> CropBox:
    box = crop.normalized()
    return CropBox(
        settings.home_x + (box.xmin - settings.origin_x) * settings.scale,
        settings.home_y + (box.ymin - settings.origin_y) * settings.scale,
        settings.home_x + (box.xmax - settings.origin_x) * settings.scale,
        settings.home_y + (box.ymax - settings.origin_y) * settings.scale,
    )


def total_path_length(strokes: Iterable[Stroke]) -> float:
    return sum(_stroke_length(stroke) for stroke in strokes)


def _iter_plot_entities(entities, include_dimensions: bool, depth: int = 0):
    if depth > 8:
        return

    for entity in entities:
        dxftype = entity.dxftype()
        if dxftype == "INSERT" or (include_dimensions and dxftype == "DIMENSION"):
            try:
                yield from _iter_plot_entities(
                    entity.virtual_entities(), include_dimensions, depth + 1
                )
            except (ezdxf.DXFError, AttributeError, TypeError):
                yield entity
            continue
        yield entity


def _entity_is_visible(doc, entity) -> bool:
    if entity.dxf.hasattr("invisible") and entity.dxf.invisible:
        return False

    layer_name = entity.dxf.layer if entity.dxf.hasattr("layer") else None
    if not layer_name:
        return True

    try:
        layer = doc.layers.get(layer_name)
    except ezdxf.DXFTableEntryError:
        return True

    return not layer.is_off() and not layer.is_frozen()


def _entity_color(doc, entity) -> str:
    if entity.dxf.hasattr("true_color") and entity.dxf.true_color is not None:
        value = int(entity.dxf.true_color)
        return f"#{(value >> 16) & 0xff:02x}{(value >> 8) & 0xff:02x}{value & 0xff:02x}"

    color_index = int(entity.dxf.color) if entity.dxf.hasattr("color") else BYLAYER
    if color_index in (BYLAYER, BYBLOCK):
        layer_name = entity.dxf.layer if entity.dxf.hasattr("layer") else None
        if layer_name:
            try:
                layer = doc.layers.get(layer_name)
                color_index = abs(int(layer.dxf.color))
            except (ezdxf.DXFTableEntryError, TypeError, ValueError):
                color_index = 7

    try:
        rgb = aci2rgb(color_index)
    except IndexError:
        return "#2f3437"

    if (rgb.r, rgb.g, rgb.b) in {(255, 255, 255), (0, 0, 0)}:
        return "#2f3437"
    return f"#{rgb.r:02x}{rgb.g:02x}{rgb.b:02x}"


def _entity_to_stroke(entity, curve_tolerance: float) -> Stroke | None:
    dxf_type = entity.dxftype()
    if dxf_type == "POINT":
        return None

    # ezdxf.path handles LINE, ARC, CIRCLE, LWPOLYLINE, POLYLINE, ELLIPSE,
    # SPLINE, and several virtual entities with bulges/curves.
    path = ez_path.make_path(entity)
    points = [
        (float(point.x), float(point.y))
        for point in path.flattening(distance=curve_tolerance)
        if isfinite(point.x) and isfinite(point.y)
    ]
    return _dedupe_stroke(points)


def _entity_to_preview_stroke(entity) -> Stroke | None:
    dxftype = entity.dxftype()
    if dxftype == "LEADER" and hasattr(entity, "vertices"):
        return [
            (float(point[0]), float(point[1]))
            for point in entity.vertices
            if len(point) >= 2
        ]
    if dxftype == "POINT" and entity.dxf.hasattr("location"):
        x = float(entity.dxf.location.x)
        y = float(entity.dxf.location.y)
        size = 0.8
        return [(x - size, y), (x + size, y), (x, y), (x, y - size), (x, y + size)]
    return None


def _entity_to_text_strokes(entity, curve_tolerance: float) -> list[Stroke]:
    dxftype = entity.dxftype()
    if dxftype not in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}:
        return []

    label = _entity_to_text_label(entity, "#000000")
    if label is None:
        return []
    width_factor = _dxf_float(entity, "width_factor", 0.75)
    if width_factor <= 0.0:
        width_factor = 0.75
    line_spacing = _dxf_float(entity, "line_spacing_factor", 1.25)
    if line_spacing <= 0.0:
        line_spacing = 1.25

    return [
        stroke
        for stroke in render_text(
            text=label.text,
            insert=(label.x, label.y),
            height=label.height,
            rotation=label.rotation,
            width_factor=width_factor,
            line_spacing=line_spacing,
            anchor=label.anchor,
        )
        if _stroke_length(stroke) > 0.001
    ]


def _mtext_alignment_anchor(entity) -> str:
    try:
        attachment = int(entity.dxf.attachment_point)
    except (AttributeError, TypeError, ValueError):
        attachment = 1
    return {
        1: "nw",
        2: "n",
        3: "ne",
        4: "w",
        5: "center",
        6: "e",
        7: "sw",
        8: "s",
        9: "se",
    }.get(attachment, "nw")


def _text_anchor(entity) -> str:
    if entity.dxftype() == "MTEXT":
        return _mtext_alignment_anchor(entity)
    return "sw"


def _normalize_anchor(anchor: str) -> str:
    return anchor


def _entity_text_rotation(entity) -> float:
    if entity.dxf.hasattr("rotation"):
        return _dxf_float(entity, "rotation", 0.0)
    if entity.dxf.hasattr("text_direction"):
        direction = entity.dxf.text_direction
        try:
            return degrees(atan2(direction.y, direction.x))
        except (TypeError, AttributeError):
            return 0.0
    return 0.0


def _entity_text_height(entity) -> float:
    for attr in ("height", "char_height"):
        if entity.dxf.hasattr(attr):
            value = _dxf_float(entity, attr, 2.5)
            if value > 0:
                return value
    return 2.5


def _entity_text_insert(entity):
    for attr in ("insert", "align_point", "location"):
        if entity.dxf.hasattr(attr):
            return getattr(entity.dxf, attr)
    return None


def _entity_text_plain(entity) -> str:
    if hasattr(entity, "plain_text"):
        try:
            return entity.plain_text()
        except TypeError:
            return entity.plain_text(split=False)
    if entity.dxf.hasattr("text"):
        return str(entity.dxf.text)
    return ""


def _dxf_float(entity, attr: str, fallback: float) -> float:
    if not entity.dxf.hasattr(attr):
        return fallback
    try:
        return float(getattr(entity.dxf, attr))
    except (TypeError, ValueError):
        return fallback


def _entity_to_text_label(entity, color: str) -> TextLabel | None:
    dxftype = entity.dxftype()
    if dxftype not in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF", "TOLERANCE"}:
        return None

    text = _clean_dxf_text(_entity_text_plain(entity))
    if not text:
        return None

    insert = _entity_text_insert(entity)
    if insert is None:
        return None

    return TextLabel(
        x=float(insert.x),
        y=float(insert.y),
        text=text,
        height=_entity_text_height(entity),
        rotation=_entity_text_rotation(entity),
        anchor=_normalize_anchor(_text_anchor(entity)),
        color=color,
    )


def _clean_dxf_text(text: str) -> str:
    text = text.replace("\\P", "\n")
    text = text.replace("\\~", " ")
    text = text.replace("{", "").replace("}", "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _dedupe_stroke(stroke: Stroke) -> Stroke:
    deduped: Stroke = []
    for point in stroke:
        if deduped and _same_point(deduped[-1], point):
            continue
        deduped.append(point)
    return deduped


def _same_point(a: Point, b: Point, tolerance: float = 1e-6) -> bool:
    return abs(a[0] - b[0]) <= tolerance and abs(a[1] - b[1]) <= tolerance


def _stroke_length(stroke: Stroke) -> float:
    return sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(stroke, stroke[1:]))


INSIDE = 0
LEFT = 1
RIGHT = 2
BOTTOM = 4
TOP = 8


def clip_segment_to_box(start: Point, end: Point, crop: CropBox) -> tuple[Point, Point] | None:
    box = crop.normalized()
    x1, y1 = start
    x2, y2 = end
    code1 = _clip_code(x1, y1, box)
    code2 = _clip_code(x2, y2, box)

    while True:
        if not (code1 | code2):
            return (x1, y1), (x2, y2)
        if code1 & code2:
            return None

        code_out = code1 or code2
        if code_out & TOP:
            if y2 == y1:
                return None
            x = x1 + (x2 - x1) * (box.ymax - y1) / (y2 - y1)
            y = box.ymax
        elif code_out & BOTTOM:
            if y2 == y1:
                return None
            x = x1 + (x2 - x1) * (box.ymin - y1) / (y2 - y1)
            y = box.ymin
        elif code_out & RIGHT:
            if x2 == x1:
                return None
            y = y1 + (y2 - y1) * (box.xmax - x1) / (x2 - x1)
            x = box.xmax
        else:
            if x2 == x1:
                return None
            y = y1 + (y2 - y1) * (box.xmin - x1) / (x2 - x1)
            x = box.xmin

        if code_out == code1:
            x1, y1 = x, y
            code1 = _clip_code(x1, y1, box)
        else:
            x2, y2 = x, y
            code2 = _clip_code(x2, y2, box)


def _clip_code(x: float, y: float, crop: CropBox) -> int:
    code = INSIDE
    if x < crop.xmin:
        code |= LEFT
    elif x > crop.xmax:
        code |= RIGHT
    if y < crop.ymin:
        code |= BOTTOM
    elif y > crop.ymax:
        code |= TOP
    return code
