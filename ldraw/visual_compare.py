"""Register and compare LDraw renders with raster reference images.

The module intentionally treats rendering and image comparison as separate
steps.  It can render a reproducible LeoCAD camera sweep, but it can also rank
PNGs created by LDView, Blender, or any other renderer.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageColor, ImageDraw

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

Mask = NDArray[np.bool_]
RgbArray = NDArray[np.uint8]
Box = tuple[int, int, int, int]

DEFAULT_BACKGROUND_TOLERANCE = 24.0
DEFAULT_SCALE_MIN = 0.65
DEFAULT_SCALE_MAX = 1.45
DEFAULT_SCALE_STEPS = 41


@dataclass(frozen=True, slots=True)
class AlignmentConfig:
    """Search bounds and silhouette extraction settings."""

    min_scale: float = DEFAULT_SCALE_MIN
    max_scale: float = DEFAULT_SCALE_MAX
    scale_steps: int = DEFAULT_SCALE_STEPS
    background_tolerance: float = DEFAULT_BACKGROUND_TOLERANCE
    alpha_threshold: int = 16

    def __post_init__(self) -> None:
        """Validate settings early so failed sweeps do not render images."""
        if self.min_scale <= 0:
            msg = "min_scale must be positive"
            raise ValueError(msg)
        if self.max_scale < self.min_scale:
            msg = "max_scale must not be less than min_scale"
            raise ValueError(msg)
        if self.scale_steps < 1:
            msg = "scale_steps must be at least one"
            raise ValueError(msg)
        if self.background_tolerance < 0:
            msg = "background_tolerance must not be negative"
            raise ValueError(msg)
        if not 0 <= self.alpha_threshold <= 255:
            msg = "alpha_threshold must be between 0 and 255"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Region:
    """A named pixel or normalized image crop."""

    name: str
    box: tuple[float, float, float, float]
    relative: bool = True

    def resolve(self, size: tuple[int, int]) -> Box:
        """Resolve the region to a non-empty box clipped to ``size``."""
        width, height = size
        x, y, region_width, region_height = self.box
        if self.relative:
            x *= width
            region_width *= width
            y *= height
            region_height *= height
        left = max(0, min(width, round(x)))
        top = max(0, min(height, round(y)))
        right = max(left, min(width, round(x + region_width)))
        bottom = max(top, min(height, round(y + region_height)))
        if left == right or top == bottom:
            msg = f"region {self.name!r} resolves to an empty crop"
            raise ValueError(msg)
        return left, top, right, bottom


@dataclass(frozen=True, slots=True)
class Camera:
    """One LeoCAD camera orientation in degrees."""

    latitude: float
    longitude: float

    @property
    def key(self) -> str:
        """Return a stable filesystem-safe orientation key."""
        return f"lat_{_angle_key(self.latitude)}_lon_{_angle_key(self.longitude)}"


@dataclass(frozen=True, slots=True)
class Alignment:
    """Scale and placement of the candidate foreground on the reference."""

    scale: float
    offset_x: int
    offset_y: int
    source_box: Box
    scaled_width: int
    scaled_height: int
    silhouette_iou: float


@dataclass(slots=True)
class Comparison:
    """An in-memory registered image pair and its quantitative metrics."""

    reference: Image.Image
    candidate: Image.Image
    reference_mask: Mask
    candidate_mask: Mask
    alignment: Alignment
    metrics: dict[str, float]
    regions: dict[str, dict[str, float]] = field(default_factory=dict)


def _angle_key(value: float) -> str:
    """Encode a signed angle without punctuation that varies by platform."""
    sign = "p" if value >= 0 else "m"
    magnitude = f"{abs(value):06.2f}".replace(".", "d")
    return f"{sign}{magnitude}"


def parse_number_list(value: str) -> list[float]:
    """Parse a comma-separated list of finite numbers."""
    try:
        numbers = [float(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        msg = f"expected comma-separated numbers, got {value!r}"
        raise argparse.ArgumentTypeError(msg) from exc
    if not numbers or not all(math.isfinite(number) for number in numbers):
        msg = f"expected one or more finite numbers, got {value!r}"
        raise argparse.ArgumentTypeError(msg)
    return numbers


def camera_grid(
    latitudes: Iterable[float],
    longitudes: Iterable[float],
) -> list[Camera]:
    """Return the Cartesian product of camera latitudes and longitudes."""
    return [
        Camera(latitude=latitude, longitude=longitude)
        for latitude in latitudes
        for longitude in longitudes
    ]


def load_image(path: Path) -> Image.Image:
    """Load an image as detached RGBA pixels."""
    with Image.open(path) as image:
        return image.convert("RGBA")


def _border_pixels(rgb: RgbArray) -> RgbArray:
    """Collect all border pixels once, without duplicated corners."""
    if rgb.shape[0] == 1 or rgb.shape[1] == 1:
        return rgb.reshape((-1, 3))
    return np.concatenate(
        (
            rgb[0, :, :],
            rgb[-1, :, :],
            rgb[1:-1, 0, :],
            rgb[1:-1, -1, :],
        ),
    )


def estimate_background(image: Image.Image) -> tuple[int, int, int]:
    """Estimate a flat background colour from the median border colour."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    median = np.median(_border_pixels(rgb), axis=0)
    return cast("tuple[int, int, int]", tuple(round(float(value)) for value in median))


