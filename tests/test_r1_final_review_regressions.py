from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from completion_verifier.experiments.r1 import (
    R1ControllerReceipt,
    R1ExperimentConfig,
    R1SourceClaim,
)
from completion_verifier.experiments.r1.artifacts import (
    verify_r1_manifest,
    write_r1_artifacts,
)
from completion_verifier.experiments.r1.models import R1RunRecord
from completion_verifier.experiments.r1.orchestrator import evaluate_attempt
from completion_verifier.remote import RemoteObservation, RemoteOutcome
from completion_verifier.remote.evaluation import evaluate_remote_observation
from completion_verifier.remote.github import GitHubPullRequestContract


class _MatchVerifier:
    def verify(self, contract: GitHubPullRequestContract) -> RemoteObservation:
        del contract
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.MATCH,
            trusted=True,
            reason="matched",
            evidence={"fresh": True},
        )


def _config() -> R1ExperimentConfig:
    return R1ExperimentConfig(
        experiment_id="PRIVATE_FINAL_REVIEW",
        seed=23,
        repetitions=1,
        scenarios=("S0",),
        treatment="baseline",
        scaffold_id="final-review",
        scaffold_version="1",
        max_live_actions=4,
    )


def _observation() -> RemoteObservation:
    return RemoteObservation(
        provider="github",
        kind="pull_request",
        outcome=RemoteOutcome.MATCH,
        trusted=True,
        reason="matched",
        evidence={"fresh": True},
    )


def _run() -> R1RunRecord:
    observation = _observation()
    return R1RunRecord(
        scenario_id="S0",
        source_claim=R1SourceClaim(True, 0, False, 3),
        controller_receipts=(R1ControllerReceipt("create_branch", True, 1),),
        observations=(observation,),
        evaluations=(evaluate_remote_observation(observation, completion_claimed=True),),
    )


def _contract() -> GitHubPullRequestContract:
    return GitHubPullRequestContract(
        repository="PRIVATE_OWNER/PRIVATE_REPO",
        repository_id=991,
        pull_number=7,
        expected_head_oid="a" * 40,
        expected_base_ref="main",
        expected_state="open",
    )


class R1FinalReviewRegressionTests(unittest.TestCase):
    def test_manifest_rejects_nested_untracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            write_r1_artifacts(output, _config(), (_run(),), {"schema_version": "1"})
            nested = output / "raw"
            nested.mkdir()
            (nested / "provider.json").write_text("PRIVATE_PROVIDER_BODY", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_r1_manifest(output)

    def test_manifest_rejects_stale_public_config_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            write_r1_artifacts(output, _config(), (_run(),), {"schema_version": "1"})
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["public_config_digest"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                verify_r1_manifest(output)

    def test_runner_orchestrator_records_verification_latency(self) -> None:
        record = evaluate_attempt(
            scenario_id="S0",
            contract=_contract(),
            source_claim=R1SourceClaim(True, 0, False, 3),
            controller_receipts=(R1ControllerReceipt("create_branch", True, 1),),
            verifier=_MatchVerifier(),
        )
        self.assertEqual(len(record.verification_latency_ms), 1)
        self.assertIsNotNone(record.verification_latency_ms[0])
        assert record.verification_latency_ms[0] is not None
        self.assertGreaterEqual(record.verification_latency_ms[0], 0.0)


if __name__ == "__main__":
    unittest.main()
