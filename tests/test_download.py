"""Tests for download functionality."""

import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Self
from unittest.mock import MagicMock, patch

import pytest
import requests

from ldraw import download
from ldraw.downloads import (
    ARCHIVE_URL,
    LDRAW_URL,
    ArchiveIntegrity,
    _case_safe_rename,
    _download,
    _normalize_tree,
    _temporary_rename_path,
    check_archive_integrity,
    unpack_version,
)


class FakeResponse:
    """Minimal stand-in for a streamed ``requests`` response."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        chunks: tuple[bytes, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks
        self._error = error

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        """Raise ``HTTPError`` for 4xx/5xx status codes."""
        if self.status_code >= 400:
            message = f"status {self.status_code}"
            raise requests.HTTPError(message)

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:  # noqa: ARG002
        """Yield the queued chunks, then raise the queued error if any."""
        yield from self._chunks
        if self._error is not None:
            raise self._error


def _install_fake_get(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[FakeResponse],
) -> list[dict[str, str] | None]:
    """Serve queued responses from ``requests.get`` and record headers."""
    sent_headers: list[dict[str, str] | None] = []

    def fake_get(
        *,
        url: str,
        stream: bool,
        timeout: int,
        headers: dict[str, str] | None,
    ) -> FakeResponse:
        assert stream is True
        assert timeout == 30
        sent_headers.append(headers)
        return responses.pop(0)

    monkeypatch.setattr("ldraw.downloads.requests.get", fake_get)
    return sent_headers


def _write_sidecar(
    partial: Path,
    *,
    etag: str | None = '"v1"',
    total: int | None = None,
) -> Path:
    sidecar = partial.with_name(f"{partial.name}.meta")
    sidecar.write_text(
        json.dumps({"etag": etag, "last_modified": None, "total": total}),
        encoding="utf-8",
    )
    return sidecar


@patch("zipfile.ZipFile", spec=zipfile.ZipFile)
@patch("ldraw.downloads._download")
@patch("ldraw.downloads.generate_parts_lst")
def test_download(
    generate_parts_lst_mock: MagicMock,
    download_mock: MagicMock,
    zip_mock: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    zip_mock.return_value.__enter__.return_value.infolist.return_value = []
    zip_mock.return_value.__enter__.return_value.testzip.return_value = None
    retrieved = tmp_path / "complete.zip"

    def retrieve(**_kwargs: object) -> Path:
        retrieved.write_bytes(b"zip")
        return retrieved

    download_mock.side_effect = retrieve

    with patch(
        "ldraw.downloads.get_latest_release_id",
        return_value="2099-01",
    ) as get_latest_release_id_mock:
        download()

    download_mock.assert_called_once()
    assert download_mock.call_args.kwargs["show_progress"] is True
    get_latest_release_id_mock.assert_called_once()
    generate_parts_lst_mock.assert_called_once()


@patch("ldraw.downloads.generate_parts_lst")
@patch("ldraw.downloads.unpack_version")
@patch("ldraw.downloads._download")
def test_download_versioned_uses_archive_url(
    download_mock: MagicMock,
    unpack_version_mock: MagicMock,
    generate_parts_lst_mock: MagicMock,
    tmp_path: Path,
) -> None:
    retrieved = tmp_path / "2018-02.zip"
    with zipfile.ZipFile(retrieved, "w") as archive:
        archive.writestr("ldraw/parts.lst", "parts")
    download_mock.return_value = retrieved

    download(show_progress=False, version="2018-02")

    assert download_mock.call_args.kwargs["url"] == f"{ARCHIVE_URL}/2018-02.zip"


@patch("ldraw.downloads.get_latest_release_id", return_value="2099-01")
@patch("ldraw.downloads.generate_parts_lst")
@patch("ldraw.downloads.unpack_version")
@patch("ldraw.downloads._download")
def test_download_complete_uses_ldraw_url(
    download_mock: MagicMock,
    unpack_version_mock: MagicMock,
    generate_parts_lst_mock: MagicMock,
    get_latest_release_id_mock: MagicMock,
    tmp_path: Path,
) -> None:
    retrieved = tmp_path / "retrieved.zip"
    with zipfile.ZipFile(retrieved, "w") as archive:
        archive.writestr("ldraw/parts.lst", "parts")
    download_mock.return_value = retrieved
    unpack_version_mock.return_value = tmp_path

    assert download(show_progress=False) == "2099-01"

    assert download_mock.call_args.kwargs["url"] == f"{LDRAW_URL}/complete.zip"
    assert (tmp_path / "ldraw" / "_release.txt").read_text() == "2099-01"


def test_download_rejects_invalid_version() -> None:
    with pytest.raises(ValueError, match="Unsupported LDraw library version"):
        download(show_progress=False, version="../bad")


def test_unpack_version_rejects_unsafe_zip_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version_zip = tmp_path / "bad.zip"
    with zipfile.ZipFile(version_zip, "w") as zip_file:
        zip_file.writestr("../escape.dat", "bad")
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path / "cache")

    with pytest.raises(ValueError, match="Unsafe ZIP member path"):
        unpack_version(version_zip=version_zip, version="2018-02")

    assert not (tmp_path / "escape.dat").exists()


def test_unpack_version_rejects_invalid_version(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported LDraw library version"):
        unpack_version(version_zip=tmp_path / "missing.zip", version="../bad")


@patch("ldraw.downloads.requests.get")
def test_download_failure_leaves_no_cached_file(
    get_mock: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    response = get_mock.return_value.__enter__.return_value
    response.iter_content.side_effect = requests.ConnectionError("dropped")

    with pytest.raises(requests.ConnectionError):
        _download(url="https://example.test/x.zip", filename="x.zip")

    assert not (tmp_path / "x.zip").exists()


@patch("ldraw.downloads.requests.get")
def test_download_success_replaces_partial_file(
    get_mock: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    response = get_mock.return_value.__enter__.return_value
    response.iter_content.return_value = [b"zip-bytes"]

    result = _download(url="https://example.test/x.zip", filename="x.zip")

    assert result == tmp_path / "x.zip"
    assert result.read_bytes() == b"zip-bytes"
    assert not (tmp_path / "x.zip.part").exists()


def test_download_resume_appends_partial_and_sends_range_with_if_range(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    partial = tmp_path / "x.zip.part"
    partial.write_bytes(b"first-")
    sidecar = _write_sidecar(partial, etag='"v1"', total=12)
    sent_headers = _install_fake_get(
        monkeypatch,
        [
            FakeResponse(
                status_code=206,
                headers={
                    "content-length": "6",
                    "content-range": "bytes 6-11/12",
                    "etag": '"v1"',
                },
                chunks=(b"second",),
            ),
        ],
    )

    result = _download(
        url="https://example.test/x.zip",
        filename="x.zip",
        resume=True,
    )

    assert sent_headers == [{"Range": "bytes=6-", "If-Range": '"v1"'}]
    assert result.read_bytes() == b"first-second"
    assert not partial.exists()
    assert not sidecar.exists()


def test_download_resume_without_stored_validator_restarts_from_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    partial = tmp_path / "x.zip.part"
    partial.write_bytes(b"stale-bytes")
    sent_headers = _install_fake_get(
        monkeypatch,
        [FakeResponse(headers={"content-length": "5"}, chunks=(b"fresh",))],
    )

    result = _download(
        url="https://example.test/x.zip",
        filename="x.zip",
        resume=True,
    )

    assert sent_headers == [None]
    assert result.read_bytes() == b"fresh"


def test_download_resume_200_response_truncates_and_restarts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    partial = tmp_path / "x.zip.part"
    partial.write_bytes(b"first-")
    _write_sidecar(partial, etag='"v1"', total=12)
    sent_headers = _install_fake_get(
        monkeypatch,
        [FakeResponse(headers={"content-length": "9"}, chunks=(b"full-body",))],
    )

    result = _download(
        url="https://example.test/x.zip",
        filename="x.zip",
        resume=True,
    )

    assert sent_headers == [{"Range": "bytes=6-", "If-Range": '"v1"'}]
    assert result.read_bytes() == b"full-body"


def test_download_resume_416_discards_partial_and_restarts_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    partial = tmp_path / "x.zip.part"
    partial.write_bytes(b"oversized-partial")
    sidecar = _write_sidecar(partial, etag='"v1"', total=4)
    sent_headers = _install_fake_get(
        monkeypatch,
        [
            FakeResponse(status_code=416),
            FakeResponse(headers={"content-length": "4"}, chunks=(b"good",)),
        ],
    )

    result = _download(
        url="https://example.test/x.zip",
        filename="x.zip",
        resume=True,
    )

    assert len(sent_headers) == 2
    assert sent_headers[1] is None
    assert result.read_bytes() == b"good"
    assert not sidecar.exists()


def test_download_resume_416_finalizes_complete_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    partial = tmp_path / "x.zip.part"
    partial.write_bytes(b"complete-bytes")
    _write_sidecar(partial, etag='"v1"', total=len(b"complete-bytes"))
    sent_headers = _install_fake_get(
        monkeypatch,
        [
            FakeResponse(
                status_code=416,
                headers={
                    "content-range": f"bytes */{len(b'complete-bytes')}",
                    "etag": '"v1"',
                },
            ),
        ],
    )

    result = _download(
        url="https://example.test/x.zip",
        filename="x.zip",
        resume=True,
    )

    assert len(sent_headers) == 1
    assert result.read_bytes() == b"complete-bytes"
    assert not partial.exists()


def test_download_resume_416_remote_size_overrides_stale_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    partial = tmp_path / "x.zip.part"
    partial.write_bytes(b"stale")
    _write_sidecar(partial, etag='"v1"', total=len(b"stale"))
    fresh = b"new!"
    sent_headers = _install_fake_get(
        monkeypatch,
        [
            FakeResponse(
                status_code=416,
                headers={"content-range": f"bytes */{len(fresh)}"},
            ),
            FakeResponse(
                headers={"content-length": str(len(fresh))},
                chunks=(fresh,),
            ),
        ],
    )

    result = _download(
        url="https://example.test/x.zip",
        filename="x.zip",
        resume=True,
    )

    assert len(sent_headers) == 2
    assert sent_headers[1] is None
    assert result.read_bytes() == fresh


def test_download_resume_416_restarts_when_same_size_validator_changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    partial = tmp_path / "x.zip.part"
    partial.write_bytes(b"stale")
    _write_sidecar(partial, etag='"v1"', total=5)
    sent_headers = _install_fake_get(
        monkeypatch,
        [
            FakeResponse(
                status_code=416,
                headers={"content-range": "bytes */5", "etag": '"v2"'},
            ),
            FakeResponse(headers={"content-length": "5"}, chunks=(b"fresh",)),
        ],
    )

    result = _download(
        url="https://example.test/x.zip",
        filename="x.zip",
        resume=True,
    )

    assert sent_headers == [
        {"Range": "bytes=5-", "If-Range": '"v1"'},
        None,
    ]
    assert result.read_bytes() == b"fresh"


def test_download_resume_206_restarts_when_response_validator_changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    partial = tmp_path / "x.zip.part"
    partial.write_bytes(b"old-")
    _write_sidecar(partial, etag='"v1"', total=8)
    sent_headers = _install_fake_get(
        monkeypatch,
        [
            FakeResponse(
                status_code=206,
                headers={
                    "content-length": "4",
                    "content-range": "bytes 4-7/8",
                    "etag": '"v2"',
                },
                chunks=(b"tail",),
            ),
            FakeResponse(headers={"content-length": "8"}, chunks=(b"new-file",)),
        ],
    )

    result = _download(
        url="https://example.test/x.zip",
        filename="x.zip",
        resume=True,
    )

    assert sent_headers == [
        {"Range": "bytes=4-", "If-Range": '"v1"'},
        None,
    ]
    assert result.read_bytes() == b"new-file"


def test_download_resume_206_restarts_when_response_validator_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    partial = tmp_path / "x.zip.part"
    partial.write_bytes(b"old-")
    _write_sidecar(partial, etag='"v1"', total=8)
    sent_headers = _install_fake_get(
        monkeypatch,
        [
            FakeResponse(
                status_code=206,
                headers={
                    "content-length": "4",
                    "content-range": "bytes 4-7/8",
                },
                chunks=(b"tail",),
            ),
            FakeResponse(headers={"content-length": "8"}, chunks=(b"new-file",)),
        ],
    )

    result = _download(
        url="https://example.test/x.zip",
        filename="x.zip",
        resume=True,
    )

    assert sent_headers == [
        {"Range": "bytes=4-", "If-Range": '"v1"'},
        None,
    ]
    assert result.read_bytes() == b"new-file"


def test_download_resume_content_range_mismatch_restarts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    partial = tmp_path / "x.zip.part"
    partial.write_bytes(b"abc")
    _write_sidecar(partial, etag='"v1"', total=10)
    sent_headers = _install_fake_get(
        monkeypatch,
        [
            FakeResponse(
                status_code=206,
                headers={"content-length": "10", "content-range": "bytes 0-9/10"},
                chunks=(b"full-fresh",),
            ),
            FakeResponse(headers={"content-length": "10"}, chunks=(b"full-fresh",)),
        ],
    )

    result = _download(
        url="https://example.test/x.zip",
        filename="x.zip",
        resume=True,
    )

    assert len(sent_headers) == 2
    assert sent_headers[1] is None
    assert result.read_bytes() == b"full-fresh"


def test_download_midstream_error_with_resume_preserves_partial_and_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    _install_fake_get(
        monkeypatch,
        [
            FakeResponse(
                headers={"content-length": "10", "etag": '"v2"'},
                chunks=(b"begin",),
                error=requests.ConnectionError("dropped"),
            ),
        ],
    )

    with pytest.raises(requests.ConnectionError):
        _download(
            url="https://example.test/x.zip",
            filename="x.zip",
            resume=True,
        )

    partial = tmp_path / "x.zip.part"
    assert partial.read_bytes() == b"begin"
    sidecar = json.loads(
        (tmp_path / "x.zip.part.meta").read_text(encoding="utf-8"),
    )
    assert sidecar["etag"] == '"v2"'
    assert sidecar["total"] == 10


def test_temporary_rename_path_skips_existing(tmp_path: Path) -> None:
    target = tmp_path / "LDRAW"
    (tmp_path / "LDRAW__pyldraw_tmp__").mkdir()

    candidate = _temporary_rename_path(target)

    assert candidate.name == "LDRAW__pyldraw_tmp_1__"


def test_case_safe_rename_changes_directory_case(tmp_path: Path) -> None:
    source = tmp_path / "LDRAW"
    source.mkdir()
    (source / "marker.txt").write_text("marker")

    result = _case_safe_rename(source, tmp_path / "ldraw")

    assert [child.name for child in tmp_path.iterdir()] == ["ldraw"]
    assert (result / "marker.txt").read_text() == "marker"


def test_normalize_tree_github_snapshot(tmp_path: Path) -> None:
    ldraw_dir = tmp_path / "ldraw-parts-2018-02" / "LDRAW"
    (ldraw_dir / "PARTS" / "S").mkdir(parents=True)
    (ldraw_dir / "PARTS" / "973.DAT").write_text("0 Minifig Torso")
    (ldraw_dir / "PARTS" / "S" / "973S01.DAT").write_text("0 ~Minifig Torso subpart")
    (ldraw_dir / "P").mkdir()
    (ldraw_dir / "PARTS.LST").write_text("parts")
    (ldraw_dir / "ldconfig.ldr").write_text("colours")

    _normalize_tree(tmp_path)

    assert not (tmp_path / "ldraw-parts-2018-02").exists()
    names = sorted(child.name for child in (tmp_path / "ldraw").iterdir())
    assert names == ["ldconfig.ldr", "p", "parts", "parts.lst"]
    parts_names = sorted(
        child.name for child in (tmp_path / "ldraw" / "parts").iterdir()
    )
    assert parts_names == ["973.dat", "s"]
    subpart_names = [
        child.name for child in (tmp_path / "ldraw" / "parts" / "s").iterdir()
    ]
    assert subpart_names == ["973s01.dat"]


def test_normalize_tree_complete_layout(tmp_path: Path) -> None:
    (tmp_path / "ldraw" / "parts").mkdir(parents=True)
    (tmp_path / "ldraw" / "LDConfig.ldr").write_text("colours")

    _normalize_tree(tmp_path)

    names = sorted(child.name for child in (tmp_path / "ldraw").iterdir())
    assert names == ["ldconfig.ldr", "parts"]


def test_normalize_tree_missing_destination(tmp_path: Path) -> None:
    _normalize_tree(tmp_path / "nonexistent")

    assert not (tmp_path / "nonexistent").exists()


@patch("ldraw.downloads.requests.get")
def test_download_timeout_is_set(
    get_mock: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    response = get_mock.return_value.__enter__.return_value
    response.iter_content.return_value = [b"zip-bytes"]

    _download(url="https://example.test/x.zip", filename="x.zip")

    assert get_mock.call_args.kwargs["timeout"] == 30


@patch("ldraw.downloads.requests.get")
def test_download_failure_cleans_up_part_file(
    get_mock: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    response = get_mock.return_value.__enter__.return_value
    response.iter_content.side_effect = requests.ConnectionError("dropped")

    with pytest.raises(requests.ConnectionError):
        _download(url="https://example.test/x.zip", filename="x.zip")

    assert not (tmp_path / "x.zip.part").exists()


@patch("ldraw.download_updates.requests.get")
def test_latest_release_id_preserves_dashed_id(get_mock: MagicMock) -> None:
    from ldraw.download_updates import TARGET_HREF, get_latest_release_id

    get_mock.return_value.text = (
        f'<html><body><a data-pan="update-complete-zip-2024-01" '
        f'href="{TARGET_HREF}">Download</a></body></html>'
    )

    assert get_latest_release_id() == "2024-01"
    assert get_mock.call_args.kwargs["timeout"] == 30


@patch("ldraw.download_updates.requests.get")
def test_latest_release_id_plain_numeric(get_mock: MagicMock) -> None:
    from ldraw.download_updates import TARGET_HREF, get_latest_release_id

    get_mock.return_value.text = (
        f'<html><body><a data-pan="update-complete-zip-2606" '
        f'href="{TARGET_HREF}">Download</a></body></html>'
    )

    assert get_latest_release_id() == "2606"


@patch("ldraw.download_updates.requests.get")
def test_latest_release_id_missing_anchor_raises(get_mock: MagicMock) -> None:
    from ldraw.download_updates import get_latest_release_id
    from ldraw.errors import CouldNotDetermineLatestVersionError

    get_mock.return_value.text = "<html><body>no anchors here</body></html>"

    with pytest.raises(CouldNotDetermineLatestVersionError):
        get_latest_release_id()


@patch("ldraw.download_updates.requests.get")
def test_latest_release_id_unparseable_pan_raises(get_mock: MagicMock) -> None:
    from ldraw.download_updates import TARGET_HREF, get_latest_release_id
    from ldraw.errors import CouldNotDetermineLatestVersionError

    get_mock.return_value.text = (
        f'<html><body><a data-pan="no-trailing-id-" '
        f'href="{TARGET_HREF}">Download</a></body></html>'
    )

    with pytest.raises(CouldNotDetermineLatestVersionError):
        get_latest_release_id()


def test_download_complete_discards_cached_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    stale = tmp_path / "complete.zip"
    stale.write_bytes(b"stale bytes")

    with (
        patch("ldraw.downloads.get_latest_release_id", return_value="2099-01"),
        patch("ldraw.downloads.generate_parts_lst"),
        patch("ldraw.downloads.unpack_version") as unpack_version_mock,
        patch("ldraw.downloads._download") as download_mock,
    ):
        unpack_version_mock.return_value = tmp_path / "complete"
        replacement = tmp_path / "replacement.zip"
        with zipfile.ZipFile(replacement, "w") as archive:
            archive.writestr("ldraw/parts.lst", "parts")
        download_mock.return_value = replacement
        download(show_progress=False)

    assert not stale.exists()
    download_mock.assert_called_once()


@patch("ldraw.downloads.generate_parts_lst")
@patch("ldraw.downloads.unpack_version")
@patch("ldraw.downloads._download")
def test_download_versioned_keeps_cached_zip(
    download_mock: MagicMock,
    unpack_version_mock: MagicMock,
    generate_parts_lst_mock: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    cached = tmp_path / "2018-02.zip"
    with zipfile.ZipFile(cached, "w") as archive:
        archive.writestr("ldraw/parts.lst", "parts")
    download_mock.return_value = cached

    download(show_progress=False, version="2018-02")

    assert cached.exists()


@patch("ldraw.downloads.generate_parts_lst")
@patch("ldraw.downloads.unpack_version")
@patch("ldraw.downloads._download")
def test_download_versioned_discards_corrupt_cached_zip(
    download_mock: MagicMock,
    unpack_version_mock: MagicMock,
    generate_parts_lst_mock: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    corrupt = tmp_path / "2018-02.zip"
    corrupt.write_bytes(b"definitely not a zip archive")
    replacement = tmp_path / "replacement.zip"

    def replacement_download(**_kwargs: object) -> Path:
        with zipfile.ZipFile(replacement, "w") as archive:
            archive.writestr("ldraw/parts.lst", "parts")
        return replacement

    download_mock.side_effect = replacement_download

    download(show_progress=False, version="2018-02")

    assert not corrupt.exists()
    download_mock.assert_called_once()


@patch("ldraw.downloads.generate_parts_lst")
@patch("ldraw.downloads.unpack_version")
@patch("ldraw.downloads._download")
def test_download_tolerates_concurrent_corrupt_cache_deletion(
    download_mock: MagicMock,
    unpack_version_mock: MagicMock,
    generate_parts_lst_mock: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    corrupt = tmp_path / "2018-02.zip"
    corrupt.write_bytes(b"definitely not a zip archive")
    replacement = tmp_path / "replacement.zip"

    def delete_corrupt_during_check(path: Path) -> ArchiveIntegrity:
        if path == corrupt:
            path.unlink()
            return ArchiveIntegrity(valid=False, error=zipfile.BadZipFile("corrupt"))
        return check_archive_integrity(path)

    def replacement_download(**_kwargs: object) -> Path:
        with zipfile.ZipFile(replacement, "w") as archive:
            archive.writestr("ldraw/parts.lst", "parts")
        return replacement

    monkeypatch.setattr(
        "ldraw.downloads.check_archive_integrity",
        delete_corrupt_during_check,
    )
    download_mock.side_effect = replacement_download

    download(show_progress=False, version="2018-02")

    download_mock.assert_called_once()
    unpack_version_mock.assert_called_once()


@patch("ldraw.downloads.generate_parts_lst")
@patch("ldraw.downloads.unpack_version")
@patch("ldraw.downloads._download")
def test_download_discards_corrupt_fresh_archive_before_unpacking(
    download_mock: MagicMock,
    unpack_version_mock: MagicMock,
    generate_parts_lst_mock: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    corrupt = tmp_path / "2018-02.zip"

    def redownload_corrupt(**_kwargs: object) -> Path:
        corrupt.write_bytes(b"definitely not a zip archive")
        return corrupt

    download_mock.side_effect = redownload_corrupt

    with pytest.raises(zipfile.BadZipFile, match="failed integrity check"):
        download(show_progress=False, version="2018-02")

    assert not corrupt.exists()
    unpack_version_mock.assert_not_called()


def test_unpack_version_discards_bad_zip_for_self_heal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path / "cache")
    version_zip = tmp_path / "2018-02.zip"
    version_zip.write_bytes(b"junk bytes, not a zip")

    with pytest.raises(zipfile.BadZipFile):
        unpack_version(
            version_zip=version_zip,
            version="2018-02",
            show_progress=False,
        )

    assert not version_zip.exists()


def test_normalize_tree_raises_on_case_collision(tmp_path: Path) -> None:
    ldraw_dir = tmp_path / "ldraw"
    parts_upper = ldraw_dir / "PARTS"
    parts_upper.mkdir(parents=True)
    (ldraw_dir / "Parts").mkdir(exist_ok=True)
    if len(list(ldraw_dir.iterdir())) < 2:
        pytest.skip("case-insensitive filesystem cannot host colliding names")

    with pytest.raises(ValueError, match="Case-colliding"):
        _normalize_tree(tmp_path)


def test_normalize_tree_rejects_wrapper_collision_before_mutation(
    tmp_path: Path,
) -> None:
    wrapper = tmp_path / "ldraw-parts-2099-01"
    upper = wrapper / "LDRAW"
    lower = wrapper / "ldraw"
    upper.mkdir(parents=True)
    try:
        lower.mkdir()
    except FileExistsError:
        pytest.skip("case-insensitive filesystem cannot host colliding names")
    if len(list(wrapper.iterdir())) < 2:
        pytest.skip("case-insensitive filesystem cannot host colliding names")
    (upper / "upper.dat").write_text("upper")
    (lower / "lower.dat").write_text("lower")

    with pytest.raises(ValueError, match="Case-colliding wrapper entries"):
        _normalize_tree(tmp_path)

    assert (upper / "upper.dat").read_text() == "upper"
    assert (lower / "lower.dat").read_text() == "lower"
    assert wrapper.is_dir()


def test_case_safe_rename_rolls_back_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "LDRAW"
    source.mkdir()
    original_rename = Path.rename
    calls = {"count": 0}

    def failing_second_rename(self: Path, target: Path) -> Path:
        calls["count"] += 1
        if calls["count"] == 2:
            message = "simulated failure"
            raise OSError(message)
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", failing_second_rename)

    with pytest.raises(OSError, match="simulated failure"):
        _case_safe_rename(source, tmp_path / "ldraw")

    entries = [child.name for child in tmp_path.iterdir()]
    assert entries == ["LDRAW"]


def test_normalize_tree_replaces_stale_tree_with_new_wrapper(tmp_path: Path) -> None:
    stale_parts = tmp_path / "ldraw" / "parts"
    stale_parts.mkdir(parents=True)
    (stale_parts / "old.dat").write_text("0 Old Part")
    fresh = tmp_path / "ldraw-parts-2099-01" / "LDRAW" / "PARTS"
    fresh.mkdir(parents=True)
    (fresh / "NEW.DAT").write_text("0 New Part")

    _normalize_tree(tmp_path)

    assert not (tmp_path / "ldraw-parts-2099-01").exists()
    assert (tmp_path / "ldraw" / "parts" / "new.dat").read_text() == "0 New Part"
    assert not (tmp_path / "ldraw" / "parts" / "old.dat").exists()


@patch("zipfile.ZipFile", spec=zipfile.ZipFile)
def test_unpack_version_show_progress_false_is_silent(
    zip_mock: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path / "cache")
    zip_mock.return_value.__enter__.return_value.infolist.return_value = []
    version_zip = tmp_path / "2018-02.zip"
    version_zip.write_bytes(b"zip")

    unpack_version(
        version_zip=version_zip,
        version="2018-02",
        show_progress=False,
    )

    assert capsys.readouterr().out == ""


def test_anchor_tag_parser_first_match_wins() -> None:
    from ldraw.download_updates import TARGET_HREF, AnchorTagParser

    parser = AnchorTagParser()
    parser.feed(
        f'<a data-pan="update-arch-zip-0001" href="https://other.test/x.zip">o</a>'
        f'<a data-pan="update-complete-zip-2024-01" href="{TARGET_HREF}">first</a>'
        f'<a data-pan="update-complete-zip-9999" href="{TARGET_HREF}">later</a>',
    )

    assert parser.found is True
    assert parser.data_pan_value == "update-complete-zip-2024-01"


def test_extract_data_pan_returns_none_without_anchor() -> None:
    from ldraw.download_updates import extract_data_pan_from_html

    assert extract_data_pan_from_html("<html></html>") is None


@patch("ldraw.download_updates.requests.get")
def test_latest_release_id_rejects_missing_segment_boundary(
    get_mock: MagicMock,
) -> None:
    from ldraw.download_updates import TARGET_HREF, get_latest_release_id
    from ldraw.errors import CouldNotDetermineLatestVersionError

    get_mock.return_value.text = (
        f'<a data-pan="update-complete-zipfoo2024-01" '
        f'href="{TARGET_HREF}">malformed</a>'
    )

    with pytest.raises(CouldNotDetermineLatestVersionError):
        get_latest_release_id()
