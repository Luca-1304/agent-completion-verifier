# GitHub Remote-State Verifier v0.8 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one privacy-minimal, authenticated, read-only GitHub pull-request verifier that independently observes external state and feeds the existing completion evaluator.

**Architecture:** Add `completion_verifier.remote` beside the provider-free v0.7 `postconditions` package. A private immutable GitHub contract and private normalized snapshot stay outside the disclosure surface; an injected `GitHubStateReader` supplies state; a verifier emits `MATCH`, `MISMATCH`, or `INDETERMINATE`; and a small adapter maps those outcomes into the existing `evaluate_case` status engine. The built-in GitHub.com reader uses standard-library `http.client` with caller-supplied credentials, GET only, no redirect following, no retries, no polling, and no environment-secret discovery.

**Tech Stack:** Python 3.10–3.13 standard library only (`dataclasses`, `enum`, `typing`, `http.client`, `json`, `email.utils`, `datetime`, `time`), existing evaluator/models, `unittest`, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-29-github-remote-verifier-design.md`

## Global Constraints

- v0.7 local postcondition APIs, sandbox behavior, live runner, CLIs, and evaluator semantics stay unchanged.
- Existing evaluator remains the only completion-status engine.
- No GitHub mutation operation exists: no POST, PUT, PATCH, DELETE, GraphQL mutation, PR merge/create/close/comment, branch/ref write, issue write, or workflow dispatch.
- No OAuth/token acquisition or secret storage; credentials come only from an explicit caller-owned provider object.
- Remote package must not read `.env`, `os.environ`, `os.getenv`, Git credential helpers, or local secret stores.
- Built-in network path is GitHub.com HTTPS only and performs GET only with bounded timeout, no redirects, no retries, no polling, and no cached/ETag reuse.
- Public serialization never emits repository locators/IDs, PR numbers, refs, object IDs, credentials, headers, provider URLs, raw bodies, provider exception text, account identity, caller IDs, timestamps, or internal digests.
- Every target `404` is `INDETERMINATE(resource_unobservable)` in v0.8.
- `401` is `INDETERMINATE(authentication_failed)`; ambiguous permission/rate/network/provider failures remain indeterminate.
- Trusted structural contradiction is `MISMATCH`; exact trusted state is `MATCH`.
- `MATCH` -> `VERIFIED_COMPLETE`, `MISMATCH` -> `FAILED`, `INDETERMINATE` -> `UNVERIFIED` through the existing evaluator.
- Object IDs accept exactly 40 or 64 ASCII hex characters and are canonicalized lowercase.
- Target numeric repository ID is authoritative for identity; `owner/name` is private addressing data only.
- Normal CI never requires a real GitHub token or performs a real provider call.
- Real-provider experiments remain separately gated after implementation review.
- TDD is mandatory: commit test-only RED first, confirm the expected CI failure, then add minimal production code.

---

### Task 1: Remote outcome model, GitHub contract, private snapshot, and evaluator mapping

**Files:**
- Create: `src/completion_verifier/remote/__init__.py`
- Create: `src/completion_verifier/remote/models.py`
- Create: `src/completion_verifier/remote/evaluation.py`
- Create: `src/completion_verifier/remote/github/__init__.py`
- Create: `src/completion_verifier/remote/github/contracts.py`
- Test: `tests/test_remote_github_contracts.py`
- Test: `tests/test_remote_evaluation.py`

**Interfaces:**

```python
class RemoteOutcome(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    INDETERMINATE = "INDETERMINATE"

@dataclass(frozen=True, repr=False)
class RemoteObservation:
    provider: str
    kind: str
    outcome: RemoteOutcome
    trusted: bool
    reason: str
    evidence: dict[str, bool]
    trust_basis: str = "authenticated_remote_state"
    schema_version: str = "1"

    def to_dict(self) -> dict[str, object]: ...

@dataclass(frozen=True, repr=False)
class GitHubPullRequestContract:
    repository: str
    repository_id: int
    pull_number: int
    expected_head_oid: str
    expected_base_ref: str
    expected_state: str
    expected_merge_oid: str | None = None
    expected_head_repository_id: int | None = None
    schema_version: str = "1"

@dataclass(frozen=True, repr=False)
class GitHubPullRequestSnapshot:
    repository_id: int
    pull_number: int
    state: str
    merged: bool
    head_oid: str
    head_repository_id: int | None
    base_ref: str
    merge_oid: str | None
    request_started_at: float
    request_finished_at: float
    provider_date: float | None

remote_postcondition_case(observation: RemoteObservation, *, completion_claimed: bool = True) -> Case
evaluate_remote_observation(observation: RemoteObservation, *, completion_claimed: bool = True) -> Evaluation
```

- [ ] **Step 1: Write contract/privacy/evaluator tests first.** Cover positive IDs, `owner/name` syntax, bounded ref strings, control-character rejection, 40/64 object-ID validation/canonicalization, expected-state enum, merge OID only for `merged`, fixed repr for contract/snapshot, observation allow-lists, and evaluator mapping.

```python
def test_indeterminate_remote_observation_maps_to_unverified(self) -> None:
    observation = RemoteObservation(
        provider="github",
        kind="pull_request",
        outcome=RemoteOutcome.INDETERMINATE,
        trusted=False,
        reason="provider_unavailable",
        evidence={"fresh": False},
    )
    self.assertEqual(
        evaluate_remote_observation(observation).status,
        Status.UNVERIFIED,
    )
```

- [ ] **Step 2: Commit test-only RED.** Run CI on the branch/PR. Expected failure: imports under `completion_verifier.remote` do not exist. Confirm no unrelated failure before production code.
- [ ] **Step 3: Implement minimal models/contracts/evaluator adapter.** Keep all public observation strings from fixed allow-lists. For `INDETERMINATE`, build a `Case` with the static requirement and **no event**, so the unchanged evaluator returns `UNVERIFIED`. For `MATCH`/`MISMATCH`, use one static `verify_remote:github:pull_request` event with only fixed labels/booleans.
- [ ] **Step 4: Re-run CI.** Task-specific tests and full existing suite must pass.
- [ ] **Step 5: Commit GREEN:** `feat: add remote verification contracts and outcomes`.

---

### Task 2: Injected GitHub state reader protocol and pure comparison verifier

**Files:**
- Create: `src/completion_verifier/remote/github/verifier.py`
- Modify: `src/completion_verifier/remote/github/__init__.py`
- Test: `tests/test_remote_github_verifier.py`

**Interfaces:**

```python
class GitHubStateReader(Protocol):
    def read_pull_request(self, contract: GitHubPullRequestContract) -> GitHubReadResult: ...

@dataclass(frozen=True, repr=False)
class GitHubReadResult:
    snapshot: GitHubPullRequestSnapshot | None
    reason: str | None = None

verify_github_pull_request(
    contract: GitHubPullRequestContract,
    reader: GitHubStateReader,
    *,
    now: Callable[[], float] = time.time,
) -> RemoteObservation

evaluate_github_pull_request(
    contract: GitHubPullRequestContract,
    reader: GitHubStateReader,
    *,
    completion_claimed: bool = True,
    now: Callable[[], float] = time.time,
) -> Evaluation
```

`GitHubReadResult(snapshot=None, reason=<fixed indeterminate code>)` is the only reader failure surface. Raw exceptions never cross the reader boundary.

- [ ] **Step 1: Add RED tests with a small fake reader.** Cover exact match, target repository ID mismatch, head OID mismatch, optional head-repository mismatch, base mismatch, open/closed/merged distinctions, wrong merge OID, and an indeterminate reader result.
- [ ] **Step 2: Add freshness RED tests.** Provider timestamp far outside bounded skew yields `INDETERMINATE(observation_not_fresh)`; normal missing provider `Date` does not by itself fail if local request start/end are coherent and recent. Inject `now` for deterministic testing.
- [ ] **Step 3: Commit RED and confirm CI fails because verifier functions are missing.**
- [ ] **Step 4: Implement pure comparison verifier.** Check repository identity first, then state/head/head-repository/base/merge. Produce fixed evidence booleans such as `repository_identity_matches`, `head_matches`, `head_repository_matches`, `base_matches`, `state_matches`, `merge_matches`, `fresh`. Do not serialize expected/observed values.
- [ ] **Step 5: Run task tests + full suite; commit GREEN:** `feat: verify GitHub pull request snapshots`.

---

### Task 3: Read-only standard-library GitHub.com REST reader

**Files:**
- Create: `src/completion_verifier/remote/github/reader.py`
- Modify: `src/completion_verifier/remote/github/__init__.py`
- Test: `tests/test_remote_github_reader.py`

**Interfaces:**

```python
class GitHubCredentialProvider(Protocol):
    def authorization_header(self) -> str: ...

class GitHubRESTReader:
    def __init__(
        self,
        credential_provider: GitHubCredentialProvider,
        *,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_048_576,
        connection_factory: Callable[..., object] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None: ...

    def read_pull_request(
        self,
        contract: GitHubPullRequestContract,
    ) -> GitHubReadResult: ...
```

The injectable `connection_factory` is test-only dependency injection for deterministic fake `HTTPSConnection` behavior; normal CI performs no real network.

- [ ] **Step 1: Write RED tests for request construction.** Assert host is exactly `api.github.com`; method exactly `GET`; path uses the private contract locator and PR number; headers include fixed `Accept`, `X-GitHub-Api-Version`, `User-Agent`, caller Authorization; no body; one request only.
- [ ] **Step 2: Write RED tests for credential safety.** Empty/invalid header -> `authentication_failed`; provider called only inside reader; provider repr/token sentinel absent from returned result repr/public observation; no environment lookup tokens appear in remote source.
- [ ] **Step 3: Write RED classification tests.** `401`, every `404`, permission `403`, rate-limited `403`/`429`, any `3xx`, `5xx`, timeout/DNS/TLS/OSError, malformed JSON, wrong schema/types, truncated/oversized body.
- [ ] **Step 4: Write RED success-normalization tests.** Normalize only `id`, PR `number`, `state`, `merged`, `head.sha`, `head.repo.id`, `base.ref`, `merge_commit_sha`, and response `Date`. Reject booleans masquerading as integer IDs and malformed object IDs.
- [ ] **Step 5: Commit test-only RED and confirm expected failures.**
- [ ] **Step 6: Implement `http.client.HTTPSConnection` transport.** Read at most `max_response_bytes + 1`; reject overflow. Do not follow redirects. Do not retry. Do not persist body. Do not expose provider exceptions. Use fixed reason codes only.
- [ ] **Step 7: Run reader tests and full suite; commit GREEN:** `feat: add authenticated read-only GitHub reader`.

---

### Task 4: Public API, v0.8 identity, docs, and release privacy gate

**Files:**
- Modify: `src/completion_verifier/__init__.py`
- Modify: `src/completion_verifier/remote/__init__.py`
- Modify: `src/completion_verifier/remote/github/__init__.py`
- Modify: `pyproject.toml`
- Create: `docs/REMOTE_GITHUB.md`
- Modify: `README.md`
- Modify: `docs/RESEARCH_ROADMAP.md`
- Create: `scripts/verify_remote_release.py`
- Modify: `scripts/verify_release.py`
- Test: `tests/test_remote_release.py`

**Release identity:** `0.8.0` in both `pyproject.toml` and `completion_verifier.__version__`.

**Root public imports:** contracts/outcomes/evaluation helpers may be exported from `completion_verifier`; credential/transport classes remain clearly provider-specific under `completion_verifier.remote.github`.

- [ ] **Step 1: Add RED release/privacy tests.** Assert version `0.8.0`; docs state authenticated external-state proof boundary; a representative fake-reader match/mismatch/indeterminate public payload excludes synthetic repo locator, IDs, PR number, refs, OIDs, token sentinel, provider body/error sentinel, timestamps, and credential-provider repr.
- [ ] **Step 2: Add static capability tests.** Remote source must not contain `os.environ`, `os.getenv`, `.env`, mutation method literals (`POST`, `PUT`, `PATCH`, `DELETE`) as request methods, retry loops/backoff/polling, or third-party HTTP client imports. `pyproject.toml` base dependencies stay empty.
- [ ] **Step 3: Commit RED and confirm expected version/docs/release failures.**
- [ ] **Step 4: Update public API/version/docs and implement `verify_remote_release.py`.** The release script uses only fake readers/transports and proves match/mismatch/indeterminate mapping plus privacy. Add it to `scripts/verify_release.py`.
- [ ] **Step 5: Keep README claims exact.** Say v0.8 can independently verify one authenticated GitHub PR state at observation time; explicitly state it does not prove causality, user authorization, permanence, provider integrity, or production safety.
- [ ] **Step 6: Run full CI source/wheel matrix; commit GREEN:** `release: prepare authenticated GitHub verifier v0.8.0`.

---

### Task 5: Stress gate trigger and exact-head verification

**Files:**
- Modify only the existing comment in `.github/workflows/fifteen-pass-verification.yml` if necessary to trigger the already-existing PR-path stress workflow. Do not alter commands, permissions, matrices, cadence, checkout auth, or environment behavior.

- [ ] **Step 1: Confirm ordinary PR CI on exact implementation head is green for Python 3.10, 3.11, 3.12, and 3.13.** Each job must run unit tests, `scripts/verify_release.py`, build the wheel, install in a clean environment, and `pip check`.
- [ ] **Step 2: Confirm live-runner safety/wheel workflow remains green.** If its path filter does not naturally run because v0.8 does not touch live files/`pyproject.toml`, the version bump in `pyproject.toml` should trigger it; do not weaken the workflow.
- [ ] **Step 3: Trigger existing 15-pass workflow without changing its commands.** Confirm both Python 3.10 and 3.13 jobs complete the `Run fifteen consecutive complete cycles` step successfully.
- [ ] **Step 4: Compare implementation branch to `main`.** Must be 0 behind immediately before merge; no unplanned mutations/dependencies/secrets.

---

### Task 6: Independent review after green, adversarial fixes, and re-verification

**Files:** determined only by review findings; no speculative refactor.

- [ ] **Step 1: Review the complete PR diff after all gates are green.** Evaluate correctness, trust boundary, privacy, auth handling, HTTP semantics, timestamp/freshness logic, evaluator mapping, and package compatibility.
- [ ] **Step 2: Run explicit adversarial checklist:**
  - public repo + invalid token cannot become trusted;
  - private/inaccessible repo `404` cannot become decisive failure;
  - renamed locator redirect cannot be followed;
  - same PR number in wrong repository cannot pass numeric identity check;
  - open PR exposing `merge_commit_sha` cannot satisfy merged state;
  - malformed `head.repo`/deleted fork cannot crash or leak;
  - `True` cannot pass as repository/PR numeric ID;
  - uppercase valid OIDs canonicalize; invalid-length/non-hex reject;
  - provider `Date` parsing cannot throw raw text into evidence;
  - connection exception text/token/header/body cannot enter public serialization;
  - no second request/retry hidden after rate/network failures;
  - indeterminate state produces an event-free case and `UNVERIFIED`.
- [ ] **Step 3: If a review finding exists, add a failing regression test first, confirm RED, then make the smallest fix and re-run all exact-head gates.**
- [ ] **Step 4: Re-review the final diff.** No unresolved review threads, no privacy regressions, no new untested behavior.
- [ ] **Step 5: Only then mark implementation PR ready and squash-merge using the exact verified head SHA. Preserve implementation and design branches.

---

## Exact-head merge gate

Implementation merges only when all are true:

1. approved design/spec and this plan are already on `main`;
2. implementation occurs on a separate `feat/v0.8-*` branch, never directly on `main`;
3. every production slice has a verified RED-before-GREEN history;
4. full test/source/wheel CI is green on the exact final head for Python 3.10–3.13;
5. live-runner safety/wheel gate is green on the exact final head when triggered;
6. existing 15-pass gate succeeds on Python 3.10 and 3.13;
7. implementation branch is 0 behind `main` immediately before merge;
8. final review finds no unresolved correctness/privacy/auth/trust issue;
9. public evidence/repr/errors contain no caller-controlled remote identifiers, credentials, raw provider content, timestamps, or internal digests;
10. no GitHub mutation, secret acquisition/storage, retries, polling, monitoring, or dynamic plugin capability was introduced;
11. no real provider token/call is required to claim v0.8 implementation complete;
12. squash merge uses the exact tested expected head SHA, and both design and implementation branches are preserved.
