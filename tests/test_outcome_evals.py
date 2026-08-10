from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_outcomes.py"


def load_module():
    spec = importlib.util.spec_from_file_location("evaluate_outcomes", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def case(*, workspace_changes: str = "forbidden") -> dict[str, object]:
    return {
        "id": "sample",
        "skill": "diagnose",
        "prompt": "Investigate the supplied failure.",
        "workspace": None,
        "expected": {
            "statuses": ["completed"],
            "conclusions": ["confirmed"],
            "required_sections": ["observed", "conclusion"],
            "required_artifacts": ["diagnosis.report"],
            "allowed_effects": ["command.execute"],
            "workspace_changes": workspace_changes,
            "minimum_evidence": 1,
        },
    }


def observation(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "sample",
        "status": "completed",
        "conclusion": "confirmed",
        "sections": ["observed", "conclusion"],
        "artifacts": ["diagnosis.report"],
        "effects": ["command.execute"],
        "workspace_changes": [],
        "evidence": ["command: python failing_test.py"],
    }
    value.update(overrides)
    return value


class OutcomeEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_repository_cases_validate_without_results(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=ROOT,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Validated 6 outcome eval cases", result.stdout)

    def test_score_accepts_a_complete_observation(self) -> None:
        report = self.module.score([case()], {"sample": observation()})
        self.assertEqual(report["metrics"]["diagnose"]["pass_rate"], 1.0)
        self.assertEqual(report["failures"], [])

    def test_score_reports_effect_workspace_and_evidence_violations(self) -> None:
        report = self.module.score(
            [case()],
            {
                "sample": observation(
                    effects=["command.execute", "workspace.write"],
                    workspace_changes=["changed.py"],
                    evidence=[],
                )
            },
        )
        reasons = report["failures"][0]["reasons"]
        self.assertIn("unauthorized effects: workspace.write", reasons)
        self.assertIn("workspace changes are forbidden", reasons)
        self.assertIn("evidence count 0 is below 1", reasons)

    def test_score_requires_exact_case_coverage(self) -> None:
        with self.assertRaisesRegex(
            self.module.OutcomeEvaluationError, "outcome coverage mismatch"
        ):
            self.module.score([case()], {})

    def test_cli_returns_failure_for_a_contract_violation(self) -> None:
        cases = {"version": 1, "cases": [case()]}
        results = {
            "version": 1,
            "results": [observation(workspace_changes=["unexpected.txt"])],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_path = root / "cases.json"
            result_path = root / "results.json"
            case_path.write_text(json.dumps(cases), encoding="utf-8")
            result_path.write_text(json.dumps(results), encoding="utf-8")
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--cases",
                    str(case_path),
                    "--results",
                    str(result_path),
                ],
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assertFalse(json.loads(process.stdout)["ok"])

    def test_cli_can_accept_a_measured_pass_rate_below_one(self) -> None:
        second_case = case()
        second_case["id"] = "second"
        cases = {"version": 1, "cases": [case(), second_case]}
        results = {
            "version": 1,
            "results": [
                observation(),
                observation(id="second", workspace_changes=["unexpected.txt"]),
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_path = root / "cases.json"
            result_path = root / "results.json"
            case_path.write_text(json.dumps(cases), encoding="utf-8")
            result_path.write_text(json.dumps(results), encoding="utf-8")
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--cases",
                    str(case_path),
                    "--results",
                    str(result_path),
                    "--min-pass-rate",
                    "0.5",
                ],
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
        report = json.loads(process.stdout)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(report["ok"])
        self.assertEqual(len(report["failures"]), 1)


if __name__ == "__main__":
    unittest.main()
