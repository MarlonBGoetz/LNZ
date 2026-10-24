"""Offline packaging-config tests for pyproject.toml.

These guard against a regression where a real ``overwatch`` subpackage (one that
carries an ``__init__.py``) is silently dropped from the distributed package
set. Historically the hand-maintained ``[tool.setuptools] packages`` list
enumerated only ``overwatch`` and ``overwatch.sidecar`` and OMITTED
``overwatch.datagen``, so a normal install shipped a broken/missing datagen
package. The fix switched to automatic discovery
(``[tool.setuptools.packages.find] include = ["overwatch*"]``).

The tests stay stdlib-only and do not import setuptools. They compare the
on-disk package layout (directories under ``overwatch/`` that contain an
``__init__.py``) against whatever the pyproject declares. ``tomllib`` is used
when available (Python 3.11+); a layout-vs-config consistency assertion also
runs on 3.10 without tomllib.
"""

from __future__ import annotations

import os

import pytest


def _discover_packages(repo_root):
    """Return the set of __init__.py-bearing package names under overwatch/."""
    pkg_root = os.path.join(repo_root, "overwatch")
    packages = set()
    for dirpath, _dirnames, filenames in os.walk(pkg_root):
        if "__init__.py" not in filenames:
            continue
        rel = os.path.relpath(dirpath, repo_root)
        packages.add(rel.replace(os.sep, "."))
    return packages


def test_layout_has_expected_packages(repo_root):
    """Sanity: the three real packages exist on disk; tests is NOT one."""
    packages = _discover_packages(repo_root)
    assert {"overwatch", "overwatch.sidecar", "overwatch.datagen"} <= packages
    # tests is intentionally not a package and must never be shipped.
    assert "tests" not in packages
    assert not os.path.exists(os.path.join(repo_root, "tests", "__init__.py"))


def test_pyproject_covers_every_real_package(repo_root):
    """Every __init__.py-bearing overwatch package must be covered by packaging.

    Fails if (e.g.) overwatch.datagen is dropped from the packaging config,
    whether packaging uses find-discovery or an explicit list.
    """
    tomllib = pytest.importorskip("tomllib")
    with open(os.path.join(repo_root, "pyproject.toml"), "rb") as fh:
        pyproject = tomllib.load(fh)

    setuptools_cfg = pyproject.get("tool", {}).get("setuptools", {})
    packages = _discover_packages(repo_root)

    pkgs_field = setuptools_cfg.get("packages")
    if isinstance(pkgs_field, list):
        # Explicit list: every real package must be enumerated.
        missing = packages - set(pkgs_field)
        assert not missing, f"pyproject packages list omits: {sorted(missing)}"
    else:
        # Automatic discovery: an include pattern must match overwatch*.
        find_cfg = (
            pkgs_field.get("find", {}) if isinstance(pkgs_field, dict) else
            setuptools_cfg.get("packages", {})
        )
        if not find_cfg:
            find_cfg = (
                pyproject.get("tool", {})
                .get("setuptools", {})
                .get("packages", {})
            )
        include = find_cfg.get("include", []) if isinstance(find_cfg, dict) else []
        assert any(
            pat == "overwatch*" or pat == "overwatch" or pat.startswith("overwatch")
            for pat in include
        ), f"find discovery must include an overwatch* pattern, got {include!r}"


def test_datagen_regression_guard_without_tomllib(repo_root):
    """3.10-safe guard: datagen must be covered by the raw pyproject text.

    Runs even when tomllib is unavailable. Ensures that the on-disk package
    overwatch.datagen is accounted for either by a find include=["overwatch*"]
    pattern or by being named explicitly in an packages list.
    """
    assert "overwatch.datagen" in _discover_packages(repo_root)

    with open(os.path.join(repo_root, "pyproject.toml"), encoding="utf-8") as fh:
        text = fh.read()

    covered_by_discovery = 'include = ["overwatch*"]' in text or "overwatch*" in text
    covered_explicitly = '"overwatch.datagen"' in text
    assert covered_by_discovery or covered_explicitly, (
        "pyproject.toml must cover overwatch.datagen via find discovery "
        "(overwatch*) or by naming it explicitly"
    )
