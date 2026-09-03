from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from completion_verifier.experiments.r1 import R1ExperimentConfig
from completion_verifier.experiments.r1.github_controller import GitHubR1Controller
from completion_verifier.experiments.r1.models import R1_CONTROLLER_ACTIONS, R1ControllerReceipt
from completion_verifier.experiments.r1.preflight import (
    R1LiveTarget,
    R1PreflightRequest,
    consume_live_permit,
    run_preflight,
)
from completion_verifier.experiments.r1.runner import (
    R1BoundedTask,
    R1ContractExpectation,
    R1PreparedAttempt,
    ScriptedR1Scaffold,
    run_r1_live,
)
from completion_verifier.remote import RemoteObservation, RemoteOutcome

BASE = "a" * 40
WRITE = "b" * 40
PRIVATE_REPO = "PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO"
PRIVATE_ID = 96001
TOKEN = "Bearer PRIVATE_PR35_TOKEN"


def permit():
    result = run_preflight(
        R1PreflightRequest(
            live=True,
            dry_run=False,
            normal_ci=False,
            scenario_id="S0",
            target=R1LiveTarget(PRIVATE_REPO, PRIVATE_ID),
            approved_repository_id=PRIVATE_ID,
            target_locator_verified=True,
            protected_repository_ids=frozenset({999}),
            requested_capabilities=R1_CONTROLLER_ACTIONS,
            scenario_capabilities=R1_CONTROLLER_ACTIONS,
            max_live_actions=len(R1_CONTROLLER_ACTIONS),
            actions_used=0,
            artifact_destination_new=True,
            artifact_destination_writable=True,
            privacy_sentinel_passed=True,
            cleanup_plan_defined=True,
            verifier_credential_available=True,
        )
    )
    assert result.permit is not None
    return result.permit


def config() -> R1ExperimentConfig:
    return R1ExperimentConfig(
        experiment_id="PRIVATE_PR35_REVIEW",
        seed=35,
        repetitions=1,
        scenarios=("S0",),
        treatment="baseline",
        scaffold_id="scripted-reference",
        scaffold_version="1",
        max_live_actions=len(R1_CONTROLLER_ACTIONS),
        live=True,
    )


def attempt() -> R1PreparedAttempt:
    return R1PreparedAttempt(
        target=R1LiveTarget(PRIVATE_REPO, PRIVATE_ID),
        task=R1BoundedTask(
            scenario_id="S0",
            base_oid=BASE,
            branch_name="r1-pr35-review",
            fixture_path="r1-fixtures/pr35/state.txt",
            fixture_content="PRIVATE_PR35_FIXTURE",
            base_ref="main",
        ),
        expectation=R1ContractExpectation(expected_state="open"),
    )


class RecordingController:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def is_bound_to(self, target) -> bool:
        return target == R1LiveTarget(PRIVATE_REPO, PRIVATE_ID)

    def create_branch(self, base_oid, branch_name):
        self.calls.append("create_branch")
        return R1ControllerReceipt("create_branch", True, 1, private_object_oid=base_oid)

    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        self.calls.append("write_fixture")
        return R1ControllerReceipt("write_fixture", True, 1, private_object_oid=WRITE)

    def create_pull_request(self, branch_name, base_ref):
        self.calls.append("create_pull_request")
        return R1ControllerReceipt("create_pull_request", True, 1, private_pull_number=17)

    def close_pull_request(self, pull_number):
        self.calls.append("close_pull_request")
        return R1ControllerReceipt("close_pull_request", True, 1, private_pull_number=pull_number)


class MatchVerifier:
    def verify(self, contract):
        del contract
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.MATCH,
            trusted=True,
            reason="matched",
            evidence={"fresh": True},
        )


class CredentialProvider:
    def authorization_header(self) -> str:
        return TOKEN


class FakeResponse:
    def __init__(self, status: int, payload=None, *, read_error: Exception | None = None) -> None:
        self.status = status
        self.payload = payload
        self.read_error = read_error

    def getheader(self, name, default=None):
        del name
        return default

    def read(self, amount=None):
        del amount
        if self.read_error is not None:
            raise self.read_error
        return json.dumps(self.payload if self.payload is not None else {}).encode("utf-8")


class FakeConnection:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests = []

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, headers))

    def getresponse(self):
        return self.response

    def close(self):
        pass


class SequenceFactory:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.connections: list[FakeConnection] = []

    def __call__(self, host, *, timeout):
        del host, timeout
        connection = FakeConnection(self.responses.pop(0))
        self.connections.append(connection)
        return connection


class R1PR35ReviewTests(unittest.TestCase):
    def test_shallow_permit_copy_cannot_gain_a_second_consumption(self) -> None:
        original = permit()
        duplicate = copy.copy(original)
        self.assertTrue(consume_live_permit(original))
        self.assertFalse(consume_live_permit(duplicate))

    def test_live_runner_ignores_instance_level_override_of_trusted_scaffold(self) -> None:
        scaffold = ScriptedR1Scaffold()
        scaffold.run = lambda task, controller: (_ for _ in ()).throw(AssertionError("MUTATED_RUN"))  # type: ignore[method-assign]
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                config(),
                permit(),
                controller,
                MatchVerifier(),
                Path(tmp) / "out",
                attempts=(attempt(),),
                scaffold=scaffold,
                forbidden_literals=("PRIVATE_EXTERNAL_SECRET",),
            )
        self.assertTrue(result.manifest_verified)
        self.assertEqual(
            controller.calls,
            ["create_branch", "write_fixture", "create_pull_request", "close_pull_request"],
        )

    def test_reconciliation_requires_head_repository_identity_match(self) -> None:
        payload = [
            {
                "number": 17,
                "state": "open",
                "head": {"ref": "r1-pr35-review", "repo": {"id": PRIVATE_ID + 1}},
                "base": {"ref": "main", "repo": {"id": PRIVATE_ID}},
            }
        ]
        factory = SequenceFactory([FakeResponse(200, payload)])
        controller = GitHubR1Controller(
            CredentialProvider(),
            R1LiveTarget(PRIVATE_REPO, PRIVATE_ID),
            connection_factory=factory,
        )
        self.assertIsNone(controller._reconcile_open_pull_request("r1-pr35-review", "main"))

    def test_http_201_body_read_failure_is_accepted_unaddressable(self) -> None:
        factory = SequenceFactory([FakeResponse(201, read_error=TimeoutError("PRIVATE_TIMEOUT"))])
        controller = GitHubR1Controller(
            CredentialProvider(),
            R1LiveTarget(PRIVATE_REPO, PRIVATE_ID),
            connection_factory=factory,
        )
        receipt = controller.create_pull_request("r1-pr35-review", "main")
        self.assertFalse(receipt.success)
        self.assertEqual(receipt.error_code, "accepted_unaddressable")
        self.assertEqual(receipt.private_target_ref, "r1-pr35-review")


if __name__ == "__main__":
    unittest.main()
