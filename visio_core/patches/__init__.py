"""
Patches for the upstream ``vsdx`` library.

Batch B (Phase 4) makes patch application **explicit**: ``apply_patches()``
is the single entry point, it is idempotent, and it reports which patches
were activated. Import-time auto-application is preserved for backward
compatibility but is now controlled by the ``VISIO_AUTO_APPLY_PATCHES``
environment variable — set it to ``"0"`` in the MCP server and the new
AgentOS entrypoint, and call ``apply_patches()`` explicitly there.

Why this matters (diary 11/12–11/13):
- The vsdx library ships a connector ``create`` that only glues one axis;
  ``vsdx_connector_patch`` fixes it. Without the patch, connectors drift.
- Connector visibility after save depends on ``connector_visibility_patch``.

Loading these submodules mutates the ``vsdx`` library at import time, so
we must make sure they are loaded exactly once, and we must be able to
prove it from tests and from the MCP server boot path.
"""
from __future__ import annotations

import os
from typing import List

_applied: bool = False
_applied_names: List[str] = []


def apply_patches(force: bool = False) -> List[str]:
    """Apply the vsdx-library patches. Safe to call repeatedly.

    Args:
        force: If True, re-import the patch submodules even if already
            applied. This is primarily a test hook; real callers should
            rely on idempotency.

    Returns:
        The list of patch module names that were activated during this
        call (empty if already applied and ``force=False``).
    """
    global _applied, _applied_names
    if _applied and not force:
        return []

    # Deferred imports — importing these modules is what actually monkey-
    # patches the upstream ``vsdx`` library. Keeping the imports inside
    # the function makes the side effect explicit and testable.
    applied_this_call: List[str] = []
    try:
        from . import vsdx_connector_patch  # noqa: F401
        applied_this_call.append("vsdx_connector_patch")
    except Exception as err:  # pragma: no cover — upstream lib shape drift
        print(f"[visio_core.patches] vsdx_connector_patch failed: {err}")

    try:
        from . import connector_visibility_patch  # noqa: F401
        applied_this_call.append("connector_visibility_patch")
    except Exception as err:  # pragma: no cover
        print(f"[visio_core.patches] connector_visibility_patch failed: {err}")

    _applied = True
    _applied_names = list(set(_applied_names + applied_this_call))
    return applied_this_call


def patches_applied() -> bool:
    """True iff ``apply_patches()`` has been called at least once."""
    return _applied


def applied_patch_names() -> List[str]:
    """Return the module names of patches that have been activated."""
    return list(_applied_names)


# Opt-in auto-apply. Legacy import-time activation is gated by the
# ``VISIO_AUTO_APPLY_PATCHES`` env var (default off). The MCP server and
# the AgentOS entrypoint call :func:`apply_patches` explicitly; tests do
# the same via ``conftest.py``.
if os.environ.get("VISIO_AUTO_APPLY_PATCHES", "0") == "1":
    apply_patches()


__all__ = [
    "apply_patches",
    "patches_applied",
    "applied_patch_names",
]