def foreground_mask(
    image: Image.Image,
    *,
    background_tolerance: float = DEFAULT_BACKGROUND_TOLERANCE,
    alpha_threshold: int = 16,
) -> Mask:
    """Extract foreground using useful alpha or distance from border colour.

    A PNG with any transparency uses its alpha channel.  Fully opaque images
    use the median border colour as a background estimate, which works well for
    the flat backgrounds normally produced by LDraw renderers and product art.
    """
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    alpha = rgba[:, :, 3]
    if np.any(alpha < 255):
        return alpha > alpha_threshold

    background = np.asarray(estimate_background(image), dtype=np.int32)
    delta = rgba[:, :, :3].astype(np.int32) - background
    squared_distance = np.sum(delta * delta, axis=2, dtype=np.int32)
    return squared_distance > background_tolerance**2


def mask_box(mask: Mask) -> Box:
    """Return the tight non-empty bounding box of a silhouette."""
    rows, columns = np.nonzero(mask)
    if rows.size == 0:
        msg = "image has no detectable foreground"
        raise ValueError(msg)
    return (
        int(columns.min()),
        int(rows.min()),
        int(columns.max()) + 1,
        int(rows.max()) + 1,
    )


def _scale_values(config: AlignmentConfig) -> NDArray[np.float64]:
    """Return inclusive candidate scales."""
    if config.scale_steps == 1:
        return np.asarray([config.min_scale], dtype=np.float64)
    return np.linspace(
        config.min_scale,
        config.max_scale,
        num=config.scale_steps,
        dtype=np.float64,
    )


def _resize_mask(mask: Mask, size: tuple[int, int]) -> Mask:
    """Resize a boolean mask without introducing anti-aliasing."""
    source = Image.fromarray(mask.astype(np.uint8) * 255)
    resized = source.resize(size, resample=Image.Resampling.NEAREST)
    return np.asarray(resized, dtype=np.uint8) > 0


def _best_placement(reference: Mask, candidate: Mask) -> tuple[int, int, int]:
    """Find the in-canvas translation with maximum silhouette intersection."""
    reference_height, reference_width = reference.shape
    candidate_height, candidate_width = candidate.shape
    if candidate_height > reference_height or candidate_width > reference_width:
        msg = "scaled candidate does not fit inside the reference canvas"
        raise ValueError(msg)

    convolution_shape = (
        reference_height + candidate_height - 1,
        reference_width + candidate_width - 1,
    )
    reference_fft = np.fft.rfft2(reference, s=convolution_shape)
    candidate_fft = np.fft.rfft2(candidate[::-1, ::-1], s=convolution_shape)
    correlation = np.fft.irfft2(
        reference_fft * candidate_fft,
        s=convolution_shape,
    )
    valid = correlation[
        candidate_height - 1 : reference_height,
        candidate_width - 1 : reference_width,
    ]
    flat_index = int(np.argmax(valid))
    y, x = np.unravel_index(flat_index, valid.shape)
    intersection = round(float(valid[y, x]))
    return int(x), int(y), intersection


def register_silhouettes(
    reference_mask: Mask,
    candidate_mask: Mask,
    *,
    config: AlignmentConfig | None = None,
) -> Alignment:
    """Fit candidate scale and translation by maximizing silhouette IoU."""
    settings = config or AlignmentConfig()
    source_box = mask_box(candidate_mask)
    left, top, right, bottom = source_box
    cropped = candidate_mask[top:bottom, left:right]
    reference_area = int(reference_mask.sum())
    if reference_area == 0:
        msg = "reference image has no detectable foreground"
        raise ValueError(msg)

    best: Alignment | None = None
    for scale_value in _scale_values(settings):
        scale = float(scale_value)
        scaled_width = max(1, round(cropped.shape[1] * scale))
        scaled_height = max(1, round(cropped.shape[0] * scale))
        if (
            scaled_width > reference_mask.shape[1]
            or scaled_height > reference_mask.shape[0]
        ):
            continue
        scaled = _resize_mask(cropped, (scaled_width, scaled_height))
        offset_x, offset_y, intersection = _best_placement(reference_mask, scaled)
        candidate_area = int(scaled.sum())
        union = reference_area + candidate_area - intersection
        iou = intersection / union if union else 1.0
        alignment = Alignment(
            scale=scale,
            offset_x=offset_x,
            offset_y=offset_y,
            source_box=source_box,
            scaled_width=scaled_width,
            scaled_height=scaled_height,
            silhouette_iou=iou,
        )
        if best is None or alignment.silhouette_iou > best.silhouette_iou:
            best = alignment

    if best is None:
        msg = "no configured scale fits the candidate inside the reference canvas"
        raise ValueError(msg)
    return best


