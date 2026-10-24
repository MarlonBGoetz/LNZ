"""FastMCP entrypoint: ``python -m overwatch.server``.

The MCP SDK (``fastmcp`` / ``mcp``) is imported inside a guarded block. When the
SDK is present the 20 tool functions from :mod:`overwatch.tools` are registered
with a FastMCP server. When the SDK is absent -- as in the offline sandbox --
running ``python -m overwatch.server`` prints a clear "MCP SDK required" message
and exits non-zero **without a traceback**, while ``import overwatch.tools``
keeps working for the tests.

Each tool returns ``(result_dict, summary)``; the thin MCP wrapper adapts that
to a JSON payload with a ``summary`` field.
"""

from __future__ import annotations

import sys
from typing import Any

from . import tools


def _load_mcp():
    """Import a FastMCP-compatible server class, or return ``None``."""
    try:  # pragma: no cover - SDK absent in the sandbox
        from fastmcp import FastMCP  # type: ignore

        return FastMCP
    except Exception:
        pass
    try:  # pragma: no cover - SDK absent in the sandbox
        from mcp.server.fastmcp import FastMCP  # type: ignore

        return FastMCP
    except Exception:
        return None


def build_server(mcp_factory: Any = None):  # pragma: no cover - needs the SDK
    """Build and return a FastMCP server with every tool registered."""
    FastMCP = mcp_factory or _load_mcp()
    if FastMCP is None:
        raise RuntimeError("MCP SDK required")
    server = FastMCP("gpu-overwatch")

    def _register(name, fn):
        def wrapper(**kwargs: Any):
            result, summary = fn(**kwargs)
            return {"result": result, "summary": summary}

        wrapper.__name__ = name
        wrapper.__doc__ = fn.__doc__
        server.tool(name=name)(wrapper)

    for name, fn in tools.TOOLS.items():
        _register(name, fn)
    return server


def main(argv=None) -> int:
    """CLI entrypoint. Exits non-zero (cleanly) when the SDK is missing."""
    FastMCP = _load_mcp()
    if FastMCP is None:
        sys.stderr.write(
            "MCP SDK required: install the optional 'mcp' extra "
            "(pip install 'gpu-overwatch[mcp]') to run the overwatch MCP server. "
            "The tool functions in overwatch.tools import and run without the SDK.\n"
        )
        return 1
    server = build_server(FastMCP)  # pragma: no cover - SDK absent in sandbox
    server.run()  # pragma: no cover
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
