# Postcondition verification SDK

Version 0.7 adds a provider-free SDK for independently checking a small set of local postconditions after an agent or workflow claims that an action succeeded.

The SDK is an observer, not an executor. It performs **no network** calls, reads no credentials or environment variables, sends no messages, and does not mutate the state it is checking.

## Built-in verifier kinds

The v0.7 registry is deliberately closed to three local verifier kinds:

- `TextFileContract` — requires one confined regular file to contain the exact declared UTF-8 text.
- `DirectoryContract` — requires one confined directory to exist, optionally with declared direct children or an exact-empty requirement.
- `JsonObjectContract` — requires one confined UTF-8 JSON file to contain a top-level object matching declared keys and values, with optional exact-key-set checking.

Unknown verifier kinds are rejected. v0.7 does not load arbitrary plugins or user-supplied code.

## Basic use

```python
from pathlib import Path

from completion_verifier.postconditions import (
    TextFileContract,
    evaluate_postcondition,
    verify_postcondition,
)

contract = TextFileContract("output/result.txt", "ready\n")
observation = verify_postcondition(contract, Path("workspace"))
evaluation = evaluate_postcondition(contract, Path("workspace"))

print(observation.matches)
print(evaluation.status.value)
```

The verifier reads state independently of any source-reported success receipt. A matching observation is then adapted into the existing Agent Completion Verifier evaluator; v0.7 does not introduce a second status engine.

## Privacy boundary

Contracts can contain sensitive caller data in memory because verification may require an exact path, expected text, required child names, or JSON keys and values. Treat raw contract objects and their internal `identity_digest` as private application data unless you have separately established that the values are safe to disclose.

The default disclosure surface is **privacy-safe public serialization**:

- contract `to_public_dict()` output excludes caller paths, contract identifiers, file or child names, JSON key names and values, raw expected content, and the internal identity digest;
- observation `to_dict()` output contains only fixed kind/schema labels, booleans, numeric counts, the fixed trust-basis label, and fixed reason codes;
- resolved absolute roots, local usernames, home paths, parser messages, OS exception messages, environment values, and unrelated directory or JSON contents are not included.

Hashing personal data is not treated as anonymisation. A deterministic digest of low-entropy values can sometimes be guessed. The internal contract digest exists for exact identity/reproducibility and is intentionally excluded from public serialization by default.

If an application needs a private correlation ID, retain it separately from the disclosure-safe evidence object.

## Fail-closed behavior

The SDK rejects or fails closed on:

- absolute paths, traversal, backslashes, empty path components and unsupported schema versions;
- symlinked roots, parent components or final targets;
- wrong filesystem types;
- missing required state;
- I/O failures;
- invalid UTF-8 or JSON;
- duplicate JSON object keys;
- non-object JSON top levels;
- required child, expected value or exact-key mismatches.

Errors use fixed reason codes such as `missing`, `unsafe_path`, `wrong_type`, `io_error`, `invalid_utf8`, `invalid_json`, `duplicate_key`, `wrong_top_level`, and `key_mismatch`. Raw exception text is not used as public evidence.

## What this proves — and what it does not

For the three supported local contracts, the SDK can prove whether independently observed local state matches the declared postcondition at observation time, subject to the filesystem trust boundary documented above.

It **does not prove remote identity**, remote authorization, causal attribution, durable persistence after observation, or production safety. It also does not prove that a particular agent caused the state change merely because the resulting state matches.

Remote GitHub, email, calendar, database, deployment, browser, or payment verification is outside v0.7. Each future remote verifier needs a separately reviewed trust and privacy contract before implementation.

## Compatibility

The existing v0.6 sandbox and optional OpenAI live runner remain separate and unchanged by the postcondition SDK. The new package adds no required third-party runtime dependency and retains Python 3.10–3.13 support.
