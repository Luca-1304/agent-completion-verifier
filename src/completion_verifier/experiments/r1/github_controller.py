from __future__ import annotations

import base64
import http.client
import json
import math
from typing import Callable, Protocol
from urllib.parse import quote

from .controller import (
    _validate_base_ref,
    _validate_oid,
    _validate_pull_number,
    validate_r1_branch_name,
    validate_r1_fixture_path,
)
from .models import R1ControllerReceipt
from .preflight import R1LiveTarget


_GITHUB_HOST = "api.github.com"
_API_VERSION = "2022-11-28"
_USER_AGENT = "agent-completion-verifier-r1/0.8"


class R1GitHubCredentialProvider(Protocol):
    def authorization_header(self) -> str: ...


def _valid_authorization_header(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    )


def _rate_limited(response: object) -> bool:
    try:
        retry_after = response.getheader("Retry-After")  # type: ignore[attr-defined]
        remaining = response.getheader("X-RateLimit-Remaining")  # type: ignore[attr-defined]
    except Exception:
        return False
    return bool(retry_after) or remaining == "0"


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate provider response key.")
        result[key] = value
    return result


def _status_error(response: object, status: int) -> str | None:
    if status == 401:
        return "authentication_failed"
    if status == 403:
        return "rate_limited" if _rate_limited(response) else "permission_unverified"
    if status == 404:
        return "permission_unverified"
    if status == 409:
        return "resource_conflict"
    if status == 422:
        return "validation_failed"
    if status == 429:
        return "rate_limited"
    if 300 <= status <= 399:
        return "redirect_rejected"
    if status >= 500:
        return "provider_unavailable"
    if 400 <= status <= 499:
        return "provider_rejected"
    return None


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Provider pull-request number is invalid.")
    return value


