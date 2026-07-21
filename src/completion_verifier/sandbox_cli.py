from __future__ import annotations

import argparse
import json
from pathlib import Path

from .sandbox import (
    SCENARIO_IDS,
    SandboxSuiteConfig,
    run_sandbox_suite,
)


def load_config(path: Path) -> SandboxSuiteConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path}:{exc.lineno}:{exc.colno}: invalid JSON: {exc.msg}"
        ) from exc
    return SandboxSuiteConfig.from_dict(raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic file-write scenarios and independently verify "
            "their local sandbox postconditions."
        )
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--scenario",
        choices=("all", *SCENARIO_IDS),
        default="all",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved suite without creating sandbox files.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.scenario != "all":
            config = config.with_scenarios((args.scenario,))
        if args.dry_run:
            payload = {
                "suite_id": config.suite_id,
                "config_digest": config.digest,
                "contract_digest": config.contract.digest,
                "scenarios": list(config.scenarios),
            }
        else:
            payload = run_sandbox_suite(config, args.output).to_dict()
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
