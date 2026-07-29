"""Semantic building-instruction support layered over raw LDraw objects."""

from __future__ import annotations

import json
import math
import shlex
from contextlib import contextmanager
from dataclasses import dataclass, field, fields, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from ldraw.bom import BomRow, bill_of_materials
from ldraw.geometry import Identity, Matrix, Vector
from ldraw.lines import Comment, MetaCommand
from ldraw.pieces import Piece
from ldraw.serialization import format_ldraw_number
from ldraw.utils import normalize_ref
from ldraw.validation import Severity

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ldraw.model import Model, ModelOccurrence
    from ldraw.part import ParsedObject
    from ldraw.parts import Parts


class RotationMode(StrEnum):
    """MLCad rotation-step modes."""

    RELATIVE = "REL"
    ADDITIVE = "ADD"
    ABSOLUTE = "ABS"
    END = "END"


class DirectiveKind(StrEnum):
    """Instruction directives understood by the semantic layer."""

    STEP = "step"
    ROTATION_STEP = "rotation_step"
    CALLOUT_BEGIN = "callout_begin"
    CALLOUT_END = "callout_end"
    MULTI_STEP_BEGIN = "multi_step_begin"
    MULTI_STEP_END = "multi_step_end"
    INVENTORY_IGNORE_BEGIN = "inventory_ignore_begin"
    INVENTORY_IGNORE_END = "inventory_ignore_end"
    NO_STEP = "no_step"
    PARSE_NO_STEP = "parse_no_step"
    PAGE_BREAK = "page_break"
    CAMERA = "camera"
    NOTE = "note"
    HIGHLIGHT = "highlight"
    ARROW = "arrow"
    UNSUPPORTED_LPUB = "unsupported_lpub"
    UNSUPPORTED_PYLDRAW = "unsupported_pyldraw"
    MALFORMED = "malformed"


class CalloutMode(StrEnum):
    """LPub3D callout assembly modes."""

    ASSEMBLED = "ASSEMBLED"
    ROTATED = "ROTATED"
    WHOLE = "WHOLE"


class InventoryTarget(StrEnum):
    """LPub3D inventory-ignore targets."""

    PLI = "PLI"
    BOM = "BOM"
    PART = "PART"


class InstructionScope(StrEnum):
    """Persistence scope for LPub3D camera directives."""

    GLOBAL = "GLOBAL"
    LOCAL = "LOCAL"


class CameraContext(StrEnum):
    """LPub3D assembly context receiving camera settings."""

    ASSEMBLY = "ASSEM"
    CALLOUT = "CALLOUT"
    MULTI_STEP = "MULTI_STEP"


@dataclass(frozen=True, slots=True)
class RotationStep:
    """A parsed MLCad ``ROTSTEP`` boundary."""

    mode: RotationMode
    angles: tuple[float, float, float] | None
    command_matrix: Matrix
    effective_matrix: Matrix
    source_line: int | None = None


@dataclass(frozen=True, slots=True)
class CameraState:
    """Renderer-neutral LPub3D assembly camera state."""

    angles: tuple[float, float] | None = None
    angle_preset: str | None = None
    position: tuple[float, float, float] | None = None
    target: tuple[float, float, float] | None = None
    up_vector: tuple[float, float, float] | None = None
    distance: float | None = None
    fov: float | None = None
    name: str | None = None
    orthographic: bool | None = None
    z_near: float | None = None
    z_far: float | None = None

    def merged(self, override: CameraState) -> CameraState:
        """Return this state with non-None fields from ``override`` applied."""
        values = {
            item.name: getattr(override, item.name)
            if getattr(override, item.name) is not None
            else getattr(self, item.name)
            for item in fields(self)
        }
        return CameraState(**values)


