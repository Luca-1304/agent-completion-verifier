# Research roadmap

## Research question

How often do tool-using agents claim completion without sufficient evidence,
and which interventions reduce that rate without making agents unnecessarily
rigid or ineffective?

## Proposed experimental expansion

1. Run equivalent tasks across multiple models and agent scaffolds.
2. Inject controlled failures: timeouts, permission errors, partial writes,
   stale state, tool exceptions, and deceptive success-shaped outputs.
3. Compare baseline agents with evidence-contract prompts and verifier feedback.
4. Evaluate on held-out tools and task structures.
5. Separate claim calibration from actual task success.

## Candidate metrics

- false-completion rate;
- verified task-completion rate;
- recovery rate after tool failure;
- unsupported-claim rate;
- partial-workflow detection rate;
- excess refusal or unnecessary retry rate;
- generalisation to unseen action and evidence schemas.

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
