# v0.8 GitHub remote-state verifier design

Date: 29 August 2026
Status: proposed for review
Scope: first authenticated remote-state verifier only
Tracking issue: #19

## Goal

Extend Agent Completion Verifier beyond local postconditions with one independently authenticated, read-only verifier for GitHub pull-request state.

The verifier answers a narrow question:

> Did GitHub independently report that the expected pull-request state existed at observation time?

It does not execute the action being judged, mutate GitHub, infer user intent, prove authorization, prove causal attribution, or guarantee that the state will remain true later.

## Why GitHub first

GitHub is the preferred first remote provider because pull-request state is concrete, machine-readable and externally observable without retaining message bodies or other high-sensitivity personal content.

The first target is deliberately one narrow contract: a GitHub pull request. Ref, deployment, issue, email, calendar, database and payment verifiers remain out of scope until this boundary is proven.

## Architectural choice

Use an injected read-only provider reader rather than putting authentication and HTTP logic inside the verification engine.

The architecture has five layers:

1. **Private contract** — immutable expected GitHub state.
2. **Credential boundary** — caller-owned credential provider; the SDK never reads environment variables for secrets.
3. **Read-only GitHub reader** — authenticated GET-only transport that normalizes only fields needed for verification.
4. **Remote verifier** — compares the private snapshot with the private contract and emits privacy-minimal evidence.
5. **Existing evaluator adapter** — maps decisive match/mismatch/indeterminate outcomes into the existing evaluator instead of creating a new status engine.

This keeps v0.7 local verification unchanged and prevents provider credentials, URLs and raw API payloads from leaking into the core completion model.

## Package boundary

Add a separate remote package beside `completion_verifier.postconditions`:

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

The local `postconditions` package remains provider-free and unchanged.

## Initial contract

`GitHubPullRequestContract` is immutable and privacy-sensitive. It contains only fields needed to define the expected state:

- private repository locator (`owner/name`) used to address the provider;
- required stable numeric repository ID;
- pull-request number;
- expected head commit SHA;
- expected base ref;
- expected state: `open`, `closed`, or `merged`;
- optional expected merge SHA, valid only when `expected_state="merged"`;
- optional expected head-repository ID for cross-repository pull requests.

Repository ID is authoritative for target identity. The human-readable repository locator is only an addressing input and must not substitute for the numeric identity check.

Pull numbers and repository IDs must be positive integers. Refs are validated as bounded non-empty strings and reject control characters. Commit IDs accept supported hexadecimal Git object identifiers without silently normalizing arbitrary input.

`repr(contract)` is fixed/static and never contains repository names, IDs, PR numbers, refs or SHAs.

## Expected-state semantics

A successful provider read is compared exactly:

- `open` requires provider state `open` and not merged;
- `closed` requires provider state `closed` and not merged;
- `merged` requires the provider's merged state to be true;
- head SHA must match exactly;
- base ref must match exactly;
- target repository ID must match exactly;
- optional head-repository ID must match exactly when declared;
- optional merge SHA must match GitHub's post-merge `merge_commit_sha` when declared.

The verifier does not use GitHub's `mergeable` field as proof of completion. GitHub documents that `merge_commit_sha` has different semantics before and after merge, so merge-SHA verification is only meaningful after the provider reports the PR as merged.

## Provider reader

### Interface

`GitHubStateReader` is an injected protocol. The verifier depends on that protocol, not on HTTP directly.

The built-in implementation, `GitHubRESTReader`, provides the first real provider path and uses GET requests only.

The reader returns a strict private `GitHubPullRequestSnapshot`; it does not return raw JSON to the verifier.

### Authentication

The caller supplies a credential provider object/callable. The SDK does not:

- read `.env` files;
- read `os.environ`/`os.getenv`;
- discover local credential stores;
- persist credentials;
- include credentials in repr, exceptions, observations or fixtures.

