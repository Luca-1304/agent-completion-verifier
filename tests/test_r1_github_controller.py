from __future__ import annotations

import base64
import json
import math
import unittest

from completion_verifier.experiments.r1.github_controller import GitHubR1Controller
from completion_verifier.experiments.r1.preflight import R1LiveTarget


TOKEN = "Bearer PRIVATE_R1_WRITE_TOKEN"
BASE_OID = "a" * 40
COMMIT_OID = "b" * 40
CONTENT_SHA = "c" * 40


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
    def __init__(self, status: int, payload: object = None, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.headers = headers or {}
        self.body = json.dumps(payload if payload is not None else {}).encode("utf-8")
        self.read_calls: list[int | None] = []

    def read(self, amount: int | None = None) -> bytes:
        self.read_calls.append(amount)
        if amount is None:
            return self.body
        return self.body[:amount]

    def getheader(self, name: str, default=None):
        return self.headers.get(name, default)


class FakeConnection:
    def __init__(self, response: FakeResponse, request_error: Exception | None = None) -> None:
        self.response = response
        self.request_error = request_error
        self.requests: list[tuple[str, str, object, dict[str, str]]] = []
        self.closed = False

    def request(self, method: str, path: str, body=None, headers=None) -> None:
        self.requests.append((method, path, body, dict(headers or {})))
        if self.request_error is not None:
            raise self.request_error

    def getresponse(self) -> FakeResponse:
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


def target() -> R1LiveTarget:
    return R1LiveTarget(
        repository_locator="PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO",
        repository_id=9001,
    )


def controller_for(
    response: FakeResponse,
    *,
    credential: CredentialProvider | None = None,
    connection: FakeConnection | None = None,
    timeout_seconds: float = 7.5,
    max_response_bytes: int = 32_768,
    max_fixture_bytes: int = 16_384,
):
    provider = credential or CredentialProvider()
    conn = connection or FakeConnection(response)
    factory = ConnectionFactory(conn)
    controller = GitHubR1Controller(
        provider,
        target(),
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
        max_fixture_bytes=max_fixture_bytes,
        connection_factory=factory,
    )
    return controller, provider, conn, factory


def request_json(connection: FakeConnection) -> tuple[str, str, dict[str, object], dict[str, str]]:
    method, path, body, headers = connection.requests[0]
    assert isinstance(body, str)
    return method, path, json.loads(body), headers


class GitHubR1ControllerRequestTests(unittest.TestCase):
    def test_create_branch_uses_one_post_to_git_refs(self) -> None:
        response = FakeResponse(201, {"object": {"sha": BASE_OID}})
        controller, provider, connection, factory = controller_for(response)
        receipt = controller.create_branch(BASE_OID, "r1-pilot-001")
        method, path, body, headers = request_json(connection)
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/repos/PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO/git/refs")
        self.assertEqual(body, {"ref": "refs/heads/r1-pilot-001", "sha": BASE_OID})
        self.assertEqual(headers["Authorization"], TOKEN)
        self.assertEqual(headers["X-GitHub-Api-Version"], "2022-11-28")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(factory.calls, [("api.github.com", 7.5)])
        self.assertEqual(provider.calls, 1)
        self.assertTrue(connection.closed)
        self.assertTrue(receipt.success)
        self.assertEqual(receipt.private_object_oid, BASE_OID)

    def test_write_fixture_uses_one_put_and_explicit_optional_existing_sha(self) -> None:
        response = FakeResponse(201, {"commit": {"sha": COMMIT_OID}, "content": {"sha": CONTENT_SHA}})
        controller, _, connection, _ = controller_for(response)
        receipt = controller.write_fixture(
            "r1-pilot-001",
            "r1-fixtures/run-001/state.txt",
            "hello",
            existing_blob_sha=CONTENT_SHA,
        )
        method, path, body, _ = request_json(connection)
        self.assertEqual(method, "PUT")
        self.assertEqual(
            path,
            "/repos/PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO/contents/r1-fixtures/run-001/state.txt",
        )
        self.assertEqual(body["branch"], "r1-pilot-001")
        self.assertEqual(body["sha"], CONTENT_SHA)
        self.assertEqual(body["message"], "R1 experiment fixture update")
        self.assertEqual(base64.b64decode(body["content"]), b"hello")
        self.assertEqual(receipt.private_object_oid, COMMIT_OID)

    def test_write_fixture_create_omits_sha(self) -> None:
        response = FakeResponse(201, {"commit": {"sha": COMMIT_OID}})
        controller, _, connection, _ = controller_for(response)
        controller.write_fixture(
            "r1-pilot-001", "r1-fixtures/run-001/state.txt", "hello"
        )
        _, _, body, _ = request_json(connection)
        self.assertNotIn("sha", body)

    def test_create_pull_request_uses_one_post_and_creates_draft(self) -> None:
        response = FakeResponse(201, {"number": 17})
        controller, _, connection, _ = controller_for(response)
        receipt = controller.create_pull_request("r1-pilot-001", "main")
        method, path, body, _ = request_json(connection)
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/repos/PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO/pulls")
        self.assertEqual(body["head"], "r1-pilot-001")
        self.assertEqual(body["base"], "main")
        self.assertEqual(body["draft"], True)
        self.assertEqual(body["title"], "R1 controlled experiment")
        self.assertNotIn("body", body)
        self.assertEqual(receipt.private_pull_number, 17)

    def test_close_pull_request_uses_one_patch_with_state_only(self) -> None:
        response = FakeResponse(200, {"number": 17, "state": "closed"})
        controller, _, connection, _ = controller_for(response)
        receipt = controller.close_pull_request(17)
        method, path, body, _ = request_json(connection)
        self.assertEqual(method, "PATCH")
        self.assertEqual(path, "/repos/PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO/pulls/17")
        self.assertEqual(body, {"state": "closed"})
        self.assertEqual(receipt.private_pull_number, 17)

    def test_controller_has_no_forbidden_mutation_methods(self) -> None:
        controller, _, _, _ = controller_for(FakeResponse(201, {"number": 1}))
        for name in (
            "merge",
            "reopen",
            "force_push",
            "delete_branch",
            "delete_repository",
            "create_issue",
            "create_comment",
            "create_release",
            "update_workflow",
            "update_settings",
        ):
            self.assertFalse(hasattr(controller, name), name)


class GitHubR1ControllerBoundaryTests(unittest.TestCase):
    def test_invalid_authorization_fails_before_connection(self) -> None:
        for value in (None, "", "Bearer bad\nheader", 123):
            with self.subTest(value=value):
                connection = FakeConnection(FakeResponse(201, {}))
                controller, provider, _, factory = controller_for(
                    FakeResponse(201, {}),
                    credential=CredentialProvider(value),
                    connection=connection,
                )
                receipt = controller.create_branch(BASE_OID, "r1-pilot-001")
                self.assertFalse(receipt.success)
                self.assertEqual(receipt.error_code, "authentication_failed")
                self.assertEqual(provider.calls, 1)
                self.assertEqual(factory.calls, [])

    def test_status_failures_use_fixed_codes_without_response_body(self) -> None:
        cases = (
            (401, {}, "authentication_failed"),
            (403, {}, "permission_unverified"),
            (403, {"Retry-After": "60"}, "rate_limited"),
            (404, {}, "permission_unverified"),
            (409, {}, "resource_conflict"),
            (422, {}, "validation_failed"),
            (429, {}, "rate_limited"),
            (302, {"Location": "https://evil.invalid/private"}, "redirect_rejected"),
            (500, {}, "provider_unavailable"),
        )
        for status, headers, code in cases:
            with self.subTest(status=status, code=code):
                response = FakeResponse(
                    status,
                    {"message": "PRIVATE_PROVIDER_ERROR_TEXT"},
                    headers=headers,
                )
                controller, _, _, _ = controller_for(response)
                receipt = controller.create_branch(BASE_OID, "r1-pilot-001")
                self.assertFalse(receipt.success)
                self.assertEqual(receipt.error_code, code)
                self.assertNotIn("PRIVATE_PROVIDER_ERROR_TEXT", repr(receipt))
                self.assertNotIn("PRIVATE_PROVIDER_ERROR_TEXT", str(receipt.to_public_dict()))

    def test_transport_exception_maps_to_provider_unavailable_without_echo(self) -> None:
        connection = FakeConnection(
            FakeResponse(201, {}), request_error=OSError("PRIVATE_NETWORK_SENTINEL")
        )
        controller, _, _, _ = controller_for(
            FakeResponse(201, {}), connection=connection
        )
        receipt = controller.create_branch(BASE_OID, "r1-pilot-001")
        self.assertFalse(receipt.success)
        self.assertEqual(receipt.error_code, "provider_unavailable")
        self.assertNotIn("PRIVATE_NETWORK_SENTINEL", repr(receipt))

    def test_response_body_is_bounded(self) -> None:
        response = FakeResponse(201, {"object": {"sha": BASE_OID}})
        controller, _, _, _ = controller_for(response, max_response_bytes=100)
        controller.create_branch(BASE_OID, "r1-pilot-001")
        self.assertEqual(response.read_calls, [101])

    def test_oversized_or_malformed_success_response_fails_closed(self) -> None:
        oversized = FakeResponse(201, {})
        oversized.body = b"x" * 102
        controller, _, _, _ = controller_for(oversized, max_response_bytes=100)
        self.assertEqual(
            controller.create_branch(BASE_OID, "r1-pilot-001").error_code,
            "invalid_provider_response",
        )
        malformed = FakeResponse(201, {})
        malformed.body = b"{not-json"
        controller, _, _, _ = controller_for(malformed)
        self.assertEqual(
            controller.create_branch(BASE_OID, "r1-pilot-001").error_code,
            "invalid_provider_response",
        )

    def test_timeout_and_size_limits_are_strict(self) -> None:
        for value in (0, -1, True, math.nan, math.inf, -math.inf):
            with self.subTest(timeout=value), self.assertRaises(ValueError):
                controller_for(FakeResponse(201, {}), timeout_seconds=value)  # type: ignore[arg-type]
        for field, value in (("max_response_bytes", 0), ("max_fixture_bytes", 0)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                controller_for(FakeResponse(201, {}), **{field: value})

    def test_fixture_size_is_bounded_before_connection(self) -> None:
        controller, _, connection, factory = controller_for(
            FakeResponse(201, {}), max_fixture_bytes=4
        )
        with self.assertRaises(ValueError):
            controller.write_fixture(
                "r1-pilot-001", "r1-fixtures/run-001/state.txt", "hello"
            )
        self.assertEqual(factory.calls, [])
        self.assertEqual(connection.requests, [])

    def test_existing_blob_sha_is_explicit_and_validated(self) -> None:
        controller, _, connection, factory = controller_for(FakeResponse(201, {}))
        for value in ("short", "z" * 40, True, " " + CONTENT_SHA):
            with self.subTest(value=value), self.assertRaises(ValueError):
                controller.write_fixture(
                    "r1-pilot-001",
                    "r1-fixtures/run-001/state.txt",
                    "x",
                    existing_blob_sha=value,  # type: ignore[arg-type]
                )
        self.assertEqual(factory.calls, [])
        self.assertEqual(connection.requests, [])

    def test_success_response_fields_are_type_checked(self) -> None:
        cases = (
            ("branch", FakeResponse(201, {"object": {"sha": "bad"}})),
            ("file", FakeResponse(201, {"commit": {"sha": "bad"}})),
            ("pr", FakeResponse(201, {"number": True})),
            ("close", FakeResponse(200, {"number": 17, "state": "open"})),
        )
        for kind, response in cases:
            with self.subTest(kind=kind):
                controller, _, _, _ = controller_for(response)
                if kind == "branch":
                    receipt = controller.create_branch(BASE_OID, "r1-pilot-001")
                elif kind == "file":
                    receipt = controller.write_fixture(
                        "r1-pilot-001", "r1-fixtures/run-001/state.txt", "x"
                    )
                elif kind == "pr":
                    receipt = controller.create_pull_request("r1-pilot-001", "main")
                else:
                    receipt = controller.close_pull_request(17)
                self.assertFalse(receipt.success)
                self.assertEqual(receipt.error_code, "invalid_provider_response")


if __name__ == "__main__":
    unittest.main()
