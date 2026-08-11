"""Provider-free release smoke for the v0.7 postcondition SDK."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from completion_verifier.models import Status
from completion_verifier.postconditions import (
    DirectoryContract,
    JsonObjectContract,
    TextFileContract,
    evaluate_postcondition,
    verify_postcondition,
)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="PRIVATE_RELEASE_VERIFY_ROOT-") as directory:
        root = Path(directory)

        (root / "PRIVATE_RELEASE_TEXT.txt").write_text(
            "PRIVATE_RELEASE_TEXT_VALUE", encoding="utf-8"
        )
        target_dir = root / "PRIVATE_RELEASE_DIRECTORY"
        target_dir.mkdir()
        (target_dir / "PRIVATE_RELEASE_CHILD").write_text(
            "PRIVATE_RELEASE_CHILD_VALUE", encoding="utf-8"
        )
        (root / "PRIVATE_RELEASE_JSON.json").write_text(
            '{"PRIVATE_RELEASE_JSON_KEY":"PRIVATE_RELEASE_JSON_VALUE"}',
            encoding="utf-8",
        )

        contracts = (
            TextFileContract(
                "PRIVATE_RELEASE_TEXT.txt",
                "PRIVATE_RELEASE_TEXT_VALUE",
                contract_id="PRIVATE_RELEASE_TEXT_ID",
            ),
            DirectoryContract(
                "PRIVATE_RELEASE_DIRECTORY",
                required_children=("PRIVATE_RELEASE_CHILD",),
                contract_id="PRIVATE_RELEASE_DIRECTORY_ID",
            ),
            JsonObjectContract(
                "PRIVATE_RELEASE_JSON.json",
                {"PRIVATE_RELEASE_JSON_KEY": "PRIVATE_RELEASE_JSON_VALUE"},
                contract_id="PRIVATE_RELEASE_JSON_ID",
            ),
        )

        observations = [verify_postcondition(contract, root) for contract in contracts]
        evaluations = [evaluate_postcondition(contract, root) for contract in contracts]
        if not all(observation.trusted and observation.matches for observation in observations):
            raise AssertionError("A representative postcondition did not verify.")
        if not all(evaluation.status is Status.VERIFIED_COMPLETE for evaluation in evaluations):
            raise AssertionError("Postcondition evaluation did not reuse verified completion.")

        public_payload = json.dumps(
            {
                "contracts": [contract.to_public_dict() for contract in contracts],
                "observations": [observation.to_dict() for observation in observations],
                "evaluations": [evaluation.to_dict() for evaluation in evaluations],
            },
            sort_keys=True,
        )
        forbidden = (
            str(root),
            "PRIVATE_RELEASE_VERIFY_ROOT",
            "PRIVATE_RELEASE_TEXT",
            "PRIVATE_RELEASE_TEXT_VALUE",
            "PRIVATE_RELEASE_TEXT_ID",
            "PRIVATE_RELEASE_DIRECTORY",
            "PRIVATE_RELEASE_CHILD",
            "PRIVATE_RELEASE_CHILD_VALUE",
            "PRIVATE_RELEASE_DIRECTORY_ID",
            "PRIVATE_RELEASE_JSON",
            "PRIVATE_RELEASE_JSON_KEY",
            "PRIVATE_RELEASE_JSON_VALUE",
            "PRIVATE_RELEASE_JSON_ID",
        )
        for value in forbidden:
            if value in public_payload:
                raise AssertionError("Postcondition public serialization leaked caller data.")
        for contract in contracts:
            if contract.identity_digest in public_payload:
                raise AssertionError("Internal contract digest leaked into public serialization.")

    print("Postcondition release verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
