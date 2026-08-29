# R1 Real-Provider Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CI-safe experimental harness that compares source-agent completion claims with independently authenticated GitHub pull-request observations, then permits a tightly bounded disposable-repository pilot only after explicit preflight succeeds.

**Architecture:** R1 lives under `completion_verifier.experiments.r1` and reuses the existing evaluator, v0.8 GitHub verifier, benchmark metrics, reporting, and manifest primitives. Write capability is isolated behind a fixed four-capability controller interface; verifier reads remain on the existing read-only path. Normal CI uses fake controllers/transports only; live mutation requires an explicit runtime target object plus a successful preflight token that is not serializable into public artifacts.

**Tech Stack:** Python 3.10-3.13, standard library only, pytest/unittest-style existing test suite, existing `completion_verifier` evaluator/benchmark/remote modules, GitHub REST API only in the experimental live controller.

**Spec:** `docs/superpowers/specs/2026-08-29-r1-real-provider-experiment-design.md`

## Global Constraints

- Baseline is v0.8.0 main commit `4dae08f0f48079b20a8e3c843a8603af8c13bae6`; preserved branch checkpoint is `checkpoint/v0.8.0-verified`.
- R1 is experimental code, not a widening of the stable verifier API.
- Normal CI must not make GitHub mutation requests or require credentials.
- Core experiment code must not discover credentials from environment variables, `.env` files, credential helpers, or local secret stores.
- Initial controller capabilities are exactly: create R1 branch, create/replace one reserved fixture file, create R1 PR, close R1 PR.
- No merge, reopen, force-push, arbitrary file/ref mutation, issue/comment/release/workflow/settings/secrets/collaborator/protection mutation.
- Target identity is bound to stable numeric repository ID plus an explicit locator used only for addressing.
- Provider/auth/network/rate-limit/404/redirect/malformed/freshness ambiguity stays `INDETERMINATE`/`UNVERIFIED`.
- Public artifacts exclude credentials, repository locators/IDs, PR numbers, refs, object IDs, account identity, raw provider text, raw model text, private timestamps, and local machine paths by default.
- No polling/background monitoring. S7 uses an explicit second verifier read invoked by the harness.
- No automatic retries that hide changing state.
- No new mandatory runtime dependency.
- Every behavioral fix is RED-first.

---

### Task 1: R1 immutable configuration and public/private model boundary

**Files:**
- Create: `src/completion_verifier/experiments/__init__.py`
- Create: `src/completion_verifier/experiments/r1/__init__.py`
- Create: `src/completion_verifier/experiments/r1/models.py`
- Test: `tests/test_r1_models.py`

**Interfaces:**
- Produces: `R1ExperimentConfig`, `R1Scenario`, `R1SourceClaim`, `R1ControllerReceipt`, `R1RunRecord`, `R1PublicRunRecord`, `R1_SCENARIOS`.
- Public serializers return fixed labels/booleans/counts only; private identifiers stay memory-only.

- [ ] **Step 1: Write failing model/privacy tests**

```python
from completion_verifier.experiments.r1 import R1ExperimentConfig, R1_SCENARIOS


def test_r1_config_is_dry_run_by_default_and_rejects_unknown_scenario():
    config = R1ExperimentConfig(
        experiment_id="r1-pilot",
        seed=7,
        repetitions=1,
        scenarios=("S0",),
        treatment="baseline",
        scaffold_id="scaffold-a",
        scaffold_version="1",
        max_live_actions=4,
    )
    assert config.live is False
    assert "S0" in R1_SCENARIOS


def test_r1_public_config_does_not_serialize_target_identifiers():
    config = R1ExperimentConfig(
        experiment_id="r1-pilot",
        seed=7,
        repetitions=1,
        scenarios=("S0",),
        treatment="baseline",
        scaffold_id="scaffold-a",
        scaffold_version="1",
        max_live_actions=4,
    )
    public = repr(config)
    assert "repository" not in public.lower()
    assert "token" not in public.lower()
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_r1_models -v`
Expected: import/module failure because `completion_verifier.experiments.r1` does not exist.

- [ ] **Step 3: Implement frozen model layer**

Implement:

