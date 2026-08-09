from __future__ import annotations

from typing import Any

from .contracts import NoctisError, TERMINAL_STATES, validate_extension


TASK_RESULT_EVENTS = {
    "task.blocked": "blocked",
    "task.completed": "completed",
    "task.failed": "failed",
    "task.input-required": "input-required",
}
TASK_EVENTS = set(TASK_RESULT_EVENTS) | {"task.canceled", "task.retried"}
RUN_EVENTS = {"run.granted", "run.revoked", "run.tasks-added"}


def task_state(definition: dict[str, Any], *, added_revision: int) -> dict[str, Any]:
    return {
        **definition,
        "added_revision": added_revision,
        "status": "pending",
        "attempt": 0,
        "revision": 0,
        "claim_id": None,
        "result": None,
        "started_at": None,
        "finished_at": None,
    }


def reduce_run_event(
    event: dict[str, Any],
    revision: int,
    grants: set[str],
    executors: list[dict[str, Any]],
    tasks: dict[str, dict[str, Any]],
    order: list[str],
) -> tuple[
    int,
    set[str],
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    list[str],
    dict[str, Any],
]:
    if event["previous_revision"] != revision:
        raise NoctisError(
            f"run event {event['id']} conflicts at revision {event['previous_revision']}"
        )
    next_grants = set(grants)
    next_executors = list(executors)
    next_tasks = dict(tasks)
    next_order = list(order)
    event_type = event["type"]
    if event_type == "run.granted":
        next_grants.update(event["data"]["requirements"])
    elif event_type == "run.revoked":
        next_grants.difference_update(event["data"]["requirements"])
    else:
        extension = validate_extension(
            event["data"]["extension"], next_executors, list(next_tasks.values())
        )
        next_executors.extend(extension["executors"])
        for definition in extension["tasks"]:
            next_tasks[definition["id"]] = task_state(
                definition, added_revision=event["revision"]
            )
            next_order.append(definition["id"])
        event = {**event, "data": {"extension": extension}}
    return (
        event["revision"],
        next_grants,
        next_executors,
        next_tasks,
        next_order,
        event,
    )


def reduce_task_event(
    task: dict[str, Any],
    event: dict[str, Any],
    result: dict[str, Any] | None,
    known_task_ids: set[str],
) -> dict[str, Any]:
    if event["previous_revision"] != task["revision"]:
        raise NoctisError(
            f"task event {event['id']} conflicts at revision {event['previous_revision']}"
        )
    event_type = event["type"]
    data = event["data"]
    if event_type in TASK_RESULT_EVENTS:
        if task["status"] != "pending":
            raise NoctisError(
                f"task {task['id']} cannot apply {event_type} from {task['status']}"
            )
        if data["attempt"] != task["attempt"] + 1:
            raise NoctisError(
                f"task {task['id']} result attempt must follow its prior durable attempt"
            )
        expected_result = f"results/{task['id']}/attempt-{data['attempt']}.json"
        if data["result"] != expected_result:
            raise NoctisError(f"task {task['id']} result path must be {expected_result}")
        if result is None:
            raise NoctisError(f"task {task['id']} result is required")
        expected_status = TASK_RESULT_EVENTS[event_type]
        if result["status"] != expected_status:
            raise NoctisError(
                f"task {task['id']} event and result status do not match"
            )
        return {
            **task,
            "status": expected_status,
            "attempt": data["attempt"],
            "revision": event["revision"],
            "claim_id": result["claim_id"],
            "result": result,
            "finished_at": event["created_at"],
        }
    if result is not None:
        raise NoctisError(f"task {task['id']} has an unexpected result")
    if event_type == "task.retried":
        if task["status"] not in {"pending", "blocked", "failed", "input-required"}:
            raise NoctisError(
                f"task {task['id']} cannot be retried from {task['status']}"
            )
        if data["attempt"] < task["attempt"] or data["attempt"] > task["attempt"] + 1:
            raise NoctisError(f"task {task['id']} retry has an invalid attempt")
        return {
            **task,
            "status": "pending",
            "attempt": data["attempt"],
            "revision": event["revision"],
            "claim_id": None,
            "result": None,
            "started_at": None,
            "finished_at": None,
        }
    if task["status"] in TERMINAL_STATES:
        raise NoctisError(f"task {task['id']} cannot be canceled from {task['status']}")
    if data["attempt"] < task["attempt"] or data["attempt"] > task["attempt"] + 1:
        raise NoctisError(f"task {task['id']} cancellation has an invalid attempt")
    if data["cascade_from"] is not None and data["cascade_from"] not in known_task_ids:
        raise NoctisError(
            f"task {task['id']} cancellation references unknown source "
            f"'{data['cascade_from']}'"
        )
    return {
        **task,
        "status": "canceled",
        "attempt": data["attempt"],
        "revision": event["revision"],
        "claim_id": None,
        "result": None,
        "finished_at": event["created_at"],
    }


def validate_dependency_states(tasks: list[dict[str, Any]]) -> None:
    by_id = {task["id"]: task for task in tasks}
    for task in tasks:
        dependency_states = [by_id[item]["status"] for item in task["needs"]]
        if task["status"] == "completed" and any(
            state != "completed" for state in dependency_states
        ):
            raise NoctisError(
                f"completed task {task['id']} has a dependency that is not completed"
            )
        if task["status"] == "pending" and any(
            state == "canceled" for state in dependency_states
        ):
            raise NoctisError(
                f"pending task {task['id']} must be canceled after a dependency is canceled"
            )


def derive_run_status(tasks: list[dict[str, Any]]) -> str:
    states = [task["status"] for task in tasks]
    if states and all(state == "completed" for state in states):
        return "completed"
    if any(state == "working" for state in states):
        return "working"
    if any(state == "input-required" for state in states):
        return "input-required"
    if any(state == "blocked" for state in states):
        return "blocked"
    if any(state == "failed" for state in states):
        return "failed"
    if states and all(state in TERMINAL_STATES for state in states):
        return "canceled"
    return "submitted"


def ready_task_ids(tasks: list[dict[str, Any]]) -> list[str]:
    by_id = {task["id"]: task for task in tasks}
    return [
        task["id"]
        for task in tasks
        if task["status"] == "pending"
        and all(by_id[item]["status"] == "completed" for item in task["needs"])
    ]


def descendants(tasks: list[dict[str, Any]], task_id: str) -> list[str]:
    selected = [task_id]
    changed = True
    while changed:
        changed = False
        for task in tasks:
            if task["id"] not in selected and set(task["needs"]) & set(selected):
                selected.append(task["id"])
                changed = True
    return selected
