from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
ARS = SKILLS / "ars" / "scripts" / "ars.py"
EXPECTED = {
    "ars",
    "noctis",
    "spec",
    "design",
    "implement",
    "test",
    "code-review",
    "verify",
}
ATOMIC = ("spec", "design", "implement", "test", "code-review", "verify")


class RepositoryContractTests(unittest.TestCase):
    def test_npm_distribution_is_declarative_and_keeps_core_optional(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        distribution = json.loads(
            (ROOT / "distribution.json").read_text(encoding="utf-8")
        )
        self.assertEqual(package["name"], "ars-noctis")
        self.assertEqual(package["bin"], {"ars-noctis": "bin/ars-noctis.mjs"})
        self.assertEqual(package["engines"], {"node": ">=22"})
        self.assertNotIn("dependencies", package)
        self.assertEqual(distribution["schema"], "ars-noctis.distribution/v1")
        self.assertEqual(distribution["profiles"]["core"], ["ars", "noctis"])
        self.assertEqual(
            {item["id"] for item in distribution["skills"]}, EXPECTED
        )
        self.assertEqual(
            {
                item["id"]
                for item in distribution["skills"]
                if item.get("requires", {}).get("python")
            },
            {"ars", "noctis"},
        )
        self.assertEqual(
            {
                item["id"]
                for item in distribution["skills"]
                if "git" in item.get("requires", {}).get("executables", [])
            },
            {"ars", "noctis"},
        )
        self.assertEqual(
            {
                item["id"]
                for item in distribution["skills"]
                if item.get("checks")
            },
            {"ars", "noctis"},
        )

    def test_node_doctor_has_no_skill_specific_branches(self) -> None:
        doctor = (ROOT / "lib" / "doctor.mjs").read_text(encoding="utf-8")
        self.assertNotIn("ars.json", doctor)
        self.assertNotIn("'ars'", doctor)
        self.assertNotIn("'noctis'", doctor)
        self.assertIn("skill.checks", doctor)

    def test_ci_checks_supported_node_versions_before_minimal_publish_job(self) -> None:
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        publish = (ROOT / ".github" / "workflows" / "publish.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("pull_request:", ci)
        self.assertIn("node: [22, 24]", ci)
        self.assertIn("runs-on: windows-latest", ci)
        self.assertIn("needs: package", publish)
        self.assertEqual(publish.count("id-token: write"), 1)
        self.assertLess(publish.index("publish:"), publish.index("id-token: write"))
        self.assertIn("npm publish ./package/ars-noctis-*.tgz", publish)
        self.assertNotRegex(ci + publish, r"uses:\s+[^\s]+@v\d")

    def test_repository_contains_eight_independent_skill_entrypoints(self) -> None:
        actual = {
            path.name for path in SKILLS.iterdir() if (path / "SKILL.md").is_file()
        }
        self.assertEqual(actual, EXPECTED)
        for name in EXPECTED:
            with self.subTest(skill=name):
                self.assertTrue((SKILLS / name / "agents" / "openai.yaml").is_file())
        self.assertFalse((SKILLS / "noctis" / "ars.json").exists())

    def test_every_manifest_validates_through_public_cli(self) -> None:
        for name in EXPECTED - {"noctis"}:
            result = subprocess.run(
                [sys.executable, str(ARS), "validate", "--skill", str(SKILLS / name)],
                cwd=ROOT,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            with self.subTest(skill=name):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(json.loads(result.stdout)["ok"])

    def test_manifests_expose_only_discovery_contract(self) -> None:
        expected_fields = {"schema", "id", "version", "capabilities"}
        capability_fields = {"id", "description", "accepts", "returns", "effects"}
        for name in EXPECTED - {"noctis"}:
            manifest = json.loads((SKILLS / name / "ars.json").read_text(encoding="utf-8"))
            with self.subTest(skill=name):
                self.assertEqual(set(manifest), expected_fields)
                self.assertEqual(manifest["schema"], "ars.skill/v1")
                self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
                for capability in manifest["capabilities"]:
                    self.assertEqual(set(capability), capability_fields)
                    self.assertEqual(capability["accepts"], "ars.task/v1")
                    self.assertEqual(capability["returns"], "ars.result/v1")

    def test_noctis_core_has_no_ars_or_provider_dependency(self) -> None:
        scripts = SKILLS / "noctis" / "scripts"
        sources = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(scripts.rglob("*.py"))
        ).lower()
        for forbidden in ("ars.json", "ars.skill/", "ars.task/", "ars.result/", "ars.plan/"):
            self.assertNotIn(forbidden, sources)
        self.assertNotIn("from ars", sources)
        self.assertNotIn("import ars", sources)
        self.assertTrue((scripts / "noctislib" / "contracts.py").is_file())
        self.assertTrue((scripts / "noctislib" / "state.py").is_file())
        self.assertTrue((scripts / "noctislib" / "runtime.py").is_file())
        self.assertFalse((scripts / "noctis_runtime.py").exists())

    def test_ars_adapter_uses_public_json_not_noctis_internals(self) -> None:
        adapter = (SKILLS / "ars" / "scripts" / "ars_noctis.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("noctislib", adapter)
        self.assertNotIn("skills/noctis", adapter.replace("\\", "/"))
        self.assertIn("noctis.plan/v1", adapter)
        self.assertIn("noctis.extension/v1", adapter)

    def test_noctis_owns_generic_git_state_and_dynamic_extension(self) -> None:
        instructions = (SKILLS / "noctis" / "SKILL.md").read_text(encoding="utf-8")
        contracts = (SKILLS / "noctis" / "references" / "contracts.md").read_text(
            encoding="utf-8"
        )
        operations = (SKILLS / "noctis" / "references" / "operations.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(".noctis/runs/<run-id>/", instructions)
        self.assertIn("noctis.extension/v1", contracts)
        self.assertIn("expected-run-revision", operations)
        self.assertIn("noctis/cache.sqlite3", operations)
        self.assertNotIn(".ars/runs/<run-id>/", instructions)

    def test_example_assets_keep_adapter_and_core_schemas_separate(self) -> None:
        core_plan = json.loads(
            (SKILLS / "noctis" / "assets" / "plan.example.json").read_text(
                encoding="utf-8"
            )
        )
        core_extension = json.loads(
            (SKILLS / "noctis" / "assets" / "extension.example.json").read_text(
                encoding="utf-8"
            )
        )
        ars_plan = json.loads(
            (SKILLS / "ars" / "assets" / "noctis-plan.example.json").read_text(
                encoding="utf-8"
            )
        )
        app_run_config = json.loads(
            (SKILLS / "ars" / "assets" / "app-run-config.example.json").read_text(
                encoding="utf-8"
            )
        )
        app_host = json.loads(
            (SKILLS / "ars" / "assets" / "app-host.example.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(core_plan["schema"], "noctis.plan/v1")
        self.assertEqual(core_extension["schema"], "noctis.extension/v1")
        self.assertEqual(ars_plan["schema"], "ars.plan/v1")
        self.assertEqual(app_run_config["schema"], "ars.app-run-config/v1")
        self.assertEqual(app_run_config["default"]["agent_mode"], "single")
        self.assertEqual(app_host["schema"], "ars.app-host/v1")
        self.assertEqual(app_host["current_agent"]["explicit_skills"], ["ars"])
        self.assertTrue(all(item["kind"] != "ars" for item in core_plan["executors"]))

    def test_atomic_skills_do_not_own_orchestration_state(self) -> None:
        for name in ATOMIC:
            root = SKILLS / name
            instructions = (root / "SKILL.md").read_text(encoding="utf-8")
            with self.subTest(skill=name):
                self.assertIn("ars.task/v1", instructions)
                self.assertIn("ars.result/v1", instructions)
                self.assertFalse(any((root / "scripts").glob("*.py")))

    def test_atomic_skills_carry_self_contained_provider_contract(self) -> None:
        provider_contract = (
            SKILLS / "ars" / "references" / "provider-envelope.md"
        ).read_text(encoding="utf-8")
        for name in ATOMIC:
            root = SKILLS / name
            instructions = (root / "SKILL.md").read_text(encoding="utf-8")
            contract = (root / "references" / "ars-envelope.md").read_text(
                encoding="utf-8"
            )
            with self.subTest(skill=name):
                self.assertIn(
                    "[references/ars-envelope.md](references/ars-envelope.md)",
                    instructions,
                )
                self.assertEqual(contract, provider_contract)

    def test_openai_metadata_default_prompts_name_the_skill(self) -> None:
        for name in EXPECTED:
            content = (SKILLS / name / "agents" / "openai.yaml").read_text(encoding="utf-8")
            with self.subTest(skill=name):
                self.assertIn(f"${name}", content)
                self.assertIn("allow_implicit_invocation: false", content)

    def test_readme_records_dependency_direction_and_non_goals(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Ars -> Noctis public contract", readme)
        self.assertIn(".noctis/runs/<run-id>/", readme)
        self.assertIn("追加式 JSON + Git", readme)
        for framework in (
            "Agent Skills",
            "MCP",
            "A2A",
            "LangGraph",
            "CrewAI",
            "OpenAI Agents SDK",
            "AutoGen",
        ):
            self.assertIn(framework, readme)
        self.assertIn("不实现网络传输", readme)
        self.assertIn("Python 3.11+ 标准库", readme)


if __name__ == "__main__":
    unittest.main()
