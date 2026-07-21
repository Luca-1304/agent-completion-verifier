from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..models import Case, Requirement
from .models import RunRequest


@dataclass(frozen=True)
class RawRunTrace:
    run_id: str
    group: str
    scenario_id: str
    seed: int
    runner: str
    runner_version: str
    trace: dict[str, Any]
    retry_count: int
    unnecessary_retry_count: int
    refused: bool
    elapsed_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    def to_case(self, requirements: tuple[Requirement, ...]) -> Case:
        raw = dict(self.trace)
        raw["case_id"] = raw.pop("trace_id")
        raw["requirements"] = [
            {
                "action": requirement.action,
                "evidence_fields": list(requirement.evidence_fields),
            }
            for requirement in requirements
        ]
        return Case.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "group": self.group,
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "runner": self.runner,
            "runner_version": self.runner_version,
            "retry_count": self.retry_count,
            "unnecessary_retry_count": self.unnecessary_retry_count,
            "refused": self.refused,
            "elapsed_ms": self.elapsed_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "trace": self.trace,
        }


class ExperimentRunner(Protocol):
    name: str
    version: str

    def run(self, request: RunRequest) -> RawRunTrace:
        ...
