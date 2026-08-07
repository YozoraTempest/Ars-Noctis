from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPOSITORY_ROOT / "skills"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise AssertionError(f"expected YAML object: {path}")
    return value


def capabilities(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in manifest["capabilities"]}


def assert_compatible_ports(
    case: unittest.TestCase,
    output: dict[str, Any],
    input_port: dict[str, Any],
    *,
    required_input: bool = True,
) -> None:
    case.assertEqual(output["type"], input_port["type"])
    case.assertTrue(set(output["formats"]) & set(input_port["formats"]))
    case.assertTrue(output["required"])
    case.assertEqual(input_port["required"], required_input)


class RepositoryContractTests(unittest.TestCase):
    def test_exec_documents_three_distinct_capability_outputs(self) -> None:
        manifest = load_yaml(SKILLS_ROOT / "noctis-exec" / "ars.yaml")
        capabilities = {
            capability["id"]: capability for capability in manifest["capabilities"]
        }
        self.assertEqual(
            set(capabilities),
            {"discover-entries", "materialize-workflow", "execute-workflow"},
        )
        instructions = (SKILLS_ROOT / "noctis-exec" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("发现、物化与执行三个能力", instructions)
        self.assertIn("`discover-entries` 发布 `noctis.execution-entry-set@1`", instructions)

    def test_implement_keeps_tests_owned_by_a_separate_skill(self) -> None:
        instructions = (SKILLS_ROOT / "implement" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        capability = load_yaml(
            SKILLS_ROOT / "noctis" / "assets" / "capabilities" / "implement.yaml"
        )
        self.assertIn("测试由独立 Test Skill 承担", instructions)
        self.assertIn("test-execution", capability["forbids"])
        self.assertIn("至少创建一个", instructions)

    def test_atomic_executors_do_not_own_noctis_lifecycle(self) -> None:
        for skill in ("implement", "code-review", "verify"):
            instructions = (SKILLS_ROOT / skill / "SKILL.md").read_text(
                encoding="utf-8"
            )
            with self.subTest(skill=skill):
                self.assertNotIn("orchestration finish", instructions)
                self.assertNotIn("orchestration splice", instructions)
                self.assertIn("不要调用 Noctis Exec 的 `finish`、`splice`", instructions)
                self.assertIn("独立调用", instructions)

        run = (SKILLS_ROOT / "noctis-exec" / "references" / "run.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("ExecutorResult v1", run)
        self.assertIn("orchestration apply-result", run)
        self.assertIn("检查点成功后", run)
        self.assertIn("跨 Skill 协调", run)
        self.assertIn("目标 provider 的公开文档工具", run)

    def test_noctis_presents_one_complete_task_flow(self) -> None:
        instructions = (SKILLS_ROOT / "noctis" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        reference = (
            SKILLS_ROOT / "noctis" / "references" / "create-plan.md"
        ).read_text(encoding="utf-8")
        self.assertIn("只展示一条当前推荐的完整 Task 流程计划", instructions)
        self.assertIn("不同时展示多个方案", reference)

    def test_verify_preserves_human_ai_and_assisted_modes(self) -> None:
        instructions = (SKILLS_ROOT / "verify" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        expected = {
            "human": "用户操作并最终判定",
            "ai": "AI 使用获准工具执行",
            "assisted": "AI 负责打开、导航、准备或截图",
        }
        for mode, behavior in expected.items():
            with self.subTest(mode=mode):
                self.assertIn(f"- {mode}：", instructions)
                self.assertIn(behavior, instructions)

    def test_standalone_artifact_contracts_match_the_canonical_source(self) -> None:
        source = (REPOSITORY_ROOT / "scripts" / "artifact_contract.py").read_bytes()
        for path in (
            SKILLS_ROOT / "ars" / "scripts" / "artifact_contract.py",
            SKILLS_ROOT / "noctis" / "scripts" / "artifact_contract.py",
            SKILLS_ROOT / "noctis-exec" / "scripts" / "artifact_contract.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(path.read_bytes(), source)

    def test_explicit_workflow_skills_keep_safe_invocation_policy(self) -> None:
        for skill in (
            "noctis",
            "noctis-continue",
            "noctis-exec",
            "implement",
            "code-review",
            "verify",
        ):
            metadata = load_yaml(SKILLS_ROOT / skill / "agents" / "openai.yaml")
            with self.subTest(skill=skill):
                self.assertFalse(metadata["policy"]["allow_implicit_invocation"])
                self.assertIn(f"${skill}", metadata["interface"]["default_prompt"])

    def test_verify_scenarios_are_owned_once_per_unit(self) -> None:
        manifest = load_yaml(SKILLS_ROOT / "verify" / "ars.yaml")
        scenarios = next(
            document
            for document in manifest["documents"]
            if document["id"] == "scenarios"
        )
        self.assertEqual(scenarios["scope"], "unit")
        self.assertEqual(scenarios["file"], "scenarios.md")
        instructions = (SKILLS_ROOT / "verify" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("当前 Unit `noctis.md` 同级", instructions)
        self.assertIn("不得从 Track 路径猜测", instructions)

    def test_standalone_document_tools_match_the_canonical_source(self) -> None:
        source = (REPOSITORY_ROOT / "scripts" / "document_tool.py").read_bytes()
        for path in (
            SKILLS_ROOT / "implement" / "scripts" / "implementation.py",
            SKILLS_ROOT / "code-review" / "scripts" / "review.py",
            SKILLS_ROOT / "verify" / "scripts" / "scenarios.py",
            SKILLS_ROOT / "verify" / "scripts" / "verification.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(path.read_bytes(), source)

    def test_registry_capabilities_match_provider_manifests(self) -> None:
        registry = load_yaml(
            SKILLS_ROOT / "noctis" / "assets" / "registry.example.yaml"
        )
        provider_capabilities = {
            provider_id: capabilities(
                load_yaml(SKILLS_ROOT / spec["provider"] / "ars.yaml")
            )
            for provider_id, spec in registry["executors"].items()
        }

        for capability_id, registered in registry["capabilities"].items():
            declared = provider_capabilities[registered["executor"]][capability_id]
            with self.subTest(capability=capability_id):
                self.assertEqual(registered["contract"], declared["contract"])
                self.assertEqual(registered["inputs"], declared["inputs"])
                self.assertEqual(registered["outputs"], declared["outputs"])
                self.assertCountEqual(
                    registered["side_effects"], declared["side_effects"]
                )

    def test_control_plane_artifacts_have_declared_consumers(self) -> None:
        noctis = capabilities(load_yaml(SKILLS_ROOT / "noctis" / "ars.yaml"))
        continuation = capabilities(
            load_yaml(SKILLS_ROOT / "noctis-continue" / "ars.yaml")
        )
        execution = capabilities(
            load_yaml(SKILLS_ROOT / "noctis-exec" / "ars.yaml")
        )

        assert_compatible_ports(
            self,
            noctis["plan-workflow"]["outputs"]["execution-plan"],
            execution["materialize-workflow"]["inputs"]["execution-plan"],
        )
        assert_compatible_ports(
            self,
            continuation["continue-workflow"]["outputs"]["execution-entry"],
            execution["execute-workflow"]["inputs"]["execution-entry"],
        )
        assert_compatible_ports(
            self,
            execution["discover-entries"]["outputs"]["candidates"],
            continuation["continue-workflow"]["inputs"]["candidates"],
            required_input=False,
        )
        for capability_id in ("materialize-workflow", "execute-workflow"):
            assert_compatible_ports(
                self,
                execution[capability_id]["outputs"]["orchestration"],
                continuation["continue-workflow"]["inputs"]["orchestration"],
                required_input=False,
            )

    def test_continue_can_scan_without_an_artifact_input(self) -> None:
        continuation = capabilities(
            load_yaml(SKILLS_ROOT / "noctis-continue" / "ars.yaml")
        )
        orchestration = continuation["continue-workflow"]["inputs"]["orchestration"]
        self.assertFalse(orchestration["required"])


if __name__ == "__main__":
    unittest.main()
