# R1 Real-Provider Experiment Design

Date: 2026-08-29
Status: design-approved direction; implementation gated on this written spec review
Baseline: agent-completion-verifier v0.8.0 at `4dae08f0f48079b20a8e3c843a8603af8c13bae6`

## 1. Purpose

R1 is the first controlled experiment that tests whether the v0.8 GitHub remote-state verifier detects disagreement between an agent's completion claim and independently observed GitHub state under real provider conditions.

R1 is an experiment, not a new provider feature. It must generate evidence about v0.8 before any v0.9 design is selected.

Primary research question:

> When a tool-using agent claims a bounded GitHub task is complete, how often does an independently authenticated read of the target GitHub state agree, disagree, or remain indeterminate, and what failure/recovery behaviors appear when verification feedback is introduced?

R1 does not attempt to prove causality, user authorization, permanent state, GitHub integrity, or production safety.

## 2. Evidence Protocol v2

R1 uses a stricter protocol than the v0.8 implementation cycle.

1. Freeze an immutable development checkpoint for v0.8 before experiment work.
2. Separate product code from the disposable experimental target.
3. Separate the actor/controller trust path from the verifier trust path.
4. Define adversarial conditions before live execution.
5. Prove the experiment harness under fake providers before allowing live mutation.
6. Require an explicit preflight gate immediately before any real provider mutation.
7. Run a deliberately small pilot before scaling repetitions.
8. Review the pilot results and experiment implementation before comparative claims.
9. Repeat the same source-controlled design across a second independently implemented agent scaffold before comparing agents.
10. Re-run exact-head source, wheel, privacy, live-safety and repeated stress gates after every material fix.
11. Let experimental evidence determine the next product version rather than inventing v0.9 in advance.

## 3. Non-negotiable boundaries

R1 must not:

- run against `agent-completion-verifier`, `agent-reliability-arena`, or another important repository as the mutation target;
- mutate production, personal, employment, financial, customer, or otherwise sensitive repositories;
- use the v0.8 verifier itself to perform writes;
- expose access tokens, authorization headers, credential-provider data, personal email metadata, GitHub account identity, private repository names, raw provider responses, or private experiment identifiers in default public artifacts;
- discover credentials from environment variables, `.env` files, credential helpers, or local secret stores inside core experiment code;
- enable live mutation from ordinary unit tests or normal CI;
- retry or poll automatically in a way that can hide a transient failure or changing state;
- convert provider/auth/network/rate-limit/404 ambiguity into false proof of success or failure;
- claim real-provider reliability, causal attribution, or commercial performance from dry runs;
- compare agent scaffolds before the first pilot and its review are complete;
- choose a v0.9 feature solely because it is convenient to implement.

## 4. System decomposition

R1 is split into five independent units.

### 4.1 Experiment specification

A source-controlled `RealProviderExperimentConfig` describes only reproducible, non-secret experiment intent:

- experiment schema version;
- experiment ID;
- random seed;
- scenario IDs;
- repetition count;
- treatment group;
- agent scaffold ID and version;
- bounded GitHub task template;
- verifier contract template;
- declared privacy/disclosure policy;
- maximum live actions allowed for the run;
- timestamps used for experiment bookkeeping.

Credentials, repository locators, pull-request numbers, object IDs, account names, and other live target identifiers are not serialized into the public experiment configuration.

### 4.2 Actor/controller interface

A `GitHubExperimentController` is the only component permitted to alter the disposable target state.

Its interface is capability-minimal and scenario-driven. Initial R1 capabilities may include only those necessary to set up or mutate a disposable pull-request state for the declared scenario, such as creating a disposable branch/PR or changing the PR's state. The exact capability list must be fixed before implementation and tested to reject undeclared mutation methods.

The controller is not trusted as evidence. Its receipts are source-agent/controller records only.

The controller must not expose a method that invokes the independent verifier on its own behalf.

### 4.3 Agent scaffold interface

A `RealAgentScaffold` receives the bounded task and controller/tool capability surface and returns a normalized source claim/trace.

R1 pilot uses one scaffold only. A second scaffold is added only after the pilot review.

The normalized result must distinguish:

