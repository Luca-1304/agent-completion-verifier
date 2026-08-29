# v0.8 GitHub remote-state verifier design

Date: 29 August 2026
Status: proposed for review
Scope: first authenticated remote-state verifier only
Tracking issue: #19

## Goal

Extend Agent Completion Verifier beyond local postconditions with one independently authenticated, read-only verifier for GitHub pull-request state.

The verifier answers one narrow question:

> Did GitHub independently report that the expected pull-request state existed at observation time?

It does not execute the action being judged, mutate GitHub, infer user intent, prove authorization, prove causal attribution, or guarantee persistence after observation.

## Why GitHub first

GitHub pull-request state is concrete, machine-readable and externally observable without retaining message bodies or other high-sensitivity personal content.

The first remote contract is deliberately one pull-request verifier. Ref, deployment, issue, email, calendar, database and payment verifiers remain out of scope until this boundary is proven.

## Architecture

Use an injected read-only provider reader rather than putting authentication and HTTP logic inside the verification engine.

The architecture has five layers:

1. **Private contract** — immutable expected GitHub state.
2. **Credential boundary** — caller-owned credential provider; no environment-secret discovery in the SDK.
3. **Read-only GitHub reader** — authenticated GET-only transport that normalizes only fields needed for verification.
4. **Remote verifier** — compares the private snapshot with the private contract and emits privacy-minimal evidence.
5. **Existing evaluator adapter** — maps `MATCH`, `MISMATCH`, and `INDETERMINATE` into the existing evaluator instead of creating a second status engine.

This keeps v0.7 local verification unchanged and keeps credentials, provider URLs and raw API payloads outside the core completion model.

## Package boundary

Add a separate package beside `completion_verifier.postconditions`:

```text
completion_verifier/
  remote/
    __init__.py
    models.py
    evaluation.py
    github/
      __init__.py
      contracts.py
      reader.py
      verifier.py
```

`completion_verifier.postconditions` remains provider-free and unchanged.

## Initial contract

`GitHubPullRequestContract` is immutable and privacy-sensitive. It contains:

- private repository locator (`owner/name`) used only to address GitHub;
- required stable numeric target repository ID;
- positive pull-request number;
- expected head commit object ID;
- expected base ref;
- expected state: `open`, `closed`, or `merged`;
- optional expected merge object ID, valid only for `merged`;
- optional expected head-repository ID for cross-repository pull requests.

The numeric target repository ID is authoritative for identity. The human-readable repository locator is an addressing input and never substitutes for the identity check.

Object IDs accept exactly 40- or 64-character ASCII hexadecimal values and are canonicalized to lowercase internally. Refs are bounded non-empty strings and reject control characters. Repository IDs and pull numbers are positive integers.

`repr(contract)` is fixed/static and never contains repository names, IDs, PR numbers, refs or object IDs.

## Expected-state semantics

A trusted provider snapshot is compared exactly:

- `open` requires provider state `open` and `merged == false`;
- `closed` requires provider state `closed` and `merged == false`;
- `merged` requires `merged == true`;
- target repository ID must match;
- head object ID must match;
- base ref must match;
- optional head-repository ID must match when declared;
- optional merge object ID must match GitHub's post-merge `merge_commit_sha` when declared.

The verifier never uses GitHub's `mergeable` field as proof of completion. GitHub documents that `merge_commit_sha` has different semantics before and after merge, so merge-object verification is accepted only after the provider reports the PR as merged.

## Provider reader

### Interface

`GitHubStateReader` is an injected protocol. The verifier depends on that protocol, not on HTTP.

The built-in `GitHubRESTReader` supplies the first real provider path and returns a strict private `GitHubPullRequestSnapshot`. Raw JSON is never handed to the verifier.

### Credential boundary

The caller supplies one explicit credential-provider protocol with an `authorization_header()` operation. Token acquisition and storage are outside this project.

The SDK does not:

- read `.env` files;
- read `os.environ` or `os.getenv`;
- inspect Git credential helpers or local credential stores;
- persist credentials;
- accept literal secrets in contracts;
- include credential-provider repr, headers or token material in observations/errors/fixtures.

