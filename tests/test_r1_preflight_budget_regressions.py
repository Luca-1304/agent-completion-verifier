from __future__ import annotations

import unittest

from completion_verifier.experiments.r1.models import R1_CONTROLLER_ACTIONS
from completion_verifier.experiments.r1.preflight import (
    R1LiveTarget,
    R1PreflightRequest,
    run_preflight,
)


class R1PreflightBudgetRegressionTests(unittest.TestCase):
    def _request(self, **overrides: object) -> R1PreflightRequest:
        values: dict[str, object] = {
            "live": True,
            "dry_run": False,
            "normal_ci": False,
            "scenario_id": "S0",
            "target": R1LiveTarget(
                repository_locator="PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO",
                repository_id=9001,
            ),
            "approved_repository_id": 9001,
            "target_locator_verified": True,
            "protected_repository_ids": frozenset({1307015021}),
            "requested_capabilities": R1_CONTROLLER_ACTIONS,
            "scenario_capabilities": R1_CONTROLLER_ACTIONS,
            "max_live_actions": len(R1_CONTROLLER_ACTIONS),
            "actions_used": 0,
            "artifact_destination_new": True,
            "artifact_destination_writable": True,
            "privacy_sentinel_passed": True,
            "cleanup_plan_defined": True,
            "verifier_credential_available": True,
        }
        values.update(overrides)
        return R1PreflightRequest(**values)  # type: ignore[arg-type]

    def test_preflight_derives_capabilities_from_closed_scenario_definition(self) -> None:
        downgraded = R1_CONTROLLER_ACTIONS[:-1]
        result = run_preflight(
            self._request(
                requested_capabilities=downgraded,
                scenario_capabilities=downgraded,
            )
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason_code, "capability_mismatch")
        self.assertIsNone(result.permit)

    def test_preflight_rejects_budget_too_small_for_full_reviewed_sequence(self) -> None:
        result = run_preflight(
            self._request(max_live_actions=len(R1_CONTROLLER_ACTIONS) - 1)
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason_code, "action_budget_invalid")
        self.assertIsNone(result.permit)

    def test_preflight_rejects_consumed_budget_that_cannot_finish_sequence(self) -> None:
        result = run_preflight(
            self._request(max_live_actions=len(R1_CONTROLLER_ACTIONS), actions_used=1)
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason_code, "action_budget_exhausted")
        self.assertIsNone(result.permit)


if __name__ == "__main__":
    unittest.main()
