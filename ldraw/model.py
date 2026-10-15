"""Reading and writing whole LDraw model files (.ldr and .mpd)."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from ldraw._model_copy import _copy_model, _origin_assignment, _restore_model_state
from ldraw._model_cycles import _cycle_callback, _iter_cycle_tolerant_occurrences
from ldraw._model_definitions import _DefinitionRegistry, _SourceOrigin
from ldraw._model_structure import iter_structure_edges
from ldraw._model_validation import ModelValidationContext, _resolve_reference
from ldraw._model_views import _model_view, _resolution_root, _selected_model
from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.errors import (
    DuplicateSubmodelError,
    InvalidColourValueError,
    InvalidNumericValueError,
    MisplacedNofileError,
    PartError,
    StructuralCommentError,
    SubmodelCycleError,
    SubmodelNameRequiredError,
    UnknownSubmodelError,
)
from ldraw.geometry import Identity, Vector
from ldraw.lines import Comment, MetaCommand
from ldraw.part import ParsedObject, parse_ldraw_line
from ldraw.pieces import MAIN_COLOUR_CODE, Piece, _default_leaf_identity
from ldraw.utils import (
    SUBMODEL_SUFFIXES,
    ldraw_file_name,
    normalize_ref,
    split_reference,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from ldraw.analysis import ModelAnalysis
    from ldraw.bom import BomRow
    from ldraw.colour import Colour
    from ldraw.geometry import Matrix
    from ldraw.instructions import InstructionDocument, InstructionStep, RotationMode
    from ldraw.parts import Parts
    from ldraw.pieces import Group

_NumberedLine = tuple[int, str]

_MANAGED_HEADER_PREFIXES = ("Name:", "Author:", "BFC")
_MANAGED_META_TYPES = ("LDRAW_ORG", "LICENSE")


def _is_nofile(line: str) -> bool:
    """Return whether the line is a ``0 NOFILE`` command."""
    match line.split(maxsplit=2):
        case ["0", keyword, *_] if keyword.upper() == "NOFILE":
            return True
        case _:
            return False


@dataclass(slots=True)
class _RawSection:
    """A ``0 FILE`` section before its lines are parsed."""

    name: str
    line_number: int = 0
    lines: list[_NumberedLine] = field(default_factory=list)


@dataclass(frozen=True, slots=True, eq=False)
class OccurrencePathItem:
    """One local placement in a root-to-leaf occurrence path."""

    model: Model
    piece: Piece
    source_line: int | None
    local_step: int | None
    effective_step: int | None

    @property
    def step(self) -> int | None:
        """Compatibility spelling for ``local_step`` — the *local* step.

        This is the step counted within the placement's own section, not
        the inherited one, so for submodel contents it differs from
        ``ModelOccurrence.step`` (which is the *effective* step). Use
        ``effective_step`` for the inherited semantics.
        """
        return self.local_step


@dataclass(frozen=True, slots=True, eq=False)
class ModelOccurrence:
    """One placed leaf part occurrence in a model.

    Occurrences are traversal events: two placements of the same submodel
    produce distinct occurrences, so they compare and hash by identity.

    ``step`` is the *effective* (inherited) step: pieces inside a submodel
    report the step their outermost placement belongs to. This differs
    from ``path[-1].step``, which is the placement's *local* step within
    its own section (``OccurrencePathItem.local_step``); ``source_step``
    carries the same local semantics.
    """

    piece: Piece
    part_code: str
    reference: str
    colour: Colour
    position: Vector
    matrix: Matrix
    source_model: Model
    source_line: int | None
    step: int | None
    source_step: int | None
    path: tuple[OccurrencePathItem, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelLoadResult:
    """Model, diagnostics, and source completeness from one read/parse pass."""

    model: Model | None
    diagnostics: tuple[Diagnostic, ...]
    complete: bool

    @property
    def valid(self) -> bool:
        """Whether the load emitted no error diagnostics."""
        return not any(
            diagnostic.severity is Severity.ERROR for diagnostic in self.diagnostics
        )

    def analyze(self, parts: Parts | None = None) -> ModelAnalysis | None:
        """Analyze the loaded model without discarding its diagnostics."""
        if self.model is None:
            return None
        from ldraw.analysis import analyze_model  # noqa: PLC0415

        return analyze_model(
            self.model,
            parts=parts,
            diagnostics=self.diagnostics,
        )


def _split_sections(
    text: str,
    *,
    source: Path | str | None = None,
) -> tuple[list[_NumberedLine], list[_RawSection]]:
    """Split document text into a preamble and its ``0 FILE`` sections."""
    preamble: list[_NumberedLine] = []
    sections: list[_RawSection] = []
    current: list[_NumberedLine] | None = preamble
    for number, line in enumerate(text.splitlines(), start=1):
        if (name := ldraw_file_name(line)) is not None:
            sections.append(_RawSection(name))
            current = sections[-1].lines
        elif _is_nofile(line):
            if not sections:
                raise MisplacedNofileError(
                    source=str(source) if source is not None else "<string>",
                    line_number=number,
                )
            # Lines between 0 NOFILE and the next 0 FILE are ignored.
            current = None
        elif current is not None:
            current.append((number, line))
    return preamble, sections


def _parse_objects(
    numbered_lines: Iterable[_NumberedLine],
    *,
    source: Path | str | None,
) -> tuple[list[ParsedObject], dict[Piece, int], dict[int, int]]:
    """Parse numbered lines, adding file and line context to errors."""
    objects: list[ParsedObject] = []
    source_lines: dict[Piece, int] = {}
    object_source_lines: dict[int, int] = {}
    for number, line in numbered_lines:
        try:
            parsed = parse_ldraw_line(line)
        except PartError as parse_error:
            parse_error.add_context(
                source=str(source) if source is not None else "<string>",
                line_number=number,
            )
            raise
        if parsed is not None:
            objects.append(parsed)
            object_source_lines[id(parsed)] = number
            if isinstance(parsed, Piece):
                source_lines[parsed] = number
    return objects, source_lines, object_source_lines


@dataclass(slots=True, eq=False)
class Model:
    """A whole LDraw model, optionally with MPD submodels.

    Models compare and hash by identity: their objects contain
    identity-compared pieces, so field-wise equality would be meaningless.
    Compare model content with ``m1.to_ldraw() == m2.to_ldraw()``.
    """

    name: str = ""
    objects: list[ParsedObject] = field(default_factory=list)
    submodels: dict[str, Model] = field(default_factory=dict)
    _source_lines: dict[Piece, int] = field(default_factory=dict, repr=False)
    _object_source_lines: dict[int, int] = field(default_factory=dict, repr=False)
    _serialization_origin: Model | dict[str, object] | _SourceOrigin | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    _is_submodel_view: bool = field(default=False, init=False, repr=False)

    def __setattr__(self, name: str, value: object) -> None:
        """Initialize private copy lineage without changing constructor hooks."""
        super(Model, self).__setattr__(
            name,
            _origin_assignment(model=self, value=value)
            if name == "_serialization_origin"
            else value,
        )

    def __copy__(self) -> Self:
        if copier := getattr(super(Model, self), "__copy__", None):
            return copier()
        return _copy_model(self)

    def __setstate__(self, state: Any) -> None:  # noqa: ANN401 - arbitrary subclass state
        _restore_model_state(model=self, state=state)

    def _serialization_aliases(self) -> tuple[Model, ...]:
        """Additional selected definitions recognized by private expansion models."""
        return ()

    def _header(self) -> Iterable[Comment | MetaCommand]:
        for obj in self.objects:
            if not isinstance(obj, Comment | MetaCommand):
                return
            yield obj

    def _header_comment(self, prefix: str) -> str | None:
        for obj in self._header():
            if isinstance(obj, Comment) and obj.text.startswith(prefix):
                return obj.text.removeprefix(prefix).strip()
        return None

    def _header_meta(self, meta_type: str) -> str | None:
        for obj in self._header():
            if isinstance(obj, MetaCommand) and obj.type == meta_type:
                return obj.text
        return None

    @property
    def description(self) -> str | None:
        """The description from the first line, when it is an unmanaged comment."""
        match self.objects:
            case [Comment(text=text), *_] if not text.startswith(
                _MANAGED_HEADER_PREFIXES,
            ):
                return text
            case _:
                return None

    @property
    def header_name(self) -> str | None:
        """The ``0 Name:`` header value."""
        return self._header_comment("Name:")

    @property
    def author(self) -> str | None:
        """The ``0 Author:`` header value."""
        return self._header_comment("Author:")

    @property
    def ldraw_org(self) -> str | None:
        """The ``0 !LDRAW_ORG`` header value."""
        return self._header_meta("LDRAW_ORG")

    @property
    def license(self) -> str | None:
        """The ``0 !LICENSE`` header value."""
        return self._header_meta("LICENSE")

    @property
    def bfc(self) -> str | None:
        """The ``0 BFC`` header value."""
        return self._header_comment("BFC")

    @property
    def pieces(self) -> list[Piece]:
        """The type-1 subfile references in this model."""
        return [obj for obj in self.objects if isinstance(obj, Piece)]

    def submodel_for(self, piece: Piece) -> Model | None:
        """Resolve a piece's subfile reference to a submodel, if any."""
        key = normalize_ref(piece.reference)
        if key == normalize_ref(self.name):
            return self
        return self.submodels.get(key)

    def source_line_for(self, obj: ParsedObject) -> int | None:
        """Return the parsed source line for this exact object."""
        if (line_number := self._object_source_lines.get(id(obj))) is not None:
            return line_number
        return self._source_lines.get(obj) if isinstance(obj, Piece) else None

    def add(self, *objects: ParsedObject) -> None:
        """Append parsed objects (pieces, comments, geometry) to the model."""
        self.objects.extend(objects)

    def add_group(self, group: Group) -> None:
        """Append a group's pieces; group transforms apply at serialization."""
        self.objects.extend(group.pieces)

    @classmethod
    def from_pieces(
        cls,
        pieces: Iterable[Piece],
        *,
        name: str = "",
        description: str | None = None,
        author: str | None = None,
    ) -> Self:
        """Build a model from pieces, optionally with header comments."""
        model = cls(name=name, objects=list(pieces))
        model.set_header(description=description, author=author)
        return model

    def set_header(
        self,
        *,
        description: str | None = None,
        name: str | None = None,
        author: str | None = None,
        ldraw_org: str | None = None,
        license: str | None = None,  # noqa: A002 - mirrors the 0 !LICENSE header
    ) -> None:
        """Set or replace standard header lines at the top of the model.

        ``ldraw_org`` and ``license`` write the ``0 !LDRAW_ORG`` and
        ``0 !LICENSE`` meta commands, placed after any ``Name:``/``Author:``
        comments in canonical header order.
        """
        if description is not None:
            self._set_description(description)
        if name is not None:
            self._set_header_comment(prefix="Name:", value=name)
        if author is not None:
            self._set_header_comment(prefix="Author:", value=author)
        if ldraw_org is not None:
            self._set_header_meta(meta_type="LDRAW_ORG", value=ldraw_org)
        if license is not None:
            self._set_header_meta(meta_type="LICENSE", value=license)

    def _has_description(self) -> bool:
        return self.description is not None

    def _set_description(self, description: str) -> None:
        if self._has_description():
            self.objects[0] = Comment(description)
        else:
            self.objects.insert(0, Comment(description))

    def _set_header_comment(self, *, prefix: str, value: str) -> None:
        comment = Comment(f"{prefix} {value}")
        for index, obj in enumerate(self.objects):
            if not isinstance(obj, Comment | MetaCommand):
                break
            if isinstance(obj, Comment) and obj.text.startswith(prefix):
                self.objects[index] = comment
                return
        self.objects.insert(self._header_insert_index(prefix), comment)

    def _header_insert_index(self, prefix: str) -> int:
        if prefix == "Author:":
            for index, obj in enumerate(self.objects):
                if not isinstance(obj, Comment | MetaCommand):
                    break
                if isinstance(obj, Comment) and obj.text.startswith("Name:"):
                    return index + 1
        return 1 if self._has_description() else 0

    def _set_header_meta(self, *, meta_type: str, value: str) -> None:
        meta = MetaCommand(meta_type, value)
        for index, obj in enumerate(self.objects):
            if not isinstance(obj, Comment | MetaCommand):
                break
            if isinstance(obj, MetaCommand) and obj.type == meta_type:
                self.objects[index] = meta
                return
        self.objects.insert(self._meta_insert_index(meta_type), meta)

    def _meta_insert_index(self, meta_type: str) -> int:
        """Index after the description, Name:/Author:, and earlier metas."""
        preceding_types = _MANAGED_META_TYPES[: _MANAGED_META_TYPES.index(meta_type)]
        index = 1 if self._has_description() else 0
        for position, obj in enumerate(self.objects):
            if not isinstance(obj, Comment | MetaCommand):
                break
            follows_comment = isinstance(obj, Comment) and obj.text.startswith(
                ("Name:", "Author:"),
            )
            follows_meta = isinstance(obj, MetaCommand) and obj.type in preceding_types
            if follows_comment or follows_meta:
                index = position + 1
        return index

    def add_submodel(
        self,
        submodel: Model,
        *,
        colour: Colour | int = MAIN_COLOUR_CODE,
        position: Vector | None = None,
        matrix: Matrix | None = None,
    ) -> Piece:
        """Register a submodel and append a type-1 piece referencing it.

        The submodel's own nested submodels are hoisted into this model's
        flat mapping, since serialization only walks one level. The same
        submodel object may be added repeatedly; each call appends another
        placement piece. A *different* model under an already-registered
        name still raises ``DuplicateSubmodelError``.
        """
        if not submodel.name:
            raise SubmodelNameRequiredError
        key = normalize_ref(submodel.name)
        incoming = {key: submodel, **submodel.submodels}
        for new_key, new_model in incoming.items():
            if new_key == normalize_ref(self.name):
                raise DuplicateSubmodelError(new_model.name)
            existing = self.submodels.get(new_key)
            if existing is not None and existing is not new_model:
                raise DuplicateSubmodelError(new_model.name)
        self.submodels.update(incoming)
        stem, suffix = split_reference(submodel.name)
        piece = Piece(
            colour=colour,
            position=position if position is not None else Vector(0, 0, 0),
            matrix=matrix if matrix is not None else Identity(),
            part=stem,
            suffix=suffix,
        )
        self.objects.append(piece)
        return piece

    def submodel_view(self, name: str) -> Model:
        """Return a submodel that resolves references against this root.

        Models taken straight from ``Model.submodels`` have an empty
        submodel table, so iterating them treats references to sibling
        submodels as leaf pieces. The returned model shares this root's
        submodel table instead, making ``iter_pieces``,
        ``bill_of_materials``, and ``find_pieces(recursive=True)`` expand
        nested references correctly. State reads and writes are forwarded to
        the selected model; references resolve through the original root.
        The private adapter inherits the selected class, preserving
        ``isinstance`` and custom traversal without copying subclass state.
        Descriptors bind to the view, with isolated cached properties.
        Shallow copies keep these bindings; deep copies and pickle preserve
        them in their copied graphs. View creation skips user subclass hooks.

        Raises ``UnknownSubmodelError`` for a name that is neither this
        model's nor one of its submodels'.
        """
        key = normalize_ref(name)
        root = _resolution_root(self)
        if key == normalize_ref(self.name):
            submodel = _selected_model(self)
        elif key == normalize_ref(root.name):
            submodel = root
        elif (submodel := root.submodels.get(key)) is None:
            raise UnknownSubmodelError(name)
        return _model_view(selected=submodel, root=root)

    def add_step(self) -> None:
        """Append a ``0 STEP`` marker ending the current building step."""
        self.objects.append(Comment("STEP"))

    def add_rotation_step(
        self,
        x: float,
        y: float,
        z: float,
        *,
        mode: RotationMode | str = "REL",
    ) -> None:
        """Append a canonical MLCad ``ROTSTEP`` instruction boundary."""
        from ldraw.instructions import RotationMode  # noqa: PLC0415
        from ldraw.serialization import format_ldraw_number  # noqa: PLC0415

        rotation_mode = (
            mode if isinstance(mode, RotationMode) else RotationMode(mode.upper())
        )
        if rotation_mode is RotationMode.END:
            msg = "Use end_rotation_steps() for a ROTSTEP END boundary"
            raise ValueError(msg)
        values = " ".join(format_ldraw_number(value) for value in (x, y, z))
        self.objects.append(Comment(f"ROTSTEP {values} {rotation_mode.value}"))

    def end_rotation_steps(self) -> None:
        """Append ``0 ROTSTEP END`` and restore the default instruction view."""
        self.objects.append(Comment("ROTSTEP END"))

    def instruction_document(
        self,
        *,
        parts: Parts | None = None,
    ) -> InstructionDocument:
        """Interpret this model and its reachable submodels as instructions."""
        from ldraw.instructions import InstructionDocument  # noqa: PLC0415

        return InstructionDocument.from_model(self, parts=parts)

    def iter_instruction_steps(self) -> Iterator[InstructionStep]:
        """Yield this model section's semantic instruction steps.

        This convenience method constructs the complete instruction document,
        including reachable and orphan sections. Callers that need to inspect
        steps repeatedly should build :meth:`instruction_document` once and
        reuse its ``root.steps`` tuple.
        """
        yield from self.instruction_document().root.steps

    @property
    def steps(self) -> list[list[Piece]]:
        """Pieces grouped by ``0 STEP`` markers.

        Pieces after the last marker form a final step, so a model without
        any ``0 STEP`` lines is a single step. A trailing marker does not
        produce an empty step. Submodel references are not expanded.
        """
        groups: list[list[Piece]] = [[]]
        for obj in self.objects:
            if isinstance(obj, Comment) and obj.text.strip().upper() == "STEP":
                groups.append([])
            elif isinstance(obj, Piece):
                groups[-1].append(obj)
        while len(groups) > 1 and not groups[-1]:
            groups.pop()
        return groups

    def iter_pieces(self) -> Iterator[Piece]:
        """Recursively yield leaf pieces, expanding submodel references.

        References are resolved against *this* model's submodel table. A
        model taken straight from ``Model.submodels`` has an empty table,
        so references to sibling submodels are silently yielded as if they
        were leaf pieces — inspect a submodel through
        ``root.submodel_view(name)`` instead.
        """
        return _iter_model_pieces(
            root=_resolution_root(self),
            model=_selected_model(self),
            visiting=frozenset(),
        )

    def iter_occurrences(
        self,
        *,
        expand_submodels: bool = True,
        include_steps: bool = True,
    ) -> Iterator[ModelOccurrence]:
        """Yield placed part occurrences with transform and source context."""
        return _occurrences_at_origin(
            model=self,
            expand_submodels=expand_submodels,
            include_steps=include_steps,
            on_cycle=_cycle_callback(self),
        )

    def bill_of_materials(self, *, parts: Parts | None = None) -> list[BomRow]:
        """Count leaf pieces by part and colour, expanding submodel references.

        Colour 16 (the main colour) inside a submodel is resolved to the
        colour the submodel was placed with. As with ``iter_pieces``,
        submodel references only resolve against this model's own submodel
        table; to count a single submodel of a larger model, call this on
        ``root.submodel_view(name)``. Built-in expansion skips cyclic references;
        custom overrides delegating to ``super()`` inherit that tolerance.
        Other custom exceptions propagate.
        """
        from ldraw.bom import bill_of_materials  # noqa: PLC0415

        return bill_of_materials(self, parts=parts)

    def find_pieces(
        self,
        *,
        part: str | None = None,
        colour: Colour | int | None = None,
        recursive: bool = False,
    ) -> list[Piece]:
        """Return pieces matching the given part code and/or colour.

        Part codes are compared case-insensitively.
        """
        source: Iterable[Piece] = self.iter_pieces() if recursive else self.pieces
        wanted_part = part.casefold() if part is not None else None
        return [
            piece
            for piece in source
            if (wanted_part is None or piece.part.casefold() == wanted_part)
            and (colour is None or piece.colour == colour)
        ]

    def to_ldraw(self) -> str:
        """Serialize the model (and any submodels) to LDraw text."""
        return _models_ldraw(
            models=_serialization_models(model=self), mpd=bool(self.submodels)
        )

    def __str__(self) -> str:
        return self.to_ldraw()

    def save(self, path: Path | str) -> None:
        """Write the model to a file, with a trailing newline."""
        text = self.to_ldraw()
        Path(path).write_text(
            f"{text}\n" if text else "",
            encoding="utf-8",
            newline="\n",
        )


