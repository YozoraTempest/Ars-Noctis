#!/usr/bin/env python3
"""Normalize version 1 Ars Artifact port contracts."""

from __future__ import annotations

import re
from typing import Any


IDENTIFIER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ARTIFACT_FORMAT = re.compile(
    r"^[a-z0-9]+(?:[.-][a-z0-9]+)*@[1-9][0-9]*$"
)


class ArtifactContractError(ValueError):
    pass


def _identifier(value: Any, context: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ArtifactContractError(
            f"{context} must be a lowercase hyphenated identifier"
        )
    return value


def normalize_port(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ArtifactContractError(f"{context} must be an object")
    missing = sorted({"type", "formats", "required"} - set(value))
    unknown = sorted(
        set(value) - {"type", "formats", "required", "cardinality"}
    )
    if missing:
        raise ArtifactContractError(f"{context} is missing: {', '.join(missing)}")
    if unknown:
        raise ArtifactContractError(
            f"{context} has unknown fields: {', '.join(unknown)}"
        )
    formats = value["formats"]
    if not isinstance(formats, list) or not formats:
        raise ArtifactContractError(f"{context}.formats must be a non-empty list")
    normalized_formats: list[str] = []
    for index, artifact_format in enumerate(formats):
        if not isinstance(artifact_format, str) or not ARTIFACT_FORMAT.fullmatch(
            artifact_format
        ):
            raise ArtifactContractError(
                f"{context}.formats contains invalid format "
                f"at index {index}: {artifact_format!r}"
            )
        normalized_formats.append(artifact_format)
    if len(normalized_formats) != len(set(normalized_formats)):
        raise ArtifactContractError(f"{context}.formats contains duplicates")
    required = value["required"]
    if not isinstance(required, bool):
        raise ArtifactContractError(f"{context}.required must be a boolean")
    cardinality = value.get("cardinality", "one")
    if cardinality not in ("one", "many"):
        raise ArtifactContractError(
            f"{context}.cardinality must be 'one' or 'many'"
        )
    normalized = {
        "type": _identifier(value["type"], f"{context}.type"),
        "formats": sorted(normalized_formats),
        "required": required,
    }
    if cardinality == "many":
        normalized["cardinality"] = "many"
    return normalized


def normalize_ports(value: Any, context: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ArtifactContractError(f"{context} must be an object")
    normalized: dict[str, dict[str, Any]] = {}
    for port_id in sorted(value):
        _identifier(port_id, f"{context} port id")
        normalized[port_id] = normalize_port(
            value[port_id], f"{context}.{port_id}"
        )
    return normalized
