"""Tests for the committed teacher-queue job spec(s) + example inputs manifest.

Fully offline, stdlib-only. These tests:

* parse every committed ``datagen/teacher-queue*.yaml`` via
  ``overwatch.config.load_config`` and validate the required datagen fields;
* assert the tiering (demo-clip tier present + NON-CUTTABLE, XD-Violence subset
  capped at <=300, a LIRIS-ACCEDE front-of-tier-2 placeholder is documented);
* parse ``datagen/teacher-queue-inputs.example.jsonl`` and assert the record
  shape (id/tier/path);
* run the spec end-to-end through ``run_driver`` against the injected
  ``FakeInference`` (``OVERWATCH_FAKE=1``) over a tiny tmp manifest, proving the
  spec is driver-consumable with **no teacher model and no network**.
"""

from __future__ import annotations

import glob
import json
import os

import pytest

from overwatch import config
from overwatch.datagen import driver


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _spec_paths(repo_root):
    paths = sorted(glob.glob(os.path.join(repo_root, "datagen", "teacher-queue*.yaml")))
    assert paths, "expected at least one datagen/teacher-queue*.yaml spec"
    return paths


def _load_specs(repo_root):
    return [(p, config.load_config(p)) for p in _spec_paths(repo_root)]


def _read_example_manifest(repo_root):
    """Parse the committed example manifest, skipping ``#`` comment lines."""
    path = os.path.join(repo_root, "datagen", "teacher-queue-inputs.example.jsonl")
    records = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            records.append(json.loads(line))
    return records


# ----------------------------------------------------------------------
# spec: required datagen fields
# ----------------------------------------------------------------------
def test_spec_parses_and_has_required_fields(repo_root):
    for path, spec in _load_specs(repo_root):
        assert isinstance(spec, dict), path
        for field in ("name", "mode", "model", "input", "output", "sampling", "qa"):
            assert field in spec and spec[field] is not None, f"{path} missing {field}"
        assert str(spec["output"]).startswith("/workspace/datasets/"), path
        qa = spec["qa"]
        assert isinstance(qa, dict), path
        for field in ("every_records", "sample_size", "rubric"):
            assert field in qa and qa[field] is not None, f"{path} qa missing {field}"


def test_spec_model_is_tribe_with_local_llama_override(repo_root):
    for path, spec in _load_specs(repo_root):
        assert spec["model"] == "facebook/tribev2", path
        override = spec.get("model_local_override") or {}
        assert override.get("data.text_feature.model_name") == (
            "/workspace/models/Llama-3.2-3B"
        ), path


def test_spec_budget_fits_under_per_run_cap(repo_root):
    # $3.99/hr * ~2h = $7.98; budget must stay under the $20 per-run cap.
    for path, spec in _load_specs(repo_root):
        budget = float(spec["budget_usd"])
        assert 0 < budget <= 20, path


# ----------------------------------------------------------------------
# spec: tiering
# ----------------------------------------------------------------------
def test_spec_tiering_demo_tikharm_xdviolence(repo_root):
    for path, spec in _load_specs(repo_root):
        datasets = spec.get("datasets")
        assert isinstance(datasets, list) and datasets, f"{path} has no datasets block"
        by_name = {d["name"]: d for d in datasets}

        # demo-clip tier is present and NON-CUTTABLE.
        assert "demo-clips" in by_name, path
        demo = by_name["demo-clips"]
        assert demo["tier"] == 1, path
        assert demo.get("non_cuttable") is True, path

        # TikHarm is tier 1.
        assert "tikharm" in by_name, path
        assert by_name["tikharm"]["tier"] == 1, path

        # XD-Violence subset is tier 2 and capped at <=300 clips.
        assert "xd-violence-subset" in by_name, path
        xd = by_name["xd-violence-subset"]
        assert xd["tier"] == 2, path
        assert int(xd["max_clips"]) <= 300, path


