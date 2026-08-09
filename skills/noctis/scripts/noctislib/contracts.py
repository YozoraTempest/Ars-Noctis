from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Any


IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.:-][a-z0-9]+)*$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
RESULT_STATES = {"blocked", "completed", "failed", "input-required"}
TERMINAL_STATES = {"canceled", "completed"}


class NoctisError(ValueError):
    """Raised when a Noctis contract or state transition is invalid."""


def object_value(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise NoctisError(f"{context} must be an object with string keys")
    return value


def exact(value: dict[str, Any], fields: set[str], context: str) -> None:
    missing = sorted(fields - set(value))
    unknown = sorted(set(value) - fields)
    if missing:
        raise NoctisError(f"{context} is missing: {', '.join(missing)}")
    if unknown:
        raise NoctisError(f"{context} has unknown fields: {', '.join(unknown)}")


def text_value(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NoctisError(f"{context} must be a non-empty string")
    return value.strip()


def identifier(value: Any, context: str) -> str:
    result = text_value(value, context)
    if not IDENTIFIER.fullmatch(result):
        raise NoctisError(f"{context} has an invalid identifier: {result}")
    return result


def uuid_value(value: Any, context: str) -> str:
    result = text_value(value, context)
    try:
        parsed = uuid.UUID(result)
    except ValueError as error:
        raise NoctisError(f"{context} must be a UUID") from error
    if str(parsed) != result:
        raise NoctisError(f"{context} must use canonical lowercase UUID form")
    return result


def integer_value(value: Any, context: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise NoctisError(f"{context} must be an integer greater than or equal to {minimum}")
    return value


def timestamp_value(value: Any, context: str) -> str:
    result = text_value(value, context)
    try:
        parsed = datetime.fromisoformat(result)
    except ValueError as error:
        raise NoctisError(f"{context} must be an ISO 8601 timestamp") from error
    if parsed.tzinfo is None:
        raise NoctisError(f"{context} must include a timezone")
    return result


def string_list(value: Any, context: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise NoctisError(f"{context} must be a list")
    result = [identifier(item, f"{context}[{index}]") for index, item in enumerate(value)]
    if nonempty and not result:
        raise NoctisError(f"{context} must not be empty")
    if len(result) != len(set(result)):
        raise NoctisError(f"{context} contains duplicates")
    return result


def json_value(value: Any, context: str) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise NoctisError(f"{context} must be strict JSON") from error
    return value


def canonical_digest(value: Any) -> str:
    payload = json.dumps(
        json_value(value, "value"),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def validate_executor(value: Any, context: str) -> dict[str, Any]:
    executor = object_value(value, context)
    exact(executor, {"id", "kind", "snapshot", "digest"}, context)
    snapshot = json_value(executor["snapshot"], f"{context}.snapshot")
    digest = executor["digest"]
    if digest is not None:
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise NoctisError(f"{context}.digest must be null or sha256:<64 lowercase hex>")
        if canonical_digest(snapshot) != digest:
            raise NoctisError(f"{context}.digest does not match its snapshot")
    return {
        "id": identifier(executor["id"], f"{context}.id"),
        "kind": identifier(executor["kind"], f"{context}.kind"),
        "snapshot": snapshot,
        "digest": digest,
    }


def validate_task(value: Any, context: str) -> dict[str, Any]:
    task = object_value(value, context)
    exact(task, {"id", "needs", "executor", "request", "requirements"}, context)
    return {
        "id": identifier(task["id"], f"{context}.id"),
        "needs": string_list(task["needs"], f"{context}.needs"),
        "executor": identifier(task["executor"], f"{context}.executor"),
        "request": json_value(task["request"], f"{context}.request"),
        "requirements": sorted(
            string_list(task["requirements"], f"{context}.requirements")
        ),
    }


def validate_graph(tasks: list[dict[str, Any]]) -> None:
    ids = [task["id"] for task in tasks]
    if len(ids) != len(set(ids)):
        raise NoctisError("task ids must be unique")
    known = set(ids)
    dependencies = {task["id"]: task["needs"] for task in tasks}
    for task in tasks:
        unknown = sorted(set(task["needs"]) - known)
        if unknown:
            raise NoctisError(
                f"task '{task['id']}' needs unknown tasks: {', '.join(unknown)}"
            )
        if task["id"] in task["needs"]:
            raise NoctisError(f"task '{task['id']}' cannot depend on itself")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise NoctisError(f"task graph contains a cycle at '{task_id}'")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in dependencies[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in dependencies:
        visit(task_id)


def validate_plan(value: Any) -> dict[str, Any]:
    plan = object_value(value, "plan")
    exact(plan, {"schema", "title", "objective", "executors", "tasks"}, "plan")
    if plan["schema"] != "noctis.plan/v1":
        raise NoctisError("plan.schema must be 'noctis.plan/v1'")
    raw_executors = plan["executors"]
    if not isinstance(raw_executors, list) or not raw_executors:
        raise NoctisError("plan.executors must be a non-empty list")
    executors = [
        validate_executor(item, f"plan.executors[{index}]")
        for index, item in enumerate(raw_executors)
    ]
    executor_ids = [item["id"] for item in executors]
    if len(executor_ids) != len(set(executor_ids)):
        raise NoctisError("plan repeats executor ids")
    raw_tasks = plan["tasks"]
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise NoctisError("plan.tasks must be a non-empty list")
    tasks = [validate_task(item, f"plan.tasks[{index}]") for index, item in enumerate(raw_tasks)]
    known_executors = set(executor_ids)
    for task in tasks:
        if task["executor"] not in known_executors:
            raise NoctisError(
                f"task '{task['id']}' references unknown executor '{task['executor']}'"
            )
    validate_graph(tasks)
    return {
        "schema": "noctis.plan/v1",
        "title": text_value(plan["title"], "plan.title"),
        "objective": text_value(plan["objective"], "plan.objective"),
        "executors": executors,
        "tasks": tasks,
    }


def validate_origin(value: Any, context: str = "origin") -> dict[str, Any]:
    origin = object_value(value, context)
    exact(origin, {"kind", "summary", "reference"}, context)
    reference = origin["reference"]
    if reference is not None:
        reference = text_value(reference, f"{context}.reference")
    return {
        "kind": identifier(origin["kind"], f"{context}.kind"),
        "summary": text_value(origin["summary"], f"{context}.summary"),
        "reference": reference,
    }


def validate_extension(
    value: Any,
    existing_executors: list[dict[str, Any]],
    existing_tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    extension = object_value(value, "extension")
    exact(extension, {"schema", "origin", "executors", "tasks"}, "extension")
    if extension["schema"] != "noctis.extension/v1":
        raise NoctisError("extension.schema must be 'noctis.extension/v1'")
    raw_executors = extension["executors"]
    if not isinstance(raw_executors, list):
        raise NoctisError("extension.executors must be a list")
    added_executors = [
        validate_executor(item, f"extension.executors[{index}]")
        for index, item in enumerate(raw_executors)
    ]
    if len({item["id"] for item in added_executors}) != len(added_executors):
        raise NoctisError("extension repeats executor ids")
    by_executor = {item["id"]: item for item in existing_executors}
    new_executors: list[dict[str, Any]] = []
    for executor in added_executors:
        previous = by_executor.get(executor["id"])
        if previous is not None and previous != executor:
            raise NoctisError(
                f"extension changes existing executor '{executor['id']}'"
            )
        if previous is None:
            by_executor[executor["id"]] = executor
            new_executors.append(executor)

    raw_tasks = extension["tasks"]
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise NoctisError("extension.tasks must be a non-empty list")
    added_tasks = [
        validate_task(item, f"extension.tasks[{index}]")
        for index, item in enumerate(raw_tasks)
    ]
    existing_ids = {item["id"] for item in existing_tasks}
    repeated = sorted(existing_ids & {item["id"] for item in added_tasks})
    if repeated:
        raise NoctisError("extension reuses task ids: " + ", ".join(repeated))
    for task in added_tasks:
        if task["executor"] not in by_executor:
            raise NoctisError(
                f"task '{task['id']}' references unknown executor '{task['executor']}'"
            )
    combined = [*existing_tasks, *added_tasks]
    validate_graph(combined)
    return {
        "schema": "noctis.extension/v1",
        "origin": validate_origin(extension["origin"], "extension.origin"),
        "executors": new_executors,
        "tasks": added_tasks,
    }


def validate_result(
    value: Any,
    run_id: str,
    task_id: str,
    claim_id: str,
    attempt: int,
) -> dict[str, Any]:
    result = object_value(value, "result")
    exact(
        result,
        {
            "schema",
            "run_id",
            "task_id",
            "claim_id",
            "attempt",
            "status",
            "summary",
            "output",
        },
        "result",
    )
    if result["schema"] != "noctis.result/v1":
        raise NoctisError("result.schema must be 'noctis.result/v1'")
    if result["run_id"] != run_id or result["task_id"] != task_id:
        raise NoctisError("result run_id/task_id does not match the claimed task")
    if result["claim_id"] != claim_id or result["attempt"] != attempt:
        raise NoctisError("result claim_id/attempt is stale")
    status = result["status"]
    if status not in RESULT_STATES:
        raise NoctisError(
            "result.status must be blocked, completed, failed, or input-required"
        )
    return {
        "schema": "noctis.result/v1",
        "run_id": run_id,
        "task_id": task_id,
        "claim_id": claim_id,
        "attempt": attempt,
        "status": status,
        "summary": text_value(result["summary"], "result.summary"),
        "output": json_value(result["output"], "result.output"),
    }
