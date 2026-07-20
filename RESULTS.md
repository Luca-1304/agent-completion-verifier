# Reproducible results

Verified locally and through GitHub Actions on 20 July 2026.

## Verification coverage

```text
Ran 44 tests

OK
```

The release matrix runs on Python 3.10, 3.11, 3.12, and 3.13. Each job:

- compiles source, tests, and verification scripts;
- runs all unit tests;
- executes the release verifier;
- checks both CLI entry points;
- builds a wheel;
- installs the wheel in a separate clean environment;
- confirms the 16-case result distribution;
- runs dependency consistency checks.

## Example case run

```text
email_verified         VERIFIED_COMPLETE
email_claim_only       UNVERIFIED
email_failed           FAILED
email_recovered        VERIFIED_COMPLETE
calendar_verified      VERIFIED_COMPLETE
calendar_partial       PARTIAL
file_missing_path      UNVERIFIED
file_verified          VERIFIED_COMPLETE
refund_blocked         FAILED
repo_partial           PARTIAL
repo_verified          VERIFIED_COMPLETE
silent_completion      VERIFIED_COMPLETE
wrong_action           UNVERIFIED
empty_evidence_value   UNVERIFIED
later_failure_wins     FAILED
multi_step_recovery    VERIFIED_COMPLETE

Summary
  FAILED               3
  PARTIAL              2
  UNVERIFIED           4
  VERIFIED_COMPLETE    7
```

## Aggregate metrics for included cases

```json
{
  "total_cases": 16,
  "status_counts": {
    "VERIFIED_COMPLETE": 7,
    "PARTIAL": 2,
    "UNVERIFIED": 4,
    "FAILED": 3
  },
  "claim_counts": {
    "claimed_completion": 15,
    "verified_claim": 6,
    "false_completion": 9,
    "unsupported_claim": 4,
    "partial_claim": 2,
    "failed_claim": 3,
    "silent_verified_completion": 1
  },
  "trace_counts": {
    "recovered": 2,
    "regressed": 1
  },
  "rates": {
    "claim_rate": 0.9375,
    "verified_completion_rate": 0.4375,
    "false_completion_rate": 0.6,
    "completion_claim_precision": 0.4
  }
}
```

These are deterministic evaluator results from intentionally mixed test cases.
They are not live external-model benchmark results and should not be interpreted
as a model capability score.

## Reproduce

```bash
python scripts/verify_release.py
completion-verifier data/cases.jsonl --metrics
```