def _serialized(obj: ParsedObject) -> str:
    """Serialize one object, rejecting comments that re-parse as MPD structure."""
    line = obj.to_ldraw()
    if isinstance(obj, Comment) and (
        ldraw_file_name(line) is not None or _is_nofile(line)
    ):
        raise StructuralCommentError(obj.text)
    return line


def _serialization_models(*, model: Model) -> Iterator[Model]:
    """Keep the selected section authoritative and reject conflicting dependencies."""
    registry = _DefinitionRegistry(
        selected=model,
        aliases=model._serialization_aliases(),  # noqa: SLF001
    )
    yield model
    for dependency in model.submodels.values():
        if registry.register(dependency):
            yield dependency


def _models_ldraw(*, models: Iterable[Model], mpd: bool) -> str:
    """Emit definitions already validated by their collecting registry."""
    sections: list[str] = []
    for model in models:
        if not mpd:
            return "\n".join(_serialized(obj) for obj in model.objects)
        if not model.name:
            raise SubmodelNameRequiredError
        sections.append(
            "\n".join(
                (
                    f"0 FILE {model.name}",
                    *(_serialized(obj) for obj in model.objects),
                    "0 NOFILE",
                ),
            ),
        )
    return "\n".join(sections)


def _iter_model_pieces(
    root: Model,
    model: Model,
    visiting: frozenset[str],
) -> Iterator[Piece]:
    """Yield leaf pieces of ``model``, resolving references against ``root``."""
    key = normalize_ref(model.name)
    if key in visiting:
        raise SubmodelCycleError(model.name)
    frames = [
        _ReferenceFrame(
            model=model, pieces=iter(model.pieces), visiting=visiting | {key}
        )
    ]
    while frames:
        frame = frames[-1]
        if (piece := next(frame.pieces, None)) is None:
            frames.pop()
            continue
        target = _resolve_reference(root=root, piece=piece, context=None)
        if target is None:
            yield piece
            continue
        _cycle_target(
            source=frame.model,
            piece=piece,
            target=target,
            visiting=frame.visiting,
            on_cycle=None,
        )
        frames.append(
            _ReferenceFrame(
                model=target,
                pieces=iter(target.pieces),
                visiting=frame.visiting | {normalize_ref(target.name)},
            )
        )


