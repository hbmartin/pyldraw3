# API Reference

The generated API reference covers the stable public surface and the modules
most users interact with directly.

## Public API

Start with [Public API](public.md) for the names exported from `ldraw`:
`Model`, `Piece`, `Group`, `Person`, `Parts`, geometry types, validation
types, and helper functions.

## Module References

- [Models and Pieces](models.md): model files, MPD submodels, piece placement,
  groups, colours, and transformation primitives.
- [Parts and Geometry](parts.md): parts catalog lookup, generated-library
  helpers, bounding boxes, studs, and part metadata.
- [LDraw Lines](lines.md): parsed line objects, raw part parsing, and
  serialization primitives.
- [Utilities](utilities.md): bill-of-materials helpers, validation, config,
  and exceptions.

Generated `ldraw.library.*` modules are intentionally not included here because
they depend on the locally downloaded LDraw release. Run `ldraw generate` and
`ldraw stubs` in consuming projects for release-specific import and type-stub
coverage.
