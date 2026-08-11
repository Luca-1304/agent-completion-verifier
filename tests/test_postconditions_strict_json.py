from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from completion_verifier.postconditions import JsonObjectContract, JsonObjectVerifier


class StrictJsonTests(unittest.TestCase):
    def test_non_standard_constants_are_invalid_json(self) -> None:
        for raw in ('{"value":NaN}', '{"value":Infinity}', '{"value":-Infinity}'):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "state.json").write_text(raw, encoding="utf-8")
                observation = JsonObjectVerifier().verify(
                    JsonObjectContract("state.json", {"value": 1}), root
                )
                self.assertTrue(observation.trusted)
                self.assertFalse(observation.matches)
                self.assertEqual(observation.reason, "invalid_json")
                self.assertFalse(observation.evidence["valid_json"])


if __name__ == "__main__":
    unittest.main()
