from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Any

from ..adapters import canonical_json_sha256
from ..models import Case, Evaluation

_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{name}' must be a non-empty string.")
    if "\x00" in value:
        raise ValueError(f"'{name}' contains a NUL byte.")
    return value.strip()


def validate_relative_path(value: object) -> str:
    path = required_text(value, "path")
    if "\\" in path or _DRIVE_PREFIX.match(path):
        raise ValueError("Path must use a portable relative POSIX form.")
    pure = PurePosixPath(path)
    if pure.is_absolute():
        raise ValueError("Path must be relative to the sandbox root.")
    raw_parts = path.split("/")
    if not raw_parts or any(part in ("", ".", "..") for part in raw_parts):
        raise ValueError("Path traversal and empty path components are not allowed.")
    return pure.as_posix()


@dataclass(frozen=True)
class FileWriteContract:
    contract_id: str
    path: str
    content: str
    schema_version: str = "1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_id", required_text(self.contract_id, "contract_id"))
        object.__setattr__(self, "path", validate_relative_path(self.path))
        if not isinstance(self.content, str) or not self.content:
            raise ValueError("'content' must be a non-empty UTF-8 string.")
        object.__setattr__(self, "schema_version", required_text(self.schema_version, "schema_version"))
        if self.schema_version != "1":
            raise ValueError(f"Unsupported contract schema_version '{self.schema_version}'.")

    @classmethod
    def from_dict(cls, raw: object) -> "FileWriteContract":
        if not isinstance(raw, dict):
            raise ValueError("File write contract must be a JSON object.")
        return cls(
            contract_id=raw.get("contract_id"),
            path=raw.get("path"),
            content=raw.get("content"),
            schema_version=raw.get("schema_version", "1"),
        )

    @property
    def expected_bytes(self) -> bytes:
        return self.content.encode("utf-8")

    @property
    def expected_size(self) -> int:
        return len(self.expected_bytes)

    @property
    def expected_sha256(self) -> str:
        return hashlib.sha256(self.expected_bytes).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "path": self.path,
            "content": self.content,
        }

    @property
    def digest(self) -> str:
        return canonical_json_sha256(
            {**self.to_dict(), "schema_version": self.schema_version}
        )


@dataclass(frozen=True)
class SourceToolReport:
    scenario_id: str
    attempted_path: str
    reported_success: bool
    reported_evidence: dict[str, Any]
    completion_claimed: bool
    source_event_id: str
    error_kind: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario_id", required_text(self.scenario_id, "scenario_id"))
        object.__setattr__(self, "attempted_path", required_text(self.attempted_path, "attempted_path"))
        if not isinstance(self.reported_success, bool) or not isinstance(self.completion_claimed, bool):
            raise ValueError("Source report success and completion claim must be boolean.")
        if not isinstance(self.reported_evidence, dict):
            raise ValueError("Source reported evidence must be an object.")
        object.__setattr__(self, "reported_evidence", dict(self.reported_evidence))
        object.__setattr__(self, "source_event_id", required_text(self.source_event_id, "source_event_id"))
        if self.error_kind is not None:
            object.__setattr__(self, "error_kind", required_text(self.error_kind, "error_kind"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "attempted_path": self.attempted_path,
            "reported_success": self.reported_success,
            "reported_evidence": dict(self.reported_evidence),
            "completion_claimed": self.completion_claimed,
            "source_event_id": self.source_event_id,
            "error_kind": self.error_kind,
        }


@dataclass(frozen=True)
class FileObservation:
    contract_id: str
    path: str
    confined: bool
    exists: bool
    regular_file: bool
    size: int | None
    sha256: str | None
    matches_content: bool
    matches_contract: bool
    error: str | None = None
    trust_basis: str = "independent_local_state"

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "path": self.path,
            "confined": self.confined,
            "exists": self.exists,
            "regular_file": self.regular_file,
            "size": self.size,
            "sha256": self.sha256,
            "matches_content": self.matches_content,
            "matches_contract": self.matches_contract,
            "error": self.error,
            "trust_basis": self.trust_basis,
        }


@dataclass(frozen=True)
class SandboxRunResult:
    scenario_id: str
    contract: FileWriteContract
    report: SourceToolReport
    observation: FileObservation
    case: Case
    evaluation: Evaluation
    security_rejected: bool = False

    def result_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "reported_success": self.report.reported_success,
            "completion_claimed": self.report.completion_claimed,
            "matches_contract": self.observation.matches_contract,
            "security_rejected": self.security_rejected,
            "status": self.evaluation.status.value,
        }


@dataclass(frozen=True)
class SandboxSuiteConfig:
    suite_id: str
    generated_at: str
    scenarios: tuple[str, ...]
    contract: FileWriteContract
    schema_version: str = "1"

    @classmethod
    def from_dict(cls, raw: object) -> "SandboxSuiteConfig":
        if not isinstance(raw, dict):
            raise ValueError("Sandbox suite configuration must be a JSON object.")
        from .scenarios import SCENARIO_IDS

        suite_id = required_text(raw.get("suite_id"), "suite_id")
        generated_at = required_text(raw.get("generated_at"), "generated_at")
        scenarios_raw = raw.get("scenarios")
        if not isinstance(scenarios_raw, list) or not scenarios_raw:
            raise ValueError("'scenarios' must be a non-empty list.")
        scenarios = tuple(required_text(item, "scenario") for item in scenarios_raw)
        if len(scenarios) != len(set(scenarios)):
            raise ValueError("Duplicate scenario identifiers are not allowed.")
        unknown = [item for item in scenarios if item not in SCENARIO_IDS]
        if unknown:
            raise ValueError("Unknown scenario: " + ", ".join(unknown))
        contract = FileWriteContract.from_dict(raw.get("contract"))
        schema_version = required_text(raw.get("schema_version", "1"), "schema_version")
        if schema_version != "1":
            raise ValueError(f"Unsupported sandbox schema_version '{schema_version}'.")
        return cls(suite_id, generated_at, scenarios, contract, schema_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "generated_at": self.generated_at,
            "scenarios": list(self.scenarios),
            "contract": self.contract.to_dict(),
            "schema_version": self.schema_version,
        }

    @property
    def digest(self) -> str:
        return canonical_json_sha256(self.to_dict())

    def with_scenarios(self, scenarios: tuple[str, ...]) -> "SandboxSuiteConfig":
        return replace(self, scenarios=scenarios)
