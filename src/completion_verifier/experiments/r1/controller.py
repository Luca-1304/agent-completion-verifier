from __future__ import annotations

import re
from typing import Protocol

from ...sandbox.models import validate_relative_path
from .models import R1ControllerReceipt


_OID_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
_BRANCH_RE = re.compile(r"^r1-[A-Za-z0-9._-]+$")
_BASE_REF_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def _validate_oid(value: object) -> str:
    if not isinstance(value, str) or not _OID_RE.fullmatch(value):
        raise ValueError("Object ID must be a 40- or 64-character hexadecimal string.")
    return value.lower()


def validate_r1_branch_name(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("R1 branch name must be a non-empty string.")
    if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("R1 branch name contains unsupported whitespace or controls.")
    if "/" in value or "\\" in value or ".." in value or value == "r1-":
        raise ValueError("R1 branch name must be one reserved branch component.")
    if not _BRANCH_RE.fullmatch(value):
        raise ValueError("R1 branch name must use the reserved r1- prefix.")
    return value


def validate_r1_fixture_path(value: object) -> str:
    path = validate_relative_path(value)
    if not path.startswith("r1-fixtures/"):
        raise ValueError("R1 fixture path must use the reserved r1-fixtures/ prefix.")
    if path == "r1-fixtures":
        raise ValueError("R1 fixture path must name a file below the reserved prefix.")
    return path


def _validate_base_ref(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("Base ref must be a non-empty exact string.")
    if "\\" in value or ".." in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Base ref contains unsupported characters.")
    if not _BASE_REF_RE.fullmatch(value):
        raise ValueError("Base ref contains unsupported characters.")
    return value


def _validate_pull_number(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Pull-request number must be a positive integer.")
    return value


class R1Controller(Protocol):
    def create_branch(self, base_oid: str, branch_name: str) -> R1ControllerReceipt: ...

    def write_fixture(
        self, branch_name: str, relative_path: str, content: str
    ) -> R1ControllerReceipt: ...

    def create_pull_request(
        self, branch_name: str, base_ref: str
    ) -> R1ControllerReceipt: ...

    def close_pull_request(self, pull_number: int) -> R1ControllerReceipt: ...


class DryRunR1Controller:
    """Validation-only controller used by tests, previews, and normal CI."""

    def create_branch(self, base_oid: str, branch_name: str) -> R1ControllerReceipt:
        _validate_oid(base_oid)
        branch = validate_r1_branch_name(branch_name)
        return R1ControllerReceipt(
            action="create_branch",
            success=True,
            action_cost=1,
            private_target_ref=branch,
        )

    def write_fixture(
        self, branch_name: str, relative_path: str, content: str
    ) -> R1ControllerReceipt:
        branch = validate_r1_branch_name(branch_name)
        path = validate_r1_fixture_path(relative_path)
        if not isinstance(content, str) or not content:
            raise ValueError("Fixture content must be a non-empty string.")
        return R1ControllerReceipt(
            action="write_fixture",
            success=True,
            action_cost=1,
            private_target_ref=f"{branch}:{path}",
        )

    def create_pull_request(
        self, branch_name: str, base_ref: str
    ) -> R1ControllerReceipt:
        branch = validate_r1_branch_name(branch_name)
        base = _validate_base_ref(base_ref)
        return R1ControllerReceipt(
            action="create_pull_request",
            success=True,
            action_cost=1,
            private_target_ref=f"{branch}:{base}",
        )

    def close_pull_request(self, pull_number: int) -> R1ControllerReceipt:
        number = _validate_pull_number(pull_number)
        return R1ControllerReceipt(
            action="close_pull_request",
            success=True,
            action_cost=1,
            private_target_ref=str(number),
        )
