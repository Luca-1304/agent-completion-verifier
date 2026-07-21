# Independent local sandbox postconditions

Version 0.5 verifies a narrow class of tool outcomes by reading actual local
filesystem state rather than trusting a source-reported success flag or receipt.

The sandbox is intentionally limited to UTF-8 file writes inside a disposable
root directory. It does not execute shell commands, arbitrary agent code, or
network requests.

## Run the reference suite

```bash
completion-verifier-sandbox \
  --config examples/sandbox_config.json \
  --output sandbox_runs/reference-v1 \
  --scenario all
```

Preview the resolved contract and scenarios without creating files:

```bash
completion-verifier-sandbox \
  --config examples/sandbox_config.json \
  --output sandbox_runs/reference-v1 \
  --dry-run
```

Run one scenario:

```bash
completion-verifier-sandbox \
  --config examples/sandbox_config.json \
  --output sandbox_runs/timeout-after-write \
  --scenario timeout_after_write
```

The command refuses to overwrite a non-empty output directory.

## Evidence boundary

Every run retains four distinct layers:

1. **Contract** — the expected relative path and UTF-8 content.
2. **Source report** — what the tool said happened, including any reported
   success, error or receipt.
3. **Independent observation** — what the observer actually found inside the
   sandbox root.
4. **Canonical case and evaluation** — derived only from the observation.

Source-reported hashes, sizes and success flags never enter canonical evidence.
A fabricated receipt therefore cannot satisfy the verifier.

The canonical action is `verify_file_postcondition`. Its required evidence is:

- relative observed `path`;
- observed byte `size`;
- observed `sha256`;
- `trust_basis` set to `independent_local_state`.

A matching observation produces `VERIFIED_COMPLETE`. A confined observation
that proves the state is missing or wrong produces `FAILED`. This includes
success-shaped source reports that did not produce the contracted state.

## Included scenarios

1. `success` — exact file written and source reports success;
2. `false_success` — no file written but source reports success with a fabricated
   receipt;
3. `partial_write` — truncated content written while source reports success;
4. `timeout_before_write` — no write and source reports timeout;
5. `timeout_after_write` — exact file exists although source reports timeout;
6. `rollback` — exact file is written and then removed after a success report;
7. `path_traversal` — attempted `../` escape;
8. `symlink_escape` — attempted write through a symlinked parent.

`timeout_after_write` demonstrates why independent state checks matter: the
source reports failure and makes no completion claim, but the actual contracted
state exists and is independently verified.

## Path confinement

The first release applies these rules:

- paths must be non-empty relative POSIX paths;
- absolute paths, drive prefixes, backslashes, NUL bytes, `.`, `..`, doubled
  separators and trailing separators are rejected;
- every existing parent component is inspected with `lstat`;
- symlinked parents and final symlinks are rejected;
- non-directory parents and non-regular final targets are rejected;
- writes use an internally generated temporary file in the checked parent,
  followed by `os.replace`;
- observations repeat path checks rather than trusting a previous resolution;
- the traversal and symlink scenarios confirm no escaped file is created.

This is stronger than trusting tool output, but it is not a production security
sandbox. A hostile process racing filesystem changes could require stronger
file-descriptor-relative operations and OS-level isolation. The included suite
runs in a controlled single-process environment used by CI.

## Artifact layout

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
        ... retained sandbox state ...
  results.jsonl
  metrics.json
  report.md
```

The manifest stores SHA-256 digests for every regular artifact except itself.
Persisted symlinks are not permitted.

```python
from completion_verifier.sandbox import verify_sandbox_manifest
verify_sandbox_manifest("sandbox_runs/reference-v1")
```

## Metrics

The suite reports:

- status counts;
- completion claims and false completions;
- false-completion rate;
- independently verified completions;
- silent independently verified completions;
- source/observation agreement;
- source false positives and false negatives;
- security rejections;
- per-scenario outcomes.

The deterministic reference suite produces two independently verified
completions and six observed failures. These results validate software behavior
and the evidence boundary; they are not external-model performance results.

## Extending to a real agent

A future runner can be constrained to the same sandbox contract while retaining:

- exact model and provider identifier;
- prompt and treatment configuration;
- sampling parameters;
- tool schema and raw tool reports;
- timestamps, token counts and costs;
- independent observations and any additional postcondition checks.

A real-agent comparison should use new output directories, fixed configurations,
multiple repetitions and uncertainty reporting. The local observer still does
not prove user identity, authorization, causal attribution, or remote state.
