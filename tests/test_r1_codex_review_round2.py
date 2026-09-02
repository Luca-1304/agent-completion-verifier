from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from completion_verifier.experiments.r1 import R1ExperimentConfig
from completion_verifier.experiments.r1.github_controller import GitHubR1Controller
from completion_verifier.experiments.r1.models import R1ControllerReceipt
from completion_verifier.experiments.r1.preflight import (
    R1LiveTarget,
    R1PreflightRequest,
    run_preflight,
)
from completion_verifier.experiments.r1.runner import (
    R1BoundedTask,
    R1ContractExpectation,
    R1PreparedAttempt,
    R1RunnerAbort,
    R1ScaffoldResult,
    ScriptedR1Scaffold,
    run_r1_live,
)
from completion_verifier.experiments.r1.scenarios import get_r1_scenario
from completion_verifier.remote import RemoteObservation, RemoteOutcome


REPO = "PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO"
REPO_ID = 94001
BASE = "a" * 40
WRITE = "b" * 40


class CredentialProvider:
    def authorization_header(self) -> str:
        return "Bearer PRIVATE_R1_WRITE_TOKEN"


class MalformedAcceptedResponse:
    status = 201

    def read(self, amount=None):
        del amount
        return b"{not-json"

    def getheader(self, name, default=None):
        del name
        return default


class FakeConnection:
    def __init__(self) -> None:
        self.requests = []

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, headers))

    def getresponse(self):
        return MalformedAcceptedResponse()

    def close(self):
        pass


class ConnectionFactory:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def __call__(self, host, *, timeout):
        del host, timeout
        return self.connection


def _config() -> R1ExperimentConfig:
    return R1ExperimentConfig(
        experiment_id="PRIVATE_ROUND2",
        seed=41,
        repetitions=1,
        scenarios=("S0",),
        treatment="baseline",
        scaffold_id="reviewed-scripted",
        scaffold_version="1",
        max_live_actions=4,
        live=True,
    )


def _attempt() -> R1PreparedAttempt:
    return R1PreparedAttempt(
        target=R1LiveTarget(REPO, REPO_ID),
        task=R1BoundedTask(
            scenario_id="S0",
            base_oid=BASE,
            branch_name="r1-round2",
            fixture_path="r1-fixtures/round2/state.txt",
            fixture_content="PRIVATE_ROUND2_FIXTURE",
            base_ref="main",
        ),
        expectation=R1ContractExpectation(expected_state="open"),
    )


def _permit():
    definition = get_r1_scenario("S0")
    result = run_preflight(
        R1PreflightRequest(
            live=True,
            dry_run=False,
            normal_ci=False,
            scenario_id="S0",
            target=R1LiveTarget(REPO, REPO_ID),
            approved_repository_id=REPO_ID,
            target_locator_verified=True,
            protected_repository_ids=frozenset({999999}),
            requested_capabilities=definition.capabilities,
            scenario_capabilities=definition.capabilities,
            max_live_actions=4,
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


class RecordingController:
    def __init__(self) -> None:
        self.calls = []

    def is_bound_to(self, target) -> bool:
        return target == R1LiveTarget(REPO, REPO_ID)

    def create_branch(self, base_oid, branch_name):
        self.calls.append(("create_branch", branch_name))
        return R1ControllerReceipt("create_branch", True, 1, private_object_oid=base_oid)

    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        del content, existing_blob_sha
        self.calls.append(("write_fixture", branch_name, relative_path))
        return R1ControllerReceipt("write_fixture", True, 1, private_object_oid=WRITE)

    def create_pull_request(self, branch_name, base_ref):
        self.calls.append(("create_pull_request", branch_name, base_ref))
        return R1ControllerReceipt("create_pull_request", True, 1, private_pull_number=91)

    def close_pull_request(self, pull_number):
        self.calls.append(("close_pull_request", pull_number))
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


class UnreviewedLiveScaffold:
    def run(self, task, controller):
        controller.create_branch(task.base_oid, task.branch_name)
        return R1ScaffoldResult(completion_claimed=False)


class R1Round2ReviewTests(unittest.TestCase):
    def test_accepted_but_unparseable_pr_response_is_marked_for_reconciliation(self) -> None:
        factory = ConnectionFactory()
        controller = GitHubR1Controller(
            CredentialProvider(),
            R1LiveTarget(REPO, REPO_ID),
            connection_factory=factory,
        )
        receipt = controller.create_pull_request("r1-round2", "main")
        self.assertFalse(receipt.success)
        self.assertEqual(receipt.error_code, "accepted_unaddressable")
        self.assertEqual(receipt.private_target_ref, "r1-round2")
        self.assertEqual(len(factory.connection.requests), 1)

    def test_live_mode_rejects_arbitrary_in_process_scaffold_before_mutation(self) -> None:
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(),
                    _permit(),
                    controller,
                    MatchVerifier(),
                    Path(tmp) / "out",
                    attempts=(_attempt(),),
                    scaffold=UnreviewedLiveScaffold(),
                    forbidden_literals=("PRIVATE_EXTERNAL_SECRET",),
                )
        self.assertEqual(raised.exception.reason_code, "live_scaffold_not_reviewed")
        self.assertEqual(controller.calls, [])


if __name__ == "__main__":
    unittest.main()
