"""
Batch B Phase 5 acceptance test — skill manifest shape.

The skill layer is text, not code, so the test is intentionally light:
we confirm the canonical workflow is present and the three required
checklists exist. Heavier end-to-end validation (skill-driven
scenario execution) is deferred to an integration CI job that has
network + LLM access.
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOT = REPO_ROOT / "skills" / "visio"
SKILL_FILE = SKILL_ROOT / "SKILL.md"
CHECKLIST_DIR = SKILL_ROOT / "checklists"


def test_skill_file_exists_and_is_nonempty():
    assert SKILL_FILE.exists(), f"Missing {SKILL_FILE}"
    content = SKILL_FILE.read_text(encoding="utf-8")
    assert len(content.strip()) > 0


def test_skill_covers_the_canonical_workflow():
    content = SKILL_FILE.read_text(encoding="utf-8").lower()
    for phase in ("recommend", "analyze", "plan", "open", "save", "render"):
        assert phase in content, f"Skill must mention workflow phase '{phase}'"


def test_skill_enforces_save_reload_rule():
    content = SKILL_FILE.read_text(encoding="utf-8")
    assert "save_requires_reload" in content.lower() or "re-open after save" in content.lower(), (
        "Skill must encode the diary 11/13 save/reload ritual, either by "
        "referencing the SAVE_REQUIRES_RELOAD error code or the 'reopen "
        "after save' rule in plain English."
    )


@pytest.mark.parametrize(
    "checklist",
    [
        "template-analysis.md",
        "save-verify.md",
        "complex-template.md",
    ],
)
def test_each_checklist_exists_and_is_nonempty(checklist: str):
    path = CHECKLIST_DIR / checklist
    assert path.exists(), f"Missing checklist {path}"
    assert path.read_text(encoding="utf-8").strip(), f"Checklist {path} is empty"