def _iter_occurrences_skip_cycles(
    model: Model,
    *,
    expand_submodels: bool = True,
    include_steps: bool = True,
    diagnostics: list[Diagnostic] | None = None,
) -> Iterator[ModelOccurrence]:
    """Yield occurrences, skipping re-entry into in-progress submodels.

    Used by analysis, summary, and BOM paths for built-in expansion and
    custom overrides delegating to it. Other custom exceptions propagate.
    Each skipped cyclic reference appends an
    ``MPD_CYCLE`` diagnostic to ``diagnostics`` when a list is given.
    """

    def record(source: Model, piece: Piece, target: Model) -> None:
        if diagnostics is None:
            return
        error = SubmodelCycleError(target.name)
        diagnostics.append(
            Diagnostic(
                line_number=source.source_line_for(piece),
                message=error.message,
                code=DiagnosticCode.MPD_CYCLE,
                section=source.name or None,
                offending_value=piece.reference,
                cause=error,
            ),
        )

    if _uses_builtin_occurrences(model):
        return _occurrences_at_origin(
            model=model,
            expand_submodels=expand_submodels,
            include_steps=include_steps,
            on_cycle=record,
        )
    return _iter_cycle_tolerant_occurrences(
        model=model,
        expand_submodels=expand_submodels,
        include_steps=include_steps,
        on_cycle=record,
    )