@dataclass(frozen=True, slots=True)
class InstructionDirective:
    """One interpreted instruction directive with its raw source object."""

    kind: DirectiveKind
    raw: Comment | MetaCommand
    source_line: int | None
    data: tuple[tuple[str, object], ...] = ()

    def value(self, key: str, default: object = None) -> object:
        """Return one named directive value."""
        return dict(self.data).get(key, default)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready directive representation."""
        return {
            "kind": self.kind.value,
            "source_line": self.source_line,
            "raw": self.raw.to_ldraw(),
            "data": dict(self.data),
        }


@dataclass(frozen=True, slots=True)
class InstructionCallout:
    """A callout active within one instruction step."""

    mode: CalloutMode
    references: tuple[str, ...]
    source_line: int | None


@dataclass(frozen=True, slots=True)
class InstructionIssue:
    """A structural or semantic instruction problem."""

    section: str
    line_number: int | None
    code: str
    message: str
    severity: Severity = Severity.ERROR


@dataclass(frozen=True, slots=True)
class InstructionStep:
    """One section-local building step and its effective instruction state."""

    number: int
    section_name: str
    objects: tuple[ParsedObject, ...]
    added_pieces: tuple[Piece, ...]
    directives: tuple[InstructionDirective, ...]
    rotation: RotationStep | None
    camera: CameraState
    callouts: tuple[InstructionCallout, ...]
    multi_step_group: int | None
    page_break_before: bool
    suppressed: bool
    source_start_line: int | None
    source_end_line: int | None
    _root: Model = field(repr=False, compare=False)
    _model: Model = field(repr=False, compare=False)
    _cumulative_objects: tuple[ParsedObject, ...] = field(repr=False, compare=False)
    _ignored_pli: frozenset[int] = field(repr=False, compare=False)
    _ignored_bom: frozenset[int] = field(repr=False, compare=False)
    _cumulative_ignored_pli: frozenset[int] = field(repr=False, compare=False)
    _cumulative_ignored_bom: frozenset[int] = field(repr=False, compare=False)

    @property
    def cumulative_pieces(self) -> tuple[Piece, ...]:
        """Direct placements accumulated in this section through this step."""
        return tuple(obj for obj in self._cumulative_objects if isinstance(obj, Piece))

    def added_occurrences(
        self,
        *,
        expand_submodels: bool = True,
    ) -> tuple[ModelOccurrence, ...]:
        """Return leaf occurrences added in this step."""
        return self._occurrences(
            objects=self.added_pieces,
            expand_submodels=expand_submodels,
        )

    def cumulative_occurrences(
        self,
        *,
        expand_submodels: bool = True,
    ) -> tuple[ModelOccurrence, ...]:
        """Return leaf occurrences accumulated through this step."""
        return self._occurrences(
            objects=self.cumulative_pieces,
            expand_submodels=expand_submodels,
        )

    def added_bill_of_materials(
        self,
        *,
        parts: Parts | None = None,
        expand_submodels: bool = True,
        respect_lpub: bool = True,
    ) -> list[BomRow]:
        """Return the parts tray for placements added in this step."""
        ignored = self._ignored_pli if respect_lpub else frozenset()
        return self._bill_of_materials(
            objects=self.added_pieces,
            ignored=ignored,
            parts=parts,
            expand_submodels=expand_submodels,
        )

    def cumulative_bill_of_materials(
        self,
        *,
        parts: Parts | None = None,
        expand_submodels: bool = True,
        respect_lpub: bool = True,
    ) -> list[BomRow]:
        """Return the accumulated BOM through this step."""
        ignored = self._cumulative_ignored_bom if respect_lpub else frozenset()
        return self._bill_of_materials(
            objects=self.cumulative_pieces,
            ignored=ignored,
            parts=parts,
            expand_submodels=expand_submodels,
        )

    def _occurrences(
        self,
        *,
        objects: tuple[Piece, ...],
        expand_submodels: bool,
    ) -> tuple[ModelOccurrence, ...]:
        from ldraw.model import Model  # noqa: PLC0415

        view = Model(
            name=self._model.name,
            objects=list(objects),
            submodels=_expandable_submodels(self._root, expand=expand_submodels),
            _source_lines=self._model._source_lines,  # noqa: SLF001
            _object_source_lines=self._model._object_source_lines,  # noqa: SLF001
        )
        return tuple(
            view.iter_occurrences(
                expand_submodels=expand_submodels,
                include_steps=False,
            )
        )

    def _bill_of_materials(
        self,
        *,
        objects: tuple[Piece, ...],
        ignored: frozenset[int],
        parts: Parts | None,
        expand_submodels: bool,
    ) -> list[BomRow]:
        from ldraw.model import Model  # noqa: PLC0415

        included: list[ParsedObject] = [
            piece for piece in objects if id(piece) not in ignored
        ]
        view = Model(
            name=self._model.name,
            objects=included,
            submodels=_expandable_submodels(self._root, expand=expand_submodels),
        )
        return bill_of_materials(view, parts=parts)


@dataclass(frozen=True, slots=True)
class InstructionSection:
    """The independent instruction sequence for one model section."""

    name: str
    is_root: bool
    reachable: bool
    references: tuple[str, ...]
    steps: tuple[InstructionStep, ...]
    model: Model = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class InstructionDocument:
    """A sectioned semantic view of an LDraw model's instructions."""

    root: InstructionSection
    sections: tuple[InstructionSection, ...]
    orphan_sections: tuple[InstructionSection, ...]
    model: Model = field(repr=False, compare=False)
    parts: Parts | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_model(
        cls,
        model: Model,
        *,
        parts: Parts | None = None,
    ) -> InstructionDocument:
        """Build a semantic instruction document from ``model``."""
        reachable_models = _reachable_instruction_models(model)
        sections = tuple(
            _build_section(
                root=model,
                model=section_model,
                is_root=index == 0,
                reachable=True,
            )
            for index, section_model in enumerate(reachable_models)
        )
        reachable_keys = {normalize_ref(item.name) for item in reachable_models}
        orphan_sections = tuple(
            _build_section(root=model, model=item, is_root=False, reachable=False)
            for item in model.submodels.values()
            if _is_instruction_model(item)
            and normalize_ref(item.name) not in reachable_keys
        )
        return cls(
            root=sections[0],
            sections=sections,
            orphan_sections=orphan_sections,
            model=model,
            parts=parts,
        )

    def section(self, name: str) -> InstructionSection:
        """Return a reachable section by case-insensitive reference name."""
        wanted = normalize_ref(name)
        for section in self.sections:
            if normalize_ref(section.name) == wanted:
                return section
        msg = f"No reachable instruction section named {name!r}"
        raise KeyError(msg)


def _rotation_matrix(angles: tuple[float, float, float]) -> Matrix:
    wx, wy, wz = (math.radians(value) for value in angles)
    s1, s2, s3 = math.sin(wx), math.sin(wy), math.sin(wz)
    c1, c2, c3 = math.cos(wx), math.cos(wy), math.cos(wz)
    return Matrix(
        [
            [c2 * c3, -c2 * s3, s2],
            [c1 * s3 + s1 * s2 * c3, c1 * c3 - s1 * s2 * s3, -s1 * c2],
            [s1 * s3 - c1 * s2 * c3, s1 * c3 + c1 * s2 * s3, c1 * c2],
        ]
    )


def _data(**values: object) -> tuple[tuple[str, object], ...]:
    return tuple(values.items())


def _malformed(
    raw: Comment | MetaCommand,
    line: int | None,
    message: str,
) -> InstructionDirective:
    return InstructionDirective(
        DirectiveKind.MALFORMED,
        raw,
        line,
        _data(error=message),
    )


