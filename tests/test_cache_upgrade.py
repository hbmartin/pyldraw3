"""Listing parser changes invalidate persisted catalog and generation state."""

import re
from pathlib import Path

import pytest

from ldraw import _parts_listing, catalog, generation
from ldraw.config import Config


def test_old_listing_catalog_and_generated_library_rebuild_automatically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "source" / "ldraw"
    (root / "parts").mkdir(parents=True)
    (root / "parts" / "custom.dat").write_text("0 Brick Legacy\n0 !CATEGORY Brick\n")
    (root / "parts" / "custom.dat.v1.dat").write_text(
        "0 Brick Dotted\n0 !CATEGORY Brick\n"
    )
    listing = root / "parts.lst"
    listing.write_text("custom.dat.v1.dat  Brick Dotted\n")
    config = Config(
        ldraw_library_path=str(root.parent), generated_path=str(tmp_path / "generated")
    )
    before = catalog.catalog_fingerprint(listing)
    with monkeypatch.context() as legacy:
        legacy.setattr(
            _parts_listing, "DOT_DAT", re.compile(r"\.DAT", flags=re.IGNORECASE)
        )
        legacy.setattr(catalog, "CATALOG_SCHEMA_VERSION", 6)
        legacy.setattr(generation, "GENERATION_SCHEMA_VERSION", 3)
        generation.generate(config)
    fingerprint_path = generation.generation_hash_path(config.generated_path)
    legacy_fingerprint = fingerprint_path.read_text()
    assert legacy_fingerprint.startswith("3\n")
    legacy_modules = list((fingerprint_path.parent / "parts").glob("*.py"))
    assert any("= 'custom'" in path.read_text() for path in legacy_modules)
    assert (
        catalog.load_catalog(
            catalog.catalog_db_path(config.generated_path),
            md5=before.parts_lst_md5,
            library_root=root,
            tree_fingerprint=before.tree_fingerprint,
        )
        is None
    )
    generation.generate(config)
    assert catalog.catalog_fingerprint(listing) == before
    fingerprint = fingerprint_path.read_text()
    assert fingerprint.startswith("4\n")
    assert fingerprint.splitlines()[1:] == legacy_fingerprint.splitlines()[1:]
    modules = list((fingerprint_path.parent / "parts").glob("*.py"))
    assert any("= 'custom.dat.v1'" in path.read_text() for path in modules)
    assert all("= 'custom'" not in path.read_text() for path in modules)
    rebuilt = catalog.load_catalog(
        catalog.catalog_db_path(config.generated_path),
        md5=before.parts_lst_md5,
        library_root=root,
        tree_fingerprint=before.tree_fingerprint,
    )
    assert rebuilt is not None
    assert list(rebuilt.by_code) == ["custom.dat.v1"]
