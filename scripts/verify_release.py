"""Run the checks expected before publishing a release."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = os.environ.copy()
ENV["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + ENV.get("PYTHONPATH", "")


def run(*command: str) -> None:
    print(f"\n$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, env=ENV, check=True)


def main() -> int:
    run(sys.executable, "-m", "compileall", "-q", "src", "tests")
    run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v")
    run(sys.executable, "-m", "completion_verifier", "data/cases.jsonl")
    run(sys.executable, "-m", "completion_verifier", "examples/minimal_cases.jsonl", "--json")
    print("\nRelease verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