def apply_alignment(
    candidate: Image.Image,
    candidate_mask: Mask,
    alignment: Alignment,
    canvas_size: tuple[int, int],
) -> tuple[Image.Image, Mask]:
    """Apply a registration and return transparent RGBA plus its silhouette."""
    source = candidate.convert("RGBA").crop(alignment.source_box)
    source_mask = candidate_mask[
        alignment.source_box[1] : alignment.source_box[3],
        alignment.source_box[0] : alignment.source_box[2],
    ]
    scaled_size = (alignment.scaled_width, alignment.scaled_height)
    source = source.resize(scaled_size, resample=Image.Resampling.LANCZOS)
    scaled_mask = _resize_mask(source_mask, scaled_size)

    source_array = np.asarray(source, dtype=np.uint8).copy()
    source_array[:, :, 3] = scaled_mask.astype(np.uint8) * 255
    foreground = Image.fromarray(source_array)
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    canvas.alpha_composite(
        foreground,
        dest=(alignment.offset_x, alignment.offset_y),
    )
    canvas_mask = np.zeros((canvas_size[1], canvas_size[0]), dtype=np.bool_)
    y_slice = slice(alignment.offset_y, alignment.offset_y + alignment.scaled_height)
    x_slice = slice(alignment.offset_x, alignment.offset_x + alignment.scaled_width)
    canvas_mask[y_slice, x_slice] = scaled_mask
    return canvas, canvas_mask


def image_metrics(
    reference: Image.Image,
    candidate: Image.Image,
    reference_mask: Mask,
    candidate_mask: Mask,
) -> dict[str, float]:
    """Calculate silhouette and foreground colour metrics."""
    intersection = reference_mask & candidate_mask
    union = reference_mask | candidate_mask
    reference_area = int(reference_mask.sum())
    candidate_area = int(candidate_mask.sum())
    intersection_area = int(intersection.sum())
    union_area = int(union.sum())
    precision = intersection_area / candidate_area if candidate_area else 0.0
    recall = intersection_area / reference_area if reference_area else 0.0
    dice_denominator = reference_area + candidate_area

    reference_rgb = np.asarray(reference.convert("RGB"), dtype=np.float64)
    candidate_rgb = np.asarray(candidate.convert("RGB"), dtype=np.float64)
    if intersection_area:
        colour_delta = (
            reference_rgb[intersection] - candidate_rgb[intersection]
        ) / 255.0
        rgb_mae = float(np.mean(np.abs(colour_delta)))
        rgb_rmse = float(np.sqrt(np.mean(colour_delta**2)))
    else:
        rgb_mae = 1.0
        rgb_rmse = 1.0

    return {
        "silhouette_iou": intersection_area / union_area if union_area else 1.0,
        "silhouette_dice": (
            2 * intersection_area / dice_denominator if dice_denominator else 1.0
        ),
        "silhouette_precision": precision,
        "silhouette_recall": recall,
        "foreground_area_ratio": (
            candidate_area / reference_area if reference_area else 0.0
        ),
        "rgb_mae": rgb_mae,
        "rgb_rmse": rgb_rmse,
    }


def compare(
    reference: Image.Image,
    candidate: Image.Image,
    *,
    config: AlignmentConfig | None = None,
    regions: Sequence[Region] = (),
) -> Comparison:
    """Register and compare two images without writing artifacts."""
    settings = config or AlignmentConfig()
    reference = reference.convert("RGBA")
    candidate = candidate.convert("RGBA")
    reference_mask = foreground_mask(
        reference,
        background_tolerance=settings.background_tolerance,
        alpha_threshold=settings.alpha_threshold,
    )
    raw_candidate_mask = foreground_mask(
        candidate,
        background_tolerance=settings.background_tolerance,
        alpha_threshold=settings.alpha_threshold,
    )
    alignment = register_silhouettes(
        reference_mask,
        raw_candidate_mask,
        config=settings,
    )
    aligned_candidate, candidate_mask = apply_alignment(
        candidate,
        raw_candidate_mask,
        alignment,
        reference.size,
    )
    metrics = image_metrics(
        reference,
        aligned_candidate,
        reference_mask,
        candidate_mask,
    )
    region_metrics: dict[str, dict[str, float]] = {}
    for region in regions:
        box = region.resolve(reference.size)
        left, top, right, bottom = box
        region_metrics[region.name] = image_metrics(
            reference.crop(box),
            aligned_candidate.crop(box),
            reference_mask[top:bottom, left:right],
            candidate_mask[top:bottom, left:right],
        )
    return Comparison(
        reference=reference,
        candidate=aligned_candidate,
        reference_mask=reference_mask,
        candidate_mask=candidate_mask,
        alignment=alignment,
        metrics=metrics,
        regions=region_metrics,
    )


