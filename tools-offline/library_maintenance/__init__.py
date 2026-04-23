"""Offline library maintenance utilities (Batch A Phase 3).

Scripts here are **not** exposed to the LLM. They are used by a human
operator to keep the template/stencil library trustworthy and to
regenerate the lite+full indexes after pruning.

Destructive operations always run through a manifest step first, so that
a reviewer can inspect exactly which files would be removed before
anything is touched on disk.
"""
