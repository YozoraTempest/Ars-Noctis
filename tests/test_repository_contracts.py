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
