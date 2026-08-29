from __future__ import annotations

import json
import unittest

from completion_verifier.remote.github import (
    GitHubPullRequestContract,
    GitHubRESTReader,
)


HEAD = "a" * 40
MERGE = "b" * 40
TOKEN = "Bearer PRIVATE_TOKEN_SENTINEL"


def contract() -> GitHubPullRequestContract:
    return GitHubPullRequestContract(
        repository="PRIVATE_OWNER/PRIVATE_REPO",
        repository_id=101,
        pull_number=22,
        expected_head_oid=HEAD,
        expected_base_ref="PRIVATE_BASE",
        expected_state="open",
    )


def payload(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "id": 999999,  # PR database ID: must never be used as repository identity.
        "number": 22,
        "state": "open",
        "merged": False,
        "head": {"sha": HEAD, "repo": {"id": 202}},
        "base": {"ref": "PRIVATE_BASE", "repo": {"id": 101}},
        "merge_commit_sha": None,
    }
    result.update(overrides)
    return result


class CredentialProvider:
    def __init__(self, value: object = TOKEN) -> None:
        self.value = value
        self.calls = 0

    def authorization_header(self):
        self.calls += 1
        return self.value

    def __repr__(self) -> str:
        return "CredentialProvider(PRIVATE_PROVIDER_REPR)"


