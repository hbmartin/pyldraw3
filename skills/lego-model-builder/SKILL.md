---
name: lego-model-builder
description: Turn a natural-language description of a LEGO model into a runnable pyldraw3 Python program and an LDraw .ldr file, verified with a render-and-iterate loop. Use when someone wants to "build a LEGO model", "make an LDraw model of ...", "generate an .ldr / .mpd", or design a brick model (parametric structures like walls/towers/stairs, or freeform objects) as code they can re-run and tweak.
---

# Build a LEGO model from a description

This skill takes a spoken-language model idea and produces two deliverables in
the current directory: a clean, commented **pyldraw3 program** (`<slug>.py`) and
the **LDraw model** it generates (`<slug>.ldr`). It renders the model from
several angles, inspects the images, fixes mistakes, and repeats — so the file
you hand back has actually been looked at, not just written.

It is self-contained: it installs `pyldraw3`, downloads/generates the parts
library, and finds (or installs) an LDraw renderer on its own. It runs with any
compatible coding agent that can execute code locally on Linux or macOS.

Read `references/api-cheatsheet.md` before writing any program — it has the
build API, the coordinate system, and the gotchas. Reach into
`references/palette.md` for the parts and colours to use first.

## Workflow

> **`$SKILL_DIR`** in the commands below means this skill's own directory (the
> folder containing this `SKILL.md`). Set it first so the helpers resolve from
> anywhere, since you run this skill from the user's model output directory:
> `SKILL_DIR=/absolute/path/to/skills/lego-model-builder`.
>
> **`$PYTHON_BIN`** means the interpreter preflight selected. Set it once, the
> same way preflight does:
> `PYTHON_BIN="${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/python}"; PYTHON_BIN="${PYTHON_BIN:-python3}"`.
> Always run the CLI as `"$PYTHON_BIN" -m ldraw.cli ...` so it shares the
> environment pyldraw3 was installed into.

### 1. Preflight the environment

Run the bootstrap and read its status report:

```bash
bash "$SKILL_DIR/scripts/preflight.sh"
```

It is idempotent and prints one line
each for `pyldraw3:`, `library:`, and `renderer:`. It will, only as needed:

- Select Python 3.12+ (an activated virtual environment is authoritative), then
  install pyldraw3 into that exact interpreter if `import ldraw` fails. It uses
  `uv pip --python` when available and interpreter-bound `python -m pip`
  fallbacks, so the generated model programs and the `ldraw` CLI share one
  environment.
- Download + generate the parts library if missing —
  `ldraw download --yes` then `ldraw generate --yes`. This fetches the
  `complete` release (~80 MB) and is **slow on first run**; tell the user it's
  a one-time setup. To trade coverage for speed the user may instead pin a
  smaller release, e.g. `ldraw download --version 2018-02 --yes`.
- Detect a renderer on `PATH` in order `ldview` → `leocad`, and try to install
  one if neither is found (Linux: `leocad` + `xvfb` via apt; macOS: detects
  existing LDView.app/LeoCAD.app bundles and prints how to put them on `PATH` —
  install LDView from https://tcobbs.github.io/ldview/ if absent).

If the report ends with `renderer: NONE`, continue in **validate-only mode**:
you will still generate, validate, and BOM the model, but you cannot see it —
make this limitation explicit to the user at the end.

Never let a missing renderer or a failed install abort the build; degrade and
warn instead.

### 2. Interview the user

Before writing code, pin down what's actually underspecified. Ask only what you
need (skip anything the request already answers):

- **Subject & style** — what is it; realistic vs. stylized; any reference.
- **Size / scale** — rough footprint in studs or bricks, and overall height.
- **Colours** — primary/accent colours (map to `references/palette.md`).
- **Level of detail** — blocky and simple vs. more part variety.
- **Hard constraints** — must sit on a baseplate, symmetry, a parts budget, etc.

For clearly-specified small asks ("a red 4x8 wall three bricks tall"), skip
straight to building.

### 3. Design the build

- Choose parts from `references/palette.md` first — those are common, reliable,
  and predictable. For anything it lacks, find the real code with the CLI:

  ```bash
  "$PYTHON_BIN" -m ldraw.cli parts search "arch 1 x 6"  # code + category + description
  "$PYTHON_BIN" -m ldraw.cli parts info 3455            # code, category, import line
  ```

  Always confirm a code with `parts info` before baking it in.
- Lay out coordinates using the conventions in `references/api-cheatsheet.md`:
  LDraw units (LDU), **`-Y` is up**, brick = 24 LDU tall, plate = 8 LDU, stud
  pitch = 20 LDU. Prefer loops and named constants over hand-placed magic
  numbers — that is what makes the program re-runnable and tweakable.

### 4. Write the program

Write `<slug>.py` (slug = a short kebab-case name from the description, e.g.
`red-castle`). Requirements:

- Use `Piece.place(part, colour=..., position=Vector(...), matrix=...)` and
  assemble a **flat** model with `Model.from_pieces([...], name="<slug>.ldr",
  description=..., author=...)`, then `model.save("<slug>.ldr")`.
- Prefer imported names from `ldraw.library.parts` / `ldraw.library.colours`
  (raw code strings also work as `part=`).
- Comment the structure and expose the key dimensions as top-level constants so
  the user can tweak and re-run. Keep it readable — it is a deliverable.

### 5. Run it

```bash
"$PYTHON_BIN" <slug>.py        # writes <slug>.ldr into the current directory
```

### 6. Verify

```bash
"$PYTHON_BIN" -m ldraw.cli validate <slug>.ldr        # unknown parts/colours, syntax
"$PYTHON_BIN" "$SKILL_DIR/scripts/check_geometry.py" <slug>.ldr  # duplicate / floating pieces
"$PYTHON_BIN" "$SKILL_DIR/scripts/render.py" <slug>.ldr          # front/iso/top PNGs (if a renderer exists)
```

`render.py` writes `<slug>.front.png`, `<slug>.iso.png`, `<slug>.top.png` and
prints the paths. Before replacing requested views, it moves the existing PNGs
into a UTC timestamped directory under `previous/` and prints an `ARCHIVED:`
line for each one. Render history is retained across iterations. **View the new
images** — do not assume the model is correct.

If a re-render exits 1, check its output for `ARCHIVED:` lines. If any were
printed, the prior images were moved into `previous/<timestamp>/` before the
failed render — look there rather than treating the views as lost. If there
are no `ARCHIVED:` lines (bad arguments, missing model, or no renderer), the
prior images are untouched in the working directory.

### 7. Iterate (bounded)

Diagnose what the renders and checks reveal — wrong part, wrong colour,
misaligned studs, floating or overlapping pieces, wrong proportions — edit the
program, and re-run steps 5–6. Cap this at **3–5 render-fix cycles**, then stop
and present the best result even if imperfect (say what's still off).

### 8. Present

- Show the renders.
- Print the bill of materials: `"$PYTHON_BIN" -m ldraw.cli bom <slug>.ldr`.
- Hand over both files: `<slug>.py` (re-runnable, tweak the constants) and
  `<slug>.ldr` (open in any LDraw viewer — LDView, Studio, LeoCAD, Bricklink).
- In validate-only mode, state clearly that the model was **not** visually
  verified and suggest the user open the `.ldr` in a viewer.

## Notes

- Everything lands in the **current working directory**; run the skill from
  wherever the user wants the files.
- The library setup and renderer install touch the user's real machine
  (`~/.config`/`~/.cache`/`~/.local` and package managers) — this is intended
  for an interactive local session, not an isolated CI job.