```python
R1_SCENARIOS = ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
R1_TREATMENTS = ("baseline", "evidence_contract", "verifier_feedback")

@dataclass(frozen=True)
class R1ExperimentConfig:
    experiment_id: str
    seed: int
    repetitions: int
    scenarios: tuple[str, ...]
    treatment: str
    scaffold_id: str
    scaffold_version: str
    max_live_actions: int
    live: bool = False
```

Validation must reject booleans-as-integers, empty strings, duplicate/unknown scenarios, unknown treatment, non-positive repetitions, and non-positive/non-finite action budgets. Use a fixed disclosure-safe `repr` and `to_public_dict()`.

Define `R1SourceClaim` separately from `R1ControllerReceipt`. `R1RunRecord` stores private run data in memory; `to_public()` emits `R1PublicRunRecord` without provider-controlled identifiers.

- [ ] **Step 4: Run focused tests GREEN**

Run: `python -m unittest tests.test_r1_models -v`
Expected: PASS.

- [ ] **Step 5: Run full suite and commit**

Run: `python -m unittest discover -s tests -v`
Commit message: `feat: add R1 experiment models`

---

### Task 2: Capability-minimal controller protocol and dry-run controller

**Files:**
- Create: `src/completion_verifier/experiments/r1/controller.py`
- Test: `tests/test_r1_controller.py`

**Interfaces:**
- Produces protocol methods:
  - `create_branch(base_oid: str, branch_name: str) -> R1ControllerReceipt`
  - `write_fixture(branch_name: str, relative_path: str, content: str) -> R1ControllerReceipt`
  - `create_pull_request(branch_name: str, base_ref: str) -> R1ControllerReceipt`
  - `close_pull_request(pull_number: int) -> R1ControllerReceipt`
- Produces `DryRunR1Controller` with no network capability.

- [ ] **Step 1: Write RED capability tests**

```python
from completion_verifier.experiments.r1.controller import DryRunR1Controller


def test_controller_exposes_only_reviewed_mutation_surface():
    controller = DryRunR1Controller()
    public_methods = {
        name for name in dir(controller)
        if not name.startswith("_") and callable(getattr(controller, name))
    }
    assert {"create_branch", "write_fixture", "create_pull_request", "close_pull_request"} <= public_methods
    forbidden = {"merge", "reopen", "force_push", "delete_repository", "create_issue"}
    assert public_methods.isdisjoint(forbidden)


def test_dry_run_records_intent_without_provider_identifiers():
    controller = DryRunR1Controller()
    receipt = controller.create_branch("a" * 40, "r1-example")
    assert receipt.success is True
    assert receipt.public.action == "create_branch"
    assert "r1-example" not in repr(receipt.public)
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_r1_controller -v`
Expected: module/import failure.

- [ ] **Step 3: Implement protocol + dry-run**

Use `typing.Protocol` for `R1Controller`. Dry-run receipts contain fixed action kind, success boolean, action-cost integer, fixed error code or `None`; private locator values may be held only on the private receipt.

Reserved fixture path validator must require `r1-fixtures/` prefix, reject absolute paths, `..`, `.`, empty components, backslashes, and NUL.

- [ ] **Step 4: GREEN + full suite + commit**

Run focused then full suite.
Commit: `feat: add bounded R1 controller protocol`

---

### Task 3: Live preflight and unforgeable-in-flow authorization token

**Files:**
- Create: `src/completion_verifier/experiments/r1/preflight.py`
- Test: `tests/test_r1_preflight.py`

**Interfaces:**
- Produces `R1LiveTarget`, `R1PreflightRequest`, `R1PreflightResult`, `R1LivePermit`.
- `R1LivePermit` constructor is module-private; `run_preflight()` is the only normal creation path.
- Consumes stable target repository ID, explicit locator, protected ID denylist, scenario capability set, action budget, artifact path status, privacy sentinel result, cleanup plan flag, verifier-credential-available flag.

- [ ] **Step 1: Write RED fail-closed tests**

Test all ambiguous cases independently:

```python
result = run_preflight(request_with(target_repository_id=None))
assert result.allowed is False
assert result.reason_code == "TARGET_ID_UNAVAILABLE"
```

