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
- an authenticated GitHub pull-request remote-state verifier with a caller-owned
  credential boundary, GET-only standard-library transport, stable repository
  identity checks, explicit freshness rules and `MATCH`/`MISMATCH`/`INDETERMINATE`
  outcomes mapped through the existing evaluator;
- remote privacy gates that exclude credentials, repository/PR/ref/object-ID
  values, provider bodies and provider error text from default public evidence;
- artifact manifest verification and cross-version package verification.

## Next experimental expansion

1. Run a separately gated real-provider experiment in a disposable/research
   GitHub repository using the v0.8 verifier. Keep source-agent claims/traces
   separate from the independent provider observation and avoid production or
   sensitive repositories.
2. Inject false-success, wrong-head, wrong-base, wrong-state, permission-failure
   and rollback conditions, then measure claim/observation disagreement,
   recovery, unnecessary retry/refusal and verification overhead.
3. Repeat the same source-controlled setup across at least two independently
   implemented agent scaffolds before making comparative reliability claims.
4. Repeat each condition enough times for uncertainty intervals and sensitivity
   analysis.
5. Evaluate held-out actions, contracts and failure schedules.
6. Measure verifier gaming, excess refusal and unnecessary retries, including
   temporary contract satisfaction followed by rollback.
7. Strengthen local path operations with file-descriptor-relative APIs and an
   OS-level sandbox before evaluating less trusted code.
8. Only after the first remote experiment is understood, consider a second
   provider or temporal re-verification/revocation checks as a separately
   designed version.

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
- additional independently authenticated external-state readers;
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
- How often does a verifier-passing remote state later roll back or diverge from
  the user's actual intent?
