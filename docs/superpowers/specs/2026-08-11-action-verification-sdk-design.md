# v0.7 Action Verification SDK design

Date: 11 August 2026
Status: proposed design
Scope: provider-free verification only

## Goal

Turn Agent Completion Verifier's existing evidence-grounded completion logic into a small reusable SDK for independently verifying postconditions after an agent or workflow claims an action succeeded.

The SDK observes and judges state. It does not execute actions, call providers, send messages, mutate external systems, or require credentials.

## Why this shape

Version 0.6 already proves a strong narrow path: one exact file-write contract can be independently observed and evaluated without trusting the source's success report. v0.7 should generalise that idea without weakening or rewriting the proven sandbox path.

The new layer therefore sits beside the existing sandbox implementation. Existing v0.6 behaviour remains a compatibility boundary and can later be adapted into the generic interface after the new contract is proven.

## Architecture

Add a focused `completion_verifier.postconditions` package with four concepts:

1. `PostconditionContract`
   - immutable description of what state must be true;
   - explicit `kind` and schema version;
   - deterministic canonical digest;
   - strict parsing with unknown-field rejection.

2. `PostconditionObservation`
   - normalized result of independently reading state;
   - records whether the observation was trustworthy, whether the contract matched, and a small allow-listed evidence payload;
   - never treats a source-provided receipt as independent evidence.

3. `PostconditionVerifier`
   - narrow verifier protocol/interface: `verify(contract, root) -> observation`;
   - read-only by contract;
   - verifier failures fail closed rather than becoming successful or ambiguous matches.

4. Explicit verifier registry
   - maps a known `kind` to a concrete verifier;
   - no dynamic import, package discovery, arbitrary code loading, or plugin execution in v0.7;
   - unknown kinds are rejected.

The first three verifier kinds are deliberately local and deterministic:

### A. Exact text-file state

Checks a confined relative path for:
- path confinement;
- no symlink traversal;
- regular-file type;
- exact UTF-8 byte equality;
- size and SHA-256 consistency.

This should reuse proven path-safety primitives where practical but must not change existing v0.6 sandbox semantics.

### B. Directory state

Checks a confined relative path for:
- existence;
- directory type;
- no symlink traversal;
- optional required direct child names;
- optional exact-empty requirement.

It does not recursively inventory arbitrary directory contents by default.

### C. Structured JSON state

Checks a confined regular UTF-8 JSON file for:
- strict JSON parsing;
- duplicate-key rejection;
- top-level object requirement;
- exact expected values only for explicitly declared JSON object keys;
- optional exact-key-set mode.

v0.7 does not add JSONPath, arbitrary predicates, regex execution, schema engines, or user-supplied code.

## Data flow

1. Caller supplies a strict postcondition contract and a local root.
2. Registry selects the verifier by explicit `kind`.
3. Verifier independently reads local state.
4. Verifier emits a normalized `PostconditionObservation`.
5. A small adapter converts the observation into the existing `Case`/`Event` evidence model so the current evaluator can produce `VERIFIED_COMPLETE`, `PARTIAL`, `UNVERIFIED`, or `FAILED` without a second evaluation engine.
6. Caller may serialize the contract and observation using deterministic public methods.

No source-reported success field can satisfy the postcondition by itself.

## Personal-information and secret protection

Privacy is a hard acceptance requirement for v0.7.

### Data minimisation

- The generic observation schema stores only evidence needed to prove or disprove the declared contract.
- It must not automatically capture file bodies, directory listings beyond explicitly requested child names, environment variables, usernames, home-directory names, email addresses, account identifiers, message contents, API responses, or unrelated metadata.
- Error messages must be sanitized and use contract-relative paths rather than resolved absolute filesystem paths.

### Public/test fixtures

- Repository examples and tests use synthetic identifiers only.
- No real names, personal email addresses, phone numbers, addresses, credentials, private message bodies, machine usernames, or local home paths are permitted in new v0.7 fixtures.
- Tests should include a regression check that representative serialized observations do not leak absolute root paths or unrelated file contents.

