from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SKILL_ROOT.parents[1]
SKILLS_ROOT = REPOSITORY_ROOT / "skills"
ARS_SCRIPT_ROOT = SKILL_ROOT / "scripts"
NOCTIS_CLI = SKILLS_ROOT / "noctis" / "scripts" / "noctis.py"
sys.path.insert(0, str(ARS_SCRIPT_ROOT))

import ars_host as host  # noqa: E402


class ArsHostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.email", "host@example.test")
        self.git("config", "user.name", "Host Test")
        (self.project / "base.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "base.txt")
        self.git("commit", "-m", "test: initialize repository")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, *arguments: str) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.project,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def write_json(self, name: str, value: object) -> Path:
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_create_next_finish_uses_public_noctis_cli_and_local_claim_cache(self) -> None:
        plan_path = self.write_json(
            "plan.json",
            {
                "schema": "ars.plan/v1",
                "title": "Host test",
                "objective": "Exercise the compact host lifecycle.",
                "workspaces": [{"id": "main", "root": "."}],
                "tasks": [
                    {
                        "id": "inspect",
                        "provider": "code-review",
                        "capability": "code.review",
                        "workspace": "main",
                        "needs": [],
                        "instructions": "Inspect the repository.",
                        "inputs": [],
                        "acceptance": ["Return a review report"],
                        "effects": [],
                    }
                ],
            },
        )
        app_host_path = self.write_json(
            "host.json",
            {
                "schema": "ars.app-host/v1",
                "current_agent": {
                    "model": None,
                    "reasoning_effort": None,
                    "explicit_skills": ["code-review"],
                },
                "subagents": {"available": False, "models": []},
            },
        )
        created = host.create_run(
            project=self.project,
            plan_path=plan_path,
            skills_roots=[SKILLS_ROOT],
            noctis=NOCTIS_CLI,
        )
        self.assertEqual(created["schema"], "ars.host-create/v1")
        self.assertEqual(created["ready"], ["inspect"])
        run_id = created["run_id"]
        self.git("add", ".noctis/runs")
        self.git("commit", "-m", "test: checkpoint host run")

        dispatch = host.next_task(
            project=self.project,
            run_id=run_id,
            host_path=app_host_path,
            noctis=NOCTIS_CLI,
        )
        self.assertEqual(dispatch["schema"], "ars.app-dispatch/v1")
        self.assertEqual(dispatch["status"], "ready")
        self.assertEqual(dispatch["task"]["task_id"], "inspect")
        self.assertNotIn("dependencies", dispatch)
        claim_id = dispatch["task"]["claim_id"]
        cache_path = host.claim_cache_path(self.project, claim_id)
        self.assertTrue(cache_path.is_file())
        self.assertEqual(self.git("status", "--short"), "")

        result_path = self.write_json(
            "result.json",
            {
                "schema": "ars.result/v1",
                "run_id": run_id,
                "task_id": "inspect",
                "claim_id": claim_id,
                "attempt": dispatch["task"]["attempt"],
                "status": "completed",
                "summary": "Inspection completed.",
                "artifacts": [
                    {
                        "id": "report",
                        "type": "review.report",
                        "media_type": "application/json",
                        "locator": {"kind": "inline", "value": {"findings": []}},
                        "digest": None,
                    }
                ],
                "evidence": [],
                "effects": [],
            },
        )
        finished = host.finish_task(
            project=self.project,
            result_path=result_path,
            noctis=NOCTIS_CLI,
        )
        self.assertEqual(finished["schema"], "ars.host-finish/v1")
        self.assertEqual(finished["run_status"], "completed")
        self.assertFalse(cache_path.exists())
        self.assertEqual(len(finished["checkpoint_required"]), 2)

    def test_finish_preserves_cache_when_result_is_invalid(self) -> None:
        claim_id = "00000000-0000-4000-8000-000000000001"
        cache_path = host.claim_cache_path(self.project, claim_id)
        host.adapter.atomic_write_json(cache_path, {"claim_id": claim_id})
        result_path = self.write_json(
            "invalid-result.json",
            {"schema": "ars.result/v1", "claim_id": claim_id},
        )

        with self.assertRaises(host.adapter.AdapterError):
            host.finish_task(
                project=self.project,
                result_path=result_path,
                noctis=NOCTIS_CLI,
            )
        self.assertTrue(cache_path.is_file())


if __name__ == "__main__":
    unittest.main()