class FakeResponse:
    def __init__(
        self,
        status: int = 200,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.body = body if body is not None else json.dumps(payload()).encode("utf-8")
        self.headers = headers or {}
        self.read_calls: list[int | None] = []

    def read(self, amount: int | None = None) -> bytes:
        self.read_calls.append(amount)
        if amount is None:
            return self.body
        return self.body[:amount]

    def getheader(self, name: str, default=None):
        return self.headers.get(name, default)


class FakeConnection:
    def __init__(
        self,
        response: FakeResponse | None = None,
        *,
        request_error: Exception | None = None,
        response_error: Exception | None = None,
    ) -> None:
        self.response = response or FakeResponse()
        self.request_error = request_error
        self.response_error = response_error
        self.requests: list[tuple[str, str, object, dict[str, str]]] = []
        self.closed = False

    def request(self, method: str, path: str, body=None, headers=None) -> None:
        self.requests.append((method, path, body, dict(headers or {})))
        if self.request_error is not None:
            raise self.request_error

    def getresponse(self) -> FakeResponse:
        if self.response_error is not None:
            raise self.response_error
        return self.response

    def close(self) -> None:
        self.closed = True


class ConnectionFactory:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.calls: list[tuple[str, float]] = []

    def __call__(self, host: str, *, timeout: float):
        self.calls.append((host, timeout))
        return self.connection


def reader_for(
    response: FakeResponse | None = None,
    *,
    credential: CredentialProvider | None = None,
    connection: FakeConnection | None = None,
    max_response_bytes: int = 1_048_576,
):
    provider = credential or CredentialProvider()
    conn = connection or FakeConnection(response)
    factory = ConnectionFactory(conn)
    reader = GitHubRESTReader(
        provider,
        timeout_seconds=7.5,
        max_response_bytes=max_response_bytes,
        connection_factory=factory,
        clock=lambda: 1_000.0,
    )
    return reader, provider, conn, factory


class GitHubRESTRequestTests(unittest.TestCase):
    def test_success_uses_exactly_one_get_to_github_api(self) -> None:
        reader, provider, connection, factory = reader_for()
        result = reader.read_pull_request(contract())

        self.assertIsNotNone(result.snapshot)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(factory.calls, [("api.github.com", 7.5)])
        self.assertEqual(len(connection.requests), 1)
        method, path, body, headers = connection.requests[0]
        self.assertEqual(method, "GET")
        self.assertEqual(path, "/repos/PRIVATE_OWNER/PRIVATE_REPO/pulls/22")
        self.assertIsNone(body)
        self.assertEqual(headers["Authorization"], TOKEN)
        self.assertEqual(headers["Accept"], "application/vnd.github+json")
        self.assertEqual(headers["X-GitHub-Api-Version"], "2022-11-28")
        self.assertTrue(headers["User-Agent"].startswith("agent-completion-verifier/"))
        self.assertTrue(connection.closed)

    def test_reader_reads_at_most_limit_plus_one_byte(self) -> None:
        response = FakeResponse(body=b"{}")
        reader, _, _, _ = reader_for(response, max_response_bytes=100)
        reader.read_pull_request(contract())
        self.assertEqual(response.read_calls, [101])

    def test_credential_provider_is_only_called_by_reader_and_not_exposed(self) -> None:
        provider = CredentialProvider()
        reader, _, _, _ = reader_for(credential=provider)
        result = reader.read_pull_request(contract())
        self.assertEqual(provider.calls, 1)
        rendered = repr(result)
        for secret in ("PRIVATE_TOKEN_SENTINEL", "PRIVATE_PROVIDER_REPR"):
            self.assertNotIn(secret, rendered)

    def test_invalid_authorization_header_fails_before_connection(self) -> None:
        for value in (None, "", "Bearer bad\nheader", 123):
            with self.subTest(value=value):
                connection = FakeConnection()
                reader, provider, _, factory = reader_for(
                    credential=CredentialProvider(value),
                    connection=connection,
                )
                result = reader.read_pull_request(contract())
                self.assertEqual(result.reason, "authentication_failed")
                self.assertEqual(provider.calls, 1)
                self.assertEqual(factory.calls, [])
                self.assertEqual(connection.requests, [])


class GitHubRESTClassificationTests(unittest.TestCase):
    def reason_for(self, status: int, *, headers: dict[str, str] | None = None) -> str | None:
        reader, _, _, _ = reader_for(FakeResponse(status=status, body=b"{}", headers=headers))
        return reader.read_pull_request(contract()).reason

    def test_status_classification_is_fail_closed(self) -> None:
        cases = (
            (401, None, "authentication_failed"),
            (404, None, "resource_unobservable"),
            (403, None, "permission_unverified"),
            (429, None, "rate_limited"),
            (301, None, "redirect_rejected"),
            (302, None, "redirect_rejected"),
            (500, None, "provider_unavailable"),
            (503, None, "provider_unavailable"),
        )
        for status, headers, expected in cases:
            with self.subTest(status=status):
                self.assertEqual(self.reason_for(status, headers=headers), expected)

    def test_rate_limit_403_is_distinguished_by_fixed_headers(self) -> None:
        self.assertEqual(
            self.reason_for(403, headers={"X-RateLimit-Remaining": "0"}),
            "rate_limited",
        )
        self.assertEqual(
            self.reason_for(403, headers={"Retry-After": "15"}),
            "rate_limited",
        )

    def test_network_and_transport_errors_do_not_leak_exception_text(self) -> None:
        for error in (
            TimeoutError("PRIVATE_TIMEOUT_DETAIL"),
            OSError("PRIVATE_OS_ERROR_WITH_TOKEN_PRIVATE_TOKEN_SENTINEL"),
        ):
            with self.subTest(error=type(error).__name__):
                connection = FakeConnection(request_error=error)
                reader, _, _, _ = reader_for(connection=connection)
                result = reader.read_pull_request(contract())
                self.assertEqual(result.reason, "provider_unavailable")
                self.assertNotIn("PRIVATE_", repr(result))
                self.assertTrue(connection.closed)

    def test_malformed_or_oversized_success_response_is_indeterminate(self) -> None:
        malformed = FakeResponse(status=200, body=b"{PRIVATE_BAD_JSON")
        reader, _, _, _ = reader_for(malformed)
        self.assertEqual(reader.read_pull_request(contract()).reason, "invalid_provider_response")

        oversized = FakeResponse(status=200, body=b"x" * 11)
        reader, _, _, _ = reader_for(oversized, max_response_bytes=10)
        self.assertEqual(reader.read_pull_request(contract()).reason, "invalid_provider_response")

    def test_malformed_provider_date_is_indeterminate_without_echo(self) -> None:
        response = FakeResponse(headers={"Date": "PRIVATE_BAD_DATE"})
        reader, _, _, _ = reader_for(response)
        result = reader.read_pull_request(contract())
        self.assertEqual(result.reason, "invalid_provider_response")
        self.assertNotIn("PRIVATE_BAD_DATE", repr(result))


class GitHubRESTNormalizationTests(unittest.TestCase):
    def read_payload(self, value: dict[str, object]):
        response = FakeResponse(body=json.dumps(value).encode("utf-8"))
        reader, _, _, _ = reader_for(response)
        return reader.read_pull_request(contract())

    def test_repository_identity_comes_from_base_repo_id_not_pull_id(self) -> None:
        value = payload(id=101)
        value["base"] = {"ref": "PRIVATE_BASE", "repo": {"id": 303}}
        result = self.read_payload(value)
        self.assertIsNotNone(result.snapshot)
        assert result.snapshot is not None
        self.assertEqual(result.snapshot.repository_id, 303)
        self.assertNotEqual(result.snapshot.repository_id, value["id"])

    def test_success_normalizes_only_required_fields(self) -> None:
        value = payload(extra_private_field="PRIVATE_BODY_SENTINEL")
        result = self.read_payload(value)
        self.assertIsNotNone(result.snapshot)
        assert result.snapshot is not None
        self.assertEqual(result.snapshot.repository_id, 101)
        self.assertEqual(result.snapshot.pull_number, 22)
        self.assertEqual(result.snapshot.state, "open")
        self.assertFalse(result.snapshot.merged)
        self.assertEqual(result.snapshot.head_oid, HEAD)
        self.assertEqual(result.snapshot.head_repository_id, 202)
        self.assertEqual(result.snapshot.base_ref, "PRIVATE_BASE")
        self.assertIsNone(result.snapshot.merge_oid)
        self.assertNotIn("PRIVATE_BODY_SENTINEL", repr(result.snapshot))

    def test_deleted_fork_null_head_repo_normalizes_to_none(self) -> None:
        value = payload()
        value["head"] = {"sha": HEAD, "repo": None}
        result = self.read_payload(value)
        self.assertIsNotNone(result.snapshot)
        assert result.snapshot is not None
        self.assertIsNone(result.snapshot.head_repository_id)

    def test_boolean_ids_and_malformed_object_ids_are_rejected(self) -> None:
        bad_values = []

        value = payload(number=True)
        bad_values.append(value)

        value = payload()
        value["base"] = {"ref": "PRIVATE_BASE", "repo": {"id": True}}
        bad_values.append(value)

        value = payload()
        value["head"] = {"sha": "not-an-object-id", "repo": {"id": 202}}
        bad_values.append(value)

        for value in bad_values:
            with self.subTest(value=value):
                self.assertEqual(
                    self.read_payload(value).reason,
                    "invalid_provider_response",
                )

    def test_wrong_schema_shapes_are_rejected(self) -> None:
        values = (
            {},
            payload(head=None),
            payload(base=None),
            payload(merged="false"),
            payload(state=123),
            payload(merge_commit_sha=123),
        )
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(
                    self.read_payload(value).reason,
                    "invalid_provider_response",
                )


if __name__ == "__main__":
    unittest.main()