### Digests are not automatic anonymisation

- The SDK must not hash arbitrary personal fields merely to claim they are safe. Low-entropy identifiers can sometimes be recovered by guessing.
- Content digests are appropriate where they prove a caller-declared local artifact contract; they are not a general PII-redaction mechanism.
- Future remote adapters must prefer minimal booleans, counts, caller-supplied opaque references, or deliberately scoped metadata over raw personal fields.

### Secrets

- v0.7 has no credential inputs and no network clients.
- Environment variables are not read by the postcondition package.
- Existing repository secret/private-run ignore rules remain in force.
- Exceptions and serialized observations must not include environment values or secret material.

## Error handling

Fail closed:

- invalid or unknown contract -> reject before observation;
- path traversal, symlink escape, non-regular expected file, unsafe root -> non-matching observation or explicit verification error, never success;
- malformed JSON or duplicate keys -> non-match with sanitized reason;
- I/O errors -> non-match/verification failure with sanitized reason;
- unknown verifier kind -> reject;
- registry collisions -> reject at definition/construction time.

No verifier may silently coerce malformed input into a valid contract.

## Compatibility

- Existing public v0.6 APIs and CLI commands remain unchanged.
- No change to the optional OpenAI live runner.
- No new runtime dependency is required.
- Python 3.10-3.13 support remains required.
- The existing evaluator remains authoritative for completion status.

## Public API target

The public surface should stay small. Intended shape:

```python
from completion_verifier.postconditions import (
    verify_postcondition,
    TextFileContract,
    DirectoryContract,
    JsonObjectContract,
)

observation = verify_postcondition(contract, root)
```

Concrete class/function names may be adjusted during implementation only if the resulting API remains equally small and explicit.

## Testing strategy

Use test-driven development.

Minimum tests:

- contract parsing/deterministic digests;
- unknown fields and schema versions rejected;
- registry accepts known kinds and rejects unknown kinds;
- text-file success, missing file, content mismatch, wrong type, traversal, final symlink, parent symlink;
- directory success, missing directory, wrong type, required-child mismatch, empty/non-empty checks, symlink rejection;
- JSON success, value mismatch, missing key, unexpected key in exact mode, malformed UTF-8/JSON, duplicate key, wrong top-level type, symlink rejection;
- normalized observation -> existing evaluator integration;
- serialized evidence excludes resolved absolute root paths and unrelated contents;
- no postcondition code reads environment credentials;
- complete existing source test suite still passes.

Release verification should retain the repository's full Python 3.10-3.13 matrix and clean-wheel checks.

## Out of scope for v0.7

- Gmail, Google Calendar, GitHub, database, browser, deployment, payment, or other remote verifiers;
- network access;
- credentials or OAuth;
- action execution;
- arbitrary user plugins;
- automatic retries;
- background monitoring;
- recursive filesystem indexing;
- storing raw personal content for convenience;
- claiming production readiness from local-only verification.

## Follow-on direction

After v0.7 is proven, remote verifiers can implement the same postcondition interface one at a time. Each remote adapter must define its own trust boundary and privacy-minimal evidence contract before implementation. Likely first candidates are GitHub pull-request/ref verification and email-send verification, because both directly test the original false-completion problem.

## Success criteria

v0.7 is complete only if:

1. three provider-free verifier kinds work through one explicit API;
2. all verifier inputs fail closed;
3. observations feed the existing evaluator rather than creating a parallel status system;
4. v0.6 behaviour remains unchanged;
5. serialized evidence is privacy-minimal and does not leak absolute machine paths or unrelated content;
6. no credential/network dependency is introduced;
7. full repository verification passes on the exact implementation head;
8. documentation clearly states that local postcondition verification does not prove remote identity, authorization, causation, or production safety.
