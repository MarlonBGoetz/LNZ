"""CPU-only training stand-in that drives the sidecar/detector tests.

Uses :mod:`overwatch.client` to emit step/loss metric records and a final
checkpoint. Failure injection via ``--fail MODE@STEP`` reproduces the four
canonical failure modes from the plan:

* ``nan@300``   -- emit a NaN loss at step 300.
* ``oom@100``   -- print ``CUDA out of memory`` and exit non-zero at step 100.
* ``hang@200``  -- stop emitting steps / sleep at step 200 (a stall).
* ``crash@50``  -- exit non-zero at step 50.

The default run completes with exit 0 and a final checkpoint.

To keep tests fast the loop is scaled: the failure/completion *trigger* steps
(300, 100, 200, 50, ...) are mapped to a small number of scaled iterations via
``--scale`` (default divides the trigger step so the loop runs in well under a
second). The ``--fail`` flag STRING is preserved exactly (``nan@300`` etc.);
only the internal iteration count is scaled.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time

# Make `import overwatch` work when run directly (no install in the sandbox).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from overwatch import client as ow  # noqa: E402


def _parse_fail(spec):
    """Parse ``MODE@STEP`` into ``(mode, step)`` or ``(None, None)``."""
    if not spec:
        return None, None
    if "@" not in spec:
        return spec, None
    mode, _, step = spec.partition("@")
    try:
        return mode, int(step)
    except ValueError:
        return mode, None


def main(argv=None):
    parser = argparse.ArgumentParser(prog="fake_train")
    parser.add_argument(
        "--fail",
        default=None,
        help="failure injection MODE@STEP, e.g. nan@300, oom@100, hang@200, crash@50",
    )
    parser.add_argument(
        "--total-steps",
        type=int,
        default=500,
        help="nominal total steps for a clean run (before scaling)",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=50,
        help="divide the nominal trigger step by this to keep tests fast",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="seconds to sleep per scaled step (keep tiny)",
    )
    parser.add_argument(
        "--hang-seconds",
        type=float,
        default=2.0,
        help="how long to sleep when hang is triggered",
    )
    args = parser.parse_args(argv)

    mode, trigger = _parse_fail(args.fail)
    scale = max(1, args.scale)

    def scaled(step):
        return max(1, step // scale)

    nominal_total = args.total_steps
    # The loop iterates over nominal steps but only emits at scaled cadence so
    # the trigger is reached quickly. We walk scaled iterations and map back to
    # the nominal step number for the records.
    total_iters = scaled(nominal_total)
    trigger_iter = scaled(trigger) if trigger is not None else None

    ckpt_dir = os.environ.get(ow.CKPT_DIR_ENV, ".")

    loss = 2.0
    for i in range(1, total_iters + 1):
        nominal_step = i * scale
        # Fire failure modes at the scaled trigger iteration.
        if trigger_iter is not None and i >= trigger_iter:
            if mode == "oom":
                print("CUDA out of memory. Tried to allocate 2.00 GiB", flush=True)
                return 2
            if mode == "crash":
                print(f"RuntimeError: training crashed at step {nominal_step}", flush=True)
                return 3
            if mode == "nan":
                ow.log(step=nominal_step, loss=float("nan"))
                print(f"loss became NaN at step {nominal_step}", flush=True)
                return 0
            if mode == "hang":
                print(f"[hang] no further progress after step {nominal_step}", flush=True)
                time.sleep(args.hang_seconds)
                return 0

        loss = max(0.05, loss * 0.97 + 0.001)
        ow.log(step=nominal_step, loss=loss, lr=1e-3, tokens=1024)
        print(f"step {nominal_step} loss {loss:.4f}", flush=True)
        if args.sleep:
            time.sleep(args.sleep)

    # Clean completion: final checkpoint and exit 0.
    final = os.path.join(ckpt_dir, "final.ckpt")
    ow.checkpoint(path=final, step=nominal_total)
    print(f"done; checkpoint {final}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
