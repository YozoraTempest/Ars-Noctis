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

    @staticmethod
    def app_host(
        *,
        current_model: str | None = None,
        current_effort: str | None = None,
        subagents: bool = True,
        efforts: list[str] | None = None,
        explicit_skills: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "schema": "ars.app-host/v1",
            "current_agent": {
                "model": current_model,
                "reasoning_effort": current_effort,
                "explicit_skills": explicit_skills
                if explicit_skills is not None
                else ["code-review"],
            },
            "subagents": {
                "available": subagents,
                "models": [
                    {
                        "id": "gpt-5.6-terra",
                        "reasoning_efforts": efforts
                        if efforts is not None
                        else ["low", "medium", "high"],
                    }
                ],
            },
        }

    def checkpoint(self, path: str, message: str) -> str:
        self.git("add", path)
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")

    def test_catalog_and_plan_adapter_freeze_only_selected_providers(self) -> None:
        catalog = adapter.discover([SKILLS_ROOT])
        self.assertEqual(
            {provider["id"] for provider in catalog["providers"]},
            {"ars", "spec", "design", "implement", "test", "code-review", "verify"},
        )
        plan = adapter.adapt_plan(self.ars_plan(), self.project, [SKILLS_ROOT])
        normalized = contracts.validate_plan(plan)
        self.assertEqual([item["kind"] for item in normalized["executors"]], ["ars"])
        snapshot = normalized["executors"][0]["snapshot"]
        self.assertEqual(snapshot["provider"]["id"], "code-review")
        self.assertEqual(snapshot["schema"], "ars.executor-snapshot/v2")
        self.assertEqual(
            snapshot["runtime"]["model"], {"value": "inherit", "source": "agent"}
        )
        self.assertEqual(
            snapshot["runtime"]["agent_mode"], {"value": "single", "source": "agent"}
        )
        self.assertEqual(normalized["tasks"][0]["requirements"], [])

    def test_app_profile_is_local_and_customizes_each_skill(self) -> None:
        initialized = adapter.init_app_profile(self.project)
        profile_path = Path(initialized["path"])
        self.assertEqual(initialized["status"], "created")
        self.assertEqual(initialized["profile"], adapter.empty_app_profile())
        self.assertTrue(profile_path.is_file())
        self.assertEqual(self.git("status", "--short"), "")

        updated = adapter.set_app_profile(
            self.project,
            "code-review",
            agent_mode="multi",
            model="gpt-5.6-terra",
            reasoning_effort="medium",
        )
        self.assertEqual(
            updated["profile"]["skills"]["code-review"],
            {
                "agent_mode": "multi",
                "model": "gpt-5.6-terra",
                "reasoning_effort": "medium",
            },
        )
        plan = adapter.adapt_plan(self.ars_plan(), self.project, [SKILLS_ROOT])
        runtime_snapshot = plan["executors"][0]["snapshot"]["runtime"]
        self.assertEqual(
            runtime_snapshot["model"],
            {"value": "gpt-5.6-terra", "source": "repository"},
        )
        self.assertEqual(
            runtime_snapshot["agent_mode"],
            {"value": "multi", "source": "repository"},
        )

    def test_app_runtime_precedence_falls_back_one_tier_at_a_time(self) -> None:
        task = {"id": "inspect", "provider": "code-review"}
        profile = adapter.validate_app_profile(
            {
                "schema": "ars.app-profile/v1",
                "skills": {"code-review": {"model": "repository-model"}},
            }
        )
        run_config = adapter.validate_app_selection(
            {
                "schema": "ars.app-run-config/v1",
                "default": {"model": "run-model"},
                "providers": {"code-review": {"model": "provider-model"}},
                "tasks": {"inspect": {"model": "task-model"}},
            },
            "ars.app-run-config/v1",
            "run config",
        )
        explicit = adapter.validate_app_selection(
            {
                "schema": "ars.app-explicit-config/v1",
                "default": {},
                "providers": {},
                "tasks": {"inspect": {"model": "explicit-model"}},
            },
            "ars.app-explicit-config/v1",
            "explicit config",
        )

        def selected_model() -> dict[str, str]:
            return adapter.resolve_app_runtime(task, profile, run_config, explicit)["model"]

        self.assertEqual(selected_model(), {"value": "explicit-model", "source": "explicit"})
        explicit["tasks"].clear()
        self.assertEqual(selected_model(), {"value": "repository-model", "source": "repository"})
        profile["skills"].clear()
        self.assertEqual(selected_model(), {"value": "task-model", "source": "task"})
        run_config["tasks"].clear()
        self.assertEqual(selected_model(), {"value": "provider-model", "source": "provider"})
        run_config["providers"].clear()
        self.assertEqual(selected_model(), {"value": "run-model", "source": "run"})
        run_config["default"].clear()
        self.assertEqual(selected_model(), {"value": "inherit", "source": "agent"})

    def test_same_provider_can_bind_single_and_multi_agent_executors(self) -> None:
        plan_value = self.ars_plan()
        second = dict(plan_value["tasks"][0])
        second["id"] = "inspect-independently"
        second["needs"] = ["inspect"]
        plan_value["tasks"].append(second)
        run_config = {
            "schema": "ars.app-run-config/v1",
            "default": {},
            "providers": {},
            "tasks": {
                "inspect": {"agent_mode": "single", "model": "inherit"},
                "inspect-independently": {
                    "agent_mode": "multi",
                    "model": "gpt-5.6-sol",
                },
            },
        }
        adapted = adapter.adapt_plan(
            plan_value,
            self.project,
            [SKILLS_ROOT],
            run_config_value=run_config,
        )
        self.assertEqual(len(adapted["executors"]), 2)
        self.assertNotEqual(
            adapted["tasks"][0]["executor"], adapted["tasks"][1]["executor"]
        )
        modes = {
            item["snapshot"]["runtime"]["agent_mode"]["value"]
            for item in adapted["executors"]
        }
        self.assertEqual(modes, {"single", "multi"})

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
        dispatch = adapter.dispatch_claim(claim, self.project, self.app_host())
        self.assertEqual(dispatch["status"], "ready")
        self.assertEqual(dispatch["mode"], "single")
        self.assertEqual(dispatch["invocation"], "$code-review")
        self.assertIsNone(dispatch["spawn"])
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

    def test_multi_dispatch_freezes_spawn_arguments_and_blocks_unavailable_host(self) -> None:
        run_config = {
            "schema": "ars.app-run-config/v1",
            "default": {},
            "providers": {},
            "tasks": {
                "inspect": {
                    "agent_mode": "multi",
                    "model": "gpt-5.6-terra",
                    "reasoning_effort": "medium",
                }
            },
        }
        generic_plan = adapter.adapt_plan(
            self.ars_plan(),
            self.project,
            [SKILLS_ROOT],
            run_config_value=run_config,
        )
        plan_path = self.write_json("multi-plan.json", generic_plan)
        run_id = str(runtime.create_run(self.project, plan_path, [], None)["run_id"])
        self.checkpoint(".noctis/runs", "test: create multi-agent Run")
        claim = runtime.claim_task(self.project, run_id, "inspect")

        ready = adapter.dispatch_claim(claim, self.project, self.app_host())
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["mode"], "multi")
        self.assertEqual(
            ready["spawn"],
            {
                "fork_turns": "none",
                "model": "gpt-5.6-terra",
                "reasoning_effort": "medium",
                "message": ready["spawn"]["message"],
            },
        )
        self.assertIn("Use $code-review", ready["spawn"]["message"])
        self.assertIn('"schema": "ars.task/v1"', ready["spawn"]["message"])

        unavailable = adapter.dispatch_claim(
            claim, self.project, self.app_host(subagents=False)
        )
        self.assertEqual(unavailable["status"], "blocked")
        self.assertIn(
            "subagents-unavailable",
            {item["code"] for item in unavailable["blockers"]},
        )
        unsupported = adapter.dispatch_claim(
            claim, self.project, self.app_host(efforts=["high"])
        )
        self.assertEqual(unsupported["status"], "blocked")
        self.assertIn(
            "reasoning-effort-unavailable",
            {item["code"] for item in unsupported["blockers"]},
        )

    def test_single_dispatch_rejects_a_model_switch(self) -> None:
        run_config = {
            "schema": "ars.app-run-config/v1",
            "default": {},
            "providers": {},
            "tasks": {
                "inspect": {
                    "agent_mode": "single",
                    "model": "gpt-5.6-terra",
                }
            },
        }
        generic_plan = adapter.adapt_plan(
            self.ars_plan(),
            self.project,
            [SKILLS_ROOT],
            run_config_value=run_config,
        )
        plan_path = self.write_json("single-plan.json", generic_plan)
        run_id = str(runtime.create_run(self.project, plan_path, [], None)["run_id"])
        self.checkpoint(".noctis/runs", "test: create single-agent Run")
        claim = runtime.claim_task(self.project, run_id, "inspect")
        blocked = adapter.dispatch_claim(
            claim,
            self.project,
            self.app_host(current_model="gpt-5.6-sol"),
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["blockers"][0]["code"], "single-model-mismatch")

        inactive = adapter.dispatch_claim(
            claim,
            self.project,
            self.app_host(
                current_model="gpt-5.6-terra",
                explicit_skills=[],
            ),
        )
        self.assertEqual(inactive["status"], "blocked")
        self.assertEqual(
            inactive["blockers"][0]["code"], "single-skill-not-explicit"
        )

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
