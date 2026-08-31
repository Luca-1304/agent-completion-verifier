from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from completion_verifier.experiments.r1 import R1ExperimentConfig
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
    ScriptedR1Scaffold,
    run_r1_live,
)
from completion_verifier.experiments.r1.scenarios import get_r1_scenario
from completion_verifier.remote import RemoteObservation, RemoteOutcome


BASE = "a" * 40
WRITE = "b" * 40
PRIVATE_REPO = "PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO"
PRIVATE_ID = 94001


def _config() -> R1ExperimentConfig:
    return R1ExperimentConfig(
        experiment_id="PRIVATE_RECONCILIATION_EXPERIMENT",
        seed=19,
        repetitions=1,
        scenarios=("S0",),
        treatment="baseline",
        scaffold_id="scripted-reference",
        scaffold_version="1",
        max_live_actions=4,
        live=True,
    )


def _attempt() -> R1PreparedAttempt:
    return R1PreparedAttempt(
        target=R1LiveTarget(PRIVATE_REPO, PRIVATE_ID),
        task=R1BoundedTask(
            scenario_id="S0",
            base_oid=BASE,
            branch_name="r1-reconcile-accepted-pr",
            fixture_path="r1-fixtures/reconcile/state.txt",
            fixture_content="PRIVATE_RECONCILE_FIXTURE",
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
            target=R1LiveTarget(PRIVATE_REPO, PRIVATE_ID),
            approved_repository_id=PRIVATE_ID,
            target_locator_verified=True,
            protected_repository_ids=frozenset({999}),
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


class UnexpectedVerifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, contract):
        self.calls += 1
        del contract
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.MATCH,
            trusted=True,
            reason="matched",
            evidence={"fresh": True},
        )


class AcceptedUnaddressableController:
    def __init__(self, reconciled_number: int | None) -> None:
        self.reconciled_number = reconciled_number
        self.calls: list[tuple[object, ...]] = []

    def is_bound_to(self, target) -> bool:
        return target == R1LiveTarget(PRIVATE_REPO, PRIVATE_ID)

    def create_branch(self, base_oid, branch_name):
        self.calls.append(("create_branch", branch_name))
        return R1ControllerReceipt("create_branch", True, 1, private_object_oid=base_oid)

    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        self.calls.append(("write_fixture", branch_name, relative_path))
        return R1ControllerReceipt("write_fixture", True, 1, private_object_oid=WRITE)

    def create_pull_request(self, branch_name, base_ref):
        self.calls.append(("create_pull_request", branch_name, base_ref))
        return R1ControllerReceipt(
            "create_pull_request",
            False,
            1,
            error_code="accepted_unaddressable",
            private_target_ref=branch_name,
        )

    def _reconcile_open_pull_request(self, branch_name, base_ref):
        self.calls.append(("reconcile", branch_name, base_ref))
        return self.reconciled_number

    def close_pull_request(self, pull_number):
        self.calls.append(("close_pull_request", pull_number))
        return R1ControllerReceipt(
            "close_pull_request", True, 1, private_pull_number=pull_number
        )


class R1AcceptedUnaddressableReconciliationTests(unittest.TestCase):
    def test_unique_reconciliation_closes_once_and_preserves_aborted_evidence(self) -> None:
        controller = AcceptedUnaddressableController(77)
        verifier = UnexpectedVerifier()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                _config(),
                _permit(),
                controller,
                verifier,
                Path(tmp) / "out",
                attempts=(_attempt(),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_EXTERNAL_SECRET",),
            )
        self.assertEqual(verifier.calls, 0)
        self.assertEqual(result.runs[0].abort_reason, "controller_failure")
        self.assertEqual(result.runs[0].observations, ())
        self.assertEqual(
            [receipt.error_code for receipt in result.runs[0].controller_receipts],
            [None, None, "accepted_unaddressable", None],
        )
        self.assertEqual(controller.calls[-2][0], "reconcile")
        self.assertEqual(controller.calls[-1], ("close_pull_request", 77))
        self.assertEqual(result.metrics["harness_aborted_count"], 1)
        self.assertEqual(result.metrics["cleanup_unresolved_count"], 0)

    def test_ambiguous_reconciliation_is_not_retried_or_falsely_marked_clean(self) -> None:
        controller = AcceptedUnaddressableController(None)
        verifier = UnexpectedVerifier()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                _config(),
                _permit(),
                controller,
                verifier,
                Path(tmp) / "out",
                attempts=(_attempt(),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_EXTERNAL_SECRET",),
            )
        self.assertEqual(verifier.calls, 0)
        self.assertEqual(
            [call[0] for call in controller.calls],
            ["create_branch", "write_fixture", "create_pull_request", "reconcile"],
        )
        self.assertEqual(result.runs[0].abort_reason, "controller_failure")
        self.assertEqual(result.metrics["cleanup_unresolved_count"], 1)


if __name__ == "__main__":
    unittest.main()
