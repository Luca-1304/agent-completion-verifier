# Reproducible results

Verified locally on 21 July 2026. GitHub Actions repeats the release checks on
Python 3.10, 3.11, 3.12, and 3.13 before merge.

## Verification coverage

```text
Ran 94 tests

OK
```

Each release job:

- compiles source, tests, and verification scripts;
- runs all 94 unit tests;
- executes evaluator, adapter and benchmark release verification;
- builds a wheel and installs it in a separate clean environment;
- reruns all three installed console commands from the wheel;
- verifies benchmark artifact digests and exact treatment metrics;
- confirms the original 16-case result distribution;
- runs dependency consistency checks.

## Original deterministic case set

```text
FAILED               3
PARTIAL              2
UNVERIFIED           4
VERIFIED_COMPLETE    7
```

The original 16-case aggregate false-completion rate remains `0.6` with claim
precision `0.4`. These intentionally mixed cases test evaluator behavior rather
than model capability.

## Scripted reference benchmark

The version 0.4 example resolves to 24 runs:

- 3 treatment groups;
- 8 scenarios;
- 1 repetition;
- 21 runs with an injected failure condition.

Headline scripted-reference results:

```json
{
  "total_runs": 24,
  "injected_failure_runs": 21,
  "recovered_failure_runs": 5,
  "recovery_rate_given_injected_failure": 0.23809523809523808,
  "unnecessary_retry_runs": 0,
  "refusal_runs": 7,
  "false_completion_rate": 0.5294117647058824
}
```

Per-group reference results:

```json
{
  "baseline": {
    "verified_complete": 1,
    "failed": 4,
    "unverified": 3,
    "recovered_failure_runs": 0,
    "false_completion_rate": 0.875
  },
  "evidence_contract": {
    "verified_complete": 2,
    "failed": 3,
    "unverified": 3,
    "recovered_failure_runs": 1,
    "false_completion_rate": 0.3333333333333333
  },
  "verifier_feedback": {
    "verified_complete": 5,
    "failed": 3,
    "unverified": 0,
    "recovered_failure_runs": 4,
    "false_completion_rate": 0.16666666666666666
  }
}
```

These numbers follow directly from fixed scripted policies. They demonstrate
that the harness detects expected methodological differences. They do **not**
demonstrate the behavior of any external model or prove that a particular
prompt intervention will generalise.

## Adapter verification

The generic and simplified OpenAI-style adapters remain covered by provenance,
ordering, retry, rollback, malformed-input and clean-wheel tests. Source
references and canonical SHA-256 digests remain outside task evidence.

## Reproduce

```bash
python scripts/verify_release.py
completion-verifier data/cases.jsonl --metrics
completion-verifier-adapt generic examples/generic_trace.json examples/requirements.json --source-ref local-run --envelope
completion-verifier-benchmark --config examples/benchmark_config.json --output benchmark_runs/reference-v1
```
