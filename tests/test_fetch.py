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
