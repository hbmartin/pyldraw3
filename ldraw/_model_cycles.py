"""Invocation-local cycle tolerance for authoritative occurrence providers."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from ldraw.model import Model, ModelOccurrence
    from ldraw.pieces import Piece


@dataclass(frozen=True, slots=True)
class _CyclePolicy:
    model: Model
    callback: Callable[[Model, Piece, Model], None]


_CYCLE_POLICY: ContextVar[_CyclePolicy | None] = ContextVar(
    "ldraw_cycle_policy", default=None
)


def _cycle_callback(model: Model) -> Callable[[Model, Piece, Model], None] | None:
    policy = _CYCLE_POLICY.get()
    return policy.callback if policy is not None and policy.model is model else None


def _iter_cycle_tolerant_occurrences(
    *,
    model: Model,
    expand_submodels: bool,
    include_steps: bool,
    on_cycle: Callable[[Model, Piece, Model], None],
) -> Iterator[ModelOccurrence]:
    """Set tolerance while producing each event, never while yielding it."""
    policy = _CyclePolicy(model=model, callback=on_cycle)
    token = _CYCLE_POLICY.set(policy)
    try:
        occurrences = model.iter_occurrences(
            expand_submodels=expand_submodels, include_steps=include_steps
        )
    finally:
        _CYCLE_POLICY.reset(token)
    while True:
        token = _CYCLE_POLICY.set(policy)
        try:
            occurrence = next(occurrences)
        except StopIteration:
            return
        finally:
            _CYCLE_POLICY.reset(token)
        yield occurrence
