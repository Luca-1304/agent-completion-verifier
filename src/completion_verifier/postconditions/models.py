from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, ClassVar

_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_KINDS = frozenset({"text_file", "directory", "json_object"})
_REASON_CODES = frozenset(
    {
        "missing",
        "unsafe_path",
        "wrong_type",
        "io_error",
        "content_mismatch",
        "required_children_missing",
        "not_empty",
        "invalid_utf8",
        "invalid_json",
        "duplicate_key",
        "wrong_top_level",
        "key_mismatch",
    }
)
_EVIDENCE_KEYS = frozenset(
    {
        "exists",
        "regular_file",
        "directory",
        "size_matches",
        "content_matches",
        "required_children_present",
        "empty",
        "valid_utf8",
        "valid_json",
        "top_level_object",
        "expected_keys_present",
        "expected_values_match",
        "key_count_matches",
        "expected_key_count",
        "required_child_count",
    }
)


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{name}' must be a non-empty string.")
    if "\x00" in value:
        raise ValueError(f"'{name}' contains a NUL byte.")
    return value.strip()


def validate_relative_path(value: object) -> str:
    path = _required_text(value, "path")
    if "\\" in path or _DRIVE_PREFIX.match(path):
        raise ValueError("Path must use a portable relative POSIX form.")
    pure = PurePosixPath(path)
    if pure.is_absolute():
        raise ValueError("Path must be relative.")
    parts = path.split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError("Path traversal and empty path components are not allowed.")
    return pure.as_posix()


def _validate_direct_child(value: object) -> str:
    child = _required_text(value, "required_child")
    if child in (".", "..") or "/" in child or "\\" in child or _DRIVE_PREFIX.match(child):
        raise ValueError("Required child names must be direct portable names.")
    return child


def _canonical_digest(raw: object) -> str:
    try:
        encoded = json.dumps(
            raw,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Contract values must be canonical JSON data.") from exc
    return hashlib.sha256(encoded).hexdigest()


def _validate_schema(value: object) -> str:
    schema = _required_text(value, "schema_version")
    if schema != "1":
        raise ValueError(f"Unsupported schema_version '{schema}'.")
    return schema


@dataclass(frozen=True)
class TextFileContract:
    path: str
    expected_text: str
    contract_id: str = "postcondition"
    schema_version: str = "1"
    kind: ClassVar[str] = "text_file"

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", validate_relative_path(self.path))
        if not isinstance(self.expected_text, str):
            raise ValueError("'expected_text' must be a string.")
        object.__setattr__(self, "contract_id", _required_text(self.contract_id, "contract_id"))
        object.__setattr__(self, "schema_version", _validate_schema(self.schema_version))

    @property
    def identity_digest(self) -> str:
        return _canonical_digest(
            {
                "schema_version": self.schema_version,
                "kind": self.kind,
                "contract_id": self.contract_id,
                "path": self.path,
                "expected_text": self.expected_text,
            }
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "expected_size": len(self.expected_text.encode("utf-8")),
        }


@dataclass(frozen=True)
class DirectoryContract:
    path: str
    required_children: tuple[str, ...] = ()
    exact_empty: bool = False
    contract_id: str = "postcondition"
    schema_version: str = "1"
    kind: ClassVar[str] = "directory"

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", validate_relative_path(self.path))
        if not isinstance(self.required_children, tuple):
            raise ValueError("'required_children' must be a tuple.")
        children = tuple(_validate_direct_child(value) for value in self.required_children)
        if len(children) != len(set(children)):
            raise ValueError("Duplicate required child names are not allowed.")
        if not isinstance(self.exact_empty, bool):
            raise ValueError("'exact_empty' must be boolean.")
        if self.exact_empty and children:
            raise ValueError("'exact_empty' cannot be combined with required children.")
        object.__setattr__(self, "required_children", tuple(sorted(children)))
        object.__setattr__(self, "contract_id", _required_text(self.contract_id, "contract_id"))
        object.__setattr__(self, "schema_version", _validate_schema(self.schema_version))

    @property
    def identity_digest(self) -> str:
        return _canonical_digest(
            {
                "schema_version": self.schema_version,
                "kind": self.kind,
                "contract_id": self.contract_id,
                "path": self.path,
                "required_children": list(self.required_children),
                "exact_empty": self.exact_empty,
            }
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "required_child_count": len(self.required_children),
            "exact_empty": self.exact_empty,
        }


@dataclass(frozen=True)
class JsonObjectContract:
    path: str
    expected: dict[str, object]
    exact_keys: bool = False
    contract_id: str = "postcondition"
    schema_version: str = "1"
    kind: ClassVar[str] = "json_object"

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", validate_relative_path(self.path))
        if not isinstance(self.expected, dict):
            raise ValueError("'expected' must be an object.")
        if not all(isinstance(key, str) and key.strip() for key in self.expected):
            raise ValueError("Expected JSON keys must be non-empty strings.")
        if not isinstance(self.exact_keys, bool):
            raise ValueError("'exact_keys' must be boolean.")
        expected = dict(self.expected)
        _canonical_digest(expected)
        object.__setattr__(self, "expected", expected)
        object.__setattr__(self, "contract_id", _required_text(self.contract_id, "contract_id"))
        object.__setattr__(self, "schema_version", _validate_schema(self.schema_version))

    @property
    def identity_digest(self) -> str:
        return _canonical_digest(
            {
                "schema_version": self.schema_version,
                "kind": self.kind,
                "contract_id": self.contract_id,
                "path": self.path,
                "expected": self.expected,
                "exact_keys": self.exact_keys,
            }
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "expected_key_count": len(self.expected),
            "exact_keys": self.exact_keys,
        }


PostconditionContract = TextFileContract | DirectoryContract | JsonObjectContract


@dataclass(frozen=True)
class PostconditionObservation:
    kind: str
    trusted: bool
    matches: bool
    evidence: dict[str, object] = field(default_factory=dict)
    reason: str | None = None
    trust_basis: str = "independent_local_state"

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError("Unknown postcondition observation kind.")
        if not isinstance(self.trusted, bool) or not isinstance(self.matches, bool):
            raise ValueError("Observation trust and match fields must be boolean.")
        if self.trust_basis != "independent_local_state":
            raise ValueError("Unsupported observation trust basis.")
        if self.reason is not None and self.reason not in _REASON_CODES:
            raise ValueError("Unknown postcondition reason code.")
        if not isinstance(self.evidence, dict):
            raise ValueError("Observation evidence must be an object.")
        unknown = set(self.evidence) - _EVIDENCE_KEYS
        if unknown:
            raise ValueError("Observation evidence contains unsupported fields.")
        for value in self.evidence.values():
            if not isinstance(value, (bool, int)) or isinstance(value, str):
                raise ValueError("Observation evidence values must be booleans or integers.")
        object.__setattr__(self, "evidence", dict(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "kind": self.kind,
            "trusted": self.trusted,
            "matches": self.matches,
            "evidence": dict(self.evidence),
            "reason": self.reason,
            "trust_basis": self.trust_basis,
        }
