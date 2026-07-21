from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..adapters import GenericJsonTraceAdapter
from ..evaluator import evaluate_case
from ..models import Case, Evaluation
from .models import ExperimentConfig, build_run_matrix
from .reporting import (
    build_report,
    calculate_experiment_metrics,
    file_sha256,
    json_text,
    jsonl_text,
)
from .runner import ExperimentRunner, RawRunTrace
from .scenarios import default_scenarios


@dataclass(frozen=True)
class ExperimentResult:
    output_dir: Path
    total_runs: int
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        experiment = self.metrics["experiment"]
        return {
            "output_dir": str(self.output_dir),
            "total_runs": self.total_runs,
            "recovered_failure_runs": experiment["recovered_failure_runs"],
            "false_completion_rate": self.metrics["benchmark"]["rates"]["false_completion_rate"],
            "manifest_verified": True,
        }


def _prepare_output(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output directory is non-empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "raw_traces").mkdir()
    (output_dir / "envelopes").mkdir()


def run_experiment(
    config: ExperimentConfig,
    output_dir: Path,
    runner: ExperimentRunner,
) -> ExperimentResult:
    output_dir = Path(output_dir)
    _prepare_output(output_dir)
    requests = build_run_matrix(config)
    scenario_map = default_scenarios(config.requirements[0])
    adapter = GenericJsonTraceAdapter()
    runs: list[RawRunTrace] = []
    cases: list[Case] = []
    evaluations: list[Evaluation] = []

    (output_dir / "config.json").write_text(json_text(config.to_dict()), encoding="utf-8")

    for request in requests:
        raw = runner.run(request)
        if raw.run_id != request.run_id:
            raise ValueError("Runner returned a mismatched run ID.")
        runs.append(raw)
        raw_relative = Path("raw_traces") / f"{request.run_id}.json"
        (output_dir / raw_relative).write_text(json_text(raw.to_dict()), encoding="utf-8")
        envelope = adapter.adapt(
            raw.trace,
            requirements=config.requirements,
            source_ref=raw_relative.as_posix(),
        )
        envelope_payload = envelope.to_dict()
        (output_dir / "envelopes" / f"{request.run_id}.json").write_text(
            json_text(envelope_payload), encoding="utf-8"
        )
        case = envelope.to_case()
        evaluation = evaluate_case(case)
        cases.append(case)
        evaluations.append(evaluation)

    case_payloads = [
        {
            "case_id": case.case_id,
            "task": case.task,
            "completion_claimed": case.completion_claimed,
            "requirements": [
                {
                    "action": req.action,
                    "evidence_fields": list(req.evidence_fields),
                }
                for req in case.requirements
            ],
            "events": [
                {
                    "action": event.action,
                    "success": event.success,
                    "evidence": event.evidence,
                }
                for event in case.events
            ],
        }
        for case in cases
    ]
    (output_dir / "cases.jsonl").write_text(jsonl_text(case_payloads), encoding="utf-8")
    (output_dir / "evaluations.jsonl").write_text(
        jsonl_text(evaluation.to_dict() for evaluation in evaluations), encoding="utf-8"
    )
    (output_dir / "runs.jsonl").write_text(
        jsonl_text(
            {
                key: value
                for key, value in raw.to_dict().items()
                if key != "trace"
            }
            for raw in runs
        ),
        encoding="utf-8",
    )
    metrics = calculate_experiment_metrics(
        config, runs, cases, evaluations, scenario_map
    )
    (output_dir / "metrics.json").write_text(json_text(metrics), encoding="utf-8")
    (output_dir / "report.md").write_text(
        build_report(config, metrics, runner.name), encoding="utf-8"
    )

    files = {
        path.relative_to(output_dir).as_posix(): file_sha256(path)
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    manifest = {
        "schema_version": "1",
        "experiment_id": config.experiment_id,
        "config_digest": config.digest,
        "runner": runner.name,
        "runner_version": runner.version,
        "generated_at": config.generated_at,
        "files": files,
    }
    (output_dir / "manifest.json").write_text(json_text(manifest), encoding="utf-8")
    verify_manifest(output_dir)
    return ExperimentResult(output_dir, len(runs), metrics)


def verify_manifest(output_dir: Path) -> bool:
    output_dir = Path(output_dir)
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Manifest is missing.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("Manifest files mapping is invalid.")
    for relative, expected in files.items():
        path = output_dir / relative
        if not path.is_file():
            raise ValueError(f"Manifest file is missing: {relative}")
        actual = file_sha256(path)
        if actual != expected:
            raise ValueError(f"Manifest digest mismatch for {relative}.")
    return True
