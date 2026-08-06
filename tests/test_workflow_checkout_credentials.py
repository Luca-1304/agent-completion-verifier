from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _checkout_steps(text: str) -> list[str]:
    lines = text.splitlines()
    steps: list[str] = []

    for index, line in enumerate(lines):
        if "uses: actions/checkout@" not in line:
            continue

        uses_indent = _indent(line)
        step_indent = max(uses_indent - 2, 0)
        start = index
        while start > 0:
            candidate = lines[start]
            if _indent(candidate) == step_indent and candidate.lstrip().startswith("- "):
                break
            start -= 1

        end = index + 1
        while end < len(lines):
            candidate = lines[end]
            stripped = candidate.strip()
            if stripped and _indent(candidate) < step_indent:
                break
            if _indent(candidate) == step_indent and candidate.lstrip().startswith("- "):
                break
            end += 1

        steps.append("\n".join(lines[start:end]))

    return steps


class WorkflowCheckoutCredentialTests(unittest.TestCase):
    def test_checkout_never_persists_token_after_read_only_clone(self) -> None:
        offenders: list[str] = []
        checkout_count = 0

        for workflow in sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml"))):
            for position, step in enumerate(_checkout_steps(workflow.read_text(encoding="utf-8")), 1):
                checkout_count += 1
                if "persist-credentials: false" not in step:
                    offenders.append(f"{workflow.name} checkout step {position}")

        self.assertGreater(checkout_count, 0)
        self.assertEqual(
            offenders,
            [],
            "Checkout credentials remain persisted in: " + ", ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
