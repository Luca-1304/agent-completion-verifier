from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .evaluator import evaluate_cases
from .metrics import calculate_metrics
from .models import Case


def load_cases(path: Path) -> list[Case]:
    cases: list[Case] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                cases.append(Case.from_dict(raw))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    if not cases:
        raise ValueError(f"No cases found in {path}.")
    return cases


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate whether AI-agent completion claims are evidence-grounded."
    )
    parser.add_argument("cases", type=Path, help="Path to a JSONL case file.")
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--json", action="store_true", help="Emit detailed machine-readable JSON."
    )
    output.add_argument(
        "--metrics",
        action="store_true",
        help="Emit aggregate benchmark metrics as machine-readable JSON.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        cases = load_cases(args.cases)
        evaluations = evaluate_cases(cases)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if args.metrics:
        print(json.dumps(calculate_metrics(cases, evaluations).to_dict(), indent=2))
    elif args.json:
        print(json.dumps([value.to_dict() for value in evaluations], indent=2))
    else:
        for item in evaluations:
            print(f"{item.case_id:22} {item.status.value}")
        counts = Counter(item.status.value for item in evaluations)
        print("\nSummary")
        for status, count in sorted(counts.items()):
            print(f"  {status:20} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
