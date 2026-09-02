from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from ...models import Evaluation
from ...remote.models import RemoteObservation


R1_SCENARIOS = ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
R1_TREATMENTS = ("baseline", "evidence_contract", "verifier_feedback")
R1_CONTROLLER_ACTIONS = (
    "create_branch",
    "write_fixture",
    "create_pull_request",
    "close_pull_request",
)
R1_CONTROLLER_ERROR_CODES = (
    "provider_rejected",
    "invalid_request",
    "action_not_allowed",
    "action_budget_exceeded",
    "provider_unavailable",
    "authentication_failed",
    "permission_unverified",
    "rate_limited",
    "resource_conflict",
    "validation_failed",
    "redirect_rejected",
    "invalid_provider_response",
)
R1_RUN_STATUSES = ("observed", "preverification_aborted")
R1_ABORT_REASON_CODES = ("controller_failure", "contract_unaddressable")
_PRIVATE_OID_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{name}' must be a non-empty string.")
    return value.strip()


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"'{name}' must be a non-negative integer.")
    return value


def _private_oid(value: object, name: str) -> str:
    if not isinstance(value, str) or not _PRIVATE_OID_RE.fullmatch(value):
        raise ValueError(f"'{name}' must be a 40- or 64-character hexadecimal object ID.")
    return value.lower()


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"'{name}' must be a positive integer.")
    return value


@dataclass(frozen=True, repr=False)
class R1ExperimentConfig:
    experiment_id: str
    seed: int
    repetitions: int
    scenarios: tuple[str, ...]
    treatment: str
    scaffold_id: str
    scaffold_version: str
    max_live_actions: int
    live: bool = False
    schema_version: str = "1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "experiment_id", _text(self.experiment_id, "experiment_id"))
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("'seed' must be an integer.")
        if isinstance(self.repetitions, bool) or not isinstance(self.repetitions, int) or self.repetitions <= 0:
            raise ValueError("'repetitions' must be a positive integer.")
        if not isinstance(self.scenarios, tuple) or not self.scenarios:
            raise ValueError("'scenarios' must be a non-empty tuple.")
        if any(not isinstance(item, str) or item not in R1_SCENARIOS for item in self.scenarios):
            raise ValueError("Unknown R1 scenario.")
        if len(self.scenarios) != len(set(self.scenarios)):
            raise ValueError("Duplicate R1 scenarios are not allowed.")
        if self.treatment not in R1_TREATMENTS:
            raise ValueError("Unknown R1 treatment.")
        object.__setattr__(self, "scaffold_id", _text(self.scaffold_id, "scaffold_id"))
        object.__setattr__(self, "scaffold_version", _text(self.scaffold_version, "scaffold_version"))
        if (
            isinstance(self.max_live_actions, bool)
            or not isinstance(self.max_live_actions, int)
            or self.max_live_actions <= 0
        ):
            raise ValueError("'max_live_actions' must be a positive integer.")
        if not isinstance(self.live, bool):
            raise ValueError("'live' must be boolean.")
        if self.schema_version != "1":
            raise ValueError("Unsupported R1 experiment schema version.")

    def __repr__(self) -> str:
        return "R1ExperimentConfig()"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "seed": self.seed,
            "repetitions": self.repetitions,
            "scenarios": list(self.scenarios),
            "treatment": self.treatment,
            "scaffold_id": self.scaffold_id,
            "scaffold_version": self.scaffold_version,
            "max_live_actions": self.max_live_actions,
            "live": self.live,
        }


@dataclass(frozen=True, repr=False)
class R1SourceClaim:
    completion_claimed: bool
    retry_count: int
    refusal: bool
    action_count: int
    private_trace_ref: str | None = None
    schema_version: str = "1"

    def __post_init__(self) -> None:
        if not isinstance(self.completion_claimed, bool):
            raise ValueError("'completion_claimed' must be boolean.")
        object.__setattr__(self, "retry_count", _nonnegative_int(self.retry_count, "retry_count"))
        if not isinstance(self.refusal, bool):
            raise ValueError("'refusal' must be boolean.")
        object.__setattr__(self, "action_count", _nonnegative_int(self.action_count, "action_count"))
        if self.private_trace_ref is not None:
            object.__setattr__(
                self,
                "private_trace_ref",
                _text(self.private_trace_ref, "private_trace_ref"),
            )
        if self.schema_version != "1":
            raise ValueError("Unsupported R1 source-claim schema version.")

    def __repr__(self) -> str:
        return "R1SourceClaim()"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "completion_claimed": self.completion_claimed,
            "retry_count": self.retry_count,
            "refusal": self.refusal,
            "action_count": self.action_count,
        }


