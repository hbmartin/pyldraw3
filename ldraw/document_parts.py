"""Document-local definitions layered over an immutable library source."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ldraw._connection_sources import _SourceText
from ldraw.connection_metadata import LDCadShadowLibrary
from ldraw.diagnostics import Diagnostic, Severity
from ldraw.part import Part
from ldraw.part_metadata import PartMetadata, parse_metadata_lines
from ldraw.parts import CatalogEntry, PartCategory, Parts, PartsCatalog
from ldraw.utils import normalize_ref, split_reference

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ldraw._connection_results import ShadowConnectionResult
    from ldraw.model import Model
    from ldraw.part import ParsedObject
    from ldraw.part_geometry_types import PartGeometry


class EmbeddedPart(Part):
    """A Part-compatible definition read directly from a Model section."""

    def __init__(self, model: Model, base: Parts) -> None:
        super().__init__(base.library_root / model.name)
        self.model = model

    @property
    def objects(self) -> Iterator[ParsedObject]:
        """Yield authored records without serialization or installed-file edits."""
        yield from self.model.objects

    @property
    def lines(self) -> Iterator[str]:
        """Serialize records only for header interpretation."""
        yield from (obj.to_ldraw() for obj in self.model.objects)

    @property
    def metadata(self) -> PartMetadata:
        """Interpret declared file kinds, authorship, licence, and aliases."""
        lines = list(self.lines)
        return (
            parse_metadata_lines(lines)
            if lines
            else PartMetadata(description=self.model.name)
        )


class DocumentParts(Parts):
    """Resolution and geometry caches isolated to one unchanged document."""

    def __init__(self, base: Parts, model: Model) -> None:
        self.__dict__ = base.__dict__.copy()
        self.base = base
        self.model = model
        self._connection_shadow_libraries = list(base._connection_shadow_libraries)  # noqa: SLF001
        self._studio_connection_libraries = list(base._studio_connection_libraries)  # noqa: SLF001
        self._connection_overrides = dict(base._connection_overrides)  # noqa: SLF001
        self.search_index = None
        self.embedded = {
            normalize_ref(section.name): EmbeddedPart(section, base)
            for section in (model, *model.submodels.values())
            if section.name
        }
        self.diagnostics = (*base.diagnostics, *self._shadowing())
        self._document_connections = _DocumentConnections(self)
        self._reuse_library_geometry = not any(
            name.endswith(".dat") for name in self.embedded
        )

    def _connection_shadows_for_inline(self) -> tuple[LDCadShadowLibrary, ...]:
        return (self._document_connections, *super()._connection_shadows_for_inline())

    def _connection_metadata_for(self, code: str) -> tuple[ShadowConnectionResult, ...]:
        """Keep library metadata from describing a document replacement."""
        key = normalize_ref(code)
        if key in self.embedded or f"{key}.dat" in self.embedded:
            return ()
        return super()._connection_metadata_for(code)

    def _shadowing(self) -> Iterator[Diagnostic]:
        for name in self.embedded:
            code, _ = split_reference(name)
            if name.endswith(".dat") and self.base.find_part(code=code) is not None:
                yield Diagnostic(
                    code="document.library_shadowing",
                    severity=Severity.WARNING,
                    section=name,
                    offending_value=name,
                    message=(
                        f"Embedded definition {name!r} shadows a library definition"
                    ),
                )

    def part(self, description: str | None = None, code: str | None = None) -> Part:
        """Resolve document definitions before external definitions."""
        if code is not None:
            key = normalize_ref(code)
            candidates = (
                (key,)
                if key.endswith((".dat", ".ldr", ".mpd"))
                else (f"{key}.dat", key)
            )
            for candidate in candidates:
                if candidate in self.embedded:
                    return self.embedded[candidate]
        return self.base.part(description=description, code=code)

    def geometry(self, code: str) -> PartGeometry:
        """Reuse library caches when embedded model sections cannot shadow geometry."""
        key = normalize_ref(code)
        if (
            self._reuse_library_geometry
            and key not in self.embedded
            and not key.endswith((".ldr", ".mpd"))
        ):
            return self.base.geometry(code)
        return super().geometry(code)

    def _clear_derived_geometry(self) -> None:
        self._reuse_library_geometry = False
        super()._clear_derived_geometry()

    def description_for(self, code: str) -> str | None:
        """Use embedded descriptions when the reference is shadowed."""
        if (part := self.find_part(code=code)) is not None:
            return part.description
        return None

    @property
    def catalog(self) -> PartsCatalog:
        """Return a catalog with document definitions taking precedence."""
        catalog = PartsCatalog()
        for entry in self.base.catalog.by_code.values():
            catalog.add(entry)
        for name, part in self.embedded.items():
            code, _ = split_reference(name)
            catalog.add(
                CatalogEntry(
                    code=code,
                    description=part.description,
                    category=PartCategory.from_label(part.category)
                    or PartCategory.OTHER,
                    part=part,
                    metadata=part.metadata,
                )
            )
        return catalog


class _DocumentConnections(LDCadShadowLibrary):
    """Reuse the include resolver over definitions instead of temporary files."""

    def __init__(self, parts: DocumentParts) -> None:
        super().__init__(parts.library_root)
        self.parts = parts

    def _read_shadow_text(self, code: str) -> _SourceText | None:
        if (part := self.parts.find_part(code=code)) is None:
            return None
        text = "\n".join(line.rstrip("\r\n") for line in part.lines)
        if not isinstance(part, EmbeddedPart) and "!LDCAD" not in text.upper():
            return None
        return _SourceText(
            text=text,
            path=part.path,
            archive_member=None,
            logical_name=code,
        )
