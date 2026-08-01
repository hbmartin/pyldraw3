"""Tests for the persistent SQLite parts index."""

import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from ldraw.catalog import (
    CATALOG_SCHEMA_VERSION,
    catalog_db_path,
    load_catalog,
    load_parts,
    parts_lst_md5,
    parts_tree_fingerprint,
    save_catalog,
)
from ldraw.parts import CatalogEntry, PartCategory, Parts, PartsCatalog

PARTS_LST: Path = (
    Path(__file__).resolve().parent / "test_ldraw2" / "ldraw" / "parts.lst"
)
LIBRARY_ROOT: Path = PARTS_LST.parent
TREE: str = parts_tree_fingerprint(LIBRARY_ROOT)


@pytest.fixture
def slow_catalog() -> PartsCatalog:
    return Parts(PARTS_LST).catalog


def entry_key(entry: CatalogEntry) -> tuple[object, ...]:
    return (
        entry.code,
        entry.description,
        entry.category,
        entry.minifig_section,
        str(entry.part.path) if entry.part is not None else None,
        entry.keywords,
        entry.metadata,
    )


def test_save_load_round_trip_matches_slow_path(tmp_path, slow_catalog) -> None:
    db_path = tmp_path / "catalog.sqlite"
    md5 = parts_lst_md5(PARTS_LST)

    save_catalog(
        db_path,
        md5=md5,
        catalog=slow_catalog,
        library_root=LIBRARY_ROOT,
        tree_fingerprint=TREE,
    )
    loaded = load_catalog(
        db_path,
        md5=md5,
        library_root=LIBRARY_ROOT,
        tree_fingerprint=TREE,
    )

    assert loaded is not None
    assert list(loaded.by_code) == list(slow_catalog.by_code)
    for code, entry in slow_catalog.by_code.items():
        assert entry_key(loaded.by_code[code]) == entry_key(entry)
    assert {s: len(e) for s, e in loaded.by_minifig_section.items()} == {
        s: len(e) for s, e in slow_catalog.by_minifig_section.items()
    }
    assert loaded.module_sections() == slow_catalog.module_sections()


def test_load_catalog_missing_file_returns_none(tmp_path) -> None:
    assert (
        load_catalog(
            tmp_path / "nope.sqlite",
            md5="x",
            library_root=LIBRARY_ROOT,
            tree_fingerprint="t",
        )
        is None
    )


def test_load_catalog_stale_md5_returns_none(tmp_path, slow_catalog) -> None:
    db_path = tmp_path / "catalog.sqlite"
    save_catalog(
        db_path,
        md5="old",
        catalog=slow_catalog,
        library_root=LIBRARY_ROOT,
        tree_fingerprint="t",
    )

    assert (
        load_catalog(
            db_path,
            md5="new",
            library_root=LIBRARY_ROOT,
            tree_fingerprint="t",
        )
        is None
    )


def test_load_catalog_wrong_schema_version_returns_none(
    tmp_path,
    slow_catalog,
) -> None:
    db_path = tmp_path / "catalog.sqlite"
    md5 = parts_lst_md5(PARTS_LST)
    save_catalog(
        db_path,
        md5=md5,
        catalog=slow_catalog,
        library_root=LIBRARY_ROOT,
        tree_fingerprint=TREE,
    )
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute(f"PRAGMA user_version = {CATALOG_SCHEMA_VERSION + 1}")

    assert (
        load_catalog(db_path, md5=md5, library_root=LIBRARY_ROOT, tree_fingerprint=TREE)
        is None
    )


def test_fresh_catalog_entries_carry_keywords(slow_catalog) -> None:
    keywords = slow_catalog.by_code["3959"].keywords
    assert keywords[:3] == ("Space", "Castle", "Pirates")
    assert "female stud" in keywords  # from a second !KEYWORDS line


