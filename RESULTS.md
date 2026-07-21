# Reproducible results

Verified locally on 21 July 2026. GitHub Actions repeats the release checks on
Python 3.10, 3.11, 3.12, and 3.13 before merge.

## Verification coverage

```text
Ran 123 tests

OK
```

Each release job:

- compiles source, tests and verification scripts;
- runs all 123 unit tests;
- executes evaluator, adapter, benchmark and sandbox release verification;
- builds a wheel and installs it in a separate clean environment;
- reruns all four installed console commands from the wheel;
- verifies benchmark and sandbox artifact manifests;
- confirms exact deterministic metrics from editable and wheel installations;
- confirms the original 16-case result distribution;
- runs dependency consistency checks.

## Original deterministic case set

```text
FAILED               3
PARTIAL              2
UNVERIFIED           4
VERIFIED_COMPLETE    7
```

The original 16-case false-completion rate remains `0.6` with claim precision
`0.4`. These intentionally mixed cases test evaluator behavior rather than model
capability.

## Scripted failure-injection benchmark

The version 0.4 reference benchmark remains 24 deterministic runs with 21
injected-failure conditions and five recovered failures.

```json
{
  "baseline_false_completion_rate": 0.875,
  "evidence_contract_false_completion_rate": 0.3333333333333333,
  "verifier_feedback_false_completion_rate": 0.16666666666666666
}
```

These values follow fixed scripted policies and are not external-model results.

## Independent sandbox postconditions

The version 0.5 reference suite runs eight deterministic file-write scenarios.
Canonical evidence is derived only from independently observed sandbox state.

```json
{
  "total_scenarios": 8,
  "status_counts": {
    "VERIFIED_COMPLETE": 2,
    "PARTIAL": 0,
    "UNVERIFIED": 0,
    "FAILED": 6
  },
  "claimed_completion": 4,
  "false_completion": 3,
  "false_completion_rate": 0.75,
  "independently_verified_completion": 2,
  "silent_verified_completion": 1,
  "source_observation_agreement": 4,
  "source_false_positive": 3,
  "source_false_negative": 1,
  "security_rejection": 2
}
```

Expected scenario outcomes:

```text
success                 VERIFIED_COMPLETE
false_success           FAILED
partial_write           FAILED
timeout_before_write    FAILED
timeout_after_write     VERIFIED_COMPLETE
rollback                FAILED
path_traversal          FAILED
symlink_escape          FAILED
```

The suite demonstrates:

- a fabricated source receipt cannot satisfy the verifier;
- a partial write and rollback are detected from actual state;
- timeout-after-write can be silently verified because the contracted file
  exists despite the source reporting failure;
- traversal and symlink escapes are rejected without creating an escaped file;
- source reports, observations, canonical cases and evaluations remain separate.

These deterministic local results validate the evidence boundary and sandbox
software. They do not measure any external AI model and do not provide
production identity, authorization, remote-state or adversarial OS guarantees.

## Reproduce

```bash
python scripts/verify_release.py
completion-verifier data/cases.jsonl --metrics
completion-verifier-adapt generic examples/generic_trace.json examples/requirements.json --source-ref local-run --envelope
completion-verifier-benchmark --config examples/benchmark_config.json --output benchmark_runs/reference-v1
completion-verifier-sandbox --config examples/sandbox_config.json --output sandbox_runs/reference-v1 --scenario all
```
