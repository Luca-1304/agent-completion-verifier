# Independent Sandbox Postconditions — Design

Date: 2026-07-21
Issue: #8 — Add independent sandbox postcondition verification

## Purpose

Add a safe local execution environment where file-writing outcomes are verified by independently reading sandbox state rather than trusting source-reported success or evidence.

This release demonstrates a stronger evidence boundary for one narrow domain: UTF-8 file writes inside an isolated temporary root. It does not provide production identity, authorization, malware isolation, operating-system virtualization, or proof about remote systems.

## Approaches considered

### 1. Trust the tool result and add more receipt fields

Require the tool to report path, size, and hash.

- Advantage: minimal implementation.
- Failure: the same untrusted source supplies both the completion claim and the evidence.

### 2. Re-read state after the tool call but merge the observation into the raw event

Add observed values to the original tool event.

- Advantage: easy to feed into the existing evaluator.
- Failure: source-reported and independently observed data become difficult to distinguish and audit.

### 3. Separate raw report, independent observation, and canonical evidence — selected

Execute within a confined sandbox, preserve the raw report unchanged, independently inspect actual state, and derive a new canonical verifier event only from the observation.

- Advantage: explicit trust boundary, auditable artifacts, safe local reproducibility, and a clean path toward independent postcondition plugins for other domains.
- Cost: more artifact types and a dedicated conversion step.

## Scope

The first release supports exactly one contract type:

- action: `write_file`;
- path: non-empty relative path inside the sandbox;
- content: UTF-8 text;
- expected evidence: observed path, existence, byte size, SHA-256, and content match.

The narrow scope is intentional. It allows strong path-confinement and postcondition tests without implying that arbitrary shell commands or remote tools are safe.

## Core models

### `FileWriteContract`

Immutable task contract containing:

- `contract_id`;
- relative `path`;
- expected UTF-8 `content`;
- derived `expected_size`;
- derived `expected_sha256`;
- schema version.

The contract rejects absolute paths, empty paths, `.` or `..` components, NUL bytes, and Windows drive-like prefixes.

### `SourceToolReport`

Preserves what the simulated or future real tool reported:

- scenario ID;
- attempted path;
- reported success;
- reported evidence;
- error kind;
- completion claim;
- source event ID.

These values never enter the canonical evidence event.

### `FileObservation`

Produced only by the independent local observer:

- contract ID;
- relative observed path;
- existence;
- regular-file status;
- byte size;
- SHA-256 when readable;
- content match;
- path confinement result;
- observation error when present;
- trust basis `independent_local_state`.

An observation is successful only when the confined path is a regular file and size, digest, and bytes match the contract.

### `SandboxRunResult`

Contains references to the contract, source report, observation, canonical case, and evaluation. Serialisation keeps every layer separate.

## Path confinement

`SafeFileSandbox` owns a resolved root directory and never follows user-controlled symlinks.

Rules:

1. contract and attempted paths must be relative and contain no traversal components;
2. every existing parent component under the root is checked with `lstat` and rejected if it is a symlink;
3. missing parent directories are created one component at a time;
4. the final target is rejected when it is a symlink or non-regular file;
5. reads repeat the same component checks rather than trusting a previously resolved path;
6. writes use a temporary file in the verified parent followed by `os.replace`, and the temporary filename is generated internally;
7. no path outside the root is opened, created, removed, or hashed;
8. path violations raise `SandboxSecurityError` and are recorded as failed source reports and failed observations.

The first release targets the Linux behavior used by CI. It does not claim resistance to a hostile concurrent process racing filesystem changes. Production-grade isolation would require an OS sandbox, file-descriptor-relative APIs throughout, and stronger race protections.

## Controlled scenarios

The deterministic reference suite contains:

1. `success` — exact file written; source reports success;
2. `false_success` — no file written; source reports success and fabricated receipt;
3. `partial_write` — truncated content written; source reports success;
4. `timeout_before_write` — no write; source reports timeout and no completion;
5. `timeout_after_write` — exact file written, then source reports timeout and no completion;
6. `rollback` — exact file written then removed; source reports success;
7. `path_traversal` — attempt to write outside root using `../`;
8. `symlink_escape` — attempt through a symlinked parent that points outside root.

The suite uses deterministic contract content and source event IDs. The symlink scenario creates a disposable external directory beside the sandbox and verifies that it remains unchanged.

## Independent conversion to verifier case

The canonical case uses:

- action: `verify_file_postcondition`;
- required evidence fields: `path`, `size`, `sha256`, `trust_basis`;
- completion claim: copied from the source report only as the claim under evaluation;
- event success: derived solely from `FileObservation.matches_contract`;
- event evidence: derived solely from independent observation fields.

A fabricated source receipt therefore cannot satisfy the verifier. Conversely, `timeout_after_write` can produce `VERIFIED_COMPLETE` without a completion claim because actual local state matches the contract.

When confinement fails or state does not match, the observer emits a failed required event, producing `FAILED` rather than merely `UNVERIFIED`: the independent observer established that the postcondition was not met at observation time.

## Artifact layout

A suite run writes into a new empty output directory:

```text
<output>/
  suite_config.json
  manifest.json
  runs/
    <scenario>/
      contract.json
      source_report.json
      observation.json
      case.json
      evaluation.json
      state/
        ... sandbox files when retained ...
  results.jsonl
  metrics.json
  report.md
```

The manifest stores SHA-256 digests for every regular artifact except itself. Symlinks are never included as persisted artifacts. The suite refuses to overwrite a non-empty directory.

## Metrics

The suite reports:

- total scenarios;
- verified, failed, partial, and unverified counts;
- claimed completion count;
- false-completion count and rate;
- independently verified completion count;
- silent independently verified completion count;
- source-report/observation agreement count;
- source false-positive count;
- source false-negative count;
- security rejection count;
- per-scenario status and observation summary.

These metrics describe deterministic sandbox scenarios, not model performance.

## CLI

```bash
completion-verifier-sandbox \
  --output sandbox_runs/reference-v1 \
  --scenario all
```

Optional single-scenario runs use `--scenario <id>`. A dry run prints the resolved scenario list and contract digest without creating files.

The command prints machine-readable JSON containing the output path, scenario count, manifest status, and headline metrics.

## Testing

At least 24 tests cover:

- contract validation and deterministic digest;
- safe nested write and observation;
- absolute path and traversal rejection;
- symlinked parent and final symlink rejection;
- exact success;
- false success detection;
- partial write detection;
- timeout before and after write;
- rollback detection;
- no external file creation in traversal/symlink scenarios;
- source evidence exclusion from canonical evidence;
- silent verified completion;
- artifact separation;
- no-overwrite behavior;
- deterministic metrics and output;
- manifest verification and tamper detection;
- CLI dry run, single scenario, and full suite;
- editable and clean-wheel execution.

All existing 94 tests remain green. GitHub Actions continues across Python 3.10–3.13.

## Documentation and claims

The public documentation must say:

- observations are independent from the source report within the local process;
- this is stronger than trusting a receipt but weaker than OS-level adversarial isolation;
- the sandbox has no network and never intentionally touches paths outside its temporary root;
- deterministic scenario results are not external-model results;
- future real-agent runners must be restricted to this sandbox and must retain prompt, model, tool, cost, and timing metadata separately.

## Out of scope

- shell command execution;
- arbitrary Python execution supplied by an agent;
- network access;
- live email, calendar, repository, payment, or cloud mutations;
- Windows-specific filesystem semantics;
- hostile concurrent filesystem races;
- production authorization, identity, attestation, or remote-state proof;
- claims about any external AI model.
