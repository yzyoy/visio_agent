"""Reproducible demonstration that ``recommend_template`` is now stable.

Run::

    python -m tools-offline.demo_recommend_stability
    # or, equivalently:
    python tools-offline/demo_recommend_stability.py

What it does
------------
Drives :func:`PromptTools.recommend_template` against an *intentionally
non-deterministic* stub LLM (``JitteringSemanticModel``) that swaps the
order of its top two recommendations on alternating calls. Without the
fixes in this PR the public payload would also flip on every other call.
With the fixes, the payload is byte-identical across runs because:

1. ``SmartMatcher`` forces ``temperature=0`` / fixed seed for the duration
   of every recommendation call (the LLM is asked greedily).
2. Every internal sort step uses a deterministic tiebreaker — score first,
   filename second — so equal scores can never flip silently.
3. The LLM score is blended with the structural ``combined_score`` to
   dampen the rare cases where the LLM does emit different scores.
4. A small in-memory LRU memoizes the *normalized* requirement so repeat
   calls within a session are served from cache.

The script prints a small summary and exits non-zero if the
recommendations ever diverge between runs, so it doubles as a smoke
test that can be wired into CI.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Make the repo importable when executed as a plain script (the package
# layout uses a hyphen so ``python -m tools-offline.demo_recommend_stability``
# works, but ``python tools-offline/demo_recommend_stability.py`` is friendlier
# for ad-hoc use).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from visio_core.tools.prompt_tools import PromptTools  # noqa: E402


class JitteringSemanticModel:
    """Stub LLM that intentionally swaps its top two picks every other call."""

    def __init__(self) -> None:
        self.temperature: float = 1.0
        self.top_p: float = 1.0
        self.seed: int | None = None
        self._eval_calls = 0

    def complete(self, prompt: str) -> str:
        if "用户需求描述：" in prompt:
            return json.dumps(
                {
                    "keywords": "flowchart, process, workflow",
                    "chart_type": "flowchart",
                    "complexity": "medium",
                    "estimated_shapes": "8-12",
                    "architecture_pattern": "linear workflow",
                    "specific_requirements": ["show sequential steps"],
                    "topology_type": "linear_chain",
                    "layout_direction": "vertical",
                    "connection_type": "sequential",
                },
                ensure_ascii=False,
            )

        if "候选模板列表" in prompt:
            self._eval_calls += 1
            candidates = self._extract_candidates(prompt)
            if not candidates:
                return json.dumps({"recommendations": []}, ensure_ascii=False)

            top = candidates[: min(3, len(candidates))]
            # Inject jitter: rotate the top two on every other call.
            if len(top) >= 2 and self._eval_calls % 2 == 0:
                top[0], top[1] = top[1], top[0]

            recs: List[Dict[str, Any]] = []
            for idx, (filename, template_path) in enumerate(top):
                # Tied scores expose the tiebreaker logic.
                recs.append(
                    {
                        "filename": filename,
                        "template_path": template_path,
                        "llm_score": 9.0,
                        "dimension_scores": {
                            "topology": 2,
                            "layout": 2,
                            "scale": 1.5,
                            "connections": 2,
                            "extensibility": 1.5,
                        },
                        "template_shapes_count": 12,
                        "structure_description": "Stable linear flow.",
                    }
                )
            return json.dumps({"recommendations": recs}, ensure_ascii=False)

        raise AssertionError(f"Unexpected prompt: {prompt[:200]}")

    @staticmethod
    def _extract_candidates(prompt: str) -> List[Tuple[str, str]]:
        pattern = re.compile(
            r"文件名:\s*(?P<filename>[^\n]+)\n\s*完整路径:\s*(?P<path>[^\n]+)"
        )
        return [
            (m.group("filename").strip(), m.group("path").strip())
            for m in pattern.finditer(prompt)
        ]


def _summarize(payload: Dict[str, Any]) -> List[Tuple[int, str, float]]:
    return [
        (rec["rank"], rec["filename"], rec["score"])
        for rec in payload.get("recommendations", [])
    ]


def main() -> int:
    requirement = "推荐一个流程图模板"
    top_k = 3
    runs = 5

    tools = PromptTools(template_dir="assets/templates")
    model = JitteringSemanticModel()
    tools.set_model(model)
    tools.smart_matcher.clear_recommendation_cache()

    print(f"=== recommend_template stability demo ===")
    print(f"requirement : {requirement!r}")
    print(f"top_k       : {top_k}")
    print(f"runs        : {runs}")
    print(
        f"model       : JitteringSemanticModel "
        f"(intentionally swaps top-2 every other call)\n"
    )

    payloads: List[Dict[str, Any]] = []
    for i in range(1, runs + 1):
        payload = json.loads(tools.recommend_template(requirement, top_k=top_k))
        payloads.append(payload)
        summary = _summarize(payload)
        print(f"run {i}: {summary}")

    print()
    print(f"LLM evaluations issued: {model._eval_calls} "
          f"(expected 1 — the rest hit the recommendation cache)")
    print(f"Final model.temperature: {model.temperature} (expected 0.0)")
    print(f"Final model.seed       : {model.seed} (expected 42)")

    first_recs = payloads[0]["recommendations"]
    all_match = all(p["recommendations"] == first_recs for p in payloads[1:])

    print()
    if all_match and first_recs:
        print("[OK] All runs produced identical recommendation lists.")
        return 0
    if not first_recs:
        print("[FAIL] No recommendations were produced.")
        return 2
    print("[FAIL] Recommendation lists diverged across runs.")
    for idx, payload in enumerate(payloads, 1):
        print(f"  run {idx}: {_summarize(payload)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
