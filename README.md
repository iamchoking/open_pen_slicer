# Open Pen Slicer

Small Python DXF-to-G-code tool for a pen mounted on an Ender 3 Pro.

Pen mount reference: <https://www.thingiverse.com/thing:4574948>

The generated G-code:

- uses millimeters and absolute positioning
- homes the printer
- lifts to `home_z + z_safe_height` before plotting and before the final top-left move
- traces padded 5 mm dotted bounding boxes from outermost to innermost, then
  marks the selected crop corners with L-shapes before plotting
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

1. Start the UI:

```powershell
conda run -n raisim python scripts/run_ui.py
```

2. Drop a `.dxf` file into the UI, or choose one of the last 10 remembered
   file paths from **File**.
3. In **Settings**, press **Crop**, then drag or resize the orange crop box in the preview.
4. Press **Set Origin**, then drag the green Ender 3 Pro buildplate outline to place its blue lower-left home marker in the DXF, or press **Center** to center the crop inside the dotted printable area.
5. Choose the Device. Use **Edit** to open its YAML in Notepad and **Reload**
   after changing printer properties, then use **Settings** to choose the DXF,
   set scale, rotate the DXF, and set bounding box settings.
6. Press **Save Settings** to save the current UI values to `config/settings.yaml`.
7. Set the output **Filename** and choose **Target Directory**.
8. Press **Generate**.

**Home** is the printer G-code coordinate used when a plotted point lands
on the lower-left of the buildplate visual. **Origin** is the source DXF
coordinate where that lower-left buildplate point is placed. **Crop** shows
the red crop rectangle as `X / Y / width / height`.

When neither **Crop** nor **Set Origin** is active, dragging pans the preview and
`Ctrl` + mouse wheel zooms around the cursor.

The **Target Directory** dropdown includes `Downloads` and plugged-in removable
USB/SD drives. **Generate** writes the editable **Filename** to that target.
When a removable target is selected, **Clear Drive** removes existing `*.gcode`
files from that drive before the new file is written, and **Eject** safely
ejects it after a successful write.
**Save Settings** writes the current UI values to
`config/settings.yaml` without generating G-code.
Dropped or selected DXF files are saved immediately as `active_file` plus the
last 10 `recent_files` in `config/settings.yaml`.

## CLI Workflow

Generate using the current `config/settings.yaml` active/recent DXF:

```powershell
conda run -n raisim python scripts/generate_cli.py
```

Persist CLI values back to `config/settings.yaml`; device values such as Home,
Z Height, and Speed are saved to the matching file in `config/devices/`:

```powershell
conda run -n raisim python scripts/generate_cli.py --scale 0.48 --home-x 0 --home-y 0 --origin-x 10 --origin-y 10 --save-settings
```

## Printer Notes

Printer devices are read from every `.yaml` file in `config/devices/`. The file
stem is the device ID, and `name` is shown in the Device dropdown. Device fields
are read-only in the UI; use **Edit** to open the selected YAML in Notepad and
**Reload** to re-read it. Each file defines `home`, `z_height`, `speed`,
`boundary`, and `safety_margin`. Speed values are in `mm/s`. The green outer
rectangle is the physical buildplate size. Since its lower-left maps to Home
X/Y, the inner dotted safe right edge is shown at
`boundary.x - safety_margin - home_x` relative to that lower-left point, and Y
follows the same pattern.

If the outermost preflight bounding box or Z heights exceed the
absolute boundary, G-code generation is refused. If they stay inside the
absolute boundary but enter the safety margin, the UI/CLI shows a warning and
still writes the G-code. Home Z is treated as pen down height; pen up height is
`home_z + z_hop`, and safe travel height is `home_z + z_safe_height`.

Set bounding box Num to `0` to plot only the four crop-corner L marks. With
Num above `0`, dotted boxes run from the outermost padded box inward before the
corner L marks.

## Text Fonts

DXF `TEXT` and `MTEXT` annotations are rendered with SHX stroke fonts. Korean
text uses `whgtxt.shx` or `whgdtxt.shx`; ASCII title-block text uses `txt.shx`
or `simplex.shx`. Put the fonts in `fonts/`, or set `PEN_PLOTTER_FONT_DIR` to a
directory containing them.
