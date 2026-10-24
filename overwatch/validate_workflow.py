"""Offline validator for the supervise-run workflow recipe.

The IDE ships a ``validate_workflow`` tool, but it is not available in this
sandbox, so this module is the offline stand-in. It parses a workflow JSON file
and checks the structural invariants the command-watch contract requires:

* the top-level keys (``name``, ``description``, ``inputs``, ``steps``) exist
  with the right types;
* every ``watch`` step's ``command`` string contains **no templates**
  (``{{ ... }}``) -- the run id must not be baked into the command;
* the run id is passed through the watch ``config`` as ``runId`` instead;
* a watch handler sets ``idleTimeoutSec`` so a dead run eventually terminates.

Usage::

    python -m overwatch.validate_workflow <workflow.json>

Exit code is ``0`` when the workflow is valid and non-zero otherwise, with the
problems written to stderr. The :func:`validate` function returns the list of
problems (empty when valid) so it can be reused by the CLI and tests.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any, Dict, List

# Matches a Kiro template expression such as "{{ run_id }}".
_TEMPLATE_RE = re.compile(r"\{\{.*?\}\}")


def _is_template(value: Any) -> bool:
    return isinstance(value, str) and bool(_TEMPLATE_RE.search(value))


def _walk_steps(steps: Any) -> List[Dict[str, Any]]:
    """Flatten nested steps (a ``repeat`` carries its own ``steps`` list)."""
    out: List[Dict[str, Any]] = []
    if not isinstance(steps, list):
        return out
    for step in steps:
        if not isinstance(step, dict):
            continue
        out.append(step)
        for key in ("steps", "do", "body"):
            if isinstance(step.get(key), list):
                out.extend(_walk_steps(step[key]))
    return out


def validate(data: Any) -> List[str]:
    """Return a list of problems; empty means the workflow is valid."""
    problems: List[str] = []

    if not isinstance(data, dict):
        return ["workflow must be a JSON object"]

    # --- required top-level keys / types ---
    for key, typ in (("name", str), ("description", str), ("inputs", dict), ("steps", list)):
        if key not in data:
            problems.append(f"missing required key: {key!r}")
        elif not isinstance(data[key], typ):
            problems.append(f"key {key!r} must be {typ.__name__}")

    if not isinstance(data.get("steps"), list):
        return problems  # cannot inspect steps further

    all_steps = _walk_steps(data["steps"])
    if not all_steps:
        problems.append("workflow has no steps")

    watch_steps = []
    for step in all_steps:
        watch = step.get("watch")
        handler = step.get("handler")
        # The recipe nests the handler under a watch step:
        #   {"id": "health", "watch": {"handler": {"command", "config"}}}
        if isinstance(watch, dict) and isinstance(watch.get("handler"), dict):
            watch_steps.append((step, watch["handler"]))
        elif isinstance(watch, dict) and ("command" in watch or "config" in watch):
            watch_steps.append((step, watch))
        elif isinstance(handler, dict) and isinstance(handler.get("config"), dict):
            watch_steps.append((step, handler))
        elif step.get("type") == "watch" and isinstance(step.get("config"), dict):
            watch_steps.append((step, step))

    if not watch_steps:
        problems.append("workflow has no watch step")

    for step, watch in watch_steps:
        command = watch.get("command")
        config = watch.get("config")
        if not isinstance(command, str) or not command.strip():
            problems.append(f"watch step {step.get('id')!r}: missing command string")
        elif _is_template(command):
            problems.append(
                f"watch step {step.get('id')!r}: command must not contain templates "
                f"(got {command!r}); pass runId via config instead"
            )
        if not isinstance(config, dict):
            problems.append(f"watch step {step.get('id')!r}: missing config object")
            continue
        if "runId" not in config:
            problems.append(
                f"watch step {step.get('id')!r}: config must pass the run id via 'runId'"
            )
        if "idleTimeoutSec" not in config:
            problems.append(
                f"watch step {step.get('id')!r}: config must set 'idleTimeoutSec'"
            )
        else:
            idle = config.get("idleTimeoutSec")
            if not isinstance(idle, (int, float)) or isinstance(idle, bool) or idle <= 0:
                problems.append(
                    f"watch step {step.get('id')!r}: idleTimeoutSec must be a positive number"
                )

    return problems


def validate_file(path: str) -> List[str]:
    """Load a workflow file and validate it; parse errors become problems."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return [f"workflow file not found: {path}"]
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]
    return validate(data)


def main(argv: List[str] | None = None) -> int:
    """CLI entrypoint: validate each file argument; non-zero on any problem."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        sys.stderr.write("usage: python -m overwatch.validate_workflow <workflow.json> ...\n")
        return 2
    ok = True
    for path in args:
        problems = validate_file(path)
        if problems:
            ok = False
            sys.stderr.write(f"INVALID {path}:\n")
            for problem in problems:
                sys.stderr.write(f"  - {problem}\n")
        else:
            sys.stdout.write(f"OK {path}\n")
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
