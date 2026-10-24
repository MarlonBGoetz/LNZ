"""gpu-overwatch: launch, watch, fix and shut down Runpod GPU work from Kiro.

Importing this package pulls in NO third-party module. The entire testable
surface (config, state, policy, detectors, watch, guard, cli) runs on the
Python standard library only. Real integrations (FastMCP, httpx, the runpod
SDK, jinja2, PyYAML) are optional and import-guarded at their use sites.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