The credential exists only inside the reader boundary long enough to construct the Authorization header.

The initial trust policy is authenticated verification. Anonymous public reads may be added later but cannot produce the same authenticated trust basis in v0.8.

The reader first validates that the supplied credential is accepted by an authentication-capable GitHub API request, then performs the target read. A resource read that is public by itself is not sufficient evidence that authentication succeeded.

GitHub currently documents that invalid credentials initially yield `401`, while insufficient access can produce `403` or a privacy-preserving `404`. Therefore `404` is never blindly interpreted as proof that a private resource does not exist.

### Least privilege

The implementation requests only read operations needed for repository metadata and pull-request state. It must not require write permissions and must not expose mutation methods.

GitHub currently documents pull-request reads as available to read-capable GitHub App/user/installation tokens, and repository metadata is separately read-scoped. Exact required permissions are documented in the implementation guide and verified against GitHub's current API docs at release time.

### Transport rules

The built-in reader:

- uses HTTPS only;
- targets GitHub.com API only in v0.8;
- sends a fixed API-version header and fixed User-Agent;
- performs GET only;
- sets bounded connect/read timeouts;
- does not automatically retry;
- does not forward Authorization to a different host during redirects;
- rejects cross-host redirects;
- bounds response size before JSON parsing;
- parses only required response fields and discards raw bodies afterward;
- never interpolates provider URLs, raw response bodies or credential material into public errors.

GitHub Enterprise support is out of scope for v0.8.

## Private snapshot

`GitHubPullRequestSnapshot` may contain, in memory:

- repository ID;
- PR number;
- state/merged state;
- head SHA;
- head repository ID;
- base ref;
- merge SHA;
- provider observation timestamp;
- internal HTTP status/category needed for error classification.

It has a fixed/static repr and no default public serializer.

The raw GitHub payload is not retained after normalization.

## Remote observation model

Remote verification requires three outcomes rather than a single success boolean:

- `MATCH` — trusted provider observation decisively matches the contract;
- `MISMATCH` — trusted provider observation decisively contradicts the contract;
- `INDETERMINATE` — the verifier could not safely decide.

Examples of `INDETERMINATE`:

- authentication could not be validated;
- private-resource `404` is ambiguous;
- permission is insufficient;
- rate limit is reached;
- network/TLS/timeout failure;
- provider returns malformed/unexpected data;
- the observation cannot meet freshness/trust requirements.

This distinction is mandatory. Provider unavailability must never be converted into a false claim that the target action failed.

## Existing evaluator mapping

The existing evaluator remains authoritative.

`remote_postcondition_case()` maps outcomes as follows:

- trusted `MATCH` -> one successful verification event -> `VERIFIED_COMPLETE` when it is the sole requirement;
- trusted `MISMATCH` -> one failed verification event -> `FAILED`;
- `INDETERMINATE` or untrusted observation -> no successful/failed action event -> `UNVERIFIED`.

This is intentionally different from treating every non-match as failure. `UNVERIFIED` means reality could not be established; `FAILED` means reality was observed and contradicted the claim.

No second completion-status engine is introduced.

## Privacy boundary

Privacy remains a hard acceptance requirement.

### Never emitted by default public serialization

- access tokens, authorization headers, cookies or credential metadata;
- usernames or authenticated account identity;
- repository owner/name;
- repository numeric IDs;
- PR numbers;
- branch/ref names;
- head or merge SHAs;
- provider request URLs;
- raw response JSON/body;
- provider error text;
- caller contract IDs;
- machine paths, environment values or local secret locations;
- content-derived or contract-derived digests.

### Public evidence may contain only

- fixed provider/kind/schema labels;
- fixed trust-basis labels;
- fixed outcome/reason codes;
- booleans for declared checks;
- bounded numeric counts/age values only where they cannot identify caller content.

Private identifiers may be correlated by the caller outside the public evidence object.

### Reason codes

