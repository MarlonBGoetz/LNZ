# QA rubric: labels-v1

Grade each sampled record against the checks below. A record is **bad** if it
fails any check; otherwise it is **ok**. When the bad-output fraction of a
sample crosses the configured threshold, the datagen job pauses and raises a
flag for human review.

## Checks

1. **Non-empty** — the output must not be empty or whitespace-only. An empty
   completion is graded `empty`.
2. **Not a refusal** — the model must attempt the task. Outputs that begin with
   a refusal ("I cannot", "I'm sorry", "As an AI", ...) are graded `refusal`.
3. **Well-formed** — the output must be the requested format (a small JSON
   object `{"label": "..."}`). Malformed or non-JSON output is graded `format`.

## Pause threshold

If more than the configured fraction of a QA sample is bad (empty + refusal +
format), pause the job and ask a human before producing more records. The goal
is to stop spending budget on a broken prompt/model/template as early as
possible.
