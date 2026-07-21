"""Run the checks expected before publishing a release."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from completion_verifier.benchmark import verify_manifest

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

    print("\nRelease verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
