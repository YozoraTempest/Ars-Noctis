from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SKILL_ROOT.parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "noctis.py"
SKILLS_ROOT = REPOSITORY_ROOT / "skills"


def load_module():
    spec = importlib.util.spec_from_file_location("noctis_runtime_entry", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NoctisRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.noctis = load_module()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        self.project.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.email", "noctis@example.test")
        self.git("config", "user.name", "Noctis Test")
        (self.project / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
        (self.project / "base.txt").write_text("base\n", encoding="utf-8")
        self.git("add", ".gitignore", "base.txt")
        self.git("commit", "-m", "test: initialize repository")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, *arguments: str, cwd: Path | None = None) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd or self.project,
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

    def run_cli(self, *arguments: str, cwd: Path | None = None) -> dict[str, object]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=cwd or self.project,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def task(
        self,
        task_id: str,
        provider: str,
        capability: str,
        *,
        needs: list[str] | None = None,
        effects: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "id": task_id,
            "provider": provider,
            "capability": capability,
            "workspace": "main",
            "needs": needs or [],
            "instructions": f"Execute {task_id}.",
            "inputs": [],
            "acceptance": [f"{task_id} has observable evidence"],
            "effects": effects or [],
        }

    def plan(self, tasks: list[dict[str, object]]) -> dict[str, object]:
        return {
            "schema": "ars.plan/v1",
            "title": "Test run",
            "objective": "Exercise the public runtime contract.",
            "workspaces": [{"id": "main", "root": "."}],
            "tasks": tasks,
        }

    def result(
        self,
        claim: dict[str, object],
        *,
        status: str = "completed",
        effects: list[dict[str, str]] | None = None,
        locator: dict[str, object] | None = None,
    ) -> dict[str, object]:
        artifact = {
            "id": "result",
            "type": "test.result",
            "media_type": "application/json",
            "locator": locator or {"kind": "inline", "value": {"ok": True}},
            "digest": None,
        }
        return {
            "schema": "ars.result/v1",
            "run_id": claim["run_id"],
            "task_id": claim["task_id"],
            "claim_id": claim["claim_id"],
            "attempt": claim["attempt"],
            "status": status,
            "summary": "Task produced verified output.",
            "artifacts": [artifact] if status == "completed" else [],
            "evidence": [],
            "effects": effects or [],
        }

    def create(self, plan: dict[str, object], grants: list[str] | None = None) -> str:
        plan_path = self.write_json("plan.json", plan)
        supplied = grants or []
        created = self.noctis.create_run(
            self.project,
            plan_path,
            [SKILLS_ROOT],
            supplied,
            "test authorization" if supplied else None,
            bool(set(supplied) & self.noctis.HIGH_RISK_EFFECTS),
        )
        return created["run_id"]

    def checkpoint(self, message: str = "test: checkpoint Noctis state") -> str:
        self.git("add", ".ars/runs")
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")

    def commit_implementation(self) -> str:
        (self.project / "implementation.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "implementation.txt")
        self.git("commit", "-m", "test: implement change")
        return self.git("rev-parse", "HEAD")

    def commit_effects(self, claim: dict[str, object], commit: str) -> list[dict[str, str]]:
        return [
            {
                "type": "workspace.write",
                "target": "main",
                "receipt": "implementation.txt",
                "idempotency_key": str(claim["idempotency_key"]),
            },
            {
                "type": "git.commit",
                "target": "main",
                "receipt": commit,
                "idempotency_key": str(claim["idempotency_key"]),
            },
        ]

    def test_catalog_discovers_only_explicit_manifests(self) -> None:
        catalog = self.noctis.discover([SKILLS_ROOT])
        self.assertEqual(
            {provider["id"] for provider in catalog["providers"]},
            {"ars", "implement", "code-review", "verify"},
        )

    def test_cli_runs_a_complete_single_task_lifecycle(self) -> None:
        plan_path = self.write_json(
            "plan.json",
            self.plan([self.task("review", "code-review", "code.review")]),
        )
        created = self.run_cli(
            "run-create",
            "--project",
            str(self.project),
            "--plan",
            str(plan_path),
            "--skills-root",
            str(SKILLS_ROOT),
        )
        self.checkpoint()
        claim = self.run_cli(
            "task-claim",
            "--project",
            str(self.project),
            "--run-id",
            str(created["run_id"]),
        )
        result_path = self.write_json("result.json", self.result(claim))
        finished = self.run_cli(
            "task-finish",
            "--project",
            str(self.project),
            "--run-id",
            str(created["run_id"]),
            "--task-id",
            str(claim["task_id"]),
            "--claim-id",
            str(claim["claim_id"]),
            "--expected-revision",
            str(claim["revision"]),
            "--result",
            str(result_path),
        )
        self.assertEqual(finished["run_status"], "completed")
        self.assertFalse(finished["checkpoint"]["committed"])
        self.checkpoint()
        self.assertTrue(self.noctis.show_run(self.project, str(created["run_id"]))["checkpoint"]["committed"])

    def test_duplicate_provider_ids_are_rejected_instead_of_using_path_order(self) -> None:
        root = Path(self.temporary.name) / "skills"
        for name in ("one", "two"):
            directory = root / name
            directory.mkdir(parents=True)
            (directory / "ars.json").write_text(
                (SKILLS_ROOT / "implement" / "ars.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        with self.assertRaisesRegex(self.noctis.NoctisError, "ambiguous"):
            self.noctis.discover([root])

    def test_recover_discards_local_claim_and_authorization(self) -> None:
        run_id = self.create(
            self.plan([self.task("review", "code-review", "code.review")])
        )
        self.checkpoint()
        self.noctis.claim_task(self.project, run_id, "review")
        self.assertEqual(self.noctis.show_run(self.project, run_id)["status"], "working")
        recovered = self.noctis.recover(self.project, run_id)
        self.assertEqual(recovered["runs"][0]["ready"], ["review"])
        self.assertEqual(recovered["active_grants"], [])
        cache = Path(self.noctis.cache_path(self.project))
        self.assertTrue(cache.is_file())
        git_directory = Path(self.git("rev-parse", "--absolute-git-dir")).resolve()
        self.assertEqual(cache.parent.parent, git_directory)

    def test_claim_requires_checkpoint_and_invalid_recovery_preserves_local_claim(self) -> None:
        run_id = self.create(
            self.plan([self.task("review", "code-review", "code.review")])
        )
        with self.assertRaisesRegex(self.noctis.NoctisError, "not committed"):
            self.noctis.claim_task(self.project, run_id, "review")
        self.checkpoint()
        claim = self.noctis.claim_task(self.project, run_id, "review")
        event_id = "00000000-0000-4000-8000-000000000001"
        event_path = (
            self.project / ".ars" / "runs" / run_id / "events" / f"{event_id}.json"
        )
        event_path.parent.mkdir(parents=True)
        event_path.write_text('{"schema":"broken"}\n', encoding="utf-8")
        with self.assertRaises(self.noctis.NoctisError):
            self.noctis.recover(self.project, run_id)
        retained = self.noctis.local_claim(self.project, run_id, "review")
        self.assertIsNotNone(retained)
        self.assertEqual(retained["claim_id"], claim["claim_id"])

    def test_replay_rejects_two_events_for_the_same_task_revision(self) -> None:
        run_id = self.create(
            self.plan([self.task("review", "code-review", "code.review")])
        )
        self.checkpoint()
        for reason in ("first", "second"):
            event = self.noctis.new_event(
                run_id,
                "review",
                "task.canceled",
                0,
                {
                    "attempt": 0,
                    "reason": reason,
                    "acknowledged_effects": False,
                    "cascade_from": None,
                },
            )
            self.noctis.append_event(self.project, event)
        with self.assertRaisesRegex(self.noctis.NoctisError, "conflicts at revision"):
            self.noctis.show_run(self.project, run_id)

    def test_plan_rejects_cycles_workspace_escape_and_uncommitted_writes(self) -> None:
        catalog = self.noctis.discover([SKILLS_ROOT])
        cyclic = self.plan(
            [
                self.task("one", "code-review", "code.review", needs=["two"]),
                self.task("two", "code-review", "code.review", needs=["one"]),
            ]
        )
        with self.assertRaisesRegex(self.noctis.NoctisError, "cycle"):
            self.noctis.validate_plan(cyclic, self.project, catalog)
        escaped = self.plan([self.task("one", "code-review", "code.review")])
        escaped["workspaces"] = [{"id": "main", "root": "../outside"}]
        with self.assertRaisesRegex(self.noctis.NoctisError, "must not contain"):
            self.noctis.validate_plan(escaped, self.project, catalog)
        uncommitted = self.plan(
            [
                self.task(
                    "change",
                    "implement",
                    "code.change",
                    effects=["workspace.write"],
                )
            ]
        )
        with self.assertRaisesRegex(self.noctis.NoctisError, "git.commit"):
            self.noctis.validate_plan(uncommitted, self.project, catalog)

    def test_clone_recovers_completed_implementation_and_claims_review(self) -> None:
        plan = self.plan(
            [
                self.task(
                    "change",
                    "implement",
                    "code.change",
                    effects=["git.commit", "workspace.write"],
                ),
                self.task("review", "code-review", "code.review", needs=["change"]),
            ]
        )
        run_id = self.create(plan, ["git.commit", "workspace.write"])
        self.checkpoint()
        first = self.noctis.claim_task(self.project, run_id, "change")
        output_commit = self.commit_implementation()
        result_path = self.write_json(
            "change-result.json",
            self.result(
                first,
                effects=self.commit_effects(first, output_commit),
                locator={"kind": "git", "workspace": "main", "commit": output_commit},
            ),
        )
        dirty = self.project / "not-committed.txt"
        dirty.write_text("must not cross the checkpoint\n", encoding="utf-8")
        with self.assertRaisesRegex(self.noctis.NoctisError, "uncommitted content"):
            self.noctis.finish_task(
                self.project,
                run_id,
                "change",
                str(first["claim_id"]),
                int(first["revision"]),
                result_path,
            )
        dirty.unlink()
        finished = self.noctis.finish_task(
            self.project,
            run_id,
            "change",
            str(first["claim_id"]),
            int(first["revision"]),
            result_path,
        )
        self.assertEqual(finished["ready"], ["review"])
        self.checkpoint()

        clone = Path(self.temporary.name) / "clone"
        self.git("clone", str(self.project), str(clone), cwd=Path(self.temporary.name))
        recovered = self.run_cli(
            "recover", "--project", str(clone), "--run-id", run_id, cwd=clone
        )
        self.assertEqual(recovered["runs"][0]["ready"], ["review"])
        view = self.run_cli(
            "run-show", "--project", str(clone), "--run-id", run_id, cwd=clone
        )
        by_id = {task["id"]: task for task in view["tasks"]}
        self.assertEqual(by_id["change"]["status"], "completed")
        self.assertEqual(by_id["review"]["status"], "pending")
        review = self.run_cli(
            "task-claim",
            "--project",
            str(clone),
            "--run-id",
            run_id,
            "--task-id",
            "review",
            cwd=clone,
        )
        self.assertEqual(review["checkpoint"]["commit"], self.git("rev-parse", "HEAD", cwd=clone))
        self.assertEqual(review["inputs"][0]["artifact"]["locator"]["commit"], output_commit)

    def test_claim_requires_recorded_and_current_machine_grants(self) -> None:
        plan = self.plan(
            [
                self.task(
                    "change",
                    "implement",
                    "code.change",
                    effects=["git.commit", "workspace.write"],
                )
            ]
        )
        run_id = self.create(plan)
        self.checkpoint()
        with self.assertRaisesRegex(self.noctis.NoctisError, "recorded grants"):
            self.noctis.claim_task(self.project, run_id, "change")
        with self.assertRaisesRegex(self.noctis.NoctisError, "exceed"):
            self.noctis.grant_effects(
                self.project, run_id, ["network.write"], "not requested", True
            )
        self.noctis.grant_effects(
            self.project,
            run_id,
            ["git.commit", "workspace.write"],
            "user requested the edit",
            True,
        )
        self.checkpoint()
        self.noctis.recover(self.project, run_id)
        with self.assertRaisesRegex(self.noctis.NoctisError, "current-machine authorization"):
            self.noctis.claim_task(self.project, run_id, "change")
        reauthorized = self.noctis.grant_effects(
            self.project,
            run_id,
            ["git.commit", "workspace.write"],
            "user reauthorized this clone",
            True,
        )
        self.assertEqual(reauthorized["checkpoint_required"], [])
        self.assertEqual(self.noctis.claim_task(self.project, run_id, "change")["task_id"], "change")

    def test_working_task_retry_requires_reconciliation_acknowledgement(self) -> None:
        plan = self.plan(
            [
                self.task(
                    "change",
                    "implement",
                    "code.change",
                    effects=["git.commit", "workspace.write"],
                )
            ]
        )
        run_id = self.create(plan, ["git.commit", "workspace.write"])
        self.checkpoint()
        claim = self.noctis.claim_task(self.project, run_id, "change")
        with self.assertRaisesRegex(self.noctis.NoctisError, "revision conflict"):
            self.noctis.retry_task(self.project, run_id, "change", 1, "stale", True)
        with self.assertRaisesRegex(self.noctis.NoctisError, "acknowledge-effects"):
            self.noctis.retry_task(self.project, run_id, "change", 0, "recover", False)
        retried = self.noctis.retry_task(
            self.project, run_id, "change", 0, "reconciled", True
        )
        self.assertEqual(retried["status"], "pending")
        self.checkpoint()
        second = self.noctis.claim_task(self.project, run_id, "change")
        self.assertEqual(second["attempt"], 2)
        with self.assertRaisesRegex(self.noctis.NoctisError, "does not undo"):
            self.noctis.cancel_task(
                self.project, run_id, "change", 1, "stop", False
            )

    def test_result_rejects_unreachable_git_evidence(self) -> None:
        run_id = self.create(
            self.plan([self.task("review", "code-review", "code.review")])
        )
        self.checkpoint()
        claim = self.noctis.claim_task(self.project, run_id, "review")
        invalid = self.result(
            claim,
            locator={"kind": "git", "workspace": "main", "commit": "0" * 40},
        )
        path = self.write_json("invalid-result.json", invalid)
        with self.assertRaisesRegex(self.noctis.NoctisError, "not reachable"):
            self.noctis.finish_task(
                self.project,
                run_id,
                "review",
                str(claim["claim_id"]),
                int(claim["revision"]),
                path,
            )

    def test_cancel_cascades_to_pending_descendants(self) -> None:
        run_id = self.create(
            self.plan(
                [
                    self.task("one", "code-review", "code.review"),
                    self.task("two", "code-review", "code.review", needs=["one"]),
                    self.task("three", "code-review", "code.review", needs=["two"]),
                ]
            )
        )
        self.checkpoint()
        canceled = self.noctis.cancel_task(
            self.project, run_id, "one", 0, "user canceled the workflow", False
        )
        self.assertEqual(canceled["canceled"], ["one", "two", "three"])
        self.assertEqual(self.noctis.show_run(self.project, run_id)["status"], "canceled")


if __name__ == "__main__":
    unittest.main()
