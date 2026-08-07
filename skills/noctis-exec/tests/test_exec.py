from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
EXEC_SCRIPT = SKILL_ROOT / "scripts" / "exec.py"


def load_exec_module():
    spec = importlib.util.spec_from_file_location("noctis_exec", EXEC_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {EXEC_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def binding(capability: str) -> dict:
    provider = "code-review" if capability == "review" else (
        "verify" if capability == "verify" else "implement"
    )
    return {
        "contract": 1,
        "executor": {"id": provider, "provider": provider},
        "supports": {},
    }


def artifact_binding() -> dict:
    return {"inputs": {}, "outputs": {}}


def task(
    task_id: str,
    capability: str,
    track: str,
    depends_on: list[str],
) -> dict:
    document = {
        "implement": "implementation",
        "fix-review": "implementation",
        "fix-verification": "implementation",
        "review": "review",
        "verify": "verification",
    }[capability]
    return {
        "id": task_id,
        "title": f"{capability} {track}",
        "capability": capability,
        "track": track,
        "dependsOn": depends_on,
        "binding": binding(capability),
        "artifactBinding": artifact_binding(),
        "record": {
            "document": document,
            "path": f"tracks/{track}/{document}.md",
        },
    }


def unit_payload(tasks: list[dict]) -> dict:
    return {
        "id": "U01",
        "title": "跨项目迁移",
        "objective": "并行实现两个项目并完成集成检查。",
        "completionConditions": ["全部分支完成并通过集成审查。"],
        "authority": {
            "allowed": ["修改目标仓库并创建本地提交。"],
            "forbidden": ["不得推送或部署。"],
        },
        "workflowTemplate": "reviewed",
        "tracks": [
            {
                "id": "map-frontend",
                "label": "Map 前端",
                "target": "bss-business-map-frontend",
            },
            {
                "id": "lowcode-template",
                "label": "低代码模板",
                "target": "workspace-template",
            },
            {
                "id": "integration",
                "label": "集成",
                "target": "cross-project",
            },
        ],
        "tasks": tasks,
    }


def task_payload(task_id: str = "T01") -> dict:
    return {
        "id": task_id,
        "title": "实现客户类型页面",
        "objective": "按已确认范围完成页面实现。",
        "completionConditions": ["实现记录包含完成结果和本地提交。"],
        "authority": {
            "allowed": ["修改目标仓库并创建本地提交。"],
            "forbidden": ["不得运行测试、推送或部署。"],
        },
        "capability": "implement",
        "binding": binding("implement"),
        "artifactBinding": artifact_binding(),
        "record": {
            "document": "implementation",
            "path": "implementation.md",
        },
    }


def workflow_plan() -> dict:
    work_path = "Noctis/accounts/work/migration/noctis.md"
    unit_path = "Noctis/accounts/work/migration/units/U01/noctis.md"
    return {
        "version": 2,
        "root": work_path,
        "records": [
            {
                "level": "work",
                "path": work_path,
                "input": {
                    "id": "migration",
                    "title": "表单迁移",
                    "objective": "按业务范围完成迁移。",
                    "completionConditions": ["迁移 Unit 完成。"],
                    "authority": {
                        "allowed": ["修改本地项目文件。"],
                        "forbidden": ["不得推送或部署。"],
                    },
                    "units": [
                        {
                            "id": "U01",
                            "title": "客户类型",
                            "path": "units/U01/noctis.md",
                            "dependsOn": [],
                        }
                    ],
                },
            },
            {
                "level": "unit",
                "path": unit_path,
                "input": unit_payload(
                    [task("U01.T01", "implement", "map-frontend", [])]
                ),
            },
        ],
    }


class ToolchainTests(unittest.TestCase):
    def run_tool(
        self, *arguments: str, input_value: dict | None = None, ok: bool = True
    ):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(EXEC_SCRIPT), *arguments],
            input=(
                json.dumps(input_value, ensure_ascii=False)
                if input_value is not None
                else None
            ),
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        if ok and result.returncode != 0:
            self.fail(f"command failed: {result.stderr}\n{result.stdout}")
        if not ok and result.returncode == 0:
            self.fail(f"command unexpectedly succeeded: {result.stdout}")
        return result

    def create_unit(self, root: Path, tasks: list[dict]) -> Path:
        unit = root / "Noctis" / "accounts" / "units" / "U01"
        self.run_tool(
            "orchestration",
            "create",
            "--level",
            "unit",
            "--path",
            str(unit),
            input_value=unit_payload(tasks),
        )
        return unit

    def transition(
        self,
        action: str,
        unit: Path,
        task_id: str,
        revision: int,
        *,
        status: str | None = None,
        outcome: str | None = None,
        artifacts: dict | None = None,
    ) -> dict:
        arguments = [
            "orchestration",
            action,
            "--path",
            str(unit),
            "--id",
            task_id,
            "--expected-revision",
            str(revision),
        ]
        if action == "finish":
            arguments.extend(["--to-status", status or "completed"])
            arguments.extend(["--outcome", outcome or "advanced"])
            if artifacts is not None:
                arguments.extend(["--artifacts", "-"])
        result = self.run_tool(*arguments, input_value=artifacts)
        return json.loads(result.stdout)

    def test_task_record_is_resumable_without_a_unit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Noctis").mkdir()
            (root / "Noctis" / "registry.yaml").write_text(
                "version: 3\n", encoding="utf-8"
            )
            task_root = root / "Noctis" / "accounts" / "tasks" / "T01"
            validated = self.run_tool(
                "orchestration",
                "create",
                "--level",
                "task",
                "--path",
                str(task_root),
                "--dry-run",
                input_value=task_payload(),
            )
            self.assertEqual(json.loads(validated.stdout)["status"], "valid")
            self.assertFalse((task_root / "noctis.md").exists())
            created = self.run_tool(
                "orchestration",
                "create",
                "--level",
                "task",
                "--path",
                str(task_root),
                input_value=task_payload(),
            )
            self.assertEqual(json.loads(created.stdout)["ready"], ["T01"])

            prepared = self.run_tool("entry", "--start", str(task_root))
            entry = json.loads(prepared.stdout)["entry"]
            self.assertEqual(entry["version"], 2)
            self.assertEqual(entry["orchestration"]["level"], "task")
            self.assertEqual(entry["target"]["id"], "T01")
            self.assertEqual(entry["expectedRevision"], 1)
            self.assertEqual(
                entry["orchestration"]["completionConditions"],
                ["实现记录包含完成结果和本地提交。"],
            )

            self.transition("start", task_root, "T01", 1)
            completed = self.transition("finish", task_root, "T01", 2)
            self.assertEqual(completed["orchestrationStatus"], "completed")

    def test_workflow_materialize_requires_confirmation_and_creates_pending_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = workflow_plan()
            work = root / plan["root"]
            unit = root / plan["records"][1]["path"]

            validated = self.run_tool(
                "workflow",
                "materialize",
                "--project-root",
                str(root),
                "--dry-run",
                input_value=plan,
            )
            candidate = json.loads(validated.stdout)
            self.assertEqual(candidate["status"], "valid")
            self.assertFalse(work.exists())
            self.assertFalse(unit.exists())

            rejected = self.run_tool(
                "workflow",
                "materialize",
                "--project-root",
                str(root),
                input_value=plan,
                ok=False,
            )
            self.assertIn("requires user confirmation", rejected.stderr)
            self.assertFalse(work.exists())
            self.assertFalse(unit.exists())

            created = self.run_tool(
                "workflow",
                "materialize",
                "--project-root",
                str(root),
                "--confirmed",
                input_value=plan,
            )
            result = json.loads(created.stdout)
            self.assertEqual(result["status"], "created")
            self.assertTrue(work.is_file())
            self.assertTrue(unit.is_file())
            inspected = self.run_tool(
                "orchestration", "inspect", "--path", str(work)
            )
            self.assertEqual(
                json.loads(inspected.stdout)["metadata"]["status"], "pending"
            )
            self.assertEqual(
                result["artifacts"]["orchestration"],
                {
                    "type": "orchestration-record",
                    "format": "noctis.record@3",
                    "location": plan["root"],
                    "revision": 1,
                },
            )

    def test_workflow_materialize_rejects_partial_or_mismatched_plans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = workflow_plan()
            unit = root / plan["records"][1]["path"]
            work = root / plan["root"]
            unit.parent.mkdir(parents=True)
            unit.write_text("existing", encoding="utf-8")

            conflict = self.run_tool(
                "workflow",
                "materialize",
                "--project-root",
                str(root),
                "--confirmed",
                input_value=plan,
                ok=False,
            )
            self.assertIn("already exists", conflict.stderr)
            self.assertFalse(work.exists())
            self.assertEqual(unit.read_text(encoding="utf-8"), "existing")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = workflow_plan()
            plan["records"][0]["input"]["units"][0]["path"] = (
                "units/missing/noctis.md"
            )
            mismatch = self.run_tool(
                "workflow",
                "materialize",
                "--project-root",
                str(root),
                "--dry-run",
                input_value=plan,
                ok=False,
            )
            self.assertIn("planned Unit record", mismatch.stderr)
            self.assertFalse((root / "Noctis").exists())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = workflow_plan()
            extra = json.loads(json.dumps(plan["records"][1]))
            extra["path"] = (
                "Noctis/accounts/work/migration/units/unselected/noctis.md"
            )
            extra["input"]["id"] = "U02"
            plan["records"].append(extra)
            unselected = self.run_tool(
                "workflow",
                "materialize",
                "--project-root",
                str(root),
                "--dry-run",
                input_value=plan,
                ok=False,
            )
            self.assertIn("only the root and its declared Units", unselected.stderr)
            self.assertFalse((root / "Noctis").exists())

    def test_workflow_materialize_rolls_back_a_mid_write_failure(self) -> None:
        module = load_exec_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = workflow_plan()
            work = root / plan["root"]
            unit = root / plan["records"][1]["path"]
            original_write = module._atomic_write
            writes = 0

            def fail_second_write(path, content):
                nonlocal writes
                writes += 1
                if writes == 2:
                    raise OSError("injected write failure")
                original_write(path, content)

            args = argparse.Namespace(
                project_root=root,
                input=plan,
                confirmed=True,
                dry_run=False,
            )
            with mock.patch.object(
                module, "_atomic_write", side_effect=fail_second_write
            ):
                with self.assertRaisesRegex(OSError, "injected write failure"):
                    module.materialize_workflow(args)

            self.assertEqual(writes, 2)
            self.assertFalse(work.exists())
            self.assertFalse(unit.exists())

    def test_entry_collapses_child_units_and_exposes_multiple_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Noctis").mkdir()
            (root / "Noctis" / "registry.yaml").write_text(
                "version: 3\n", encoding="utf-8"
            )
            work = root / "Noctis" / "accounts" / "work" / "migration"
            work_payload = {
                "id": "migration",
                "title": "表单迁移",
                "objective": "先完成客户类型，再处理岗位。",
                "completionConditions": ["两个 Unit 均完成。"],
                "authority": {
                    "allowed": ["修改本地项目文件。"],
                    "forbidden": ["不得推送或部署。"],
                },
                "units": [
                    {
                        "id": "U01",
                        "title": "客户类型",
                        "path": "units/customer/noctis.md",
                        "dependsOn": [],
                    }
                ],
            }
            self.run_tool(
                "orchestration",
                "create",
                "--level",
                "work",
                "--path",
                str(work),
                input_value=work_payload,
            )
            child = work / "units" / "customer"
            self.run_tool(
                "orchestration",
                "create",
                "--level",
                "unit",
                "--path",
                str(child),
                input_value=unit_payload(
                    [
                        task("U01.T01", "implement", "map-frontend", []),
                        task(
                            "U01.T02",
                            "review",
                            "map-frontend",
                            ["U01.T01"],
                        ),
                    ]
                ),
            )
            prepared = self.run_tool("entry", "--start", str(root))
            value = json.loads(prepared.stdout)
            self.assertEqual(value["status"], "ready")
            self.assertEqual(value["entry"]["orchestration"]["level"], "work")

            self.transition("start", child, "U01.T01", 1)
            self.transition("finish", child, "U01.T01", 2)
            detailed = self.run_tool(
                "entry",
                "--record",
                str(child / "noctis.md"),
                "--id",
                "U01.T02",
            )
            target = json.loads(detailed.stdout)["entry"]["target"]
            self.assertEqual(
                target["predecessors"],
                [
                    {
                        "id": "U01.T01",
                        "status": "completed",
                        "outcome": "advanced",
                        "artifacts": {},
                    }
                ],
            )

            standalone = root / "Noctis" / "accounts" / "tasks" / "T02"
            self.run_tool(
                "orchestration",
                "create",
                "--level",
                "task",
                "--path",
                str(standalone),
                input_value=task_payload("T02"),
            )
            broken = (
                root
                / "Noctis"
                / "accounts"
                / "units"
                / "broken"
                / "noctis.md"
            )
            broken.parent.mkdir(parents=True)
            broken.write_text("not frontmatter\n", encoding="utf-8")
            ambiguous = self.run_tool("entry", "--start", str(root))
            candidates = json.loads(ambiguous.stdout)
            self.assertEqual(candidates["status"], "selection-required")
            self.assertEqual(len(candidates["candidates"]), 2)
            self.assertEqual(len(candidates["warnings"]), 1)

            explicit = self.run_tool(
                "entry",
                "--start",
                str(root),
                "--record",
                str(standalone / "noctis.md"),
            )
            self.assertEqual(
                json.loads(explicit.stdout)["entry"]["orchestration"]["id"],
                "T02",
            )

    def test_unit_runs_parallel_tracks_then_serial_fan_in(self) -> None:
        tasks = [
            task("U01.T01", "implement", "map-frontend", []),
            task("U01.T02", "implement", "lowcode-template", []),
            task("U01.T03", "review", "map-frontend", ["U01.T01"]),
            task("U01.T04", "review", "lowcode-template", ["U01.T02"]),
            task(
                "U01.T05",
                "review",
                "integration",
                ["U01.T03", "U01.T04"],
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Noctis").mkdir()
            (root / "Noctis" / "registry.yaml").write_text(
                "version: 3\n", encoding="utf-8"
            )
            unit = self.create_unit(root, tasks)
            inspected = self.run_tool(
                "orchestration", "inspect", "--path", str(unit)
            )
            self.assertEqual(
                json.loads(inspected.stdout)["ready"], ["U01.T01", "U01.T02"]
            )
            discovered = self.run_tool("entry", "--start", str(root), "--list")
            entry_set = json.loads(discovered.stdout)["entrySet"]
            self.assertEqual(entry_set["version"], 1)
            self.assertEqual(len(entry_set["orchestrations"]), 1)
            self.assertEqual(
                [entry["id"] for entry in entry_set["orchestrations"][0]["entries"]],
                ["U01.T01", "U01.T02"],
            )
            selectable = self.run_tool(
                "entry", "--record", str(unit / "noctis.md")
            )
            choices = json.loads(selectable.stdout)
            self.assertEqual(choices["status"], "selection-required")
            self.assertEqual(
                [
                    (entry["id"], entry["track"], entry["status"])
                    for entry in choices["candidates"]
                ],
                [
                    ("U01.T01", "map-frontend", "ready"),
                    ("U01.T02", "lowcode-template", "ready"),
                ],
            )
            selected = self.run_tool(
                "entry",
                "--record",
                str(unit / "noctis.md"),
                "--id",
                "U01.T02",
            )
            self.assertEqual(
                json.loads(selected.stdout)["entry"]["target"]["id"], "U01.T02"
            )

            self.transition("start", unit, "U01.T01", 1)
            second_active = self.transition("start", unit, "U01.T02", 2)
            self.assertEqual(second_active["ready"], [])

            first_done = self.transition("finish", unit, "U01.T01", 3)
            self.assertEqual(first_done["ready"], ["U01.T03"])
            second_done = self.transition("finish", unit, "U01.T02", 4)
            self.assertEqual(second_done["ready"], ["U01.T03", "U01.T04"])

            self.transition("start", unit, "U01.T03", 5)
            self.transition("start", unit, "U01.T04", 6)
            self.transition("finish", unit, "U01.T03", 7)
            branch_done = self.transition("finish", unit, "U01.T04", 8)
            self.assertEqual(branch_done["ready"], ["U01.T05"])
            self.transition("start", unit, "U01.T05", 9)
            completed = self.transition("finish", unit, "U01.T05", 10)
            self.assertEqual(completed["orchestrationStatus"], "completed")

            scanned = self.run_tool(
                "orchestration", "scan", "--root", str(root)
            )
            records = json.loads(scanned.stdout)["orchestrations"]
            self.assertEqual(records[0]["level"], "unit")
            self.assertEqual(records[0]["status"], "completed")

    def test_splice_inserts_fix_and_rereview_then_rewires_verify(self) -> None:
        tasks = [
            task("U01.T01", "implement", "map-frontend", []),
            task("U01.T02", "review", "map-frontend", ["U01.T01"]),
            task("U01.T03", "verify", "integration", ["U01.T02"]),
        ]
        tasks[1]["artifactBinding"]["outputs"] = {
            "review": {
                "type": "review-record",
                "formats": ["ars.review@1"],
                "required": True,
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            unit = self.create_unit(Path(directory), tasks)
            self.transition("start", unit, "U01.T01", 1)
            self.transition("finish", unit, "U01.T01", 2)
            self.transition("start", unit, "U01.T02", 3)

            inserted = [
                task("U01.T04", "fix-review", "map-frontend", ["U01.T02"]),
                task("U01.T05", "review", "map-frontend", ["U01.T04"]),
            ]
            inserted[0]["artifactBinding"] = {
                "inputs": {
                    "review": {
                        "type": "review-record",
                        "formats": ["ars.review@1"],
                        "required": True,
                        "source": {"task": "U01.T02", "output": "review"},
                    }
                },
                "outputs": {
                    "implementation": {
                        "type": "implementation-record",
                        "formats": ["ars.implementation@1"],
                        "required": True,
                    }
                },
            }
            inserted[1]["artifactBinding"]["inputs"] = {
                "implementation": {
                    "type": "implementation-record",
                    "formats": ["ars.implementation@1"],
                    "required": True,
                    "source": {"task": "U01.T04", "output": "implementation"},
                }
            }
            review_artifact = {
                "review": {
                    "type": "review-record",
                    "format": "ars.review@1",
                    "location": "tracks/map-frontend/review.md",
                    "revision": "4",
                }
            }
            spliced = self.run_tool(
                "orchestration",
                "splice",
                "--path",
                str(unit),
                "--after",
                "U01.T02",
                "--expected-revision",
                "4",
                input_value={
                    "sourceOutcome": "findings-accepted",
                    "sourceArtifacts": review_artifact,
                    "tasks": inserted,
                    "tail": "U01.T05",
                },
            )
            splice_result = json.loads(spliced.stdout)
            self.assertEqual(splice_result["ready"], ["U01.T04"])
            self.assertEqual(splice_result["rewired"], ["U01.T03"])

            inspected = self.run_tool(
                "orchestration", "inspect", "--path", str(unit)
            )
            metadata = json.loads(inspected.stdout)["metadata"]
            self.assertEqual(metadata["items"]["U01.T01"]["outcome"], "advanced")
            self.assertEqual(
                metadata["items"]["U01.T02"]["outcome"], "findings-accepted"
            )
            self.assertEqual(
                metadata["items"]["U01.T03"]["depends_on"], ["U01.T05"]
            )
            self.assertNotIn("resume", metadata)

            stale = self.run_tool(
                "orchestration",
                "start",
                "--path",
                str(unit),
                "--id",
                "U01.T04",
                "--expected-revision",
                "4",
                ok=False,
            )
            self.assertIn("revision mismatch", stale.stderr)

            self.transition("start", unit, "U01.T04", 5)
            fix_artifact = {
                "implementation": {
                    "type": "implementation-record",
                    "format": "ars.implementation@1",
                    "location": "tracks/map-frontend/implementation.md",
                    "revision": "fix:U01.T04",
                }
            }
            self.transition(
                "finish", unit, "U01.T04", 6, artifacts=fix_artifact
            )
            self.transition("start", unit, "U01.T05", 7)
            rereviewed = self.transition("finish", unit, "U01.T05", 8)
            self.assertEqual(rereviewed["ready"], ["U01.T03"])

    def test_verification_failure_splice_resolves_evidence_for_fix(self) -> None:
        tasks = [
            task("U01.T01", "implement", "map-frontend", []),
            task("U01.T02", "verify", "integration", ["U01.T01"]),
            task("U01.T03", "review", "integration", ["U01.T02"]),
        ]
        tasks[1]["artifactBinding"]["outputs"] = {
            "verification": {
                "type": "verification-record",
                "formats": ["ars.verification@1"],
                "required": True,
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Noctis").mkdir()
            (root / "Noctis" / "registry.yaml").write_text(
                "version: 3\n", encoding="utf-8"
            )
            unit = self.create_unit(root, tasks)
            self.transition("start", unit, "U01.T01", 1)
            self.transition("finish", unit, "U01.T01", 2)
            self.transition("start", unit, "U01.T02", 3)

            repair = task(
                "U01.T04", "fix-verification", "map-frontend", ["U01.T02"]
            )
            repair["artifactBinding"] = {
                "inputs": {
                    "verification": {
                        "type": "verification-record",
                        "formats": ["ars.verification@1"],
                        "required": True,
                        "source": {"task": "U01.T02", "output": "verification"},
                    }
                },
                "outputs": {
                    "implementation": {
                        "type": "implementation-record",
                        "formats": ["ars.implementation@1"],
                        "required": True,
                    }
                },
            }
            reverify = task(
                "U01.T05", "verify", "integration", ["U01.T04"]
            )
            evidence = {
                "verification": {
                    "type": "verification-record",
                    "format": "ars.verification@1",
                    "location": "tracks/integration/verification.md",
                    "revision": "4",
                }
            }
            spliced = self.run_tool(
                "orchestration",
                "splice",
                "--path",
                str(unit),
                "--after",
                "U01.T02",
                "--expected-revision",
                "4",
                input_value={
                    "sourceOutcome": "failures-accepted",
                    "sourceArtifacts": evidence,
                    "tasks": [repair, reverify],
                    "tail": "U01.T05",
                },
            )
            self.assertEqual(json.loads(spliced.stdout)["rewired"], ["U01.T03"])

            prepared = self.run_tool(
                "entry",
                "--record",
                str(unit / "noctis.md"),
                "--id",
                "U01.T04",
            )
            target = json.loads(prepared.stdout)["entry"]["target"]
            self.assertEqual(
                target["resolvedInputs"]["verification"]["artifact"],
                evidence["verification"],
            )
            self.assertEqual(target["unresolvedInputs"], [])

            self.transition("start", unit, "U01.T04", 5)
            implementation = {
                "implementation": {
                    "type": "implementation-record",
                    "format": "ars.implementation@1",
                    "location": "tracks/map-frontend/implementation.md",
                    "revision": "fix:U01.T04",
                }
            }
            self.transition(
                "finish", unit, "U01.T04", 6, artifacts=implementation
            )
            self.transition("start", unit, "U01.T05", 7)
            reverified = self.transition("finish", unit, "U01.T05", 8)
            self.assertEqual(reverified["ready"], ["U01.T03"])

    def test_work_orchestrates_units_serially(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "Noctis" / "accounts" / "work" / "migration"
            payload = {
                "id": "migration",
                "title": "表单迁移",
                "objective": "按业务范围分批迁移。",
                "completionConditions": ["客户类型与岗位 Unit 均完成。"],
                "authority": {
                    "allowed": ["修改本地项目文件。"],
                    "forbidden": ["不得推送或部署。"],
                },
                "units": [
                    {
                        "id": "U01",
                        "title": "客户类型",
                        "path": "units/customer/noctis.md",
                        "dependsOn": [],
                    },
                    {
                        "id": "U02",
                        "title": "岗位",
                        "path": "units/post/noctis.md",
                        "dependsOn": ["U01"],
                    },
                ],
            }
            self.run_tool(
                "orchestration",
                "create",
                "--level",
                "work",
                "--path",
                str(work),
                input_value=payload,
            )
            self.transition("start", work, "U01", 1)
            first_done = self.transition("finish", work, "U01", 2)
            self.assertEqual(first_done["ready"], ["U02"])
            self.transition("start", work, "U02", 3)
            completed = self.transition("finish", work, "U02", 4)
            self.assertEqual(completed["orchestrationStatus"], "completed")

    def test_cycle_and_initial_fix_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cyclic = [
                task("U01.T01", "implement", "map-frontend", ["U01.T02"]),
                task("U01.T02", "review", "map-frontend", ["U01.T01"]),
            ]
            failed = self.run_tool(
                "orchestration",
                "create",
                "--level",
                "unit",
                "--path",
                str(root / "cycle"),
                input_value=unit_payload(cyclic),
                ok=False,
            )
            self.assertIn("cycle", failed.stderr)

            repair = [task("U01.T03", "fix-review", "map-frontend", [])]
            failed = self.run_tool(
                "orchestration",
                "create",
                "--level",
                "unit",
                "--path",
                str(root / "fix-review"),
                input_value=unit_payload(repair),
                ok=False,
            )
            self.assertIn("recovery capability", failed.stderr)

    def test_artifacts_are_validated_and_resolved_for_the_next_task(self) -> None:
        producer = task("U01.T01", "implement", "map-frontend", [])
        producer["artifactBinding"]["outputs"] = {
            "implementation": {
                "type": "implementation-record",
                "formats": ["ars.implementation@1"],
                "required": True,
            }
        }
        consumer = task("U01.T02", "review", "map-frontend", ["U01.T01"])
        consumer["artifactBinding"]["inputs"] = {
            "implementation": {
                "type": "implementation-record",
                "formats": ["ars.implementation@1"],
                "required": True,
                "source": {"task": "U01.T01", "output": "implementation"},
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Noctis").mkdir()
            (root / "Noctis" / "registry.yaml").write_text(
                "version: 3\n", encoding="utf-8"
            )
            unit = self.create_unit(root, [producer, consumer])
            self.transition("start", unit, "U01.T01", 1)
            missing = self.run_tool(
                "orchestration",
                "finish",
                "--path",
                str(unit),
                "--id",
                "U01.T01",
                "--to-status",
                "completed",
                "--outcome",
                "implemented",
                "--expected-revision",
                "2",
                ok=False,
            )
            self.assertIn("required outputs", missing.stderr)

            artifact = {
                "implementation": {
                    "type": "implementation-record",
                    "format": "ars.implementation@1",
                    "location": "tracks/map-frontend/implementation.md",
                    "revision": "2",
                }
            }
            self.transition(
                "finish", unit, "U01.T01", 2, artifacts=artifact
            )
            prepared = self.run_tool(
                "entry",
                "--record",
                str(unit / "noctis.md"),
                "--id",
                "U01.T02",
            )
            target = json.loads(prepared.stdout)["entry"]["target"]
            self.assertEqual(
                target["resolvedInputs"],
                {
                    "implementation": {
                        "artifact": artifact["implementation"],
                        "source": {
                            "task": "U01.T01",
                            "output": "implementation",
                            "provider": "implement",
                            "record": {
                                "document": "implementation",
                                "path": "tracks/map-frontend/implementation.md",
                            },
                        },
                    }
                },
            )
            self.assertEqual(target["unresolvedInputs"], [])
            self.transition("start", unit, "U01.T02", 3)

    def test_many_input_resolves_every_direct_dependency(self) -> None:
        first = task("U01.T01", "implement", "map-frontend", [])
        second = task("U01.T02", "implement", "lowcode-template", [])
        for producer in (first, second):
            producer["artifactBinding"]["outputs"] = {
                "implementation": {
                    "type": "implementation-record",
                    "formats": ["ars.implementation@1"],
                    "required": True,
                }
            }
        integration = task(
            "U01.T03",
            "review",
            "integration",
            ["U01.T01", "U01.T02"],
        )
        integration["artifactBinding"]["inputs"] = {
            "implementations": {
                "type": "implementation-record",
                "formats": ["ars.implementation@1"],
                "required": True,
                "cardinality": "many",
                "source": [
                    {"task": "U01.T01", "output": "implementation"},
                    {"task": "U01.T02", "output": "implementation"},
                ],
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Noctis").mkdir()
            (root / "Noctis" / "registry.yaml").write_text(
                "version: 3\n", encoding="utf-8"
            )
            unit = self.create_unit(root, [first, second, integration])
            artifacts = []
            revision = 1
            for task_id, track in (
                ("U01.T01", "map-frontend"),
                ("U01.T02", "lowcode-template"),
            ):
                self.transition("start", unit, task_id, revision)
                revision += 1
                artifact = {
                    "implementation": {
                        "type": "implementation-record",
                        "format": "ars.implementation@1",
                        "location": f"tracks/{track}/implementation.md",
                        "revision": f"commit:{task_id}",
                    }
                }
                artifacts.append(artifact["implementation"])
                self.transition(
                    "finish", unit, task_id, revision, artifacts=artifact
                )
                revision += 1

            prepared = self.run_tool(
                "entry",
                "--record",
                str(unit / "noctis.md"),
                "--id",
                "U01.T03",
            )
            resolved = json.loads(prepared.stdout)["entry"]["target"][
                "resolvedInputs"
            ]["implementations"]
            self.assertEqual([value["artifact"] for value in resolved], artifacts)
            self.assertEqual(
                [value["source"]["task"] for value in resolved],
                ["U01.T01", "U01.T02"],
            )

            self.transition("start", unit, "U01.T03", revision)

    def test_external_artifact_is_resolved_for_a_single_task(self) -> None:
        payload = task_payload()
        payload["artifactBinding"]["inputs"] = {
            "source": {
                "type": "dataset",
                "formats": ["tabular.csv@1"],
                "required": True,
                "source": {
                    "artifact": {
                        "type": "dataset",
                        "format": "tabular.csv@1",
                        "location": "input/customers.csv",
                        "revision": "sha256:example",
                    }
                },
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Noctis").mkdir()
            (root / "Noctis" / "registry.yaml").write_text(
                "version: 3\n", encoding="utf-8"
            )
            task_root = root / "Noctis" / "data" / "tasks" / "T01"
            self.run_tool(
                "orchestration",
                "create",
                "--level",
                "task",
                "--path",
                str(task_root),
                input_value=payload,
            )
            prepared = self.run_tool("entry", "--start", str(task_root))
            target = json.loads(prepared.stdout)["entry"]["target"]
            self.assertEqual(
                target["resolvedInputs"]["source"]["source"],
                {"external": True},
            )
            self.transition("start", task_root, "T01", 1)

    def test_extensions_support_once_each_and_item_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "scenarios.md"
            document.write_text(
                """---
document: "scenarios"
template: "plan/scenarios@1"
revision: 1
---

<!-- noctis:slot document.start -->
<!-- /noctis:slot -->

<!-- noctis:collection scenarios -->
<!-- noctis:item SC01 -->
## SC01 First
<!-- noctis:slot scenario.after -->
<!-- /noctis:slot -->
<!-- /noctis:item -->

<!-- noctis:item SC02 -->
## SC02 Second
<!-- noctis:slot scenario.after -->
<!-- /noctis:slot -->
<!-- /noctis:item -->
<!-- /noctis:collection -->

<!-- noctis:slot document.end -->
<!-- /noctis:slot -->
""",
                encoding="utf-8",
            )
            header = root / "header.md"
            header.write_text("Generated task document", encoding="utf-8")
            verification = root / "verified.md"
            verification.write_text(
                "- [ ] Verified\n- Result: pending", encoding="utf-8"
            )

            self.run_tool(
                "extend",
                "insert",
                "--document",
                str(document),
                "--slot",
                "document.start",
                "--scope",
                "once",
                "--id",
                "noctis:header",
                "--content",
                str(header),
                "--expected-revision",
                "1",
            )
            synced = self.run_tool(
                "extend",
                "sync",
                "--document",
                str(document),
                "--slot",
                "scenario.after",
                "--scope",
                "each",
                "--id",
                "verify:verified",
                "--content",
                str(verification),
                "--expected-revision",
                "2",
            )
            self.assertEqual(json.loads(synced.stdout)["changed"], 2)

            unchanged = self.run_tool(
                "extend",
                "sync",
                "--document",
                str(document),
                "--slot",
                "scenario.after",
                "--scope",
                "each",
                "--id",
                "verify:verified",
                "--content",
                str(verification),
                "--expected-revision",
                "3",
            )
            self.assertEqual(json.loads(unchanged.stdout)["revision"], 3)

            read = self.run_tool(
                "extend",
                "read",
                "--document",
                str(document),
                "--id",
                "verify:verified",
            )
            occurrences = json.loads(read.stdout)["occurrences"]
            self.assertEqual(
                [entry["item"] for entry in occurrences], ["SC01", "SC02"]
            )


if __name__ == "__main__":
    unittest.main()