def test_keywords_round_trip_through_index(tmp_path, slow_catalog) -> None:
    db_path = tmp_path / "catalog.sqlite"
    md5 = parts_lst_md5(PARTS_LST)

    save_catalog(
        db_path,
        md5=md5,
        catalog=slow_catalog,
        library_root=LIBRARY_ROOT,
        tree_fingerprint=TREE,
    )
    loaded = load_catalog(
        db_path,
        md5=md5,
        library_root=LIBRARY_ROOT,
        tree_fingerprint=TREE,
    )

    assert loaded is not None
    assert loaded.by_code["3959"].keywords == slow_catalog.by_code["3959"].keywords
    assert loaded.by_code["3959"].keywords != ()


def test_load_catalog_v1_schema_returns_none(tmp_path) -> None:
    """An old v1 index (no keywords column) must trigger a rebuild, not crash."""
    db_path = tmp_path / "catalog.sqlite"
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute("PRAGMA user_version = 1")
        connection.execute(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        )
        connection.execute(
            "CREATE TABLE parts (code TEXT PRIMARY KEY, description TEXT NOT NULL,"
            " category TEXT NOT NULL, minifig_section TEXT, path TEXT)",
        )
        connection.execute(
            "INSERT INTO meta (key, value) VALUES ('parts_lst_md5', 'x')",
        )

    assert (
        load_catalog(db_path, md5="x", library_root=LIBRARY_ROOT, tree_fingerprint="t")
        is None
    )


def test_load_catalog_corrupt_file_returns_none(tmp_path) -> None:
    db_path = tmp_path / "catalog.sqlite"
    db_path.write_bytes(b"this is not a sqlite database at all")

    assert (
        load_catalog(db_path, md5="x", library_root=LIBRARY_ROOT, tree_fingerprint="t")
        is None
    )


def test_load_catalog_corrupt_metadata_json_triggers_rebuild(
    tmp_path: Path,
    slow_catalog: PartsCatalog,
) -> None:
    """Truncated metadata_json in an existing index must force a rebuild."""
    db_path = tmp_path / "catalog.sqlite"
    md5 = parts_lst_md5(PARTS_LST)
    save_catalog(
        db_path,
        md5=md5,
        catalog=slow_catalog,
        library_root=LIBRARY_ROOT,
        tree_fingerprint=TREE,
    )
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute("""UPDATE parts SET metadata_json = '{"truncated'""")

    assert (
        load_catalog(db_path, md5=md5, library_root=LIBRARY_ROOT, tree_fingerprint=TREE)
        is None
    )


def test_load_catalog_invalid_metadata_shape_triggers_rebuild(
    tmp_path: Path,
    slow_catalog: PartsCatalog,
) -> None:
    """Valid JSON with an invalid metadata shape must also force a rebuild."""
    db_path = tmp_path / "catalog.sqlite"
    md5 = parts_lst_md5(PARTS_LST)
    save_catalog(
        db_path,
        md5=md5,
        catalog=slow_catalog,
        library_root=LIBRARY_ROOT,
        tree_fingerprint=TREE,
    )
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute("""UPDATE parts SET metadata_json = '{"preview": {}}'""")

    assert (
        load_catalog(db_path, md5=md5, library_root=LIBRARY_ROOT, tree_fingerprint=TREE)
        is None
    )


def test_load_catalog_unknown_category_returns_none(tmp_path, slow_catalog) -> None:
    db_path = tmp_path / "catalog.sqlite"
    md5 = parts_lst_md5(PARTS_LST)
    save_catalog(
        db_path,
        md5=md5,
        catalog=slow_catalog,
        library_root=LIBRARY_ROOT,
        tree_fingerprint=TREE,
    )
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute("UPDATE parts SET category = 'not-a-category'")

    assert (
        load_catalog(db_path, md5=md5, library_root=LIBRARY_ROOT, tree_fingerprint=TREE)
        is None
    )


def test_paths_outside_library_root_stay_absolute(tmp_path) -> None:
    from ldraw.part import Part

    outside = tmp_path / "elsewhere" / "3001.dat"
    outside.parent.mkdir()
    outside.write_text("0 Brick\n")
    catalog = PartsCatalog()
    catalog.add(
        CatalogEntry(
            code="3001",
            description="Brick",
            category=PartCategory.BRICK,
            part=Part(outside),
        ),
    )
    db_path = tmp_path / "catalog.sqlite"

    save_catalog(
        db_path,
        md5="x",
        catalog=catalog,
        library_root=LIBRARY_ROOT,
        tree_fingerprint="t",
    )
    loaded = load_catalog(
        db_path,
        md5="x",
        library_root=LIBRARY_ROOT,
        tree_fingerprint="t",
    )

    assert loaded is not None
    loaded_part = loaded.by_code["3001"].part
    assert loaded_part is not None
    assert loaded_part.path == outside


