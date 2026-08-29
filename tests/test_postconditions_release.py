from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

import completion_verifier
from completion_verifier.postconditions import (
    DirectoryContract,
    JsonObjectContract,
    TextFileContract,
    verify_postcondition,
)


ROOT = Path(__file__).resolve().parents[1]
POSTCONDITION_SOURCE = ROOT / "src" / "completion_verifier" / "postconditions"


class ReleaseBoundaryTests(unittest.TestCase):
    def test_current_release_version_is_0_8_0_everywhere(self) -> None:
        self.assertEqual(completion_verifier.__version__, "0.8.0")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "0.8.0")

    def test_postcondition_documentation_states_disclosure_boundary(self) -> None:
        doc = ROOT / "docs" / "POSTCONDITIONS.md"
        self.assertTrue(doc.is_file())
        text = doc.read_text(encoding="utf-8")
        self.assertIn("privacy-safe public serialization", text)
        self.assertIn("does not prove remote identity", text)
        self.assertIn("no network", text.lower())

    def test_postcondition_package_does_not_read_environment_or_import_network_clients(self) -> None:
        forbidden = (
            "os.environ",
            "os.getenv",
            "getenv(",
            "import requests",
            "import httpx",
            "import socket",
            "from urllib",
            "import urllib",
            "OPENAI_API_KEY",
        )
        offenders: list[str] = []
        for path in sorted(POSTCONDITION_SOURCE.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                if marker in text:
                    offenders.append(f"{path.name}:{marker}")
        self.assertEqual(offenders, [])

    def test_representative_public_observations_exclude_all_caller_strings(self) -> None:
        with tempfile.TemporaryDirectory(prefix="PRIVATE_RELEASE_ROOT-") as directory:
            root = Path(directory)
            (root / "PRIVATE_TEXT_FILE.txt").write_text("PRIVATE_TEXT_VALUE")
            target_dir = root / "PRIVATE_DIRECTORY"
            target_dir.mkdir()
            (target_dir / "PRIVATE_CHILD").write_text("PRIVATE_CHILD_VALUE")
            (root / "PRIVATE_JSON_FILE.json").write_text(
                '{"PRIVATE_JSON_KEY":"PRIVATE_JSON_VALUE"}', encoding="utf-8"
            )
            contracts = (
                TextFileContract(
                    "PRIVATE_TEXT_FILE.txt",
                    "PRIVATE_TEXT_VALUE",
                    contract_id="PRIVATE_TEXT_ID",
                ),
                DirectoryContract(
                    "PRIVATE_DIRECTORY",
                    required_children=("PRIVATE_CHILD",),
                    contract_id="PRIVATE_DIRECTORY_ID",
                ),
                JsonObjectContract(
                    "PRIVATE_JSON_FILE.json",
                    {"PRIVATE_JSON_KEY": "PRIVATE_JSON_VALUE"},
                    contract_id="PRIVATE_JSON_ID",
                ),
            )
            payloads = [
                json.dumps(verify_postcondition(contract, root).to_dict(), sort_keys=True)
                for contract in contracts
            ]
            combined = "\n".join(payloads)
            forbidden = (
                str(root),
                "PRIVATE_RELEASE_ROOT",
                "PRIVATE_TEXT_FILE",
                "PRIVATE_TEXT_VALUE",
                "PRIVATE_TEXT_ID",
                "PRIVATE_DIRECTORY",
                "PRIVATE_CHILD",
                "PRIVATE_CHILD_VALUE",
                "PRIVATE_DIRECTORY_ID",
                "PRIVATE_JSON_FILE",
                "PRIVATE_JSON_KEY",
                "PRIVATE_JSON_VALUE",
                "PRIVATE_JSON_ID",
            )
            for secret in forbidden:
                self.assertNotIn(secret, combined)
            for contract in contracts:
                self.assertNotIn(contract.identity_digest, combined)


if __name__ == "__main__":
    unittest.main()
