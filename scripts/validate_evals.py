#!/usr/bin/env python3
"""Validate repository Skill trigger-evaluation cases."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "trigger_queries.json"


def main() -> int:
    value = json.loads(CASES.read_text(encoding="utf-8"))
    if set(value) != {"version", "cases"} or value["version"] != 1:
        raise ValueError("trigger eval must contain version 1 and cases")
    skills = {
        path.name for path in (ROOT / "skills").iterdir() if (path / "SKILL.md").is_file()
    }
    seen: set[str] = set()
    counts = {skill: {True: 0, False: 0} for skill in skills}
    for index, case in enumerate(value["cases"]):
        if set(case) != {"id", "skill", "prompt", "should_trigger"}:
            raise ValueError(f"case {index} has invalid fields")
        if case["id"] in seen:
            raise ValueError(f"duplicate eval id: {case['id']}")
        seen.add(case["id"])
        if case["skill"] not in skills:
            raise ValueError(f"unknown eval skill: {case['skill']}")
        if not isinstance(case["prompt"], str) or not case["prompt"].strip():
            raise ValueError(f"case {case['id']} has an empty prompt")
        if not isinstance(case["should_trigger"], bool):
            raise ValueError(f"case {case['id']} should_trigger must be boolean")
        counts[case["skill"]][case["should_trigger"]] += 1
    incomplete = [
        skill
        for skill, result in counts.items()
        if result[True] < 2 or result[False] < 2
    ]
    if incomplete:
        raise ValueError("skills need at least two positive and negative cases: " + ", ".join(incomplete))
    print(f"Validated {len(seen)} trigger evals for {len(skills)} Skills.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