def parse_instruction_directive(  # noqa: PLR0911 - explicit grammar cases
    obj: ParsedObject,
    *,
    source_line: int | None = None,
) -> InstructionDirective | None:
    """Interpret one raw LDraw object as an instruction directive."""
    if isinstance(obj, Comment):
        text = obj.text.strip()
        upper = text.upper()
        if upper == "STEP":
            return InstructionDirective(DirectiveKind.STEP, obj, source_line)
        if upper.startswith("ROTSTEP"):
            return _parse_rotation(obj, source_line)
        if upper == "LPUB" or upper.startswith("LPUB "):
            return _parse_lpub(obj, text[4:].strip(), source_line)
        return None
    if not isinstance(obj, MetaCommand):
        return None
    if obj.type.casefold() == "lpub":
        return _parse_lpub(obj, obj.text, source_line)
    if obj.type.casefold() == "pyldraw":
        return _parse_pyldraw(obj, source_line)
    return None


def _parse_rotation(  # noqa: PLR0911 - explicit grammar cases
    raw: Comment,
    line: int | None,
) -> InstructionDirective:
    tokens = raw.text.split()
    if len(tokens) == 2 and tokens[1].upper() == RotationMode.END:
        return InstructionDirective(
            DirectiveKind.ROTATION_STEP,
            raw,
            line,
            _data(mode=RotationMode.END.value, angles=None),
        )
    if len(tokens) not in {4, 5}:
        return _malformed(raw, line, "ROTSTEP expects x y z [REL|ADD|ABS] or END")
    try:
        angles = tuple(float(value) for value in tokens[1:4])
    except ValueError:
        return _malformed(raw, line, "ROTSTEP angles must be numeric")
    if any(not -360 <= value <= 360 for value in angles):
        return _malformed(raw, line, "ROTSTEP angles must be between -360 and 360")
    try:
        mode = RotationMode(tokens[4].upper() if len(tokens) == 5 else "REL")
    except ValueError:
        return _malformed(raw, line, "ROTSTEP mode must be REL, ADD, or ABS")
    if mode is RotationMode.END:
        return _malformed(raw, line, "ROTSTEP END does not accept angles")
    return InstructionDirective(
        DirectiveKind.ROTATION_STEP,
        raw,
        line,
        _data(mode=mode.value, angles=angles),
    )


def _split_tokens(
    raw: Comment | MetaCommand,
    text: str,
    line: int | None,
) -> tuple[list[str] | None, InstructionDirective | None]:
    try:
        return shlex.split(text), None
    except ValueError as error:
        return None, _malformed(raw, line, f"invalid quoted text: {error}")


def _parse_lpub(
    raw: Comment | MetaCommand,
    text: str,
    line: int | None,
) -> InstructionDirective:
    tokens, error = _split_tokens(raw, text, line)
    if tokens is None:
        return error or _malformed(raw, line, "invalid quoted text")
    for parser in (
        _parse_structural_lpub,
        _parse_inventory_lpub,
        _parse_page_lpub,
        _parse_camera,
    ):
        if (directive := parser(raw, tokens, line)) is not None:
            return directive
    return InstructionDirective(DirectiveKind.UNSUPPORTED_LPUB, raw, line)


def _parse_structural_lpub(  # noqa: PLR0911 - declarative command grammar
    raw: Comment | MetaCommand,
    tokens: list[str],
    line: int | None,
) -> InstructionDirective | None:
    upper = [token.upper() for token in tokens]
    if upper[:2] == ["CALLOUT", "BEGIN"]:
        if len(tokens) > 3:
            return _malformed(raw, line, "CALLOUT BEGIN accepts at most one mode")
        mode = upper[2] if len(tokens) == 3 else CalloutMode.ASSEMBLED.value
        if mode not in {item.value for item in CalloutMode}:
            return _malformed(raw, line, "invalid CALLOUT mode")
        return InstructionDirective(
            DirectiveKind.CALLOUT_BEGIN,
            raw,
            line,
            _data(mode=mode),
        )
    if upper == ["CALLOUT", "END"]:
        return InstructionDirective(DirectiveKind.CALLOUT_END, raw, line)
    if upper == ["MULTI_STEP", "BEGIN"]:
        return InstructionDirective(DirectiveKind.MULTI_STEP_BEGIN, raw, line)
    if upper == ["MULTI_STEP", "END"]:
        return InstructionDirective(DirectiveKind.MULTI_STEP_END, raw, line)
    if upper == ["NOSTEP"]:
        return InstructionDirective(DirectiveKind.NO_STEP, raw, line)
    if upper[:1] != ["PARSE_NOSTEP"]:
        return None
    if len(upper) != 2 or upper[1] not in {"TRUE", "FALSE"}:
        return _malformed(raw, line, "PARSE_NOSTEP expects TRUE or FALSE")
    return InstructionDirective(
        DirectiveKind.PARSE_NO_STEP,
        raw,
        line,
        _data(enabled=upper[1] == "TRUE"),
    )


def _parse_inventory_lpub(
    raw: Comment | MetaCommand,
    tokens: list[str],
    line: int | None,
) -> InstructionDirective | None:
    upper = [token.upper() for token in tokens]
    inventory_names = {item.value for item in InventoryTarget}
    if (
        len(upper) == 3
        and upper[0] in inventory_names
        and upper[1:] == ["BEGIN", "IGN"]
    ):
        return InstructionDirective(
            DirectiveKind.INVENTORY_IGNORE_BEGIN,
            raw,
            line,
            _data(target=upper[0]),
        )
    if len(upper) == 2 and upper[0] in inventory_names and upper[1] == "END":
        return InstructionDirective(
            DirectiveKind.INVENTORY_IGNORE_END,
            raw,
            line,
            _data(target=upper[0]),
        )
    return None


def _parse_page_lpub(
    raw: Comment | MetaCommand,
    tokens: list[str],
    line: int | None,
) -> InstructionDirective | None:
    upper = [token.upper() for token in tokens]
    if upper[:2] != ["INSERT", "PAGE"]:
        return None
    if len(tokens) == 2:
        offset = None
    elif len(tokens) == 5 and upper[2] == "OFFSET":
        try:
            offset = (float(tokens[3]), float(tokens[4]))
        except ValueError:
            return _malformed(raw, line, "INSERT PAGE OFFSET must be numeric")
    else:
        return _malformed(raw, line, "INSERT PAGE accepts optional OFFSET x y")
    return InstructionDirective(
        DirectiveKind.PAGE_BREAK,
        raw,
        line,
        _data(offset=offset),
    )


