"""Test fixtures for the overwatch MCP tool suite.

``seed_fleet()`` returns a deterministic fake-backend seed with a GPU price
list, a mix of overwatch-created and foreign Pods and a network volume.
"""

from __future__ import annotations

from typing import Any, Dict


def gpu_price_list():
    """A deterministic GPU price list (USD/hour)."""
    return [
        {"id": "A100", "name": "A100 80GB", "memory_gb": 80, "price_per_hour": 1.89},
        {"id": "H100", "name": "H100 80GB", "memory_gb": 80, "price_per_hour": 2.99},
        {"id": "A40", "name": "A40 48GB", "memory_gb": 48, "price_per_hour": 0.79},
        {"id": "T4", "name": "T4 16GB", "memory_gb": 16, "price_per_hour": 0.29},
    ]


def seed_fleet() -> Dict[str, Any]:
    """Seed a fake backend with pods (overwatch + foreign) and a volume."""
    return {
        "gpu_types": gpu_price_list(),
        "pods": [
            {
                "id": "pod-ow-1",
                "name": "ow-run-aaa",
                "gpu": "A100",
                "gpu_count": 1,
                "price_per_hour": 1.89,
                "status": "RUNNING",
                "created_by": "overwatch",
                "env": {"OVERWATCH_RUN": "run-aaa", "OVERWATCH_KEEP": "0"},
            },
            {
                "id": "pod-ow-keep",
                "name": "ow-run-keep",
                "gpu": "H100",
                "gpu_count": 1,
                "price_per_hour": 2.99,
                "status": "RUNNING",
                "created_by": "overwatch",
                "env": {"OVERWATCH_RUN": "run-keep", "OVERWATCH_KEEP": "1"},
            },
            {
                "id": "pod-foreign-1",
                "name": "someone-elses-pod",
                "gpu": "A40",
                "gpu_count": 1,
                "price_per_hour": 0.79,
                "status": "RUNNING",
                "created_by": "other-user",
                "env": {},
            },
        ],
        "volumes": [
            {"id": "vol-PLACEHOLDER", "name": "checkpoints", "size_gb": 100},
        ],
    }
