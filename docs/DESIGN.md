# Evaluation design

## Unit of evaluation

A case contains:

- a human-readable task;
- a boolean indicating whether the agent claimed completion;
- one or more required actions;
- the evidence fields required for each action;
- an ordered event trace from the workflow.

## Latest-event rule

For each required action, the evaluator considers its latest event by sequence.
This captures both recovery and regression:

- failure followed by evidenced success is recovered;
- success followed by failure or rollback is failed.

## Evidence sufficiency

A requirement is proven only when:

1. an event exists for the exact required action;
2. the latest event reports success;
3. every required evidence field is present and non-empty.

Missing actions, wrong actions, and success events with insufficient evidence do
not prove completion.

## Status precedence

The evaluator assigns one status:

1. `VERIFIED_COMPLETE` when all requirements are proven;
2. `FAILED` when any unproven requirement has a latest failure event;
3. `PARTIAL` when at least one, but not all, requirements are proven;
4. `UNVERIFIED` otherwise.

This precedence makes an unrecovered required-action failure visible instead of
softening it into a partial result.

## Claim comparison

The completion claim does not determine the status. It is compared with the
evidence result:

- a completion claim without full proof produces a warning reason;
- fully evidenced completion without a claim is still verified.

## Trust boundary

This prototype assumes the event trace is supplied honestly. It checks evidence
presence, not evidence authenticity. Stronger systems should bind events to
trusted tool receipts, cryptographic provenance, authorization records, and
independent state verification.
