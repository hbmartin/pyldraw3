# Curated parts & colours palette

**Reach for these first.** They are the common, geometrically predictable parts
and the standard LEGO colours — using them keeps freeform builds reliable and
avoids obscure-part mistakes. For anything not here, search the full library
(`ldraw parts search "..."`) and confirm the code with `ldraw parts info CODE`.

> Confirm before baking in: the codes below are the canonical LDraw catalog
> codes and the import names follow pyldraw3's naming convention, but the exact
> generated import symbol can vary (variant suffixes like `a`/`b`, spacing). If
> an import fails, run `ldraw parts info CODE` — it prints the exact
> `from ldraw.library.parts... import ...` line — and use the code string
> directly (`Piece.place("3001", ...)`) as a fallback.

Dimensions reminder: brick = 24 LDU tall, plate = 8 LDU, stud pitch = 20 LDU,
`-Y` is up. (See `api-cheatsheet.md`.)

## Bricks (24 LDU tall)

| Code | Part | Import (`ldraw.library.parts`) |
|------|------|-------------------------------|
| 3005 | Brick 1 × 1 | `Brick1X1` |
| 3004 | Brick 1 × 2 | `Brick1X2` |
| 3622 | Brick 1 × 3 | `Brick1X3` |
| 3010 | Brick 1 × 4 | `Brick1X4` |
| 3009 | Brick 1 × 6 | `Brick1X6` |
| 3008 | Brick 1 × 8 | `Brick1X8` |
| 3003 | Brick 2 × 2 | `Brick2X2` |
| 3002 | Brick 2 × 3 | `Brick2X3` |
| 3001 | Brick 2 × 4 | `Brick2X4` |
| 2456 | Brick 2 × 6 | `Brick2X6` |
| 3007 | Brick 2 × 8 | `Brick2X8` |

## Plates (8 LDU tall)

| Code | Part | Import |
|------|------|--------|
| 3024 | Plate 1 × 1 | `Plate1X1` |
| 3023 | Plate 1 × 2 | `Plate1X2` |
| 3623 | Plate 1 × 3 | `Plate1X3` |
| 3710 | Plate 1 × 4 | `Plate1X4` |
| 3666 | Plate 1 × 6 | `Plate1X6` |
| 3460 | Plate 1 × 8 | `Plate1X8` |
| 3022 | Plate 2 × 2 | `Plate2X2` |
| 3021 | Plate 2 × 3 | `Plate2X3` |
| 3020 | Plate 2 × 4 | `Plate2X4` |
| 3795 | Plate 2 × 6 | `Plate2X6` |
| 3034 | Plate 2 × 8 | `Plate2X8` |
| 3031 | Plate 4 × 4 | `Plate4X4` |
| 3032 | Plate 4 × 6 | `Plate4X6` |
| 3035 | Plate 4 × 8 | `Plate4X8` |
| 3958 | Plate 6 × 6 | `Plate6X6` |
| 3036 | Plate 6 × 8 | `Plate6X8` |

## Baseplates (thin, ground)

| Code | Part | Import |
|------|------|--------|
| 3867 | Baseplate 16 × 16 | `Baseplate16X16` |
| 3811 | Baseplate 32 × 32 | `Baseplate32X32` |

## Tiles (smooth top, 8 LDU tall) — confirm variant suffix via `parts info`

| Code | Part |
|------|------|
| 3070b | Tile 1 × 1 |
| 3069b | Tile 1 × 2 |
| 2431 | Tile 1 × 4 |
| 3068b | Tile 2 × 2 |
| 87079 | Tile 2 × 4 |

## Slopes — confirm import name via `parts info`

Variant-suffixed codes (`3040b`, `3665a`, `4032a`, `3794b`) are the 2018-02
catalog names; newer releases may alias the bare code — `parts info` confirms
either way.

| Code | Part |
|------|------|
| 3040b | Slope 45° 2 × 1 |
| 3039 | Slope 45° 2 × 2 |
| 3038 | Slope 45° 2 × 3 |
| 3037 | Slope 45° 2 × 4 |
| 4286 | Slope 33° 3 × 1 |
| 3298 | Slope 33° 3 × 2 |
| 3665a | Slope Inverted 45° 2 × 1 |
| 3660 | Slope Inverted 45° 2 × 2 |

## Round bricks & plates

| Code | Part |
|------|------|
| 3062b | Brick 1 × 1 Round |
| 3941 | Brick 2 × 2 Round |
| 6141 | Plate 1 × 1 Round |
| 4032a | Plate 2 × 2 Round |
| 6143 | Brick 2 × 2 Round (open stud, alt) |

## SNOT / utility (sideways studs, brackets, jumpers)

| Code | Part |
|------|------|
| 4070 | Brick 1 × 1 with Headlight (Erling) — stud on one side |
| 87087 | Brick 1 × 1 with Stud on 1 Side |
| 4733 | Brick 1 × 1 with Studs on 4 Sides |
| 99781 | Bracket 1 × 2 – 1 × 2 |
| 44728 | Bracket 1 × 2 – 2 × 2 |
| 3794b | Plate 1 × 2 with 1 Centre Stud (jumper) |

## Colours

Import from `ldraw.library.colours` (spaces → underscores). Codes shown for the
`colour=<int>` fallback. Greys: the everyday modern greys are the *Bluish* ones;
`Light_Grey`/`Dark_Grey` are the legacy variants.

| Code | Name (import) |
|------|---------------|
| 0 | `Black` |
| 15 | `White` |
| 4 | `Red` |
| 1 | `Blue` |
| 2 | `Green` |
| 14 | `Yellow` |
| 25 | `Orange` |
| 71 | `Light_Bluish_Grey` |
| 72 | `Dark_Bluish_Grey` |
| 7 | `Light_Grey` (legacy) |
| 8 | `Dark_Grey` (legacy) |
| 70 | `Reddish_Brown` |
| 6 | `Brown` |
| 19 | `Tan` |
| 28 | `Dark_Tan` |
| 320 | `Dark_Red` |
| 484 | `Dark_Orange` |
| 10 | `Bright_Green` |
| 288 | `Dark_Green` |
| 272 | `Dark_Blue` |
| 85 | `Medium_Lilac` |
| 191 | `Bright_Light_Orange` |
| 226 | `Bright_Light_Yellow` |
| 47 | `Trans_Clear` |
| 36 | `Trans_Red` |

To list exactly what the generated library provides:

```bash
python -c "from ldraw.library.colours import ColoursByName; print(', '.join(sorted(ColoursByName)))"
```

Custom/direct colour (no name needed): `from ldraw import Colour;
Piece.place(part, colour=Colour(rgb='#4C9F70'))`.
