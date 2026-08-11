from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from completion_verifier.postconditions import JsonObjectContract, JsonObjectVerifier


class JsonObjectVerifierTests(unittest.TestCase):
    def test_subset_match_accepts_extra_keys_without_exposing_any_keys_or_values(self) -> None:
        with tempfile.TemporaryDirectory(prefix="PRIVATE_JSON_ROOT-") as directory:
            root = Path(directory)
            target = root / "PRIVATE_STATE_FILE.json"
            target.write_text(
                json.dumps(
                    {
                        "PRIVATE_EXPECTED_KEY": "PRIVATE_EXPECTED_VALUE",
                        "PRIVATE_EXTRA_KEY": "PRIVATE_EXTRA_VALUE",
                    }
                ),
                encoding="utf-8",
            )
            observation = JsonObjectVerifier().verify(
                JsonObjectContract(
                    "PRIVATE_STATE_FILE.json",
                    {"PRIVATE_EXPECTED_KEY": "PRIVATE_EXPECTED_VALUE"},
                    contract_id="PRIVATE_JSON_ID",
                ),
                root,
            )
            self.assertTrue(observation.trusted)
            self.assertTrue(observation.matches)
            self.assertTrue(observation.evidence["expected_keys_present"])
            self.assertTrue(observation.evidence["expected_values_match"])
            public = json.dumps(observation.to_dict(), sort_keys=True)
            for secret in (
                str(root),
                "PRIVATE_JSON_ROOT",
                "PRIVATE_STATE_FILE",
                "PRIVATE_EXPECTED_KEY",
                "PRIVATE_EXPECTED_VALUE",
                "PRIVATE_EXTRA_KEY",
                "PRIVATE_EXTRA_VALUE",
                "PRIVATE_JSON_ID",
            ):
                self.assertNotIn(secret, public)

    def test_value_mismatch_is_non_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state.json").write_text('{"status":"actual"}', encoding="utf-8")
            observation = JsonObjectVerifier().verify(
                JsonObjectContract("state.json", {"status": "expected"}), root
            )
            self.assertTrue(observation.trusted)
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "key_mismatch")
            self.assertTrue(observation.evidence["expected_keys_present"])
            self.assertFalse(observation.evidence["expected_values_match"])

    def test_missing_expected_key_is_non_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state.json").write_text('{"other":true}', encoding="utf-8")
            observation = JsonObjectVerifier().verify(
                JsonObjectContract("state.json", {"status": "ready"}), root
            )
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "key_mismatch")
            self.assertFalse(observation.evidence["expected_keys_present"])
            self.assertFalse(observation.evidence["expected_values_match"])

    def test_exact_key_mode_rejects_extra_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state.json").write_text(
                '{"status":"ready","extra":1}', encoding="utf-8"
            )
            observation = JsonObjectVerifier().verify(
                JsonObjectContract(
                    "state.json", {"status": "ready"}, exact_keys=True
                ),
                root,
            )
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "key_mismatch")
            self.assertFalse(observation.evidence["key_count_matches"])

    def test_invalid_utf8_fails_without_echoing_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state.json").write_bytes(b'{"key":"\xff"}')
            observation = JsonObjectVerifier().verify(
                JsonObjectContract("state.json", {"key": "expected"}), root
            )
            self.assertTrue(observation.trusted)
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "invalid_utf8")
            self.assertFalse(observation.evidence["valid_utf8"])

    def test_invalid_json_uses_fixed_reason_without_parser_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state.json").write_text(
                '{"PRIVATE_KEY":"PRIVATE_VALUE",', encoding="utf-8"
            )
            observation = JsonObjectVerifier().verify(
                JsonObjectContract("state.json", {"PRIVATE_KEY": "PRIVATE_VALUE"}),
                root,
            )
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "invalid_json")
            public = json.dumps(observation.to_dict(), sort_keys=True)
            self.assertNotIn("PRIVATE_KEY", public)
            self.assertNotIn("PRIVATE_VALUE", public)

    def test_duplicate_keys_are_rejected_without_echoing_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = '{"PRIVATE_DUP_KEY":"PRIVATE_A","PRIVATE_DUP_KEY":"PRIVATE_B"}'
            (root / "state.json").write_text(raw, encoding="utf-8")
            observation = JsonObjectVerifier().verify(
                JsonObjectContract("state.json", {"PRIVATE_DUP_KEY": "PRIVATE_A"}), root
            )
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "duplicate_key")
            public = json.dumps(observation.to_dict(), sort_keys=True)
            for secret in ("PRIVATE_DUP_KEY", "PRIVATE_A", "PRIVATE_B"):
                self.assertNotIn(secret, public)

    def test_top_level_non_object_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state.json").write_text('[1,2,3]', encoding="utf-8")
            observation = JsonObjectVerifier().verify(
                JsonObjectContract("state.json", {"status": "ready"}), root
            )
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "wrong_top_level")
            self.assertFalse(observation.evidence["top_level_object"])

    def test_missing_json_file_is_trusted_non_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observation = JsonObjectVerifier().verify(
                JsonObjectContract("missing.json", {"ready": True}), Path(directory)
            )
            self.assertTrue(observation.trusted)
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "missing")

    def test_json_symlink_is_untrusted(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            outside_file = Path(outside) / "state.json"
            outside_file.write_text('{"PRIVATE_KEY":"PRIVATE_VALUE"}')
            (root / "state.json").symlink_to(outside_file)
            observation = JsonObjectVerifier().verify(
                JsonObjectContract("state.json", {"PRIVATE_KEY": "PRIVATE_VALUE"}), root
            )
            self.assertFalse(observation.trusted)
            self.assertFalse(observation.matches)
            self.assertEqual(observation.reason, "unsafe_path")
            public = json.dumps(observation.to_dict(), sort_keys=True)
            self.assertNotIn("PRIVATE_KEY", public)
            self.assertNotIn("PRIVATE_VALUE", public)


if __name__ == "__main__":
    unittest.main()