The returned Authorization value exists only inside the reader long enough to perform the request.

### Authentication semantics

v0.8 requires authenticated verification. Anonymous reads cannot produce the authenticated trust basis.

The reader always sends the supplied Authorization header with the target request. GitHub currently documents that invalid credentials initially return `401`; therefore a target response accepted under the supplied Authorization header can be treated as authenticated only when it is not an authentication failure and the response is otherwise structurally valid.

No separate `/user` identity lookup is required in v0.8. This avoids coupling the verifier to one token family and avoids collecting account identity that is unnecessary for the proof.

A public-resource `200` with an accepted Authorization header can support authenticated state verification. A `401` is `INDETERMINATE(authentication_failed)`.

GitHub documents that insufficient private-resource access can deliberately appear as `404`; therefore every target `404` is treated as indeterminate in v0.8 rather than proof of non-existence.

### Least privilege

Only read access needed for repository metadata and pull-request state is permitted. No write method or mutation endpoint exists in the reader interface.

Exact permission requirements are documented against GitHub's current API docs before implementation merge. The implementation must not request or depend on write permission.

### Transport choice

The built-in reader uses a small standard-library `http.client` HTTPS transport so v0.8 adds no mandatory third-party runtime dependency and avoids environment-driven proxy discovery.

Transport rules:

- GitHub.com API only (`api.github.com`) in v0.8;
- HTTPS only;
- fixed GitHub API-version header;
- fixed User-Agent;
- GET only;
- bounded connect/read timeout;
- no automatic retry;
- no conditional-cache/ETag reuse between verifier calls;
- all HTTP redirects rejected rather than followed;
- Authorization is never forwarded to another host;
- bounded response size before JSON parsing;
- only required fields normalized;
- raw response body discarded after normalization;
- provider URL, response body and exception text never enter public evidence.

Rejecting redirects means a renamed/transferred repository locator may become `INDETERMINATE`; the caller must supply the current locator. Numeric repository ID still protects target identity after a successful read.

GitHub Enterprise Server is out of scope for v0.8.

## Private snapshot

`GitHubPullRequestSnapshot` may contain in memory:

- target repository ID;
- PR number;
- state and merged boolean;
- head object ID;
- head repository ID;
- base ref;
- merge object ID;
- request start/end timestamps;
- provider `Date` header when present;
- private HTTP status/category needed for classification.

It has a fixed/static repr and no default public serializer. The raw GitHub payload is not retained after normalization.

## Remote observation model

Remote verification requires three outcomes:

- `MATCH` — a trusted provider observation decisively matches the contract;
- `MISMATCH` — a trusted provider observation decisively contradicts the contract;
- `INDETERMINATE` — the verifier cannot safely decide.

`INDETERMINATE` includes:

- invalid/unaccepted authentication;
- `404` ambiguity;
- insufficient permission;
- rate limiting;
- network/TLS/timeout failure;
- rejected redirect;
- malformed/oversized/unexpected provider data;
- observation that cannot meet the trust/freshness rules.

Provider unavailability is never converted into a claim that the target action failed.

## Existing evaluator mapping

The existing evaluator remains authoritative.

`remote_postcondition_case()` maps:

- trusted `MATCH` -> one successful verification event -> `VERIFIED_COMPLETE` when it is the sole requirement;
- trusted `MISMATCH` -> one failed verification event -> `FAILED`;
- `INDETERMINATE` or untrusted observation -> no verification event -> `UNVERIFIED`.

This distinction is deliberate:

- `FAILED` means independent reality was successfully observed and contradicted the required state;
- `UNVERIFIED` means independent reality could not safely be established.

The existing evaluator itself is not changed to create a remote-specific status engine.

## Provider error classification

Fail closed with fixed classifications:

- `401` -> `INDETERMINATE(authentication_failed)`;
- `404` -> `INDETERMINATE(resource_unobservable)`;
- `403` or `429` with rate-limit evidence (`Retry-After` or exhausted rate-limit header) -> `INDETERMINATE(rate_limited)`;
- other `403` -> `INDETERMINATE(permission_unverified)`;
- `3xx` -> `INDETERMINATE(redirect_rejected)`;
- `5xx`, timeout, DNS/TLS/network failure -> `INDETERMINATE(provider_unavailable)`;
- malformed/oversized/unexpected successful response -> `INDETERMINATE(invalid_provider_response)`;
- authenticated, structurally valid snapshot contradicting contract -> `MISMATCH`;
- authenticated exact snapshot match -> `MATCH`.

