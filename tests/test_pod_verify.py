"""Tests for the pure-stdlib on-pod sha256 verifier.

This test imports ONLY ``pod/verify_hashes.py`` -- the sole on-pod module the
suite is allowed to touch -- by inserting the ``pod/`` directory on ``sys.path``.
It must NOT import torch / transformers / huggingface_hub, and the heavy
``pod/gpu_*_pipeline.py`` drivers must stay out of the import path entirely.
"""

from __future__ import annotations

import hashlib
import importlib
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POD_DIR = os.path.join(REPO_ROOT, "pod")
if POD_DIR not in sys.path:
    sys.path.insert(0, POD_DIR)

verify_hashes = importlib.import_module("verify_hashes")


def _write(path: str, content: bytes) -> str:
    with open(path, "wb") as handle:
        handle.write(content)
    return path


def test_module_is_pure_stdlib():
    """The heavy deps must never get pulled in by importing the verifier."""
    for banned in ("torch", "transformers", "huggingface_hub"):
        assert banned not in sys.modules


def test_sha256_file_known_content(tmp_path):
    content = b"gpu-overwatch teacher queue\n"
    path = _write(os.path.join(str(tmp_path), "blob.bin"), content)
    expected = hashlib.sha256(content).hexdigest()
    assert verify_hashes.sha256_file(path) == expected


def test_verify_digests_ok_and_mismatch(tmp_path):
    content = b"weights-shard-bytes"
    good = hashlib.sha256(content).hexdigest()
    _write(os.path.join(str(tmp_path), "shard-ok.bin"), content)
    _write(os.path.join(str(tmp_path), "shard-bad.bin"), b"other-bytes")

    expected = {"shard-ok.bin": good, "shard-bad.bin": good}
    results = dict((name, (ok, actual)) for name, ok, actual in
                   verify_hashes.verify_digests(expected, str(tmp_path)))

    assert results["shard-ok.bin"][0] is True
    assert results["shard-ok.bin"][1] == good
    assert results["shard-bad.bin"][0] is False
    assert results["shard-bad.bin"][1] != good


def test_verify_digests_missing_file_is_not_ok(tmp_path):
    expected = {"absent.safetensors": "0" * 64}
    results = verify_hashes.verify_digests(expected, str(tmp_path))
    assert results == [("absent.safetensors", False, "")]


def test_verify_returns_true_on_full_match(tmp_path):
    content = b"all-good"
    digest = hashlib.sha256(content).hexdigest()
    _write(os.path.join(str(tmp_path), "f.bin"), content)
    assert verify_hashes.verify(str(tmp_path), {"f.bin": digest}) is True


def test_hard_abort_mismatch_is_never_success(tmp_path):
    """A mismatch must yield False from verify() and nonzero from main()."""
    _write(os.path.join(str(tmp_path), "f.bin"), b"corrupted")
    expected = {"f.bin": hashlib.sha256(b"original").hexdigest()}

    assert verify_hashes.verify(str(tmp_path), expected) is False

    # Write the expected map to a JSON the CLI can load, then exercise main().
    import json

    digest_json = os.path.join(str(tmp_path), "digests.json")
    with open(digest_json, "w", encoding="utf-8") as handle:
        json.dump(expected, handle)

    rc = verify_hashes.main(["--base-dir", str(tmp_path), "--digests", digest_json])
    assert rc != 0


def test_main_zero_on_match(tmp_path):
    import json

    content = b"matches"
    digest = hashlib.sha256(content).hexdigest()
    _write(os.path.join(str(tmp_path), "g.bin"), content)
    digest_json = os.path.join(str(tmp_path), "digests.json")
    with open(digest_json, "w", encoding="utf-8") as handle:
        json.dump({"g.bin": digest}, handle)

    assert verify_hashes.main(["--base-dir", str(tmp_path), "--digests", digest_json]) == 0


def test_main_exits_nonzero_via_systemexit(tmp_path):
    """main() returns a code; wiring it through sys.exit stays nonzero."""
    _write(os.path.join(str(tmp_path), "h.bin"), b"bad")
    import json

    digest_json = os.path.join(str(tmp_path), "digests.json")
    with open(digest_json, "w", encoding="utf-8") as handle:
        json.dump({"h.bin": "f" * 64}, handle)

    with pytest.raises(SystemExit) as excinfo:
        sys.exit(verify_hashes.main(["--base-dir", str(tmp_path), "--digests", digest_json]))
    assert excinfo.value.code != 0


def test_builtin_expected_digests_loadable():
    """The pinned two-shard map must be present and look like sha256 hex."""
    expected = verify_hashes.load_expected_digests()
    assert "model-00001-of-00002.safetensors" in expected
    assert "model-00002-of-00002.safetensors" in expected
    for digest in expected.values():
        assert len(digest) == 64
        int(digest, 16)  # valid hex
