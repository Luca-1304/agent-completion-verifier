# Research roadmap

## Research question

How often do tool-using agents claim completion without sufficient evidence,
and which interventions reduce that rate without making agents unnecessarily
rigid or ineffective?

## Implemented foundation

The current release provides:

- evidence-grounded case evaluation;
- recovery and regression handling;
- aggregate false-completion and claim-precision metrics;
- machine-readable detailed and aggregate output;
- strict generic JSON and simplified OpenAI-style trace adapters;
- provenance-linked trace envelopes with canonical JSON digests;
- controlled timeout, permission, partial-write, stale-read, malformed-success,
  exception and rollback scenarios;
- baseline, evidence-contract and verifier-feedback treatment labels;
- a deterministic scripted reference runner;
- separated raw, envelope, case, evaluation, run and metrics artifacts;
- artifact manifest verification and cross-version package verification.

## Next experimental expansion

1. Implement a real runner adapter with explicit model, prompt, sampling, tool,
   date, cost and token metadata.
2. Run the same source-controlled configuration across at least two independently
   implemented agent scaffolds.
3. Add independent postcondition checks for a safe local sandbox rather than
   relying only on source-reported tool evidence.
4. Repeat each condition enough times for uncertainty intervals and sensitivity
   analysis.
5. Evaluate held-out actions, evidence contracts and failure schedules.
6. Measure whether verifier feedback causes gaming, excess refusal or
   unnecessary retries.

## Metrics already implemented

- false-completion rate;
- completion-claim precision;
- verified completion rate;
- unsupported, partial and failed claims;
- recovery and regression counts;
- recovery rate conditioned on injected failure;
- unnecessary retry and refusal rates;
- per-group and per-scenario summaries;
- timing and token means when real values are supplied.

## Stronger evidence systems

Future versions could validate evidence through:

- direct postcondition checks;
- signed or hashed tool receipts;
- independent reads of external system state;
- identity and authorization verification;
- causal linkage between the agent action and observed state change;
- temporal checks for later rollback or revocation.

## Open questions

- When should evidence be collected by the agent versus an independent monitor?
- How should conflicting receipts and observed state be resolved?
- Which evidence contracts generalise across tools?
- Can verifier feedback improve recovery without teaching agents to game the
  evaluator?
- How should uncertainty be represented when external state is temporarily
  unreadable?
- Which raw trace fields are necessary for reproducibility without retaining
  sensitive content?