def _parse_camera(
    raw: Comment | MetaCommand,
    tokens: list[str],
    line: int | None,
) -> InstructionDirective | None:
    upper = [token.upper() for token in tokens]
    context = CameraContext.ASSEMBLY
    if upper[:2] == ["CALLOUT", "ASSEM"]:
        context, command_index = CameraContext.CALLOUT, 2
    elif upper[:2] == ["MULTI_STEP", "ASSEM"]:
        context, command_index = CameraContext.MULTI_STEP, 2
    elif upper[:1] == ["ASSEM"]:
        command_index = 1
    else:
        return None
    if command_index >= len(tokens) or not upper[command_index].startswith("CAMERA_"):
        return None
    command = upper[command_index].removeprefix("CAMERA_")
    values = tokens[command_index + 1 :]
    scope = InstructionScope.GLOBAL
    if values and values[0].upper() in InstructionScope:
        scope = InstructionScope(values.pop(0).upper())
    try:
        parsed = _camera_value(command, values)
    except ValueError as error:
        return _malformed(raw, line, str(error))
    return InstructionDirective(
        DirectiveKind.CAMERA,
        raw,
        line,
        _data(
            context=context.value,
            scope=scope.value,
            field=command.casefold(),
            value=parsed,
        ),
    )


def _camera_value(
    command: str,
    values: list[str],
) -> object:
    if command in {"POSITION", "TARGET", "UPVECTOR"}:
        return _camera_vector(command, values)
    if command in {"DISTANCE", "FOV", "ZFAR", "ZNEAR"}:
        return _camera_scalar(command, values)
    parsers = {
        "ORTHOGRAPHIC": _camera_boolean,
        "NAME": _camera_name,
        "ANGLES": _camera_angles,
    }
    if (parser := parsers.get(command)) is None:
        msg = f"unsupported camera command CAMERA_{command}"
        raise ValueError(msg)
    return parser(values)


def _camera_vector(command: str, values: list[str]) -> tuple[float, float, float]:
    if len(values) != 3:
        msg = f"CAMERA_{command} expects three numeric values"
        raise ValueError(msg)
    return (float(values[0]), float(values[1]), float(values[2]))


def _camera_scalar(command: str, values: list[str]) -> float:
    if len(values) != 1:
        msg = f"CAMERA_{command} expects one numeric value"
        raise ValueError(msg)
    return float(values[0])


def _camera_boolean(values: list[str]) -> bool:
    if len(values) != 1 or values[0].upper() not in {"TRUE", "FALSE"}:
        msg = "CAMERA_ORTHOGRAPHIC expects TRUE or FALSE"
        raise ValueError(msg)
    return values[0].upper() == "TRUE"


def _camera_name(values: list[str]) -> str:
    if len(values) != 1:
        msg = "CAMERA_NAME expects one string"
        raise ValueError(msg)
    return values[0]


def _camera_angles(values: list[str]) -> str | tuple[float, float]:
    presets = {"FRONT", "BACK", "TOP", "BOTTOM", "LEFT", "RIGHT", "HOME"}
    if len(values) == 1 and values[0].upper() in presets:
        return values[0].upper()
    if len(values) == 3 and values[0].upper() == "LAT_LON":
        return (float(values[1]), float(values[2]))
    if len(values) == 2:
        return (float(values[0]), float(values[1]))
    msg = "CAMERA_ANGLES expects a preset or two numeric angles"
    raise ValueError(msg)


def _parse_pyldraw(  # noqa: PLR0911 - explicit annotation grammar
    raw: MetaCommand,
    line: int | None,
) -> InstructionDirective:
    tokens, error = _split_tokens(raw, raw.text, line)
    if tokens is None:
        return error or _malformed(raw, line, "invalid quoted text")
    upper = [token.upper() for token in tokens]
    if upper[:1] == ["NOTE"]:
        if len(tokens) != 2:
            return _malformed(raw, line, "NOTE expects one JSON-escaped string")
        return InstructionDirective(
            DirectiveKind.NOTE,
            raw,
            line,
            _data(text=tokens[1]),
        )
    if upper[:1] == ["HIGHLIGHT"]:
        if upper != ["HIGHLIGHT", "NEXT"]:
            return _malformed(raw, line, "HIGHLIGHT expects NEXT")
        return InstructionDirective(DirectiveKind.HIGHLIGHT, raw, line)
    if upper[:1] == ["ARROW"]:
        return _parse_arrow(raw, tokens=tokens, upper=upper, line=line)
    return InstructionDirective(DirectiveKind.UNSUPPORTED_PYLDRAW, raw, line)


def _parse_arrow(
    raw: MetaCommand,
    *,
    tokens: list[str],
    upper: list[str],
    line: int | None,
) -> InstructionDirective:
    if len(tokens) not in {7, 9}:
        return _malformed(
            raw,
            line,
            "ARROW expects six coordinates and optional LABEL text",
        )
    try:
        start = tuple(float(value) for value in tokens[1:4])
        end = tuple(float(value) for value in tokens[4:7])
    except ValueError:
        return _malformed(raw, line, "ARROW coordinates must be numeric")
    if len(tokens) == 9 and upper[7] != "LABEL":
        return _malformed(raw, line, "ARROW label must use LABEL")
    label = tokens[8] if len(tokens) == 9 else None
    return InstructionDirective(
        DirectiveKind.ARROW,
        raw,
        line,
        _data(start=start, end=end, label=label),
    )


def _is_instruction_model(model: Model) -> bool:
    return not model.name.casefold().endswith(".dat")


