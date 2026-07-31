# Visual comparison

The optional visual-comparison tool registers LDraw or LeoCAD renders against
raster reference images. It is intended for camera selection and repeatable
visual regression work: it does not modify the model or the program that
generated it.

The comparison pipeline estimates the flat background from the image border
(or uses PNG alpha), extracts both silhouettes, and searches a configurable
scale range. For every scale it finds the translation with the largest
silhouette overlap, then selects the registration with the highest intersection
over union (IoU).

Pillow and the visual-comparison tool are not part of the base installation.
Install the `visual-compare` extra before running it:

```console
pip install "pyldraw3[visual-compare]"
```

From a repository checkout, use `uv sync --extra visual-compare`. Run the tool
as `python -m ldraw.visual_compare`, or use the equivalent repository script
`python scripts/visual_compare.py`.

## Compare one view

```console
uv run --extra visual-compare python scripts/visual_compare.py compare \
  references/front.png renders/scout.front.png \
  --output-dir comparison/front \
  --min-scale 0.75 --max-scale 1.30 --scale-steps 56
```

This writes:

- `comparison.json`, with the registration and metrics;
- `aligned.png`, the isolated candidate foreground on the estimated reference
  background;
- `overlay.png`, where red is reference-only silhouette and cyan is
  candidate-only silhouette; and
- `difference.png`, a black-to-red-to-yellow difference heatmap. Silhouette
  mismatches use the maximum heatmap value.

The metrics are normalized to `0..1` where applicable:

- silhouette IoU, Dice, precision, and recall;
- candidate/reference foreground area ratio; and
- RGB mean absolute error (MAE) and root mean square error (RMSE), measured on
  the intersecting foreground.

PNG alpha gives the most reliable foreground. For opaque images, tune
`--background-tolerance` if anti-aliasing, shadows, or an off-white background
are being mistaken for foreground.

## Rank existing renders

Rank any set of PNGs independently of the renderer that created them:

```console
uv run --extra visual-compare python scripts/visual_compare.py rank \
  references/front.png renders/camera-*.png \
  --output-dir comparison/front-cameras --columns 5
```

`ranking.json` records each candidate's alignment and metrics. `ranking.png` is
a contact sheet ordered by silhouette IoU, with RGB MAE breaking ties.

## Generate and rank a LeoCAD camera grid

LeoCAD must be on `PATH`, or supplied with `--leocad`:

```console
uv run --extra visual-compare python scripts/visual_compare.py camera-grid model.mpd \
  --reference references/front.png \
  --output-dir comparison/camera-grid \
  --latitudes 10,20,30,40 \
  --longitudes=-70,-55,-40,-25 \
  --size 1200x900
```

The command renders the Cartesian product of the latitude and longitude lists.
Filenames encode the exact angles, and `camera-grid.json` records the full
LeoCAD command for reproducibility. When `--reference` is given, the JSON also
contains the ranked registrations and `camera-grid.png` contains the ordered
contact sheet. Add `--skip-existing` to resume an interrupted grid without
rerendering completed PNGs. Each render is bounded by `--timeout` seconds
(default 240); the render metadata is written to `camera-grid.json` before
ranking starts, so it survives a failed ranking pass.

The camera sweep is intentionally separate from model generation. It invokes
LeoCAD as:

```text
leocad MODEL --image OUTPUT --width WIDTH --height HEIGHT \
  --camera-angles LATITUDE LONGITUDE
```

## Crop important regions

For a single comparison, pass a JSON list with named regions. Boxes are
`[x, y, width, height]`, normalized by default:

```json
[
  {"name": "front grille", "box": [0.28, 0.57, 0.44, 0.22]},
  {"name": "roof", "box": [240, 80, 520, 260], "relative": false}
]
```

```console
uv run --extra visual-compare python scripts/visual_compare.py compare \
  reference.png render.png \
  --output-dir comparison --regions regions.json
```

Each region gets reference, aligned, overlay, and difference crops under
`regions/`, plus its own metrics in `comparison.json`.

## Report several reference views

Use a manifest to compare multiple views and, if useful, several candidates per
view. Paths are relative to the manifest:

```json
{
  "alignment": {
    "min_scale": 0.70,
    "max_scale": 1.35,
    "scale_steps": 66,
    "background_tolerance": 24
  },
  "views": [
    {
      "name": "front",
      "reference": "references/front.png",
      "candidates": [
        {"label": "current", "path": "renders/scout.front.png"},
        {"label": "alternate", "path": "renders/scout.front-alt.png"}
      ],
      "regions": [
        {"name": "bumper", "box": [0.20, 0.68, 0.60, 0.22]}
      ]
    },
    {
      "name": "rear three-quarter",
      "reference": "references/rear.png",
      "candidate": "renders/scout.rear.png"
    }
  ]
}
```

```console
uv run --extra visual-compare python scripts/visual_compare.py report \
  comparison-manifest.json \
  --output-dir comparison/report
```

The output contains `report.json`, a concise `report.html`, and all per-view
artifacts under `views/VIEW/CANDIDATE/`. Candidates are ranked within each view;
the aggregate section reports the mean of every metric across all comparisons.

## Interpreting results

Registration deliberately removes framing differences, so IoU emphasizes shape
and camera orientation rather than canvas placement. Inspect the recorded scale
and offsets when framing itself matters. RGB metrics are sensitive to renderer
lighting, material settings, and reference-image compression; silhouette
metrics are usually more useful for selecting the camera, while region crops
and heatmaps are more useful for finding local geometry differences.

The foreground estimator assumes the image border mostly belongs to a fairly
flat background. Use transparent renders or pre-masked inputs for photographs
with textured backgrounds, objects touching the frame, or strong cast shadows.
