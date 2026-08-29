from __future__ import annotations

import math
import re
from dataclasses import dataclass


_OID = re.compile(r"^[0-9A-Fa-f]{40}$|^[0-9A-Fa-f]{64}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_STATES = frozenset({"open", "closed", "merged"})


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"'{name}' must be a positive integer.")
    return value


def _object_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not _OID.fullmatch(value):
        raise ValueError(f"'{name}' must be a 40- or 64-character hexadecimal object ID.")
    return value.lower()


def _repository_locator(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("'repository' must be a repository locator.")
    locator = value.strip()
    if not locator or len(locator) > 200 or not _REPOSITORY.fullmatch(locator):
        raise ValueError("'repository' must use owner/name form.")
    if any(ord(char) < 32 or ord(char) == 127 for char in locator):
        raise ValueError("'repository' contains a control character.")
    return locator


def _ref(value: object, name: str = "expected_base_ref") -> str:
    if not isinstance(value, str):
        raise ValueError(f"'{name}' must be a non-empty ref.")
    if not value or len(value) > 255:
        raise ValueError(f"'{name}' must be a non-empty ref of at most 255 characters.")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"'{name}' contains a control character.")
    return value


def _timestamp(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{name}' must be a finite timestamp.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"'{name}' must be a finite timestamp.")
    return result


@dataclass(frozen=True, repr=False)
class GitHubPullRequestContract:
    repository: str
    repository_id: int
    pull_number: int
    expected_head_oid: str
    expected_base_ref: str
    expected_state: str
    expected_merge_oid: str | None = None
    expected_head_repository_id: int | None = None
    schema_version: str = "1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository", _repository_locator(self.repository))
        object.__setattr__(self, "repository_id", _positive_int(self.repository_id, "repository_id"))
        object.__setattr__(self, "pull_number", _positive_int(self.pull_number, "pull_number"))
        object.__setattr__(self, "expected_head_oid", _object_id(self.expected_head_oid, "expected_head_oid"))
        object.__setattr__(self, "expected_base_ref", _ref(self.expected_base_ref))
        if self.expected_state not in _STATES:
            raise ValueError("'expected_state' must be open, closed, or merged.")
        if self.expected_merge_oid is not None:
            if self.expected_state != "merged":
                raise ValueError("'expected_merge_oid' is valid only for merged state.")
            object.__setattr__(self, "expected_merge_oid", _object_id(self.expected_merge_oid, "expected_merge_oid"))
        if self.expected_head_repository_id is not None:
            object.__setattr__(
                self,
                "expected_head_repository_id",
                _positive_int(self.expected_head_repository_id, "expected_head_repository_id"),
            )
        if self.schema_version != "1":
            raise ValueError("Unsupported GitHub contract schema version.")

    def __repr__(self) -> str:
        return "GitHubPullRequestContract()"


@dataclass(frozen=True, repr=False)
class GitHubPullRequestSnapshot:
    repository_id: int
    pull_number: int
    state: str
    merged: bool
    head_oid: str
    head_repository_id: int | None
    base_ref: str
    merge_oid: str | None
    request_started_at: float
    request_finished_at: float
    provider_date: float | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_id", _positive_int(self.repository_id, "repository_id"))
        object.__setattr__(self, "pull_number", _positive_int(self.pull_number, "pull_number"))
        if self.state not in {"open", "closed"}:
            raise ValueError("Snapshot state must be open or closed.")
        if not isinstance(self.merged, bool):
            raise ValueError("'merged' must be boolean.")
        if self.merged and self.state != "closed":
            raise ValueError("Merged snapshot state must be closed.")
        object.__setattr__(self, "head_oid", _object_id(self.head_oid, "head_oid"))
        if self.head_repository_id is not None:
            object.__setattr__(self, "head_repository_id", _positive_int(self.head_repository_id, "head_repository_id"))
        object.__setattr__(self, "base_ref", _ref(self.base_ref, "base_ref"))
        if self.merge_oid is not None:
            object.__setattr__(self, "merge_oid", _object_id(self.merge_oid, "merge_oid"))
        object.__setattr__(self, "request_started_at", _timestamp(self.request_started_at, "request_started_at"))
        object.__setattr__(self, "request_finished_at", _timestamp(self.request_finished_at, "request_finished_at"))
        if self.provider_date is not None:
            object.__setattr__(self, "provider_date", _timestamp(self.provider_date, "provider_date"))

    def __repr__(self) -> str:
        return "GitHubPullRequestSnapshot()"