def _occurrences_at_origin(  # noqa: PLR0913 - traversal flags and initial ancestry
    *,
    model: Model,
    expand_submodels: bool,
    include_steps: bool,
    on_cycle: Callable[[Model, Piece, Model], None] | None,
    cycle_leaf: bool = False,
    visiting: frozenset[str] = frozenset(),
) -> Iterator[ModelOccurrence]:
    """Share public and cycle-tolerant expansion's identity-origin setup."""
    return _iter_model_occurrences(
        root=_resolution_root(model),
        model=_selected_model(model),
        position=Vector(0, 0, 0),
        matrix=Identity(),
        inherited_colour=None,
        visiting=visiting,
        inherited_step=None,
        path=(),
        expand_submodels=expand_submodels,
        include_steps=include_steps,
        on_cycle=on_cycle,
        cycle_leaf=cycle_leaf,
    )


def _uses_builtin_occurrences(model: Model) -> bool:
    """Keep legacy public override compatibility dispatch in one place."""
    return getattr(model.iter_occurrences, "__func__", None) is Model.iter_occurrences


def _iter_inventory_occurrences(
    model: Model, *, context: ModelValidationContext
) -> Iterator[ModelOccurrence]:
    """Use validated root placements as world coordinates at the identity origin."""
    context.ensure_validated(
        root=model,
        reachable_only=model._is_submodel_view,  # noqa: SLF001
    )
    section = _selected_model(model)
    return _iter_occurrences_at_placements(
        root=_resolution_root(model),
        model=section,
        placements=_iter_root_placements(section, context=context),
        inherited_colour=None,
        visiting=frozenset(),
        inherited_step=None,
        path=(),
        expand_submodels=True,
        include_steps=False,
        context=context,
    )


