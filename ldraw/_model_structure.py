"""Cached source discovery and complete placement-level cycle reporting."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ldraw._model_validation import ModelValidationContext, _reachable_sections
from ldraw._model_views import _resolution_root, _selected_model
from ldraw.utils import normalize_ref

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from ldraw.model import Model
    from ldraw.pieces import Piece

type _Marker = tuple[int, int]
type _Edge = tuple[Model, Piece, Model | None]


def _source_edges(
    *, root: Model, context: ModelValidationContext
) -> tuple[dict[int, Model], list[_Edge]]:
    """Reuse acyclic closures even when unrelated sections have ambiguous names."""
    expanded: set[int] = set()
    discovered = {
        id(_selected_model(section)): _selected_model(section)
        for section in _reachable_sections(
            root=root, context=context, expanded=expanded
        )
    }
    order = dict.fromkeys(
        (
            id(_selected_model(root)),
            *(
                id(_selected_model(m))
                for m in _resolution_root(root).submodels.values()
            ),
            *discovered,
        )
    )
    sources = {key: discovered[key] for key in order if key in discovered}
    edges = [
        (source, piece, context.resolve(root=root, piece=piece))
        for identity, source in sources.items()
        if identity in expanded
        for piece in source.pieces
    ]
    return sources, edges


def _postorder(adjacency: dict[int, list[int]]) -> list[int]:
    """Finish each identity vertex once without recursive DFS."""
    seen: set[int] = set()
    ordered: list[int] = []
    for identity, outgoing in adjacency.items():
        if identity in seen:
            continue
        seen.add(identity)
        frames = [(identity, iter(outgoing))]
        while frames:
            node, children = frames[-1]
            if (child := next(children, None)) is None:
                ordered.append(node)
                frames.pop()
            elif child not in seen:
                seen.add(child)
                frames.append((child, iter(adjacency[child])))
    return ordered


def _identity_cycles(*, sources: dict[int, Model], edges: list[_Edge]) -> set[_Marker]:
    """Find all edges inside cyclic strongly connected identity components."""
    outgoing: dict[int, list[int]] = {key: [] for key in sources}
    incoming: dict[int, list[int]] = {key: [] for key in sources}
    for source, _, target in edges:
        if target is not None:
            child = id(_selected_model(target))
            outgoing[id(source)].append(child)
            incoming[child].append(id(source))
    components: dict[int, int] = {}
    for node in reversed(_postorder(outgoing)):
        if node in components:
            continue
        components[node] = node
        pending = [node]
        while pending:
            for parent in incoming[pending.pop()]:
                if parent not in components:
                    components[parent] = node
                    pending.append(parent)
    return {
        (id(source), id(piece))
        for source, piece, target in edges
        if target is not None
        and components[id(source)] == components[id(_selected_model(target))]
    }


@dataclass(slots=True)
class _CycleFrame:
    identity: int
    name: str
    ancestry: frozenset[str]
    children: Iterator[_Edge]
    parent_edge: _Marker | None = None
    results: dict[str, set[_Marker]] = field(default_factory=dict)


def _merge_cycles(
    *, frame: _CycleFrame, results: dict[str, set[_Marker]], edge: _Marker
) -> None:
    for name, markers in results.items():
        frame.results.setdefault(name, set()).update((*markers, edge))


@dataclass(slots=True)
class _AmbiguousGraph:
    duplicates: set[str]
    outgoing: dict[int, list[_Edge]]
    sensitive: set[int]


def _ambiguous_graph(
    *, sources: dict[int, Model], edges: list[_Edge], duplicates: set[str]
) -> _AmbiguousGraph:
    outgoing: dict[int, list[_Edge]] = {key: [] for key in sources}
    incoming: dict[int, list[int]] = {key: [] for key in sources}
    sensitive: set[int] = set()
    for edge in edges:
        source, _, target = edge
        outgoing[id(source)].append(edge)
        if target is not None:
            incoming[id(_selected_model(target))].append(id(source))
            if normalize_ref(target.name) in duplicates:
                sensitive.add(id(source))
    pending = deque(sensitive)
    while pending:
        for parent in incoming[pending.popleft()]:
            if parent not in sensitive:
                sensitive.add(parent)
                pending.append(parent)
    return _AmbiguousGraph(
        duplicates=duplicates, outgoing=outgoing, sensitive=sensitive
    )


def _cycle_child(
    *,
    graph: _AmbiguousGraph,
    frame: _CycleFrame,
    edge: _Edge,
    memo: dict[tuple[int, frozenset[str]], dict[str, set[_Marker]]],
) -> _CycleFrame | None:
    source, piece, target = edge
    if target is None:
        return None
    marker = id(source), id(piece)
    name = normalize_ref(target.name)
    visiting = frame.ancestry | {frame.name}
    if name in visiting:
        if name in graph.duplicates:
            frame.results.setdefault(name, set()).add(marker)
    elif (identity := id(_selected_model(target))) in graph.sensitive:
        if (state := (identity, visiting)) in memo:
            _merge_cycles(frame=frame, results=memo[state], edge=marker)
        else:
            return _CycleFrame(
                identity=identity,
                name=name,
                ancestry=visiting,
                children=iter(graph.outgoing[identity]),
                parent_edge=marker,
            )
    return None


def _ambiguous_cycles(
    *, root: Model, sources: dict[int, Model], edges: list[_Edge]
) -> set[_Marker]:
    """Memoize name-closing path summaries, preserving every participating edge."""
    duplicates = {
        name
        for name, count in Counter(
            normalize_ref(s.name) for s in sources.values()
        ).items()
        if count > 1
    }
    if not duplicates:
        return set()
    graph = _ambiguous_graph(sources=sources, edges=edges, duplicates=duplicates)
    selected = _selected_model(root)
    frames = [
        _CycleFrame(
            identity=id(selected),
            name=normalize_ref(selected.name),
            ancestry=frozenset(),
            children=iter(graph.outgoing[id(selected)]),
        )
    ]
    memo: dict[tuple[int, frozenset[str]], dict[str, set[_Marker]]] = {}
    cyclic: set[_Marker] = set()
    while frames:
        frame = frames[-1]
        if (edge := next(frame.children, None)) is None:
            if closed := frame.results.pop(frame.name, None):
                cyclic.update(closed)
            memo[frame.identity, frame.ancestry] = frame.results
            frames.pop()
            if frames and frame.parent_edge is not None:
                _merge_cycles(
                    frame=frames[-1], results=frame.results, edge=frame.parent_edge
                )
            continue
        if child := _cycle_child(graph=graph, frame=frame, edge=edge, memo=memo):
            frames.append(child)
    return cyclic


def iter_structure_edges(
    *,
    root: Model,
    context: ModelValidationContext | None = None,
    descend: Callable[[Model], bool] | None = None,
) -> Iterator[tuple[Model, Piece, Model | None, bool]]:
    """Emit source edges once, independently of the route used to discover them."""
    cache = context if context is not None else ModelValidationContext()
    sources, edges = _source_edges(root=root, context=cache)
    if descend is not None:
        sources, edges = _filtered_sources(
            root=root, sources=sources, edges=edges, descend=descend
        )
    classified = [
        (
            source,
            piece,
            target if target is None or descend is None or descend(target) else None,
        )
        for source, piece, target in edges
    ]
    cyclic = _identity_cycles(sources=sources, edges=classified)
    cyclic.update(_ambiguous_cycles(root=root, sources=sources, edges=classified))
    for source, piece, target in edges:
        yield source, piece, target, (id(source), id(piece)) in cyclic


def _filtered_sources(
    *,
    root: Model,
    sources: dict[int, Model],
    edges: list[_Edge],
    descend: Callable[[Model], bool],
) -> tuple[dict[int, Model], list[_Edge]]:
    """Exclude descendants behind opaque references from instruction diagnostics."""
    outgoing: dict[int, list[int]] = {key: [] for key in sources}
    for source, _, target in edges:
        if target is not None and descend(target):
            outgoing[id(source)].append(id(_selected_model(target)))
    reachable = {id(_selected_model(root))}
    pending = list(reachable)
    while pending:
        for identity in outgoing[pending.pop()]:
            if identity not in reachable:
                reachable.add(identity)
                pending.append(identity)
    return (
        {key: source for key, source in sources.items() if key in reachable},
        [edge for edge in edges if id(edge[0]) in reachable],
    )
