"""HTTP behavior of the local OMR corpus downloader."""

from pathlib import Path

import httpx2
import pytest

from scripts.fetch_omr_corpus import fetch_model, main


def test_fetch_model_streams_redirected_content_and_closes_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses: list[httpx2.Response] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        assert request.extensions["timeout"] == dict.fromkeys(
            ("connect", "read", "write", "pool"), 60
        )
        response = (
            httpx2.Response(status_code=302, headers={"location": "/model.mpd"})
            if request.url.path == "/old.mpd"
            else httpx2.Response(
                status_code=200,
                stream=httpx2.ByteStream(b"0 FILE model.mpd\n0 Test model\n"),
            )
        )
        responses.append(response)
        return response

    with httpx2.Client(transport=httpx2.MockTransport(handler=handle)) as client:
        monkeypatch.setattr("scripts.fetch_omr_corpus.httpx2.stream", client.stream)
        assert (
            fetch_model(
                name="model.mpd",
                url="https://example.test/old.mpd",
                dest=tmp_path,
                force=False,
            )
            == "downloaded"
        )

    assert (tmp_path / "model.mpd").read_bytes() == b"0 FILE model.mpd\n0 Test model\n"
    assert not (tmp_path / "model.mpd.part").exists()
    assert len(responses) == 2
    assert all(response.is_closed for response in responses)


@pytest.mark.parametrize("error_type", [httpx2.ConnectError, httpx2.ReadTimeout])
def test_corpus_main_records_http_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[httpx2.HTTPError],
) -> None:
    def stream(**_kwargs: object) -> None:
        raise error_type("offline")

    monkeypatch.setattr("scripts.fetch_omr_corpus.httpx2.stream", stream)
    assert main(["--dest", str(tmp_path)]) == 1
    assert "FAILED: offline" in (tmp_path / "manifest.txt").read_text()