def test_save_catalog_handles_entries_without_part(tmp_path) -> None:
    catalog = PartsCatalog()
    catalog.add(
        CatalogEntry(code="3001", description="Brick", category=PartCategory.BRICK),
    )
    db_path = tmp_path / "catalog.sqlite"

    save_catalog(
        db_path,
        md5="x",
        catalog=catalog,
        library_root=LIBRARY_ROOT,
        tree_fingerprint="t",
    )
    loaded = load_catalog(
        db_path,
        md5="x",
        library_root=LIBRARY_ROOT,
        tree_fingerprint="t",
    )

    assert loaded is not None
    assert loaded.by_code["3001"].part is None


def test_load_parts_builds_and_reuses_the_index(tmp_path, monkeypatch) -> None:
    Parts.clear_cache()
    db_path = catalog_db_path(tmp_path)
    assert not db_path.exists()

    first = load_parts(PARTS_LST, tmp_path, build_index=True)
    assert first.get_entry_by_code("3005") is not None
    assert db_path.is_file()

    # The fast path must never run the categorization pass.
    def boom(self) -> None:
        message = "categorization must not run on the fast path"
        raise AssertionError(message)

    monkeypatch.setattr(Parts, "_categorize_parts", boom)
    Parts.clear_cache()
    second = load_parts(PARTS_LST, tmp_path)
    assert second.get_entry_by_code("3005") is not None
    assert list(second.catalog.by_code) == list(first.catalog.by_code)


def test_load_parts_without_build_index_leaves_no_file(tmp_path) -> None:
    Parts.clear_cache()

    parts = load_parts(PARTS_LST, tmp_path)

    assert parts.by_code  # cheap pass ran
    assert not catalog_db_path(tmp_path).exists()


def test_load_parts_swallows_save_failures(tmp_path) -> None:
    Parts.clear_cache()
    blocker = tmp_path / "generated"
    blocker.write_text("a file where the directory should be")

    parts = load_parts(PARTS_LST, blocker / "sub", build_index=True)

    assert parts.get_entry_by_code("3005") is not None


def test_catalog_db_path() -> None:
    assert catalog_db_path("/gen") == Path("/gen/catalog.sqlite")


def test_lazy_categorization_only_runs_on_catalog_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parts = Parts(PARTS_LST)
    assert parts.by_code  # parts.lst pass already done

    calls = {"count": 0}
    original = Parts._categorize_parts  # noqa: SLF001

    def counting(self: Parts) -> None:
        calls["count"] += 1
        original(self)

    monkeypatch.setattr(Parts, "_categorize_parts", counting)
    assert parts.part(code="3005") is not None  # no categorization needed
    assert calls["count"] == 0

    assert parts.get_entry_by_code("3005") is not None
    assert parts.entries_by_category(PartCategory.BRICK)
    assert calls["count"] == 1  # first catalog access, exactly once


def test_stale_tree_fingerprint_returns_none(
    tmp_path: Path,
    slow_catalog: PartsCatalog,
) -> None:
    db_path = tmp_path / "catalog.sqlite"
    md5 = parts_lst_md5(PARTS_LST)
    save_catalog(
        db_path,
        md5=md5,
        catalog=slow_catalog,
        library_root=LIBRARY_ROOT,
        tree_fingerprint="old",
    )

    assert (
        load_catalog(
            db_path,
            md5=md5,
            library_root=LIBRARY_ROOT,
            tree_fingerprint="new",
        )
        is None
    )


