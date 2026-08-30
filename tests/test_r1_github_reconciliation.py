from __future__ import annotations

import json
import unittest

from completion_verifier.experiments.r1.github_controller import GitHubR1Controller
from completion_verifier.experiments.r1.preflight import R1LiveTarget


TOKEN = "Bearer PRIVATE_R1_RECONCILE_TOKEN"


class CredentialProvider:
    def authorization_header(self):
        return TOKEN


class FakeResponse:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self.headers = {}
        self.body = json.dumps(payload).encode("utf-8")

    def read(self, amount=None):
        return self.body if amount is None else self.body[:amount]

    def getheader(self, name, default=None):
        return self.headers.get(name, default)


class FakeConnection:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests = []

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, dict(headers or {})))

    def getresponse(self):
        return self.response

    def close(self):
        pass


class Factory:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __call__(self, host, *, timeout):
        return self.connection


def _target() -> R1LiveTarget:
    return R1LiveTarget("PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO", 9001)


def _controller(response: FakeResponse):
    connection = FakeConnection(response)
    return (
        GitHubR1Controller(
            CredentialProvider(),
            _target(),
            connection_factory=Factory(connection),
        ),
        connection,
    )


class GitHubR1ReconciliationTests(unittest.TestCase):
    def test_accepted_pr_without_addressable_number_is_marked_ambiguous(self) -> None:
        controller, _ = _controller(FakeResponse(201, {"number": True}))
        receipt = controller.create_pull_request("r1-pilot-001", "main")
        self.assertFalse(receipt.success)
        self.assertEqual(receipt.error_code, "accepted_unaddressable")
        self.assertEqual(receipt.private_target_ref, "r1-pilot-001")
        self.assertIsNone(receipt.private_pull_number)

    def test_reconcile_pull_request_is_one_bounded_read_and_requires_one_exact_candidate(self) -> None:
        payload = [
            {
                "number": 73,
                "state": "open",
                "head": {"ref": "r1-pilot-001"},
                "base": {"ref": "main"},
            }
        ]
        controller, connection = _controller(FakeResponse(200, payload))
        number = controller.reconcile_pull_request("r1-pilot-001", "main")
        self.assertEqual(number, 73)
        self.assertEqual(len(connection.requests), 1)
        method, path, body, headers = connection.requests[0]
        self.assertEqual(method, "GET")
        self.assertIsNone(body)
        self.assertIn("state=open", path)
        self.assertIn("head=PRIVATE_OWNER%3Ar1-pilot-001", path)
        self.assertIn("base=main", path)
        self.assertEqual(headers["Authorization"], TOKEN)

    def test_reconciliation_rejects_zero_or_multiple_candidates(self) -> None:
        for payload in ([], [{"number": 1}, {"number": 2}]):
            with self.subTest(payload=payload):
                controller, _ = _controller(FakeResponse(200, payload))
                self.assertIsNone(controller.reconcile_pull_request("r1-pilot-001", "main"))


if __name__ == "__main__":
    unittest.main()
