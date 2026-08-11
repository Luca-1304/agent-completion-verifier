from __future__ import annotations

import json
import unittest

from completion_verifier.postconditions import (
    DirectoryContract,
    JsonObjectContract,
    TextFileContract,
)


class ContractTests(unittest.TestCase):
    def test_text_contract_public_view_contains_no_caller_strings(self) -> None:
        contract = TextFileContract(
            "PRIVATE_PATH/result.txt",
            "PRIVATE_EXPECTED_TEXT",
            contract_id="PRIVATE_CONTRACT_ID",
        )
        public = json.dumps(contract.to_public_dict(), sort_keys=True)
        for secret in (
            "PRIVATE_PATH",
            "result.txt",
            "PRIVATE_EXPECTED_TEXT",
            "PRIVATE_CONTRACT_ID",
        ):
            self.assertNotIn(secret, public)
        self.assertEqual(contract.kind, "text_file")
        self.assertEqual(len(contract.identity_digest), 64)
        self.assertNotIn(contract.identity_digest, public)

    def test_json_contract_public_view_contains_no_keys_or_values(self) -> None:
        contract = JsonObjectContract(
            "PRIVATE_JSON_PATH/state.json",
            {"PRIVATE_JSON_KEY": "PRIVATE_JSON_VALUE"},
            contract_id="PRIVATE_JSON_CONTRACT",
        )
        public = json.dumps(contract.to_public_dict(), sort_keys=True)
        for secret in (
            "PRIVATE_JSON_PATH",
            "state.json",
            "PRIVATE_JSON_KEY",
            "PRIVATE_JSON_VALUE",
            "PRIVATE_JSON_CONTRACT",
        ):
            self.assertNotIn(secret, public)
        self.assertEqual(contract.kind, "json_object")
        self.assertEqual(len(contract.identity_digest), 64)
        self.assertNotIn(contract.identity_digest, public)

    def test_directory_contract_public_view_contains_no_child_names(self) -> None:
        contract = DirectoryContract(
            "PRIVATE_DIR_PATH",
            required_children=("PRIVATE_CHILD_A", "PRIVATE_CHILD_B"),
            contract_id="PRIVATE_DIR_CONTRACT",
        )
        public = json.dumps(contract.to_public_dict(), sort_keys=True)
        for secret in (
            "PRIVATE_DIR_PATH",
            "PRIVATE_CHILD_A",
            "PRIVATE_CHILD_B",
            "PRIVATE_DIR_CONTRACT",
        ):
            self.assertNotIn(secret, public)
        self.assertEqual(contract.kind, "directory")
        self.assertEqual(len(contract.identity_digest), 64)
        self.assertNotIn(contract.identity_digest, public)

    def test_contract_identity_digest_is_deterministic(self) -> None:
        first = JsonObjectContract(
            "state.json",
            {"alpha": 1, "beta": {"nested": True}},
            exact_keys=True,
            contract_id="c1",
        )
        second = JsonObjectContract(
            "state.json",
            {"beta": {"nested": True}, "alpha": 1},
            exact_keys=True,
            contract_id="c1",
        )
        self.assertEqual(first.identity_digest, second.identity_digest)

    def test_directory_contract_rejects_empty_plus_required_children(self) -> None:
        with self.assertRaisesRegex(ValueError, "exact_empty"):
            DirectoryContract(
                "output",
                required_children=("a.txt",),
                exact_empty=True,
            )

    def test_contracts_reject_unsupported_schema_version(self) -> None:
        factories = (
            lambda: TextFileContract("out.txt", "x", schema_version="2"),
            lambda: DirectoryContract("output", schema_version="2"),
            lambda: JsonObjectContract("state.json", {"ready": True}, schema_version="2"),
        )
        for factory in factories:
            with self.subTest(factory=factory), self.assertRaisesRegex(
                ValueError, "schema_version"
            ):
                factory()

    def test_contract_paths_fail_closed(self) -> None:
        invalid = (
            "/tmp/out.txt",
            "../out.txt",
            "folder/../out.txt",
            "folder//out.txt",
            "./out.txt",
            "folder\\out.txt",
            "C:/out.txt",
        )
        for path in invalid:
            with self.subTest(path=path), self.assertRaises(ValueError):
                TextFileContract(path, "x")

    def test_directory_child_names_are_direct_and_unique(self) -> None:
        for child in ("nested/file.txt", "../escape", "a\\b", "", "."):
            with self.subTest(child=child), self.assertRaises(ValueError):
                DirectoryContract("output", required_children=(child,))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            DirectoryContract("output", required_children=("a.txt", "a.txt"))

    def test_json_expected_keys_must_be_non_empty_strings(self) -> None:
        with self.assertRaises(ValueError):
            JsonObjectContract("state.json", {"": 1})
        with self.assertRaises(ValueError):
            JsonObjectContract("state.json", {1: "value"})  # type: ignore[dict-item]


if __name__ == "__main__":
    unittest.main()
