from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from ...adapters import canonical_json_sha256
from ...benchmark.reporting import file_sha256, json_text, jsonl_text
from .models import R1ExperimentConfig, R1RunRecord


_R1_ARTIFACT_FILES = (
    "config.json",
    "runs.jsonl",
    "observations.jsonl",
    "evaluations.jsonl",
    "metrics.json",
    "report.md",
)


def _validate_forbidden_literals(values: Iterable[str]) -> tuple[str, ...]:
    result = tuple(values)
    if any(not isinstance(item, str) or not item for item in result):
        raise ValueError("Forbidden privacy sentinels must be non-empty strings.")
    return result


def _privacy_text(payload: object) -> str:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Privacy sentinel payload is not serializable.") from exc


def privacy_sentinel(
    payloads: Iterable[object], forbidden_literals: Iterable[str]
) -> bool:
    forbidden = _validate_forbidden_literals(forbidden_literals)
    text = "\n".join(_privacy_text(payload) for payload in payloads)
    return not any(literal in text for literal in forbidden)


def reserve_r1_output_dir(output_dir: Path) -> Path:
    """Reserve and probe the actual artifact destination before live mutation."""
    output_dir = Path(output_dir)
    if output_dir.is_symlink():
        raise ValueError("R1 artifact output directory cannot be a symlink.")
    if output_dir.exists():
        if not output_dir.is_dir() or any(output_dir.iterdir()):
            raise FileExistsError("R1 artifact output directory must be new or empty.")
    else:
        output_dir.mkdir(parents=True, exist_ok=False)
    probe = output_dir / ".r1-write-probe"
    try:
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
        raise OSError("R1 artifact output directory is not writable.") from exc
    return output_dir


def _prepare_output(output_dir: Path) -> None:
    reserve_r1_output_dir(output_dir)


def _build_report(
    config: R1ExperimentConfig,
    runs: tuple[R1RunRecord, ...],
    metrics: dict[str, object],
) -> str:
    scenarios = ", ".join(config.scenarios)
    cleanup_failures = metrics.get("cleanup_failure_count", 0)
    return (
        "# R1 controlled real-provider experiment\n\n"
        "This artifact set records privacy-minimal experiment output. "
        "It does not contain live target identifiers, credentials, raw provider bodies, "
        "or raw model text by default.\n\n"
        "## Scope\n\n"
        f"- Runs: {len(runs)}\n"
        f"- Scenarios: {scenarios}\n"
        f"- Treatment: {config.treatment}\n"
        f"- Scaffold: {config.scaffold_id} {config.scaffold_version}\n"
        f"- Cleanup failures: {cleanup_failures}\n"
        "\nA verifier MATCH means the reviewed remote contract matched the authenticated "
        "observation at that observation point. It does not prove causality, user "
        "authorization, permanence, provider integrity, or production safety.\n"
    )


def write_r1_artifacts(
    output_dir: Path,
    config: R1ExperimentConfig,
    runs: tuple[R1RunRecord, ...],
    metrics: dict[str, object],
    *,
    forbidden_literals: Iterable[str] = (),
) -> Path:
    output_dir = Path(output_dir)
    if not isinstance(config, R1ExperimentConfig):
        raise ValueError("R1 artifacts require an R1ExperimentConfig.")
    if not isinstance(runs, tuple) or not runs or not all(
        isinstance(item, R1RunRecord) for item in runs
    ):
        raise ValueError("R1 artifacts require a non-empty tuple of R1RunRecord objects.")
    if not isinstance(metrics, dict):
        raise ValueError("R1 metrics must be an object.")

    forbidden = _validate_forbidden_literals(forbidden_literals)
    public_config = config.to_public_dict()
    public_runs = [run.to_public_dict() for run in runs]
    observations = [
        {
            "schema_version": "1",
            "scenario_id": run.scenario_id,
            "observation_index": index,
            "observation": observation.to_dict(),
        }
        for run in runs
        for index, observation in enumerate(run.observations)
    ]
    evaluations = [
        {
            "schema_version": "1",
            "scenario_id": run.scenario_id,
            "evaluation_index": index,
            "evaluation": evaluation.to_dict(),
        }
        for run in runs
        for index, evaluation in enumerate(run.evaluations)
    ]
    report = _build_report(config, runs, metrics)

    public_payloads: tuple[object, ...] = (
        public_config,
        public_runs,
        observations,
        evaluations,
        metrics,
        report,
        _R1_ARTIFACT_FILES,
    )
    if forbidden and not privacy_sentinel(public_payloads, forbidden):
        raise ValueError("R1 public artifact privacy sentinel failed.")

    # Validate all JSON material before creating durable files.
    config_text = json_text(public_config)
    runs_text = jsonl_text(public_runs)
    observations_text = jsonl_text(observations)
    evaluations_text = jsonl_text(evaluations)
    metrics_text = json_text(metrics)

    _prepare_output(output_dir)
    (output_dir / "config.json").write_text(config_text, encoding="utf-8")
    (output_dir / "runs.jsonl").write_text(runs_text, encoding="utf-8")
    (output_dir / "observations.jsonl").write_text(observations_text, encoding="utf-8")
    (output_dir / "evaluations.jsonl").write_text(evaluations_text, encoding="utf-8")
    (output_dir / "metrics.json").write_text(metrics_text, encoding="utf-8")
    (output_dir / "report.md").write_text(report, encoding="utf-8")

    file_digests = {
        name: file_sha256(output_dir / name) for name in _R1_ARTIFACT_FILES
    }
    manifest = {
        "schema_version": "1",
        "artifact_kind": "r1_public_experiment",
        "public_config_digest": canonical_json_sha256(public_config),
        "files": file_digests,
    }
    (output_dir / "manifest.json").write_text(json_text(manifest), encoding="utf-8")
    verify_r1_manifest(output_dir)
    return output_dir


def verify_r1_manifest(output_dir: Path) -> bool:
    output_dir = Path(output_dir)
    manifest_path = output_dir / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("R1 manifest is missing.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("R1 manifest is invalid.") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1":
        raise ValueError("R1 manifest schema is invalid.")
    if manifest.get("artifact_kind") != "r1_public_experiment":
        raise ValueError("R1 manifest artifact kind is invalid.")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(_R1_ARTIFACT_FILES):
        raise ValueError("R1 manifest file mapping is invalid.")

    expected_files = set(_R1_ARTIFACT_FILES) | {"manifest.json"}
    actual_entries = tuple(output_dir.iterdir())
    if any(
        entry.name not in expected_files or entry.is_symlink() or not entry.is_file()
        for entry in actual_entries
    ):
        raise ValueError("R1 artifact directory contains missing or untracked files.")
    if {entry.name for entry in actual_entries} != expected_files:
        raise ValueError("R1 artifact directory contains missing or untracked files.")

    for name in _R1_ARTIFACT_FILES:
        expected = files.get(name)
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError("R1 manifest digest is invalid.")
        path = output_dir / name
        if path.is_symlink() or not path.is_file() or file_sha256(path) != expected:
            raise ValueError("R1 manifest digest mismatch.")

    config_path = output_dir / "config.json"
    try:
        public_config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("R1 public config is invalid.") from exc
    if not isinstance(public_config, dict):
        raise ValueError("R1 public config is invalid.")
    expected_config_digest = manifest.get("public_config_digest")
    if (
        not isinstance(expected_config_digest, str)
        or len(expected_config_digest) != 64
        or canonical_json_sha256(public_config) != expected_config_digest
    ):
        raise ValueError("R1 public config digest mismatch.")
    return True
