from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ...remote.models import RemoteOutcome
from .models import R1_CONTROLLER_ACTIONS, R1_SCENARIOS


@dataclass(frozen=True, repr=False)
class R1ScenarioDefinition:
    scenario_id: str
    capabilities: tuple[str, ...]
    expected_outcome: RemoteOutcome
    live_eligible: bool
    requires_cleanup: bool
    second_read: bool = False

    def __post_init__(self) -> None:
        if self.scenario_id not in R1_SCENARIOS:
            raise ValueError("Unknown R1 scenario definition.")
        if not isinstance(self.capabilities, tuple) or len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("R1 scenario capabilities must be a unique tuple.")
        if any(item not in R1_CONTROLLER_ACTIONS for item in self.capabilities):
            raise ValueError("R1 scenario contains unsupported capability.")
        if not isinstance(self.expected_outcome, RemoteOutcome):
            raise ValueError("R1 scenario expected outcome is invalid.")
        if not isinstance(self.live_eligible, bool):
            raise ValueError("R1 scenario live_eligible must be boolean.")
        if not isinstance(self.requires_cleanup, bool):
            raise ValueError("R1 scenario requires_cleanup must be boolean.")
        if not isinstance(self.second_read, bool):
            raise ValueError("R1 scenario second_read must be boolean.")
        if self.live_eligible and self.capabilities != R1_CONTROLLER_ACTIONS:
            raise ValueError("Live R1 scenarios use the complete reviewed controller surface.")
        if self.live_eligible and not self.requires_cleanup:
            raise ValueError("Live R1 scenarios require cleanup.")
        if not self.live_eligible and self.capabilities:
            raise ValueError("Non-live R1 scenarios cannot request mutation capabilities.")
        if self.second_read and self.scenario_id != "S7":
            raise ValueError("Only R1 S7 may require an explicit second read.")

    def __repr__(self) -> str:
        return "R1ScenarioDefinition()"


_ALL = R1_CONTROLLER_ACTIONS

R1_SCENARIO_DEFINITIONS: Mapping[str, R1ScenarioDefinition] = MappingProxyType(
    {
        "S0": R1ScenarioDefinition("S0", _ALL, RemoteOutcome.MATCH, True, True),
        "S1": R1ScenarioDefinition("S1", _ALL, RemoteOutcome.MISMATCH, True, True),
        "S2": R1ScenarioDefinition("S2", _ALL, RemoteOutcome.MISMATCH, True, True),
        "S3": R1ScenarioDefinition("S3", _ALL, RemoteOutcome.MISMATCH, True, True),
        "S4": R1ScenarioDefinition("S4", _ALL, RemoteOutcome.MISMATCH, True, True),
        "S5": R1ScenarioDefinition(
            "S5", _ALL, RemoteOutcome.INDETERMINATE, True, True
        ),
        "S6": R1ScenarioDefinition(
            "S6", (), RemoteOutcome.INDETERMINATE, False, False
        ),
        "S7": R1ScenarioDefinition(
            "S7", _ALL, RemoteOutcome.MATCH, True, True, second_read=True
        ),
        "S8": R1ScenarioDefinition(
            "S8", (), RemoteOutcome.INDETERMINATE, False, False
        ),
    }
)


def get_r1_scenario(scenario_id: str) -> R1ScenarioDefinition:
    try:
        return R1_SCENARIO_DEFINITIONS[scenario_id]
    except (KeyError, TypeError) as exc:
        raise ValueError("Unknown R1 scenario.") from exc
