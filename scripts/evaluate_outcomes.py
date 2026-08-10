#!/usr/bin/env python3
"""Validate and score normalized observations from fresh Skill outcome evaluations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evals" / "outcome_cases.json"
STATUSES = {"completed", "failed", "blocked", "input-required"}
CONCLUSIONS = {
    "confirmed",
    "probable",
    "not-reproduced",
    "environmental",
    "unresolved",
}
EFFECTS = {"command.execute", "git.commit", "network.write", "workspace.write"}
WORKSPACE_POLICIES = {"forbidden", "allowed", "required"}


class OutcomeEvaluationError(ValueError):
    pass


def exact_object(value: Any, fields: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise OutcomeEvaluationError(
            f"{context} must contain only: {', '.join(sorted(fields))}"
        )
    return value


def string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OutcomeEvaluationError(f"{context} must be a non-empty string")
    return value


def string_list(value: Any, context: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise OutcomeEvaluationError(f"{context} must be a list of strings")
    result = [string(item, f"{context}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise OutcomeEvaluationError(f"{context} contains duplicates")
    return result


def load_cases(path: Path, known_skills: set[str] | None = None) -> list[dict[str, Any]]:
    value = exact_object(
        json.loads(path.read_text(encoding="utf-8")), {"version", "cases"}, "cases"
    )
    if value["version"] != 1 or not isinstance(value["cases"], list):
        raise OutcomeEvaluationError("cases must use outcome evaluation version 1")
    seen: set[str] = set()
    normalized = []
    expectation_fields = {
        "statuses",
        "conclusions",
        "required_sections",
        "required_artifacts",
        "allowed_effects",
        "workspace_changes",
        "minimum_evidence",
    }
    for index, raw in enumerate(value["cases"]):
        case = exact_object(
            raw, {"id", "skill", "prompt", "workspace", "expected"}, f"cases[{index}]"
        )
        case_id = string(case["id"], f"cases[{index}].id")
        if case_id in seen:
            raise OutcomeEvaluationError(f"duplicate outcome case: {case_id}")
        seen.add(case_id)
        skill = string(case["skill"], f"cases[{index}].skill")
        if known_skills is not None and skill not in known_skills:
            raise OutcomeEvaluationError(f"unknown outcome Skill: {skill}")
        prompt = string(case["prompt"], f"cases[{index}].prompt")
        workspace = case["workspace"]
        if workspace is not None:
            workspace = string(workspace, f"cases[{index}].workspace")
            path_value = Path(workspace)
            if path_value.is_absolute() or ".." in path_value.parts:
                raise OutcomeEvaluationError(
                    f"cases[{index}].workspace must be repository-relative"
                )
            if known_skills is not None and not (ROOT / path_value).is_dir():
                raise OutcomeEvaluationError(
                    f"cases[{index}].workspace does not exist: {workspace}"
                )
        expected = exact_object(
            case["expected"], expectation_fields, f"cases[{index}].expected"
        )
        statuses = string_list(
            expected["statuses"], f"cases[{index}].expected.statuses", allow_empty=False
        )
        if not set(statuses) <= STATUSES:
            raise OutcomeEvaluationError(f"cases[{index}] contains an unknown status")
        conclusions = expected["conclusions"]
        if not isinstance(conclusions, list) or not conclusions:
            raise OutcomeEvaluationError(
                f"cases[{index}].expected.conclusions must be a non-empty list"
            )
        if any(item is not None and item not in CONCLUSIONS for item in conclusions):
            raise OutcomeEvaluationError(f"cases[{index}] contains an unknown conclusion")
        if len({json.dumps(item) for item in conclusions}) != len(conclusions):
            raise OutcomeEvaluationError(f"cases[{index}].expected.conclusions repeats values")
        required_sections = string_list(
            expected["required_sections"], f"cases[{index}].expected.required_sections"
        )
        required_artifacts = string_list(
            expected["required_artifacts"], f"cases[{index}].expected.required_artifacts"
        )
        allowed_effects = string_list(
            expected["allowed_effects"], f"cases[{index}].expected.allowed_effects"
        )
        if not set(allowed_effects) <= EFFECTS:
            raise OutcomeEvaluationError(f"cases[{index}] contains an unknown effect")
        workspace_policy = expected["workspace_changes"]
        if workspace_policy not in WORKSPACE_POLICIES:
            raise OutcomeEvaluationError(
                f"cases[{index}].expected.workspace_changes is invalid"
            )
        minimum_evidence = expected["minimum_evidence"]
        if isinstance(minimum_evidence, bool) or not isinstance(minimum_evidence, int) or minimum_evidence < 0:
            raise OutcomeEvaluationError(
                f"cases[{index}].expected.minimum_evidence must be a non-negative integer"
            )
        normalized.append(
            {
                "id": case_id,
                "skill": skill,
                "prompt": prompt,
                "workspace": workspace,
                "expected": {
                    "statuses": statuses,
                    "conclusions": conclusions,
                    "required_sections": required_sections,
                    "required_artifacts": required_artifacts,
                    "allowed_effects": allowed_effects,
                    "workspace_changes": workspace_policy,
                    "minimum_evidence": minimum_evidence,
                },
            }
        )
    if not normalized:
        raise OutcomeEvaluationError("outcome evaluation requires at least one case")
    return normalized


def load_results(path: Path) -> dict[str, dict[str, Any]]:
    value = exact_object(
        json.loads(path.read_text(encoding="utf-8")), {"version", "results"}, "results"
    )
    if value["version"] != 1 or not isinstance(value["results"], list):
        raise OutcomeEvaluationError("results must use outcome observation version 1")
    fields = {
        "id",
        "status",
        "conclusion",
        "sections",
        "artifacts",
        "effects",
        "workspace_changes",
        "evidence",
    }
    normalized: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(value["results"]):
        result = exact_object(raw, fields, f"results[{index}]")
        result_id = string(result["id"], f"results[{index}].id")
        if result_id in normalized:
            raise OutcomeEvaluationError(f"duplicate outcome result: {result_id}")
        status = result["status"]
        if status not in STATUSES:
            raise OutcomeEvaluationError(f"results[{index}].status is invalid")
        conclusion = result["conclusion"]
        if conclusion is not None and conclusion not in CONCLUSIONS:
            raise OutcomeEvaluationError(f"results[{index}].conclusion is invalid")
        normalized[result_id] = {
            "id": result_id,
            "status": status,
            "conclusion": conclusion,
            "sections": string_list(result["sections"], f"results[{index}].sections"),
            "artifacts": string_list(result["artifacts"], f"results[{index}].artifacts"),
            "effects": string_list(result["effects"], f"results[{index}].effects"),
            "workspace_changes": string_list(
                result["workspace_changes"], f"results[{index}].workspace_changes"
            ),
            "evidence": string_list(result["evidence"], f"results[{index}].evidence"),
        }
    return normalized


def score(cases: list[dict[str, Any]], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    expected_ids = {case["id"] for case in cases}
    missing = sorted(expected_ids - set(results))
    unknown = sorted(set(results) - expected_ids)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise OutcomeEvaluationError("outcome coverage mismatch; " + "; ".join(details))
    failures = []
    metrics: dict[str, dict[str, int]] = {}
    for case in cases:
        result = results[case["id"]]
        expected = case["expected"]
        reasons = []
        if result["status"] not in expected["statuses"]:
            reasons.append(f"status '{result['status']}' is not allowed")
        if result["conclusion"] not in expected["conclusions"]:
            reasons.append(f"conclusion '{result['conclusion']}' is not allowed")
        missing_sections = sorted(set(expected["required_sections"]) - set(result["sections"]))
        if missing_sections:
            reasons.append("missing sections: " + ", ".join(missing_sections))
        missing_artifacts = sorted(set(expected["required_artifacts"]) - set(result["artifacts"]))
        if missing_artifacts:
            reasons.append("missing artifacts: " + ", ".join(missing_artifacts))
        extra_effects = sorted(set(result["effects"]) - set(expected["allowed_effects"]))
        if extra_effects:
            reasons.append("unauthorized effects: " + ", ".join(extra_effects))
        policy = expected["workspace_changes"]
        if policy == "forbidden" and result["workspace_changes"]:
            reasons.append("workspace changes are forbidden")
        if policy == "required" and not result["workspace_changes"]:
            reasons.append("workspace changes are required")
        if len(result["evidence"]) < expected["minimum_evidence"]:
            reasons.append(
                f"evidence count {len(result['evidence'])} is below {expected['minimum_evidence']}"
            )
        bucket = metrics.setdefault(case["skill"], {"total": 0, "passed": 0})
        bucket["total"] += 1
        if reasons:
            failures.append({"id": case["id"], "skill": case["skill"], "reasons": reasons})
        else:
            bucket["passed"] += 1
    reported_metrics = {
        skill: {
            **bucket,
            "pass_rate": bucket["passed"] / bucket["total"],
        }
        for skill, bucket in sorted(metrics.items())
    }
    return {"metrics": reported_metrics, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--min-pass-rate", type=float, default=1.0)
    args = parser.parse_args()
    if not 0.0 <= args.min_pass_rate <= 1.0:
        parser.error("--min-pass-rate must be between 0 and 1")
    try:
        known_skills = {
            path.name
            for path in (ROOT / "skills").iterdir()
            if (path / "SKILL.md").is_file()
        }
        cases = load_cases(args.cases, known_skills if args.cases.resolve() == DEFAULT_CASES else None)
        if args.results is None:
            print(
                f"Validated {len(cases)} outcome eval cases for "
                f"{len({case['skill'] for case in cases})} Skills."
            )
            return 0
        report = score(cases, load_results(args.results))
        failed_skills = [
            skill
            for skill, metrics in report["metrics"].items()
            if metrics["pass_rate"] < args.min_pass_rate
        ]
        report.update(
            {
                "ok": not failed_skills,
                "version": 1,
                "minimumPassRate": args.min_pass_rate,
                "failedSkills": failed_skills,
            }
        )
    except (OSError, UnicodeError, json.JSONDecodeError, OutcomeEvaluationError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