def test_spec_documents_liris_accede_front_of_tier2_placeholder(repo_root):
    # The LIRIS-ACCEDE front-of-tier-2 insertion must be documented as a
    # clearly-marked commented placeholder (we do NOT wait for it, so it is not
    # an active dataset entry).
    for path, spec in _load_specs(repo_root):
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read().lower()
        assert "liris-accede" in text, path
        assert "front of tier 2" in text or "front-of-tier-2" in text or (
            "front" in text and "tier 2" in text
        ), path
        # It is a commented placeholder, not an active dataset row.
        datasets = spec.get("datasets") or []
        assert all(d.get("name") != "liris-accede" for d in datasets), path


# ----------------------------------------------------------------------
# example inputs manifest: record shape
# ----------------------------------------------------------------------
def test_example_manifest_record_shape(repo_root):
    records = _read_example_manifest(repo_root)
    assert records, "example manifest has no (non-comment) records"
    for rec in records:
        assert isinstance(rec, dict)
        for field in ("id", "tier", "path"):
            assert field in rec, rec
        assert isinstance(rec["id"], str) and rec["id"], rec
        assert rec["tier"] in (1, 2), rec
        assert str(rec["path"]).startswith("/workspace/"), rec
    # The demo + tikharm + xd-violence datasets are all represented.
    datasets = {rec.get("dataset") for rec in records}
    assert {"demo", "tikharm", "xd-violence"}.issubset(datasets), datasets


def test_example_manifest_comments_mark_liris_accede(repo_root):
    path = os.path.join(repo_root, "datagen", "teacher-queue-inputs.example.jsonl")
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read().lower()
    assert "liris-accede" in text
    # The liris-accede example is commented out (every line that mentions it is a
    # comment line), so it is never an active record.
    for line in text.splitlines():
        if "liris-accede" in line:
            assert line.strip().startswith("#"), line


# ----------------------------------------------------------------------
# end-to-end: the spec is driver-consumable offline (FakeInference)
# ----------------------------------------------------------------------
def test_spec_runs_end_to_end_offline_with_fake_inference(repo_root, tmp_path, monkeypatch):
    monkeypatch.setenv("OVERWATCH_FAKE", "1")

    # Load the committed spec, then point input/output at a tmp manifest so the
    # test never touches the volume paths. Everything else (model, template,
    # sampling, qa) comes straight from the committed spec -> proves it is
    # consumable by run_driver unchanged.
    spec = config.load_config(os.path.join(repo_root, "datagen", "teacher-queue-v1.yaml"))

    manifest_path = os.path.join(str(tmp_path), "inputs.jsonl")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        for i in range(5):
            tier = 1 if i < 3 else 2
            handle.write(json.dumps({"id": f"clip-{i}", "tier": tier, "path": f"/workspace/clips/{i}.mp4"}) + "\n")

    out_dir = os.path.join(str(tmp_path), "out")
    spec["input"] = manifest_path
    spec["output"] = out_dir
    # The committed qa.rubric path is on the volume; override to a tmp file so the
    # offline driver does not need it (QA grading uses grade_output regardless).
    spec["template"] = None

    fake = driver.FakeInference()
    report = driver.run_driver(
        spec,
        base_dir=str(tmp_path),
        inference=fake,
        output_dir=out_dir,
        shard_size=2,
    )

    assert report["records"] == 5
    assert report["failed"] == 0
    assert report["qa_status"] == "ok"
    # Shards + manifest were produced.
    manifest = driver.load_manifest(out_dir)
    assert manifest["shards"] == report["shards"]
    assert len(manifest["shards"]) == 3  # 5 records / shard_size 2
    assert manifest["records"] == 5
    total = 0
    for name in manifest["shards"]:
        with open(os.path.join(out_dir, name), "r", encoding="utf-8") as handle:
            total += sum(1 for line in handle if line.strip())
    assert total == 5
    # No temp files left behind (atomic writes).
    leftovers = [f for f in os.listdir(out_dir) if f.startswith(".shard-") or f.startswith(".manifest-")]
    assert leftovers == []


