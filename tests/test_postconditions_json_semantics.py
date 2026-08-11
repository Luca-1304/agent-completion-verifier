from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from completion_verifier.postconditions import JsonObjectContract, JsonObjectVerifier


class JsonSemanticTests(unittest.TestCase):
    def test_json_boolean_and_number_are_distinct_values(self) -> None:
        cases = (
            ('{"value":true}', {"value": 1}),
            ('{"value":1}', {"value": True}),
            ('{"value":[true]}', {"value": [1]}),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw, expected=expected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "state.json").write_text(raw, encoding="utf-8")
                observation = JsonObjectVerifier().verify(
                    JsonObjectContract("state.json", expected), root
                )
                self.assertTrue(observation.trusted)
                self.assertFalse(observation.matches)
                self.assertEqual(observation.reason, "key_mismatch")
                self.assertFalse(observation.evidence["expected_values_match"])

    def test_json_contract_expected_state_is_deeply_immutable(self) -> None:
        source = {
            "nested": {"flag": True},
            "items": [1, {"ready": True}],
        }
        contract = JsonObjectContract("state.json", source)
        original_digest = contract.identity_digest

        source["nested"]["flag"] = False
        source["items"][1]["ready"] = False
        self.assertEqual(contract.identity_digest, original_digest)

        with self.assertRaises(TypeError):
            contract.expected["new"] = "value"  # type: ignore[index]
        with self.assertRaises(TypeError):
            contract.expected["nested"]["flag"] = False  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
