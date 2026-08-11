from __future__ import annotations

import unittest

from completion_verifier.postconditions import (
    DirectoryContract,
    JsonObjectContract,
    TextFileContract,
)


class ContractReprPrivacyTests(unittest.TestCase):
    def test_contract_repr_excludes_caller_controlled_values(self) -> None:
        contracts = (
            TextFileContract(
                "PRIVATE_REPR_TEXT_PATH.txt",
                "PRIVATE_REPR_TEXT_VALUE",
                contract_id="PRIVATE_REPR_TEXT_ID",
            ),
            DirectoryContract(
                "PRIVATE_REPR_DIRECTORY",
                required_children=("PRIVATE_REPR_CHILD",),
                contract_id="PRIVATE_REPR_DIRECTORY_ID",
            ),
            JsonObjectContract(
                "PRIVATE_REPR_JSON.json",
                {"PRIVATE_REPR_KEY": "PRIVATE_REPR_VALUE"},
                contract_id="PRIVATE_REPR_JSON_ID",
            ),
        )
        forbidden = (
            "PRIVATE_REPR_TEXT_PATH",
            "PRIVATE_REPR_TEXT_VALUE",
            "PRIVATE_REPR_TEXT_ID",
            "PRIVATE_REPR_DIRECTORY",
            "PRIVATE_REPR_CHILD",
            "PRIVATE_REPR_DIRECTORY_ID",
            "PRIVATE_REPR_JSON",
            "PRIVATE_REPR_KEY",
            "PRIVATE_REPR_VALUE",
            "PRIVATE_REPR_JSON_ID",
        )
        for contract in contracts:
            rendered = repr(contract)
            for value in forbidden:
                self.assertNotIn(value, rendered)


if __name__ == "__main__":
    unittest.main()