class GitHubR1Controller:
    """Capability-minimal GitHub writer for the reviewed R1 experiment only.

    Each public method performs at most one declared mutation request. It does
    not retry, follow redirects, discover state, merge, reopen, or delete.
    """

    def __init__(
        self,
        credential_provider: R1GitHubCredentialProvider,
        target: R1LiveTarget,
        *,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 32_768,
        max_fixture_bytes: int = 16_384,
        connection_factory: Callable[..., object] | None = None,
    ) -> None:
        if not isinstance(target, R1LiveTarget):
            raise ValueError("R1 GitHub controller requires an R1LiveTarget.")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or float(timeout_seconds) <= 0
        ):
            raise ValueError("'timeout_seconds' must be a finite positive number.")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or max_response_bytes <= 0
        ):
            raise ValueError("'max_response_bytes' must be a positive integer.")
        if (
            isinstance(max_fixture_bytes, bool)
            or not isinstance(max_fixture_bytes, int)
            or max_fixture_bytes <= 0
        ):
            raise ValueError("'max_fixture_bytes' must be a positive integer.")
        self._credential_provider = credential_provider
        self._target = target
        self._timeout_seconds = float(timeout_seconds)
        self._max_response_bytes = max_response_bytes
        self._max_fixture_bytes = max_fixture_bytes
        self._connection_factory = connection_factory or http.client.HTTPSConnection

    def __repr__(self) -> str:
        return "GitHubR1Controller()"

    def _failed(self, action: str, code: str) -> R1ControllerReceipt:
        return R1ControllerReceipt(
            action=action,
            success=False,
            action_cost=1,
            error_code=code,
        )

    def _request(
        self,
        *,
        action: str,
        method: str,
        path: str,
        payload: dict[str, object],
        success_statuses: tuple[int, ...],
    ) -> tuple[dict[str, object] | None, R1ControllerReceipt | None]:
        try:
            authorization = self._credential_provider.authorization_header()
        except Exception:
            return None, self._failed(action, "authentication_failed")
        if not _valid_authorization_header(authorization):
            return None, self._failed(action, "authentication_failed")

        connection = None
        try:
            connection = self._connection_factory(
                _GITHUB_HOST,
                timeout=self._timeout_seconds,
            )
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": _API_VERSION,
                "User-Agent": _USER_AGENT,
                "Authorization": authorization,
                "Content-Type": "application/json",
            }
            body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            connection.request(method, path, body=body, headers=headers)  # type: ignore[attr-defined]
            response = connection.getresponse()  # type: ignore[attr-defined]
            status = response.status  # type: ignore[attr-defined]

            error = _status_error(response, status)
            if error is not None:
                return None, self._failed(action, error)
            if status not in success_statuses:
                return None, self._failed(action, "invalid_provider_response")

            raw_body = response.read(self._max_response_bytes + 1)  # type: ignore[attr-defined]
            if len(raw_body) > self._max_response_bytes:
                return None, self._failed(action, "invalid_provider_response")
            try:
                raw = json.loads(raw_body.decode("utf-8"), object_pairs_hook=_strict_object)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                return None, self._failed(action, "invalid_provider_response")
            if not isinstance(raw, dict):
                return None, self._failed(action, "invalid_provider_response")
            return raw, None
        except (OSError, TimeoutError, http.client.HTTPException, TypeError, ValueError, OverflowError):
            return None, self._failed(action, "provider_unavailable")
        finally:
            if connection is not None:
                try:
                    connection.close()  # type: ignore[attr-defined]
                except Exception:
                    pass

    @property
    def _repository_path(self) -> str:
        return quote(self._target.repository_locator, safe="/")

    def create_branch(self, base_oid: str, branch_name: str) -> R1ControllerReceipt:
        oid = _validate_oid(base_oid)
        branch = validate_r1_branch_name(branch_name)
        raw, failure = self._request(
            action="create_branch",
            method="POST",
            path=f"/repos/{self._repository_path}/git/refs",
            payload={"ref": f"refs/heads/{branch}", "sha": oid},
            success_statuses=(201,),
        )
        if failure is not None:
            return failure
        try:
            assert raw is not None
            obj = raw.get("object")
            if not isinstance(obj, dict):
                raise ValueError
            returned_oid = _validate_oid(obj.get("sha"))
            if returned_oid != oid:
                raise ValueError
        except (TypeError, ValueError):
            return self._failed("create_branch", "invalid_provider_response")
        return R1ControllerReceipt(
            action="create_branch",
            success=True,
            action_cost=1,
            private_object_oid=returned_oid,
        )

    def write_fixture(
        self,
        branch_name: str,
        relative_path: str,
        content: str,
        *,
        existing_blob_sha: str | None = None,
    ) -> R1ControllerReceipt:
        branch = validate_r1_branch_name(branch_name)
        path = validate_r1_fixture_path(relative_path)
        if not isinstance(content, str) or not content:
            raise ValueError("Fixture content must be a non-empty string.")
        encoded_content = content.encode("utf-8")
        if len(encoded_content) > self._max_fixture_bytes:
            raise ValueError("Fixture content exceeds the configured byte limit.")
        existing = None
        if existing_blob_sha is not None:
            existing = _validate_oid(existing_blob_sha)

        payload: dict[str, object] = {
            "message": "R1 experiment fixture update",
            "content": base64.b64encode(encoded_content).decode("ascii"),
            "branch": branch,
        }
        if existing is not None:
            payload["sha"] = existing
        raw, failure = self._request(
            action="write_fixture",
            method="PUT",
            path=f"/repos/{self._repository_path}/contents/{quote(path, safe='/')}",
            payload=payload,
            success_statuses=(200, 201),
        )
        if failure is not None:
            return failure
        try:
            assert raw is not None
            commit = raw.get("commit")
            if not isinstance(commit, dict):
                raise ValueError
            commit_oid = _validate_oid(commit.get("sha"))
        except (TypeError, ValueError):
            return self._failed("write_fixture", "invalid_provider_response")
        return R1ControllerReceipt(
            action="write_fixture",
            success=True,
            action_cost=1,
            private_object_oid=commit_oid,
        )

    def create_pull_request(
        self, branch_name: str, base_ref: str
    ) -> R1ControllerReceipt:
        branch = validate_r1_branch_name(branch_name)
        base = _validate_base_ref(base_ref)
        raw, failure = self._request(
            action="create_pull_request",
            method="POST",
            path=f"/repos/{self._repository_path}/pulls",
            payload={
                "title": "R1 controlled experiment",
                "head": branch,
                "base": base,
                "draft": True,
            },
            success_statuses=(201,),
        )
        if failure is not None:
            return failure
        try:
            assert raw is not None
            number = _positive_int(raw.get("number"))
        except (TypeError, ValueError):
            return self._failed("create_pull_request", "invalid_provider_response")
        return R1ControllerReceipt(
            action="create_pull_request",
            success=True,
            action_cost=1,
            private_pull_number=number,
        )

    def close_pull_request(self, pull_number: int) -> R1ControllerReceipt:
        number = _validate_pull_number(pull_number)
        raw, failure = self._request(
            action="close_pull_request",
            method="PATCH",
            path=f"/repos/{self._repository_path}/pulls/{number}",
            payload={"state": "closed"},
            success_statuses=(200,),
        )
        if failure is not None:
            return failure
        try:
            assert raw is not None
            returned_number = _positive_int(raw.get("number"))
            state = raw.get("state")
            if returned_number != number or state != "closed":
                raise ValueError
        except (TypeError, ValueError):
            return self._failed("close_pull_request", "invalid_provider_response")
        return R1ControllerReceipt(
            action="close_pull_request",
            success=True,
            action_cost=1,
            private_pull_number=returned_number,
        )
