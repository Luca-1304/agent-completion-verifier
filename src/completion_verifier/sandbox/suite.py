from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import SandboxRunResult, SandboxSuiteConfig
from .reporting import (
    build_report,
    calculate_sandbox_metrics,
    case_dict,
    file_sha256,
    json_text,
    jsonl_text,
)
from .runner import SandboxReferenceRunner


@dataclass(frozen=True)
class SandboxSuiteResult:
    output_dir: Path
    total_scenarios: int
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "total_scenarios": self.total_scenarios,
            "verified_complete": self.metrics["status_counts"]["VERIFIED_COMPLETE"],
            "failed": self.metrics["status_counts"]["FAILED"],
            "false_completion_rate": self.metrics["false_completion_rate"],
            "security_rejection": self.metrics["security_rejection"],
            "manifest_verified": True,
        }


def _prepare_output(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output directory is non-empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "runs").mkdir()


def run_sandbox_suite(
    config: SandboxSuiteConfig,
    output_dir: Path,
    runner: SandboxReferenceRunner | None = None,
) -> SandboxSuiteResult:
    output_dir = Path(output_dir)
    _prepare_output(output_dir)
    runner = runner or SandboxReferenceRunner()
    (output_dir / "suite_config.json").write_text(
        json_text(config.to_dict()), encoding="utf-8"
    )
    results: list[SandboxRunResult] = []
    for scenario_id in config.scenarios:
        run_dir = output_dir / "runs" / scenario_id
        state_dir = run_dir / "state"
        state_dir.mkdir(parents=True)
        result = runner.run(scenario_id, config.contract, state_dir)
        results.append(result)
        (run_dir / "contract.json").write_text(
            json_text(config.contract.to_dict()), encoding="utf-8"
        )
        (run_dir / "source_report.json").write_text(
            json_text(result.report.to_dict()), encoding="utf-8"
        )
        (run_dir / "observation.json").write_text(
            json_text(result.observation.to_dict()), encoding="utf-8"
        )
        (run_dir / "case.json").write_text(
            json_text(case_dict(result.case)), encoding="utf-8"
        )
        (run_dir / "evaluation.json").write_text(
            json_text(result.evaluation.to_dict()), encoding="utf-8"
        )

    (output_dir / "results.jsonl").write_text(
        jsonl_text(result.result_dict() for result in results), encoding="utf-8"
    )
    metrics = calculate_sandbox_metrics(results)
    (output_dir / "metrics.json").write_text(json_text(metrics), encoding="utf-8")
    (output_dir / "report.md").write_text(
        build_report(config, metrics), encoding="utf-8"
    )
    files = {
        path.relative_to(output_dir).as_posix(): file_sha256(path)
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and not path.is_symlink() and path.name != "manifest.json"
    }
    manifest = {
        "schema_version": "1",
        "suite_id": config.suite_id,
        "config_digest": config.digest,
        "generated_at": config.generated_at,
        "runner": runner.name,
        "runner_version": runner.version,
        "files": files,
    }
    (output_dir / "manifest.json").write_text(json_text(manifest), encoding="utf-8")
    verify_sandbox_manifest(output_dir)
    return SandboxSuiteResult(output_dir, len(results), metrics)


def verify_sandbox_manifest(output_dir: Path) -> bool:
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
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Manifest file is missing or unsafe: {relative}")
        actual = file_sha256(path)
        if actual != expected:
            raise ValueError(f"Manifest digest mismatch for {relative}.")
    return True
