from __future__ import annotations

import json
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = SKILL_ROOT / "scripts"
SCRIPT = SCRIPT_ROOT / "noctis.py"
REPOSITORY_ROOT = SKILL_ROOT.parents[1]
TEST_SUPPORT_ROOT = REPOSITORY_ROOT / "tests"
sys.path.insert(0, str(SCRIPT_ROOT))
sys.path.insert(0, str(TEST_SUPPORT_ROOT))

from git_fixture import GitRepositoryTestCase  # noqa: E402
from noctislib import contracts, runtime, state  # noqa: E402


class StateReducerTests(unittest.TestCase):
    def test_run_extension_reduces_without_git_or_executor_knowledge(self) -> None:
        executor = {
            "id": "local:worker:1",
            "kind": "test",
            "snapshot": {"version": 1},
            "digest": None,
        }
        first = {
            "id": "first",
            "needs": [],
            "executor": "local:worker:1",
            "request": {"operation": "first"},
            "requirements": [],
        }
        second = {
            "id": "second",
            "needs": ["first"],
            "executor": "local:worker:1",
            "request": {"operation": "second"},
            "requirements": [],
        }
        event = {
            "id": "00000000-0000-4000-8000-000000000001",
            "type": "run.tasks-added",
            "previous_revision": 0,
            "revision": 1,
            "data": {
                "extension": {
                    "schema": "noctis.extension/v1",
                    "origin": {
                        "kind": "user-request",
                        "summary": "Add a second task.",
                        "reference": None,
                    },
                    "executors": [],
                    "tasks": [second],
                }
            },
        }
        revision, grants, executors, tasks, order, _ = state.reduce_run_event(
            event,
            0,
            set(),
            [executor],
            {"first": state.task_state(first, added_revision=0)},
            ["first"],
        )
        self.assertEqual(revision, 1)
        self.assertEqual(grants, set())
        self.assertEqual(executors, [executor])
        self.assertEqual(order, ["first", "second"])
        self.assertEqual(tasks["second"]["added_revision"], 1)