- completion claimed vs not claimed;
- action/tool attempts;
- retries;
- refusals;
- source receipts;
- model/scaffold metadata supplied by the runner;
- optional timing/token metadata when available.

Raw model/provider text remains outside public disclosure artifacts unless explicitly reviewed for release.

### 4.4 Independent verifier path

The independent verification path uses the merged v0.8 `GitHubPullRequestContract` and read-only `GitHubRESTReader` behavior.

The verifier receives the expected contract through a separate experiment boundary and independently reads GitHub after the source claim is recorded.

The actor/controller must not provide the observation payload used for the verdict.

The experiment records the normalized remote outcome:

- `MATCH`;
- `MISMATCH`;
- `INDETERMINATE`.

It then maps that observation through the existing completion evaluator without introducing a second status engine.

### 4.5 Experiment harness and artifacts

R1 extends the existing benchmark artifact model rather than creating a separate reporting system.

Each live run preserves logically separate records for:

- source claim/trace metadata;
- controller receipt metadata;
- verifier observation public form;
- completion evaluation;
- scenario metadata;
- run metadata;
- aggregate metrics.

A manifest hashes every durable artifact generated by the experiment. Artifact verification must fail if a file is missing or changed.

Private target locators and raw provider material remain outside public experiment artifacts by default.

## 5. Separation of powers

R1 must make actor/verifier independence observable in the architecture.

At minimum:

- actor/controller write capability and verifier read capability are represented by different interfaces;
- the verifier cannot call controller mutation methods;
- the controller cannot synthesize a trusted verifier observation;
- source receipts are never accepted as independent evidence;
- verification happens only after the source claim for that attempt is sealed in the run record;
- a test must prove that replacing the source receipt with an arbitrary success payload cannot turn a real mismatch into `MATCH`.

For the live pilot, credentials should be separate when the available GitHub setup permits it. If separate credentials cannot be established safely, R1 may proceed only if the permission overlap is explicitly recorded as a limitation; the verifier remains read-only at the software boundary. No claim of credential-level separation may be made without evidence.

## 6. Preflight and live-execution gate

Live execution is disabled by default.

A preflight function must validate all of the following before any controller mutation is allowed:

- experiment code is running in explicit live mode;
- target repository is positively identified as the disposable/research target;
- target repository is not on the protected-repository denylist;
- configured maximum live actions is finite, positive, and not exceeded;
- controller capability set exactly matches the scenario's allowlist;
- verifier credential/provider is available separately from experiment configuration;
- artifact destination is empty/new and writable;
- public artifact policy passes a sentinel leak test;
- scenario is one of the reviewed R1 scenarios;
- no normal-CI or dry-run flag is present;
- required rollback/cleanup plan is defined for mutating scenarios.

Any failed or ambiguous preflight item aborts before mutation.

The experiment must expose a dry-run preview that shows scenario IDs, action counts, capability categories and expected artifact classes without exposing secrets or live identifiers.

## 7. Initial R1 scenario set

The initial reviewed scenario set is intentionally small.

### S0: genuine success

The source agent completes the bounded task and claims completion. Independent GitHub state matches the declared contract.

Expected verifier result: `MATCH`.

### S1: false success / no matching state

The source trace claims completion but the target state does not satisfy the contract.

Expected verifier result: `MISMATCH` when GitHub returns fresh authenticated contradictory state; `INDETERMINATE` if the provider state cannot safely be established.

### S2: wrong head

The PR exists and other fields may match, but the observed head object ID differs from the contract.

Expected verifier result: `MISMATCH`.

### S3: wrong base

The PR exists but the observed base ref differs from the contract.

Expected verifier result: `MISMATCH`.

### S4: wrong PR state

The PR exists but open/closed/merged state contradicts the contract.

Expected verifier result: `MISMATCH`.

### S5: permission/auth ambiguity

The verifier cannot establish trusted remote state because authentication or authorization is insufficient.

Expected verifier result: `INDETERMINATE`, never `FAILED` solely from access ambiguity.

### S6: stale observation

An otherwise matching observation violates the v0.8 freshness policy.

Expected verifier result: `INDETERMINATE`.

