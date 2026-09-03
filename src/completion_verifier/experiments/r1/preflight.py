from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import R1_CONTROLLER_ACTIONS, R1_SCENARIOS
from .scenarios import get_r1_scenario


_PREFLIGHT_REASONS = frozenset(
    {
        "preflight_passed",
        "live_mode_required",
        "dry_run_active",
        "normal_ci_rejected",
        "target_id_unavailable",
        "target_identity_mismatch",
        "target_locator_unverified",
        "target_protected",
        "scenario_unreviewed",
        "capability_mismatch",
        "action_budget_invalid",
        "action_budget_exhausted",
        "artifact_destination_unsafe",
        "privacy_sentinel_failed",
        "cleanup_plan_missing",
        "verifier_credential_unavailable",
    }
)
_PERMIT_KEY = object()
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_-]{0,37}[A-Za-z0-9])?$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def _require_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"'{name}' must be boolean.")
    return value


def _positive_repository_id(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"'{name}' must be a positive integer.")
    return value


def _validate_locator(value: object) -> str:
    """Validate the conservative ASCII GitHub owner/repository subset used by R1."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("Repository locator must be a non-empty exact string.")
    if value.count("/") != 1 or "\\" in value or "\x00" in value:
        raise ValueError("Repository locator must use owner/repository form.")
    owner, repo = value.split("/", 1)
    if (
        not _OWNER_RE.fullmatch(owner)
        or not _REPOSITORY_RE.fullmatch(repo)
        or repo in {".", ".."}
    ):
        raise ValueError("Repository locator must use conservative ASCII owner/repository form.")
    return value


def _validate_capabilities(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"'{name}' must be a tuple.")
    if len(value) != len(set(value)):
        raise ValueError(f"'{name}' cannot contain duplicates.")
    if any(not isinstance(item, str) for item in value):
        raise ValueError(f"'{name}' must contain strings.")
    return value


def artifact_destination_binding(value: str | Path) -> str:
    """Return a private canonical binding for the reviewed artifact destination.

    This value is intentionally kept in memory only. It is not a public digest or
    an anonymization mechanism.
    """
    if not isinstance(value, (str, Path)):
        raise ValueError("Artifact destination must be path-like.")
    path = Path(value)
    if not str(path):
        raise ValueError("Artifact destination must be non-empty.")
    try:
        return str(path.expanduser().resolve(strict=False))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("Artifact destination cannot be canonicalized.") from exc


@dataclass(frozen=True, repr=False)
class R1LiveTarget:
    repository_locator: str
    repository_id: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_locator", _validate_locator(self.repository_locator))
        object.__setattr__(
            self,
            "repository_id",
            _positive_repository_id(self.repository_id, "repository_id"),
        )

    def __repr__(self) -> str:
        return "R1LiveTarget()"


@dataclass(frozen=True, repr=False)
class R1PreflightRequest:
    live: bool
    dry_run: bool
    normal_ci: bool
    scenario_id: str
    target: R1LiveTarget | None
    approved_repository_id: int | None
    target_locator_verified: bool
    protected_repository_ids: frozenset[int]
    requested_capabilities: tuple[str, ...]
    scenario_capabilities: tuple[str, ...]
    max_live_actions: int
    actions_used: int
    artifact_destination_new: bool
    artifact_destination_writable: bool
    privacy_sentinel_passed: bool
    cleanup_plan_defined: bool
    verifier_credential_available: bool
    artifact_destination_binding: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.protected_repository_ids, frozenset):
            raise ValueError("'protected_repository_ids' must be a frozenset.")
        if any(
            isinstance(item, bool) or not isinstance(item, int) or item <= 0
            for item in self.protected_repository_ids
        ):
            raise ValueError("Protected repository IDs must be positive integers.")
        _validate_capabilities(self.requested_capabilities, "requested_capabilities")
        _validate_capabilities(self.scenario_capabilities, "scenario_capabilities")
        if self.artifact_destination_binding is not None:
            object.__setattr__(
                self,
                "artifact_destination_binding",
                artifact_destination_binding(self.artifact_destination_binding),
            )

    def __repr__(self) -> str:
        return "R1PreflightRequest()"


@dataclass(frozen=True, init=False, repr=False)
class R1LivePermit:
    _scenario_id: str
    _repository_id: int
    _repository_locator: str
    _capabilities: tuple[str, ...]
    _max_live_actions: int
    _artifact_destination_binding: str | None
    _consumed: bool

    def __init__(
        self,
        *,
        scenario_id: str,
        repository_id: int,
        repository_locator: str,
        capabilities: tuple[str, ...],
        max_live_actions: int,
        artifact_binding: str | None,
        _key: object,
    ) -> None:
        if _key is not _PERMIT_KEY:
            raise ValueError("R1 live permits are issued only by successful preflight.")
        object.__setattr__(self, "_scenario_id", scenario_id)
        object.__setattr__(self, "_repository_id", repository_id)
        object.__setattr__(self, "_repository_locator", _validate_locator(repository_locator))
        object.__setattr__(self, "_capabilities", tuple(capabilities))
        object.__setattr__(self, "_max_live_actions", max_live_actions)
        object.__setattr__(self, "_artifact_destination_binding", artifact_binding)
        object.__setattr__(self, "_consumed", False)

    def __repr__(self) -> str:
        return "R1LivePermit()"


@dataclass(frozen=True, repr=False)
class R1PreflightResult:
    allowed: bool
    reason_code: str
    permit: R1LivePermit | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise ValueError("'allowed' must be boolean.")
        if self.reason_code not in _PREFLIGHT_REASONS:
            raise ValueError("Unknown R1 preflight reason code.")
        if self.allowed != (self.permit is not None):
            raise ValueError("Allowed preflight results require exactly one live permit.")
        if self.allowed and self.reason_code != "preflight_passed":
            raise ValueError("Allowed preflight result must use preflight_passed.")
        if not self.allowed and self.reason_code == "preflight_passed":
            raise ValueError("Rejected preflight cannot use preflight_passed.")

    def __repr__(self) -> str:
        return "R1PreflightResult()"

    def to_public_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reason_code": self.reason_code}


def _reject(reason_code: str) -> R1PreflightResult:
    return R1PreflightResult(False, reason_code, None)


def run_preflight(request: R1PreflightRequest) -> R1PreflightResult:
    if not isinstance(request, R1PreflightRequest):
        raise ValueError("R1 preflight requires an R1PreflightRequest.")

    live = _require_bool(request.live, "live")
    dry_run = _require_bool(request.dry_run, "dry_run")
    normal_ci = _require_bool(request.normal_ci, "normal_ci")
    locator_verified = _require_bool(request.target_locator_verified, "target_locator_verified")
    destination_new = _require_bool(request.artifact_destination_new, "artifact_destination_new")
    destination_writable = _require_bool(
        request.artifact_destination_writable, "artifact_destination_writable"
    )
    privacy_ok = _require_bool(request.privacy_sentinel_passed, "privacy_sentinel_passed")
    cleanup_ok = _require_bool(request.cleanup_plan_defined, "cleanup_plan_defined")
    verifier_available = _require_bool(
        request.verifier_credential_available, "verifier_credential_available"
    )

    if not live:
        return _reject("live_mode_required")
    if dry_run:
        return _reject("dry_run_active")
    if normal_ci:
        return _reject("normal_ci_rejected")

    if request.target is None or request.approved_repository_id is None:
        return _reject("target_id_unavailable")
    try:
        approved_id = _positive_repository_id(
            request.approved_repository_id, "approved_repository_id"
        )
    except ValueError:
        return _reject("target_id_unavailable")
    if request.target.repository_id != approved_id:
        return _reject("target_identity_mismatch")
    if not locator_verified:
        return _reject("target_locator_unverified")
    if request.target.repository_id in request.protected_repository_ids:
        return _reject("target_protected")

    if request.scenario_id not in R1_SCENARIOS:
        return _reject("scenario_unreviewed")
    try:
        definition = get_r1_scenario(request.scenario_id)
        requested = _validate_capabilities(
            request.requested_capabilities, "requested_capabilities"
        )
        supplied_expected = _validate_capabilities(
            request.scenario_capabilities, "scenario_capabilities"
        )
    except ValueError:
        return _reject("capability_mismatch")
    expected = definition.capabilities
    if (
        requested != expected
        or supplied_expected != expected
        or any(item not in R1_CONTROLLER_ACTIONS for item in requested)
    ):
        return _reject("capability_mismatch")

    if (
        isinstance(request.max_live_actions, bool)
        or not isinstance(request.max_live_actions, int)
        or request.max_live_actions <= 0
        or isinstance(request.actions_used, bool)
        or not isinstance(request.actions_used, int)
        or request.actions_used < 0
    ):
        return _reject("action_budget_invalid")
    required_actions = len(expected)
    if request.max_live_actions < required_actions:
        return _reject("action_budget_invalid")
    if request.actions_used + required_actions > request.max_live_actions:
        return _reject("action_budget_exhausted")

    if not destination_new or not destination_writable:
        return _reject("artifact_destination_unsafe")
    if not privacy_ok:
        return _reject("privacy_sentinel_failed")
    if not cleanup_ok:
        return _reject("cleanup_plan_missing")
    if not verifier_available:
        return _reject("verifier_credential_unavailable")

    permit = R1LivePermit(
        scenario_id=request.scenario_id,
        repository_id=request.target.repository_id,
        repository_locator=request.target.repository_locator,
        capabilities=expected,
        max_live_actions=request.max_live_actions,
        artifact_binding=request.artifact_destination_binding,
        _key=_PERMIT_KEY,
    )
    return R1PreflightResult(True, "preflight_passed", permit)


def validate_live_permit(
    permit: R1LivePermit,
    *,
    scenario_id: str,
    repository_id: int,
    capabilities: tuple[str, ...],
    actions_used: int,
    action_cost: int,
    repository_locator: str | None = None,
    artifact_binding: str | None = None,
) -> bool:
    if not isinstance(permit, R1LivePermit) or permit._consumed:
        return False
    if isinstance(repository_id, bool) or not isinstance(repository_id, int):
        return False
    if isinstance(actions_used, bool) or not isinstance(actions_used, int) or actions_used < 0:
        return False
    if isinstance(action_cost, bool) or not isinstance(action_cost, int) or action_cost <= 0:
        return False
    if not isinstance(capabilities, tuple):
        return False
    if repository_locator is not None:
        try:
            locator = _validate_locator(repository_locator)
        except ValueError:
            return False
        if locator != permit._repository_locator:
            return False
    if artifact_binding is not None:
        try:
            destination = artifact_destination_binding(artifact_binding)
        except ValueError:
            return False
        if permit._artifact_destination_binding != destination:
            return False
    return (
        scenario_id == permit._scenario_id
        and repository_id == permit._repository_id
        and capabilities == permit._capabilities
        and actions_used + action_cost <= permit._max_live_actions
    )


def consume_live_permit(
    permit: R1LivePermit,
    *,
    scenario_id: str,
    repository_id: int,
    repository_locator: str,
    capabilities: tuple[str, ...],
    artifact_binding: str | None,
) -> bool:
    """Consume a process-local permit immediately before the first live mutation."""
    if not validate_live_permit(
        permit,
        scenario_id=scenario_id,
        repository_id=repository_id,
        repository_locator=repository_locator,
        capabilities=capabilities,
        actions_used=0,
        action_cost=1,
        artifact_binding=artifact_binding,
    ):
        return False
    object.__setattr__(permit, "_consumed", True)
    return True
