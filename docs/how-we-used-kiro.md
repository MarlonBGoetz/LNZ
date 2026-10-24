# How we used Kiro

gpu-overwatch is a Kiro-first project. Kiro did not just help write it; Kiro
wrote it from a spec and then operated it. Everything below is verifiable in the
repository tree.

## Spec in, code out

[`docs/overwatch-plan.md`](overwatch-plan.md) is the single checked-in
specification. Kiro generated the `overwatch/` Python package (config, state,
policy, detectors, MCP server, watch program, guard, CLI, client, sidecar and
datagen driver), the offline test suite, and the Power wiring from it. The
"purely Kiro" rule means the plan is the source of truth and the code follows
it.

## Steering keeps agents on-policy

Four steering files in [`.kiro/steering/`](../.kiro/steering/) encode the rules
the running agents must honor: `gpu-policy.md` (lower-only caps, GPU allowlist,
never delete a volume, never stop a kept Pod), `training-contract.md`,
`datagen.md` and `gpu-setup.md`. The generated code and the live agents read the
same policy.

## The operating surface

- **2 agents** in [`.kiro/agents/`](../.kiro/agents/): `gpu-operator.md` (the
  session operator persona) and `gpu-medic.json` (the careful triage agent that
  takes the smallest safe action).
- **8 hooks** in [`.kiro/hooks/`](../.kiro/hooks/) spanning `SessionStart`,
  `PreToolUse` (two guards), `PostToolUse` (audit log and start-supervision),
  `PostFileSave`, `Stop` and `SessionEnd`.
- **2 workflows** in [`.kiro/workflows/`](../.kiro/workflows/): `supervise-run`
  (watch plus `gpu-medic` triage in a repeat loop, then a post-mortem) and
  `datagen` (watch, QA against a rubric, teardown).
- **6 skills** in [`gpu-overwatch/skills/`](../gpu-overwatch/skills/): `setup`,
  `launch-run`, `triage-run`, `gpu-sizing`, `dataset-fanout` and `teardown`.
- **Power packaging**: [`plugin.json`](../gpu-overwatch/plugin.json) and
  [`mcp.json`](../gpu-overwatch/mcp.json), which wire the `runpod` and
  `overwatch` MCP servers.

## The result

With this wiring, a Kiro session recommended a GPU, smoke tested, launched real
H100 Pods on Runpod, watched them, kept them inside the budget guard, and tore
them down cleanly, all through the MCP tools and hooks above. See the README
["The win"](GPU_OVERWATCH.md#-the-win) section for the honest scope.