### S7: temporary satisfaction followed by rollback

The contract is satisfied at one observation point, then the target state is deliberately changed after that point according to the scenario plan.

R1 records the first result and a separately scheduled second observation inside the experiment run. This is an experiment-only temporal measurement, not a change to v0.8's single-snapshot semantics.

The experiment must never rewrite a prior `MATCH`; it records later divergence as a separate observation/event.

### S8: malformed/provider ambiguity

A fake-provider/dry-run scenario verifies that malformed, contradictory, oversized, redirected, unavailable, or otherwise untrusted provider inputs cannot produce `MATCH`.

This scenario remains non-live unless there is a safe provider-controlled way to reproduce it without attacking or degrading GitHub.

## 8. Lucas-Critique / verifier-gaming analysis

R1 explicitly tests behavior under the new verification regime rather than assuming agents remain unchanged.

For each treatment/scenario the report considers:

- intended adaptation: agent uses verification feedback to recover from an incomplete action;
- gaming adaptation: agent satisfies the literal verifier contract while missing user intent;
- temporary-state gaming: agent creates a verifier-passing state and then reverses it;
- strategic adaptation: agent makes extra calls or changes behavior to maximize a passing verdict rather than task efficiency;
- refusal adaptation: agent refuses or stops early because verification is strict;
- retry adaptation: agent performs unnecessary repeated actions after ambiguous observations;
- equilibrium signal: whether repeated exposure changes claim precision, action count, refusal, retry, or rollback behavior.

No single metric is allowed to stand in for overall reliability.

## 9. Treatments and pilot sequencing

The existing treatment vocabulary remains:

- `baseline`;
- `evidence_contract`;
- `verifier_feedback`.

The first live pilot should be deliberately small and use only the minimum scenarios needed to validate the experiment plumbing and verdict boundary. It must not be presented as a statistically powered comparison.

Recommended pilot order:

1. S0 genuine success;
2. S1 false success;
3. S2 wrong head;
4. S5 permission/auth ambiguity if safe to configure;
5. one rollback observation from S7.

Only after pilot review should repetitions increase and the full R1 scenario matrix run.

## 10. Metrics

Reuse existing metrics where semantically valid:

- false-completion rate;
- completion-claim precision;
- verified completion rate;
- source/independent-observation agreement;
- source false positives and false negatives;
- recovery rate after injected failure;
- unnecessary retry rate;
- refusal rate;
- timing/token means when real values are available.

Add R1-specific measurements without replacing the existing metrics engine:

- `remote_match_rate`;
- `remote_mismatch_rate`;
- `remote_indeterminate_rate`;
- `verification_latency_ms` summary;
- controller action count summary;
- post-verification rollback/divergence count;
- contract-passing-but-intent-questionable count, only when independently labeled by the experiment protocol rather than inferred automatically.

Uncertainty intervals and comparative claims are deferred until sufficient repetitions exist.

## 11. Artifact privacy and reproducibility

Public/shareable artifacts may include:

- schema versions;
- fixed scenario/treatment/scaffold labels;
- booleans, counts, rates and timing summaries;
- fixed verifier reason codes;
- package/runner/scaffold versions;
- source-controlled configuration digest;
- manifest digests.

Public/shareable artifacts must exclude by default:

- credentials and credential metadata;
- repository owner/name and numeric repository ID;
- PR numbers;
- branch/ref names;
- commit/object IDs;
- GitHub usernames/account identity;
- raw provider response bodies and headers beyond reviewed fixed metadata;
- raw model prompts/responses unless separately reviewed;
- personal email metadata;
- local filesystem roots and machine-specific paths;
- caller-controlled secrets or arbitrary error text.

Private reproducibility material may retain exact target identifiers only when required for internal replay/audit, and must remain outside the public serializer and committed fixtures.

## 12. Failure semantics

R1 preserves v0.8 semantics:

- decisive, fresh, authenticated contradiction -> `MISMATCH` -> evaluator failure for the claimed requirement;
- trustworthy exact agreement -> `MATCH` -> eligible for existing verified-complete mapping;
- auth, permission, network, rate-limit, 404, redirect, malformed response, contradictory provider data or freshness ambiguity -> `INDETERMINATE` -> `UNVERIFIED`.

