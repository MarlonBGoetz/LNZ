"""Policy model for ``.overwatch/policy.yaml``.

Holds spend caps, the GPU allowlist and the detector thresholds that mirror the
Supervision-loop table in the plan. The single most important safety rule lives
here: :meth:`Policy.budget_set` can only ever *lower* a cap. Any attempt to
raise a cap raises :class:`BudgetRaiseError`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import config

DEFAULT_POLICY_PATH = os.path.join(".overwatch", "policy.yaml")

# Default detector thresholds (mirror the Supervision-loop table in the plan).
DEFAULT_THRESHOLDS: Dict[str, Any] = {
    # NaN loss: restart at half the learning rate, at most 2 retries.
    "nan_restart_lr_factor": 0.5,
    "nan_max_retries": 2,
    # Divergence: loss EMA rising for 200 steps.
    "divergence_ema_rising_steps": 200,
    # OOM: halve the micro-batch.
    "oom_microbatch_factor": 0.5,
    # Stall: no step for 10 min, or util < 5% for 10 min.
    "stall_no_step_seconds": 600,
    "stall_util_floor_pct": 5,
    "stall_util_seconds": 600,
    # Preemption: 3 missed polls.
    "preempt_missed_polls": 3,
    # Eval regression: eval worse for 3 evals.
    "eval_regression_evals": 3,
    # Budget: warn at 80%, stop at 100%.
    "budget_warn_fraction": 0.8,
    "budget_stop_fraction": 1.0,
    # Checkpoint every 15 minutes.
    "checkpoint_interval_seconds": 900,
}

DEFAULT_SESSION_CAP_USD = 50.0
DEFAULT_PER_RUN_CAP_USD = 20.0
DEFAULT_MAX_HOURS = 8.0
DEFAULT_GPU_ALLOWLIST = ["A100", "H100"]


class BudgetRaiseError(ValueError):
    """Raised when a tool attempts to raise a spend cap (not permitted)."""


@dataclass
class Policy:
    """In-memory policy. Caps may only be lowered via :meth:`budget_set`."""

    session_cap_usd: float = DEFAULT_SESSION_CAP_USD
    per_run_cap_usd: float = DEFAULT_PER_RUN_CAP_USD
    max_hours: float = DEFAULT_MAX_HOURS
    gpu_allowlist: List[str] = field(default_factory=lambda: list(DEFAULT_GPU_ALLOWLIST))
    thresholds: Dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))

    # Only these keys are treated as lowerable spend caps.
    _CAP_KEYS = ("session_cap_usd", "per_run_cap_usd", "max_hours")

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "Policy":
        """Build a policy from a parsed mapping, filling in defaults."""
        data = data or {}
        thresholds = dict(DEFAULT_THRESHOLDS)
        thresholds.update(data.get("thresholds") or {})
        allowlist = data.get("gpu_allowlist")
        if not allowlist:
            allowlist = list(DEFAULT_GPU_ALLOWLIST)
        return cls(
            session_cap_usd=float(data.get("session_cap_usd", DEFAULT_SESSION_CAP_USD)),
            per_run_cap_usd=float(data.get("per_run_cap_usd", DEFAULT_PER_RUN_CAP_USD)),
            max_hours=float(data.get("max_hours", DEFAULT_MAX_HOURS)),
            gpu_allowlist=list(allowlist),
            thresholds=thresholds,
        )

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Policy":
        """Load the policy from ``policy.yaml`` (or defaults if missing)."""
        target = path or DEFAULT_POLICY_PATH
        if not os.path.exists(target):
            return cls()
        return cls.from_dict(config.load_config(target))

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the policy back to a plain mapping."""
        return {
            "session_cap_usd": self.session_cap_usd,
            "per_run_cap_usd": self.per_run_cap_usd,
            "max_hours": self.max_hours,
            "gpu_allowlist": list(self.gpu_allowlist),
            "thresholds": dict(self.thresholds),
        }

    # ------------------------------------------------------------------
    # Thresholds
    # ------------------------------------------------------------------
    def threshold(self, name: str) -> Any:
        """Return a detector threshold by name."""
        if name not in self.thresholds:
            raise KeyError(f"unknown threshold: {name}")
        return self.thresholds[name]

    # ------------------------------------------------------------------
    # Lower-only cap setter
    # ------------------------------------------------------------------
    def budget_set(self, key: str, value: float) -> float:
        """Lower a spend cap. Raising a cap is rejected.

        Returns the new cap value on success. Raises
        :class:`BudgetRaiseError` if ``value`` is greater than the current
        cap, and :class:`KeyError` if ``key`` is not a cap.
        """
        if key not in self._CAP_KEYS:
            raise KeyError(f"not a lowerable cap: {key}")
        value = float(value)
        current = float(getattr(self, key))
        if value > current:
            raise BudgetRaiseError(
                f"cannot raise {key} from {current} to {value}; caps may only be lowered"
            )
        setattr(self, key, value)
        return value

    def gpu_allowed(self, gpu: str) -> bool:
        """Whether a GPU type is permitted by the allowlist."""
        return gpu in self.gpu_allowlist
