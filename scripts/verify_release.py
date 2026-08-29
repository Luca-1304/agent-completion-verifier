"""Run the checks expected before publishing a release."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from completion_verifier.benchmark import verify_manifest
from completion_verifier.sandbox import verify_sandbox_manifest

ROOT = Path(__file__).resolve().parents[1]
ENV = os.environ.copy()
ENV["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + ENV.get("PYTHONPATH", "")


def run(*command: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    print(f"\n$ {' '.join(command)}", flush=True)
    return subprocess.run(
        command,
        cwd=ROOT,
        env=ENV,
        check=True,
        text=True,
        capture_output=capture,
    )


def main() -> int:
    run(sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts")
    run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v")
    run(sys.executable, "scripts/verify_postconditions_release.py")
    run(sys.executable, "scripts/verify_remote_release.py")
    run(sys.executable, "-m", "completion_verifier", "data/cases.jsonl")
    run(
        sys.executable,
        "-m",
        "completion_verifier",
        "examples/minimal_cases.jsonl",
        "--json",
    )
    metrics = run(
        sys.executable,
        "-m",
        "completion_verifier",
        "data/cases.jsonl",
        "--metrics",
        capture=True,
    )
    metrics_payload = json.loads(metrics.stdout)
    if metrics_payload["total_cases"] != 16:
        raise AssertionError("Expected 16 benchmark cases.")
    if metrics_payload["status_counts"] != {
        "VERIFIED_COMPLETE": 7,
        "PARTIAL": 2,
        "UNVERIFIED": 4,
        "FAILED": 3,
    }:
        raise AssertionError("Unexpected benchmark status distribution.")

    generic = run(
        sys.executable,
        "-m",
        "completion_verifier.adapter_cli",
        "generic",
        "examples/generic_trace.json",
        "examples/requirements.json",
        "--source-ref",
        "release-generic",
        "--envelope",
        capture=True,
    )
    generic_payload = json.loads(generic.stdout)
    source = generic_payload["source"]
    if source["source_ref"] != "release-generic":
        raise AssertionError("Generic adapter lost its source reference.")
    if len(source["raw_sha256"]) != 64:
        raise AssertionError("Generic adapter produced an invalid source digest.")
    if any("source_event_id" in event["evidence"] for event in generic_payload["events"]):
        raise AssertionError("Provenance leaked into task evidence.")

    openai_case = run(
        sys.executable,
        "-m",
        "completion_verifier.adapter_cli",
        "openai",
        "examples/openai_tool_trace.json",
        "examples/requirements.json",
        "--source-ref",
        "release-openai",
        capture=True,
    )
    openai_payload = json.loads(openai_case.stdout)
    if "source" in openai_payload:
        raise AssertionError("Canonical case output must not contain provenance fields.")
    if openai_payload["events"][0]["action"] != "send_email":
        raise AssertionError("OpenAI-style adapter produced the wrong action.")

    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "reference-benchmark"
        benchmark = run(
            sys.executable,
            "-m",
            "completion_verifier.benchmark_cli",
            "--config",
            "examples/benchmark_config.json",
            "--output",
            str(output),
            capture=True,
        )
        summary = json.loads(benchmark.stdout)
        if summary["total_runs"] != 24 or not summary["manifest_verified"]:
            raise AssertionError("Benchmark summary is incomplete.")
        if not verify_manifest(output):
            raise AssertionError("Benchmark manifest did not verify.")
        benchmark_metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
        experiment = benchmark_metrics["experiment"]
        if experiment["injected_failure_runs"] != 21:
            raise AssertionError("Unexpected injected-failure run count.")
        if experiment["recovered_failure_runs"] != 5:
            raise AssertionError("Unexpected recovered-failure run count.")
        expected_group_rates = {
            "baseline": 0.875,
            "evidence_contract": 1 / 3,
            "verifier_feedback": 1 / 6,
        }
        for group, expected in expected_group_rates.items():
            actual = benchmark_metrics["groups"][group]["rates"]["false_completion_rate"]
            if abs(actual - expected) > 1e-12:
                raise AssertionError(f"Unexpected false-completion rate for {group}.")
        if len(list((output / "raw_traces").glob("*.json"))) != 24:
            raise AssertionError("Expected 24 raw trace artifacts.")
        if len(list((output / "envelopes").glob("*.json"))) != 24:
            raise AssertionError("Expected 24 envelope artifacts.")

    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "reference-sandbox"
        sandbox = run(
            sys.executable,
            "-m",
            "completion_verifier.sandbox_cli",
            "--config",
            "examples/sandbox_config.json",
            "--output",
            str(output),
            "--scenario",
            "all",
            capture=True,
        )
        summary = json.loads(sandbox.stdout)
        if summary["total_scenarios"] != 8 or not summary["manifest_verified"]:
            raise AssertionError("Sandbox summary is incomplete.")
        if not verify_sandbox_manifest(output):
            raise AssertionError("Sandbox manifest did not verify.")
        sandbox_metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
        expected_metrics = {
            "claimed_completion": 4,
            "false_completion": 3,
            "false_completion_rate": 0.75,
            "independently_verified_completion": 2,
            "silent_verified_completion": 1,
            "source_observation_agreement": 4,
            "source_false_positive": 3,
            "source_false_negative": 1,
            "security_rejection": 2,
        }
        for key, expected in expected_metrics.items():
            if sandbox_metrics[key] != expected:
                raise AssertionError(f"Unexpected sandbox metric: {key}.")
        if sandbox_metrics["status_counts"] != {
            "VERIFIED_COMPLETE": 2,
            "PARTIAL": 0,
            "UNVERIFIED": 0,
            "FAILED": 6,
        }:
            raise AssertionError("Unexpected sandbox status distribution.")
        if len(list((output / "runs").glob("*/source_report.json"))) != 8:
            raise AssertionError("Expected eight source report artifacts.")
        if len(list((output / "runs").glob("*/observation.json"))) != 8:
            raise AssertionError("Expected eight observation artifacts.")
        false_case = json.loads(
            (output / "runs/false_success/case.json").read_text(encoding="utf-8")
        )
        false_source = json.loads(
            (output / "runs/false_success/source_report.json").read_text(encoding="utf-8")
        )
        case_evidence = false_case["events"][0]["evidence"]
        if case_evidence.get("sha256") == false_source["reported_evidence"]["sha256"]:
            raise AssertionError("Source receipt leaked into canonical evidence.")
        if case_evidence["trust_basis"] != "independent_local_state":
            raise AssertionError("Canonical sandbox evidence has the wrong trust basis.")
        timeout_after = json.loads(
            (output / "runs/timeout_after_write/evaluation.json").read_text(
                encoding="utf-8"
            )
        )
        if timeout_after["status"] != "VERIFIED_COMPLETE":
            raise AssertionError("Timeout-after-write was not independently verified.")
        if any(path.is_symlink() for path in output.rglob("*")):
            raise AssertionError("Sandbox artifacts must not persist symlinks.")

    print("\nRelease verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
