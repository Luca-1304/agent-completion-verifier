from __future__ import annotations

import unittest

from completion_verifier.experiments.r1.controller import (
    DryRunR1Controller,
    validate_r1_branch_name,
    validate_r1_fixture_path,
)


class R1ControllerTests(unittest.TestCase):
    def test_controller_exposes_only_reviewed_mutation_surface(self) -> None:
        controller = DryRunR1Controller()
        public_methods = {
            name
            for name in dir(controller)
            if not name.startswith("_") and callable(getattr(controller, name))
        }
        required = {"create_branch", "write_fixture", "create_pull_request", "close_pull_request"}
        forbidden = {
            "merge",
            "reopen",
            "force_push",
            "delete_branch",
            "delete_repository",
            "create_issue",
            "create_comment",
            "update_workflow",
        }
        self.assertTrue(required.issubset(public_methods))
        self.assertTrue(public_methods.isdisjoint(forbidden))

    def test_dry_run_records_intent_without_echoing_private_values(self) -> None:
        controller = DryRunR1Controller()
        receipt = controller.create_branch("a" * 40, "r1-exp-001")
        self.assertTrue(receipt.success)
        self.assertEqual(receipt.to_public_dict()["action"], "create_branch")
        self.assertNotIn("r1-exp-001", repr(receipt))
        self.assertNotIn("a" * 40, str(receipt.to_public_dict()))

    def test_branch_name_requires_reserved_prefix_and_single_component(self) -> None:
        self.assertEqual(validate_r1_branch_name("r1-exp-001"), "r1-exp-001")
        for value in (
            "main",
            "feature/r1-exp",
            "r1-exp/child",
            "r1-../bad",
            "r1-exp\\bad",
            " r1-exp-001 ",
            "r1-",
            "",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_r1_branch_name(value)

    def test_fixture_path_is_confined_to_reserved_prefix(self) -> None:
        self.assertEqual(
            validate_r1_fixture_path("r1-fixtures/run-001/state.txt"),
            "r1-fixtures/run-001/state.txt",
        )
        for value in (
            "state.txt",
            "/r1-fixtures/state.txt",
            "r1-fixtures/../state.txt",
            "r1-fixtures/./state.txt",
            "r1-fixtures//state.txt",
            "r1-fixtures\\state.txt",
            "C:/r1-fixtures/state.txt",
            "r1-fixtures/",
            "r1-fixtures/\x00state.txt",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_r1_fixture_path(value)

    def test_dry_run_validates_inputs_before_issuing_receipt(self) -> None:
        controller = DryRunR1Controller()
        with self.assertRaises(ValueError):
            controller.create_branch("short", "r1-exp-001")
        with self.assertRaises(ValueError):
            controller.write_fixture("r1-exp-001", "not-reserved/file.txt", "x")
        with self.assertRaises(ValueError):
            controller.create_pull_request("main", "main")
        for pull_number in (0, -1, True):
            with self.subTest(pull_number=pull_number), self.assertRaises(ValueError):
                controller.close_pull_request(pull_number)  # type: ignore[arg-type]

    def test_dry_run_receipts_use_fixed_action_cost(self) -> None:
        controller = DryRunR1Controller()
        receipts = (
            controller.create_branch("a" * 40, "r1-exp-001"),
            controller.write_fixture(
                "r1-exp-001", "r1-fixtures/run-001/state.txt", "hello"
            ),
            controller.create_pull_request("r1-exp-001", "main"),
            controller.close_pull_request(7),
        )
        self.assertTrue(all(item.action_cost == 1 for item in receipts))
        self.assertTrue(all(item.success for item in receipts))


if __name__ == "__main__":
    unittest.main()
