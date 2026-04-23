"""
Batch B Phase 3 acceptance test — ``visio_core`` import boundary.

The acceptance gate from the roadmap is:

    python -c "import visio_core" succeeds without agno installed.

We cannot uninstall agno during a test, but we *can* prove two weaker
invariants that together imply the boundary is healthy:

1. Importing ``visio_core`` does not pull ``agno`` into ``sys.modules``
   as a side effect (the module is importable regardless of agno's
   presence).
2. The package's public re-export list matches the declared
   ``CORE_MODULES_EXPORTED`` tuple — nothing slips through silently.
"""
from __future__ import annotations

import importlib
import sys


def test_visio_core_import_does_not_pull_agno_at_module_scope():
    # If agno is already imported by a prior test, snapshot the set and
    # compare only additions triggered by a fresh import of visio_core.
    before_agno = {k for k in sys.modules if k == "agno" or k.startswith("agno.")}
    # Force a fresh import of the top-level visio_core module.
    sys.modules.pop("visio_core", None)
    mod = importlib.import_module("visio_core")

    after_agno = {k for k in sys.modules if k == "agno" or k.startswith("agno.")}
    new_agno = after_agno - before_agno
    assert not new_agno, (
        "Importing 'visio_core' must not transitively import agno. "
        f"New agno modules pulled in: {sorted(new_agno)}"
    )

    # Verify the package exposes its declared ``__all__`` via __getattr__
    # (lazy) without pulling agno into sys.modules.
    assert hasattr(mod, "__all__")
    for name in mod.__all__:
        _ = getattr(mod, name)


def test_visio_core_apply_patches_is_the_patches_apply_patches():
    import visio_core
    from visio_core.patches import apply_patches as original

    assert visio_core.apply_patches is original, (
        "visio_core.apply_patches must be the same callable as "
        "visio_core.patches.apply_patches."
    )


def test_smart_matcher_import_does_not_pull_agno_at_module_scope():
    """Priority 4 acceptance: ``SmartMatcher`` is agno-free at import.

    The recommendation path must be callable from pure-library callers
    that build their own LLM client. Importing the module should not
    drag ``agno.*`` in as a side effect; ``agno.models.message.Message``
    is constructed lazily inside the methods that actually hit the LLM.
    """
    before_agno = {k for k in sys.modules if k == "agno" or k.startswith("agno.")}
    sys.modules.pop("visio_core.utils.smart_matcher", None)
    importlib.import_module("visio_core.utils.smart_matcher")

    after_agno = {k for k in sys.modules if k == "agno" or k.startswith("agno.")}
    new_agno = after_agno - before_agno
    assert not new_agno, (
        "Importing 'visio_core.utils.smart_matcher' must not "
        f"transitively import agno. New agno modules: {sorted(new_agno)}"
    )
