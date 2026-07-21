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
- deterministic test cases and cross-version package verification.

## Next experimental expansion

1. Build a controlled failure-injection harness that retains raw traces,
   requirements, derived envelopes, cases, evaluations, and metrics separately.
2. Run equivalent tasks across multiple models and agent scaffolds.
3. Inject controlled failures: timeouts, permission errors, partial writes,
   stale state, tool exceptions, deceptive success-shaped outputs, and rollback.
4. Compare baseline instructions with evidence-contract instructions and
   evidence-contract instructions plus verifier feedback.
5. Evaluate on held-out tools and task structures.
6. Separate claim calibration from actual task success.

## Candidate experimental metrics

Already implemented for structured traces:

- false-completion rate;
- verified task-completion rate;
- unsupported-claim rate;
- partial and failed claim counts;
- recovery and regression case counts.

Still requiring controlled agent experiments:

- excess refusal or unnecessary retry rate;
- time and token overhead from evidence contracts;
- generalisation to unseen action and evidence schemas;
- verifier-gaming rate;
- recovery rate conditioned on injected failures.

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
