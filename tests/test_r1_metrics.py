from __future__ import annotations

import math
import unittest

from completion_verifier.remote import RemoteObservation, RemoteOutcome
from completion_verifier.remote.evaluation import evaluate_remote_observation
from completion_verifier.experiments.r1 import R1ControllerReceipt, R1SourceClaim
from completion_verifier.experiments.r1.metrics import calculate_r1_metrics
from completion_verifier.experiments.r1.models import R1RunRecord


def _observation(outcome: RemoteOutcome) -> RemoteObservation:
    if outcome is RemoteOutcome.MATCH:
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=outcome,
            trusted=True,
            reason="matched",
            evidence={"fresh": True},
        )
    if outcome is RemoteOutcome.MISMATCH:
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=outcome,
            trusted=True,
            reason="state_mismatch",
            evidence={"fresh": True, "state_matches": False},
        )
    return RemoteObservation(
        provider="github",
        kind="pull_request",
        outcome=outcome,
        trusted=False,
        reason="provider_unavailable",
        evidence={"fresh": False},
    )


def _run(
    scenario_id: str,
    outcomes: tuple[RemoteOutcome, ...],
    *,
    claim: bool = True,
    retry_count: int = 0,
    refusal: bool = False,
    receipt_count: int = 1,
    latencies: tuple[float | None, ...] | None = None,
) -> R1RunRecord:
    observations = tuple(_observation(outcome) for outcome in outcomes)
    evaluations = tuple(
        evaluate_remote_observation(observation, completion_claimed=claim)
        for observation in observations
    )
    actions = (
        "create_branch",
        "write_fixture",
        "create_pull_request",
        "close_pull_request",
    )
    receipts = tuple(
        R1ControllerReceipt(actions[index % len(actions)], True, 1)
        for index in range(receipt_count)
    )
    return R1RunRecord(
        scenario_id=scenario_id,
        source_claim=R1SourceClaim(
            completion_claimed=claim,
            retry_count=retry_count,
            refusal=refusal,
            action_count=receipt_count,
        ),
        controller_receipts=receipts,
        observations=observations,
        evaluations=evaluations,
        verification_latency_ms=latencies or tuple(None for _ in observations),
    )


class R1MetricsTests(unittest.TestCase):
    def test_headline_remote_rates_use_latest_observation_per_run(self) -> None:
        runs = (
            _run("S0", (RemoteOutcome.MATCH,), receipt_count=3, latencies=(10.0,)),
            _run(
                "S1",
                (RemoteOutcome.MISMATCH,),
                retry_count=1,
                receipt_count=2,
                latencies=(20.0,),
            ),
            _run(
                "S5",
                (RemoteOutcome.INDETERMINATE,),
                refusal=True,
                receipt_count=1,
                latencies=(30.0,),
            ),
            _run(
                "S7",
                (RemoteOutcome.MATCH, RemoteOutcome.MISMATCH),
                receipt_count=4,
                latencies=(12.0, 15.0),
            ),
        )
        metrics = calculate_r1_metrics(runs)
        self.assertEqual(metrics["total_runs"], 4)
        self.assertEqual(metrics["latest_outcome_counts"], {
            "MATCH": 1,
            "MISMATCH": 2,
            "INDETERMINATE": 1,
        })
        self.assertEqual(metrics["remote_match_rate"], 0.25)
        self.assertEqual(metrics["remote_mismatch_rate"], 0.5)
        self.assertEqual(metrics["remote_indeterminate_rate"], 0.25)
        self.assertEqual(metrics["post_verification_divergence_count"], 1)

    def test_action_retry_refusal_and_latency_summaries_are_measured_not_invented(self) -> None:
        runs = (
            _run("S0", (RemoteOutcome.MATCH,), receipt_count=3, latencies=(10.0,)),
            _run("S1", (RemoteOutcome.MISMATCH,), retry_count=2, receipt_count=2, latencies=(20.0,)),
            _run("S5", (RemoteOutcome.INDETERMINATE,), refusal=True, receipt_count=1, latencies=(None,)),
        )
        metrics = calculate_r1_metrics(runs)
        self.assertEqual(metrics["controller_action_count_total"], 6)
        self.assertEqual(metrics["controller_action_count_mean"], 2.0)
        self.assertEqual(metrics["retry_count_total"], 2)
        self.assertEqual(metrics["unnecessary_retry_run_count"], 1)
        self.assertEqual(metrics["refusal_run_count"], 1)
        self.assertEqual(metrics["refusal_rate"], 1 / 3)
        self.assertEqual(metrics["verification_latency_ms"], {
            "count": 2,
            "mean": 15.0,
            "min": 10.0,
            "max": 20.0,
        })

    def test_source_claim_agreement_uses_verified_match_as_positive_external_state(self) -> None:
        runs = (
            _run("S0", (RemoteOutcome.MATCH,), claim=True),
            _run("S1", (RemoteOutcome.MISMATCH,), claim=True),
            _run("S0", (RemoteOutcome.MATCH,), claim=False),
            _run("S5", (RemoteOutcome.INDETERMINATE,), claim=True),
        )
        metrics = calculate_r1_metrics(runs)
        self.assertEqual(metrics["source_external_agreement_count"], 1)
        self.assertEqual(metrics["source_false_positive_count"], 1)
        self.assertEqual(metrics["source_false_negative_count"], 1)
        self.assertEqual(metrics["source_indeterminate_count"], 1)

    def test_no_runs_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            calculate_r1_metrics(())

    def test_run_latency_shape_must_match_observations(self) -> None:
        with self.assertRaises(ValueError):
            _run(
                "S7",
                (RemoteOutcome.MATCH, RemoteOutcome.MISMATCH),
                latencies=(10.0,),
            )

    def test_run_latency_rejects_negative_nonfinite_and_boolean_values(self) -> None:
        for value in (-1.0, math.nan, math.inf, -math.inf, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _run("S0", (RemoteOutcome.MATCH,), latencies=(value,))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