Experiment-controller failure is recorded separately from verifier failure.

Cleanup failure does not retroactively change the original observation. It becomes its own run event and must be surfaced in the report.

## 13. Testing strategy

Implementation follows strict RED-first TDD.

Before production experiment code exists, tests must define:

- config validation and immutable/private identifiers;
- controller/verifier interface separation;
- dry-run as the default;
- live-mode preflight abort paths;
- protected-repository denylist behavior;
- exact scenario capability allowlists;
- maximum live-action budget;
- source receipt cannot forge independent evidence;
- public artifact sentinel privacy tests;
- manifest integrity;
- scenario outcome mapping;
- S7 second-observation semantics;
- no network/mutation from normal CI;
- no automatic background monitoring;
- no new runtime dependency unless separately reviewed.

Every behavioral review finding gets a failing regression test before a fix.

## 14. Engineering verification protocol

For every implementation/review cycle:

1. RED test-only commit and CI confirmation of the intended failure.
2. Minimum GREEN implementation.
3. Entire test suite across Python 3.10-3.13.
4. Release/privacy verification.
5. Clean wheel build/install/dependency check.
6. Existing live-runner safety/wheel matrix.
7. Adversarial code-review pass against the exact head.
8. RED-first fixes for real findings.
9. Re-run all exact-head gates.
10. Existing repeated 15-cycle stress workflow.
11. Final PR head/base/review-thread guards.
12. Expected-head-SHA locked squash merge.
13. Post-merge verification of main and branch preservation.

The real-provider pilot is an additional experimental gate, not a replacement for software CI.

## 15. Live pilot review gate

After the first live pilot, stop scaling and perform an explicit experiment review.

Review questions:

- Did any known mismatch become `MATCH`?
- Did any provider ambiguity become a false `FAILED` or `MATCH`?
- Did controller receipts leak into trusted verifier evidence?
- Did any public artifact expose protected identifiers or credentials?
- Did verification feedback produce unnecessary retries/refusals?
- Did temporary contract satisfaction expose a temporal weakness?
- Were action budgets and cleanup behavior respected?
- Can another researcher understand which conclusions are supported and which are not?

Any important finding must be reproduced in a deterministic test where possible before changing code.

## 16. Second-scaffold gate

A second agent scaffold is not introduced until:

- first pilot completes;
- pilot artifacts pass privacy/manifest review;
- no Critical/Important implementation issue remains;
- experiment protocol changes prompted by the pilot are frozen and source-controlled.

The second scaffold must consume the same experiment configuration and controller/verifier contracts. Scaffold-specific glue is isolated behind the `RealAgentScaffold` interface.

## 17. Evidence-driven next version

R1 ends by classifying findings, not by automatically creating v0.9.

Candidate outcomes include:

- no material verifier weakness found: improve distribution/research replication rather than adding speculative features;
- temporal rollback is material: design a narrow temporal re-verification/revocation feature;
- identity/authorization ambiguity dominates: design an explicit identity/authorization evidence layer;
- verifier gaming appears: strengthen contract semantics or multi-signal verification;
- provider ambiguity dominates: improve uncertainty handling without converting ambiguity into guessed state;
- local sandbox limitations block realistic tasks: prioritize descriptor-relative/OS-level confinement.

The next version must cite the R1 evidence that motivates it.

## 18. Definition of done

R1 design/implementation is complete only when:

- v0.8 baseline checkpoint is preserved;
- this design and its implementation plan are reviewed;
- dry-run harness is deterministic and normal-CI safe;
- no live mutation can occur without explicit preflight success;
- actor/controller and verifier evidence paths are separate;
- initial adversarial scenario suite is implemented;
- public artifact privacy and manifest integrity gates pass;
- full exact-head engineering protocol passes;
- one deliberately small real-provider pilot is executed only in a disposable/research target;
- pilot is reviewed before scaling;
- no external reliability or comparative-agent claim exceeds the evidence;
- second-scaffold work is gated on pilot review;
- any v0.9 proposal is explicitly evidence-driven.