def overlay_image(result: Comparison) -> Image.Image:
    """Create an overlay with reference-only red and candidate-only cyan."""
    reference_rgb = np.asarray(result.reference.convert("RGB"), dtype=np.uint8)
    overlay = (reference_rgb.astype(np.float64) * 0.30).astype(np.uint8)
    reference_only = result.reference_mask & ~result.candidate_mask
    candidate_only = result.candidate_mask & ~result.reference_mask
    intersection = result.reference_mask & result.candidate_mask
    overlay[reference_only] = (255, 64, 64)
    overlay[candidate_only] = (0, 220, 255)
    blended = np.asarray(result.candidate.convert("RGB"), dtype=np.uint8)
    overlay[intersection] = (
        reference_rgb[intersection].astype(np.uint16)
        + blended[intersection].astype(np.uint16)
    ) // 2
    return Image.fromarray(overlay)


def difference_heatmap(result: Comparison) -> Image.Image:
    """Create a black-to-red-to-yellow normalized difference heatmap."""
    reference_rgb = np.asarray(result.reference.convert("RGB"), dtype=np.float64)
    candidate_rgb = np.asarray(result.candidate.convert("RGB"), dtype=np.float64)
    intersection = result.reference_mask & result.candidate_mask
    mismatch = result.reference_mask ^ result.candidate_mask
    error = np.zeros(result.reference_mask.shape, dtype=np.float64)
    error[intersection] = (
        np.mean(
            np.abs(reference_rgb[intersection] - candidate_rgb[intersection]),
            axis=1,
        )
        / 255.0
    )
    error[mismatch] = 1.0
    heatmap = np.zeros((*error.shape, 3), dtype=np.uint8)
    heatmap[:, :, 0] = np.clip(error * 510, 0, 255).astype(np.uint8)
    heatmap[:, :, 1] = np.clip((error - 0.5) * 510, 0, 255).astype(np.uint8)
    return Image.fromarray(heatmap)


def write_comparison_artifacts(
    result: Comparison,
    output_dir: Path,
    *,
    regions: Sequence[Region] = (),
) -> dict[str, object]:
    """Write aligned, overlay, heatmap, and optional crop images."""
    output_dir.mkdir(parents=True, exist_ok=True)
    background = estimate_background(result.reference)
    aligned = Image.new("RGBA", result.reference.size, (*background, 255))
    aligned.alpha_composite(result.candidate)
    aligned.convert("RGB").save(output_dir / "aligned.png")
    overlay = overlay_image(result)
    overlay.save(output_dir / "overlay.png")
    difference = difference_heatmap(result)
    difference.save(output_dir / "difference.png")

    region_outputs: dict[str, dict[str, str]] = {}
    for region in regions:
        box = region.resolve(result.reference.size)
        safe_name = _safe_name(region.name)
        paths = {
            "reference": f"regions/{safe_name}.reference.png",
            "aligned": f"regions/{safe_name}.aligned.png",
            "overlay": f"regions/{safe_name}.overlay.png",
            "difference": f"regions/{safe_name}.difference.png",
        }
        for path in paths.values():
            (output_dir / path).parent.mkdir(parents=True, exist_ok=True)
        result.reference.crop(box).convert("RGB").save(
            output_dir / paths["reference"],
        )
        aligned.crop(box).convert("RGB").save(output_dir / paths["aligned"])
        overlay.crop(box).save(output_dir / paths["overlay"])
        difference.crop(box).save(output_dir / paths["difference"])
        region_outputs[region.name] = paths

    return {
        "alignment": asdict(result.alignment),
        "metrics": result.metrics,
        "regions": {
            name: {
                "metrics": result.regions[name],
                "artifacts": region_outputs[name],
            }
            for name in result.regions
        },
        "artifacts": {
            "aligned": "aligned.png",
            "overlay": "overlay.png",
            "difference": "difference.png",
        },
    }


def _safe_name(value: str) -> str:
    """Return a stable conservative path segment."""
    safe = "".join(character if character.isalnum() else "-" for character in value)
    return safe.strip("-") or "item"


