# R1 controlled real-provider experiment

R1 is an **experimental** harness around the v0.8 authenticated GitHub pull-request verifier. Its purpose is to test a narrow question under controlled conditions: when a source agent claims that a bounded GitHub task is complete, does an **independent verifier** observe remote state that matches the separately declared contract?

The R1 implementation is not itself evidence that the system is reliable against the real provider. Until a reviewed disposable-target pilot is actually run, there is **no real-provider reliability claim**.

## Current status

The source-controlled harness, dry controller, preflight gate, narrow GitHub writer, scenario definitions, artifact pipeline, metrics and runner are implemented on the R1 development branch and tested with fake transports/verifiers. The hardened live gate binds the source scaffold to one exact prepared action sequence and one live repetition per permit. A live pilot is still gated separately.

The package release remains v0.8.0. R1 is evidence-generating experiment infrastructure, not a v0.9 feature release.

## Trust separation

R1 keeps four records conceptually separate:

1. the bounded task supplied to the source scaffold;
2. the source claim and controller receipts;
3. the independently specified verifier contract;
4. the authenticated remote observation used by the existing evaluator.

A source claim or successful controller receipt cannot become independent evidence. The controller cannot synthesize a trusted verifier observation, and the verifier is not given controller receipts as proof.

The provider-facing writer is reviewed execution infrastructure, not an adversarial evidence source. Before mutation, the live runner requires it to affirm binding to the same preflight-approved target. The source scaffold does not receive raw provider credentials, the verifier observation, or authority to choose a different target, branch, fixture path/content, base ref, pull request, action order, or action cardinality.

## Mutation boundary

Live mutation is disabled by default. The reviewed controller can only:

- create a branch under the reserved `r1-` prefix;
- create or replace one file under the reserved `r1-fixtures/` path;
- create a draft pull request into the reviewed base ref;
- close that pull request.

It has no merge, reopen, delete, force-push, arbitrary-ref, arbitrary-file, issue, comment, release, workflow, settings, secrets, collaborator or protection-rule operation. It performs one declared provider request per action and has **no polling**, no automatic retry and no redirect following.

The live action gate enforces the exact prepared arguments, exact action order and single-use cardinality. A scaffold cannot substitute another branch/path/content/base ref, create a second pull request, or close a pull request other than the one created by that attempt.

## Live preflight

A real provider mutation requires a successful fail-closed **preflight** and an in-process permit bound to:

- explicit live mode;
- a separately approved stable numeric repository ID;
- a repository locator separately verified against that ID;
- a protected-repository denylist;
- the exact scenario and fixed capability tuple;
- a finite action budget;
- a new/writable artifact destination;
- a passing public-artifact privacy sentinel;
- a defined cleanup plan;
- verifier credential availability outside experiment configuration;
- a non-CI, non-dry execution context.

The initial live-pilot permit authorizes exactly one repetition. The live runner also checks that the writer is bound to the same disposable target before any mutation. It reserves a cleanup action before pull-request creation so an agent cannot consume the final action while leaving a research PR open.

The intended target is a **disposable** or dedicated research repository. R1 must not use this repository, another important project, personal/employment/financial/customer repositories, or any production target for mutations.

## Scenarios

The initial closed scenario set is S0–S8:

- S0 genuine matching state;
- S1 false-success mismatch;
- S2 wrong head object ID;
- S3 wrong base ref;
- S4 wrong pull-request state;
- S5 authentication/permission ambiguity;
- S6 stale observation, fake/dry only;
- S7 temporary satisfaction followed by one explicit close and one explicit second read;
- S8 malformed/provider ambiguity, fake/dry only unless a separately safe reproduction is designed.

S7 preserves both observations. A later mismatch does not rewrite the earlier match.

## Failure semantics

The v0.8 semantics remain authoritative:

- fresh authenticated exact agreement -> `MATCH` -> eligible for `VERIFIED_COMPLETE`;
- fresh authenticated contradiction -> `MISMATCH` -> evaluator failure for the claimed requirement;
- authentication, authorization, rate-limit, network, 404, redirect, malformed-provider or freshness ambiguity -> `INDETERMINATE` -> `UNVERIFIED`.

Controller failures are recorded separately from verifier outcomes. Cleanup failure does not retroactively alter the earlier remote observation. On a normal completed experiment path, failed `close_pull_request` receipts are counted as `cleanup_failure_count` and surfaced in the public report. If an unexpected scaffold/verifier exception aborts the experiment before an artifact set exists, R1 makes one best-effort reserved cleanup attempt without retrying or masking the original exception; that aborted path is not presented as a completed experiment result.

## Privacy and artifacts

Public artifacts use fixed filenames and privacy-minimal serializers. They may contain fixed scenario/treatment/scaffold labels, booleans, counts, rates, latency summaries, fixed reason codes and public configuration/manifest digests.

By default they exclude credentials, repository owner/name and numeric ID, pull-request numbers, branch/ref names, commit/object IDs, account identity, raw provider bodies/headers, raw model text, personal email metadata, machine-specific filesystem paths and arbitrary provider error text.

Before durable public artifacts are written, R1 combines caller-supplied secret sentinels with distinctive private strings that the harness already holds in memory, including the experiment ID, target locator, prepared branch/path/content, relevant object IDs and private trace/receipt strings. Short generic values and numeric identifiers are protected by fixed public serializers rather than substring scanning to avoid meaningless collisions. The manifest then detects changed, missing and untracked files.

## What a result proves — and does not prove

A verifier `MATCH` proves only that the reviewed contract matched the authenticated GitHub observation at that observation point under the verifier's stated assumptions. It does not prove **causality**, user **authorization**, intent, **permanence**, provider integrity, or production safety.

A `MISMATCH` proves a trusted contradiction at observation time; it does not prove which actor caused the state. An `INDETERMINATE` means the experiment could not safely establish the state and must not be promoted to success or failure.

## Pilot gate

The first live pilot must use a separately reviewed disposable target and deliberately small sequence: S0, S1, S2, S5 only if permission separation can be configured safely, then S7. The pilot is plumbing/evidence validation, not a statistically powered comparison.

Only after pilot review should repetitions increase or a second independently implemented agent scaffold be introduced. Comparative or reliability claims require actual observed data, sufficient repetitions and an explicit uncertainty analysis.
