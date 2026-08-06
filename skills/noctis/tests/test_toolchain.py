from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
INIT_SCRIPT = SKILL_ROOT / "scripts" / "init_registry.py"
NOCTIS_SCRIPT = SKILL_ROOT / "scripts" / "noctis.py"


def load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registry_input() -> dict:
    return {
        "presets": {
            "verified": {
                "workflow": ["implement", "review", "verify"],
                "description": "包含实际行为验收",
            },
            "reviewed": {
                "workflow": ["implement", "review"],
                "description": "默认工程修改",
            },
        },
        "stages": {
            "verify": {"supports": {}, "executor": "verify", "contract": 1},
            "review": {"supports": {}, "executor": "code-review", "contract": 1},
            "implement": {"supports": {}, "executor": "implement", "contract": 1},
            "fix": {"supports": {}, "executor": "implement", "contract": 1},
        },
        "supports": {},
        "executors": {
            "verify": {"source": "manifest", "provider": "verify"},
            "implement": {"source": "manifest", "provider": "implement"},
            "code-review": {"source": "manifest", "provider": "code-review"},
        },
        "default_preset": "reviewed",
        "version": 1,
    }


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_script("init_registry", INIT_SCRIPT)

    def test_default_registry_matches_golden_file(self) -> None:
        expected = (SKILL_ROOT / "assets" / "registry.example.yaml").read_text(
            encoding="utf-8"
        )
        self.assertEqual(self.module.render_registry(registry_input()), expected)

    def test_install_does_not_replace_without_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status, target, _ = self.module.install_registry(root, registry_input())
            self.assertEqual(status, "created")
            original = target.read_text(encoding="utf-8")

            changed = registry_input()
            changed["presets"]["reviewed"]["description"] = "另一种说明"
            status, _, diff = self.module.install_registry(root, changed)
            self.assertEqual(status, "different")
            self.assertIn("另一种说明", diff)
            self.assertEqual(target.read_text(encoding="utf-8"), original)

            status, _, _ = self.module.install_registry(root, changed, replace=True)
            self.assertEqual(status, "replaced")
            self.assertIn("另一种说明", target.read_text(encoding="utf-8"))

    def test_fix_cannot_be_a_normal_preset_stage(self) -> None:
        value = registry_input()
        value["presets"]["reviewed"]["workflow"].append("fix")
        with self.assertRaisesRegex(self.module.RegistryError, "recovery stage"):
            self.module.validate_registry(value)


