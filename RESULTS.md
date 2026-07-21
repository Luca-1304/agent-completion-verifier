# Reproducible results

Verified locally on 21 July 2026. GitHub Actions repeats the release checks on
Python 3.10, 3.11, 3.12, and 3.13 before merge.

## Verification coverage

```text
Ran 74 tests

OK
```

Each release job:

- compiles source, tests, and verification scripts;
- runs all 74 unit tests;
- executes the release verifier;
- checks detailed and aggregate evaluator output;
- checks generic and simplified OpenAI-style trace conversion;
- builds a wheel;
- installs the wheel in a separate clean environment;
- reruns both evaluator and adapter console commands from that wheel;
- confirms the 16-case result distribution and provenance invariants;
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

## Adapter verification

The generic example contains a timeout followed by a successful retry. The
adapter preserves both events in source order and the evaluator returns
`VERIFIED_COMPLETE` from the latest evidenced event.

The simplified OpenAI-style example pairs one `tool_call` with one
`tool_result`. The tool-call arguments do not enter the event evidence; only the
result's source-reported evidence is converted.

The release gate also confirms:

- the canonical JSON source digest is 64 hexadecimal characters;
- source references survive envelope conversion;
- provenance never appears inside task evidence;
- canonical case output contains no source envelope fields;
- editable and clean-wheel installations produce equivalent results.

These are deterministic evaluator and transformation results. They are not live
external-model benchmark results and should not be interpreted as a model
capability score or independent proof of external state.

## Reproduce

```bash
python scripts/verify_release.py
completion-verifier data/cases.jsonl --metrics
completion-verifier-adapt generic examples/generic_trace.json examples/requirements.json --source-ref local-run --envelope
completion-verifier-adapt openai examples/openai_tool_trace.json examples/requirements.json --source-ref local-response
```
