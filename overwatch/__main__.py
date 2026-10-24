"""Make ``python -m overwatch`` behave like ``python -m overwatch.cli``.

Both invocations dispatch to :func:`overwatch.cli.main`.
"""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