class ToolchainTests(unittest.TestCase):
    def run_tool(self, *arguments: str, input_text: str | None = None, ok: bool = True):
        result = subprocess.run(
            [sys.executable, str(NOCTIS_SCRIPT), *arguments],
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )
        if ok and result.returncode != 0:
            self.fail(f"command failed: {result.stderr}\n{result.stdout}")
        if not ok and result.returncode == 0:
            self.fail(f"command unexpectedly succeeded: {result.stdout}")
        return result

    def test_task_create_inspect_transition_and_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / "Noctis" / "accounts" / "tasks" / "20260806-example"
            payload = json.dumps(
                {
                    "title": "示例任务",
                    "objective": "完成示例实现。",
                    "workflowSnapshot": {
                        "stages": {
                            "fix": {
                                "contract": 1,
                                "executor": {
                                    "id": "implement",
                                    "provider": "implement",
                                },
                                "supports": {},
                            },
                            "implement": {
                                "contract": 1,
                                "executor": {"id": "implement", "provider": "implement"},
                                "supports": {},
                            },
                            "review": {
                                "contract": 1,
                                "executor": {
                                    "id": "code-review",
                                    "provider": "code-review",
                                },
                                "supports": {
                                    "stage-knowledge": {
                                        "contract": 1,
                                        "provider": "codebase-design",
                                        "activation": "before",
                                    }
                                },
                            },
                        }
                    },
                },
                ensure_ascii=False,
            )
            created = self.run_tool(
                "task",
                "create",
                "--task",
                str(task),
                "--stage",
                "implement",
                "--workflow",
                "implement",
                "review",
                input_text=payload,
            )
            self.assertEqual(json.loads(created.stdout)["revision"], 1)

            inspected = self.run_tool("task", "inspect", "--task", str(task))
            metadata = json.loads(inspected.stdout)["metadata"]
            self.assertEqual(metadata["workflow"], ["implement", "review"])
            self.assertEqual(metadata["stage"], "implement")
            self.assertEqual(
                metadata["workflow_snapshot"]["stages"]["review"]["executor"]["provider"],
                "code-review",
            )
            self.assertEqual(
                metadata["workflow_snapshot"]["stages"]["review"]["supports"]
                ["stage-knowledge"]["activation"],
                "before",
            )

            appended = self.run_tool(
                "task",
                "append",
                "--task",
                str(task),
                "--section",
                "steps",
                "--item",
                "S01",
                "--expected-revision",
                "1",
                input_text=json.dumps({"content": "- [ ] Implement change"}),
            )
            self.assertEqual(json.loads(appended.stdout)["revision"], 2)

            checked = self.run_tool(
                "task",
                "update",
                "--task",
                str(task),
                "--section",
                "item.content",
                "--item",
                "S01",
                "--expected-revision",
                "2",
                input_text=json.dumps({"content": "- [x] Implement change"}),
            )
            self.assertEqual(json.loads(checked.stdout)["revision"], 3)

            skipped = self.run_tool(
                "task",
                "transition",
                "--task",
                str(task),
                "--from-stage",
                "implement",
                "--to-stage",
                "review",
                "--expected-revision",
                "3",
            )
            self.assertEqual(json.loads(skipped.stdout)["stage"], "review")

            returned = self.run_tool(
                "task",
                "transition",
                "--task",
                str(task),
                "--from-stage",
                "review",
                "--to-status",
                "completed",
                "--expected-revision",
                "4",
            )
            self.assertEqual(json.loads(returned.stdout)["status"], "completed")

    def test_fix_resume_queue_cannot_escape_snapshot_or_skip_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / "Noctis" / "accounts" / "tasks" / "20260806-recovery"
            payload = json.dumps(
                {
                    "title": "恢复任务",
                    "objective": "验证恢复队列。",
                    "workflowSnapshot": {
                        "stages": {
                            stage: {
                                "contract": 1,
                                "executor": {
                                    "id": "implement" if stage == "fix" else stage,
                                    "provider": "implement" if stage == "fix" else stage,
                                },
                                "supports": {},
                            }
                            for stage in ("implement", "fix", "review", "verify")
                        }
                    },
                },
                ensure_ascii=False,
            )
            self.run_tool(
                "task",
                "create",
                "--task",
                str(task),
                "--stage",
                "implement",
                "--workflow",
                "implement",
                "review",
                "verify",
                input_text=payload,
            )

            transitioned = self.run_tool(
                "task",
                "transition",
                "--task",
                str(task),
                "--from-stage",
                "implement",
                "--to-stage",
                "fix",
                "--resume",
                "review",
                "verify",
                "--expected-revision",
                "1",
            )
            transition_result = json.loads(transitioned.stdout)
            self.assertEqual(transition_result["revision"], 2)
            self.assertEqual(transition_result["resume"], ["review", "verify"])

            resumed = self.run_tool(
                "task",
                "transition",
                "--task",
                str(task),
                "--from-stage",
                "fix",
                "--use-resume",
                "--expected-revision",
                "2",
            )
            resume_result = json.loads(resumed.stdout)
            self.assertEqual(resume_result["stage"], "review")
            self.assertEqual(resume_result["resume"], ["verify"])

            scanned = self.run_tool("task", "scan", "--root", str(root))
            scan_result = json.loads(scanned.stdout)
            tasks = scan_result["tasks"]
            self.assertEqual(len(tasks), 1, scan_result)
            self.assertEqual(tasks[0]["stage"], "review")

            bypassed = self.run_tool(
                "task",
                "transition",
                "--task",
                str(task),
                "--from-stage",
                "review",
                "--to-stage",
                "verify",
                "--expected-revision",
                "3",
                ok=False,
            )
            self.assertIn("recovery queue", bypassed.stderr)

            resumed_again = self.run_tool(
                "task",
                "transition",
                "--task",
                str(task),
                "--from-stage",
                "review",
                "--use-resume",
                "--expected-revision",
                "3",
            )
            self.assertEqual(json.loads(resumed_again.stdout)["stage"], "verify")

            stale = self.run_tool(
                "task",
                "transition",
                "--task",
                str(task),
                "--from-stage",
                "verify",
                "--to-status",
                "completed",
                "--expected-revision",
                "3",
                ok=False,
            )
            self.assertIn("revision mismatch", stale.stderr)

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
            verification.write_text("- [ ] Verified\n- Result: pending", encoding="utf-8")

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
            unchanged_result = json.loads(unchanged.stdout)
            self.assertEqual(unchanged_result["changed"], 0)
            self.assertEqual(unchanged_result["revision"], 3)

            read = self.run_tool(
                "extend",
                "read",
                "--document",
                str(document),
                "--id",
                "verify:verified",
            )
            occurrences = json.loads(read.stdout)["occurrences"]
            self.assertEqual([entry["item"] for entry in occurrences], ["SC01", "SC02"])

            updated = root / "updated.md"
            updated.write_text("- [x] Verified\n- Result: passed", encoding="utf-8")
            self.run_tool(
                "extend",
                "upsert",
                "--document",
                str(document),
                "--slot",
                "scenario.after",
                "--scope",
                "item",
                "--item",
                "SC01",
                "--id",
                "verify:verified",
                "--content",
                str(updated),
                "--expected-revision",
                "3",
            )
            final = document.read_text(encoding="utf-8")
            self.assertIn("## SC01 First", final)
            self.assertIn("## SC02 Second", final)
            self.assertEqual(final.count("<!-- noctis:extension verify:verified -->"), 2)
            self.assertIn("revision: 4", final)


if __name__ == "__main__":
    unittest.main()
