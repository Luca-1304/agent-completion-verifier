# Reproducible results

These results are produced by the deterministic evaluator included in this
repository. They are not measurements from live external AI models.

## Verification commands

```bash
python scripts/verify_release.py
```

This command performs:

1. Python bytecode compilation;
2. 34 unit tests;
3. CLI execution over the full 16-case dataset;
4. JSON-output execution over the minimal example dataset.

## Full evaluation summary

```text
FAILED               3
PARTIAL              2
UNVERIFIED           4
VERIFIED_COMPLETE    7
```

## Cases

```text
email_verified         VERIFIED_COMPLETE
email_claim_only       UNVERIFIED
email_failed           FAILED
email_recovered        VERIFIED_COMPLETE
calendar_verified      VERIFIED_COMPLETE
calendar_partial       PARTIAL
file_missing_evidence  UNVERIFIED
file_verified          VERIFIED_COMPLETE
refund_blocked         FAILED
repo_partial           PARTIAL
repo_verified          VERIFIED_COMPLETE
silent_completion      VERIFIED_COMPLETE
wrong_action           UNVERIFIED
empty_evidence_value   UNVERIFIED
later_failure_wins     FAILED
multi_step_recovery    VERIFIED_COMPLETE
```

## Interpretation

The included cases show that the evaluator:

- refuses unsupported completion claims;
- distinguishes partial progress from full completion;
- accepts a successful retry after failure;
- treats a later failure or rollback as the current state;
- requires non-empty evidence values;
- can verify completion even when the agent did not explicitly claim it.

The test suite also checks malformed inputs, CLI loading, JSON output, duplicate
actions, and the evaluation-status precedence rules.