Reason codes are fixed and non-interpolating. Initial examples:

- `matched`;
- `repository_identity_mismatch`;
- `head_mismatch`;
- `base_mismatch`;
- `state_mismatch`;
- `merge_mismatch`;
- `authentication_failed`;
- `permission_unverified`;
- `resource_unobservable`;
- `rate_limited`;
- `provider_unavailable`;
- `invalid_provider_response`;
- `observation_not_fresh`.

Public output never includes raw HTTP exception strings or response bodies.

## Freshness and consistency

v0.8 verifies state at observation time, not indefinitely.

Each private observation records request start/end time and the provider response date when available. The reader requests fresh state rather than accepting an application-level cached result supplied by the source agent.

A public observation may report only a coarse/fixed freshness status, not the private timestamp unless an explicit disclosure layer is added later.

The verifier makes no claim that a matching state persists after observation. Temporal re-verification, revocation and rollback monitoring remain follow-on work.

No background monitoring or automatic polling is added in v0.8.

## Security and trust boundaries

The verifier proves provider-observed state, not causality.

A `MATCH` does not prove:

- the agent caused the state;
- the user authorized the action;
- the action was safe or desirable;
- the expected state was not created by another actor;
- the state remains true after the observation;
- GitHub itself was uncompromised.

The HTTPS/provider/authentication boundary is explicitly trusted for v0.8.

## Failure handling

Fail closed:

- invalid contract -> reject construction;
- unsupported provider/kind -> reject;
- invalid credential -> `INDETERMINATE`;
- permission ambiguity -> `INDETERMINATE`;
- private/ambiguous `404` -> `INDETERMINATE` unless an earlier trusted read makes non-existence decisive;
- `403`/`429` rate limit -> `INDETERMINATE` with fixed rate-limit reason;
- network/TLS/timeout -> `INDETERMINATE`;
- malformed provider JSON/schema -> `INDETERMINATE`;
- authenticated, structurally valid response that contradicts contract -> `MISMATCH`;
- exact trusted match -> `MATCH`.

No retries are hidden inside verification. A caller can choose to run a new explicit verification later.

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

The credential provider is caller-owned and deliberately omitted from examples containing literal secrets.

## Testing strategy

TDD is mandatory. Tests use synthetic fixtures and fake transports; no real token is committed or required by normal CI.

Minimum RED-first coverage:

### Contracts/privacy

- strict field validation;
- contradictory merge fields rejected;
- fixed repr excludes every caller-controlled sentinel;
- public observation serialization excludes repository/PR/ref/SHA/token sentinels;
- deep immutability where nested state exists.

### Reader/authentication

- credential provider is called only inside reader boundary;
- no environment-variable reads;
- no write HTTP methods;
- invalid credential -> indeterminate;
- insufficient permission -> indeterminate;
- ambiguous private `404` -> indeterminate;
- rate-limit `403`/`429` -> indeterminate;
- timeout/TLS/network failure -> indeterminate;
- malformed/oversized response -> indeterminate;
- cross-host redirect rejected without forwarding authorization;
- raw provider errors never enter public output;
- no automatic retry.

### Verification semantics

- exact match;
- wrong repository identity;
- wrong head SHA;
- wrong head repository identity;
- wrong base ref;
- open vs closed vs merged distinctions;
- merged PR with wrong expected merge SHA;
- provider indeterminate state;
- GitHub pre-merge `merge_commit_sha` is never accepted as post-merge completion evidence.

### Evaluator integration

- match -> `VERIFIED_COMPLETE`;
- decisive mismatch -> `FAILED`;
- unavailable/ambiguous read -> `UNVERIFIED`;
- existing evaluator remains the only status engine;
- all v0.7 local postcondition tests remain unchanged and green.

### Release gates

- Python 3.10-3.13 source/sdist/wheel verification;
- clean-wheel install;
- dependency check;
- existing live-runner safety gate;
- repeated verification gate;
- static privacy regression for remote package;
- no committed credentials or provider response fixtures containing real account data.

