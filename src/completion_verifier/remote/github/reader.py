from __future__ import annotations

import http.client
import json
import math
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Protocol

from .contracts import GitHubPullRequestContract, GitHubPullRequestSnapshot
from .verifier import GitHubReadResult


_GITHUB_HOST = "api.github.com"
_API_VERSION = "2022-11-28"
_USER_AGENT = "agent-completion-verifier/0.8"


class GitHubCredentialProvider(Protocol):
    def authorization_header(self) -> str:
        ...


def _valid_authorization_header(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return not any(ord(char) < 32 or ord(char) == 127 for char in value)


def _rate_limited(response: object) -> bool:
    try:
        retry_after = response.getheader("Retry-After")  # type: ignore[attr-defined]
        remaining = response.getheader("X-RateLimit-Remaining")  # type: ignore[attr-defined]
    except Exception:
        return False
    return bool(retry_after) or remaining == "0"


def _parse_provider_date(response: object) -> float | None:
    try:
        raw = response.getheader("Date")  # type: ignore[attr-defined]
    except Exception as exc:
        raise ValueError("Invalid provider date header.") from exc
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw:
        raise ValueError("Invalid provider date header.")
    try:
        value = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid provider date header.") from exc
    if value is None:
        raise ValueError("Invalid provider date header.")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate provider response key.")
        result[key] = value
    return result


def _normalize_snapshot(
    raw: object,
    *,
    request_started_at: float,
    request_finished_at: float,
    provider_date: float | None,
) -> GitHubPullRequestSnapshot:
    if not isinstance(raw, dict):
        raise ValueError("Provider response must be an object.")

    number = raw.get("number")
    state = raw.get("state")
    merged = raw.get("merged")
    head = raw.get("head")
    base = raw.get("base")
    merge_oid = raw.get("merge_commit_sha")

    if not isinstance(head, dict) or not isinstance(base, dict):
        raise ValueError("Provider response has invalid pull-request shape.")
    head_oid = head.get("sha")
    head_repo = head.get("repo")
    base_ref = base.get("ref")
    base_repo = base.get("repo")
    if head_repo is not None and not isinstance(head_repo, dict):
        raise ValueError("Provider response has invalid head repository shape.")
    if not isinstance(base_repo, dict):
        raise ValueError("Provider response has invalid base repository shape.")

    head_repository_id = None if head_repo is None else head_repo.get("id")
    repository_id = base_repo.get("id")

    if isinstance(state, bool) or not isinstance(state, str):
        raise ValueError("Provider response has invalid state.")
    if not isinstance(merged, bool):
        raise ValueError("Provider response has invalid merged value.")
    if merge_oid is not None and not isinstance(merge_oid, str):
        raise ValueError("Provider response has invalid merge object ID.")

    return GitHubPullRequestSnapshot(
        repository_id=repository_id,  # type: ignore[arg-type]
        pull_number=number,  # type: ignore[arg-type]
        state=state,
        merged=merged,
        head_oid=head_oid,  # type: ignore[arg-type]
        head_repository_id=head_repository_id,  # type: ignore[arg-type]
        base_ref=base_ref,  # type: ignore[arg-type]
        merge_oid=merge_oid,
        request_started_at=request_started_at,
        request_finished_at=request_finished_at,
        provider_date=provider_date,
    )


class GitHubRESTReader:
    def __init__(
        self,
        credential_provider: GitHubCredentialProvider,
        *,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_048_576,
        connection_factory: Callable[..., object] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise ValueError("'timeout_seconds' must be a finite positive number.")
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("'timeout_seconds' must be a finite positive number.")
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or max_response_bytes <= 0:
            raise ValueError("'max_response_bytes' must be a positive integer.")
        if not callable(clock):
            raise ValueError("'clock' must be callable.")
        self._credential_provider = credential_provider
        self._timeout_seconds = timeout
        self._max_response_bytes = max_response_bytes
        self._connection_factory = connection_factory or http.client.HTTPSConnection
        self._clock = clock

    def __repr__(self) -> str:
        return "GitHubRESTReader()"

    def read_pull_request(self, contract: GitHubPullRequestContract) -> GitHubReadResult:
        if not isinstance(contract, GitHubPullRequestContract):
            return GitHubReadResult(snapshot=None, reason="invalid_provider_response")

        try:
            authorization = self._credential_provider.authorization_header()
        except Exception:
            return GitHubReadResult(snapshot=None, reason="authentication_failed")
        if not _valid_authorization_header(authorization):
            return GitHubReadResult(snapshot=None, reason="authentication_failed")

        connection = None
        try:
            started = float(self._clock())
            connection = self._connection_factory(
                _GITHUB_HOST,
                timeout=self._timeout_seconds,
            )
            path = f"/repos/{contract.repository}/pulls/{contract.pull_number}"
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": _API_VERSION,
                "User-Agent": _USER_AGENT,
                "Authorization": authorization,
            }
            connection.request("GET", path, body=None, headers=headers)  # type: ignore[attr-defined]
            response = connection.getresponse()  # type: ignore[attr-defined]
            status = response.status  # type: ignore[attr-defined]

            if status == 401:
                return GitHubReadResult(snapshot=None, reason="authentication_failed")
            if status == 404:
                return GitHubReadResult(snapshot=None, reason="resource_unobservable")
            if status == 429:
                return GitHubReadResult(snapshot=None, reason="rate_limited")
            if status == 403:
                reason = "rate_limited" if _rate_limited(response) else "permission_unverified"
                return GitHubReadResult(snapshot=None, reason=reason)
            if 300 <= status <= 399:
                return GitHubReadResult(snapshot=None, reason="redirect_rejected")
            if status >= 500:
                return GitHubReadResult(snapshot=None, reason="provider_unavailable")
            if status != 200:
                return GitHubReadResult(snapshot=None, reason="invalid_provider_response")

            body = response.read(self._max_response_bytes + 1)  # type: ignore[attr-defined]
            finished = float(self._clock())
            if len(body) > self._max_response_bytes:
                return GitHubReadResult(snapshot=None, reason="invalid_provider_response")
            try:
                text = body.decode("utf-8")
                raw = json.loads(text, object_pairs_hook=_strict_object)
                provider_date = _parse_provider_date(response)
                snapshot = _normalize_snapshot(
                    raw,
                    request_started_at=started,
                    request_finished_at=finished,
                    provider_date=provider_date,
                )
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, OverflowError):
                return GitHubReadResult(snapshot=None, reason="invalid_provider_response")
            return GitHubReadResult(snapshot=snapshot)
        except (OSError, TimeoutError, http.client.HTTPException, TypeError, ValueError, OverflowError):
            return GitHubReadResult(snapshot=None, reason="provider_unavailable")
        finally:
            if connection is not None:
                try:
                    connection.close()  # type: ignore[attr-defined]
                except Exception:
                    pass
