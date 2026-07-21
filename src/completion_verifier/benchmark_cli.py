from __future__ import annotations

import argparse
import json
from pathlib import Path

from .benchmark import (
    ExperimentConfig,
    ScriptedReferenceRunner,
    build_run_matrix,
    run_experiment,
)


def load_config(path: Path) -> ExperimentConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path}:{exc.lineno}:{exc.colno}: invalid JSON: {exc.msg}"
        ) from exc
    return ExperimentConfig.from_dict(raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a reproducible controlled failure-injection benchmark."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--runner",
        choices=("scripted-reference",),
        default="scripted-reference",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved deterministic run matrix without writing artifacts.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        runner = ScriptedReferenceRunner()
        if args.dry_run:
            matrix = build_run_matrix(config)
            payload = {
                "experiment_id": config.experiment_id,
                "config_digest": config.digest,
                "runner": runner.name,
                "runner_version": runner.version,
                "runs": [
                    {
                        "run_id": request.run_id,
                        "group": request.group,
                        "scenario": request.scenario.scenario_id,
                        "repetition": request.repetition,
                        "seed": request.seed,
                    }
                    for request in matrix
                ],
            }
        else:
            payload = run_experiment(config, args.output, runner).to_dict()
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
