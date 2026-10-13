"""Live section adapters with root-owned resolution and descriptor caches."""

from __future__ import annotations

from copy import deepcopy
from functools import cached_property
from types import GetSetDescriptorType, MemberDescriptorType, MethodType
from typing import TYPE_CHECKING, Any, SupportsIndex, cast
from weakref import ReferenceType, WeakKeyDictionary, ref

if TYPE_CHECKING:
    from ldraw.model import Model

_MISSING = object()
_VIEW_BINDINGS = frozenset({"_view_selected", "_view_root", "_view_cache"})
_VIEW_PROTOCOLS = frozenset(
    {
        "__class__",
        "__copy__",
        "__deepcopy__",
        "__reduce__",
        "__reduce_ex__",
        "__getstate__",
        "__setstate__",
    }
)
_VIEW_CLASSES: WeakKeyDictionary[type[Model], ReferenceType[type[Model]]] = (
    WeakKeyDictionary()
)


def _class_descriptor(model: Model, name: str) -> Any:  # noqa: ANN401 - descriptors
    for base in type(model).__mro__:
        if name in (namespace := vars(base)):
            return namespace[name]
    return _MISSING


def _storage_descriptor(descriptor: object) -> bool:
    return isinstance(descriptor, MemberDescriptorType | GetSetDescriptorType)


def _view_attribute(*, view: _ModelViewMixin, selected: Model, name: str) -> Any:  # noqa: ANN401 - descriptor values
    descriptor = _class_descriptor(selected, name)
    if isinstance(descriptor, cached_property):
        return object.__getattribute__(view, name)
    if _storage_descriptor(descriptor) or not hasattr(type(descriptor), "__get__"):
        return getattr(selected, name)
    if not (
        hasattr(type(descriptor), "__set__") or hasattr(type(descriptor), "__delete__")
    ) and name in (state := getattr(selected, "__dict__", {})):
        value = state[name]
        return (
            MethodType(value.__func__, view)
            if isinstance(value, MethodType) and value.__self__ is selected
            else value
        )
    return (
        getattr(selected, name)
        if isinstance(descriptor, classmethod)
        else object.__getattribute__(view, name)
    )


class _ModelViewMixin:
    __slots__ = ()

    if TYPE_CHECKING:
        _view_selected: Model
        _view_root: Model
        _view_cache: dict[str, object]

    def __init_subclass__(cls, **_kwargs: object) -> None:
        """Do not register the internal adapter through user subclass hooks."""

    def __getattribute__(self, name: str) -> Any:  # noqa: ANN401 - proxy attributes
        if name in _VIEW_BINDINGS or name in _VIEW_PROTOCOLS:
            return object.__getattribute__(self, name)
        if name == "__dict__":
            return object.__getattribute__(self, "_view_cache")
        selected = object.__getattribute__(self, "_view_selected")
        match name:
            case "submodels" | "submodel_for":
                return getattr(object.__getattribute__(self, "_view_root"), name)
            case "_is_submodel_view":
                return True
            case _:
                pass
        return _view_attribute(view=self, selected=selected, name=name)

    def __setattr__(self, name: str, value: object) -> None:
        if name in _VIEW_BINDINGS or name == "_is_submodel_view":
            message = (
                "a live model view always has selected-section scope"
                if name == "_is_submodel_view"
                else "cannot change a live model view binding"
            )
            raise AttributeError(message)
        if name == "submodels":
            setattr(self._view_root, name, value)
            return
        descriptor = _class_descriptor(self._view_selected, name)
        if isinstance(descriptor, cached_property):
            self._view_cache[name] = value
        elif not _storage_descriptor(descriptor) and hasattr(
            type(descriptor), "__set__"
        ):
            descriptor.__set__(self, value)
        else:
            setattr(self._view_selected, name, value)

    def __delattr__(self, name: str) -> None:
        if name in _VIEW_BINDINGS or name == "_is_submodel_view":
            message = "cannot delete a live model view binding"
            raise AttributeError(message)
        descriptor = _class_descriptor(self._view_selected, name)
        if isinstance(descriptor, cached_property):
            if name not in self._view_cache:
                raise AttributeError(name)
            del self._view_cache[name]
        elif not _storage_descriptor(descriptor) and hasattr(
            type(descriptor), "__delete__"
        ):
            descriptor.__delete__(self)
        else:
            delattr(
                self._view_root if name == "submodels" else self._view_selected, name
            )

    def __copy__(self) -> Model:
        return _model_view(selected=self._view_selected, root=self._view_root)

    def __deepcopy__(self, memo: dict[int, Any]) -> Model:
        view = _allocate_view(type(self._view_selected))
        memo[id(self)] = view
        _initialize_view(
            view=view,
            selected=deepcopy(x=self._view_selected, memo=memo),
            root=deepcopy(x=self._view_root, memo=memo),
        )
        return view

    def __getstate__(self) -> tuple[Model, Model]:
        return self._view_selected, self._view_root

    def __setstate__(self, state: tuple[Model, Model]) -> None:
        _initialize_view(view=cast("Model", self), selected=state[0], root=state[1])

    def __reduce_ex__(self, _protocol: SupportsIndex) -> tuple[object, ...]:
        return _allocate_view, (type(self._view_selected),), self.__getstate__()

    def __reduce__(self) -> tuple[object, ...]:
        return self.__reduce_ex__(4)


def _view_class(selected_class: type[Model]) -> type[Model]:
    """Keep generated types alive only while their users keep them alive."""
    if (cached := _VIEW_CLASSES.get(selected_class)) is not None and (
        view_class := cached()
    ) is not None:
        return view_class
    view_class = cast(
        "type[Model]",
        type(
            f"_Live{selected_class.__name__}View",
            (_ModelViewMixin, selected_class),
            {
                "__module__": __name__,
                "__slots__": ("_view_selected", "_view_root", "_view_cache"),
            },
        ),
    )
    _VIEW_CLASSES[selected_class] = ref(view_class)
    return view_class


def _allocate_view(selected_class: type[Model]) -> Model:
    """Allocate before restoring state so pickle and deepcopy handle cycles."""
    return object.__new__(_view_class(selected_class))


def _initialize_view(*, view: Model, selected: Model, root: Model) -> None:
    object.__setattr__(view, "_view_selected", _selected_model(selected))
    object.__setattr__(view, "_view_root", _resolution_root(root))
    object.__setattr__(view, "_view_cache", {})


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
    view = _allocate_view(type(_selected_model(selected)))
    _initialize_view(view=view, selected=selected, root=root)
    return view