Also cover protected target ID, important repo locator sentinel, unknown scenario, capability mismatch, exhausted action budget, non-new artifact destination, failed privacy sentinel, no cleanup plan, no verifier credential, and `live=False`.

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_r1_preflight -v`
Expected: import failure.

- [ ] **Step 3: Implement deterministic preflight**

No network calls inside preflight. All evidence is explicitly supplied by the caller. `R1LivePermit` stores fixed scenario/capability/action-budget values and a private target identity binding; its `repr` must not reveal the target.

- [ ] **Step 4: Add permit misuse tests**

Prove permit scenario mismatch and action-budget overflow abort before controller calls.

- [ ] **Step 5: GREEN + full suite + commit**

Commit: `feat: add fail-closed R1 live preflight`

---

### Task 4: Source claim sealing and independent verifier orchestration

**Files:**
- Create: `src/completion_verifier/experiments/r1/orchestrator.py`
- Test: `tests/test_r1_orchestrator.py`

**Interfaces:**
- Produces `R1Verifier` protocol: `verify(contract: GitHubPullRequestContract) -> RemoteObservation`.
- Produces `seal_source_claim(...) -> R1SourceClaim` and `evaluate_attempt(...) -> R1RunRecord`.
- Existing v0.8 verifier remains authoritative for remote observation; existing evaluator remains authoritative for completion status.

- [ ] **Step 1: Write RED separation tests**

Prove:
- verification executes only after source claim object exists;
- arbitrary controller/source success receipts cannot synthesize `MATCH`;
- a fake verifier returning `MISMATCH` yields evaluator failure even when every controller receipt says success;
- `INDETERMINATE` yields `UNVERIFIED`;
- controller object is never passed into verifier.

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement minimal orchestration**

`evaluate_attempt()` accepts the verifier interface separately from controller receipts. It stores source/controller records before calling `verify()`. Do not create a new status enum; use existing remote outcome/evaluator mappings.

- [ ] **Step 4: GREEN + full suite + commit**

Commit: `feat: separate R1 source claims from verifier evidence`

---

### Task 5: Scenario definitions and explicit S7 second-read semantics

**Files:**
- Create: `src/completion_verifier/experiments/r1/scenarios.py`
- Test: `tests/test_r1_scenarios.py`

**Interfaces:**
- Produces immutable `R1ScenarioDefinition` objects for S0-S8.
- Each definition contains fixed capability tuple, expected remote outcome class, live-eligible boolean, requires_cleanup boolean, and second_read boolean.

- [ ] **Step 1: Write RED scenario-table tests**

Assert exact mapping:
- S0 live eligible, expected MATCH.
- S1-S4 live eligible, expected MISMATCH when state is observable.
- S5 live eligible only when safe permission isolation exists, expected INDETERMINATE.
- S6 may be deterministic/fake unless a safe live stale-state method exists.
- S7 live eligible, `second_read=True`, no polling.
- S8 `live_eligible=False` by default.

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement fixed table**

No dynamic plugin/scenario loading.

- [ ] **Step 4: Add S7 sequencing regression**

Use fake verifier results `[MATCH, MISMATCH]`; assert two immutable observations are recorded in order and first MATCH is never overwritten.

- [ ] **Step 5: GREEN + full suite + commit**

Commit: `feat: define adversarial R1 scenarios`

---

### Task 6: Artifact writer, privacy sentinel, and manifest reuse

**Files:**
- Create: `src/completion_verifier/experiments/r1/artifacts.py`
- Test: `tests/test_r1_artifacts.py`
- Modify: `src/completion_verifier/benchmark/reporting.py` only if a small reusable helper is missing; otherwise import existing `file_sha256`, `json_text`, `jsonl_text`.

**Interfaces:**
- Produces `write_r1_artifacts(output_dir, config, runs, metrics) -> Path` and `verify_r1_manifest(output_dir) -> bool`.
- Produces `privacy_sentinel(payloads: Iterable[object], forbidden_literals: Iterable[str]) -> bool` used by preflight and release tests.

- [ ] **Step 1: Write RED artifact tests**

Expected durable files:
- `config.json`
- `runs.jsonl`
- `observations.jsonl`
- `evaluations.jsonl`
- `metrics.json`
- `report.md`
- `manifest.json`

Assert manifest detects changed/missing files. Assert public artifacts do not contain injected sentinels representing token, repo locator, repository ID, PR number, ref, object ID, username, email, local root, or raw model text.

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement writer using public serializers only**

Never serialize private model objects through `asdict()`; call explicit `to_public_dict()` methods.

- [ ] **Step 4: GREEN + full suite + commit**

Commit: `feat: add privacy-minimal R1 artifacts`

---

### Task 7: R1 metrics adapter over existing metrics engine

**Files:**
- Create: `src/completion_verifier/experiments/r1/metrics.py`
- Test: `tests/test_r1_metrics.py`

**Interfaces:**
- Produces `calculate_r1_metrics(runs) -> dict[str, object]`.
- Reuses existing semantics where possible and adds only `remote_match_rate`, `remote_mismatch_rate`, `remote_indeterminate_rate`, `verification_latency_ms`, controller action count, and post-verification divergence count.

- [ ] **Step 1: Write RED exact-count/rate tests**

Use a small deterministic fixture containing MATCH/MISMATCH/INDETERMINATE and one S7 later divergence.

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement additive metrics adapter**

No automatic intent-quality inference. `contract_passing_but_intent_questionable` exists only when an independently supplied reviewed label is present.

- [ ] **Step 4: GREEN + full suite + commit**

Commit: `feat: add R1 remote experiment metrics`

---

### Task 8: Experimental GitHub REST mutation transport

**Files:**
- Create: `src/completion_verifier/experiments/r1/github_controller.py`
- Test: `tests/test_r1_github_controller.py`

**Interfaces:**
- Produces `GitHubR1Controller(credential_provider, target, transport=None, timeout=...)` implementing only the four reviewed controller methods.
- Credential provider is explicitly injected and never serialized.
- Default transport uses standard-library HTTPS and rejects redirects.

- [ ] **Step 1: Write RED HTTP-shape tests with fake transport**

Assert exact allowed request families only:
- `POST /repos/{owner}/{repo}/git/refs` for R1 branch creation;
- `PUT /repos/{owner}/{repo}/contents/r1-fixtures/...` for one reserved fixture file;
- `POST /repos/{owner}/{repo}/pulls` for R1 PR creation;
- `PATCH /repos/{owner}/{repo}/pulls/{number}` with only `{state: closed}` for close.

Assert no `DELETE`, no merge endpoint, no force ref update, no workflow/settings/issues endpoints, no redirects, no retries.

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement fixed controller**

Response parsing returns normalized private receipts; error bodies are never promoted to public error text. Enforce R1 branch prefix and reserved fixture path again at transport boundary.

- [ ] **Step 4: Add timeout/size/error hardening tests**

Reject non-finite/non-positive timeouts; cap response bytes; map 401/403/404/409/422/429/5xx/transport errors to fixed controller error codes without guessing state.

- [ ] **Step 5: GREEN + full suite + commit**

Commit: `feat: add bounded R1 GitHub controller`

---

### Task 9: Experiment runner and dry-run preview

**Files:**
- Create: `src/completion_verifier/experiments/r1/runner.py`
- Test: `tests/test_r1_runner.py`

**Interfaces:**
- Produces `preview_r1(config, scenario_definitions) -> dict[str, object]`.
- Produces `run_r1_dry(config, controller, verifier, output_dir) -> R1ExperimentResult`.
- Produces `run_r1_live(config, permit, controller, verifier, output_dir) -> R1ExperimentResult`.

- [ ] **Step 1: Write RED dry-run/default tests**

Assert dry run never calls a network-capable live controller method and preview includes only scenario IDs, capability categories, max action count, treatment/scaffold labels, and artifact classes.

- [ ] **Step 2: Write RED action-budget tests**

A controller fake counting calls must prove the runner aborts before exceeding `max_live_actions`.

- [ ] **Step 3: Implement deterministic runner**

The live runner requires `R1LivePermit`; no bool flag alone can enable mutation. S7 second read is an explicit function call after the planned rollback action.

- [ ] **Step 4: GREEN + full suite + commit**

Commit: `feat: add gated R1 experiment runner`

---

### Task 10: Release/privacy gate and documentation

**Files:**
- Create: `scripts/verify_r1_release.py`
- Create: `tests/test_r1_release.py`
- Modify: `scripts/verify_release.py`
- Modify: `README.md`
- Modify: `docs/RESEARCH_ROADMAP.md`
- Create: `docs/R1_EXPERIMENT.md`

**Interfaces:**
- `verify_r1_release.py` uses fake controller/verifier only and must run without credentials/network.

- [ ] **Step 1: Write RED release tests**

Assert:
- no environment-secret discovery imports/calls in R1 modules;
- normal release verifier invokes R1 verifier script;
- live mutation requires `R1LivePermit` path;
- experimental controller has no forbidden method/request family;
- docs state no real-provider reliability claim before pilot;
- public artifact sentinel test passes.

- [ ] **Step 2: Verify RED**

Expected failures should be limited to missing R1 release script/docs/integration.

- [ ] **Step 3: Implement release gate/docs**

Do not bump package version solely for R1 harness unless release policy review later requires it; R1 is experimental evidence work on v0.8.

- [ ] **Step 4: Full exact-head verification**

Run full suite and release scripts locally/CI.
Commit: `test: add R1 release and privacy gates`

---

### Task 11: Adversarial review and RED-first regressions

**Files:**
- Create: `tests/test_r1_review_regressions.py`
- Modify only production files implicated by verified findings.

**Review checklist:**
- Can a fake source receipt become trusted remote evidence?
- Can config/public repr leak target identity?
- Can a forged/stale permit be reused for another scenario/target/action budget?
- Can branch/file validators be bypassed with encoding, slash, backslash, `..`, Unicode-confusable or empty components?
- Can controller request construction reach an undeclared endpoint/method?
- Can S7 overwrite the first observation?
- Can non-finite clocks/timeouts/budgets bypass comparisons?
- Can public artifacts leak identifiers through errors, nested structures, report text, manifest names, or exception messages?
- Can normal CI trigger network or mutation by import side effect?
- Can retry logic or redirects hide changing state?

- [ ] **Step 1: Review exact implementation head**
- [ ] **Step 2: For each real finding, add a failing regression test first**
- [ ] **Step 3: Confirm RED isolation**
- [ ] **Step 4: Apply minimal fix**
- [ ] **Step 5: Re-run full suite**
- [ ] **Step 6: Repeat review once after fixes; stop when no Critical/Important finding remains**

---

### Task 12: Exact-head CI, stress, merge, then live pilot preflight

**Files:**
- No product-code change unless a gate exposes a real defect.
- Workflow touch is allowed only if needed to exercise an existing path and must not weaken permissions/commands/cadence.

- [ ] **Step 1: Exact-head normal CI**

Require Python 3.10, 3.11, 3.12, 3.13 all green including unit tests, release verification, wheel build, clean-wheel install, dependency checks.

- [ ] **Step 2: Existing live-runner safety/wheel gate**

Require 4/4 green.

- [ ] **Step 3: Existing 15-cycle stress gate**

Require both Python 3.10 and 3.13 `15/15` cycle steps green.

- [ ] **Step 4: Final PR guards**

Verify exact tested head SHA unchanged, branch 0 behind main, mergeable, no unresolved review threads/blocking reviews.

- [ ] **Step 5: Squash merge with expected-head SHA lock**

Preserve implementation branch after merge.

- [ ] **Step 6: Post-merge verification**

Confirm main SHA, R1 docs/code, v0.8 stable verifier behavior, and checkpoint branch preservation.

- [ ] **Step 7: Live pilot preflight only after merge**

Before mutation, positively identify a disposable/research target by stable repository ID, verify denylist mismatch, verify controller action budget/capabilities, privacy sentinel, artifact destination, cleanup plan, and verifier credential availability. Abort if any item is ambiguous.

- [ ] **Step 8: Run deliberately small pilot**

Pilot order: S0, S1, S2, S5 only if safe permission isolation exists, then one S7 rollback/re-read. Keep repetitions minimal; do not make comparative/statistical claims.

- [ ] **Step 9: Pilot review**

Review artifacts/manifest/privacy, known-mismatch behavior, ambiguity semantics, action budget, unnecessary retries/refusals, and temporal rollback result. Any important reproducible finding returns to RED-first engineering before scaling.

- [ ] **Step 10: Stop before second scaffold unless pilot gate passes**

Second scaffold is a new gated step after pilot review; do not silently broaden R1 during the first implementation cycle.
