"""
Batch B Phase 4 acceptance test — explicit patch application.

The diary 11/12–11/13 lessons depend on ``vsdx_connector_patch`` and
``connector_visibility_patch`` being active. Batch B makes the activation
path explicit (``apply_patches()``) rather than a silent import side
effect. This test guards that the explicit call is idempotent, reports
the patches it activated, and survives being called twice.
"""
from __future__ import annotations

import pytest


def test_apply_patches_is_idempotent_and_reports_names():
    from visio_core.patches import (
        apply_patches,
        patches_applied,
        applied_patch_names,
    )

    apply_patches()
    assert patches_applied() is True
    names = applied_patch_names()
    assert "vsdx_connector_patch" in names, (
        "The connector patch must activate on apply_patches(); "
        f"applied set was {names}"
    )
    assert "connector_visibility_patch" in names, (
        "The visibility patch must activate on apply_patches(); "
        f"applied set was {names}"
    )

    # Second call must be a no-op by contract.
    second = apply_patches()
    assert second == [], (
        "apply_patches() must be idempotent on repeated calls without "
        f"force=True; got {second}"
    )


def test_apply_patches_force_re_applies_without_error():
    from visio_core.patches import apply_patches
    # force=True must not raise even when the patches are already active.
    result = apply_patches(force=True)
    # The result list contains the modules re-imported this call. The
    # subset relation is what matters, not exact equality.
    assert set(result) <= {"vsdx_connector_patch", "connector_visibility_patch"}


def test_patches_package_exposes_canonical_api():
    from visio_core import patches

    for symbol in ("apply_patches", "patches_applied", "applied_patch_names"):
        assert hasattr(patches, symbol), f"patches.{symbol} missing after Batch B"
