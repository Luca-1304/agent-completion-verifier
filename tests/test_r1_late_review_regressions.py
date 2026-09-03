from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from completion_verifier.experiments.r1.artifacts import (
    verify_r1_manifest,
    write_r1_artifacts,
)
from completion_verifier.experiments.r1.models import (
    R1ControllerReceipt,
    R1ExperimentConfig,
    R1RunRecord,
)
from completion_verifier.experiments.r1.orchestrator import (
    append_explicit_second_observation,
    evaluate_attempt,
    seal_source_claim,
)
from completion_verifier.models import Evaluation, Status
from completion_verifier.remote import RemoteObservation, RemoteOutcome
from completion_verifier.remote.github import GitHubPullRequestContract


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


class SequenceVerifier:
    def __init__(self):
        self.outcomes = [RemoteOutcome.MATCH, RemoteOutcome.MISMATCH]

    def verify(self, contract):
        del contract
        outcome = self.outcomes.pop(0)
        if outcome is RemoteOutcome.MATCH:
            return RemoteObservation(
                provider="github",
                kind="pull_request",
                outcome=outcome,
                trusted=True,
                reason="matched",
                evidence={"fresh": True},
            )
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=outcome,
            trusted=True,
            reason="state_mismatch",
            evidence={"fresh": True, "state_matches": False},
        )


def _config() -> R1ExperimentConfig:
    return R1ExperimentConfig(
        experiment_id="PRIVATE_EXPERIMENT_ID",
        seed=7,
        repetitions=1,
        scenarios=("S0",),
        treatment="baseline",
        scaffold_id="scripted-reference",
        scaffold_version="1",
        max_live_actions=4,
        live=False,
    )


def _contract() -> GitHubPullRequestContract:
    return GitHubPullRequestContract(
        repository="PRIVATE_OWNER/PRIVATE_REPO",
        repository_id=9001,
        pull_number=7,
        expected_head_oid="a" * 40,
        expected_base_ref="main",
        expected_state="open",
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
    evaluation = Evaluation(Status.VERIFIED_COMPLETE, "verified", {})
    return R1RunRecord(
        scenario_id="S0",
        source_claim=seal_source_claim(
            completion_claimed=True,
            retry_count=0,
            refusal=False,
            action_count=0,
        ),
        controller_receipts=(),
        observations=(observation,),
        evaluations=(evaluation,),
    )


class R1LateArtifactReviewTests(unittest.TestCase):
    def test_manifest_rejects_nested_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            write_r1_artifacts(output, _config(), (_run(),), {"schema_version": "1"})
            nested = output / "raw"
            nested.mkdir()
            (nested / "provider.json").write_text("PRIVATE_PROVIDER_BODY", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_r1_manifest(output)

    def test_manifest_validates_public_config_digest(self) -> None:
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


class R1LateLatencyReviewTests(unittest.TestCase):
    def test_evaluate_attempt_measures_verifier_latency(self) -> None:
        claim = seal_source_claim(
            completion_claimed=True,
            retry_count=0,
            refusal=False,
            action_count=0,
        )
        with patch("time.monotonic_ns", side_effect=(1_000_000_000, 1_012_500_000)):
            run = evaluate_attempt(
                scenario_id="S0",
                contract=_contract(),
                source_claim=claim,
                controller_receipts=(),
                verifier=MatchVerifier(),
            )
        self.assertEqual(run.verification_latency_ms, (12.5,))

    def test_s7_second_read_preserves_both_measured_latencies(self) -> None:
        claim = seal_source_claim(
            completion_claimed=True,
            retry_count=0,
            refusal=False,
            action_count=3,
        )
        verifier = SequenceVerifier()
        with patch(
            "time.monotonic_ns",
            side_effect=(1_000_000_000, 1_010_000_000, 2_000_000_000, 2_025_000_000),
        ):
            first = evaluate_attempt(
                scenario_id="S7",
                contract=_contract(),
                source_claim=claim,
                controller_receipts=(),
                verifier=verifier,
            )
            second = append_explicit_second_observation(
                first,
                contract=_contract(),
                verifier=verifier,
                rollback_receipt=R1ControllerReceipt(
                    "close_pull_request", True, 1, private_pull_number=7
                ),
            )
        self.assertEqual(second.verification_latency_ms, (10.0, 25.0))


if __name__ == "__main__":
    unittest.main()
