from __future__ import annotations

import json
import unittest

from completion_verifier.models import Status
from completion_verifier.remote import (
    RemoteObservation,
    RemoteOutcome,
    evaluate_remote_observation,
    remote_postcondition_case,
)


class RemoteEvaluationTests(unittest.TestCase):
    def test_match_maps_to_verified_complete(self) -> None:
        observation = RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.MATCH,
            trusted=True,
            reason="matched",
            evidence={"fresh": True, "state_matches": True},
        )
        evaluation = evaluate_remote_observation(observation)
        self.assertEqual(evaluation.status, Status.VERIFIED_COMPLETE)
        self.assertEqual(evaluation.proven_actions, ("verify_remote:github:pull_request",))

    def test_decisive_mismatch_maps_to_failed(self) -> None:
        observation = RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.MISMATCH,
            trusted=True,
            reason="head_mismatch",
            evidence={"fresh": True, "head_matches": False},
        )
        evaluation = evaluate_remote_observation(observation)
        self.assertEqual(evaluation.status, Status.FAILED)
        self.assertEqual(evaluation.failed_actions, ("verify_remote:github:pull_request",))

    def test_indeterminate_maps_to_unverified_without_failure_event(self) -> None:
        observation = RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.INDETERMINATE,
            trusted=False,
            reason="provider_unavailable",
            evidence={"fresh": False},
        )
        case = remote_postcondition_case(observation)
        self.assertEqual(case.events, ())
        evaluation = evaluate_remote_observation(observation)
        self.assertEqual(evaluation.status, Status.UNVERIFIED)
        self.assertEqual(evaluation.failed_actions, ())
        self.assertEqual(evaluation.missing_actions, ("verify_remote:github:pull_request",))

    def test_case_uses_only_static_identifiers_and_public_evidence(self) -> None:
        observation = RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.MATCH,
            trusted=True,
            reason="matched",
            evidence={
                "repository_identity_matches": True,
                "head_matches": True,
                "base_matches": True,
                "state_matches": True,
                "fresh": True,
            },
        )
        case = remote_postcondition_case(observation)
        payload = json.dumps(
            {
                "case_id": case.case_id,
                "task": case.task,
                "requirements": [
                    {
                        "action": item.action,
                        "evidence_fields": list(item.evidence_fields),
                    }
                    for item in case.requirements
                ],
                "events": [
                    {
                        "action": item.action,
                        "success": item.success,
                        "evidence": item.evidence,
                    }
                    for item in case.events
                ],
            },
            sort_keys=True,
        )
        self.assertIn("verify_remote:github:pull_request", payload)
        self.assertIn("authenticated_remote_state", payload)
        for secret in (
            "PRIVATE_OWNER",
            "PRIVATE_REPO",
            "PRIVATE_BRANCH",
            "PRIVATE_TOKEN",
            "a" * 40,
        ):
            self.assertNotIn(secret, payload)

    def test_completion_claim_flag_is_type_checked(self) -> None:
        observation = RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.MATCH,
            trusted=True,
            reason="matched",
            evidence={"fresh": True},
        )
        with self.assertRaises(ValueError):
            remote_postcondition_case(observation, completion_claimed=1)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
