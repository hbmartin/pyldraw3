"""Invocation-local source placements and reference resolution for comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ldraw._model_views import _resolution_root, _selected_model
from ldraw.utils import normalize_ref, split_ldraw_reference

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from ldraw.geometry import Matrix, Vector
    from ldraw.model import Model
    from ldraw.pieces import Piece
    from ldraw.validation import _NumericAnalysis


@dataclass(slots=True)
class ModelValidationContext:
    """Share analysis within one load/compare operation, never across mutations."""

    placements: dict[Piece, tuple[Vector, Matrix]] = field(default_factory=dict)
    targets: dict[Piece, Model | None] = field(default_factory=dict)
    _root: Model | None = field(default=None, init=False, repr=False)
    validated_sections: set[int] = field(default_factory=set, repr=False)
    _edges: dict[int, tuple[tuple[Piece, Model], ...]] = field(
        default_factory=dict, init=False, repr=False
    )
    _builtin_resolver: bool = field(default=False, init=False, repr=False)
    _completed_sections: dict[tuple[int, bool], frozenset[int]] = field(
        default_factory=dict, init=False, repr=False
    )

    def bind(self, root: Model) -> None:
        """Keep cached references scoped to one resolution root."""
        root = _resolution_root(root)
        if self._root is None:
            self._root = root
            from ldraw.model import Model  # noqa: PLC0415 - runtime cycle

            self._builtin_resolver = (
                getattr(root.submodel_for, "__func__", None) is Model.submodel_for
            )
        elif self._root is not root:
            message = "model validation context belongs to a different resolution root"
            raise ValueError(message)

    def mark_validated(self, *, root: Model, reachable_only: bool) -> None:
        """Record successful source validation for this invocation's scope."""
        for section in self.sections(root=root, reachable_only=reachable_only):
            self.validated_sections.add(id(section))

    def sections(self, *, root: Model, reachable_only: bool) -> Iterator[Model]:
        """Discover a scope once, validating cycle-closing targets before stopping."""
        self.bind(root)
        selected = _selected_model(root)
        scope = id(selected), reachable_only
        completed = self._completed_sections.get(scope)
        if completed is not None and completed <= self.validated_sections:
            return
        visited: set[int] = set()
        sources = (
            _reachable_sections(root=root, context=self)
            if reachable_only
            else _declared_sections(model=selected)
        )
        for section in sources:
            if (key := id(section)) not in visited:
                visited.add(key)
                yield section
        self._completed_sections[scope] = frozenset(visited)

    def ensure_validated(self, *, root: Model, reachable_only: bool) -> None:
        """Complete partial source analysis before using cached placements."""
        self.bind(root)
        from ldraw.validation import (  # noqa: PLC0415 - model/validation cycle
            _iter_model_numeric_issues,
            _reject_numeric_issue,
        )

        scopes = (True,) if reachable_only else (False, True)
        for scope in scopes:
            # Declared sections cover all targets of the built-in root resolver.
            if scope and not reachable_only and self._builtin_resolver:
                continue
            for issue in _iter_model_numeric_issues(
                root, reachable_only=scope, context=self
            ):
                _reject_numeric_issue(issue)

    def edges(self, *, root: Model, section: Model) -> tuple[tuple[Piece, Model], ...]:
        """Discover each section's resolved submodel references once."""
        self.bind(root)
        section = _selected_model(section)
        if (key := id(section)) not in self._edges:
            self._edges[key] = tuple(
                (piece, target)
                for piece in section.pieces
                if (target := self.resolve(root=root, piece=piece)) is not None
            )
        return self._edges[key]

    def has_external_resolution(self) -> bool:
        """Whether targets can extend beyond the root's declared table."""
        return not self._builtin_resolver

    def unique_names(self, *, root: Model) -> bool:
        """Inspect cached edges without assuming uniqueness from resolver type."""
        discovery = _unique_sections(root=root, context=self)
        while True:
            try:
                next(discovery)
            except StopIteration as completed:
                return bool(completed.value)

    def record(self, *, piece: Piece, analysis: _NumericAnalysis) -> None:
        """Retain finite effective placements with the required type narrowing."""
        if (
            not analysis.invalid
            and analysis.position is not None
            and analysis.matrix is not None
        ):
            self.placements[piece] = analysis.position, analysis.matrix

    def placement(self, *, model: Model, piece: Piece) -> tuple[Vector, Matrix]:
        """Validate a missing cache entry instead of exposing a dictionary error."""
        if (placement := self.placements.get(piece)) is not None:
            return placement
        from ldraw.validation import (  # noqa: PLC0415 - exceptional partial cache
            _numeric_issue,
            _piece_analysis,
            _reject_numeric_issue,
        )

        (position, matrix), analysis = _piece_analysis(piece)
        if issue := _numeric_issue(
            analysis,
            number=model.source_line_for(piece),
            path=None,
            section=model.name or None,
        ):
            _reject_numeric_issue(issue)
        self.placements[piece] = position, matrix
        return position, matrix

    def resolve(self, *, root: Model, piece: Piece) -> Model | None:
        """Resolve a source reference once against this operation's root table."""
        if _resolution_root(root) is not self._root:
            self.bind(root)
        if piece not in self.targets:
            self.targets[piece] = _optional_reference(root=root, piece=piece)
        return self.targets[piece]


