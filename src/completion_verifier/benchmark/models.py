from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from ..adapters import canonical_json_sha256
from ..models import Requirement

ALLOWED_GROUPS = ("baseline", "evidence_contract", "verifier_feedback")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{name}' must be a non-empty string.")
    return value.strip()


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"'{name}' must be a non-empty list.")
    result = tuple(_text(item, name) for item in value)
    if len(result) != len(set(result)):
        noun = "group" if name == "groups" else "scenario"
        raise ValueError(f"Duplicate {noun} identifiers are not allowed.")
    return result


@dataclass(frozen=True)
class ToolOutcome:
    success: bool
    evidence: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False
    automatic: bool = False
    error_kind: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise ValueError("Tool outcome success must be boolean.")
        if not isinstance(self.evidence, dict):
            raise ValueError("Tool outcome evidence must be an object.")
        object.__setattr__(self, "evidence", dict(self.evidence))
        if not isinstance(self.retryable, bool) or not isinstance(self.automatic, bool):
            raise ValueError("Tool outcome flags must be boolean.")
        if self.error_kind is not None:
            object.__setattr__(self, "error_kind", _text(self.error_kind, "error_kind"))


@dataclass(frozen=True)
class FailureScenario:
    scenario_id: str
    description: str
    injected_failure: bool
    outcomes: tuple[ToolOutcome, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario_id", _text(self.scenario_id, "scenario_id"))
        object.__setattr__(self, "description", _text(self.description, "description"))
        if not isinstance(self.injected_failure, bool):
            raise ValueError("Scenario injected_failure must be boolean.")
        if not self.outcomes or not all(isinstance(item, ToolOutcome) for item in self.outcomes):
            raise ValueError("Scenario outcomes must be a non-empty tuple of ToolOutcome objects.")
        if self.outcomes[0].automatic:
            raise ValueError("The first scenario outcome cannot be automatic.")


@dataclass(frozen=True)
class ExperimentConfig:
    experiment_id: str
    seed: int
    repetitions: int
    groups: tuple[str, ...]
    scenarios: tuple[str, ...]
    task: str
    requirements: tuple[Requirement, ...]
    generated_at: str
    schema_version: str = "1"

    @classmethod
    def from_dict(cls, raw: object) -> "ExperimentConfig":
        if not isinstance(raw, dict):
            raise ValueError("Experiment configuration must be a JSON object.")
        experiment_id = _text(raw.get("experiment_id"), "experiment_id")
        seed = raw.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("'seed' must be an integer.")
        repetitions = raw.get("repetitions")
        if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions <= 0:
            raise ValueError("'repetitions' must be a positive integer.")
        groups = _string_tuple(raw.get("groups"), "groups")
        unknown_groups = [group for group in groups if group not in ALLOWED_GROUPS]
        if unknown_groups:
            raise ValueError("Unknown group: " + ", ".join(unknown_groups))
        scenarios = _string_tuple(raw.get("scenarios"), "scenarios")
        from .scenarios import SCENARIO_IDS

        unknown_scenarios = [name for name in scenarios if name not in SCENARIO_IDS]
        if unknown_scenarios:
            raise ValueError("Unknown scenario: " + ", ".join(unknown_scenarios))
        task = _text(raw.get("task"), "task")
        requirements_raw = raw.get("requirements")
        if not isinstance(requirements_raw, list) or len(requirements_raw) != 1:
            raise ValueError("Benchmark configuration requires exactly one requirement.")
        requirements = tuple(Requirement.from_dict(item) for item in requirements_raw)
        generated_at = _text(raw.get("generated_at"), "generated_at")
        schema_version = _text(raw.get("schema_version", "1"), "schema_version")
        if schema_version != "1":
            raise ValueError(f"Unsupported benchmark schema_version '{schema_version}'.")
        return cls(
            experiment_id,
            seed,
            repetitions,
            groups,
            scenarios,
            task,
            requirements,
            generated_at,
            schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "seed": self.seed,
            "repetitions": self.repetitions,
            "groups": list(self.groups),
            "scenarios": list(self.scenarios),
            "task": self.task,
            "requirements": [
                {
                    "action": requirement.action,
                    "evidence_fields": list(requirement.evidence_fields),
                }
                for requirement in self.requirements
            ],
            "generated_at": self.generated_at,
            "schema_version": self.schema_version,
        }

    @property
    def digest(self) -> str:
        return canonical_json_sha256(self.to_dict())


@dataclass(frozen=True)
class RunRequest:
    experiment_id: str
    run_id: str
    group: str
    scenario: FailureScenario
    repetition: int
    seed: int
    task: str
    requirements: tuple[Requirement, ...]
    config_digest: str


def derive_run_seed(experiment_seed: int, key: str) -> int:
    payload = f"{experiment_seed}:{key}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def build_run_matrix(config: ExperimentConfig) -> tuple[RunRequest, ...]:
    from .scenarios import default_scenarios

    scenario_map = default_scenarios(config.requirements[0])
    requests: list[RunRequest] = []
    for group in config.groups:
        for scenario_id in config.scenarios:
            scenario = scenario_map[scenario_id]
            for repetition in range(config.repetitions):
                identity = (
                    f"{config.experiment_id}:{group}:{scenario_id}:"
                    f"{repetition}:{config.seed}"
                )
                short = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
                run_id = f"{group}--{scenario_id}--r{repetition}--{short}"
                requests.append(
                    RunRequest(
                        experiment_id=config.experiment_id,
                        run_id=run_id,
                        group=group,
                        scenario=scenario,
                        repetition=repetition,
                        seed=derive_run_seed(config.seed, run_id),
                        task=config.task,
                        requirements=config.requirements,
                        config_digest=config.digest,
                    )
                )
    return tuple(requests)
