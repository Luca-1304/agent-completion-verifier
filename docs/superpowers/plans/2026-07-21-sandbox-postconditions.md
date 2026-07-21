# Independent Sandbox Postconditions Implementation Plan

**Goal:** Add a safe local file-write sandbox where canonical verifier evidence comes only from independent state observation, not source-reported receipts.

**Architecture:** Introduce a focused `completion_verifier.sandbox` package with immutable contracts, confined filesystem operations, deterministic scenarios, an independent observer, canonical case conversion, artifact/manifest generation, metrics, and an installed CLI. Keep source reports, observations, cases, and evaluations separate.

**Tech Stack:** Python 3.10+, standard library only, existing evaluator and manifest patterns, unittest, setuptools scripts, GitHub Actions.

## Constraints

- No shell execution, arbitrary code execution, or network access.
- No intended reads/writes outside the disposable sandbox root.
- Source receipts never enter canonical evidence.
- Results are deterministic sandbox-methodology results, not external-model measurements.
- Existing 94 tests remain green on Python 3.10–3.13.

### Task 1: Contracts, observations, and safe filesystem boundary

- Create `src/completion_verifier/sandbox/models.py`.
- Create `src/completion_verifier/sandbox/filesystem.py`.
- Write failing tests for contract validation, digest, safe nested writes, observations, traversal, parent symlink and final symlink rejection.
- Implement minimal immutable models and confinement logic.
- Run focused and full tests.

### Task 2: Deterministic scenarios and independent case conversion

- Create `src/completion_verifier/sandbox/scenarios.py`.
- Create `src/completion_verifier/sandbox/runner.py`.
- Write failing tests for eight scenarios, false success, partial write, timeout before/after write, rollback, no external mutation, source-evidence exclusion, and silent verified completion.
- Implement source reports, independent observation, and case conversion.
- Run focused and full tests.

### Task 3: Suite artifacts, metrics, and manifest

- Create `src/completion_verifier/sandbox/suite.py`.
- Create `src/completion_verifier/sandbox/reporting.py`.
- Write failing tests for artifact separation, deterministic output, metrics, no-overwrite, manifest verification and tamper detection.
- Implement suite and reporting.
- Run focused and full tests.

### Task 4: CLI and package integration

- Create `src/completion_verifier/sandbox_cli.py`.
- Modify `src/completion_verifier/__init__.py` and `pyproject.toml` for v0.5.0 and `completion-verifier-sandbox`.
- Add CLI dry-run, single-scenario, full-suite and invalid-scenario tests.
- Run focused and full tests.

### Task 5: Documentation and release gates

- Create `docs/SANDBOX.md`.
- Modify `README.md`, `RESULTS.md`, `docs/RESEARCH_ROADMAP.md`, `scripts/verify_release.py`, and `.github/workflows/tests.yml`.
- Run all tests, release verifier, wheel build, clean-wheel suite and dependency checks.
- Repeat verification from a clean wheel.
- Publish via PR and merge only after Python 3.10–3.13 are fully green.
