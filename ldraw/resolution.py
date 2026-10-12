"""Shared physical boundaries, alias expansion, and authored geometry traversal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.errors import PartError
from ldraw.geometry import Identity, Vector
from ldraw.lines import Line, OptionalLine, Quadrilateral, Triangle
from ldraw.model import (
    Model,
    ModelOccurrence,
    OccurrencePathItem,
    _effective_colour,
    _iter_piece_steps,
)
from ldraw.part_metadata import (
    PartFileKind,
    PartMetadata,
    PartStatus,
    parse_metadata_lines,
)
from ldraw.pieces import Piece
from ldraw.utils import normalize_ref, split_reference

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ldraw.colour import Colour
    from ldraw.geometry import Matrix
    from ldraw.parts import Parts


@dataclass(frozen=True, slots=True)
class RawGeometry:
    """Drawable points and source attribution, independent of physical parts."""

    points: tuple[Vector, ...]
    section: str
    source_line: int | None
    path: tuple[OccurrencePathItem, ...]
    colour: Colour | None = None


class DocumentResolver:
    """Definition-aware traversal shared by counting and spatial analysis."""

    def __init__(self, model: Model, parts: Parts | None = None) -> None:
        self.model = model
        self.parts = parts.with_embedded(model) if parts is not None else None
        self.diagnostics: list[Diagnostic] = (
            list(self.parts.diagnostics) if self.parts else []
        )
        self.provisional: set[str] = set()
        self.unresolved: list[str] = []
        self._external: dict[str, Model | None] = {}
        self._reported: set[tuple[str, str]] = set()
        self._classifications: dict[str, tuple[PartFileKind, bool]] = {}

    def _note(
        self,
        code: str,
        reference: str,
        message: str,
        *,
        occurrence: ModelOccurrence | None = None,
    ) -> None:
        if (code, reference) not in self._reported:
            self._reported.add((code, reference))
            self.diagnostics.append(
                Diagnostic(
                    code=code,
                    severity=(
                        Severity.ERROR
                        if code == DiagnosticCode.MPD_CYCLE
                        else Severity.WARNING
                    ),
                    line_number=occurrence.source_line if occurrence else None,
                    section=occurrence.source_model.name if occurrence else None,
                    offending_value=reference,
                    message=message,
                )
            )

    def _definition(self, reference: str) -> Model | None:
        if normalize_ref(reference) == normalize_ref(self.model.name):
            return self.model
        if (section := self.model.submodels.get(normalize_ref(reference))) is not None:
            return section
        key = normalize_ref(reference)
        if key not in self._external:
            part = (
                self.parts.find_part(
                    code=(
                        split_reference(reference)[0]
                        if key.endswith(".dat")
                        else reference
                    )
                )
                if self.parts
                else None
            )
            try:
                self._external[key] = (
                    Model(name=reference, objects=list(part.objects)) if part else None
                )
            except (OSError, PartError, UnicodeError):
                self._external[key] = None
        return self._external[key]

    def events(self) -> Iterator[ModelOccurrence | RawGeometry]:
        """Yield physical leaves and direct drawable records with world transforms."""
        yield from self._walk(
            self.model,
            position=Vector(0, 0, 0),
            matrix=Identity(),
            inherited=None,
            path=(),
            visiting=frozenset(),
            step=None,
        )

    def _walk(  # noqa: PLR0913 - traversal context is explicit
        self,
        section: Model,
        *,
        position: Vector,
        matrix: Matrix,
        inherited: Colour | None,
        path: tuple[OccurrencePathItem, ...],
        visiting: frozenset[str],
        step: int | None,
    ) -> Iterator[ModelOccurrence | RawGeometry]:
        visiting = visiting | {normalize_ref(section.name)}
        for obj in section.objects:
            if isinstance(obj, Line | Triangle | Quadrilateral | OptionalLine):
                points = obj.points[:2] if isinstance(obj, OptionalLine) else obj.points
                yield RawGeometry(
                    points=tuple(position + matrix * point for point in points),
                    section=section.name,
                    source_line=section.source_line_for(obj),
                    path=path,
                    colour=_effective_colour(obj.colour, inherited),
                )
        for index, (piece, local_step) in enumerate(
            _iter_piece_steps(section, include_steps=True)
        ):
            local_position, local_matrix = piece._transformed()  # noqa: SLF001
            colour = _effective_colour(piece.colour, inherited)
            effective_step = step if step is not None else local_step
            placement = OccurrencePathItem(
                model=section,
                piece=piece,
                source_line=section.source_line_for(piece),
                local_step=local_step,
                effective_step=effective_step,
                piece_index=index,
            )
            occurrence = ModelOccurrence(
                piece=piece,
                part_code=piece.part,
                reference=piece.reference,
                colour=colour,
                position=position + matrix * local_position,
                matrix=matrix * local_matrix,
                source_model=section,
                source_line=section.source_line_for(piece),
                step=effective_step,
                source_step=local_step,
                path=(*path, placement),
            )
            yield from self._reference_events(occurrence, visiting=visiting)

    def _reference_events(
        self, occurrence: ModelOccurrence, *, visiting: frozenset[str]
    ) -> Iterator[ModelOccurrence | RawGeometry]:
        definition = self._definition(occurrence.reference)
        kind, alias = self._classification(occurrence.reference, definition)
        assembly = (
            kind == PartFileKind.SHORTCUT
            or alias
            or (
                not occurrence.reference.casefold().endswith(".dat")
                and kind == PartFileKind.UNKNOWN
            )
        )
        if definition is not None and assembly:
            if alias and not definition.pieces:
                definition = self._alias_definition(definition, occurrence=occurrence)
            if normalize_ref(definition.name) in visiting:
                self.unresolved.append(occurrence.reference)
                self._note(
                    DiagnosticCode.MPD_CYCLE,
                    occurrence.reference,
                    f"Submodel reference cycle detected at {occurrence.reference!r}",
                    occurrence=occurrence,
                )
            else:
                yield from self._walk(
                    definition,
                    position=occurrence.position,
                    matrix=occurrence.matrix,
                    inherited=occurrence.colour,
                    path=occurrence.path,
                    visiting=visiting,
                    step=occurrence.step,
                )
        elif kind in {
            PartFileKind.PRIMITIVE,
            PartFileKind.PRIMITIVE_8,
            PartFileKind.PRIMITIVE_48,
            PartFileKind.SUBPART,
        }:
            self._note(
                "document.nonphysical_reference",
                occurrence.reference,
                f"{occurrence.reference!r} is a primitive or subpart; "
                "excluded from physical inventory",
            )
            if self.parts is not None:
                local = self.parts.geometry(occurrence.part_code)
                yield RawGeometry(
                    points=tuple(
                        occurrence.position + occurrence.matrix * point
                        for point in local.points
                    ),
                    section=occurrence.source_model.name,
                    source_line=occurrence.source_line,
                    path=occurrence.path,
                    colour=occurrence.colour,
                )
                self.diagnostics.extend(local.diagnostics)
        else:
            yield occurrence

    def _alias_definition(
        self, definition: Model, *, occurrence: ModelOccurrence
    ) -> Model:
        """Resolve a declared moved target even when no placement record is present."""
        metadata = parse_metadata_lines([obj.to_ldraw() for obj in definition.objects])
        if metadata.replacement:
            return Model(
                name=definition.name,
                objects=[Piece.place(metadata.replacement, colour=16)],
            )
        self.unresolved.append(occurrence.reference)
        self._note(
            "document.unresolved_alias",
            occurrence.reference,
            f"Alias {occurrence.reference!r} declares no resolvable target",
            occurrence=occurrence,
        )
        return definition

    def _uncached_classification(
        self, reference: str, definition: Model | None
    ) -> tuple[PartFileKind, bool]:
        if definition is None:
            self.provisional.add(reference)
            self.unresolved.append(reference)
            self._note(
                "document.unresolved_contents",
                reference,
                f"No definition for {reference!r}; physical count is provisional",
            )
            return PartFileKind.UNKNOWN, False
        metadata = (
            parse_metadata_lines([obj.to_ldraw() for obj in definition.objects])
            if definition.objects
            else PartMetadata(description=definition.name)
        )
        if metadata.file_kind == PartFileKind.UNKNOWN and reference.casefold().endswith(
            ".dat"
        ):
            self.provisional.add(reference)
            self._note(
                "document.provisional_part",
                reference,
                f"Unclassified .dat {reference!r} is a provisional physical boundary",
            )
        return metadata.file_kind, metadata.status in {
            PartStatus.ALIAS,
            PartStatus.MOVED,
        }

    def _classification(
        self, reference: str, definition: Model | None
    ) -> tuple[PartFileKind, bool]:
        key = normalize_ref(reference)
        if key not in self._classifications:
            self._classifications[key] = self._uncached_classification(
                reference, definition
            )
        return self._classifications[key]
