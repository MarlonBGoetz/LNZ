#!/usr/bin/env python3
"""Pure-stdlib sha256 verifier for the downloaded Llama-3.2-3B weights.

This is the ONLY on-pod pipeline module that the gpu-overwatch test suite is
allowed to import. It deliberately uses nothing beyond the standard library
(``hashlib``/``os``/``sys``/``json``/``argparse``) so it imports cleanly in the
offline sandbox -- no ``torch``, ``transformers`` or ``huggingface_hub``.

On the Pod it is the HARD-STOP gate between the model download and the TRIBE
teacher queue: ``main()`` exits NONZERO if any safetensors shard's sha256 does
not match the pinned expected digest, so a corrupted / substituted download can
never flow into the teacher traces.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Dict, List, Tuple

# The two pinned digests for unsloth/Llama-3.2-3B at revision
# d4446454d87d51aa42e1fb174f25acc5f8762331. These are duplicated in the sibling
# ``expected_digests.json`` (loaded when present) so the values live in exactly
# one obvious place for the orchestrator to audit, with a hardcoded fallback so
# the module still works if the JSON is not shipped alongside it.
EXPECTED_DIGESTS: Dict[str, str] = {
    "model-00001-of-00002.safetensors": "584d8d3e3f82f7964955174dfe5e3b1cf117a9d859f022cfdf7fcb884856e002",
    "model-00002-of-00002.safetensors": "4719a04514ec2f060240711b7c33ab21187cac730ecaba3040b7a0fd95a9cefb",
}

_SIBLING_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "expected_digests.json")

# Read in 1 MiB blocks so hashing a multi-GB shard never loads it into memory.
_CHUNK = 1024 * 1024


def load_expected_digests(path: str = _SIBLING_JSON) -> Dict[str, str]:
    """Return the expected {filename: sha256} map.

    Loads the sibling ``expected_digests.json`` when it exists, otherwise falls
    back to the hardcoded :data:`EXPECTED_DIGESTS`. Digests are normalised to
    lowercase hex.
    """
    expected = dict(EXPECTED_DIGESTS)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            expected = {str(k): str(v) for k, v in data.items()}
    except (OSError, ValueError):
        # Missing or malformed JSON -> keep the hardcoded fallback.
        pass
    return {name: digest.strip().lower() for name, digest in expected.items()}


def sha256_file(path: str) -> str:
    """Return the lowercase hex sha256 of the file at ``path`` (streamed)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_digests(expected: Dict[str, str], base_dir: str) -> List[Tuple[str, bool, str]]:
    """Verify every expected file under ``base_dir``.

    Returns a list of ``(name, ok, actual)`` tuples. ``ok`` is False for a
    mismatch AND for a missing file (``actual`` is then the empty string), so a
    missing shard is never silently treated as a pass.
    """
    results: List[Tuple[str, bool, str]] = []
    for name, want in expected.items():
        path = os.path.join(base_dir, name)
        if not os.path.isfile(path):
            results.append((name, False, ""))
            continue
        actual = sha256_file(path)
        results.append((name, actual == want.strip().lower(), actual))
    return results


def verify(base_dir: str, expected: Dict[str, str] | None = None) -> bool:
    """Return True only if EVERY expected file matches; print a report.

    This is the programmatic hard-abort entrypoint: a single mismatch or missing
    file yields False and is never reported as success.
    """
    expected = expected if expected is not None else load_expected_digests()
    results = verify_digests(expected, base_dir)
    all_ok = True
    for name, ok, actual in results:
        if ok:
            print(f"[verify_hashes] OK    {name}  sha256={actual}")
        else:
            all_ok = False
            shown = actual if actual else "<missing>"
            want = expected.get(name, "<unknown>")
            print(
                f"[verify_hashes] FAIL  {name}  expected={want}  actual={shown}",
                file=sys.stderr,
            )
    if all_ok:
        print(f"[verify_hashes] all {len(results)} digest(s) verified under {base_dir}")
    else:
        print(
            "[verify_hashes] DIGEST MISMATCH -- aborting; downloaded weights do "
            "NOT match the pinned sha256. Do NOT continue the teacher run.",
            file=sys.stderr,
        )
    return all_ok


def main(argv: List[str] | None = None) -> int:
    """CLI entrypoint. Exits NONZERO (hard abort) on any mismatch/missing file."""
    parser = argparse.ArgumentParser(
        description="Verify Llama-3.2-3B safetensors against pinned sha256 digests."
    )
    parser.add_argument(
        "--base-dir",
        required=True,
        help="Directory holding the downloaded safetensors shards.",
    )
    parser.add_argument(
        "--digests",
        default=_SIBLING_JSON,
        help="Optional path to a {filename: sha256} JSON (defaults to the sibling file).",
    )
    args = parser.parse_args(argv)
    expected = load_expected_digests(args.digests)
    return 0 if verify(args.base_dir, expected) else 1


if __name__ == "__main__":
    sys.exit(main())
