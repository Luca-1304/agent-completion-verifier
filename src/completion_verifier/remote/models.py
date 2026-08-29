from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class RemoteOutcome(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    INDETERMINATE = "INDETERMINATE"


_PROVIDERS = frozenset({"github"})
_KINDS = frozenset({"pull_request"})
_MISMATCH_REASONS = frozenset(
    {
        "repository_identity_mismatch",
        "head_mismatch",
        "head_repository_mismatch",
        "base_mismatch",
        "state_mismatch",
        "merge_mismatch",
    }
)
_INDETERMINATE_REASONS = frozenset(
    {
        "authentication_failed",
        "permission_unverified",
        "resource_unobservable",
        "rate_limited",
        "redirect_rejected",
        "provider_unavailable",
        "invalid_provider_response",
        "observation_not_fresh",
    }
)
_REASON_CODES = frozenset({"matched"}) | _MISMATCH_REASONS | _INDETERMINATE_REASONS
_EVIDENCE_KEYS = frozenset(
    {
        "repository_identity_matches",
        "head_matches",
        "head_repository_matches",
        "base_matches",
        "state_matches",
        "merge_matches",
        "fresh",
    }
)


@dataclass(frozen=True, repr=False)
class RemoteObservation:
    provider: str
    kind: str
    outcome: RemoteOutcome
    trusted: bool
    reason: str
    evidence: Mapping[str, bool] = field(default_factory=dict)
    trust_basis: str = "authenticated_remote_state"
    schema_version: str = "1"

    def __post_init__(self) -> None:
        if self.provider not in _PROVIDERS:
            raise ValueError("Unsupported remote provider.")
        if self.kind not in _KINDS:
            raise ValueError("Unsupported remote observation kind.")
        if not isinstance(self.outcome, RemoteOutcome):
            raise ValueError("Unsupported remote observation outcome.")
        if not isinstance(self.trusted, bool):
            raise ValueError("'trusted' must be boolean.")
        if self.reason not in _REASON_CODES:
            raise ValueError("Unknown remote observation reason code.")
        if self.trust_basis != "authenticated_remote_state":
            raise ValueError("Unsupported remote observation trust basis.")
        if self.schema_version != "1":
            raise ValueError("Unsupported remote observation schema version.")
        if not isinstance(self.evidence, Mapping):
            raise ValueError("Remote observation evidence must be an object.")

        evidence = dict(self.evidence)
        if set(evidence) - _EVIDENCE_KEYS:
            raise ValueError("Remote observation evidence contains unsupported fields.")
        if any(not isinstance(value, bool) for value in evidence.values()):
            raise ValueError("Remote observation evidence values must be boolean.")

        if self.outcome is RemoteOutcome.MATCH:
            if not self.trusted or self.reason != "matched":
                raise ValueError("MATCH requires trusted matched evidence.")
        elif self.outcome is RemoteOutcome.MISMATCH:
            if not self.trusted or self.reason not in _MISMATCH_REASONS:
                raise ValueError("MISMATCH requires a trusted mismatch reason.")
        else:
            if self.trusted or self.reason not in _INDETERMINATE_REASONS:
                raise ValueError("INDETERMINATE requires an untrusted indeterminate reason.")

        object.__setattr__(self, "evidence", MappingProxyType(evidence))

    def __repr__(self) -> str:
        return "RemoteObservation()"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "kind": self.kind,
            "outcome": self.outcome.value,
            "trusted": self.trusted,
            "evidence": dict(self.evidence),
            "reason": self.reason,
            "trust_basis": self.trust_basis,
        }
