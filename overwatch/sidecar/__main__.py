"""Entry point: ``python -m overwatch.sidecar -- <train cmd>``.

Starts the :class:`~overwatch.sidecar.runner.Runner` wrapping the training
command and the :mod:`~overwatch.sidecar.server` HTTP service on
``$OVERWATCH_PORT`` (default 8080), then blocks until the training process
exits. SIGTERM triggers the runner's checkpoint-then-exit reflex.

Usage::

    python -m overwatch.sidecar [--port N] [--host H] -- python train.py ...

Everything after ``--`` is the training command, run verbatim.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from typing import List, Optional, Tuple

from ..policy import Policy
from .runner import Runner
from .server import build_server, serve_in_thread

DEFAULT_PORT = 8080


def _split_argv(argv: List[str]) -> Tuple[List[str], List[str]]:
    """Split ``argv`` at the first ``--`` into (sidecar args, train command)."""
    if "--" in argv:
        idx = argv.index("--")
        return argv[:idx], argv[idx + 1:]
    return argv, []


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    own_args, train_cmd = _split_argv(argv)

    parser = argparse.ArgumentParser(prog="python -m overwatch.sidecar")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("OVERWATCH_PORT", DEFAULT_PORT)),
    )
    parser.add_argument("--price-per-hour", type=float, default=0.0)
    parser.add_argument("--budget-cap-usd", type=float, default=None)
    parser.add_argument("--max-hours", type=float, default=None)
    args = parser.parse_args(own_args)

    if not train_cmd:
        parser.error("no training command given; pass it after `--`")

    policy = Policy.load()
    runner = Runner(
        train_cmd,
        policy=policy,
        price_per_hour=args.price_per_hour,
        budget_cap_usd=args.budget_cap_usd,
        max_hours=args.max_hours,
    )

    server = build_server(runner, host=args.host, port=args.port)
    serve_in_thread(server)
    bound_port = server.server_address[1]

    # SIGTERM reflex: checkpoint then exit.
    signal.signal(signal.SIGTERM, runner.handle_sigterm)

    runner.start()
    print(f"[overwatch.sidecar] serving on {args.host}:{bound_port}", flush=True)

    code = runner.wait()
    runner.shutdown()
    server.shutdown()
    return int(code or 0)


if __name__ == "__main__":
    raise SystemExit(main())