def _expandable_submodels(root: Model, *, expand: bool) -> dict[str, Model]:
    if not expand:
        return {}
    return {
        key: model
        for key, model in root.submodels.items()
        if _is_instruction_model(model)
    }


def _reachable_instruction_models(root: Model) -> list[Model]:
    pending = [root]
    seen = {normalize_ref(root.name)}
    index = 0
    while index < len(pending):
        current = pending[index]
        index += 1
        for piece in current.pieces:
            target = root.submodel_for(piece)
            if target is None or not _is_instruction_model(target):
                continue
            key = normalize_ref(target.name)
            if key not in seen:
                seen.add(key)
                pending.append(target)
    return [
        root,
        *(
            model
            for model in root.submodels.values()
            if normalize_ref(model.name) in seen and _is_instruction_model(model)
        ),
    ]


def _references(root: Model, model: Model) -> tuple[str, ...]:
    refs: list[str] = []
    for piece in model.pieces:
        target = root.submodel_for(piece)
        if target is not None and _is_instruction_model(target):
            refs.append(target.name)
    return tuple(dict.fromkeys(refs))


@dataclass(slots=True)
class _CalloutState:
    mode: CalloutMode
    line: int | None
    references: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _StepState:
    objects: list[ParsedObject] = field(default_factory=list)
    directives: list[InstructionDirective] = field(default_factory=list)
    pieces: list[Piece] = field(default_factory=list)
    ignored_pli: set[int] = field(default_factory=set)
    ignored_bom: set[int] = field(default_factory=set)
    callouts: list[InstructionCallout] = field(default_factory=list)
    local_cameras: dict[CameraContext, CameraState] = field(default_factory=dict)
    page_break: bool = False
    suppressed: bool = False


@dataclass(slots=True)
class _SectionMachine:
    root: Model
    model: Model
    is_root: bool
    reachable: bool
    steps: list[InstructionStep] = field(default_factory=list)
    state: _StepState = field(default_factory=_StepState)
    cumulative: list[ParsedObject] = field(default_factory=list)
    cumulative_pli: set[int] = field(default_factory=set)
    cumulative_bom: set[int] = field(default_factory=set)
    ignores: list[InventoryTarget] = field(default_factory=list)
    active_callouts: list[_CalloutState] = field(default_factory=list)
    active_group: int | None = None
    next_group: int = 1
    global_cameras: dict[CameraContext, CameraState] = field(default_factory=dict)
    current_view: Matrix = field(default_factory=Identity)

    def build(self) -> InstructionSection:
        for obj in self.model.objects:
            directive = parse_instruction_directive(
                obj,
                source_line=self.model.source_line_for(obj),
            )
            self._add_object(obj, directive=directive)
            if directive is not None and not self._apply_step_directive(directive):
                self._apply_structural_directive(directive)
        if self.state.objects or not self.steps:
            self.finish()
        return InstructionSection(
            name=self.model.name,
            is_root=self.is_root,
            reachable=self.reachable,
            references=_references(self.root, self.model),
            steps=tuple(self.steps),
            model=self.model,
        )

    def camera_state(self) -> CameraState:
        context = (
            CameraContext.CALLOUT
            if self.active_callouts or self.state.callouts
            else CameraContext.MULTI_STEP
            if self.active_group is not None
            else CameraContext.ASSEMBLY
        )
        result = self.global_cameras.get(CameraContext.ASSEMBLY, CameraState())
        if context is not CameraContext.ASSEMBLY:
            result = result.merged(self.global_cameras.get(context, CameraState()))
        result = result.merged(
            self.state.local_cameras.get(CameraContext.ASSEMBLY, CameraState())
        )
        if context is not CameraContext.ASSEMBLY:
            result = result.merged(self.state.local_cameras.get(context, CameraState()))
        return result

    def finish(
        self,
        rotation_directive: InstructionDirective | None = None,
    ) -> None:
        rotation = _rotation_from_directive(
            rotation_directive,
            current=self.current_view,
        )
        if rotation is not None:
            self.current_view = rotation.effective_matrix
        self.cumulative.extend(self.state.objects)
        self.cumulative_pli.update(self.state.ignored_pli)
        self.cumulative_bom.update(self.state.ignored_bom)
        lines = [
            line
            for obj in self.state.objects
            if (line := self.model.source_line_for(obj)) is not None
        ]
        callouts = [
            *self.state.callouts,
            *(
                InstructionCallout(item.mode, tuple(item.references), item.line)
                for item in self.active_callouts
            ),
        ]
        self.steps.append(
            InstructionStep(
                number=len(self.steps) + 1,
                section_name=self.model.name,
                objects=tuple(self.state.objects),
                added_pieces=tuple(self.state.pieces),
                directives=tuple(self.state.directives),
                rotation=rotation,
                camera=self.camera_state(),
                callouts=tuple(callouts),
                multi_step_group=self.active_group,
                page_break_before=self.state.page_break,
                suppressed=self.state.suppressed,
                source_start_line=min(lines, default=None),
                source_end_line=max(lines, default=None),
                _root=self.root,
                _model=self.model,
                _cumulative_objects=tuple(self.cumulative),
                _ignored_pli=frozenset(self.state.ignored_pli),
                _ignored_bom=frozenset(self.state.ignored_bom),
                _cumulative_ignored_pli=frozenset(self.cumulative_pli),
                _cumulative_ignored_bom=frozenset(self.cumulative_bom),
            )
        )
        self.state = _StepState()

    def _add_object(
        self,
        obj: ParsedObject,
        *,
        directive: InstructionDirective | None,
    ) -> None:
        if directive is not None:
            self.state.directives.append(directive)
        self.state.objects.append(obj)
        if not isinstance(obj, Piece):
            return
        self.state.pieces.append(obj)
        if InventoryTarget.PLI in self.ignores or InventoryTarget.PART in self.ignores:
            self.state.ignored_pli.add(id(obj))
        if InventoryTarget.BOM in self.ignores or InventoryTarget.PART in self.ignores:
            self.state.ignored_bom.add(id(obj))
        for callout in self.active_callouts:
            callout.references.append(obj.reference)

    def _apply_step_directive(self, directive: InstructionDirective) -> bool:
        match directive.kind:
            case DirectiveKind.STEP:
                self.finish()
            case DirectiveKind.ROTATION_STEP:
                self.finish(directive)
            case DirectiveKind.NO_STEP:
                self.state.suppressed = True
            case DirectiveKind.PAGE_BREAK:
                self.state.page_break = True
            case DirectiveKind.CAMERA:
                _apply_camera_directive(
                    directive,
                    global_cameras=self.global_cameras,
                    local_cameras=self.state.local_cameras,
                )
            case _:
                return False
        return True

    def _apply_structural_directive(self, directive: InstructionDirective) -> None:
        match directive.kind:
            case DirectiveKind.CALLOUT_BEGIN:
                mode = CalloutMode(str(directive.value("mode")))
                self.active_callouts.append(_CalloutState(mode, directive.source_line))
            case DirectiveKind.CALLOUT_END:
                if self.active_callouts:
                    completed = self.active_callouts.pop()
                    self.state.callouts.append(
                        InstructionCallout(
                            completed.mode,
                            tuple(completed.references),
                            completed.line,
                        )
                    )
            case DirectiveKind.MULTI_STEP_BEGIN:
                if self.active_group is None:
                    self.active_group = self.next_group
                    self.next_group += 1
            case DirectiveKind.MULTI_STEP_END:
                self.active_group = None
            case DirectiveKind.INVENTORY_IGNORE_BEGIN:
                self.ignores.append(InventoryTarget(str(directive.value("target"))))
            case DirectiveKind.INVENTORY_IGNORE_END:
                target = InventoryTarget(str(directive.value("target")))
                if target in self.ignores:
                    self.ignores.remove(target)
            case _:
                pass


