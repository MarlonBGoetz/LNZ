---
inclusion: manual
---

# /gpu-setup

Run the gpu-overwatch Power's **setup** skill to bring this workspace to a
launch-ready state.

This steering file is `inclusion: manual`, so Kiro surfaces it as the
`/gpu-setup` slash command. When the user invokes `/gpu-setup` (or when the
SessionStart fleet brief / `overwatch doctor` reports that setup is incomplete),
follow the Power's setup skill: `gpu-overwatch/skills/setup/SKILL.md`.

Key rules to honor while running setup:

- Run the doctor first (`bash gpu-overwatch/skills/setup/scripts/doctor.sh
  --json`) and **skip any step that is already `ok`**.
- Ask the user **one concern at a time**; do not dump the whole checklist.
- **Never ask for the `RUNPOD_API_KEY` in chat** -- it is read from the shell
  environment and only its last 4 characters are ever displayed.
- Steps that need live Runpod (API reachability, datacenter stock, volume
  creation, a live GPU smoke) are **reported honestly as needing credentials**,
  never faked.
- The free self-test (step 7) runs fully offline (`overwatch selftest`).
- Finish by **running the doctor again** to confirm every check is green.