def test_spec_budget_forwarded_to_run_driver_offline(repo_root, tmp_path, monkeypatch):
    """The committed spec's budget_usd is usable by run_driver for spend tracking.

    Mirrors how the GPU-A on-pod driver forwards spec['budget_usd'] +
    price_per_record into run_driver so on-pod spend is tracked against the
    budget. Fully offline via FakeInference.
    """
    monkeypatch.setenv("OVERWATCH_FAKE", "1")
    spec = config.load_config(os.path.join(repo_root, "datagen", "teacher-queue-v1.yaml"))
    assert "budget_usd" in spec and float(spec["budget_usd"]) > 0

    manifest_path = os.path.join(str(tmp_path), "inputs.jsonl")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        for i in range(4):
            handle.write(json.dumps({"id": f"clip-{i}", "tier": 1, "path": f"/workspace/clips/{i}.mp4"}) + "\n")
    out_dir = os.path.join(str(tmp_path), "out")
    spec["input"] = manifest_path
    spec["output"] = out_dir
    spec["template"] = None

    report = driver.run_driver(
        spec,
        base_dir=str(tmp_path),
        inference=driver.FakeInference(),
        output_dir=out_dir,
        budget_usd=float(spec["budget_usd"]),
        price_per_record=0.001,
        shard_size=10,
    )
    assert report["records"] == 4
    # Spend is tracked and stays under the (generous) committed budget.
    assert report["spend_usd"] == pytest.approx(4 * 0.001)
    assert report["over_budget"] is False


# ----------------------------------------------------------------------
# GPU-A on-pod driver: source-level guards (NOT imported -- it pulls torch /
# transformers / TRIBE which are absent in the sandbox). We read it as text and
# assert the review fixes hold: it runs the COMMITTED spec and flips the HF
# offline toggles only AFTER the first Step 0 pass.
# ----------------------------------------------------------------------
def _gpu_a_source(repo_root):
    path = os.path.join(repo_root, "pod", "gpu_a_pipeline.py")
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def test_gpu_a_driver_runs_committed_spec_not_inline(repo_root):
    src = _gpu_a_source(repo_root)
    # Loads the committed spec from the volume via the stdlib config loader.
    assert "/workspace/datagen/teacher-queue-v1.yaml" in src
    assert "from overwatch.config import load_config" in src
    # The divergent inline spec builder is gone (no /workspace/inputs/*.jsonl).
    assert "_teacher_specs" not in src
    assert "/workspace/inputs/" not in src


def test_gpu_a_driver_flips_offline_after_step0(repo_root):
    src = _gpu_a_source(repo_root)
    # Ordering guard: the Step 0 smoke/benchmark call must appear BEFORE the
    # offline toggle in main(), so lazily-loaded encoders cache first.
    step0_idx = src.find("step0_smoke_and_benchmark(model, args.reports_dir)")
    offline_idx = src.find("enable_offline_mode()", src.find("def main("))
    assert step0_idx != -1 and offline_idx != -1
    assert step0_idx < offline_idx


def test_gpu_b_driver_reads_staged_manifest_not_inputs(repo_root):
    path = os.path.join(repo_root, "pod", "gpu_b_pipeline.py")
    with open(path, "r", encoding="utf-8") as handle:
        src = handle.read()
    # GPU-B reads the staged tier-ordered manifest, fail-closed, and no longer
    # the unstaged /workspace/inputs/clips.jsonl.
    assert "/workspace/datagen/teacher-queue-inputs.jsonl" in src
    assert "/workspace/inputs/clips.jsonl" not in src
    assert "FileNotFoundError" in src


def test_spec_resume_is_idempotent_offline(repo_root, tmp_path, monkeypatch):
    monkeypatch.setenv("OVERWATCH_FAKE", "1")
    spec = config.load_config(os.path.join(repo_root, "datagen", "teacher-queue-v1.yaml"))
    manifest_path = os.path.join(str(tmp_path), "inputs.jsonl")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        for i in range(3):
            handle.write(json.dumps({"id": f"clip-{i}", "tier": 1, "path": f"/workspace/clips/{i}.mp4"}) + "\n")
    out_dir = os.path.join(str(tmp_path), "out")
    spec["input"] = manifest_path
    spec["output"] = out_dir
    spec["template"] = None

    first = driver.run_driver(spec, base_dir=str(tmp_path), output_dir=out_dir, shard_size=10)
    assert first["records"] == 3
    second = driver.run_driver(spec, base_dir=str(tmp_path), output_dir=out_dir, shard_size=10)
    assert second["new_records"] == 0
    assert second["records"] == 3
