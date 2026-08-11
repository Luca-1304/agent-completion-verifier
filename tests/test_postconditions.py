from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from completion_verifier.postconditions import (
    DirectoryContract,
    DirectoryVerifier,
    JsonObjectContract,
    TextFileContract,
    TextFileVerifier,
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


class TextFileVerifierTests(unittest.TestCase):
    def test_exact_utf8_match_is_verified_without_exposing_content(self) -> None:
        with tempfile.TemporaryDirectory(prefix="PRIVATE_ROOT_SENTINEL-") as directory:
            root = Path(directory)
            target = root / "PRIVATE_FILE_NAME.txt"
            target.write_text("PRIVATE_OBSERVED_TEXT", encoding="utf-8")
            observation = TextFileVerifier().verify(
                TextFileContract(
                    "PRIVATE_FILE_NAME.txt",
                    "PRIVATE_OBSERVED_TEXT",
                    contract_id="PRIVATE_TEXT_ID",
                ),
                root,
            )
            self.assertTrue(observation.trusted)
            self.assertTrue(observation.matches)
            self.assertEqual(
                observation.evidence,
                {
                    "exists": True,
                    "regular_file": True,
                    "size_matches": True,
                    "content_matches": True,
                },
            )
            public = json.dumps(observation.to_dict(), sort_keys=True)
            for secret in (
                str(root),
                "PRIVATE_ROOT_SENTINEL",
                "PRIVATE_FILE_NAME",
                "PRIVATE_OBSERVED_TEXT",
                "PRIVATE_TEXT_ID",
            ):
                self.assertNotIn(secret, public)

    def test_missing_file_is_trusted_non_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observation = TextFileVerifier().verify(
                TextFileContract("missing.txt", "expected"), Path(directory)
            )
            self.assertTrue(observation.trusted)
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "missing")
            self.assertFalse(observation.evidence["exists"])

    def test_content_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "result.txt").write_text("actual", encoding="utf-8")
            observation = TextFileVerifier().verify(
                TextFileContract("result.txt", "expected"), root
            )
            self.assertTrue(observation.trusted)
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "content_mismatch")
            self.assertFalse(observation.evidence["content_matches"])

    def test_wrong_final_type_is_trusted_non_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "result.txt").mkdir()
            observation = TextFileVerifier().verify(
                TextFileContract("result.txt", "expected"), root
            )
            self.assertTrue(observation.trusted)
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "wrong_type")
            self.assertFalse(observation.evidence["regular_file"])

    def test_parent_symlink_is_untrusted_and_never_followed(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            outside_root = Path(outside)
            (outside_root / "secret.txt").write_text("PRIVATE_OUTSIDE_TEXT")
            (root / "link").symlink_to(outside_root, target_is_directory=True)
            observation = TextFileVerifier().verify(
                TextFileContract("link/secret.txt", "PRIVATE_OUTSIDE_TEXT"), root
            )
            self.assertFalse(observation.trusted)
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "unsafe_path")
            self.assertNotIn(
                "PRIVATE_OUTSIDE_TEXT", json.dumps(observation.to_dict(), sort_keys=True)
            )

    def test_final_symlink_is_untrusted_and_never_followed(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            outside_file = Path(outside) / "secret.txt"
            outside_file.write_text("PRIVATE_OUTSIDE_TEXT")
            (root / "result.txt").symlink_to(outside_file)
            observation = TextFileVerifier().verify(
                TextFileContract("result.txt", "PRIVATE_OUTSIDE_TEXT"), root
            )
            self.assertFalse(observation.trusted)
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "unsafe_path")

    def test_symlink_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as real:
            link = Path(directory) / "root-link"
            link.symlink_to(Path(real), target_is_directory=True)
            observation = TextFileVerifier().verify(
                TextFileContract("result.txt", "expected"), link
            )
            self.assertFalse(observation.trusted)
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "unsafe_path")


