"""Reading and writing whole LDraw model files (.ldr and .mpd)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Self

from ldraw.errors import (
    DuplicateSubmodelError,
    PartError,
    SubmodelCycleError,
    SubmodelNameRequiredError,
)
from ldraw.geometry import Identity, Vector
from ldraw.lines import Comment, MetaCommand
from ldraw.part import ParsedObject, parse_ldraw_line
from ldraw.pieces import MAIN_COLOUR_CODE, Piece
from ldraw.utils import ldraw_file_name, normalize_ref, split_reference

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from ldraw.colour import Colour
    from ldraw.geometry import Matrix
    from ldraw.pieces import Group

_NumberedLine = tuple[int, str]

_MANAGED_HEADER_PREFIXES = ("Name:", "Author:", "BFC")


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
    lines: list[_NumberedLine] = field(default_factory=list)


def _split_sections(
    text: str,
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
            # Lines between 0 NOFILE and the next 0 FILE are ignored.
            current = None
        elif current is not None:
            current.append((number, line))
    return preamble, sections


def _parse_objects(
    numbered_lines: Iterable[_NumberedLine],
    *,
    source: Path | str | None,
) -> list[ParsedObject]:
    """Parse numbered lines, adding file and line context to errors."""
    objects: list[ParsedObject] = []
    for number, line in numbered_lines:
        try:
            parsed = parse_ldraw_line(line)
        except PartError as parse_error:
            message = (
                f"{parse_error.message} in {source or '<string>'} at line {number}"
            )
            raise PartError(message) from parse_error
        if parsed is not None:
            objects.append(parsed)
    return objects


@dataclass(slots=True)
class Model:
    """A whole LDraw model, optionally with MPD submodels."""

    name: str = ""
    objects: list[ParsedObject] = field(default_factory=list)
    submodels: dict[str, Model] = field(default_factory=dict)

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
        """The description from the first line, when it is a comment."""
        match self.objects:
            case [Comment(text=text), *_]:
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
    ) -> None:
        """Set or replace standard header comments at the top of the model."""
        if description is not None:
            self._set_description(description)
        if name is not None:
            self._set_header_comment(prefix="Name:", value=name)
        if author is not None:
            self._set_header_comment(prefix="Author:", value=author)

    def _has_description(self) -> bool:
        match self.objects:
            case [Comment(text=text), *_]:
                return not text.startswith(_MANAGED_HEADER_PREFIXES)
            case _:
                return False

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
        flat mapping, since serialization only walks one level.
        """
        if not submodel.name:
            raise SubmodelNameRequiredError
        key = normalize_ref(submodel.name)
        incoming = {key: submodel, **submodel.submodels}
        for new_key, new_model in incoming.items():
            if new_key == normalize_ref(self.name) or new_key in self.submodels:
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

    def iter_pieces(self) -> Iterator[Piece]:
        """Recursively yield leaf pieces, expanding submodel references."""
        return _iter_model_pieces(root=self, model=self, visiting=frozenset())

    def find_pieces(
        self,
        *,
        part: str | None = None,
        colour: Colour | int | None = None,
        recursive: bool = False,
    ) -> list[Piece]:
        """Return pieces matching the given part code and/or colour."""
        source: Iterable[Piece] = self.iter_pieces() if recursive else self.pieces
        wanted_part = part.upper() if part is not None else None
        return [
            piece
            for piece in source
            if (wanted_part is None or piece.part == wanted_part)
            and (colour is None or piece.colour == colour)
        ]

    def to_ldraw(self) -> str:
        """Serialize the model (and any submodels) to LDraw text."""
        if not self.submodels:
            return "\n".join(obj.to_ldraw() for obj in self.objects)
        sections: list[str] = []
        for model in (self, *self.submodels.values()):
            if not model.name:
                raise SubmodelNameRequiredError
            sections.append(
                "\n".join(
                    (
                        f"0 FILE {model.name}",
                        *(obj.to_ldraw() for obj in model.objects),
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
    preamble, sections = _split_sections(text)
    objects = _parse_objects(preamble, source=source)
    if not sections:
        return Model(name=name, objects=objects)
    first, *rest = sections
    root = Model(
        name=first.name,
        objects=[*objects, *_parse_objects(first.lines, source=source)],
    )
    for section in rest:
        key = normalize_ref(section.name)
        if key == normalize_ref(root.name) or key in root.submodels:
            raise DuplicateSubmodelError(section.name)
        root.submodels[key] = Model(
            name=section.name,
            objects=_parse_objects(section.lines, source=source),
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