def _build_section(
    *,
    root: Model,
    model: Model,
    is_root: bool,
    reachable: bool,
) -> InstructionSection:
    return _SectionMachine(
        root=root,
        model=model,
        is_root=is_root,
        reachable=reachable,
    ).build()


def _rotation_from_directive(
    directive: InstructionDirective | None,
    *,
    current: Matrix,
) -> RotationStep | None:
    if directive is None or directive.kind is DirectiveKind.MALFORMED:
        return None
    mode = RotationMode(str(directive.value("mode")))
    if mode is RotationMode.END:
        identity = Identity()
        return RotationStep(mode, None, identity, identity, directive.source_line)
    raw_angles = directive.value("angles")
    if not isinstance(raw_angles, tuple) or len(raw_angles) != 3:
        return None
    x, y, z = raw_angles
    if (
        not isinstance(x, int | float)
        or not isinstance(y, int | float)
        or not isinstance(z, int | float)
    ):
        return None
    angles = (float(x), float(y), float(z))
    command = _rotation_matrix(angles)
    effective = command if mode is RotationMode.ABSOLUTE else current * command
    if mode is RotationMode.RELATIVE:
        effective = Identity() * command
    return RotationStep(mode, angles, command, effective, directive.source_line)


_CAMERA_FIELD_MAP = {
    "angles": "angles",
    "position": "position",
    "target": "target",
    "upvector": "up_vector",
    "distance": "distance",
    "fov": "fov",
    "name": "name",
    "orthographic": "orthographic",
    "znear": "z_near",
    "zfar": "z_far",
}


def _apply_camera_directive(
    directive: InstructionDirective,
    *,
    global_cameras: dict[CameraContext, CameraState],
    local_cameras: dict[CameraContext, CameraState],
) -> None:
    context = CameraContext(str(directive.value("context")))
    scope = InstructionScope(str(directive.value("scope")))
    field_name = str(directive.value("field"))
    value = directive.value("value")
    target = global_cameras if scope is InstructionScope.GLOBAL else local_cameras
    current = target.get(context, CameraState())
    if field_name == "angles" and isinstance(value, str):
        updated = replace(current, angle_preset=value, angles=None)
    else:
        attribute = _CAMERA_FIELD_MAP[field_name]
        updated = replace(current, **{attribute: value})
    target[context] = updated


