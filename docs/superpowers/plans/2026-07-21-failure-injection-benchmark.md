# Controlled Failure-Injection Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, provider-neutral experiment harness with a scripted reference runner, separated raw/derived artifacts, failure-conditioned metrics, and a wheel-installed CLI.

**Architecture:** Add a focused `completion_verifier.benchmark` package. Immutable configuration and scenario models produce a deterministic run matrix; a runner protocol supplies raw traces; the harness adapts and evaluates them with the existing verifier, writes reproducible artifacts, and verifies a digest manifest. The included scripted runner validates methodology only and is labelled accordingly.

**Tech Stack:** Python 3.10+, standard library only, existing verifier/adapters/metrics, unittest, setuptools console scripts, GitHub Actions.

## Global Constraints

- No network calls or paid model calls in the reference release.
- No external-model performance claims from scripted-reference output.
- Raw traces, envelopes, cases, evaluations, run metadata, and metrics remain separate.
- Scientific JSON output is deterministic for identical configuration and runner version.
- Existing 74 tests must remain green on Python 3.10–3.13.

---

### Task 1: Configuration, scenarios, and deterministic run matrix

**Files:**
- Create: `src/completion_verifier/benchmark/models.py`
- Create: `src/completion_verifier/benchmark/scenarios.py`
- Create: `src/completion_verifier/benchmark/__init__.py`
- Test: `tests/test_benchmark.py`

**Interfaces:**
- Produces: `ExperimentConfig.from_dict`, `ExperimentConfig.to_dict`, `FailureScenario`, `RunRequest`, `build_run_matrix`, `derive_run_seed`, `default_scenarios`.

- [ ] Write failing tests for validation, all eight scenarios, deterministic seeds, run IDs, ordering, and duplicate rejection.
- [ ] Run `python -m unittest tests.test_benchmark.ConfigurationTests -v` and confirm failures are due to missing benchmark modules.
- [ ] Implement immutable models and scenario generation with canonical config digest.
- [ ] Re-run focused tests and full suite.
- [ ] Commit configuration and scenario foundation.

### Task 2: Runner protocol and scripted reference treatments

**Files:**
- Create: `src/completion_verifier/benchmark/runner.py`
- Create: `src/completion_verifier/benchmark/reference_runner.py`
- Modify: `tests/test_benchmark.py`

**Interfaces:**
- Produces: `ExperimentRunner`, `RawRunTrace`, `ScriptedReferenceRunner.run(RunRequest)`.

- [ ] Write failing tests for baseline, evidence-contract, verifier-feedback, timeout recovery, terminal failure, missing evidence, rollback, retry and refusal metadata.
- [ ] Run focused tests and confirm missing implementation failures.
- [ ] Implement minimal protocol and deterministic reference behavior.
- [ ] Re-run focused and full tests.
- [ ] Commit reference runner.

### Task 3: Harness, artifact separation, metrics, and manifest verification

**Files:**
- Create: `src/completion_verifier/benchmark/harness.py`
- Create: `src/completion_verifier/benchmark/reporting.py`
- Modify: `tests/test_benchmark.py`

**Interfaces:**
- Produces: `run_experiment(config, output_dir, runner) -> ExperimentResult`, `verify_manifest(output_dir)`, `calculate_experiment_metrics`.

- [ ] Write failing tests for artifact layout, no-overwrite, deterministic output, per-group/scenario metrics, recovery/refusal/retry counts, and digest verification.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement end-to-end harness using `GenericJsonTraceAdapter`, existing evaluator and benchmark metrics.
- [ ] Re-run focused and full tests.
- [ ] Commit harness and reporting.

### Task 4: Benchmark CLI and package integration

**Files:**
- Create: `src/completion_verifier/benchmark_cli.py`
- Modify: `src/completion_verifier/__init__.py`
- Modify: `pyproject.toml`
- Create: `examples/benchmark_config.json`
- Modify: `tests/test_benchmark.py`

**Interfaces:**
- Produces console command `completion-verifier-benchmark` with `--config`, `--output`, `--runner scripted-reference`, and `--dry-run`.

- [ ] Write failing CLI dry-run, full-run, invalid-runner and overwrite tests.
- [ ] Run focused tests and confirm missing CLI failures.
- [ ] Implement CLI, version 0.4.0, script entry point, and example config.
- [ ] Re-run focused and full tests.
- [ ] Commit CLI/package integration.

### Task 5: Documentation and release gates

**Files:**
- Create: `docs/BENCHMARK.md`
- Modify: `README.md`
- Modify: `RESULTS.md`
- Modify: `docs/RESEARCH_ROADMAP.md`
- Modify: `scripts/verify_release.py`
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- Release checks must run the benchmark from editable and clean-wheel installs and verify its manifest.

- [ ] Document method, schemas, scripted-reference limitation, reproduction and real-run requirements.
- [ ] Add benchmark execution and artifact assertions to release verification and CI.
- [ ] Run full tests, release verifier, wheel build, clean-wheel benchmark, and dependency checks.
- [ ] Repeat the full verification once in a separate clean environment.
- [ ] Publish through a PR and merge only after all Python 3.10–3.13 jobs pass.
