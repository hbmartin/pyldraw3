"""Invocation-local cycle tolerance for authoritative occurrence providers."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from inspect import Parameter, signature
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

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


def _custom_occurrences(
    *, model: Model, expand_submodels: bool, include_steps: bool
) -> Iterable[ModelOccurrence]:
    """Adapt legacy narrower overrides without retrying failures in their bodies."""
    provider = model.iter_occurrences
    try:
        parameters = signature(provider).parameters
    except (TypeError, ValueError):
        # An opaque callable retains the public method's keyword contract.
        return provider(expand_submodels=expand_submodels, include_steps=include_steps)
    variadic = any(
        parameter.kind is Parameter.VAR_KEYWORD for parameter in parameters.values()
    )
    if "expand_submodels" not in parameters and not variadic and not expand_submodels:
        message = "custom iter_occurrences does not support expand_submodels=False"
        raise TypeError(message)
    values = {"expand_submodels": expand_submodels, "include_steps": include_steps}
    positional = [
        parameter
        for parameter in parameters.values()
        if parameter.kind is Parameter.POSITIONAL_ONLY
    ]
    last = max(
        (
            index
            for index, parameter in enumerate(positional)
            if parameter.name in values
        ),
        default=-1,
    )
    arguments: list[object] = []
    for parameter in positional[: last + 1]:
        if parameter.name in values:
            arguments.append(values[parameter.name])
        elif parameter.default is not Parameter.empty:
            arguments.append(parameter.default)
        else:
            message = f"custom iter_occurrences requires argument {parameter.name!r}"
            raise TypeError(message)
    keywords = {
        name: value
        for name, value in values.items()
        if ((parameter := parameters.get(name)) is None and variadic)
        or (
            parameter is not None
            and parameter.kind
            in {Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY}
        )
    }
    return provider(*arguments, **keywords)


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
        occurrences = iter(
            _custom_occurrences(
                model=model,
                expand_submodels=expand_submodels,
                include_steps=include_steps,
            )
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
