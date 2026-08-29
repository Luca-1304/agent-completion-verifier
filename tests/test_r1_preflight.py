from __future__ import annotations

import unittest
from dataclasses import replace

from completion_verifier.experiments.r1.preflight import (
    R1LivePermit,
    R1LiveTarget,
    R1PreflightRequest,
    run_preflight,
    validate_live_permit,
)


class R1PreflightTests(unittest.TestCase):
    def _target(self, **overrides: object) -> R1LiveTarget:
        values: dict[str, object] = {
            "repository_locator": "PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO",
            "repository_id": 9001,
        }
        values.update(overrides)
        return R1LiveTarget(**values)  # type: ignore[arg-type]

    def _request(self, **overrides: object) -> R1PreflightRequest:
        values: dict[str, object] = {
            "live": True,
            "dry_run": False,
            "normal_ci": False,
            "scenario_id": "S0",
            "target": self._target(),
            "approved_repository_id": 9001,
            "target_locator_verified": True,
            "protected_repository_ids": frozenset({1307015021}),
            "requested_capabilities": (
                "create_branch",
                "write_fixture",
                "create_pull_request",
            ),
            "scenario_capabilities": (
                "create_branch",
                "write_fixture",
                "create_pull_request",
            ),
            "max_live_actions": 4,
            "actions_used": 0,
            "artifact_destination_new": True,
            "artifact_destination_writable": True,
            "privacy_sentinel_passed": True,
            "cleanup_plan_defined": True,
            "verifier_credential_available": True,
        }
        values.update(overrides)
        return R1PreflightRequest(**values)  # type: ignore[arg-type]

    def test_happy_path_returns_private_permit(self) -> None:
        result = run_preflight(self._request())
        self.assertTrue(result.allowed)
        self.assertEqual(result.reason_code, "preflight_passed")
        self.assertIsInstance(result.permit, R1LivePermit)
        self.assertEqual(repr(result.permit), "R1LivePermit()")
        self.assertNotIn("PRIVATE_OWNER", repr(result))

    def test_live_must_be_explicit_and_dry_run_or_ci_must_be_false(self) -> None:
        for changes, reason in (
            ({"live": False}, "live_mode_required"),
            ({"dry_run": True}, "dry_run_active"),
            ({"normal_ci": True}, "normal_ci_rejected"),
        ):
            with self.subTest(changes=changes):
                result = run_preflight(self._request(**changes))
                self.assertFalse(result.allowed)
                self.assertEqual(result.reason_code, reason)
                self.assertIsNone(result.permit)

    def test_target_identity_must_be_available_and_match_approved_id(self) -> None:
        for changes, reason in (
            ({"target": None}, "target_id_unavailable"),
            ({"approved_repository_id": None}, "target_id_unavailable"),
            ({"approved_repository_id": 9002}, "target_identity_mismatch"),
            ({"target_locator_verified": False}, "target_locator_unverified"),
        ):
            with self.subTest(changes=changes):
                result = run_preflight(self._request(**changes))
                self.assertFalse(result.allowed)
                self.assertEqual(result.reason_code, reason)

    def test_target_model_rejects_boolean_or_nonpositive_repository_id(self) -> None:
        for value in (True, 0, -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self._target(repository_id=value)

    def test_protected_repository_is_always_rejected(self) -> None:
        target = self._target(repository_id=1307015021)
        result = run_preflight(
            self._request(target=target, approved_repository_id=1307015021)
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason_code, "target_protected")

    def test_only_reviewed_scenarios_are_allowed(self) -> None:
        request = self._request()
        object.__setattr__(request, "scenario_id", "UNKNOWN")
        result = run_preflight(request)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason_code, "scenario_unreviewed")

    def test_capability_set_must_exactly_match_scenario(self) -> None:
        for requested in (
            ("create_branch",),
            (
                "create_branch",
                "write_fixture",
                "create_pull_request",
                "close_pull_request",
            ),
            ("merge",),
        ):
            with self.subTest(requested=requested):
                result = run_preflight(self._request(requested_capabilities=requested))
                self.assertFalse(result.allowed)
                self.assertEqual(result.reason_code, "capability_mismatch")

    def test_action_budget_must_be_valid_and_not_exhausted(self) -> None:
        for changes, reason in (
            ({"max_live_actions": True}, "action_budget_invalid"),
            ({"max_live_actions": 0}, "action_budget_invalid"),
            ({"actions_used": True}, "action_budget_invalid"),
            ({"actions_used": -1}, "action_budget_invalid"),
            ({"actions_used": 4}, "action_budget_exhausted"),
            ({"actions_used": 5}, "action_budget_exhausted"),
        ):
            with self.subTest(changes=changes):
                request = self._request()
                for key, value in changes.items():
                    object.__setattr__(request, key, value)
                result = run_preflight(request)
                self.assertFalse(result.allowed)
                self.assertEqual(result.reason_code, reason)

    def test_artifact_privacy_cleanup_and_verifier_requirements_fail_closed(self) -> None:
        for changes, reason in (
            ({"artifact_destination_new": False}, "artifact_destination_unsafe"),
            ({"artifact_destination_writable": False}, "artifact_destination_unsafe"),
            ({"privacy_sentinel_passed": False}, "privacy_sentinel_failed"),
            ({"cleanup_plan_defined": False}, "cleanup_plan_missing"),
            ({"verifier_credential_available": False}, "verifier_credential_unavailable"),
        ):
            with self.subTest(changes=changes):
                result = run_preflight(self._request(**changes))
                self.assertFalse(result.allowed)
                self.assertEqual(result.reason_code, reason)

    def test_boolean_preflight_flags_are_type_checked(self) -> None:
        for field in (
            "live",
            "dry_run",
            "normal_ci",
            "target_locator_verified",
            "artifact_destination_new",
            "artifact_destination_writable",
            "privacy_sentinel_passed",
            "cleanup_plan_defined",
            "verifier_credential_available",
        ):
            request = self._request()
            object.__setattr__(request, field, 1)
            with self.subTest(field=field), self.assertRaises(ValueError):
                run_preflight(request)

    def test_permit_is_bound_to_scenario_target_capabilities_and_budget(self) -> None:
        permit = run_preflight(self._request()).permit
        assert permit is not None
        self.assertTrue(
            validate_live_permit(
                permit,
                scenario_id="S0",
                repository_id=9001,
                capabilities=(
                    "create_branch",
                    "write_fixture",
                    "create_pull_request",
                ),
                actions_used=0,
                action_cost=1,
            )
        )
        for changes in (
            {"scenario_id": "S1"},
            {"repository_id": 9002},
            {"capabilities": ("create_branch",)},
            {"actions_used": 4},
            {"action_cost": 5},
        ):
            kwargs: dict[str, object] = {
                "scenario_id": "S0",
                "repository_id": 9001,
                "capabilities": (
                    "create_branch",
                    "write_fixture",
                    "create_pull_request",
                ),
                "actions_used": 0,
                "action_cost": 1,
            }
            kwargs.update(changes)
            with self.subTest(changes=changes):
                self.assertFalse(validate_live_permit(permit, **kwargs))  # type: ignore[arg-type]

    def test_preflight_repr_and_public_result_do_not_expose_target(self) -> None:
        request = self._request()
        result = run_preflight(request)
        self.assertEqual(repr(request.target), "R1LiveTarget()")
        self.assertEqual(repr(request), "R1PreflightRequest()")
        self.assertEqual(repr(result), "R1PreflightResult()")
        public = result.to_public_dict()
        rendered = str(public)
        self.assertNotIn("PRIVATE_OWNER", rendered)
        self.assertNotIn("9001", rendered)
        self.assertEqual(public, {"allowed": True, "reason_code": "preflight_passed"})


if __name__ == "__main__":
    unittest.main()