def _iter_root_placements(
    model: Model, *, context: ModelValidationContext
) -> Iterator[tuple[Piece, int | None, Vector, Matrix]]:
    """Read validated world placements at the comparison's identity origin."""
    for piece in model.objects:
        if isinstance(piece, Piece):
            yield piece, None, *context.placement(model=model, piece=piece)


@dataclass(slots=True)
class _AuditFrame:
    model: Model
    edges: Iterator[tuple[Piece, Model]]
    position: Vector
    matrix: Matrix
    visiting: frozenset[str]
    at_origin: bool = False


def _audit_inventory_transforms(
    model: Model, *, context: ModelValidationContext
) -> None:
    """Audit composed submodel edges with an explicit depth-first stack."""
    if not model.submodels and not context.has_external_resolution():
        return
    selected = _selected_model(model)
    frames = [
        _AuditFrame(
            model=selected,
            edges=iter(context.edges(root=model, section=selected)),
            position=Vector(x=0, y=0, z=0),
            matrix=Identity(),
            visiting=frozenset({normalize_ref(selected.name)}),
            at_origin=True,
        )
    ]
    while frames:
        frame = frames[-1]
        if (edge := next(frame.edges, None)) is None:
            frames.pop()
            continue
        piece, resolved = edge
        effective = context.placement(model=frame.model, piece=piece)
        position, matrix = (
            effective
            if frame.at_origin
            else _compose_placement(
                model=frame.model,
                piece=piece,
                position=frame.position,
                matrix=frame.matrix,
                effective=effective,
                context=context,
            )
        )
        target = _cycle_target(
            source=frame.model,
            piece=piece,
            target=resolved,
            visiting=frame.visiting,
            on_cycle=_ignore_cycle,
        )
        if target is not None:
            frames.append(
                _AuditFrame(
                    model=target,
                    edges=iter(context.edges(root=model, section=target)),
                    position=position,
                    matrix=matrix,
                    visiting=frame.visiting | {normalize_ref(target.name)},
                )
            )


def _iter_model_occurrences(  # noqa: PLR0913 - explicit traversal state
    *,
    root: Model,
    model: Model,
    position: Vector,
    matrix: Matrix,
    inherited_colour: Colour | None,
    visiting: frozenset[str],
    inherited_step: int | None,
    path: tuple[OccurrencePathItem, ...],
    expand_submodels: bool,
    include_steps: bool,
    on_cycle: Callable[[Model, Piece, Model], None] | None = None,
    context: ModelValidationContext | None = None,
    cycle_leaf: bool = False,
) -> Iterator[ModelOccurrence]:
    """Compose the supplied parent transform and traverse resulting placements."""
    return _iter_occurrences_at_placements(
        root=root,
        model=model,
        placements=_iter_composed_placements(
            model=model,
            position=position,
            matrix=matrix,
            include_steps=include_steps,
            context=context,
        ),
        inherited_colour=inherited_colour,
        visiting=visiting,
        inherited_step=inherited_step,
        path=path,
        expand_submodels=expand_submodels,
        include_steps=include_steps,
        on_cycle=on_cycle,
        context=context,
        cycle_leaf=cycle_leaf,
    )


def _iter_composed_placements(
    *,
    model: Model,
    position: Vector,
    matrix: Matrix,
    include_steps: bool,
    context: ModelValidationContext | None,
) -> Iterator[tuple[Piece, int | None, Vector, Matrix]]:
    """Compose each source placement, checking world values for comparison."""
    for piece, source_step in _iter_piece_steps(model, include_steps=include_steps):
        effective = (
            context.placement(model=model, piece=piece)
            if context is not None
            else piece._transformed()  # noqa: SLF001
        )
        yield (
            piece,
            source_step,
            *_compose_placement(
                model=model,
                piece=piece,
                position=position,
                matrix=matrix,
                effective=effective,
                context=context,
            ),
        )


def _compose_placement(  # noqa: PLR0913 - explicit transform context
    *,
    model: Model,
    piece: Piece,
    position: Vector,
    matrix: Matrix,
    effective: tuple[Vector, Matrix],
    context: ModelValidationContext | None,
) -> tuple[Vector, Matrix]:
    piece_position, piece_matrix = effective
    world_position = position + matrix * piece_position
    world_matrix = matrix * piece_matrix
    if context is not None:
        _composition_check()(
            model=model,
            piece=piece,
            position=world_position,
            matrix=world_matrix,
        )
    return world_position, world_matrix


@cache
def _composition_check() -> Callable[..., None]:
    """Load the cycle-safe numeric checker once, only for checked traversal."""
    from ldraw.validation import _check_composed_placement  # noqa: PLC0415

    return _check_composed_placement


def _ignore_cycle(source: Model, piece: Piece, target: Model) -> None:
    """Stop cyclic audit re-entry without classifying source structure."""


