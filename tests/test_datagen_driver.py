"""Tests for the datagen driver (offline, fake inference backend).

All tests force the fake inference backend via OVERWATCH_FAKE=1 and write shards
under a tmp output dir. No network, no GPU, no third-party packages.
"""

from __future__ import annotations

import json
import os

import pytest

from overwatch.datagen import driver


@pytest.fixture(autouse=True)
def fake_env(monkeypatch):
    monkeypatch.setenv("OVERWATCH_FAKE", "1")


def _write_prompts(path, n):
    with open(path, "w", encoding="utf-8") as handle:
        for i in range(n):
            handle.write(json.dumps({"id": i, "input": f"text {i}"}) + "\n")


def _spec(tmp_path, input_path, output_dir, **over):
    spec = {
        "name": "t",
        "mode": "serverless",
        "model": "m",
        "input": input_path,
        "output": output_dir,
        "template": None,
        "sampling": {"temperature": 0.7, "max_tokens": 16},
        "concurrency": 1,
    }
    spec.update(over)
    return spec


def _read_shard(output_dir, name):
    rows = []
    with open(os.path.join(output_dir, name), "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


# ----------------------------------------------------------------------
# idempotent key
# ----------------------------------------------------------------------
def test_record_key_is_stable_and_keyed_on_fields():
    k1 = driver.record_key({"input": "x"}, "m", "t.jinja", {"temperature": 0.7})
    k2 = driver.record_key({"input": "x"}, "m", "t.jinja", {"temperature": 0.7})
    assert k1 == k2
    # Changing any keyed field changes the key.
    assert k1 != driver.record_key({"input": "x"}, "m2", "t.jinja", {"temperature": 0.7})
    assert k1 != driver.record_key({"input": "x"}, "m", "t.jinja", {"temperature": 0.8})
    assert k1 != driver.record_key({"input": "y"}, "m", "t.jinja", {"temperature": 0.7})


# ----------------------------------------------------------------------
# atomic shards + manifest
# ----------------------------------------------------------------------
def test_shards_written_atomically_and_listed_in_manifest(tmp_path):
    inp = os.path.join(str(tmp_path), "prompts.jsonl")
    out = os.path.join(str(tmp_path), "out")
    _write_prompts(inp, 5)
    spec = _spec(tmp_path, inp, out, shard_size=2)
    report = driver.run_driver(spec, base_dir=str(tmp_path), output_dir=out, shard_size=2)

    assert report["records"] == 5
    manifest = driver.load_manifest(out)
    # 5 records / shard_size 2 -> 3 shards (2, 2, 1).
    assert manifest["shards"] == report["shards"]
    assert len(manifest["shards"]) == 3
    assert manifest["records"] == 5
    # No temp files left behind (atomic rename).
    leftovers = [f for f in os.listdir(out) if f.startswith(".shard-") or f.startswith(".manifest-")]
    assert leftovers == []
    # Every listed shard is a readable JSONL with the right total.
    total = sum(len(_read_shard(out, name)) for name in manifest["shards"])
    assert total == 5


# ----------------------------------------------------------------------
# idempotent resume
# ----------------------------------------------------------------------
def test_resume_skips_already_done_keys(tmp_path):
    inp = os.path.join(str(tmp_path), "prompts.jsonl")
    out = os.path.join(str(tmp_path), "out")
    _write_prompts(inp, 4)
    spec = _spec(tmp_path, inp, out, shard_size=2)

    first = driver.run_driver(spec, base_dir=str(tmp_path), output_dir=out, shard_size=2)
    assert first["records"] == 4

    # Re-run the same spec: nothing new is produced, manifest unchanged.
    second = driver.run_driver(spec, base_dir=str(tmp_path), output_dir=out, shard_size=2)
    assert second["new_records"] == 0
    assert second["records"] == 4
    assert second["shards_written"] == []


# ----------------------------------------------------------------------
# exact dedup
# ----------------------------------------------------------------------
def test_exact_dedup_by_key(tmp_path):
    inp = os.path.join(str(tmp_path), "prompts.jsonl")
    out = os.path.join(str(tmp_path), "out")
    with open(inp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"id": 1, "input": "same"}) + "\n")
        handle.write(json.dumps({"id": 1, "input": "same"}) + "\n")  # exact duplicate
        handle.write(json.dumps({"id": 2, "input": "other"}) + "\n")
    spec = _spec(tmp_path, inp, out, shard_size=10)
    report = driver.run_driver(spec, base_dir=str(tmp_path), output_dir=out, shard_size=10)
    assert report["deduped"] == 1
    assert report["records"] == 2
    manifest = driver.load_manifest(out)
    assert len(manifest["keys"]) == len(set(manifest["keys"])) == 2