def test_dat_header_edit_invalidates_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library = tmp_path / "ldraw"
    shutil.copytree(LIBRARY_ROOT, library)
    parts_lst = library / "parts.lst"
    generated = tmp_path / "generated"
    Parts.clear_cache()
    first = load_parts(parts_lst, generated, build_index=True)
    first_entry = first.get_entry_by_code("3005")
    assert first_entry is not None
    assert "edited" not in first_entry.keywords
    unrelated = Parts.get(PARTS_LST, tree_fingerprint=TREE)

    target = library / "parts" / "3005.dat"
    text = target.read_text()
    target.write_text(
        text.replace(
            "0 !LICENSE Redistributable",
            "0 !KEYWORDS edited\n0 !LICENSE Redistributable",
            1,
        ),
    )

    calls = {"count": 0}
    original = Parts._categorize_parts  # noqa: SLF001

    def counting(self: Parts) -> None:
        calls["count"] += 1
        original(self)

    monkeypatch.setattr(Parts, "_categorize_parts", counting)
    parts = load_parts(parts_lst, generated)
    entry = parts.get_entry_by_code("3005")
    assert entry is not None
    assert "edited" in entry.keywords
    assert parts is not first
    assert calls["count"] == 1
    assert Parts.get(PARTS_LST, tree_fingerprint=TREE) is unrelated


def test_dat_header_edit_invalidates_memo_without_index(tmp_path: Path) -> None:
    library = tmp_path / "ldraw"
    shutil.copytree(LIBRARY_ROOT, library)
    parts_lst = library / "parts.lst"
    generated = tmp_path / "generated"
    Parts.clear_cache()
    first = load_parts(parts_lst, generated, build_index=False)
    first_entry = first.get_entry_by_code("3005")
    assert first_entry is not None
    assert "edited" not in first_entry.keywords
    assert not catalog_db_path(generated).is_file()

    target = library / "parts" / "3005.dat"
    text = target.read_text()
    target.write_text(
        text.replace(
            "0 !LICENSE Redistributable",
            "0 !KEYWORDS edited\n0 !LICENSE Redistributable",
            1,
        ),
    )

    second = load_parts(parts_lst, generated, build_index=False)
    entry = second.get_entry_by_code("3005")
    assert entry is not None
    assert "edited" in entry.keywords
    assert second is not first


def test_parts_lst_md5_invalidates_memo_when_stat_key_is_unchanged(
    tmp_path: Path,
) -> None:
    library = tmp_path / "ldraw"
    shutil.copytree(LIBRARY_ROOT, library)
    parts_lst = library / "parts.lst"
    generated = tmp_path / "generated"
    Parts.clear_cache()
    first = load_parts(parts_lst, generated, build_index=True)
    assert first.by_code["3005"] == "Brick  1 x  1"
    unrelated = Parts.get(PARTS_LST, tree_fingerprint=TREE)

    original_stat = parts_lst.stat()
    original = parts_lst.read_bytes()
    edited = original.replace(b"Brick  1 x  1", b"Brick  1 x  9", 1)
    assert len(edited) == len(original)
    parts_lst.write_bytes(edited)
    os.utime(
        parts_lst,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    assert parts_lst.stat().st_size == original_stat.st_size
    assert parts_lst.stat().st_mtime_ns == original_stat.st_mtime_ns

    second = load_parts(parts_lst, generated)

    assert second is not first
    assert second.by_code["3005"] == "Brick  1 x  9"
    assert Parts.get(PARTS_LST, tree_fingerprint=TREE) is unrelated


def test_tree_fingerprint_includes_relative_paths(tmp_path: Path) -> None:
    parts_dir = tmp_path / "parts"
    parts_dir.mkdir()
    original = parts_dir / "3001.dat"
    original.write_text("0 Brick 2 x 4\n")
    before = parts_tree_fingerprint(tmp_path)

    original.rename(parts_dir / "renamed.dat")

    assert parts_tree_fingerprint(tmp_path) != before


def test_fresh_index_load_is_memoized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Parts.clear_cache()
    load_parts(PARTS_LST, tmp_path, build_index=True)

    def boom(self: Parts) -> None:
        message = "categorization must not run on the fast path"
        raise AssertionError(message)

    monkeypatch.setattr(Parts, "_categorize_parts", boom)
    Parts.clear_cache()
    second = load_parts(PARTS_LST, tmp_path)
    third = load_parts(PARTS_LST, tmp_path)

    assert second is third
    assert second.get_entry_by_code("3005") is not None
