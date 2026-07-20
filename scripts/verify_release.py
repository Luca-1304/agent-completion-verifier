"""Run the checks expected before publishing a release."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
    payload = json.loads(metrics.stdout)
    if payload["total_cases"] != 16:
        raise AssertionError("Expected 16 benchmark cases.")
    if payload["status_counts"] != {
        "VERIFIED_COMPLETE": 7,
        "PARTIAL": 2,
        "UNVERIFIED": 4,
        "FAILED": 3,
    }:
        raise AssertionError("Unexpected benchmark status distribution.")
    print("\nRelease verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