def _cycle_target(  # noqa: PLR0913 - cycle callback and instruction leaf policy
    *,
    source: Model,
    piece: Piece,
    target: Model,
    visiting: frozenset[str],
    on_cycle: Callable[[Model, Piece, Model], None] | None,
    cycle_leaf: bool = False,
) -> Model | None:
    """Share cycle handling between occurrence expansion and numeric audits."""
    if normalize_ref(target.name) not in visiting:
        return target
    if on_cycle is not None:
        on_cycle(source, piece, target)
    elif not cycle_leaf:
        raise SubmodelCycleError(target.name)
    return None


@dataclass(slots=True)
class _OccurrenceFrame:
    model: Model
    placements: Iterator[tuple[Piece, int | None, Vector, Matrix]]
    colour: Colour | None
    visiting: frozenset[str]
    step: int | None
    path: tuple[OccurrencePathItem, ...]


def _placement_state(
    *,
    frame: _OccurrenceFrame,
    piece: Piece,
    source_step: int | None,
) -> tuple[int | None, Colour, tuple[OccurrencePathItem, ...]]:
    """Prepare inherited metadata shared by leaves and submodel placements."""
    step = frame.step if frame.step is not None else source_step
    colour = _effective_colour(colour=piece.colour, inherited=frame.colour)
    path = (
        *frame.path,
        OccurrencePathItem(
            model=frame.model,
            piece=piece,
            source_line=frame.model.source_line_for(piece),
            local_step=source_step,
            effective_step=step,
        ),
    )
    return step, colour, path


def _descendant_frame(  # noqa: PLR0913 - explicit traversal state
    *,
    parent: _OccurrenceFrame,
    target: Model,
    position: Vector,
    matrix: Matrix,
    include_steps: bool,
    context: ModelValidationContext | None,
    colour: Colour,
    step: int | None,
    path: tuple[OccurrencePathItem, ...],
) -> _OccurrenceFrame:
    return _OccurrenceFrame(
        model=target,
        placements=iter(
            _iter_composed_placements(
                model=target,
                position=position,
                matrix=matrix,
                include_steps=include_steps,
                context=context,
            )
        ),
        colour=colour,
        visiting=parent.visiting | {normalize_ref(target.name)},
        step=step,
        path=path,
    )


def _iter_occurrences_at_placements(  # noqa: PLR0913 - explicit traversal state
    *,
    root: Model,
    model: Model,
    placements: Iterable[tuple[Piece, int | None, Vector, Matrix]],
    inherited_colour: Colour | None,
    visiting: frozenset[str],
    inherited_step: int | None,
    path: tuple[OccurrencePathItem, ...],
    expand_submodels: bool,
    include_steps: bool,
    on_cycle: Callable[[Model, Piece, Model], None] | None = None,
    context: ModelValidationContext | None = None,
    cycle_leaf: bool = False,
) -> Iterator[ModelOccurrence]:
    """Expand world placements iteratively, preserving depth-first event order."""
    frames = [
        _OccurrenceFrame(
            model=model,
            placements=iter(placements),
            colour=inherited_colour,
            visiting=visiting | {normalize_ref(model.name)},
            step=inherited_step,
            path=path,
        )
    ]
    while frames:
        frame = frames[-1]
        if (placement := next(frame.placements, None)) is None:
            frames.pop()
            continue
        piece, source_step, position, matrix = placement
        step, colour, event_path = _placement_state(
            frame=frame,
            piece=piece,
            source_step=source_step,
        )
        resolved = target = None
        if expand_submodels:
            resolved = _resolve_reference(root=root, piece=piece, context=context)
        if resolved is not None:
            target = _cycle_target(
                source=frame.model,
                piece=piece,
                target=resolved,
                visiting=frame.visiting,
                on_cycle=on_cycle,
                cycle_leaf=cycle_leaf,
            )
        if resolved is not None and target is None and not cycle_leaf:
            continue
        if target is not None:
            frames.append(
                _descendant_frame(
                    parent=frame,
                    target=target,
                    position=position,
                    matrix=matrix,
                    include_steps=include_steps,
                    context=context,
                    colour=colour,
                    step=step,
                    path=event_path,
                )
            )
        else:
            yield ModelOccurrence(
                piece=piece,
                part_code=_default_leaf_identity(piece),
                reference=piece.reference,
                colour=colour,
                position=position,
                matrix=matrix,
                source_model=frame.model,
                source_line=event_path[-1].source_line,
                step=step,
                source_step=source_step,
                path=event_path,
            )


def _iter_piece_steps(
    model: Model,
    *,
    include_steps: bool,
) -> Iterator[tuple[Piece, int | None]]:
    step = 1
    for obj in model.objects:
        if (
            include_steps
            and isinstance(obj, Comment)
            and obj.text.strip().upper() == "STEP"
        ):
            step += 1
        elif isinstance(obj, Piece):
            yield obj, step if include_steps else None


def _effective_colour(*, colour: Colour, inherited: Colour | None) -> Colour:
    if colour.code == MAIN_COLOUR_CODE and inherited is not None:
        return inherited
    return colour


def _source_path(source: Path | str | None) -> Path | None:
    return None if source is None else Path(source)


def _split_sections_report(
    text: str,
    *,
    source: Path | str | None,
) -> tuple[list[_NumberedLine], list[_RawSection], list[Diagnostic], bool]:
    """Split MPD structure while retaining diagnostics instead of aborting."""
    preamble: list[_NumberedLine] = []
    sections: list[_RawSection] = []
    diagnostics: list[Diagnostic] = []
    current: list[_NumberedLine] | None = preamble
    complete = True
    path = _source_path(source)
    for number, line in enumerate(text.splitlines(), start=1):
        if (name := ldraw_file_name(line)) is not None:
            sections.append(_RawSection(name=name, line_number=number))
            current = sections[-1].lines
        elif _is_nofile(line):
            if not sections:
                error = MisplacedNofileError(
                    source=str(source) if source is not None else "<string>",
                    line_number=number,
                )
                diagnostics.append(
                    Diagnostic(
                        line_number=number,
                        message=error.message,
                        code=DiagnosticCode.MPD_MISPLACED_NOFILE,
                        path=path,
                        offending_value=line,
                        cause=error,
                    ),
                )
                complete = False
            else:
                current = None
        elif current is not None:
            current.append((number, line))
        elif line.strip():
            # The MPD spec ignores such lines, so a spec-legal file must
            # stay valid: report the dropped content as a warning only.
            diagnostics.append(
                Diagnostic(
                    line_number=number,
                    message="content after 0 NOFILE is ignored until the next section",
                    severity=Severity.WARNING,
                    code=DiagnosticCode.MPD_CONTENT_AFTER_NOFILE,
                    path=path,
                    offending_value=line,
                ),
            )
            complete = False
    return preamble, sections, diagnostics, complete