@dataclass(frozen=True, repr=False)
class R1ControllerReceipt:
    action: str
    success: bool
    action_cost: int
    error_code: str | None = None
    private_target_ref: str | None = None
    private_object_oid: str | None = None
    private_pull_number: int | None = None
    schema_version: str = "1"

    def __post_init__(self) -> None:
        if self.action not in R1_CONTROLLER_ACTIONS:
            raise ValueError("Unsupported R1 controller action.")
        if not isinstance(self.success, bool):
            raise ValueError("'success' must be boolean.")
        if isinstance(self.action_cost, bool) or not isinstance(self.action_cost, int) or self.action_cost <= 0:
            raise ValueError("'action_cost' must be a positive integer.")
        if self.error_code is not None and self.error_code not in R1_CONTROLLER_ERROR_CODES:
            raise ValueError("Unsupported R1 controller error code.")
        if self.success and self.error_code is not None:
            raise ValueError("Successful controller receipts cannot contain an error code.")
        if self.private_target_ref is not None:
            object.__setattr__(
                self,
                "private_target_ref",
                _text(self.private_target_ref, "private_target_ref"),
            )
        if self.private_object_oid is not None:
            object.__setattr__(
                self,
                "private_object_oid",
                _private_oid(self.private_object_oid, "private_object_oid"),
            )
        if self.private_pull_number is not None:
            object.__setattr__(
                self,
                "private_pull_number",
                _positive_int(self.private_pull_number, "private_pull_number"),
            )
        if not self.success and (
            self.private_object_oid is not None or self.private_pull_number is not None
        ):
            raise ValueError("Failed controller receipts cannot retain provider object identifiers.")
        if self.schema_version != "1":
            raise ValueError("Unsupported R1 controller-receipt schema version.")

    def __repr__(self) -> str:
        return "R1ControllerReceipt()"

    @property
    def public(self) -> "R1ControllerReceipt":
        return self

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "action": self.action,
            "success": self.success,
            "action_cost": self.action_cost,
            "error_code": self.error_code,
        }


@dataclass(frozen=True, repr=False)
class R1RunRecord:
    scenario_id: str
    source_claim: R1SourceClaim
    controller_receipts: tuple[R1ControllerReceipt, ...]
    observations: tuple[RemoteObservation, ...]
    evaluations: tuple[Evaluation, ...]
    verification_latency_ms: tuple[float | None, ...] = ()
    run_status: str = "observed"
    abort_reason_code: str | None = None
    schema_version: str = "1"

    def __post_init__(self) -> None:
        if self.scenario_id not in R1_SCENARIOS:
            raise ValueError("Unknown R1 scenario.")
        if not isinstance(self.source_claim, R1SourceClaim):
            raise ValueError("R1 run record requires a sealed source claim.")
        if not isinstance(self.controller_receipts, tuple) or not all(
            isinstance(item, R1ControllerReceipt) for item in self.controller_receipts
        ):
            raise ValueError("R1 run record controller receipts are invalid.")
        if self.run_status not in R1_RUN_STATUSES:
            raise ValueError("Unknown R1 run status.")
        if self.abort_reason_code is not None and self.abort_reason_code not in R1_ABORT_REASON_CODES:
            raise ValueError("Unknown R1 abort reason code.")
        if not isinstance(self.observations, tuple) or not all(
            isinstance(item, RemoteObservation) for item in self.observations
        ):
            raise ValueError("R1 run record observations are invalid.")
        if not isinstance(self.evaluations, tuple) or not all(
            isinstance(item, Evaluation) for item in self.evaluations
        ):
            raise ValueError("R1 run record evaluations are invalid.")
        if len(self.observations) != len(self.evaluations):
            raise ValueError("R1 observations and evaluations must remain one-to-one.")
        if self.run_status == "observed":
            if not self.observations or self.abort_reason_code is not None:
                raise ValueError("Observed R1 runs require remote evidence and no abort reason.")
        else:
            if self.observations or self.evaluations or self.abort_reason_code is None:
                raise ValueError("Preverification-aborted R1 runs cannot contain remote evidence.")
        latencies = self.verification_latency_ms
        if not isinstance(latencies, tuple):
            raise ValueError("R1 verification latencies must be a tuple.")
        if not latencies:
            latencies = tuple(None for _ in self.observations)
            object.__setattr__(self, "verification_latency_ms", latencies)
        if len(latencies) != len(self.observations):
            raise ValueError("R1 verification latencies must align with observations.")
        for value in latencies:
            if value is None:
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise ValueError("R1 verification latency must be finite and non-negative.")
        if self.schema_version != "1":
            raise ValueError("Unsupported R1 run-record schema version.")

    def __repr__(self) -> str:
        return "R1RunRecord()"

    @property
    def evaluation(self) -> Evaluation | None:
        return self.evaluations[-1] if self.evaluations else None

    def to_public_dict(self) -> dict[str, Any]:
        evaluation = self.evaluation
        return {
            "schema_version": self.schema_version,
            "scenario_id": self.scenario_id,
            "run_status": self.run_status,
            "abort_reason_code": self.abort_reason_code,
            "source_claim": self.source_claim.to_public_dict(),
            "controller_receipts": [
                receipt.to_public_dict() for receipt in self.controller_receipts
            ],
            "observations": [observation.to_dict() for observation in self.observations],
            "remote_outcomes": [observation.outcome.value for observation in self.observations],
            "evaluations": [item.to_dict() for item in self.evaluations],
            "evaluation": None if evaluation is None else evaluation.to_dict(),
            "verification_latency_ms": list(self.verification_latency_ms),
        }