No raw provider error string is serialized.

## Privacy boundary

Privacy remains a hard acceptance requirement.

### Never emitted by default public serialization

- access tokens, authorization headers, cookies or credential metadata;
- username/authenticated account identity;
- repository owner/name;
- repository numeric IDs;
- PR numbers;
- branch/ref names;
- head or merge object IDs;
- provider request URLs;
- raw response JSON/body;
- HTTP exception/provider error text;
- caller contract IDs;
- machine paths or environment values;
- content-derived or contract-derived digests.

### Public evidence may contain only

- fixed provider/kind/schema labels;
- fixed trust-basis label;
- fixed outcome/reason code;
- booleans for declared checks;
- a coarse fixed freshness flag when useful.

No raw timestamp, rate-limit count or private identifier is included in default public evidence.

Private correlation identifiers remain caller-side.

### Fixed reason codes

Initial codes:

- `matched`;
- `repository_identity_mismatch`;
- `head_mismatch`;
- `head_repository_mismatch`;
- `base_mismatch`;
- `state_mismatch`;
- `merge_mismatch`;
- `authentication_failed`;
- `permission_unverified`;
- `resource_unobservable`;
- `rate_limited`;
- `redirect_rejected`;
- `provider_unavailable`;
- `invalid_provider_response`;
- `observation_not_fresh`.

Codes never interpolate caller/provider values.

## Freshness and consistency

Each `verify_*` call performs a new provider request. v0.8 does not reuse a caller-supplied source-agent cache, local ETag cache or previous verifier snapshot.

The private snapshot records request start/end time and provider `Date` when available. The implementation defines a bounded clock-skew tolerance; an obviously stale/inconsistent provider timestamp yields `INDETERMINATE(observation_not_fresh)` rather than a match.

The default public observation exposes only a boolean/fixed freshness result.

A match proves state only at observation time. No background monitoring, polling, revocation watch or persistence claim is added in v0.8.

## Security/trust boundary

A `MATCH` proves only that the trusted HTTPS/authenticated GitHub read reported the required state at observation time.

It does not prove:

- the agent caused the state;
- the user authorized the action;
- the action was desirable/safe;
- another actor did not create the same state;
- the state persists later;
- GitHub itself was uncompromised.

The HTTPS/GitHub/authentication boundary is explicitly trusted for v0.8.

## Public API target

```python
from completion_verifier.remote.github import (
    GitHubPullRequestContract,
    GitHubRESTReader,
    evaluate_github_pull_request,
    verify_github_pull_request,
)

reader = GitHubRESTReader(credential_provider=my_provider)
observation = verify_github_pull_request(contract, reader)
evaluation = evaluate_github_pull_request(contract, reader)
```

No example contains a literal credential.

## Testing strategy

TDD is mandatory. Normal CI uses only synthetic fixtures and fake transports; no real GitHub token is committed or required.

### Contract/privacy tests

- strict field validation;
- 40/64 hex object-ID validation/canonicalization;
- contradictory merge fields rejected;
- fixed contract/private-snapshot repr;
- public serialization excludes repository/PR/ref/object-ID/token sentinels;
- no caller-controlled values in fixed errors.

### Reader/authentication tests

- credential provider invoked only in reader boundary;
- no environment-variable reads;
- no write HTTP method;
- no redirects followed;
- invalid auth -> indeterminate;
- `404` -> indeterminate;
- permission `403` -> indeterminate;
- rate-limit `403`/`429` -> indeterminate;
- timeout/DNS/TLS/network/5xx -> indeterminate;
- malformed/oversized response -> indeterminate;
- raw errors/headers/body never enter public output;
- no automatic retry;
- no cross-call ETag/cache reuse.

### Verification tests

