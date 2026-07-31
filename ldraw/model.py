"""Reading and writing whole LDraw model files (.ldr and .mpd)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Self

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
from ldraw.pieces import MAIN_COLOUR_CODE, Piece
from ldraw.utils import ldraw_file_name, normalize_ref, split_reference

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

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
        """Compatibility spelling for the placement's local source step."""
        return self.local_step


@dataclass(frozen=True, slots=True, eq=False)
class ModelOccurrence:
    """One placed leaf part occurrence in a model.

    Occurrences are traversal events: two placements of the same submodel
    produce distinct occurrences, so they compare and hash by identity.
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
        nested references correctly. It is a live view — its objects and
        submodel table are shared with this model, not copied.

        Raises ``UnknownSubmodelError`` for a name that is neither this
        model's nor one of its submodels'.
        """
        key = normalize_ref(name)
        if key == normalize_ref(self.name):
            return self
        if (submodel := self.submodels.get(key)) is None:
            raise UnknownSubmodelError(name)
        return Model(
            name=submodel.name,
            objects=submodel.objects,
            submodels=self.submodels,
            _source_lines=submodel._source_lines,  # noqa: SLF001 - same class
            _object_source_lines=submodel._object_source_lines,  # noqa: SLF001
        )

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
        return _iter_model_pieces(root=self, model=self, visiting=frozenset())

    def iter_occurrences(
        self,
        *,
        expand_submodels: bool = True,
        include_steps: bool = True,
    ) -> Iterator[ModelOccurrence]:
        """Yield placed part occurrences with transform and source context."""
        return _iter_model_occurrences(
            root=self,
            model=self,
            position=Vector(0, 0, 0),
            matrix=Identity(),
            inherited_colour=None,
            visiting=frozenset(),
            inherited_step=None,
            path=(),
            expand_submodels=expand_submodels,
            include_steps=include_steps,
        )

    def bill_of_materials(self, *, parts: Parts | None = None) -> list[BomRow]:
        """Count leaf pieces by part and colour, expanding submodel references.

        Colour 16 (the main colour) inside a submodel is resolved to the
        colour the submodel was placed with. As with ``iter_pieces``,
        submodel references only resolve against this model's own submodel
        table; to count a single submodel of a larger model, call this on
        ``root.submodel_view(name)``.
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
        if not self.submodels:
            return "\n".join(_serialized(obj) for obj in self.objects)
        sections: list[str] = []
        for model in (self, *self.submodels.values()):
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


def _iter_model_pieces(
    root: Model,
    model: Model,
    visiting: frozenset[str],
) -> Iterator[Piece]:
    """Yield leaf pieces of ``model``, resolving references against ``root``."""
    key = normalize_ref(model.name)
    if key in visiting:
        raise SubmodelCycleError(model.name)
    visiting = visiting | {key}
    for piece in model.pieces:
        target = root.submodel_for(piece)
        if target is None:
            yield piece
        else:
            yield from _iter_model_pieces(root=root, model=target, visiting=visiting)


def _iter_model_occurrences(  # noqa: PLR0913 - traversal state is explicit
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
) -> Iterator[ModelOccurrence]:
    """Yield leaf occurrences of ``model``, resolving references against ``root``."""
    key = normalize_ref(model.name)
    if key in visiting:
        raise SubmodelCycleError(model.name)
    visiting = visiting | {key}
    for piece, source_step in _iter_piece_steps(model, include_steps=include_steps):
        piece_position, piece_matrix = piece._transformed()  # noqa: SLF001
        world_position = position + matrix * piece_position
        world_matrix = matrix * piece_matrix
        occurrence_step = inherited_step if inherited_step is not None else source_step
        colour = _effective_colour(piece.colour, inherited_colour)
        occurrence_path = (
            *path,
            OccurrencePathItem(
                model=model,
                piece=piece,
                source_line=model.source_line_for(piece),
                local_step=source_step,
                effective_step=occurrence_step,
            ),
        )
        target = root.submodel_for(piece) if expand_submodels else None
        if target is not None:
            yield from _iter_model_occurrences(
                root=root,
                model=target,
                position=world_position,
                matrix=world_matrix,
                inherited_colour=colour,
                visiting=visiting,
                inherited_step=occurrence_step,
                path=occurrence_path,
                expand_submodels=expand_submodels,
                include_steps=include_steps,
            )
            continue
        yield ModelOccurrence(
            piece=piece,
            part_code=piece.part,
            reference=piece.reference,
            colour=colour,
            position=world_position,
            matrix=world_matrix,
            source_model=model,
            source_line=model.source_line_for(piece),
            step=occurrence_step,
            source_step=source_step,
            path=occurrence_path,
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


def _effective_colour(colour: Colour, inherited: Colour | None) -> Colour:
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
            diagnostics.append(
                Diagnostic(
                    line_number=number,
                    message="content after 0 NOFILE is ignored until the next section",
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


def _model_structure_diagnostics(root: Model, *, path: Path | None) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    emitted_cycles: set[tuple[str, int | None]] = set()

    def walk(model: Model, visiting: tuple[str, ...]) -> None:
        key = normalize_ref(model.name)
        next_visiting = (*visiting, key)
        for piece in model.pieces:
            target = root.submodel_for(piece)
            line_number = model.source_line_for(piece)
            if target is None:
                _, suffix = split_reference(piece.reference)
                if suffix.casefold() in {".ldr", ".mpd"}:
                    diagnostics.append(
                        Diagnostic(
                            line_number=line_number,
                            message=f"unresolved submodel {piece.reference}",
                            code=DiagnosticCode.MPD_UNRESOLVED_SUBMODEL,
                            path=path,
                            section=model.name or None,
                            offending_value=piece.reference,
                        ),
                    )
                continue
            target_key = normalize_ref(target.name)
            if target_key in next_visiting:
                marker = (target_key, line_number)
                if marker not in emitted_cycles:
                    emitted_cycles.add(marker)
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
                        ),
                    )
                continue
            walk(target, next_visiting)

    walk(root, ())
    return diagnostics


def _validation_diagnostics(
    root: Model,
    *,
    parts: Parts | None,
    path: Path | None,
) -> list[Diagnostic]:
    from ldraw.validation import iter_object_issues  # noqa: PLC0415

    submodels = {normalize_ref(root.name), *root.submodels}
    diagnostics: list[Diagnostic] = []
    for section_model in (root, *root.submodels.values()):
        for obj in section_model.objects:
            number = section_model.source_line_for(obj)
            if number is None:
                continue
            diagnostics.extend(
                iter_object_issues(
                    obj,
                    number=number,
                    parts=parts,
                    submodels=submodels,
                    path=path,
                    section=section_model.name or None,
                ),
            )
    diagnostics.extend(_model_structure_diagnostics(root, path=path))
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
    if not tolerant:
        try:
            model = parse_model(text, name=name, source=source)
        except (PartError, ValueError) as error:
            diagnostic = _parse_error_diagnostic(
                error,
                number=getattr(error, "line_number", None) or 0,
                line="",
                source=source,
                section=None,
            )
            return ModelLoadResult(None, (diagnostic,), complete=False)
        diagnostics = _validation_diagnostics(
            model,
            parts=parts,
            path=_source_path(source),
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

    if not unique_sections:
        parsed = _parse_objects_report(
            preamble,
            source=source,
            section=name or None,
        )
        objects, source_lines, object_lines, parse_diagnostics, parsed_all = parsed
        model = Model(
            name=name,
            objects=objects,
            _source_lines=source_lines,
            _object_source_lines=object_lines,
        )
        diagnostics.extend(parse_diagnostics)
        complete = complete and parsed_all
    else:
        first, *rest = unique_sections
        root_lines = [*preamble, *first.lines]
        parsed = _parse_objects_report(
            root_lines,
            source=source,
            section=first.name,
        )
        objects, source_lines, object_lines, parse_diagnostics, parsed_all = parsed
        model = Model(
            name=first.name,
            objects=objects,
            _source_lines=source_lines,
            _object_source_lines=object_lines,
        )
        diagnostics.extend(parse_diagnostics)
        complete = complete and parsed_all
        for section in rest:
            parsed = _parse_objects_report(
                section.lines,
                source=source,
                section=section.name,
            )
            objects, source_lines, object_lines, section_diagnostics, parsed_all = (
                parsed
            )
            model.submodels[normalize_ref(section.name)] = Model(
                name=section.name,
                objects=objects,
                _source_lines=source_lines,
                _object_source_lines=object_lines,
            )
            diagnostics.extend(section_diagnostics)
            complete = complete and parsed_all

    diagnostics.extend(
        _validation_diagnostics(
            model,
            parts=parts,
            path=_source_path(source),
        ),
    )
    return ModelLoadResult(
        model=model,
        diagnostics=tuple(diagnostics),
        complete=complete,
    )


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
    return parse_model_result(
        text,
        name=file_path.name,
        source=file_path,
        parts=parts,
        tolerant=tolerant,
    )
