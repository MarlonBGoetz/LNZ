# gpu-overwatch

A Kiro Power that lets Kiro launch, watch, fix and shut down Runpod GPU work as
if the GPUs were local. The full specification lives in
[`docs/overwatch-plan.md`](docs/overwatch-plan.md) and the project is built from
it (the "purely Kiro" rule).

## Status

Phase 0 foundation. The testable surface runs on the Python standard library
only — no network, no GPU, and no package installs are required.

```bash
python -c 'import overwatch; print(overwatch.__version__)'
pytest -q tests/
```

## Layout

See the "Kiro wiring" section of [the plan](docs/overwatch-plan.md) for the full
directory layout. Core foundation modules:

- `overwatch/config.py` — stdlib YAML/JSON loaders (PyYAML used if present).
- `overwatch/state.py` — atomic `.overwatch/state.json` run registry (holds
  per-run bearer tokens; gitignored and in `.kiroignore`).
- `overwatch/policy.py` — spend caps (lower-only `budget_set`) and detector
  thresholds.

## Safety

- Spend caps in `.overwatch/policy.yaml` can only ever be **lowered** by tools.
- `.overwatch/state.json` holds secrets; it is gitignored and in `.kiroignore`.