class InstructionBuilder:
    """Write balanced instruction directives into a ``Model``."""

    def __init__(self, model: Model) -> None:
        self.model = model
        self._scopes: list[str] = []

    def step(self) -> None:
        """Append a plain LDraw step boundary."""
        self.model.add_step()

    def rotation_step(
        self,
        x: float,
        y: float,
        z: float,
        *,
        mode: RotationMode = RotationMode.RELATIVE,
    ) -> None:
        """Append a rotation-step boundary."""
        self.model.add_rotation_step(x, y, z, mode=mode)

    def end_rotation(self) -> None:
        """Restore the default instruction view."""
        self.model.end_rotation_steps()

    def note(self, text: str) -> None:
        """Append a renderer-neutral textual note."""
        self.model.add(MetaCommand("PYLDRAW", f"NOTE {json.dumps(text)}"))

    def arrow(self, start: Vector, end: Vector, *, label: str | None = None) -> None:
        """Append a section-local 3D arrow annotation."""
        values = " ".join(
            format_ldraw_number(value)
            for value in (start.x, start.y, start.z, end.x, end.y, end.z)
        )
        suffix = "" if label is None else f" LABEL {json.dumps(label)}"
        self.model.add(MetaCommand("PYLDRAW", f"ARROW {values}{suffix}"))

    def highlight(self, piece: Piece) -> None:
        """Highlight an existing placement using proximity-safe metadata."""
        try:
            index = next(
                index for index, obj in enumerate(self.model.objects) if obj is piece
            )
        except StopIteration as error:
            msg = "Highlighted piece is not in this model"
            raise ValueError(msg) from error
        self.model.objects.insert(index, MetaCommand("PYLDRAW", "HIGHLIGHT NEXT"))

    def page_break(self, *, offset: tuple[float, float] | None = None) -> None:
        """Append an LPub3D page break."""
        text = "INSERT PAGE"
        if offset is not None:
            x, y = (format_ldraw_number(value) for value in offset)
            text = f"{text} OFFSET {x} {y}"
        self.model.add(MetaCommand("LPUB", text))

    def suppress_step(self) -> None:
        """Mark the current step as suppressed in LPub3D."""
        self.model.add(MetaCommand("LPUB", "NOSTEP"))

    def set_camera(
        self,
        camera: CameraState,
        *,
        scope: InstructionScope = InstructionScope.LOCAL,
        context: CameraContext = CameraContext.ASSEMBLY,
    ) -> None:
        """Append canonical LPub3D camera directives for non-None fields."""
        prefix = (
            "ASSEM" if context is CameraContext.ASSEMBLY else f"{context.value} ASSEM"
        )
        for command, value in _camera_commands(camera):
            self.model.add(
                MetaCommand(
                    "LPUB",
                    f"{prefix} CAMERA_{command} {scope.value} {value}",
                )
            )

    @contextmanager
    def callout(
        self,
        *,
        mode: CalloutMode = CalloutMode.ASSEMBLED,
    ) -> Iterator[None]:
        """Write a balanced LPub3D callout range."""
        with self._range(
            key="CALLOUT",
            begin=f"CALLOUT BEGIN {mode.value}",
            end="CALLOUT END",
        ):
            yield

    @contextmanager
    def multi_step(self) -> Iterator[None]:
        """Write a balanced LPub3D multi-step range."""
        with self._range(
            key="MULTI_STEP",
            begin="MULTI_STEP BEGIN",
            end="MULTI_STEP END",
        ):
            yield

    @contextmanager
    def ignore(self, target: InventoryTarget) -> Iterator[None]:
        """Write a balanced LPub3D inventory-ignore range."""
        key = f"IGNORE:{target.value}"
        with self._range(
            key=key,
            begin=f"{target.value} BEGIN IGN",
            end=f"{target.value} END",
        ):
            yield

    @contextmanager
    def _range(self, *, key: str, begin: str, end: str) -> Iterator[None]:
        if key in self._scopes:
            msg = f"Cannot nest {key} inside itself"
            raise ValueError(msg)
        self._scopes.append(key)
        self.model.add(MetaCommand("LPUB", begin))
        try:
            yield
        finally:
            self.model.add(MetaCommand("LPUB", end))
            self._scopes.pop()


def _camera_commands(camera: CameraState) -> Iterator[tuple[str, str]]:
    if camera.angle_preset is not None:
        yield "ANGLES", camera.angle_preset
    elif camera.angles is not None:
        yield "ANGLES", " ".join(format_ldraw_number(value) for value in camera.angles)
    for command, value in (
        ("POSITION", camera.position),
        ("TARGET", camera.target),
        ("UPVECTOR", camera.up_vector),
    ):
        if value is not None:
            yield command, " ".join(format_ldraw_number(item) for item in value)
    for command, value in (
        ("DISTANCE", camera.distance),
        ("FOV", camera.fov),
        ("ZFAR", camera.z_far),
        ("ZNEAR", camera.z_near),
    ):
        if value is not None:
            yield command, format_ldraw_number(value)
    if camera.name is not None:
        yield "NAME", json.dumps(camera.name)
    if camera.orthographic is not None:
        yield "ORTHOGRAPHIC", str(camera.orthographic).upper()


def iter_instruction_issues(
    document: InstructionDocument,
    *,
    max_parts: int | None = None,
) -> Iterator[InstructionIssue]:
    """Yield structural and semantic issues in ``document``."""
    for orphan in document.orphan_sections:
        yield InstructionIssue(
            section=orphan.name,
            line_number=None,
            code="orphan-section",
            message="instruction section is not reachable from the root model",
            severity=Severity.WARNING,
        )
    yield from _cycle_issues(document)
    for section in (*document.sections, *document.orphan_sections):
        yield from _section_issues(section, document=document, max_parts=max_parts)


def _section_issues(  # noqa: C901 - validation rule coordinator
    section: InstructionSection,
    *,
    document: InstructionDocument,
    max_parts: int | None,
) -> Iterator[InstructionIssue]:
    boundaries = 0
    stack: list[tuple[str, int | None]] = []
    for step in section.steps:
        if (
            not step.added_pieces
            and step.rotation is None
            and 1 < step.number < len(section.steps)
        ):
            yield InstructionIssue(
                section.name,
                step.source_start_line,
                "empty-step",
                f"step {step.number} adds no pieces",
                Severity.WARNING,
            )
        if max_parts is not None and len(step.added_occurrences()) > max_parts:
            yield InstructionIssue(
                section.name,
                step.source_start_line,
                "step-too-large",
                f"step {step.number} adds more than {max_parts} leaf pieces",
                Severity.WARNING,
            )
        for directive in step.directives:
            if directive.kind in {DirectiveKind.STEP, DirectiveKind.ROTATION_STEP}:
                boundaries += 1
            if directive.kind is DirectiveKind.MALFORMED:
                yield InstructionIssue(
                    section.name,
                    directive.source_line,
                    "malformed-directive",
                    str(directive.value("error")),
                )
            yield from _directive_structure_issues(
                section=section.name,
                directive=directive,
                stack=stack,
            )
        yield from _camera_issues(section.name, step)
        for callout in step.callouts:
            if not _resolvable_callout_references(
                callout.references,
                root=document.model,
            ):
                yield InstructionIssue(
                    section.name,
                    callout.source_line,
                    "empty-callout",
                    "callout contains no submodel reference",
                )
    for kind, line in reversed(stack):
        yield InstructionIssue(
            section.name,
            line,
            "unclosed-range",
            f"{kind} range is not closed",
        )
    if boundaries == 0 and len(section.model.pieces) > 1:
        yield InstructionIssue(
            section.name,
            None,
            "no-step-boundaries",
            "model has multiple placements but no explicit STEP or ROTSTEP boundary",
            Severity.WARNING,
        )
    yield from _reference_issues(section, document.model)
    yield from _highlight_issues(section)