A separately gated real-provider experiment may be run only against a disposable/research repository after the implementation is reviewed. It is not part of normal CI and must not publish private identifiers.

## First empirical experiment after implementation

Once v0.8 is independently reviewed and exact-head CI is green:

1. use a disposable/research repository;
2. run a bounded GitHub task with an agent scaffold;
3. capture the agent's normal completion claim/trace separately;
4. independently verify GitHub PR state through v0.8;
5. inject false-success, wrong-head, wrong-base, wrong-state, permission-failure and rollback conditions;
6. compare source claim with provider-observed state;
7. measure false-completion rate, recovery, unnecessary retry/refusal, verifier disagreement and verification overhead;
8. repeat with at least two independently implemented agent scaffolds before comparative claims.

No real-world performance or commercial reliability claim is made until these runs exist.

## Gaming / Lucas-Critique checks

The new verifier changes agent incentives, so the experiment must explicitly test adaptation:

- **intended adaptation:** agent waits for externally verifiable completion before claiming done;
- **gaming adaptation:** agent creates the literal expected state temporarily or satisfies only the narrow contract;
- **strategic adaptation:** agent avoids difficult tasks or over-retries to obtain a verifier pass;
- **equilibrium effect:** workflows may shift toward actions that are easiest to verify rather than best for the user;
- **failure signal:** rising refusal/retry rates, post-verification rollback, contract-satisfying but intent-violating actions, or disagreement between user outcome and verifier outcome.

These signals determine whether later versions need temporal checks, richer intent contracts or causal evidence.

## Compatibility

- v0.7 local public APIs/CLIs unchanged;
- existing sandbox/live behavior unchanged;
- existing evaluator remains authoritative;
- Python 3.10-3.13 supported;
- no mandatory third-party runtime dependency is introduced if the built-in reader can remain on a small auditable standard-library HTTPS transport;
- no provider mutation or spend capability is introduced.

## Out of scope for v0.8

- creating, merging, closing or commenting on PRs;
- branch/ref mutation;
- GitHub issue/action/deployment verification;
- GitHub Enterprise Server;
- Gmail, Calendar, databases, payments, CRM or browser verification;
- automatic retries/polling/background monitoring;
- causal attribution;
- user-intent verification;
- token acquisition/OAuth login flows;
- secret storage;
- generic plugin discovery;
- public disclosure of raw provider identifiers;
- production-readiness claims.

## Success criteria

v0.8 is complete only if:

1. one authenticated read-only GitHub PR contract can be independently verified;
2. target repository identity, head SHA, base ref and PR state are checked explicitly;
3. provider ambiguity maps to `UNVERIFIED`, not false `FAILED` evidence;
4. decisive trusted mismatch maps to `FAILED`;
5. trusted exact match maps through the existing evaluator to `VERIFIED_COMPLETE`;
6. no GitHub mutation capability exists;
7. credentials and caller-controlled remote identifiers never enter public evidence/repr/errors;
8. authentication/network/response parsing fail closed;
9. all v0.7 behavior remains unchanged;
10. exact-head repository gates pass before merge;
11. documentation states clearly what external-state verification proves and does not prove;
12. the first real-provider experiment remains separate from implementation claims.

## External API assumptions to re-check before implementation merge

GitHub's documentation as checked 29 August 2026 states that:

- invalid REST credentials initially return `401`;
- insufficient access can return `403` or privacy-preserving `404`;
- private resources may intentionally return `404` when authentication is inadequate;
- rate limits can return `403` or `429`;
- pull-request GET is available to read-capable token types;
- `merge_commit_sha` changes meaning after merge and depends on merge method.

These are provider semantics, not permanent truths. The implementation must pin/document the API version it uses and re-check these assumptions against current GitHub documentation before release.
