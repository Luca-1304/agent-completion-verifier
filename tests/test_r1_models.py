from __future__ import annotations

import unittest

from completion_verifier.experiments.r1 import (
    R1ExperimentConfig,
    R1SourceClaim,
    R1ControllerReceipt,
    R1_SCENARIOS,
)


class R1ExperimentModelTests(unittest.TestCase):
    def _config(self, **overrides: object) -> R1ExperimentConfig:
        values: dict[str, object] = {
            "experiment_id": "r1-pilot",
            "seed": 7,
            "repetitions": 1,
            "scenarios": ("S0",),
            "treatment": "baseline",
            "scaffold_id": "scaffold-a",
            "scaffold_version": "1",
            "max_live_actions": 4,
        }
        values.update(overrides)
        return R1ExperimentConfig(**values)  # type: ignore[arg-type]

    def test_config_is_dry_run_by_default(self) -> None:
        config = self._config()
        self.assertFalse(config.live)
        self.assertIn("S0", R1_SCENARIOS)
        self.assertEqual(
            R1_SCENARIOS,
            ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"),
        )

    def test_config_rejects_invalid_numeric_fields(self) -> None:
        for field, value in (
            ("seed", True),
            ("repetitions", True),
            ("repetitions", 0),
            ("repetitions", -1),
            ("max_live_actions", True),
            ("max_live_actions", 0),
            ("max_live_actions", -1),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self._config(**{field: value})

    def test_config_rejects_unknown_or_duplicate_scenarios(self) -> None:
        for scenarios in (("UNKNOWN",), ("S0", "S0"), ()):
            with self.subTest(scenarios=scenarios), self.assertRaises(ValueError):
                self._config(scenarios=scenarios)

    def test_config_rejects_unknown_treatment(self) -> None:
        with self.assertRaises(ValueError):
            self._config(treatment="invented")

    def test_config_rejects_empty_text_fields(self) -> None:
        for field in ("experiment_id", "scaffold_id", "scaffold_version"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self._config(**{field: "  "})

    def test_config_repr_and_public_dict_are_disclosure_safe(self) -> None:
        config = self._config(experiment_id="PRIVATE_EXPERIMENT_SENTINEL")
        rendered = repr(config)
        public = config.to_public_dict()
        self.assertEqual(rendered, "R1ExperimentConfig()")
        self.assertNotIn("PRIVATE_EXPERIMENT_SENTINEL", rendered)
        self.assertNotIn("PRIVATE_EXPERIMENT_SENTINEL", str(public))
        self.assertEqual(public["schema_version"], "1")
        self.assertEqual(public["scenarios"], ["S0"])
        self.assertEqual(public["treatment"], "baseline")
        self.assertEqual(public["scaffold_id"], "scaffold-a")
        self.assertEqual(public["scaffold_version"], "1")
        self.assertEqual(public["repetitions"], 1)
        self.assertEqual(public["max_live_actions"], 4)
        self.assertFalse(public["live"])

    def test_source_claim_and_controller_receipt_are_distinct_types(self) -> None:
        claim = R1SourceClaim(
            completion_claimed=True,
            retry_count=1,
            refusal=False,
            action_count=2,
        )
        receipt = R1ControllerReceipt(
            action="create_branch",
            success=True,
            action_cost=1,
        )
        self.assertIsNot(type(claim), type(receipt))
        self.assertEqual(claim.to_public_dict()["completion_claimed"], True)
        self.assertEqual(receipt.to_public_dict()["action"], "create_branch")

    def test_model_repr_does_not_echo_private_metadata(self) -> None:
        claim = R1SourceClaim(
            completion_claimed=True,
            retry_count=0,
            refusal=False,
            action_count=1,
            private_trace_ref="PRIVATE_TRACE_SENTINEL",
        )
        receipt = R1ControllerReceipt(
            action="create_pull_request",
            success=False,
            action_cost=1,
            error_code="provider_rejected",
            private_target_ref="PRIVATE_TARGET_SENTINEL",
        )
        self.assertEqual(repr(claim), "R1SourceClaim()")
        self.assertEqual(repr(receipt), "R1ControllerReceipt()")
        self.assertNotIn("PRIVATE_TRACE_SENTINEL", str(claim.to_public_dict()))
        self.assertNotIn("PRIVATE_TARGET_SENTINEL", str(receipt.to_public_dict()))


if __name__ == "__main__":
    unittest.main()