# ----------------------------------------------------------------------
# retries + poison queue
# ----------------------------------------------------------------------
def test_record_failing_three_times_goes_to_failed_jsonl(tmp_path):
    inp = os.path.join(str(tmp_path), "prompts.jsonl")
    out = os.path.join(str(tmp_path), "out")
    _write_prompts(inp, 3)
    spec = _spec(tmp_path, inp, out, shard_size=10)

    # Compute the key of record id=1 and force it to always fail.
    bad_record = {"id": 1, "input": "text 1"}
    bad_key = driver.record_key(bad_record, "m", "", spec["sampling"])
    fake = driver.FakeInference(fail_keys={bad_key: 99})

    sleeps = []
    report = driver.run_driver(
        spec,
        base_dir=str(tmp_path),
        output_dir=out,
        inference=fake,
        shard_size=10,
        max_retries=3,
        base_backoff=1.0,
        sleeper=sleeps.append,
    )
    assert report["failed"] == 1
    assert report["records"] == 2  # the other two succeeded
    # The poison queue holds the failed record's key.
    failed_keys = driver.load_failed_keys(out)
    assert bad_key in failed_keys
    # Exponential backoff: with max_retries=3, two sleeps 1.0 then 2.0.
    assert sleeps == [1.0, 2.0]

    # Resume does not retry a key already in failed.jsonl.
    report2 = driver.run_driver(spec, base_dir=str(tmp_path), output_dir=out, shard_size=10)
    assert report2["new_records"] == 0


def test_transient_then_success_is_retried(tmp_path):
    inp = os.path.join(str(tmp_path), "prompts.jsonl")
    out = os.path.join(str(tmp_path), "out")
    _write_prompts(inp, 1)
    spec = _spec(tmp_path, inp, out, shard_size=10)
    rec = {"id": 0, "input": "text 0"}
    key = driver.record_key(rec, "m", "", spec["sampling"])
    fake = driver.FakeInference(fail_keys={key: 1})  # fail once, then succeed
    report = driver.run_driver(
        spec, base_dir=str(tmp_path), output_dir=out, inference=fake,
        shard_size=10, max_retries=3, base_backoff=0.0,
    )
    assert report["failed"] == 0
    assert report["records"] == 1
    assert report["retries"] == 1


# ----------------------------------------------------------------------
# QA sampling + pause
# ----------------------------------------------------------------------
def test_qa_fires_at_interval_and_pauses_on_bad_threshold(tmp_path):
    inp = os.path.join(str(tmp_path), "prompts.jsonl")
    out = os.path.join(str(tmp_path), "out")
    _write_prompts(inp, 4)
    spec = _spec(tmp_path, inp, out, shard_size=10)
    spec["qa"] = {"every_records": 2, "sample_size": 2, "rubric": "r.md"}

    # Make both records in the first QA window bad -> pause.
    r0 = {"id": 0, "input": "text 0"}
    r1 = {"id": 1, "input": "text 1"}
    k0 = driver.record_key(r0, "m", "", spec["sampling"])
    k1 = driver.record_key(r1, "m", "", spec["sampling"])
    fake = driver.FakeInference(bad_keys={k0: "empty", k1: "refusal"})

    report = driver.run_driver(
        spec, base_dir=str(tmp_path), output_dir=out, inference=fake,
        shard_size=10, qa_bad_fraction=0.5,
    )
    assert report["qa_status"] == "paused"
    assert report["paused"] is True
    assert report["qa_reports"]
    first_report = report["qa_reports"][0]
    assert first_report["crossed"] is True
    assert first_report["bad"] == 2


def test_qa_passes_when_outputs_are_good(tmp_path):
    inp = os.path.join(str(tmp_path), "prompts.jsonl")
    out = os.path.join(str(tmp_path), "out")
    _write_prompts(inp, 4)
    spec = _spec(tmp_path, inp, out, shard_size=10)
    spec["qa"] = {"every_records": 2, "sample_size": 2, "rubric": "r.md"}
    report = driver.run_driver(
        spec, base_dir=str(tmp_path), output_dir=out, shard_size=10, qa_bad_fraction=0.5,
    )
    assert report["qa_status"] == "ok"
    assert report["paused"] is False
    assert len(report["qa_reports"]) == 2  # 4 records / every 2


# ----------------------------------------------------------------------
# grading helper
# ----------------------------------------------------------------------
def test_grade_output():
    assert driver.grade_output("label:abcd1234") == "ok"
    assert driver.grade_output("") == "empty"
    assert driver.grade_output("   ") == "empty"
    assert driver.grade_output("I cannot help with that.") == "refusal"
    assert driver.grade_output("<<<not-json>>>") == "format"
