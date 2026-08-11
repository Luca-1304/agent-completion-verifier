# v0.7 Action Verification SDK design

Date: 11 August 2026
Status: approved
Scope: provider-free verification only

## Goal

Turn Agent Completion Verifier's evidence-grounded completion logic into a small reusable SDK for independently verifying postconditions after an agent or workflow claims an action succeeded.

The SDK observes and judges state. It does not execute actions, call providers, send messages, mutate external systems, or require credentials.

## Architecture

Add `completion_verifier.postconditions` beside the proven v0.6 sandbox. Existing v0.6 behaviour stays unchanged.

The new package has four concepts:

1. **Strict contracts** — immutable descriptions of required state with explicit kind/schema and fail-closed validation.
2. **Normalized observations** — independently read state represented as booleans/counts/fixed reason codes, not source receipts.
3. **Read-only verifiers** — `verify(contract, root) -> observation` with no mutation or network access.
4. **Closed registry** — exactly the built-in verifier kinds; no dynamic import, package discovery, arbitrary code loading, or registration hook in v0.7.

The existing evaluator remains authoritative. A small adapter converts an observation to the existing `Case`/`Event` model and calls `evaluate_case`; v0.7 does not create a second status engine.

## Initial verifier kinds

### Exact text-file state

Checks a confined relative path for existence, no symlink traversal, regular-file type, exact UTF-8 byte equality, and size consistency. Expected and observed text may exist in memory for comparison but are never emitted by public serialization.

### Directory state

Checks a confined relative path for existence, directory type, no symlink traversal, optional required direct children, and optional exact-empty state. `exact_empty=True` is mutually exclusive with non-empty required children. The verifier never recursively inventories contents and never serializes child names.

### Structured JSON state

Checks a confined regular UTF-8 file for strict JSON, duplicate-key rejection, top-level object type, declared expected key/value matches, and optional exact-key-set mode. Expected/observed values and key names may exist in memory for comparison but public evidence contains only aggregate match booleans/counts.

## Data flow

1. Caller constructs a strict contract and supplies a local root.
2. Closed registry selects the known verifier.
3. Verifier independently reads local state.
4. Verifier returns a normalized `PostconditionObservation`.
5. Adapter maps observation to one existing evaluator requirement/event.
6. Existing evaluator returns `VERIFIED_COMPLETE`, `PARTIAL`, `UNVERIFIED`, or `FAILED`.

A source-reported success value cannot satisfy the postcondition by itself.

## Privacy and secret protection

Privacy is a hard acceptance requirement.

### In-memory versus public evidence

Contracts may contain caller-controlled strings in memory because verification needs them: paths, expected text, required child names, JSON keys/values, and an optional caller contract identifier.

**Public serialization is deliberately narrower.** Default `to_public_dict()` / `to_dict()` output must not emit any caller-controlled identifier or value, including:

- raw or relative paths;
- contract identifiers;
- file names or directory child names;
- JSON key names or values;
- expected or observed text/content;
- absolute roots or machine paths;
- usernames/home-directory names;
- email addresses, account identifiers, message bodies, phone numbers, addresses;
- environment variables or credentials;
- raw parser or OS exception text;
- content-derived or contract-derived digests that could be dictionary-guessed from low-entropy personal values.

Public output is limited to fixed schema/kind labels, booleans, numeric counts, the fixed trust-basis label, and fixed reason codes. Callers that need a private correlation identifier keep it outside the public evidence object.

### Digests are not anonymisation

An internal deterministic digest may be used for exact contract identity and reproducibility. It is **not** included in privacy-safe public output by default and must not be described as anonymised PII. Low-entropy values can be guessed even when hashed.

### Errors

Errors use fixed codes such as `missing`, `unsafe_path`, `wrong_type`, `io_error`, `invalid_utf8`, `invalid_json`, `duplicate_key`, and `wrong_top_level`. They do not interpolate paths, file names, raw JSON, OS errors, or content.

### Tests and repository fixtures

New tests/examples use synthetic sentinel values only. Regression tests must prove that public serialization excludes:

- expected and observed sentinels;
- contract IDs;
- relative and absolute paths;
- declared/undeclared child names;
- JSON key names and values;
- unrelated local content.

No real personal identifiers, credentials, private messages, or local user paths are introduced in v0.7 fixtures.

### Secrets and networking

- no credential parameters;
- no environment-variable reads from the postcondition package;
- no network clients/imports;
- existing `.env`, key, credential, `private_runs/`, and `live_runs/` ignore boundaries remain in force;
- no provider call or spend.

## Error handling

Fail closed:

- invalid schema/unknown fields -> reject contract;
- unknown verifier kind -> reject;
- traversal, backslashes, absolute paths, symlinks, unsafe root -> never match;
- malformed UTF-8/JSON or duplicate keys -> never match;
- wrong filesystem type -> never match;
- contradictory directory requirements -> reject construction;
- I/O failure -> non-match with fixed `io_error` reason.

No malformed input is silently coerced into a valid contract.

## Compatibility

- existing v0.6 public APIs and CLIs unchanged;
- optional OpenAI live runner unchanged;
- no new runtime dependency;
- Python 3.10-3.13 remains supported;
- existing evaluator remains authoritative.

## Public API target

```python
from completion_verifier.postconditions import (
    DirectoryContract,
    JsonObjectContract,
    TextFileContract,
    evaluate_postcondition,
    verify_postcondition,
)

observation = verify_postcondition(contract, root)
evaluation = evaluate_postcondition(contract, root)
```

The public surface stays small and explicit.

## Testing strategy

TDD is mandatory. Minimum coverage:

- strict contracts and deterministic internal identity;
- unknown fields/schema versions rejected;
- contradictory directory requirements rejected;
- registry accepts only built-ins;
- text success/missing/mismatch/wrong type/traversal/parent and final symlink;
- directory success/missing/wrong type/required-child/empty/symlink;
- JSON success/mismatch/missing/extra key modes/malformed UTF-8/JSON/duplicate key/wrong top level/symlink;
- observation -> existing evaluator integration;
- public serialization leak regression for all caller-controlled identifiers/values;
- no environment or network use;
- full existing source suite passes unchanged.

Release verification retains the Python 3.10-3.13 matrix, clean-wheel checks, and 15-pass 3.10/3.13 gate before merge.

## Out of scope for v0.7

- Gmail, Calendar, GitHub, database, browser, deployment, payment, or other remote verifiers;
- credentials/OAuth/networking;
- action execution;
- arbitrary plugins;
- retries or monitoring;
- recursive filesystem indexing;
- public storage of raw personal content;
- production-readiness claims.

## Follow-on direction

After v0.7 is proven, add remote verifiers one at a time with their own reviewed trust/privacy contracts. GitHub PR/ref verification is the preferred first remote adapter because it can prove a concrete external state transition without needing message content.

## Success criteria

v0.7 is complete only if:

1. three provider-free verifier kinds work through one explicit API;
2. all malformed/unsafe inputs fail closed;
3. observations feed the existing evaluator;
4. v0.6 behaviour remains unchanged;
5. public evidence contains no caller-controlled identifiers/values or machine paths;
6. no credential/network dependency is introduced;
7. full exact-head repository verification passes;
8. docs state the local/remote trust boundary accurately.
