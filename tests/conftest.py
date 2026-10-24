"""Pytest configuration for gpu-overwatch.

Puts the repository root on ``sys.path`` so ``import overwatch`` works without
installing the package (no ``pip install -e .`` required, which matters because
the sandbox cannot reach any package registry). Also provides a fixture that
points ``OVERWATCH_STATE`` at a temp file so state tests never touch the real
``.overwatch/state.json``.
"""

from __future__ import annotations

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


@pytest.fixture()
def temp_state(tmp_path, monkeypatch):
    """Return a temp state path and route OVERWATCH_STATE at it."""
    path = os.path.join(str(tmp_path), "state.json")
    monkeypatch.setenv("OVERWATCH_STATE", path)
    return path


@pytest.fixture()
def repo_root():
    """Absolute path to the repository root (for reading committed config)."""
    return REPO_ROOT
