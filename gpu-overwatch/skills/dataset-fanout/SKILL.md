---
name: dataset-fanout
description: Fan out a dataset-generation job — write a datagen spec, choose a mode, set a QA rubric, and resume a stopped job without duplicating records.
---

# Fan out dataset generation

Use this skill to generate a dataset with the datagen driver: write a spec, pick
a generation mode, define how records are judged, and launch/resume safely. The
driver is idempotent, so a stopped job resumes without re-doing finished work.

## 1. Write a datagen spec

A spec (YAML/JSON under `datagen/`) declares the inputs and the generation
parameters. It must pin everything that affects a record so the idempotency key
is stable: `input` source, `model`, prompt `template`, and `sampling`
parameters. The record key is `hash(input, model, template, sampling)`; changing
any of these produces new records rather than colliding with old ones. See
`datagen.md` steering for the exact spec format, idempotency keys and shard
layout.

## 2. Choose a mode

- **One-shot** — a single generation per input (default for most datasets).
- **Multi-sample / fan-out** — several samples per input (set `n`), used for
  best-of-N, self-consistency or preference data.
- **Multi-stage** — chain templates (e.g. draft then critique then refine).

Pick the smallest mode that produces the data you need; more samples cost more.

## 3. Set a QA rubric

Define how a record is accepted or rejected before it lands in a shard:

- Validity checks (schema, non-empty, language, length bounds).
- A quality rubric (a judge prompt or heuristic score with a threshold).
- Dedup is automatic — exact dedup by key; the rubric handles semantic quality.

Records that fail validation go to the poison queue `failed.jsonl` for review.

## 4. Launch and resume

- Start with `datagen_start`; monitor with `datagen_status` (shards, records,
  failures) and spot-check with `datagen_sample`.
- Shards are written atomically (write-then-rename) and a manifest lists the
  finished shards.
- **Resume a stopped job** by calling `datagen_start` again with the same spec:
  finished shards in the manifest are skipped, failed records in `failed.jsonl`
  are retried with exponential backoff, and exact-key dedup prevents duplicates.
- Stop a job with `datagen_stop`; it checkpoints the manifest so a later resume
  is clean.

## Checklist

- [ ] Spec pins input, model, template and sampling (stable idempotency keys).
- [ ] Mode chosen (one-shot / fan-out / multi-stage).
- [ ] QA rubric and validity checks defined; failures route to `failed.jsonl`.
- [ ] Resume verified: re-running skips finished shards and does not duplicate.
