from __future__ import annotations

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
)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{name}' must be a non-empty string.")
    return value.strip()


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"'{name}' must be a non-negative integer.")
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
    evaluation: Evaluation
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
        if not isinstance(self.observations, tuple) or not self.observations or not all(
            isinstance(item, RemoteObservation) for item in self.observations
        ):
            raise ValueError("R1 run record observations are invalid.")
        if not isinstance(self.evaluation, Evaluation):
            raise ValueError("R1 run record evaluation is invalid.")
        if self.schema_version != "1":
            raise ValueError("Unsupported R1 run-record schema version.")

    def __repr__(self) -> str:
        return "R1RunRecord()"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scenario_id": self.scenario_id,
            "source_claim": self.source_claim.to_public_dict(),
            "controller_receipts": [
                receipt.to_public_dict() for receipt in self.controller_receipts
            ],
            "observations": [observation.to_dict() for observation in self.observations],
            "remote_outcomes": [observation.outcome.value for observation in self.observations],
            "evaluation": self.evaluation.to_dict(),
        }