class DirectoryVerifierTests(unittest.TestCase):
    def test_existing_directory_matches_without_listing_contents(self) -> None:
        with tempfile.TemporaryDirectory(prefix="PRIVATE_DIR_ROOT-") as directory:
            root = Path(directory)
            target = root / "PRIVATE_TARGET_DIR"
            target.mkdir()
            (target / "PRIVATE_UNDECLARED_CHILD").write_text("PRIVATE_CHILD_CONTENT")
            observation = DirectoryVerifier().verify(
                DirectoryContract("PRIVATE_TARGET_DIR", contract_id="PRIVATE_DIR_ID"), root
            )
            self.assertTrue(observation.trusted)
            self.assertTrue(observation.matches)
            public = json.dumps(observation.to_dict(), sort_keys=True)
            for secret in (
                str(root),
                "PRIVATE_TARGET_DIR",
                "PRIVATE_UNDECLARED_CHILD",
                "PRIVATE_CHILD_CONTENT",
                "PRIVATE_DIR_ID",
            ):
                self.assertNotIn(secret, public)

    def test_required_children_are_checked_without_serializing_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "output"
            target.mkdir()
            (target / "PRIVATE_REQUIRED_A").write_text("a")
            (target / "PRIVATE_REQUIRED_B").mkdir()
            contract = DirectoryContract(
                "output",
                required_children=("PRIVATE_REQUIRED_A", "PRIVATE_REQUIRED_B"),
            )
            observation = DirectoryVerifier().verify(contract, root)
            self.assertTrue(observation.matches)
            self.assertTrue(observation.evidence["required_children_present"])
            public = json.dumps(observation.to_dict(), sort_keys=True)
            self.assertNotIn("PRIVATE_REQUIRED_A", public)
            self.assertNotIn("PRIVATE_REQUIRED_B", public)

    def test_missing_required_child_is_non_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "output").mkdir()
            observation = DirectoryVerifier().verify(
                DirectoryContract("output", required_children=("required.txt",)), root
            )
            self.assertTrue(observation.trusted)
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "required_children_missing")
            self.assertFalse(observation.evidence["required_children_present"])

    def test_exact_empty_accepts_empty_and_rejects_non_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "output"
            target.mkdir()
            contract = DirectoryContract("output", exact_empty=True)
            empty = DirectoryVerifier().verify(contract, root)
            self.assertTrue(empty.matches)
            self.assertTrue(empty.evidence["empty"])
            (target / "PRIVATE_ENTRY").write_text("x")
            non_empty = DirectoryVerifier().verify(contract, root)
            self.assertFalse(non_empty.matches)
            self.assertFalse(non_empty.evidence["empty"])
            self.assertEqual(non_empty.reason, "not_empty")
            self.assertNotIn("PRIVATE_ENTRY", json.dumps(non_empty.to_dict()))

    def test_missing_directory_is_trusted_non_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observation = DirectoryVerifier().verify(
                DirectoryContract("missing"), Path(directory)
            )
            self.assertTrue(observation.trusted)
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "missing")

    def test_file_at_directory_path_is_wrong_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "output").write_text("x")
            observation = DirectoryVerifier().verify(DirectoryContract("output"), root)
            self.assertTrue(observation.trusted)
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "wrong_type")
            self.assertFalse(observation.evidence["directory"])

    def test_directory_symlinks_are_untrusted(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            (root / "link").symlink_to(Path(outside), target_is_directory=True)
            final = DirectoryVerifier().verify(DirectoryContract("link"), root)
            self.assertFalse(final.trusted)
            self.assertFalse(final.matches)
            self.assertEqual(final.reason, "unsafe_path")
            (root / "parent").mkdir()
            (root / "parent" / "link").symlink_to(Path(outside), target_is_directory=True)
            nested = DirectoryVerifier().verify(DirectoryContract("parent/link/child"), root)
            self.assertFalse(nested.trusted)
            self.assertFalse(nested.matches)
            self.assertEqual(nested.reason, "unsafe_path")


if __name__ == "__main__":
    unittest.main()