@dataclass(slots=True)
class _DiscoveryFrame:
    state: tuple[int, frozenset[str]]
    visiting: frozenset[str]
    children: Iterator[tuple[Piece, Model]]
    blocked: bool = False


def _discovery_frame(
    *,
    root: Model,
    section: Model,
    ancestry: frozenset[str],
    context: ModelValidationContext,
) -> _DiscoveryFrame:
    return _DiscoveryFrame(
        state=(id(section), ancestry),
        visiting=ancestry | {normalize_ref(section.name)},
        children=iter(context.edges(root=root, section=section)),
    )


def _unique_sections(
    *, root: Model, context: ModelValidationContext
) -> Generator[Model, None, bool]:
    """Explore by identity until normalized names cease to identify one source."""
    pending = [_selected_model(root)]
    names: dict[str, Model] = {}
    expanded: set[int] = set()
    while pending:
        section = _selected_model(pending.pop())
        yield section
        key = normalize_ref(section.name)
        if (previous := names.get(key)) is not None and previous is not section:
            return False
        names[key] = section
        if (identity := id(section)) in expanded:
            continue
        expanded.add(identity)
        pending.extend(
            target for _, target in reversed(context.edges(root=root, section=section))
        )
    return True


def _reachable_sections(
    *, root: Model, context: ModelValidationContext
) -> Iterator[Model]:
    """Keep unique-name cycles linear and ambiguous names ancestry-sensitive."""
    if not (yield from _unique_sections(root=root, context=context)):
        yield from _ancestry_sections(root=root, context=context)


def _ancestry_sections(
    *, root: Model, context: ModelValidationContext
) -> Iterator[Model]:
    """Reuse complete acyclic closures and exact states of blocked paths."""
    selected = _selected_model(root)
    yield selected
    frames = [
        _discovery_frame(
            root=root, section=selected, ancestry=frozenset(), context=context
        )
    ]
    complete: set[int] = set()
    sensitive: set[tuple[int, frozenset[str]]] = set()
    while frames:
        frame = frames[-1]
        if (edge := next(frame.children, None)) is None:
            frames.pop()
            if frame.blocked:
                sensitive.add(frame.state)
            else:
                complete.add(frame.state[0])
            if frames:
                frames[-1].blocked |= frame.blocked
            continue
        target = _selected_model(edge[1])
        # The consumer checks a newly seen closing section before we stop here.
        yield target
        if normalize_ref(target.name) in frame.visiting:
            frame.blocked = True
        elif id(target) in complete:
            continue
        elif (id(target), frame.visiting) in sensitive:
            frame.blocked = True
        else:
            frames.append(
                _discovery_frame(
                    root=root,
                    section=target,
                    ancestry=frame.visiting,
                    context=context,
                )
            )


def _declared_sections(*, model: Model) -> Iterator[Model]:
    """Walk declared tables without resolving references or following name cycles."""
    pending = [model]
    visited: set[int] = set()
    while pending:
        section = _selected_model(pending.pop())
        if (key := id(section)) in visited:
            continue
        visited.add(key)
        yield section
        pending.extend(reversed(tuple(section.submodels.values())))


def _optional_reference(*, root: Model, piece: Piece) -> Model | None:
    """Accept mapping-style misses without hiding unrelated resolver failures."""
    try:
        return _resolution_root(root).submodel_for(piece)
    except KeyError as error:
        if (
            len(error.args) == 1
            and isinstance(key := error.args[0], str)
            and normalize_ref(key)
            in {
                normalize_ref(piece.reference),
                normalize_ref(piece.part),
                normalize_ref(split_ldraw_reference(piece.reference)[0]),
            }
        ):
            return None
        raise


def _resolve_reference(
    *, root: Model, piece: Piece, context: ModelValidationContext | None
) -> Model | None:
    """Resolve references through the invocation cache when one is available."""
    return (
        context.resolve(root=root, piece=piece)
        if context is not None
        else _optional_reference(root=root, piece=piece)
    )
