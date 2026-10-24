# QA rubric: teacher-queue-v1 (TRIBE v2 teacher traces)

Grade each sampled teacher trace against the checks below. A record is **bad**
if it fails any check; otherwise it is **ok**. When the bad-output fraction of a
sample crosses the configured threshold (`qa.every_records` / `qa.sample_size`
in `datagen/teacher-queue-v1.yaml`), the datagen job pauses and raises a flag
for human review so a broken teacher/model path never burns budget.

These checks run against the grader in `overwatch.datagen.driver.grade_output`,
which the driver applies to the serialized teacher output text.

## Checks

1. **Non-empty** — the teacher trace must not be empty or whitespace-only. An
   empty trace is graded `empty`. A real TRIBE failure must raise (and land in
   `failed.jsonl`), never produce an empty trace; NO fake-teacher fallback.
2. **Not a refusal** — the output must be an actual teacher trace, not a model
   refusal string. Outputs that begin with a refusal ("I cannot", "I'm sorry",
   "As an AI", ...) are graded `refusal`.
3. **Well-formed** — the trace must be the expected serialized object (JSON).
   Malformed or non-JSON output is graded `format`.

## Teacher-specific signals (recorded in the Step 0 report, not graded here)

The GPU-A Step 0 smoke + throughput benchmark records, per run, whether the
**subcortical response** fires, whether the **jump-scare response** fires, the
**clips/hour/worker** for 1 vs 2 workers, and the **projected clips labeled** in
the queue window. Review those in `/workspace/reports/step0_benchmark.json`
before trusting the queue output.

## Pause threshold

If more than the configured fraction of a QA sample is bad (empty + refusal +
format), pause the job and ask a human before producing more traces. The
non-cuttable demo-clip traces and the ONNX export must never be skipped to work
around a QA pause; fix the teacher path and resume instead.
