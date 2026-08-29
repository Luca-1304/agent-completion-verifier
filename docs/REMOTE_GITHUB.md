# Authenticated GitHub remote-state verification

Version 0.8 adds one narrow external-state verifier for GitHub pull requests.
It is designed to answer a specific question:

> Did an authenticated, read-only GitHub observation report that the expected
> pull-request state existed at observation time?

This is stronger than accepting an agent's own success receipt, but it is not a
proof of everything around the action.

## What it verifies

A `GitHubPullRequestContract` can require:

- the target repository's stable numeric identity;
- a pull-request number;
- an expected head object ID;
- an expected base ref;
- expected `open`, `closed`, or `merged` state;
- an optional expected merge object ID;
- an optional head-repository identity for cross-repository pull requests.

The human-readable `owner/name` locator is private addressing data. Target
repository identity is checked against GitHub's `base.repo.id`; the pull
request's top-level database `id` is not used as repository identity. The pull
request number returned by the provider is also compared with the declared
contract rather than being trusted solely because it appeared in the request
path.

## Trust and authentication

The built-in `GitHubRESTReader` is authenticated and read-only. The caller
supplies a credential provider explicitly. The SDK does not discover secrets
from environment variables, `.env` files, credential helpers, or local secret
stores.

For GitHub's `GET /repos/{owner}/{repo}/pulls/{pull_number}` endpoint, a
fine-grained token can use either **Pull requests: read** or **Contents: read**
repository permission. GitHub also permits unauthenticated reads of public
resources, but v0.8 deliberately still requires an explicit credential because
its trust contract is an authenticated provider observation. A `404` is not
interpreted as proof of absence because insufficient access to private resources
can also produce `404`.

The reader performs one HTTPS `GET` against `api.github.com` for the target pull
request. It pins the supported GitHub REST API version `2022-11-28`. It does not
follow redirects, retry automatically, poll in the background, or expose
mutation methods. Transport timeout values must be finite and positive.

Normal CI uses fake readers/transports and requires no real GitHub credential.

## Outcomes

Remote observations use three outcomes before being mapped through the existing
evaluator:

- `MATCH`: authenticated, fresh provider state matches every declared check.
  As a sole requirement this maps to `VERIFIED_COMPLETE`.
- `MISMATCH`: authenticated, fresh provider state decisively contradicts the
  contract. This maps to `FAILED`.
- `INDETERMINATE`: the verifier cannot safely establish the target state, for
  example because authentication, permission, provider availability, rate
  limit, response validity, or freshness is uncertain. This maps to
  `UNVERIFIED`.

A target `404` is deliberately `INDETERMINATE`, because GitHub may return a
privacy-preserving `404` when a private resource is inaccessible. Provider
unavailability is therefore never converted into false evidence that an action
failed.

## Freshness

The verifier judges state at observation time. The v0.8 policy requires:

- request start not later than request finish;
- request finish no more than 5 seconds in the future relative to the verifier
  clock;
- local observation age no greater than 60 seconds;
- GitHub's `Date` header, when present, no more than 300 seconds away from local
  request finish.

A missing provider `Date` does not by itself invalidate an otherwise fresh local
observation. Non-finite verifier clock values are rejected rather than allowed
to bypass freshness comparisons.

## Privacy-safe public evidence

Contracts and private snapshots necessarily contain identifiers in memory so
that exact comparison is possible. Default public observation serialization is
much narrower. It does not emit:

- credentials, authorization headers, cookies, or credential-provider details;
- GitHub usernames/account identity;
- repository owner/name or numeric repository IDs;
- pull-request numbers;
- refs/branch names;
- head or merge object IDs;
- provider URLs or raw response bodies;
- raw provider exception text;
- private timestamps;
- caller identifiers or internal digests.

Public evidence contains only fixed provider/kind/schema labels, fixed reason
codes, the fixed trust basis, and boolean check results.

## What it does not prove

A successful v0.8 observation **does not prove causality**: another actor could
have created the matching state.

It **does not prove user authorization** or that the action was desirable,
legal, or safe.

It **does not guarantee permanence**: a PR can later be reverted, branches can
move, and remote state can change after observation.

It also does not prove GitHub itself is uncompromised or provide production
safety guarantees. The trusted boundary is GitHub's authenticated HTTPS API
response at the time of the read.

Temporal re-verification, rollback/revocation monitoring, causal linkage, and
additional providers are intentionally outside v0.8.

## Example with an injected reader

```python
from completion_verifier import GitHubPullRequestContract
from completion_verifier.remote.github import (
    GitHubRESTReader,
    evaluate_github_pull_request,
)

contract = GitHubPullRequestContract(
    repository="owner/repository",
    repository_id=123456,
    pull_number=42,
    expected_head_oid="a" * 40,
    expected_base_ref="main",
    expected_state="open",
)

# `credential_provider` is supplied by the application. Do not put literal
# secrets in source code, logs, examples, or public evidence.
reader = GitHubRESTReader(credential_provider)
evaluation = evaluate_github_pull_request(contract, reader)
print(evaluation.status.value)
```

The reader executes the observation only. It cannot create, merge, close,
comment on, or otherwise mutate the pull request.
