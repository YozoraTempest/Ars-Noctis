from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SKILL_ROOT.parents[1]
SKILLS_ROOT = REPOSITORY_ROOT / "skills"
ARS_SCRIPT_ROOT = SKILL_ROOT / "scripts"
NOCTIS_SCRIPT_ROOT = SKILLS_ROOT / "noctis" / "scripts"
sys.path.insert(0, str(ARS_SCRIPT_ROOT))
sys.path.insert(0, str(NOCTIS_SCRIPT_ROOT))

import ars_noctis as adapter  # noqa: E402
from noctislib import contracts, runtime  # noqa: E402


class ArsNoctisAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        self.project.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.email", "adapter@example.test")
        self.git("config", "user.name", "Adapter Test")
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
        path = Path(self.temporary.name) / "fixtures" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    @staticmethod
    def ars_plan(provider: str = "code-review", capability: str = "code.review") -> dict[str, object]:
        return {
            "schema": "ars.plan/v1",
            "title": "Adapter test",
            "objective": "Exercise the Ars adapter boundary.",
            "workspaces": [{"id": "main", "root": "."}],
            "tasks": [
                {
                    "id": "inspect",
                    "provider": provider,
                    "capability": capability,
                    "workspace": "main",
                    "needs": [],
                    "instructions": "Inspect the supplied repository state.",
                    "inputs": [],
                    "acceptance": ["Return one evidence-backed result"],
                    "effects": [],
                }
            ],
        }

    def checkpoint(self, path: str, message: str) -> str:
        self.git("add", path)
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")

    def test_catalog_and_plan_adapter_freeze_only_selected_providers(self) -> None:
        catalog = adapter.discover([SKILLS_ROOT])
        self.assertEqual(
            {provider["id"] for provider in catalog["providers"]},
            {"ars", "implement", "code-review", "verify"},
        )
        plan = adapter.adapt_plan(self.ars_plan(), self.project, [SKILLS_ROOT])
        normalized = contracts.validate_plan(plan)
        self.assertEqual([item["kind"] for item in normalized["executors"]], ["ars"])
        snapshot = normalized["executors"][0]["snapshot"]
        self.assertEqual(snapshot["provider"]["id"], "code-review")
        self.assertEqual(normalized["tasks"][0]["requirements"], [])

    def test_extension_can_introduce_a_provider_during_a_run(self) -> None:
        extension = json.loads(
            (SKILL_ROOT / "assets" / "noctis-extension.example.json").read_text(
                encoding="utf-8"
            )
        )
        adapted = adapter.adapt_extension(extension, self.project, [SKILLS_ROOT])
        self.assertEqual(adapted["schema"], "noctis.extension/v1")
        self.assertEqual(adapted["executors"][0]["snapshot"]["provider"]["id"], "verify")
        self.assertEqual(adapted["tasks"][0]["requirements"], ["command.execute"])

    def test_claim_and_result_round_trip_through_noctis(self) -> None:
        generic_plan = adapter.adapt_plan(self.ars_plan(), self.project, [SKILLS_ROOT])
        plan_path = self.write_json("adapted-plan.json", generic_plan)
        run_id = str(runtime.create_run(self.project, plan_path, [], None)["run_id"])
        self.checkpoint(".noctis/runs", "test: create adapted Run")

        claim = runtime.claim_task(self.project, run_id, "inspect")
        ars_task = adapter.adapt_claim(claim, self.project)
        self.assertEqual(ars_task["schema"], "ars.task/v1")
        self.assertEqual(ars_task["provider"]["id"], "code-review")
        ars_result = {
            "schema": "ars.result/v1",
            "run_id": run_id,
            "task_id": "inspect",
            "claim_id": claim["claim_id"],
            "attempt": claim["attempt"],
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
        }
        generic_result = adapter.adapt_result(claim, ars_result, self.project)
        self.assertEqual(generic_result["output"], ars_result)
        result_path = self.write_json("adapted-result.json", generic_result)
        finished = runtime.finish_task(
            self.project,
            run_id,
            "inspect",
            str(claim["claim_id"]),
            int(claim["revision"]),
            result_path,
        )
        self.assertEqual(finished["run_status"], "completed")

    def test_legacy_run_requires_explicit_migration(self) -> None:
        run_id = str(uuid.uuid4())
        created_from = self.git("rev-parse", "HEAD")
        source = self.project / ".ars" / "runs" / run_id
        source.mkdir(parents=True)
        legacy_plan = self.ars_plan()
        catalog = adapter.discover([SKILLS_ROOT])
        selected = next(item for item in catalog["providers"] if item["id"] == "code-review")
        catalog_snapshot = {
            "schema": "ars.catalog/v1",
            "providers": [
                {
                    "id": selected["id"],
                    "version": selected["version"],
                    "capabilities": selected["capabilities"],
                }
            ],
        }
        record = {
            "schema": "ars.run-record/v1",
            "id": run_id,
            "plan": "plan.json",
            "catalog": catalog_snapshot,
            "initial_grants": [],
            "grant_reason": None,
            "created_at": "2026-08-09T00:00:00+00:00",
            "created_from": created_from,
            "durable_ref": "refs/heads/main",
        }
        (source / "plan.json").write_text(json.dumps(legacy_plan), encoding="utf-8")
        (source / "run.json").write_text(json.dumps(record), encoding="utf-8")
        self.checkpoint(".ars/runs", "test: add legacy Run")

        self.assertEqual(runtime.show_run(self.project, None)["runs"], [])
        migrated = adapter.migrate_run(self.project, run_id)
        expected_target = (self.project / ".noctis" / "runs" / run_id).resolve()
        self.assertEqual(migrated["target"], str(expected_target))
        self.checkpoint(".noctis/runs", "test: migrate legacy Run")
        view = runtime.show_run(self.project, run_id)
        self.assertEqual(view["status"], "submitted")
        self.assertTrue(view["tasks"][0]["executor"].startswith("ars:code-review:"))
        self.assertEqual(view["executors"][0]["kind"], "ars")

    def test_failed_legacy_migration_does_not_publish_partial_run(self) -> None:
        run_id = str(uuid.uuid4())
        source = self.project / ".ars" / "runs" / run_id
        (source / "events").mkdir(parents=True)
        catalog = adapter.discover([SKILLS_ROOT])
        selected = next(item for item in catalog["providers"] if item["id"] == "code-review")
        record = {
            "schema": "ars.run-record/v1",
            "id": run_id,
            "plan": "plan.json",
            "catalog": {
                "schema": "ars.catalog/v1",
                "providers": [
                    {
                        "id": selected["id"],
                        "version": selected["version"],
                        "capabilities": selected["capabilities"],
                    }
                ],
            },
            "initial_grants": [],
            "grant_reason": None,
            "created_at": "2026-08-09T00:00:00+00:00",
            "created_from": self.git("rev-parse", "HEAD"),
            "durable_ref": "refs/heads/main",
        }
        (source / "plan.json").write_text(json.dumps(self.ars_plan()), encoding="utf-8")
        (source / "run.json").write_text(json.dumps(record), encoding="utf-8")
        event_id = str(uuid.uuid4())
        invalid_event = {
            "schema": "ars.event/v1",
            "id": event_id,
            "run_id": run_id,
            "task_id": "inspect",
            "type": "task.unknown",
            "previous_revision": 0,
            "revision": 1,
            "created_at": "2026-08-09T00:00:01+00:00",
            "data": {},
        }
        (source / "events" / f"{event_id}.json").write_text(
            json.dumps(invalid_event), encoding="utf-8"
        )
        with self.assertRaisesRegex(adapter.AdapterError, "unsupported legacy event"):
            adapter.migrate_run(self.project, run_id)
        self.assertFalse((self.project / ".noctis" / "runs" / run_id).exists())

        with self.assertRaisesRegex(adapter.AdapterError, "must be a UUID"):
            adapter.migrate_run(self.project, "../outside")


if __name__ == "__main__":
    unittest.main()
