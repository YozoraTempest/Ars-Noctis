from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_triggers.py"


def load_module():
    spec = importlib.util.spec_from_file_location("evaluate_triggers", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TriggerEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_score_reports_per_skill_confusion_metrics(self) -> None:
        cases = [
            {"id": "p", "skill": "sample", "should_trigger": True},
            {"id": "n", "skill": "sample", "should_trigger": False},
        ]
        report = self.module.score(cases, {"p": True, "n": True})
        self.assertEqual(report["metrics"]["sample"]["tp"], 1)
        self.assertEqual(report["metrics"]["sample"]["fp"], 1)
        self.assertEqual(report["metrics"]["sample"]["precision"], 0.5)
        self.assertEqual(report["failures"][0]["id"], "n")

    def test_cli_accepts_complete_predictions_and_rejects_low_metrics(self) -> None:
        cases = {
            "version": 1,
            "cases": [
                {"id": "p", "skill": "sample", "prompt": "use it", "should_trigger": True},
                {"id": "n", "skill": "sample", "prompt": "do not", "should_trigger": False},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_path = root / "cases.json"
            prediction_path = root / "predictions.json"
            case_path.write_text(json.dumps(cases), encoding="utf-8")
            prediction_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "predictions": [
                            {"id": "p", "trigger": True},
                            {"id": "n", "trigger": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--cases",
                    str(case_path),
                    "--predictions",
                    str(prediction_path),
                ],
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["failedSkills"], ["sample"])

    def test_evaluator_protocol_runs_one_fresh_request_per_case(self) -> None:
        cases = {
            "version": 1,
            "cases": [
                {"id": "p", "skill": "sample", "prompt": "use it", "should_trigger": True},
                {"id": "n", "skill": "sample", "prompt": "skip it", "should_trigger": False},
            ],
        }
        evaluator_source = """import json, sys
request = json.load(sys.stdin)
print(json.dumps({\"trigger\": request[\"id\"] == \"p\"}))
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_path = root / "cases.json"
            evaluator = root / "evaluator.py"
            case_path.write_text(json.dumps(cases), encoding="utf-8")
            evaluator.write_text(evaluator_source, encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--cases",
                    str(case_path),
                    "--evaluator",
                    str(evaluator),
                ],
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