def _parse_error_diagnostic(
    error: BaseException,
    *,
    number: int,
    line: str,
    source: Path | str | None,
    section: str | None,
) -> Diagnostic:
    match error:
        case InvalidNumericValueError():
            code = DiagnosticCode.PARSE_INVALID_NUMERIC
            offending_value: object = error.token
        case InvalidColourValueError():
            code = DiagnosticCode.PARSE_INVALID_COLOUR
            offending_value = error.token
        case _:
            code = DiagnosticCode.PARSE_INVALID_LINE
            offending_value = line
    message = getattr(error, "message", str(error))
    return Diagnostic(
        line_number=number,
        message=" ".join(str(message).splitlines()),
        code=code,
        path=_source_path(source),
        section=section,
        offending_value=offending_value,
        cause=error,
    )


def _parse_objects_report(
    numbered_lines: Iterable[_NumberedLine],
    *,
    source: Path | str | None,
    section: str | None,
) -> tuple[
    list[ParsedObject],
    dict[Piece, int],
    dict[int, int],
    list[Diagnostic],
    bool,
]:
    objects: list[ParsedObject] = []
    source_lines: dict[Piece, int] = {}
    object_source_lines: dict[int, int] = {}
    diagnostics: list[Diagnostic] = []
    complete = True
    for number, line in numbered_lines:
        try:
            parsed = parse_ldraw_line(line)
        except (PartError, ValueError) as error:
            diagnostics.append(
                _parse_error_diagnostic(
                    error,
                    number=number,
                    line=line,
                    source=source,
                    section=section,
                ),
            )
            complete = False
            continue
        if parsed is None:
            continue
        objects.append(parsed)
        object_source_lines[id(parsed)] = number
        if isinstance(parsed, Piece):
            source_lines[parsed] = number
    return objects, source_lines, object_source_lines, diagnostics, complete


@dataclass(slots=True)
class _ReferenceFrame:
    model: Model
    pieces: Iterator[Piece]
    visiting: frozenset[str]


def _iter_reference_edges(
    *,
    root: Model,
    context: ModelValidationContext | None = None,
    descend: Callable[[Model], bool] | None = None,
) -> Iterator[tuple[Model, Piece, Model | None, bool]]:
    """Inspect each source placement and mark all cyclic edges in stable order."""
    return iter_structure_edges(root=root, context=context, descend=descend)


def _model_structure_diagnostics(
    root: Model,
    *,
    path: Path | None,
    context: ModelValidationContext | None = None,
) -> list[Diagnostic]:
    """Keep structural diagnostics depth-first without Python recursion."""
    diagnostics: list[Diagnostic] = []
    emitted_sources: set[tuple[int, int]] = set()
    for model, piece, target, closing in _iter_reference_edges(
        root=root, context=context
    ):
        if target is not None and not closing:
            continue
        marker = id(_selected_model(model)), id(piece)
        if marker in emitted_sources:
            continue
        emitted_sources.add(marker)
        line_number = model.source_line_for(piece)
        if target is None:
            _, suffix = split_reference(piece.reference)
            if suffix.casefold() in SUBMODEL_SUFFIXES:
                diagnostics.append(
                    Diagnostic(
                        line_number=line_number,
                        message=f"unresolved submodel {piece.reference}",
                        severity=Severity.WARNING,
                        code=DiagnosticCode.MPD_UNRESOLVED_SUBMODEL,
                        path=path,
                        section=model.name or None,
                        offending_value=piece.reference,
                    )
                )
        elif closing:
            error = SubmodelCycleError(target.name)
            diagnostics.append(
                Diagnostic(
                    line_number=line_number,
                    message=error.message,
                    code=DiagnosticCode.MPD_CYCLE,
                    path=path,
                    section=model.name or None,
                    offending_value=piece.reference,
                    cause=error,
                )
            )
    return diagnostics


def _validation_diagnostics(
    root: Model,
    *,
    parts: Parts | None,
    path: Path | None,
    context: ModelValidationContext | None = None,
) -> list[Diagnostic]:
    from ldraw.validation import _iter_section_issues  # noqa: PLC0415

    submodels = {normalize_ref(root.name), *root.submodels}
    structural = _model_structure_diagnostics(root, path=path, context=context)
    unresolved_references = {
        (diagnostic.section, diagnostic.line_number)
        for diagnostic in structural
        if diagnostic.code is DiagnosticCode.MPD_UNRESOLVED_SUBMODEL
    }
    diagnostics: list[Diagnostic] = []
    for section_model in (root, *root.submodels.values()):
        diagnostics.extend(
            issue
            for issue in _iter_section_issues(
                section_model,
                parts=parts,
                submodels=submodels,
                path=path,
                context=context,
            )
            # A structurally unresolved reference is not also unknown.
            if not (
                issue.code is DiagnosticCode.MODEL_UNKNOWN_PART
                and (issue.section, issue.line_number) in unresolved_references
            )
        )
    diagnostics.extend(structural)
    return diagnostics


def parse_model_result(
    text: str,
    *,
    name: str = "",
    source: Path | str | None = None,
    parts: Parts | None = None,
    tolerant: bool = True,
) -> ModelLoadResult:
    """Parse and validate text once, optionally retaining a partial model."""
    return _parse_model_result(
        text,
        name=name,
        source=source,
        parts=parts,
        tolerant=tolerant,
    )


