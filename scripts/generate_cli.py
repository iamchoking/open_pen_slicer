from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pen_plotter.gcode import generate_gcode, plot_bounds_including_preflight
from pen_plotter.geometry import (
    clip_strokes_to_crop,
    load_dxf_drawing,
    rotate_drawing_quarters,
    transform_strokes,
)
from pen_plotter.settings import (
    DEFAULT_SETTINGS_PATH,
    CropBox,
    default_gcode_path,
    load_settings,
    save_settings,
)
from pen_plotter.printer import check_gcode_bounds, load_printer_profile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate pen-plotter G-code from a DXF.")
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=None,
        help="DXF path. Defaults to active_file from settings.yaml or the first raw/*.dxf.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Explicit output G-code path.",
    )
    parser.add_argument(
        "--target-directory",
        type=Path,
        default=None,
        help="Directory for [pen_plotter] <input-stem>.gcode when --output is omitted.",
    )
    parser.add_argument("--home-x", type=float, default=None)
    parser.add_argument("--home-y", type=float, default=None)
    parser.add_argument("--home-z", type=float, default=None)
    parser.add_argument("--origin-x", type=float, default=None)
    parser.add_argument("--origin-y", type=float, default=None)
    parser.add_argument("--z-hop", type=float, default=None)
    parser.add_argument("--z-safe-height", type=float, default=None)
    parser.add_argument("--scale", type=float, default=None)
    parser.add_argument("--rotation-quarters", type=int, default=None)
    parser.add_argument("--bounding-box-repeat", type=int, default=None)
    parser.add_argument("--bounding-box-offset", type=float, default=None)
    parser.add_argument("--bounding-box-feed", type=float, default=None)
    parser.add_argument(
        "--crop",
        nargs=4,
        type=float,
        metavar=("XMIN", "YMIN", "XMAX", "YMAX"),
        help="Crop rectangle in DXF units. Defaults to settings crop or full drawing.",
    )
    parser.add_argument(
        "--save-settings",
        action="store_true",
        help="Persist CLI values back to settings.yaml.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings()

    source = args.input
    if source is None and settings.active_file:
        source = PROJECT_ROOT / settings.active_file
    if source is None:
        candidates = sorted((PROJECT_ROOT / "raw").glob("*.dxf"))
        candidates += sorted((PROJECT_ROOT / "raw").glob("*.DXF"))
        if candidates:
            source = candidates[0]
    if source is None:
        raise SystemExit("No DXF file found. Put one in raw/ or pass --input.")
    if not source.is_absolute():
        source = PROJECT_ROOT / source

    for attr, value in (
        ("home_x", args.home_x),
        ("home_y", args.home_y),
        ("home_z", args.home_z),
        ("origin_x", args.origin_x),
        ("origin_y", args.origin_y),
        ("z_hop", args.z_hop),
        ("z_safe_height", args.z_safe_height),
        ("scale", args.scale),
        ("rotation_quarters", args.rotation_quarters),
        ("bounding_box_repeat", args.bounding_box_repeat),
        ("bounding_box_offset", args.bounding_box_offset),
        ("bounding_box_feed", args.bounding_box_feed),
    ):
        if value is not None:
            setattr(settings, attr, value)
    if args.target_directory is not None:
        settings.target_directory = str(args.target_directory)
    settings.active_file = source.resolve().relative_to(PROJECT_ROOT).as_posix()

    drawing = load_dxf_drawing(
        source,
        curve_tolerance=settings.curve_tolerance / max(settings.scale, 0.0001),
    )
    drawing = rotate_drawing_quarters(drawing, settings.rotation_quarters)
    if args.crop:
        crop = CropBox(*args.crop).normalized()
    elif settings.crop:
        crop = settings.crop.normalized()
    else:
        crop = drawing.bounds.normalized()
    settings.crop = crop
    settings.validate()
    printer = load_printer_profile()
    plot_bounds = plot_bounds_including_preflight(crop, settings)
    boundary_check = check_gcode_bounds(plot_bounds, settings, printer)
    if boundary_check.blocked:
        raise SystemExit("Refusing to write G-code: " + boundary_check.message)
    if boundary_check.warning:
        print("Warning: " + boundary_check.message)

    cropped = clip_strokes_to_crop(drawing.strokes, crop)
    transformed = transform_strokes(cropped, crop, settings)
    output = args.output or default_gcode_path(source, settings.target_directory)
    if not output.is_absolute():
        output = PROJECT_ROOT / output

    summary = generate_gcode(source, transformed, crop, settings, output)
    if args.save_settings:
        save_settings(settings, DEFAULT_SETTINGS_PATH)

    print(f"Wrote {summary.output_path}")
    print(f"Strokes: {summary.stroke_count}")
    print(f"Segments: {summary.segment_count}")
    print(
        "Plot bounds: "
        f"X {summary.plot_bounds.xmin:.2f}..{summary.plot_bounds.xmax:.2f}, "
        f"Y {summary.plot_bounds.ymin:.2f}..{summary.plot_bounds.ymax:.2f}"
    )


if __name__ == "__main__":
    main()
