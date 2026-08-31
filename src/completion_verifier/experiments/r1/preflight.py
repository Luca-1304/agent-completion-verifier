from __future__ import annotations

import re
from dataclasses import dataclass
from threading import Lock
from typing import Any

from .models import R1_CONTROLLER_ACTIONS
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
        "scenario_not_live_eligible",
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

    def __repr__(self) -> str:
        return "R1PreflightRequest()"


@dataclass(frozen=True, init=False, repr=False)
class R1LivePermit:
    _scenario_id: str
    _repository_locator: str
    _repository_id: int
    _capabilities: tuple[str, ...]
    _max_live_actions: int
    _consume_lock: Lock
    _consumed: bool

    def __init__(
        self,
        *,
        scenario_id: str,
        repository_locator: str,
        repository_id: int,
        capabilities: tuple[str, ...],
        max_live_actions: int,
        _key: object,
    ) -> None:
        if _key is not _PERMIT_KEY:
            raise ValueError("R1 live permits are issued only by successful preflight.")
        object.__setattr__(self, "_scenario_id", scenario_id)
        object.__setattr__(self, "_repository_locator", _validate_locator(repository_locator))
        object.__setattr__(self, "_repository_id", repository_id)
        object.__setattr__(self, "_capabilities", tuple(capabilities))
        object.__setattr__(self, "_max_live_actions", max_live_actions)
        object.__setattr__(self, "_consume_lock", Lock())
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

    try:
        definition = get_r1_scenario(request.scenario_id)
    except ValueError:
        return _reject("scenario_unreviewed")
    if not definition.live_eligible:
        return _reject("scenario_not_live_eligible")

    try:
        requested = _validate_capabilities(
            request.requested_capabilities, "requested_capabilities"
        )
        declared = _validate_capabilities(
            request.scenario_capabilities, "scenario_capabilities"
        )
    except ValueError:
        return _reject("capability_mismatch")
    trusted = definition.capabilities
    if (
        requested != trusted
        or declared != trusted
        or any(item not in R1_CONTROLLER_ACTIONS for item in requested)
        or any(item not in R1_CONTROLLER_ACTIONS for item in declared)
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
    required_actions = len(trusted)
    if request.max_live_actions != required_actions:
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
        repository_locator=request.target.repository_locator,
        repository_id=request.target.repository_id,
        capabilities=trusted,
        max_live_actions=request.max_live_actions,
        _key=_PERMIT_KEY,
    )
    return R1PreflightResult(True, "preflight_passed", permit)


def validate_live_permit(
    permit: R1LivePermit,
    *,
    scenario_id: str,
    repository_locator: str,
    repository_id: int,
    capabilities: tuple[str, ...],
    actions_used: int,
    action_cost: int,
) -> bool:
    if not isinstance(permit, R1LivePermit):
        return False
    try:
        locator = _validate_locator(repository_locator)
    except ValueError:
        return False
    if isinstance(repository_id, bool) or not isinstance(repository_id, int):
        return False
    if isinstance(actions_used, bool) or not isinstance(actions_used, int) or actions_used < 0:
        return False
    if isinstance(action_cost, bool) or not isinstance(action_cost, int) or action_cost <= 0:
        return False
    if not isinstance(capabilities, tuple):
        return False
    return (
        scenario_id == permit._scenario_id
        and locator == permit._repository_locator
        and repository_id == permit._repository_id
        and capabilities == permit._capabilities
        and actions_used + action_cost <= permit._max_live_actions
    )


def consume_live_permit(permit: R1LivePermit) -> bool:
    if not isinstance(permit, R1LivePermit):
        return False
    with permit._consume_lock:
        if permit._consumed:
            return False
        object.__setattr__(permit, "_consumed", True)
        return True
