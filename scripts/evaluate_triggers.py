#!/usr/bin/env python3
"""Run Skill trigger predictions and enforce precision/recall thresholds."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evals" / "trigger_queries.json"


class EvaluationError(ValueError):
    pass


def load_cases(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    cases = value.get("cases") if isinstance(value, dict) else None
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(cases, list):
        raise EvaluationError("cases must use trigger evaluation version 1")
    return cases


def load_predictions(path: Path) -> dict[str, bool]:
    value = json.loads(path.read_text(encoding="utf-8"))
    predictions = value.get("predictions") if isinstance(value, dict) else None
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(predictions, list):
        raise EvaluationError("predictions must use trigger prediction version 1")
    result: dict[str, bool] = {}
    for prediction in predictions:
        if not isinstance(prediction, dict) or set(prediction) != {"id", "trigger"}:
            raise EvaluationError("each prediction requires only id and trigger")
        if prediction["id"] in result:
            raise EvaluationError(f"duplicate prediction: {prediction['id']}")
        if not isinstance(prediction["trigger"], bool):
            raise EvaluationError(f"prediction {prediction['id']} is not boolean")
        result[prediction["id"]] = prediction["trigger"]
    return result


def run_evaluator(path: Path, cases: list[dict[str, Any]]) -> dict[str, bool]:
    command = [str(path)]
    if path.suffix.lower() == ".py":
        command.insert(0, sys.executable)
    predictions: dict[str, bool] = {}
    for case in cases:
        request = {
            "version": 1,
            "id": case["id"],
            "skill": case["skill"],
            "prompt": case["prompt"],
        }
        result = subprocess.run(
            command,
            input=json.dumps(request, ensure_ascii=False),
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise EvaluationError(
                f"evaluator failed for {case['id']}: "
                + (result.stderr.strip() or f"exit {result.returncode}")
            )
        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise EvaluationError(
                f"evaluator returned invalid JSON for {case['id']}"
            ) from error
        if not isinstance(response, dict) or set(response) != {"trigger"}:
            raise EvaluationError(
                f"evaluator response for {case['id']} must contain only trigger"
            )
        if not isinstance(response["trigger"], bool):
            raise EvaluationError(
                f"evaluator trigger for {case['id']} must be boolean"
            )
        predictions[case["id"]] = response["trigger"]
    return predictions


def score(
    cases: list[dict[str, Any]], predictions: dict[str, bool]
) -> dict[str, Any]:
    expected_ids = {case["id"] for case in cases}
    missing = sorted(expected_ids - set(predictions))
    unknown = sorted(set(predictions) - expected_ids)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise EvaluationError("prediction coverage mismatch; " + "; ".join(details))
    counts: dict[str, dict[str, int]] = {}
    failures = []
    for case in cases:
        skill = case["skill"]
        bucket = counts.setdefault(skill, {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
        expected = case["should_trigger"]
        actual = predictions[case["id"]]
        key = "tp" if expected and actual else "fn" if expected else "fp" if actual else "tn"
        bucket[key] += 1
        if expected != actual:
            failures.append(
                {"id": case["id"], "skill": skill, "expected": expected, "actual": actual}
            )
    metrics = {}
    for skill, bucket in sorted(counts.items()):
        predicted_positive = bucket["tp"] + bucket["fp"]
        actual_positive = bucket["tp"] + bucket["fn"]
        total = sum(bucket.values())
        metrics[skill] = {
            **bucket,
            "precision": bucket["tp"] / predicted_positive if predicted_positive else 0.0,
            "recall": bucket["tp"] / actual_positive if actual_positive else 0.0,
            "accuracy": (bucket["tp"] + bucket["tn"]) / total,
        }
    return {"metrics": metrics, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--predictions", type=Path)
    source.add_argument("--evaluator", type=Path)
    parser.add_argument("--min-precision", type=float, default=0.8)
    parser.add_argument("--min-recall", type=float, default=0.8)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        cases = load_cases(args.cases)
        predictions = (
            load_predictions(args.predictions)
            if args.predictions is not None
            else run_evaluator(args.evaluator, cases)
        )
        report = score(cases, predictions)
        failed_skills = [
            skill
            for skill, metrics in report["metrics"].items()
            if metrics["precision"] < args.min_precision
            or metrics["recall"] < args.min_recall
        ]
        report.update(
            {
                "ok": not failed_skills,
                "version": 1,
                "thresholds": {
                    "precision": args.min_precision,
                    "recall": args.min_recall,
                },
                "failedSkills": failed_skills,
            }
        )
    except (OSError, UnicodeError, json.JSONDecodeError, EvaluationError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 2
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
