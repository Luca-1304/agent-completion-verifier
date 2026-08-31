from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from completion_verifier.experiments.r1 import R1ExperimentConfig
from completion_verifier.experiments.r1.controller import DryRunR1Controller
from completion_verifier.experiments.r1.preflight import R1LiveTarget
from completion_verifier.experiments.r1.runner import (
    R1BoundedTask,
    R1ContractExpectation,
    R1PreparedAttempt,
    R1RunnerAbort,
    R1ScaffoldResult,
    run_r1_dry,
)
from completion_verifier.remote import RemoteObservation, RemoteOutcome


BASE = "a" * 40


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


class SelfClosingS7Scaffold:
    def run(self, task, controller):
        branch = controller.create_branch(task.base_oid, task.branch_name)
        if not branch.success:
            return R1ScaffoldResult(completion_claimed=False)
        write = controller.write_fixture(task.branch_name, task.fixture_path, task.fixture_content)
        if not write.success:
            return R1ScaffoldResult(completion_claimed=False)
        pull = controller.create_pull_request(task.branch_name, task.base_ref)
        if pull.private_pull_number is not None:
            controller.close_pull_request(pull.private_pull_number)
        return R1ScaffoldResult(completion_claimed=pull.success)


class R1S7RunnerOwnershipReviewTests(unittest.TestCase):
    def test_scaffold_cannot_consume_runner_owned_s7_rollback_action(self) -> None:
        config = R1ExperimentConfig(
            experiment_id="PRIVATE_S7_REVIEW",
            seed=7,
            repetitions=1,
            scenarios=("S7",),
            treatment="baseline",
            scaffold_id="self-closing-review-scaffold",
            scaffold_version="1",
            max_live_actions=4,
            live=False,
        )
        attempt = R1PreparedAttempt(
            target=R1LiveTarget("PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO", 93001),
            task=R1BoundedTask(
                scenario_id="S7",
                base_oid=BASE,
                branch_name="r1-s7-runner-owned",
                fixture_path="r1-fixtures/s7-runner-owned/state.txt",
                fixture_content="PRIVATE_S7_FIXTURE",
                base_ref="main",
            ),
            expectation=R1ContractExpectation(expected_state="open"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_dry(
                    config,
                    DryRunR1Controller(),
                    MatchVerifier(),
                    Path(tmp) / "out",
                    attempts=(attempt,),
                    scaffold=SelfClosingS7Scaffold(),
                    forbidden_literals=("PRIVATE_EXTERNAL_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "action_not_allowed")


if __name__ == "__main__":
    unittest.main()
