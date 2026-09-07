"""Tests for the source manifest and checksum verification.

These never touch the network: they exercise manifest parsing and hashing on
temporary files.
"""

from __future__ import annotations

import pytest

from wildfires.fetch import load_manifest, sha256_of, verify


class TestManifest:
    def test_every_source_has_target_and_checksum(self):
        for source in load_manifest():
            assert source.target is not None, f"{source.name} has no target"
            assert len(source.sha256) == 64, f"{source.name} has a malformed sha256"
            assert source.bytes > 0, f"{source.name} has no size"

    def test_every_source_has_a_route(self):
        for source in load_manifest():
            if source.kind == "http":
                assert source.url, f"{source.name} is http but has no url"
            elif source.kind == "gdrive":
                assert source.file_id, f"{source.name} is gdrive but has no file_id"
            elif source.kind == "manual":
                assert source.instructions, f"{source.name} is manual but has no instructions"
            else:
                pytest.fail(f"{source.name} has unknown kind {source.kind!r}")

    def test_names_are_unique(self):
        names = [s.name for s in load_manifest()]
        assert len(names) == len(set(names))

    def test_targets_are_unique(self):
        targets = [s.target for s in load_manifest()]
        assert len(targets) == len(set(targets))


class TestSha256:
    def test_matches_known_digest(self, tmp_path):
        # sha256 of the empty string, the standard test vector.
        path = tmp_path / "empty"
        path.write_bytes(b"")
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert sha256_of(path) == expected


class TestVerify:
    def _source(self, tmp_path, payload, digest):
        from wildfires.fetch import Source

        target = tmp_path / "f.bin"
        if payload is not None:
            target.write_bytes(payload)
        return Source(name="t", kind="http", target=target, sha256=digest,
                      bytes=len(payload or b""), url="http://x", file_id=None,
                      instructions=None, unzip_member=None)

    def test_missing_file(self, tmp_path):
        assert verify(self._source(tmp_path, None, "0" * 64)) == "missing"

    def test_matching_file_is_ok(self, tmp_path):
        payload = b"hello"
        digest = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        assert verify(self._source(tmp_path, payload, digest)) == "ok"

    def test_wrong_content_is_corrupt(self, tmp_path):
        """A truncated download must fail loudly, not produce a broken panel."""
        assert verify(self._source(tmp_path, b"hello", "0" * 64)) == "corrupt"


INTERSTITIAL = (
    '<!DOCTYPE html><html><head><title>Google Drive - Virus scan warning</title>'
    '</head><body><form action="https://drive.usercontent.google.com/download" '
    'method="get"><input type="hidden" name="id" value="ABC123">'
    '<input type="hidden" name="export" value="download">'
    '<input type="hidden" name="confirm" value="t">'
    '<input type="hidden" name="uuid" value="40f24b61-a56c-465f-b969-2690b12295c2">'
    '</form></body></html>'
)


class TestDriveConfirm:
    def test_extracts_every_form_field(self):
        from wildfires.fetch import parse_drive_confirm

        fields = parse_drive_confirm(INTERSTITIAL)
        assert fields["id"] == "ABC123"
        assert fields["confirm"] == "t"
        assert fields["uuid"] == "40f24b61-a56c-465f-b969-2690b12295c2"
        assert fields["export"] == "download"

    def test_binary_payload_is_not_mistaken_for_an_interstitial(self):
        """Shapefile bytes start 0000270a and must not parse as a confirm page."""
        from wildfires.fetch import parse_drive_confirm

        assert parse_drive_confirm("\x00\x00\x27\x0a binary junk") == {}

    def test_plain_html_without_a_form_yields_nothing(self):
        from wildfires.fetch import parse_drive_confirm

        assert parse_drive_confirm("<html><body>not a form</body></html>") == {}


class _FakeResponse:
    """Just enough of requests.Response to drive _stream_to / _download_http.

    `chunks` may contain an Exception instance instead of bytes, which
    iter_content raises mid-stream — simulating a dropped connection without
    touching the network.
    """

    def __init__(self, chunks, headers=None):
        self._chunks = chunks
        self.headers = headers or {}

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        for chunk in self._chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class TestStreamToCleansUpOnFailure:
    """Covers the temp-file leak fixed after code review: any exception during
    streaming — not only a checksum mismatch — must remove the temp file and
    leave the destination directory exactly as it was.
    """

    def test_mid_stream_exception_leaves_no_orphan_and_untouched_destination(self, tmp_path):
        from wildfires.fetch import _stream_to

        destination = tmp_path / "out.bin"
        response = _FakeResponse([b"partial-bytes", ConnectionError("dropped")])

        with pytest.raises(ConnectionError):
            _stream_to(response, destination, "0" * 64)

        assert not destination.exists()
        assert list(tmp_path.iterdir()) == []

    def test_successful_stream_lands_with_readable_permissions(self, tmp_path):
        """NamedTemporaryFile defaults to 0600; the renamed file must not."""
        from wildfires.fetch import _stream_to

        payload = b"hello"
        digest = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        destination = tmp_path / "out.bin"
        response = _FakeResponse([payload])

        _stream_to(response, destination, digest)

        assert destination.read_bytes() == payload
        assert destination.stat().st_mode & 0o777 == 0o644


class TestDownloadHandlesCorruptZip:
    """Covers the second review finding: a truncated/corrupt zip must surface
    as download() returning 'failed', not as an unhandled zipfile.BadZipFile
    crashing the whole fetch run.
    """

    def _gadm_like_source(self, tmp_path):
        from wildfires.fetch import Source

        return Source(
            name="gadm_level2",
            kind="http",
            target=tmp_path / "gadm41_PRT_2.json",
            sha256="0" * 64,
            bytes=10,
            url="http://example.invalid/gadm.zip",
            file_id=None,
            instructions=None,
            unzip_member="gadm41_PRT_2.json",
        )

    def test_corrupt_zip_returns_failed_and_leaves_no_debris(self, tmp_path, monkeypatch):
        from wildfires.fetch import download

        source = self._gadm_like_source(tmp_path)
        fake_response = _FakeResponse([b"this is not a zip file"])
        monkeypatch.setattr(
            "wildfires.fetch.requests.get", lambda *a, **k: fake_response
        )

        result = download(source)

        assert result == "failed"
        assert not source.target.exists()
        assert list(tmp_path.iterdir()) == []

    def test_missing_member_returns_failed(self, tmp_path, monkeypatch):
        """The archive is valid but doesn't contain the manifest's named member."""
        import io
        import zipfile

        from wildfires.fetch import download

        source = self._gadm_like_source(tmp_path)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("some_other_file.json", "{}")
        fake_response = _FakeResponse([buffer.getvalue()])
        monkeypatch.setattr(
            "wildfires.fetch.requests.get", lambda *a, **k: fake_response
        )

        result = download(source)

        assert result == "failed"
        assert not source.target.exists()
        assert list(tmp_path.iterdir()) == []
