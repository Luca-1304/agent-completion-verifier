from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .adapters import (
    GenericJsonTraceAdapter,
    OpenAIToolTraceAdapter,
    TraceAdapterError,
)
from .models import Requirement


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path}:{exc.lineno}:{exc.colno}: invalid JSON: {exc.msg}"
        ) from exc


def load_requirements(path: Path) -> tuple[Requirement, ...]:
    raw = load_json(path)
    if not isinstance(raw, list) or not raw:
        raise ValueError("Requirements file must contain a non-empty JSON array.")
    try:
        return tuple(Requirement.from_dict(value) for value in raw)
    except ValueError as exc:
        raise ValueError(f"Invalid requirements in {path}: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Convert a strict external tool trace into the verifier's canonical "
            "case or provenance envelope."
        )
    )
    parser.add_argument(
        "adapter",
        choices=("generic", "openai"),
        help="Source trace shape to adapt.",
    )
    parser.add_argument("trace", type=Path, help="Path to the source trace JSON file.")
    parser.add_argument(
        "requirements",
        type=Path,
        help="Path to the independent requirements JSON array.",
    )
    parser.add_argument(
        "--source-ref",
        required=True,
        help="Stable path, run ID, URI, or other reference for the raw trace.",
    )
    parser.add_argument(
        "--envelope",
        action="store_true",
        help="Emit the provenance envelope instead of only the canonical case.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    adapters: dict[str, Any] = {
        "generic": GenericJsonTraceAdapter(),
        "openai": OpenAIToolTraceAdapter(),
    }

    try:
        raw = load_json(args.trace)
        requirements = load_requirements(args.requirements)
        envelope = adapters[args.adapter].adapt(
            raw,
            requirements=requirements,
            source_ref=args.source_ref,
        )
    except (OSError, ValueError, TraceAdapterError) as exc:
        parser.error(str(exc))

    payload = envelope.to_dict() if args.envelope else envelope.case_dict()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