def _directive_structure_issues(
    *,
    section: str,
    directive: InstructionDirective,
    stack: list[tuple[str, int | None]],
) -> Iterator[InstructionIssue]:
    begin_kinds = {
        DirectiveKind.CALLOUT_BEGIN: "CALLOUT",
        DirectiveKind.MULTI_STEP_BEGIN: "MULTI_STEP",
        DirectiveKind.INVENTORY_IGNORE_BEGIN: str(directive.value("target")),
    }
    end_kinds = {
        DirectiveKind.CALLOUT_END: "CALLOUT",
        DirectiveKind.MULTI_STEP_END: "MULTI_STEP",
        DirectiveKind.INVENTORY_IGNORE_END: str(directive.value("target")),
    }
    if directive.kind in begin_kinds:
        kind = begin_kinds[directive.kind]
        if any(open_kind == kind for open_kind, _ in stack):
            yield InstructionIssue(
                section,
                directive.source_line,
                "illegal-nesting",
                f"{kind} cannot be nested inside itself",
            )
        stack.append((kind, directive.source_line))
    elif directive.kind in end_kinds:
        kind = end_kinds[directive.kind]
        if stack and stack[-1][0] == kind:
            stack.pop()
        elif any(open_kind == kind for open_kind, _ in stack):
            yield InstructionIssue(
                section,
                directive.source_line,
                "crossed-range",
                f"{kind} END crosses another active range",
            )
            del stack[
                next(
                    index
                    for index in range(len(stack) - 1, -1, -1)
                    if stack[index][0] == kind
                )
            ]
        else:
            yield InstructionIssue(
                section,
                directive.source_line,
                "unbalanced-range",
                f"{kind} END does not match the active range",
            )


def _camera_issues(section: str, step: InstructionStep) -> Iterator[InstructionIssue]:
    camera = step.camera
    if camera.fov is not None and not 0 < camera.fov < 180:
        yield InstructionIssue(
            section,
            step.source_start_line,
            "invalid-camera-fov",
            "camera FOV must be between 0 and 180 degrees",
        )
    if camera.z_near is not None and camera.z_near <= 0:
        yield InstructionIssue(
            section,
            step.source_start_line,
            "invalid-camera-near",
            "camera near clipping plane must be positive",
        )
    if camera.z_far is not None and camera.z_far <= 0:
        yield InstructionIssue(
            section,
            step.source_start_line,
            "invalid-camera-far",
            "camera far clipping plane must be positive",
        )
    if (
        camera.z_near is not None
        and camera.z_far is not None
        and camera.z_far <= camera.z_near
    ):
        yield InstructionIssue(
            section,
            step.source_start_line,
            "invalid-camera-far",
            "camera far clipping plane must be greater than its near plane",
        )
    if camera.up_vector is not None and not any(camera.up_vector):
        yield InstructionIssue(
            section,
            step.source_start_line,
            "invalid-camera-up",
            "camera up vector must be non-zero",
        )


def _reference_issues(
    section: InstructionSection,
    root: Model,
) -> Iterator[InstructionIssue]:
    for piece in section.model.pieces:
        if not piece.reference.casefold().endswith(".ldr"):
            continue
        if root.submodel_for(piece) is None:
            yield InstructionIssue(
                section.name,
                section.model.source_line_for(piece),
                "unknown-submodel",
                f"unknown submodel {piece.reference}",
            )


def _resolvable_callout_references(
    references: tuple[str, ...],
    *,
    root: Model,
) -> bool:
    root_key = normalize_ref(root.name)
    for reference in references:
        key = normalize_ref(reference)
        target = root if key == root_key else root.submodels.get(key)
        if target is not None and _is_instruction_model(target):
            return True
    return False


def _cycle_issues(document: InstructionDocument) -> Iterator[InstructionIssue]:
    root = document.model
    visited: set[str] = set()
    active: set[str] = set()
    reported: set[tuple[str, str]] = set()

    def visit(model: Model) -> Iterator[InstructionIssue]:
        key = normalize_ref(model.name)
        visited.add(key)
        active.add(key)
        for piece in model.pieces:
            target = root.submodel_for(piece)
            if target is None or not _is_instruction_model(target):
                continue
            target_key = normalize_ref(target.name)
            edge = (key, target_key)
            if target_key in active and edge not in reported:
                reported.add(edge)
                yield InstructionIssue(
                    model.name,
                    model.source_line_for(piece),
                    "cyclic-submodel",
                    f"submodel reference cycle reaches {target.name}",
                )
            elif target_key not in visited:
                yield from visit(target)
        active.remove(key)

    yield from visit(root)


def _highlight_issues(section: InstructionSection) -> Iterator[InstructionIssue]:
    pending: InstructionDirective | None = None
    for obj in section.model.objects:
        directive = parse_instruction_directive(
            obj,
            source_line=section.model.source_line_for(obj),
        )
        if directive is not None and directive.kind is DirectiveKind.HIGHLIGHT:
            pending = directive
        elif isinstance(obj, Piece):
            pending = None
        elif (
            directive is not None
            and directive.kind in {DirectiveKind.STEP, DirectiveKind.ROTATION_STEP}
            and pending is not None
        ):
            yield InstructionIssue(
                section.name,
                pending.source_line,
                "missing-highlight-target",
                "HIGHLIGHT NEXT is not followed by a piece in the same step",
            )
            pending = None
    if pending is not None:
        yield InstructionIssue(
            section.name,
            pending.source_line,
            "missing-highlight-target",
            "HIGHLIGHT NEXT is not followed by a piece",
        )
