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
  exception and rollback benchmark scenarios;
- baseline, evidence-contract and verifier-feedback treatment labels;
- a deterministic scripted benchmark runner;
- separated raw, envelope, case, evaluation, run and metrics artifacts;
- a confined local UTF-8 file-write sandbox;
- independent file existence, size, digest and content observations;
- false receipt, partial write, timeout-after-write, rollback, traversal and
  symlink-escape scenarios;
- a privacy-minimal local postcondition SDK for exact text files, directory
  state and structured JSON objects;
- a closed verifier registry and adapter into the existing evaluator;
- fixed-code, fail-closed observations that avoid exposing caller-controlled
  paths, identifiers, file names, JSON keys/values or raw content through the
  public evidence surface;
- artifact manifest verification and cross-version package verification.

## Next experimental expansion

1. Design one separately reviewed remote-state verifier with an explicit trust,
   authorization and privacy boundary. GitHub pull-request/ref state is the
   preferred first candidate because it can verify a concrete external state
   without requiring message-body retention.
2. Connect a versioned real-agent runner to confined local postconditions while
   preserving explicit model, prompt, sampling, tool, date, cost and token
   metadata outside public disclosure artifacts.
3. Run the same source-controlled configuration across at least two independently
   implemented agent scaffolds.
4. Repeat each condition enough times for uncertainty intervals and sensitivity
   analysis.
5. Evaluate held-out actions, contracts and failure schedules.
6. Measure verifier gaming, excess refusal and unnecessary retries.
7. Strengthen path operations with file-descriptor-relative APIs and an OS-level
   sandbox before evaluating less trusted code.

## Metrics already implemented

- false-completion rate;
- completion-claim precision;
- verified completion rate;
- unsupported, partial and failed claims;
- recovery and regression counts;
- recovery rate conditioned on injected failure;
- unnecessary retry and refusal rates;
- per-group and per-scenario summaries;
- source/independent-observation agreement;
- source false positives and false negatives;
- security rejection counts;
- timing and token means when real values are supplied.

## Stronger evidence systems

Future versions could validate evidence through:

- file-descriptor-relative local observations;
- OS sandboxing and process isolation;
- signed or hashed tool receipts;
- independently authenticated reads of external system state;
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
- How much independent verification overhead is acceptable for real agent runs?
