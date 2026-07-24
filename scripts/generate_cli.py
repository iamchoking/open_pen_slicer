from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pen_plotter.gcode import generate_gcode, plot_bounds_including_preflight
from pen_plotter.geometry import (
    clip_stroke_blocks_to_crop,
    clip_strokes_to_crop,
    load_dxf_drawing,
    rotate_drawing_quarters,
    transform_stroke_blocks,
    transform_strokes,
)
from pen_plotter.settings import (
    DEFAULT_RECENTS_PATH,
    DEFAULT_SETTINGS_PATH,
    CropBox,
    default_gcode_path,
    load_settings,
    save_recent_files,
    save_settings,
)
from pen_plotter.stroke_optimizer import optimize_plot_strokes
from pen_plotter.printer import (
    check_gcode_bounds,
    load_printer_profiles,
    save_printer_profile,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Open Pen Slicer G-code from a DXF.")
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=None,
        help=(
            "DXF path. Defaults to active_file or recent_files "
            "from config/recents.yaml."
        ),
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
        help="Directory for the saved output_filename when --output is omitted.",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Printer device ID from config/devices/<device>.yaml, for example CE3PRO.",
    )
    parser.add_argument("--home-x", type=float, default=None)
    parser.add_argument("--home-y", type=float, default=None)
    parser.add_argument("--home-z", type=float, default=None)
    parser.add_argument("--origin-x", type=float, default=None)
    parser.add_argument("--origin-y", type=float, default=None)
    parser.add_argument("--z-hop", type=float, default=None)
    parser.add_argument("--z-safe-height", type=float, default=None)
    parser.add_argument("--draw-speed", type=float, default=None, help="Draw speed in mm/s.")
    parser.add_argument("--travel-speed", type=float, default=None, help="Travel speed in mm/s.")
    parser.add_argument("--scale", type=float, default=None)
    parser.add_argument("--rotation-quarters", type=int, default=None)
    parser.add_argument(
        "--bounding-box-repeat",
        type=int,
        default=None,
        help="Bounding-box number (Num): count of padded dotted boxes.",
    )
    parser.add_argument(
        "--bounding-box-offset",
        type=float,
        default=None,
        help="Bounding-box padding (Pad) in mm between preflight boxes.",
    )
    parser.add_argument(
        "--bounding-box-speed",
        type=float,
        default=None,
        help="Bounding-box draw speed in mm/s.",
    )
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
        help="Persist CLI values back to config/settings.yaml.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings()
    if args.device is not None:
        settings.device_id = str(args.device)

    printer_profiles = load_printer_profiles()
    printer = printer_profiles.get(settings.device_id) or next(iter(printer_profiles.values()))
    settings.device_id = printer.key
    settings.home_x = printer.home_x
    settings.home_y = printer.home_y
    settings.home_z = printer.home_z
    settings.z_hop = printer.z_hop
    settings.z_safe_height = printer.z_safe_height
    settings.draw_speed = printer.draw_speed
    settings.travel_speed = printer.travel_speed

    source = args.input
    if source is None and settings.active_file:
        source = _resolve_input_path(settings.active_file)
    if source is None:
        source = next(
            (
                path
                for path in (_resolve_input_path(value) for value in settings.recent_files)
                if path.exists() and path.suffix.lower() == ".dxf"
            ),
            None,
        )
    if source is None:
        raise SystemExit("No DXF file found. Drop one in the UI or pass --input.")
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
        ("draw_speed", args.draw_speed),
        ("travel_speed", args.travel_speed),
        ("scale", args.scale),
        ("rotation_quarters", args.rotation_quarters),
        ("bounding_box_repeat", args.bounding_box_repeat),
        ("bounding_box_offset", args.bounding_box_offset),
        ("bounding_box_speed", args.bounding_box_speed),
    ):
        if value is not None:
            setattr(settings, attr, value)
    if args.target_directory is not None:
        settings.target_directory = str(args.target_directory)
    settings.active_file = _settings_file_text(source)
    settings.recent_files = _recent_file_texts_with(
        settings.active_file,
        settings.recent_files,
    )

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
    plot_bounds = plot_bounds_including_preflight(crop, settings)
    boundary_check = check_gcode_bounds(plot_bounds, settings, printer)
    if boundary_check.blocked:
        raise SystemExit("Refusing to write G-code: " + boundary_check.message)
    if boundary_check.warning:
        print("Warning: " + boundary_check.message)

    cropped_geometry = clip_strokes_to_crop(drawing.non_text_strokes, crop)
    cropped_text_blocks = clip_stroke_blocks_to_crop(drawing.text_blocks, crop)
    transformed = optimize_plot_strokes(
        transform_strokes(cropped_geometry, crop, settings),
        transform_stroke_blocks(cropped_text_blocks, crop, settings),
    )
    output = args.output or default_gcode_path(
        source,
        settings.target_directory,
        settings.output_filename,
    )
    if not output.is_absolute():
        output = PROJECT_ROOT / output

    summary = generate_gcode(source, transformed, crop, settings, output)
    if args.save_settings:
        if any(
            value is not None
            for value in (
                args.home_x,
                args.home_y,
                args.home_z,
                args.z_hop,
                args.z_safe_height,
                args.draw_speed,
                args.travel_speed,
            )
        ):
            printer = (
                printer.with_home(
                    settings.home_x,
                    settings.home_y,
                    settings.home_z,
                ).with_motion(
                    settings.z_hop,
                    settings.z_safe_height,
                    settings.draw_speed,
                    settings.travel_speed,
                )
            )
            save_printer_profile(printer)
        save_settings(settings, DEFAULT_SETTINGS_PATH)
        save_recent_files(
            settings.recent_files,
            DEFAULT_RECENTS_PATH,
            settings.output_filename,
        )

    print(f"Wrote {summary.output_path}")
    print(f"Strokes: {summary.stroke_count}")
    print(f"Segments: {summary.segment_count}")
    print(
        "Plot bounds: "
        f"X {summary.plot_bounds.xmin:.2f}..{summary.plot_bounds.xmax:.2f}, "
        f"Y {summary.plot_bounds.ymin:.2f}..{summary.plot_bounds.ymax:.2f}"
    )


def _resolve_input_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _settings_file_text(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _recent_file_texts_with(first_file: str, recent_files: list[str]) -> list[str]:
    values = [first_file, *recent_files]
    recent: list[str] = []
    seen: set[str] = set()
    for value in values:
        path = _resolve_input_path(value)
        if path.suffix.lower() != ".dxf":
            continue
        text = _settings_file_text(path)
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        recent.append(text)
        if len(recent) >= 10:
            break
    return recent


if __name__ == "__main__":
    main()
