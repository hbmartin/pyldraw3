"""Live section adapters with root-owned reference resolution."""

from __future__ import annotations

from functools import cache
from types import FunctionType, MethodType
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from ldraw.model import Model


class _ModelViewMixin:
    __slots__ = ()

    def __getattribute__(self, name: str) -> Any:  # noqa: ANN401 - proxy attributes
        if name in {
            "_view_selected",
            "_view_root",
            "_view_bound_names",
            "_view_classmethods",
        }:
            return object.__getattribute__(self, name)
        selected = object.__getattribute__(self, "_view_selected")
        match name:
            case "submodels" | "submodel_for":
                return getattr(object.__getattribute__(self, "_view_root"), name)
            case "_is_submodel_view":
                return True
            case _:
                pass
        if name in object.__getattribute__(self, "_view_bound_names"):
            state = getattr(selected, "__dict__", {})
            if name in state:
                value = state[name]
                return (
                    MethodType(value.__func__, self)
                    if isinstance(value, MethodType) and value.__self__ is selected
                    else value
                )
            return (
                getattr(selected, name)
                if name in object.__getattribute__(self, "_view_classmethods")
                else object.__getattribute__(self, name)
            )
        return getattr(selected, name)

    def __setattr__(self, name: str, value: object) -> None:
        match name:
            case "_view_selected" | "_view_root":
                message = "cannot change a live model view binding"
                raise AttributeError(message)
            case "submodels":
                setattr(object.__getattribute__(self, "_view_root"), name, value)
            case "_is_submodel_view":
                message = "a live model view always has selected-section scope"
                raise AttributeError(message)
            case _:
                setattr(object.__getattribute__(self, "_view_selected"), name, value)

    def __delattr__(self, name: str) -> None:
        if name in {"_view_selected", "_view_root", "_is_submodel_view"}:
            message = "cannot delete a live model view binding"
            raise AttributeError(message)
        target = object.__getattribute__(
            self, "_view_root" if name == "submodels" else "_view_selected"
        )
        delattr(target, name)


@cache
def _view_class(selected_class: type[Model]) -> type[Model]:
    """Bind inherited descriptors to a view without copying instance state."""
    descriptors = {
        name: value
        for base in reversed(selected_class.__mro__)
        for name, value in vars(base).items()
    }
    bound_names = frozenset(
        name
        for name, descriptor in descriptors.items()
        if isinstance(descriptor, FunctionType | property | staticmethod | classmethod)
    )
    return cast(
        "type[Model]",
        type(
            f"_Live{selected_class.__name__}View",
            (_ModelViewMixin, selected_class),
            {
                "__slots__": ("_view_selected", "_view_root"),
                "_view_bound_names": bound_names,
                "_view_classmethods": frozenset(
                    name
                    for name, descriptor in descriptors.items()
                    if isinstance(descriptor, classmethod)
                ),
            },
        ),
    )


def _selected_model(model: Model) -> Model:
    return (
        object.__getattribute__(model, "_view_selected")
        if isinstance(model, _ModelViewMixin)
        else model
    )


def _resolution_root(model: Model) -> Model:
    return (
        object.__getattribute__(model, "_view_root")
        if isinstance(model, _ModelViewMixin)
        else model
    )


def _model_view(*, selected: Model, root: Model) -> Model:
    selected = _selected_model(selected)
    view = object.__new__(_view_class(type(selected)))
    object.__setattr__(view, "_view_selected", selected)
    object.__setattr__(view, "_view_root", _resolution_root(root))
    return view
