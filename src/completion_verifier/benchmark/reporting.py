from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from ..evaluator import _has_evidence_value
from ..metrics import calculate_metrics
from ..models import Case, Evaluation, Status
from .models import ExperimentConfig, FailureScenario
from .runner import RawRunTrace


def json_text(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def jsonl_text(values: Iterable[object]) -> str:
    return "".join(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
        for value in values
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _event_complete(case: Case, event_index: int = -1) -> bool:
    requirement = case.requirements[0]
    matching = [event for event in case.events if event.action == requirement.action]
    if not matching:
        return False
    event = matching[event_index]
    return event.success and all(
        field in event.evidence and _has_evidence_value(event.evidence[field])
        for field in requirement.evidence_fields
    )


def _recovered(case: Case) -> bool:
    requirement = case.requirements[0]
    matching = [event for event in case.events if event.action == requirement.action]
    if len(matching) < 2 or not _event_complete(case):
        return False
    return any(
        not (
            event.success
            and all(
                field in event.evidence and _has_evidence_value(event.evidence[field])
                for field in requirement.evidence_fields
            )
        )
        for event in matching[:-1]
    )


def _mean_or_none(values: list[float | int | None]) -> float | None:
    if not values or any(value is None for value in values):
        return None
    numbers = [float(value) for value in values if value is not None]
    return sum(numbers) / len(numbers)


def calculate_experiment_metrics(
    config: ExperimentConfig,
    runs: list[RawRunTrace],
    cases: list[Case],
    evaluations: list[Evaluation],
    scenario_map: dict[str, FailureScenario],
) -> dict[str, Any]:
    overall = calculate_metrics(cases, evaluations).to_dict()

    def summary(indices: list[int]) -> dict[str, Any]:
        subset_cases = [cases[index] for index in indices]
        subset_evaluations = [evaluations[index] for index in indices]
        subset_runs = [runs[index] for index in indices]
        injected = sum(
            scenario_map[run.scenario_id].injected_failure for run in subset_runs
        )
        recovered = sum(
            scenario_map[run.scenario_id].injected_failure and _recovered(case)
            for run, case in zip(subset_runs, subset_cases, strict=True)
        )
        unnecessary = sum(run.unnecessary_retry_count > 0 for run in subset_runs)
        refusals = sum(run.refused for run in subset_runs)
        base = calculate_metrics(subset_cases, subset_evaluations).to_dict()
        return {
            "total_runs": len(indices),
            "injected_failure_runs": injected,
            "recovered_failure_runs": recovered,
            "recovery_rate_given_injected_failure": recovered / injected if injected else 0.0,
            "unnecessary_retry_runs": unnecessary,
            "unnecessary_retry_rate": unnecessary / len(indices) if indices else 0.0,
            "refusal_runs": refusals,
            "refusal_rate": refusals / len(indices) if indices else 0.0,
            "mean_elapsed_ms": _mean_or_none([run.elapsed_ms for run in subset_runs]),
            "mean_input_tokens": _mean_or_none([run.input_tokens for run in subset_runs]),
            "mean_output_tokens": _mean_or_none([run.output_tokens for run in subset_runs]),
            "status_counts": base["status_counts"],
            "claim_counts": base["claim_counts"],
            "rates": base["rates"],
        }

    all_indices = list(range(len(runs)))
    groups = {
        group: summary([index for index, run in enumerate(runs) if run.group == group])
        for group in config.groups
    }
    scenarios: dict[str, Any] = {}
    for scenario_id in config.scenarios:
        indices = [
            index for index, run in enumerate(runs) if run.scenario_id == scenario_id
        ]
        statuses = Counter(evaluations[index].status.value for index in indices)
        scenarios[scenario_id] = {
            "total_runs": len(indices),
            "injected_failure": scenario_map[scenario_id].injected_failure,
            "recovered_failure_runs": sum(_recovered(cases[index]) for index in indices),
            "status_counts": {
                status.value: statuses[status.value] for status in Status
            },
        }

    return {
        "schema_version": "1",
        "experiment_id": config.experiment_id,
        "config_digest": config.digest,
        "benchmark": overall,
        "experiment": summary(all_indices),
        "groups": groups,
        "scenarios": scenarios,
        "limitations": {
            "runner_type": "scripted-reference",
            "external_model_results": False,
            "timing_and_tokens_measured": False,
        },
    }


def build_report(config: ExperimentConfig, metrics: dict[str, Any], runner: str) -> str:
    experiment = metrics["experiment"]
    return f"""# Controlled failure-injection benchmark\n\nGenerated at: {config.generated_at}\n\nThis run validates the experiment harness with deterministic **scripted reference policies**. It is not an external-model benchmark and makes no claim about OpenAI, Anthropic, or any other model.\n\n## Configuration\n\n- Experiment: `{config.experiment_id}`\n- Configuration digest: `{config.digest}`\n- Runner: `{runner}`\n- Seed: `{config.seed}`\n- Repetitions: `{config.repetitions}`\n- Groups: {', '.join(config.groups)}\n- Scenarios: {', '.join(config.scenarios)}\n\n## Headline results\n\n- Total runs: {experiment['total_runs']}\n- Injected-failure runs: {experiment['injected_failure_runs']}\n- Recovered failure runs: {experiment['recovered_failure_runs']}\n- Recovery rate given injected failure: {experiment['recovery_rate_given_injected_failure']:.6f}\n- Unnecessary retry runs: {experiment['unnecessary_retry_runs']}\n- Refusal runs: {experiment['refusal_runs']}\n\n## Artifact boundary\n\nRaw traces, provenance envelopes, canonical cases, evaluations, run metadata and aggregate metrics are stored separately. Source-reported tool evidence is transformed deterministically but is not independent proof of external state, identity, authorisation or causality.\n\n## Reproduce\n\n```bash\ncompletion-verifier-benchmark --config examples/benchmark_config.json --output benchmark_runs/reference-v1\n```\n"""
