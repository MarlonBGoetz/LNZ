---
inclusion: fileMatch
fileMatchPattern: "datagen/**"
---

# Datagen conventions

These rules apply to dataset-generation code and specs under `datagen/`. The
driver is idempotent so a stopped job resumes without duplicating work.

## Spec format

A datagen spec (YAML/JSON) declares everything that affects a generated record.
Pin these fields so the idempotency key is stable:

- `input` — the input source (file/dataset/query) and how to iterate it.
- `model` — the model used for generation.
- `template` — the prompt template (by name or inline).
- `sampling` — decoding parameters (temperature, top-p, max tokens, `n`).
- `mode` — one-shot, multi-sample fan-out, or multi-stage.
- `qa` — validity checks and the quality rubric/threshold.
- `output` — the shard directory and target shard size.

## Idempotency keys

Each record's key is `hash(input, model, template, sampling)`. The key is
computed from the pinned spec fields, so:

- Re-running the same spec **skips** records already produced (exact dedup by
  key); it never duplicates them.
- Changing any keyed field (model, template, sampling, input) produces **new**
  records rather than colliding with old ones.

Never derive a record's identity from wall-clock time, ordering, or a random
seed that is not part of the key.

## Shard layout

- Records are written to numbered shards under the spec's `output` directory
  (e.g. `datagen/<job>/shard-00001.jsonl`).
- Writes are **atomic**: write to a temp file, then rename into place, so a
  crash never leaves a half-written shard.
- A `manifest.json` lists the finished shards; resume reads it to skip completed
  work.
- Failed records (after retries with exponential backoff) go to a poison queue
  `failed.jsonl` for later inspection, never silently dropped.