def _write_json(path: Path, payload: object) -> None:
    """Write deterministic, human-readable JSON."""
    path.write_text(
        f"{json.dumps(payload, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


def compare_paths(
    reference_path: Path,
    candidate_path: Path,
    output_dir: Path,
    *,
    config: AlignmentConfig | None = None,
    regions: Sequence[Region] = (),
) -> dict[str, object]:
    """Compare two filesystem images and write all standard artifacts."""
    result = compare(
        load_image(reference_path),
        load_image(candidate_path),
        config=config,
        regions=regions,
    )
    payload = write_comparison_artifacts(result, output_dir, regions=regions)
    payload.update(
        {
            "reference": str(reference_path.resolve()),
            "candidate": str(candidate_path.resolve()),
        },
    )
    _write_json(output_dir / "comparison.json", payload)
    return payload


def rank_candidates(
    reference_path: Path,
    candidates: Sequence[Path],
    *,
    config: AlignmentConfig | None = None,
) -> list[dict[str, object]]:
    """Register and rank candidates by silhouette IoU, then RGB error."""
    reference = load_image(reference_path)
    rows: list[dict[str, object]] = []
    for candidate_path in candidates:
        result = compare(
            reference,
            load_image(candidate_path),
            config=config,
        )
        rows.append(
            {
                "candidate": str(candidate_path.resolve()),
                "alignment": asdict(result.alignment),
                "metrics": result.metrics,
            },
        )
    rows.sort(
        key=lambda row: (
            -cast("dict[str, float]", row["metrics"])["silhouette_iou"],
            cast("dict[str, float]", row["metrics"])["rgb_mae"],
            cast("str", row["candidate"]),
        ),
    )
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def render_leocad_grid(  # noqa: PLR0913
    model: Path,
    output_dir: Path,
    cameras: Sequence[Camera],
    *,
    size: tuple[int, int] = (1024, 1024),
    executable: str = "leocad",
    skip_existing: bool = False,
    timeout_seconds: int = 240,
) -> list[dict[str, object]]:
    """Render one PNG for each camera using LeoCAD's command-line mode."""
    if not model.is_file():
        msg = f"model not found: {model}"
        raise FileNotFoundError(msg)
    resolved_executable = shutil.which(executable)
    if resolved_executable is None:
        msg = f"LeoCAD executable not found: {executable}"
        raise FileNotFoundError(msg)
    width, height = size
    if width <= 0 or height <= 0:
        msg = "render size must be positive"
        raise ValueError(msg)
    output_dir.mkdir(parents=True, exist_ok=True)
    renders: list[dict[str, object]] = []
    for camera in cameras:
        output = output_dir / f"{camera.key}.png"
        command = [
            resolved_executable,
            str(model.resolve()),
            "--image",
            str(output.resolve()),
            "--width",
            str(width),
            "--height",
            str(height),
            "--camera-angles",
            str(camera.latitude),
            str(camera.longitude),
        ]
        if not (skip_existing and output.is_file()):
            try:
                process = subprocess.run(  # noqa: S603
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                msg = f"LeoCAD timed out after {timeout_seconds}s for {camera.key}"
                raise RuntimeError(msg) from exc
            if process.returncode != 0 or not output.is_file():
                detail = (process.stderr or process.stdout).strip()
                msg = f"LeoCAD failed for {camera.key}: {detail or 'no image written'}"
                raise RuntimeError(msg)
        renders.append(
            {
                "camera": asdict(camera),
                "key": camera.key,
                "path": str(output.resolve()),
                "command": command,
            },
        )
    return renders


def write_contact_sheet(
    rows: Sequence[Mapping[str, object]],
    output: Path,
    *,
    thumbnail_size: tuple[int, int] = (240, 180),
    columns: int = 4,
) -> None:
    """Write a labelled candidate sheet in the supplied row order."""
    if columns < 1:
        msg = "columns must be positive"
        raise ValueError(msg)
    cell_width, cell_height = thumbnail_size
    label_height = 28
    row_count = max(1, math.ceil(len(rows) / columns))
    sheet = Image.new(
        "RGB",
        (columns * cell_width, row_count * (cell_height + label_height)),
        ImageColor.getrgb("#20242b"),
    )
    draw = ImageDraw.Draw(sheet)
    for index, row in enumerate(rows):
        column = index % columns
        grid_row = index // columns
        left = column * cell_width
        top = grid_row * (cell_height + label_height)
        candidate = Path(cast("str", row["candidate"]))
        with Image.open(candidate) as image:
            thumbnail = image.convert("RGB")
            thumbnail.thumbnail(thumbnail_size, resample=Image.Resampling.LANCZOS)
        image_x = left + (cell_width - thumbnail.width) // 2
        image_y = top + (cell_height - thumbnail.height) // 2
        sheet.paste(thumbnail, (image_x, image_y))
        rank = row.get("rank", index + 1)
        metrics = cast("Mapping[str, float]", row.get("metrics", {}))
        score = metrics.get("silhouette_iou")
        label = f"#{rank} {candidate.stem}"
        if score is not None:
            label = f"{label}  IoU {score:.3f}"
        draw.text((left + 6, top + cell_height + 6), label, fill="white")
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def _parse_size(value: str) -> tuple[int, int]:
    """Parse a positive WIDTHxHEIGHT value for argparse."""
    try:
        width_text, height_text = value.lower().split("x", 1)
        width, height = int(width_text), int(height_text)
    except ValueError as exc:
        msg = f"expected WIDTHxHEIGHT, got {value!r}"
        raise argparse.ArgumentTypeError(msg) from exc
    if width <= 0 or height <= 0:
        msg = f"expected positive WIDTHxHEIGHT, got {value!r}"
        raise argparse.ArgumentTypeError(msg)
    return width, height


def _regions_from_json(value: object) -> list[Region]:
    """Parse regions from a JSON-compatible list."""
    if value is None:
        return []
    if not isinstance(value, list):
        msg = "regions must be a list"
        raise TypeError(msg)
    regions: list[Region] = []
    for item in value:
        if not isinstance(item, dict):
            msg = "each region must be an object"
            raise TypeError(msg)
        name = item.get("name")
        box = item.get("box")
        if not isinstance(name, str) or not (
            isinstance(box, list)
            and len(box) == 4
            and all(isinstance(number, int | float) for number in box)
        ):
            msg = "each region needs a string name and four-number box"
            raise TypeError(msg)
        relative = item.get("relative", True)
        if not isinstance(relative, bool):
            msg = "region relative must be a boolean"
            raise TypeError(msg)
        regions.append(
            Region(
                name=name,
                box=cast(
                    "tuple[float, float, float, float]",
                    tuple(float(number) for number in cast("list[int | float]", box)),
                ),
                relative=relative,
            ),
        )
    return regions


def _config_from_mapping(value: object) -> AlignmentConfig:
    """Parse alignment settings from a JSON object."""
    if value is None:
        return AlignmentConfig()
    if not isinstance(value, dict):
        msg = "alignment must be an object"
        raise TypeError(msg)
    known = {
        "min_scale",
        "max_scale",
        "scale_steps",
        "background_tolerance",
        "alpha_threshold",
    }
    unknown = set(value) - known
    if unknown:
        msg = f"unknown alignment settings: {', '.join(sorted(unknown))}"
        raise ValueError(msg)
    return AlignmentConfig(
        min_scale=cast("float", value.get("min_scale", DEFAULT_SCALE_MIN)),
        max_scale=cast("float", value.get("max_scale", DEFAULT_SCALE_MAX)),
        scale_steps=cast("int", value.get("scale_steps", DEFAULT_SCALE_STEPS)),
        background_tolerance=cast(
            "float",
            value.get("background_tolerance", DEFAULT_BACKGROUND_TOLERANCE),
        ),
        alpha_threshold=cast("int", value.get("alpha_threshold", 16)),
    )


def _candidate_specs(value: object) -> list[tuple[str, str]]:
    """Normalize manifest candidate strings or labelled objects."""
    raw_items = value if isinstance(value, list) else [value]
    candidates: list[tuple[str, str]] = []
    for item in raw_items:
        if isinstance(item, str):
            candidates.append((Path(item).stem, item))
        elif isinstance(item, dict):
            label = item.get("label")
            path = item.get("path")
            if not isinstance(label, str) or not isinstance(path, str):
                msg = "candidate objects need string label and path fields"
                raise TypeError(msg)
            candidates.append((label, path))
        else:
            msg = "candidate must be a path or list of paths/objects"
            raise TypeError(msg)
    return candidates


def build_report(manifest_path: Path, output_dir: Path) -> dict[str, object]:
    """Build comparison artifacts and aggregate metrics for several views."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("views"), list):
        msg = "manifest must be an object with a views list"
        raise TypeError(msg)
    config = _config_from_mapping(manifest.get("alignment"))
    manifest_dir = manifest_path.resolve().parent
    output_dir.mkdir(parents=True, exist_ok=True)
    report_views: list[dict[str, object]] = []
    all_metrics: list[dict[str, float]] = []

    for view_item in cast("list[object]", manifest["views"]):
        if not isinstance(view_item, dict):
            msg = "each view must be an object"
            raise TypeError(msg)
        name = view_item.get("name")
        reference_value = view_item.get("reference")
        candidates_value = view_item.get("candidates", view_item.get("candidate"))
        if not isinstance(name, str) or not isinstance(reference_value, str):
            msg = "each view needs string name and reference fields"
            raise TypeError(msg)
        if candidates_value is None:
            msg = f"view {name!r} needs candidate or candidates"
            raise ValueError(msg)
        reference_path = (manifest_dir / reference_value).resolve()
        regions = _regions_from_json(view_item.get("regions"))
        view_rows: list[dict[str, object]] = []
        for label, candidate_value in _candidate_specs(candidates_value):
            candidate_path = (manifest_dir / candidate_value).resolve()
            relative_dir = Path("views") / _safe_name(name) / _safe_name(label)
            row = compare_paths(
                reference_path,
                candidate_path,
                output_dir / relative_dir,
                config=config,
                regions=regions,
            )
            row["name"] = label
            row["output_dir"] = relative_dir.as_posix()
            view_rows.append(row)
            all_metrics.append(cast("dict[str, float]", row["metrics"]))
        view_rows.sort(
            key=lambda row: (
                -cast("dict[str, float]", row["metrics"])["silhouette_iou"],
                cast("dict[str, float]", row["metrics"])["rgb_mae"],
            ),
        )
        for rank, row in enumerate(view_rows, start=1):
            row["rank"] = rank
        report_views.append(
            {
                "name": name,
                "reference": str(reference_path),
                "comparisons": view_rows,
            },
        )

    metric_names = sorted(all_metrics[0]) if all_metrics else []
    aggregate = {
        f"mean_{metric}": sum(row[metric] for row in all_metrics) / len(all_metrics)
        for metric in metric_names
    }
    report: dict[str, object] = {
        "manifest": str(manifest_path.resolve()),
        "alignment": asdict(config),
        "aggregate": aggregate,
        "views": report_views,
    }
    _write_json(output_dir / "report.json", report)
    (output_dir / "report.html").write_text(
        _report_html(report),
        encoding="utf-8",
    )
    return report


def _metric_cell(metrics: Mapping[str, float], name: str) -> str:
    """Format one metric as a compact HTML table cell."""
    return f"<td>{metrics[name]:.4f}</td>"


def _report_html(report: Mapping[str, object]) -> str:
    """Render a dependency-free HTML report with linked artifacts."""
    rows: list[str] = []
    views = cast("Sequence[Mapping[str, object]]", report["views"])
    for view in views:
        comparisons = cast("Sequence[Mapping[str, object]]", view["comparisons"])
        for comparison_row in comparisons:
            metrics = cast("Mapping[str, float]", comparison_row["metrics"])
            output_dir = cast("str", comparison_row["output_dir"])
            artifacts = cast("Mapping[str, str]", comparison_row["artifacts"])
            links = " ".join(
                f'<a href="{html.escape(f"{output_dir}/{path}")}">{label}</a>'
                for label, path in artifacts.items()
            )
            rows.append(
                "<tr>"
                f"<td>{html.escape(cast('str', view['name']))}</td>"
                f"<td>{comparison_row['rank']}</td>"
                f"<td>{html.escape(cast('str', comparison_row['name']))}</td>"
                f"{_metric_cell(metrics, 'silhouette_iou')}"
                f"{_metric_cell(metrics, 'silhouette_dice')}"
                f"{_metric_cell(metrics, 'rgb_mae')}"
                f"{_metric_cell(metrics, 'rgb_rmse')}"
                f"<td>{links}</td>"
                "</tr>"
            )
    aggregate = cast("Mapping[str, float]", report["aggregate"])
    aggregate_items = " ".join(
        f"<li><strong>{html.escape(name)}</strong>: {value:.4f}</li>"
        for name, value in aggregate.items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LDraw visual comparison</title>
<style>
body {{ font: 14px system-ui, sans-serif; margin: 2rem; color: #1f2937; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 1px solid #d1d5db; padding: .55rem; text-align: left; }}
th {{ background: #f3f4f6; }}
a {{ margin-right: .5rem; }}
ul {{ columns: 2; }}
</style>
</head>
<body>
<h1>LDraw visual comparison</h1>
<h2>Aggregate</h2><ul>{aggregate_items}</ul>
<h2>Views</h2>
<table>
<thead><tr><th>View</th><th>Rank</th><th>Candidate</th><th>IoU</th>
<th>Dice</th><th>RGB MAE</th><th>RGB RMSE</th><th>Artifacts</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
</body>
</html>
"""


def _alignment_from_args(args: argparse.Namespace) -> AlignmentConfig:
    """Build settings shared by CLI commands."""
    return AlignmentConfig(
        min_scale=args.min_scale,
        max_scale=args.max_scale,
        scale_steps=args.scale_steps,
        background_tolerance=args.background_tolerance,
        alpha_threshold=args.alpha_threshold,
    )


def _add_alignment_arguments(parser: argparse.ArgumentParser) -> None:
    """Add shared silhouette registration arguments."""
    parser.add_argument("--min-scale", type=float, default=DEFAULT_SCALE_MIN)
    parser.add_argument("--max-scale", type=float, default=DEFAULT_SCALE_MAX)
    parser.add_argument("--scale-steps", type=int, default=DEFAULT_SCALE_STEPS)
    parser.add_argument(
        "--background-tolerance",
        type=float,
        default=DEFAULT_BACKGROUND_TOLERANCE,
    )
    parser.add_argument("--alpha-threshold", type=int, default=16)


def _parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="ldraw-compare",
        description="Register and compare LDraw renders with raster references.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare_parser = subparsers.add_parser("compare", help="compare one image pair")
    compare_parser.add_argument("reference", type=Path)
    compare_parser.add_argument("candidate", type=Path)
    compare_parser.add_argument("--output-dir", type=Path, required=True)
    compare_parser.add_argument(
        "--regions",
        type=Path,
        help="JSON file containing a list of named crop objects",
    )
    _add_alignment_arguments(compare_parser)

    rank_parser = subparsers.add_parser("rank", help="rank existing candidate PNGs")
    rank_parser.add_argument("reference", type=Path)
    rank_parser.add_argument("candidates", nargs="+", type=Path)
    rank_parser.add_argument("--output-dir", type=Path, required=True)
    rank_parser.add_argument("--columns", type=int, default=4)
    _add_alignment_arguments(rank_parser)

    grid_parser = subparsers.add_parser(
        "camera-grid",
        help="render and optionally rank a LeoCAD camera sweep",
    )
    grid_parser.add_argument("model", type=Path)
    grid_parser.add_argument("--output-dir", type=Path, required=True)
    grid_parser.add_argument("--reference", type=Path)
    grid_parser.add_argument(
        "--latitudes",
        type=parse_number_list,
        default=parse_number_list("15,25,35"),
    )
    grid_parser.add_argument(
        "--longitudes",
        type=parse_number_list,
        default=parse_number_list("-60,-45,-30"),
    )
    grid_parser.add_argument("--size", type=_parse_size, default=(1024, 1024))
    grid_parser.add_argument("--leocad", default="leocad")
    grid_parser.add_argument("--skip-existing", action="store_true")
    grid_parser.add_argument("--columns", type=int, default=4)
    _add_alignment_arguments(grid_parser)

    report_parser = subparsers.add_parser(
        "report",
        help="compare all views in a JSON manifest",
    )
    report_parser.add_argument("manifest", type=Path)
    report_parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def _run_compare(args: argparse.Namespace) -> None:
    """Execute the compare CLI command."""
    regions: list[Region] = []
    if args.regions is not None:
        regions = _regions_from_json(
            json.loads(args.regions.read_text(encoding="utf-8")),
        )
    payload = compare_paths(
        args.reference,
        args.candidate,
        args.output_dir,
        config=_alignment_from_args(args),
        regions=regions,
    )
    print(json.dumps(payload["metrics"], sort_keys=True))


def _run_rank(args: argparse.Namespace) -> None:
    """Execute the rank CLI command."""
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = rank_candidates(
        args.reference,
        args.candidates,
        config=_alignment_from_args(args),
    )
    _write_json(args.output_dir / "ranking.json", rows)
    write_contact_sheet(
        rows,
        args.output_dir / "ranking.png",
        columns=args.columns,
    )
    print(f"ranked {len(rows)} candidates; best: {rows[0]['candidate']}")


def _run_camera_grid(args: argparse.Namespace) -> None:
    """Execute the camera-grid CLI command."""
    cameras = camera_grid(args.latitudes, args.longitudes)
    renders = render_leocad_grid(
        args.model,
        args.output_dir,
        cameras,
        size=args.size,
        executable=args.leocad,
        skip_existing=args.skip_existing,
    )
    payload: dict[str, object] = {
        "model": str(args.model.resolve()),
        "renders": renders,
    }
    if args.reference is not None:
        rows = rank_candidates(
            args.reference,
            [Path(cast("str", render["path"])) for render in renders],
            config=_alignment_from_args(args),
        )
        cameras_by_path = {
            cast("str", render["path"]): render["camera"] for render in renders
        }
        for row in rows:
            row["camera"] = cameras_by_path[cast("str", row["candidate"])]
        payload["reference"] = str(args.reference.resolve())
        payload["ranking"] = rows
        write_contact_sheet(
            rows,
            args.output_dir / "camera-grid.png",
            columns=args.columns,
        )
    _write_json(args.output_dir / "camera-grid.json", payload)
    print(f"rendered {len(renders)} camera views")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the visual-comparison CLI and return a process exit code."""
    args = _parser().parse_args(argv)
    try:
        match args.command:
            case "compare":
                _run_compare(args)
            case "rank":
                _run_rank(args)
            case "camera-grid":
                _run_camera_grid(args)
            case "report":
                report = build_report(args.manifest, args.output_dir)
                print(
                    f"wrote {len(cast('list[object]', report['views']))} view report",
                )
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
