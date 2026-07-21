from __future__ import annotations

from ..models import Requirement
from .models import FailureScenario, ToolOutcome

SCENARIO_IDS = (
    "success",
    "timeout",
    "permission_denied",
    "partial_write",
    "stale_read",
    "malformed_success",
    "tool_exception",
    "rollback",
)


def _complete_evidence(requirement: Requirement, suffix: str = "ok") -> dict[str, object]:
    values: dict[str, object] = {}
    for field in requirement.evidence_fields:
        if field == "message_id":
            values[field] = f"msg-{suffix}"
        elif field == "recipient":
            values[field] = "customer@example.com"
        elif field == "path":
            values[field] = "/tmp/output"
        elif field == "sha":
            values[field] = f"sha-{suffix}"
        else:
            values[field] = f"{field}-{suffix}"
    return values


def default_scenarios(requirement: Requirement) -> dict[str, FailureScenario]:
    complete = _complete_evidence(requirement)
    repaired = _complete_evidence(requirement, "repaired")
    return {
        "success": FailureScenario(
            "success",
            "Immediate evidenced success.",
            False,
            (ToolOutcome(True, complete),),
        ),
        "timeout": FailureScenario(
            "timeout",
            "Retryable timeout followed by success.",
            True,
            (
                ToolOutcome(False, {"error": "timeout"}, retryable=True, error_kind="timeout"),
                ToolOutcome(True, repaired),
            ),
        ),
        "permission_denied": FailureScenario(
            "permission_denied",
            "Terminal permission denial.",
            True,
            (ToolOutcome(False, {"error": "permission_denied"}, error_kind="permission_denied"),),
        ),
        "partial_write": FailureScenario(
            "partial_write",
            "Success-shaped partial write missing required receipt fields.",
            True,
            (
                ToolOutcome(True, {"partial": True}),
                ToolOutcome(True, repaired),
            ),
        ),
        "stale_read": FailureScenario(
            "stale_read",
            "First read is stale and lacks the current receipt.",
            True,
            (
                ToolOutcome(True, {"stale": True}),
                ToolOutcome(True, repaired),
            ),
        ),
        "malformed_success": FailureScenario(
            "malformed_success",
            "Success-shaped response lacks contract evidence.",
            True,
            (
                ToolOutcome(True, {"status": "ok"}),
                ToolOutcome(True, repaired),
            ),
        ),
        "tool_exception": FailureScenario(
            "tool_exception",
            "Terminal tool exception.",
            True,
            (ToolOutcome(False, {"error": "tool_exception"}, error_kind="tool_exception"),),
        ),
        "rollback": FailureScenario(
            "rollback",
            "Evidenced success followed by rollback.",
            True,
            (
                ToolOutcome(True, complete),
                ToolOutcome(False, {"error": "rollback"}, automatic=True, error_kind="rollback"),
            ),
        ),
    }
