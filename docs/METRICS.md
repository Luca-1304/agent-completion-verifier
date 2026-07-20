# Benchmark metrics

The metrics layer summarises a set of cases and their evidence-grounded
evaluations. It does not estimate external-model performance unless the input
cases were produced by controlled external agent runs.

## Claim metrics

- **Claim rate**: cases where the agent claimed completion divided by all cases.
- **Verified claim**: the agent claimed completion and the evaluator returned
  `VERIFIED_COMPLETE`.
- **False completion**: the agent claimed completion but the evaluator returned
  `PARTIAL`, `UNVERIFIED`, or `FAILED`.
- **False-completion rate**: false completions divided by claimed completions.
- **Completion-claim precision**: verified claims divided by claimed
  completions.
- **Unsupported claim**: a claimed completion with an `UNVERIFIED` result.
- **Partial claim**: a claimed completion with a `PARTIAL` result.
- **Failed claim**: a claimed completion with a `FAILED` result.
- **Silent verified completion**: a `VERIFIED_COMPLETE` result without an agent
  completion claim.

When no completion claims exist, claim precision and false-completion rate are
reported as `0.0` rather than undefined.

## Trace metrics

- **Recovered case**: for at least one required action, an earlier failure is
  followed by a latest successful event containing sufficient evidence.
- **Regressed case**: for at least one required action, an earlier successful,
  sufficiently evidenced event is followed by a latest failure.

Recovery and regression are counted once per case, even if multiple required
actions exhibit the same pattern.

## Machine-readable output

```bash
completion-verifier data/cases.jsonl --metrics
```

The command returns status counts, claim counts, trace counts, and rates as
JSON. Case IDs must be unique so aggregate results cannot silently combine
ambiguous records.
