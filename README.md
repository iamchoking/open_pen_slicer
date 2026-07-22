# Ender 3 Pro Pen Plotter

Small Python DXF-to-G-code tool for a pen mounted on an Ender 3 Pro.

Pen mount reference: <https://www.thingiverse.com/thing:4574948>

The generated G-code:

- uses millimeters and absolute positioning
- homes the printer
- lifts to `home_z + z_safe_height` before plotting and before the final top-left move
- traces the selected crop box before the drawing, using configurable repeat,
  outward offset, and feed settings
- lifts/drops Z for pen up/down strokes
- never emits extrusion moves
- never heats the hotend or bed
- emits `M104 S0` and `M140 S0` only as safety shutoff commands

## Setup

This project is configured for the `raisim` conda environment:

```powershell
conda activate raisim
python -m pip install -r requirements.txt
```

The environment and dependencies have already been created on this machine.

## UI Workflow

1. Put a `.dxf` file in `raw/`.
2. Start the UI:

```powershell
conda run -n raisim python scripts/run_ui.py
```

3. Press **Crop**, then drag or resize the orange crop box in the preview.
4. Press **Origin**, then drag the green Ender 3 Pro buildplate outline to place its blue lower-left home marker in the DXF.
5. Set scale, rotate the DXF if needed, then set Home X/Y/Z, Z hop, Z safe
   height, feed rates, and bounding box settings.
6. Choose **Target Directory**.
7. Press **Generate**.

**Home (mm)** is the printer G-code coordinate used when a plotted point lands
on the lower-left of the buildplate visual. **Origin (mm)** is the source DXF
coordinate where that lower-left buildplate point is placed. **Crop (mm)** shows
the red crop rectangle as `X / Y / Xlen / Ylen`.

When neither **Crop** nor **Origin** is active, dragging pans the preview and
`Ctrl` + mouse wheel zooms around the cursor.

The **Target Directory** dropdown includes `Downloads` and plugged-in removable
USB/SD drives. The app writes `[pen_plotter] <filename>.gcode` to that target
and saves the current settings to `settings.yaml`. Those saved values are loaded
the next time the UI opens.

## CLI Workflow

Generate using the current `settings.yaml`:

```powershell
conda run -n raisim python scripts/generate_cli.py --input raw/mech_linkage_bar.DXF
```

Persist CLI values back to `settings.yaml`:

```powershell
conda run -n raisim python scripts/generate_cli.py --scale 0.48 --home-x 0 --home-y 0 --origin-x 10 --origin-y 10 --save-settings
```

## Printer Notes

Printer limits are read from `printer.yaml` at the project root. `boundary`
defines the absolute Ender 3 Pro limits, and `safety_margin` defines the inset
printable area shown as the inner dotted rectangle in the preview. Since the
buildplate visual lower-left maps to Home X/Y, its safe right edge is shown at
`boundary.x - safety_margin - home_x` relative to that lower-left point, and Y
follows the same pattern.

If the scaled crop, preflight crop-box outlines, or Z heights exceed the
absolute boundary, G-code generation is refused. If they stay inside the
absolute boundary but enter the safety margin, the UI/CLI shows a warning and
still writes the G-code. Home Z is treated as pen down height; pen up height is
`home_z + z_hop`, and safe travel height is `home_z + z_safe_height`.

## Text Fonts

DXF `TEXT` and `MTEXT` annotations are rendered with SHX stroke fonts. Korean
text uses `whgtxt.shx` or `whgdtxt.shx`; ASCII title-block text uses `txt.shx`
or `simplex.shx`. Put the fonts in `fonts/`, or set `PEN_PLOTTER_FONT_DIR` to a
directory containing them.