def _parse_model_result(  # noqa: PLR0913 - report inputs plus optional invocation analysis
    text: str,
    *,
    name: str,
    source: Path | str | None,
    parts: Parts | None,
    tolerant: bool,
    context: ModelValidationContext | None = None,
) -> ModelLoadResult:
    """Build a report, optionally retaining source analysis for this invocation."""
    if not tolerant:
        try:
            model = parse_model(text, name=name, source=source)
        except (PartError, ValueError):
            # Re-derive diagnostics tolerantly so strict failures report
            # the same codes and line numbers as tolerant mode, then
            # discard the partial model.
            report = _parse_model_result(
                text,
                name=name,
                source=source,
                parts=parts,
                tolerant=True,
                context=context,
            )
            return ModelLoadResult(
                model=None,
                diagnostics=report.diagnostics,
                complete=False,
            )
        diagnostics = _validation_diagnostics(
            model,
            parts=parts,
            path=_source_path(source),
            context=context,
        )
        return ModelLoadResult(model, tuple(diagnostics), complete=True)

    preamble, sections, diagnostics, complete = _split_sections_report(
        text,
        source=source,
    )
    unique_sections: list[_RawSection] = []
    seen: set[str] = set()
    for section in sections:
        key = normalize_ref(section.name)
        if key in seen:
            error = DuplicateSubmodelError(section.name)
            diagnostics.append(
                Diagnostic(
                    line_number=section.line_number,
                    message=error.message,
                    code=DiagnosticCode.MPD_DUPLICATE_SECTION,
                    path=_source_path(source),
                    section=section.name,
                    offending_value=section.name,
                    cause=error,
                ),
            )
            complete = False
            continue
        seen.add(key)
        unique_sections.append(section)

    model, parse_diagnostics, parsed_all = _reported_model(
        preamble=preamble, sections=unique_sections, name=name, source=source
    )
    diagnostics.extend(parse_diagnostics)
    complete = complete and parsed_all

    diagnostics.extend(
        _validation_diagnostics(
            model,
            parts=parts,
            path=_source_path(source),
            context=context,
        ),
    )
    return ModelLoadResult(
        model=model,
        diagnostics=tuple(diagnostics),
        complete=complete,
    )


def _reported_model(
    *,
    preamble: list[_NumberedLine],
    sections: list[_RawSection],
    name: str,
    source: Path | str | None,
) -> tuple[Model, list[Diagnostic], bool]:
    """Build report sections while retaining each object's source location."""
    first, *rest = sections or [_RawSection(name=name)]
    objects, source_lines, object_lines, diagnostics, complete = _parse_objects_report(
        [*preamble, *first.lines], source=source, section=first.name or None
    )
    root = Model(
        name=first.name,
        objects=objects,
        _source_lines=source_lines,
        _object_source_lines=object_lines,
    )
    for section in rest:
        objects, source_lines, object_lines, issues, parsed_all = _parse_objects_report(
            section.lines, source=source, section=section.name
        )
        root.submodels[normalize_ref(section.name)] = Model(
            name=section.name,
            objects=objects,
            _source_lines=source_lines,
            _object_source_lines=object_lines,
        )
        diagnostics.extend(issues)
        complete = complete and parsed_all
    return root, diagnostics, complete


def parse_model(
    text: str,
    *,
    name: str = "",
    source: Path | str | None = None,
) -> Model:
    """Parse LDraw document text into a Model.

    A document without ``0 FILE`` sections becomes a single model. In an MPD
    document the first section becomes the returned root model and later
    sections become its submodels, resolvable via ``Model.submodel_for``.
    """
    preamble, sections = _split_sections(text, source=source)
    objects, source_lines, object_source_lines = _parse_objects(
        preamble,
        source=source,
    )
    if not sections:
        return Model(
            name=name,
            objects=objects,
            _source_lines=source_lines,
            _object_source_lines=object_source_lines,
        )
    first, *rest = sections
    first_objects, first_source_lines, first_object_source_lines = _parse_objects(
        first.lines,
        source=source,
    )
    root = Model(
        name=first.name,
        objects=[*objects, *first_objects],
        _source_lines={**source_lines, **first_source_lines},
        _object_source_lines={
            **object_source_lines,
            **first_object_source_lines,
        },
    )
    for section in rest:
        key = normalize_ref(section.name)
        if key == normalize_ref(root.name) or key in root.submodels:
            raise DuplicateSubmodelError(section.name)
        (
            section_objects,
            section_source_lines,
            section_object_source_lines,
        ) = _parse_objects(section.lines, source=source)
        root.submodels[key] = Model(
            name=section.name,
            objects=section_objects,
            _source_lines=section_source_lines,
            _object_source_lines=section_object_source_lines,
        )
    return root


def read_model(path: Path | str) -> Model:
    """Read a ``.ldr`` or ``.mpd`` file into a Model."""
    file_path = Path(path)
    return parse_model(
        file_path.read_text(encoding="utf-8-sig"),
        name=file_path.name,
        source=file_path,
    )


def load_model(
    path: Path | str,
    parts: Parts | None = None,
    *,
    tolerant: bool = True,
) -> ModelLoadResult:
    """Read, parse, and validate a model without throwing for data failures."""
    return _load_model(path, parts=parts, tolerant=tolerant)


def _load_inventory_model(
    path: Path,
) -> tuple[ModelLoadResult, ModelValidationContext]:
    """Load a report and source analysis for immediate inventory preparation."""
    context = ModelValidationContext()
    report = _load_model(path, parts=None, tolerant=True, context=context)
    if report.model is not None and report.complete and report.valid:
        context.mark_validated(root=report.model, reachable_only=False)
    return report, context


def _load_model(
    path: Path | str,
    *,
    parts: Parts | None,
    tolerant: bool,
    context: ModelValidationContext | None = None,
) -> ModelLoadResult:
    """Share file reading between public loading and comparison report loading."""
    file_path = Path(path)
    try:
        data = file_path.read_bytes()
    except OSError as error:
        return ModelLoadResult(
            model=None,
            diagnostics=(
                Diagnostic(
                    message=f"could not read model: {error}",
                    code=DiagnosticCode.IO_READ_FAILED,
                    path=file_path,
                    cause=error,
                ),
            ),
            complete=False,
        )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        return ModelLoadResult(
            model=None,
            diagnostics=(
                Diagnostic(
                    message=f"model is not valid UTF-8 text: {error}",
                    code=DiagnosticCode.IO_DECODE_FAILED,
                    path=file_path,
                    offending_value=data[error.start : error.end],
                    cause=error,
                ),
            ),
            complete=False,
        )
    return _parse_model_result(
        text,
        name=file_path.name,
        source=file_path,
        parts=parts,
        tolerant=tolerant,
        context=context,
    )