- exact match;
- repository identity mismatch;
- head mismatch;
- head-repository mismatch;
- base mismatch;
- open/closed/merged distinctions;
- merged PR with wrong merge object ID;
- pre-merge `merge_commit_sha` never accepted as post-merge completion evidence;
- stale/inconsistent timestamp -> indeterminate.

### Evaluator tests

- match -> `VERIFIED_COMPLETE`;
- trusted mismatch -> `FAILED`;
- provider ambiguity/unavailability -> `UNVERIFIED`;
- no new status engine;
- v0.7 local tests unchanged and green.

### Release gates

- Python 3.10-3.13 source/sdist/wheel verification;
- clean-wheel install;
- dependency check;
- existing live-runner safety gate;
- repeated verification gate;
- remote privacy regression scan;
- no committed credentials or real account/provider fixtures.

A real-provider integration experiment is separately gated and never part of ordinary CI.

## First empirical experiment after implementation

After independent implementation review and exact-head gates:

1. use a disposable/research repository;
2. run a bounded GitHub task with one agent scaffold;
3. capture the agent's normal claim/trace separately;
4. independently verify the external PR state through v0.8;
5. inject false-success, wrong-head, wrong-base, wrong-state, permission-failure and rollback conditions;
6. compare source claim against independent provider observation;
7. measure false completion, recovery, unnecessary retry/refusal, disagreement and verification overhead;
8. repeat with at least two independently implemented agent scaffolds before comparative reliability claims.

No real-world performance or commercial reliability claim is made until these runs exist.

## Gaming / Lucas-Critique checks

The verifier changes incentives, so the experiment explicitly checks:

- **intended adaptation:** agents wait for externally verifiable completion before saying done;
- **gaming adaptation:** agents temporarily create the literal expected state or satisfy only the narrow contract;
- **strategic adaptation:** agents avoid hard tasks or over-retry to obtain a verifier pass;
- **equilibrium effect:** workflows may drift toward what is easiest to verify rather than what is best for the user;
- **failure signal:** rising refusal/retry rates, post-verification rollback, contract-satisfying but intent-violating actions, or user/verifier disagreement.

These signals determine whether later versions need temporal verification, richer intent contracts or causal evidence.

## Compatibility

- v0.7 local APIs/CLIs unchanged;
- sandbox/live behavior unchanged;
- existing evaluator authoritative;
- Python 3.10-3.13 supported;
- no mandatory third-party runtime dependency;
- no provider mutation or spend capability.

## Out of scope for v0.8

- PR creation/merge/close/comment;
- branch/ref mutation;
- GitHub issues/actions/deployments verification;
- GitHub Enterprise Server;
- Gmail/Calendar/database/payment/CRM/browser verification;
- automatic retries/polling/background monitoring;
- causal attribution;
- user-intent verification;
- OAuth/token acquisition;
- secret storage;
- dynamic plugin discovery;
- public disclosure of raw provider identifiers;
- production-readiness claims.

## Success criteria

v0.8 is complete only if:

1. one authenticated read-only GitHub PR contract can be independently verified;
2. target repository ID, head object ID, base ref and PR state are checked explicitly;
3. provider ambiguity maps to `UNVERIFIED`, not false `FAILED` evidence;
4. decisive trusted mismatch maps to `FAILED`;
5. trusted exact match maps through the existing evaluator to `VERIFIED_COMPLETE`;
6. no GitHub mutation capability exists;
7. credentials and caller-controlled remote identifiers never enter public evidence/repr/errors;
8. authentication/network/response parsing fail closed;
9. all v0.7 behavior remains unchanged;
10. exact-head repository gates pass before merge;
11. documentation states exactly what remote verification proves and does not prove;
12. real-provider experiments remain separate from implementation claims.

## External API assumptions to re-check before implementation merge

GitHub documentation checked 29 August 2026 currently states that:

- invalid REST credentials initially return `401`;
- insufficient access can return `403` or privacy-preserving `404`;
- private resources may intentionally return `404` when auth/access is inadequate;
- rate limits can return `403` or `429`;
- pull-request GET is available to read-capable token types;
- `merge_commit_sha` changes meaning after merge and depends on merge method.

These provider semantics are not permanent truths. The implementation must pin/document the GitHub API version it uses and re-check them immediately before release.