class NoctisRuntimeTests(GitRepositoryTestCase):
    @staticmethod
    def executor(executor_id: str = "local:worker:1") -> dict[str, object]:
        snapshot = {"protocol": "test.executor/v1", "name": executor_id}
        return {
            "id": executor_id,
            "kind": "test",
            "snapshot": snapshot,
            "digest": contracts.canonical_digest(snapshot),
        }

    @staticmethod
    def task(
        task_id: str,
        *,
        needs: list[str] | None = None,
        executor: str = "local:worker:1",
        requirements: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "id": task_id,
            "needs": needs or [],
            "executor": executor,
            "request": {"operation": task_id, "payload": {"value": task_id}},
            "requirements": requirements or [],
        }

    def plan(self, tasks: list[dict[str, object]]) -> dict[str, object]:
        return {
            "schema": "noctis.plan/v1",
            "title": "Protocol-neutral test",
            "objective": "Exercise durable task graph behavior.",
            "executors": [self.executor()],
            "tasks": tasks,
        }

    @staticmethod
    def extension(
        tasks: list[dict[str, object]],
        executors: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        return {
            "schema": "noctis.extension/v1",
            "origin": {
                "kind": "user-request",
                "summary": "Add work discovered during execution.",
                "reference": None,
            },
            "executors": executors or [],
            "tasks": tasks,
        }

    @staticmethod
    def result(claim: dict[str, object], output: object) -> dict[str, object]:
        return {
            "schema": "noctis.result/v1",
            "run_id": claim["run_id"],
            "task_id": claim["task_id"],
            "claim_id": claim["claim_id"],
            "attempt": claim["attempt"],
            "status": "completed",
            "summary": "Executor returned an opaque value.",
            "output": output,
        }

    def create(
        self, tasks: list[dict[str, object]], grants: list[str] | None = None
    ) -> str:
        plan_path = self.write_json("plan.json", self.plan(tasks))
        supplied = grants or []
        created = runtime.create_run(
            self.project,
            plan_path,
            supplied,
            "test authorization" if supplied else None,
        )
        return str(created["run_id"])

    def checkpoint(self, message: str = "test: checkpoint Noctis state") -> str:
        self.git("add", ".noctis/runs")
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")

    def finish(self, run_id: str, claim: dict[str, object], output: object) -> dict[str, object]:
        path = self.write_json(f"{claim['task_id']}-result.json", self.result(claim, output))
        return runtime.finish_task(
            self.project,
            run_id,
            str(claim["task_id"]),
            str(claim["claim_id"]),
            int(claim["revision"]),
            path,
        )

    def test_contract_rejects_cycles_unknown_executors_and_bad_digests(self) -> None:
        cyclic = self.plan(
            [self.task("one", needs=["two"]), self.task("two", needs=["one"])]
        )
        with self.assertRaisesRegex(contracts.NoctisError, "cycle"):
            contracts.validate_plan(cyclic)

        unknown = self.plan([self.task("one", executor="missing:worker:1")])
        with self.assertRaisesRegex(contracts.NoctisError, "unknown executor"):
            contracts.validate_plan(unknown)

        bad_digest = self.plan([self.task("one")])
        bad_digest["executors"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(contracts.NoctisError, "does not match"):
            contracts.validate_plan(bad_digest)

    def test_plan_preview_omits_opaque_requests_and_executor_snapshots(self) -> None:
        plan = self.plan([self.task("first", requirements=["command.execute"])])
        plan["tasks"][0]["request"] = {"operation": "opaque"}
        preview = runtime.plan_preview(contracts.validate_plan(plan))

        self.assertEqual(
            preview,
            {
                "title": "Protocol-neutral test",
                "objective": "Exercise durable task graph behavior.",
                "tasks": [
                    {
                        "id": "first",
                        "needs": [],
                        "executor": "local:worker:1",
                    }
                ],
                "requirements": ["command.execute"],
            },
        )

    def test_committed_checkpoint_guard_skips_display_metadata(self) -> None:
        run_id = self.create([self.task("first")])
        head = self.checkpoint()

        with mock.patch.object(
            runtime,
            "git_branch",
            side_effect=AssertionError("display metadata must not be queried"),
        ):
            checkpoint, _ = runtime.require_committed_checkpoint(
                self.project, run_id
            )

        self.assertEqual(checkpoint["commit"], head)
        self.assertTrue(checkpoint["committed"])

    def test_claim_reuses_verified_base_seal(self) -> None:
        run_id = self.create([self.task("first")])
        self.checkpoint()

        with mock.patch.object(
            runtime,
            "verify_base_seal",
            wraps=runtime.verify_base_seal,
        ) as verify:
            runtime.claim_task(self.project, run_id, "first")

        self.assertEqual(verify.call_count, 1)

    def test_cli_completes_a_task_with_opaque_output(self) -> None:
        plan_path = self.write_json("cli-plan.json", self.plan([self.task("first")]))
        created = subprocess.run(
            [sys.executable, str(SCRIPT), "run-create", "--project", str(self.project), "--plan", str(plan_path)],
            cwd=self.project,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        run_id = json.loads(created.stdout)["run_id"]
        self.checkpoint()
        claim = runtime.claim_task(self.project, run_id, "first")
        finished = self.finish(run_id, claim, {"any": ["strict", "json"]})
        self.assertEqual(finished["run_status"], "completed")
        self.checkpoint()
        task = runtime.show_run(self.project, run_id)["tasks"][0]
        self.assertEqual(task["result"]["output"], {"any": ["strict", "json"]})

    def test_completed_run_accepts_dynamic_task_and_passes_dependency_result(self) -> None:
        run_id = self.create([self.task("first")])
        self.checkpoint()
        first = runtime.claim_task(self.project, run_id, "first")
        self.finish(run_id, first, {"value": 1})
        self.checkpoint()
        self.assertEqual(runtime.show_run(self.project, run_id)["status"], "completed")

        added = runtime.extend_run_value(
            self.project,
            run_id,
            self.extension([self.task("second", needs=["first"])]),
            0,
        )
        self.assertEqual(added["status"], "submitted")
        self.assertEqual(added["tasks_added"], ["second"])
        self.checkpoint()
        second = runtime.claim_task(self.project, run_id, "second")
        self.assertEqual(second["dependencies"][0]["result"]["output"], {"value": 1})

    def test_extension_can_add_executor_and_requirements_with_revision_control(self) -> None:
        run_id = self.create([self.task("first")])
        self.checkpoint()
        added_executor = self.executor("remote:worker:2")
        extension = self.extension(
            [
                self.task(
                    "remote-task",
                    executor="remote:worker:2",
                    requirements=["network.write"],
                )
            ],
            [added_executor],
        )
        added = runtime.extend_run_value(self.project, run_id, extension, 0)
        self.assertEqual(added["executors_added"], ["remote:worker:2"])
        self.assertEqual(added["missing_grants"], ["network.write"])
        self.checkpoint()
        with self.assertRaisesRegex(contracts.NoctisError, "Run revision conflict"):
            runtime.extend_run_value(
                self.project,
                run_id,
                self.extension([self.task("stale-task")]),
                0,
            )
        with self.assertRaisesRegex(contracts.NoctisError, "recorded grants"):
            runtime.claim_task(self.project, run_id, "remote-task")
        runtime.grant_requirements(
            self.project, run_id, ["network.write"], "User authorized remote execution."
        )
        self.checkpoint()
        self.assertEqual(
            runtime.claim_task(self.project, run_id, "remote-task")["executor"]["id"],
            "remote:worker:2",
        )

    def test_concurrent_extensions_leave_one_replayable_event(self) -> None:
        run_id = self.create([self.task("first")])
        self.checkpoint()
        start = threading.Barrier(2)
        outcomes: list[tuple[str, object]] = []

        def extend(task_id: str) -> None:
            start.wait()
            try:
                result = runtime.extend_run_value(
                    self.project,
                    run_id,
                    self.extension([self.task(task_id)]),
                    0,
                )
                outcomes.append(("success", result))
            except contracts.NoctisError as error:
                outcomes.append(("error", str(error)))

        threads = [
            threading.Thread(target=extend, args=(task_id,))
            for task_id in ("second", "third")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
            self.assertFalse(thread.is_alive(), "concurrent extension did not finish")

        self.assertEqual([kind for kind, _ in outcomes].count("success"), 1)
        self.assertEqual([kind for kind, _ in outcomes].count("error"), 1)
        event_directory = self.project / ".noctis" / "runs" / run_id / "events"
        self.assertEqual(len(list(event_directory.glob("*.json"))), 1)
        state = runtime.load_run_state(self.project, run_id)
        self.assertEqual(state["run_revision"], 1)
        self.assertEqual(len(state["tasks"]), 2)

    def test_recover_discards_local_claims_and_machine_authorization(self) -> None:
        run_id = self.create([self.task("first", requirements=["secret.read"])], ["secret.read"])
        self.checkpoint()
        runtime.claim_task(self.project, run_id, "first")
        self.assertEqual(runtime.show_run(self.project, run_id)["status"], "working")
        recovered = runtime.recover(self.project, run_id)
        self.assertEqual(recovered["runs"][0]["ready"], ["first"])
        self.assertEqual(recovered["active_grants"], [])
        with self.assertRaisesRegex(contracts.NoctisError, "current-machine authorization"):
            runtime.claim_task(self.project, run_id, "first")

    def test_base_plan_is_sealed_by_its_first_checkpoint(self) -> None:
        run_id = self.create([self.task("first")])
        self.checkpoint()
        plan_path = self.project / ".noctis" / "runs" / run_id / "plan.json"
        mutated = json.loads(plan_path.read_text(encoding="utf-8"))
        mutated["objective"] = "Silently replace the approved objective."
        plan_path.write_text(json.dumps(mutated), encoding="utf-8")
        with self.assertRaisesRegex(contracts.NoctisError, "sealed"):
            runtime.show_run(self.project, run_id)

    def test_replay_rejects_conflicting_task_revisions(self) -> None:
        run_id = self.create([self.task("first")])
        self.checkpoint()
        for reason in ("first cancellation", "second cancellation"):
            runtime.append_event(
                self.project,
                runtime.new_event(
                    run_id,
                    "first",
                    "task.canceled",
                    0,
                    {
                        "attempt": 0,
                        "reason": reason,
                        "acknowledged_requirements": False,
                        "cascade_from": None,
                    },
                ),
            )
        with self.assertRaisesRegex(contracts.NoctisError, "conflicts at revision"):
            runtime.show_run(self.project, run_id)

    def test_replay_binds_result_claim_id_to_its_event(self) -> None:
        run_id = self.create([self.task("first")])
        self.checkpoint()
        claim = runtime.claim_task(self.project, run_id, "first")
        self.finish(run_id, claim, {"value": 1})
        result_path = (
            self.project
            / ".noctis"
            / "runs"
            / run_id
            / "results"
            / "first"
            / "attempt-1.json"
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["claim_id"] = "00000000-0000-4000-8000-000000000001"
        result_path.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(contracts.NoctisError, "claim_id/attempt is stale"):
            runtime.show_run(self.project, run_id)

    def test_retry_requires_requirement_reconciliation_and_increments_attempt(self) -> None:
        run_id = self.create(
            [self.task("first", requirements=["command.execute"])],
            ["command.execute"],
        )
        self.checkpoint()
        runtime.claim_task(self.project, run_id, "first")
        with self.assertRaisesRegex(contracts.NoctisError, "acknowledge-requirements"):
            runtime.retry_task(self.project, run_id, "first", 0, "retry", False)
        retried = runtime.retry_task(
            self.project, run_id, "first", 0, "execution reconciled", True
        )
        self.assertEqual(retried["status"], "pending")
        self.checkpoint()
        self.assertEqual(runtime.claim_task(self.project, run_id, "first")["attempt"], 2)

    def test_cancel_cascades_to_pending_descendants(self) -> None:
        run_id = self.create(
            [
                self.task("one"),
                self.task("two", needs=["one"]),
                self.task("three", needs=["two"]),
            ]
        )
        self.checkpoint()
        canceled = runtime.cancel_task(
            self.project, run_id, "one", 0, "User canceled the workflow.", False
        )
        self.assertEqual(canceled["canceled"], ["one", "two", "three"])
        self.assertEqual(runtime.show_run(self.project, run_id)["status"], "canceled")

    def test_clone_recovers_dynamic_tasks_and_completed_results(self) -> None:
        run_id = self.create([self.task("first")])
        self.checkpoint()
        claim = runtime.claim_task(self.project, run_id, "first")
        self.finish(run_id, claim, {"receipt": "one"})
        self.checkpoint()
        runtime.extend_run_value(
            self.project,
            run_id,
            self.extension([self.task("second", needs=["first"])]),
            0,
        )
        self.checkpoint()

        clone = Path(self.temporary.name) / "clone"
        self.git("clone", str(self.project), str(clone), cwd=Path(self.temporary.name))
        recovered = runtime.recover(clone, run_id)
        self.assertEqual(recovered["runs"][0]["ready"], ["second"])
        claim = runtime.claim_task(clone, run_id, "second")
        self.assertEqual(claim["dependencies"][0]["result"]["output"], {"receipt": "one"})


if __name__ == "__main__":
    unittest.main()
