# gpu-overwatch

**Kiro drives real GPUs like they were local.** A Kiro Power that recommends, sizes, smoke tests, launches, watches, auto-heals, budget-guards and tears down Runpod GPU runs, with spend caps and safety guardrails baked in.

[![tests](https://img.shields.io/badge/tests-261%20passing-brightgreen)](../tests/)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](../pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-lightgrey)](#license)
[![built with Kiro](https://img.shields.io/badge/built%20with-Kiro-5A3EC8)](#-how-we-used-kiro)

gpu-overwatch is a packaged Kiro Power plus a stdlib-only Python package. Kiro wrote the code from a single checked-in spec ([`docs/overwatch-plan.md`](overwatch-plan.md)), and Kiro operates it through MCP tools, hooks, workflows, skills and agents. The whole testable surface runs on the Python standard library: no network, no GPU and no installs are needed to run the suite.

## 🏆 The win

This session, a **Kiro-built Power drove real Runpod H100 80GB Pods end to end** through the full supervised lifecycle:

- The real backend talked to the **live Runpod REST API** ([`rest.runpod.io/v1`](https://rest.runpod.io/v1)) and the GraphQL pricing API using **only the Python standard library** (`urllib`): no `runpod` SDK, no `httpx`, no third-party HTTP client.
- A **200 GB network volume** was created live in datacenter **US-MO-1**.
- **H100 Pods launched on secure cloud at $3.99/hr**, mounted the volume, and were cleanly stopped and terminated afterward.
- The **budget guard**, the **GPU allowlist**, the **smoke-before-launch gate** and the **no-silent-fallback-to-fake-data** invariant all held under live conditions.

**Honest scope:** we did not complete a full training run or ship a finished distillation dataset this session. The proven, brag-worthy result is the **supervised lifecycle itself** working against real hardware:

```
recommend -> size -> smoke -> launch -> watch -> budget-guard -> teardown
```

Every step above ran against live Runpod infrastructure, inside the policy guardrails, with no SDK dependency.

## 🧭 Architecture: the supervised-run loop

```
                        .overwatch/policy.yaml
                     (lower-only caps + thresholds)
                                  |
   gpu_recommend --> run_smoke --> [ guard: budget + GPU allowlist + smoke-passed ]
        size          validate                     |
                                                    v
                                              run_launch
                                      (ow-<run> Pod, volume, token)
                                                    |
          +-----------------------------------------+
          |              supervise-run workflow (repeat loop)
          v                                         |
   overwatch.watch  --one JSON line-->  gpu-medic agent (triage-run skill)
   (idle / new-activity / terminal)         smallest safe action
          |                                         |
          |            budget_status / run_metrics  |
          +------------------- budget guard --------+
                                                    |
                            100% spend -> run_stop  |
                                                    v
                                  run_report + teardown (fleet_reap)
```

The watch program reads a cursor and config on stdin and prints exactly one JSON line (`idle`, `new-activity` or `terminal-state`). A per-Pod sidecar wraps the training process behind a bearer token, periodically checkpoints, and self-stops at the budget or max-hours ceiling.

## 🛠️ MCP tools (20)

Every tool returns compact JSON plus a one-line human summary. Names are exact.

**Lifecycle**
- `gpu_recommend`: recommend a GPU type and count for a model and batch estimate.
- `run_smoke`: launch a short smoke run to validate the image and config.
- `run_launch`: provision a Pod and start a supervised training run.
- `run_status`: current status of one run.
- `run_logs`: tail logs for a run.
- `run_metrics`: latest metrics (loss, util, step rate) for a run.
- `run_signal`: send a signal (checkpoint, stop, restart) to a run.
- `run_restart`: restart a run from its latest checkpoint.
- `run_stop`: stop a run and optionally keep or destroy the Pod.
- `run_list`: list known runs.
- `run_report`: write a Markdown report for a run to `.overwatch/reports/`.
- `artifacts_pull`: pull checkpoints and artifacts from a run's volume.

**Fleet**
- `fleet_status`: status across all live Pods.
- `fleet_reap`: stop or destroy orphaned or over-budget Pods.

**Budget**
- `budget_status`: current session and per-run spend versus caps.
- `budget_set`: **lower** a cap (raising is rejected).

**Datagen**
- `datagen_start`: start a dataset-generation fan-out.
- `datagen_status`: progress of a datagen job (shards, records, failures).
- `datagen_sample`: sample a few generated records.
- `datagen_stop`: stop a datagen job.

## 🛡️ Safety model

- **Lower-only caps.** Spend caps in `.overwatch/policy.yaml` can only ever be lowered by tools. Raising is rejected, and `budget_set` enforces this. The guard blocks direct edits to the policy file.
- **Guard categories.** A `PreToolUse` guard checks every risky action against policy: the session and per-run budget, the GPU allowlist (short names mapped to real Runpod GPU IDs without loosening the check), volume protection (never delete a network volume) and keep protection (never stop or terminate a Pod marked `OVERWATCH_KEEP`).
- **Smoke before launch.** `run_launch` and `run_restart` are gated: the guard refuses to provision until a smoke test has passed.
- **No silent fake fallback.** When `RUNPOD_API_KEY` is set and `OVERWATCH_FAKE` is not `1`, the backend will not quietly fall back to fabricated data. A live run cannot "succeed" on made-up numbers.
- **Secrets stay out of git.** `.overwatch/state.json` holds per-run bearer tokens; it is gitignored and listed in `.kiroignore`, so it is never committed and never fed to the model. The Runpod API key is never printed or logged.

## 🧩 Purely Kiro

The project follows one rule: **everything is generated by Kiro from the spec.** [`docs/overwatch-plan.md`](overwatch-plan.md) is the checked-in specification, and Kiro produced the package, the tests, and the Power wiring from it. The steering files encode the policy and the training contract, so the generated code and the running agents share one source of truth.

## 🤖 How we used Kiro

Judges can verify every item below directly in the `.kiro/` tree and in `gpu-overwatch/`.

### Specs and steering drove the code
- [`docs/overwatch-plan.md`](overwatch-plan.md) is the spec. Kiro generated the `overwatch/` package, the sidecar, the MCP server, the CLI and the tests from it.
- Steering files in [`.kiro/steering/`](../.kiro/steering/) keep the agents on-policy: `gpu-policy.md` (caps, allowlist, destructive-action rules), `training-contract.md`, `datagen.md` and `gpu-setup.md`.

### Agents (2)
- [`.kiro/agents/gpu-operator.md`](../.kiro/agents/gpu-operator.md): the operator persona that sizes, smoke tests, launches, supervises and tears down runs, with the launch, sizing, teardown, triage and setup skills attached.
- [`.kiro/agents/gpu-medic.json`](../.kiro/agents/gpu-medic.json): a careful triage agent that reads a watch result and takes the smallest safe action to keep a run healthy. Read-only tools auto-approve; the `overwatch` tool requires confirmation.

### Hooks (8)
- `fleet-brief` (`SessionStart`): load policy and print a fleet and budget brief.
- `guard-runpod` (`PreToolUse`): guard every direct Runpod MCP tool call against policy before it runs.
- `guard-launch` (`PreToolUse`): guard `run_launch` and `run_restart`, enforcing budget and GPU allowlist and requiring a passed smoke test.
- `audit-log` (`PostToolUse`): append tool name, arguments and result to the audit log after every Runpod or overwatch call.
- `start-supervision` (`PostToolUse`): after a successful `run_launch`, start the `supervise-run` workflow for the new run id.
- `preflight-on-save` (`PostFileSave`): re-run preflight checks when a training script or run config is saved.
- `reap-on-stop` (`Stop`): on session stop, show idle Pods and ask before reaping them; kept Pods are always skipped.
- `session-summary` (`SessionEnd`): reap orphaned Pods and write a session summary of the fleet and total spend.

### Workflows (2)
- [`supervise-run`](../.kiro/workflows/supervise-run.workflow.json): a `repeat` loop that watches the run with `overwatch.watch` and lets `gpu-medic` triage each poll, stopping on the terminal health state, then writes a post-mortem report.
- [`datagen`](../.kiro/workflows/datagen.workflow.json): start, watch, QA and tear down a dataset-collection job; `gpu-medic` grades samples against the QA rubric and pauses the job if the bad-output rate crosses the threshold.

### Skills (6)
Under [`gpu-overwatch/skills/`](../gpu-overwatch/skills/): `setup`, `launch-run`, `triage-run`, `gpu-sizing`, `dataset-fanout` and `teardown`.

### Power packaging
- [`gpu-overwatch/plugin.json`](../gpu-overwatch/plugin.json) declares the Power.
- [`gpu-overwatch/mcp.json`](../gpu-overwatch/mcp.json) wires two MCP servers: the `runpod` server (`@runpod/mcp-server`) and the local `overwatch` server (`python -m overwatch.server`).

A standalone write-up lives in [`docs/how-we-used-kiro.md`](how-we-used-kiro.md).

## 🚀 Quickstart

Run the offline test suite (stdlib only, no network, no GPU, no installs):

```bash
python3 -c 'import overwatch; print(overwatch.__version__)'
python3 -m pytest -q tests/
```

Install the Power in Kiro by adding the `gpu-overwatch/` directory as a Power; `mcp.json` registers the `runpod` and `overwatch` MCP servers (set `RUNPOD_API_KEY` in the environment).

Check and bootstrap the environment with the `overwatch` CLI:

```bash
overwatch doctor     # environment health check (--brief, --json)
overwatch init       # guided, resumable 8-step setup
```

## 🔧 Hardening and what's next

Recent hardening: packaging now ships `overwatch.datagen`, the GraphQL pricing call sends its key via an `Authorization: Bearer` header (no key in the URL), and the no-silent-fake-fallback invariant is enforced. Next up: confirm the Serverless vLLM request and response shape and endpoint creation, confirm the live `dockerStartCmd` field name against the Runpod REST schema, and settle sidecar delivery onto the Pod. See [`docs/HANDOFF.md`](HANDOFF.md) for the current known limitations.

## License

MIT.
