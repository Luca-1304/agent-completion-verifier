# Controlled Failure-Injection Benchmark — Design

Date: 2026-07-21
Issue: #5 — Build controlled failure-injection benchmark

## Purpose

Create a reproducible experiment harness that runs equivalent tool-use tasks under controlled failures, retains raw and derived artifacts separately, and measures whether an agent or policy reports completion accurately, recovers, retries unnecessarily, or regresses.

The first release must be runnable without network access or paid model calls. It will include a deterministic reference runner for validating methodology and plumbing, while exposing a protocol that future real-model runners can implement. Reference-runner results must never be described as external-model benchmark results.

## Approaches considered

### 1. Scripted simulator only

Hard-code three policies and report their outcomes.

- Advantage: quick and reproducible.
- Risk: looks like a toy benchmark and creates no clean path to real agent runs.

### 2. Abstract experiment harness only

Define interfaces and artifact formats but provide no runnable experiment.

- Advantage: clean architecture.
- Risk: difficult to verify end-to-end and weak as a public demonstration.

### 3. Pluggable harness plus deterministic reference runner — selected

Build a provider-neutral experiment protocol, a fixed failure injector, an artifact writer, and a deterministic scripted runner implementing the same protocol.

- Advantage: end-to-end reproducibility now, honest limitations, and a direct extension point for future OpenAI, Anthropic, local-model, or custom-agent runners.
- Cost: more code and explicit separation between harness validation and model evaluation.

## Core architecture

### Experiment configuration

`ExperimentConfig` is serialisable and immutable. It contains:

- `experiment_id`: stable non-empty identifier;
- `seed`: integer random seed;
- `repetitions`: positive integer;
- `groups`: ordered experiment groups;
- `scenarios`: ordered failure scenarios;
- `output_dir`: supplied by the CLI rather than embedded into the scientific configuration;
- `schema_version`: fixed version string.

The canonical configuration digest is stored with every run artifact.

### Experiment groups

The first release defines:

- `baseline`;
- `evidence_contract`;
- `verifier_feedback`.

These are treatment labels, not claims about prompt effectiveness. A real-model runner is responsible for mapping each label to an explicit prompt or agent configuration and retaining that configuration.

### Failure scenarios

Each `FailureScenario` defines one required action and an ordered tool-result schedule. Included scenarios:

1. `success` — immediate evidenced success;
2. `timeout` — timeout failure, then optional retry success;
3. `permission_denied` — terminal permission failure;
4. `partial_write` — success-shaped result missing required evidence;
5. `stale_read` — first receipt is stale or incomplete, later read can verify state;
6. `malformed_success` — success-shaped response with invalid evidence structure;
7. `tool_exception` — explicit tool exception failure;
8. `rollback` — evidenced success followed by failure/rollback.

Scenario definitions are deterministic data. The injector never silently changes a scenario based on model output.

### Runner protocol

```python
class ExperimentRunner(Protocol):
    name: str
    version: str

    def run(self, request: RunRequest) -> RawRunTrace:
        ...
```

`RunRequest` includes experiment ID, run ID, group, scenario, repetition index, seed, task, requirements, and the scenario's controlled tool schedule.

`RawRunTrace` records:

- explicit completion claim;
- ordered tool events;
- retry and refusal counts;
- elapsed milliseconds;
- input and output token counts when known;
- runner metadata;
- treatment configuration reference;
- source-reported raw records.

Unknown token or timing values are represented as `null`, not guessed.

### Deterministic reference runner

The reference runner validates the harness. It uses fixed, documented behavior:

- `baseline`: claims completion after the first tool attempt, even when evidence is insufficient;
- `evidence_contract`: retries retryable failures once and claims completion only when required evidence exists;
- `verifier_feedback`: behaves like evidence contract and performs one verifier-guided retry when the first apparent success lacks required evidence.

Terminal permission failures and tool exceptions are not retried. Rollback is retained as the latest event and therefore produces failure even if completion was claimed earlier.

The runner must be labelled `scripted-reference`, and reports must state that results measure the scripted policies, not AI models.

## Artifact layout

Each experiment writes into a new directory and refuses to overwrite an existing non-empty directory.

```text
<output>/
  config.json
  manifest.json
  raw_traces/
    <run_id>.json
  envelopes/
    <run_id>.json
  cases.jsonl
  evaluations.jsonl
  runs.jsonl
  metrics.json
  report.md
```

- `raw_traces/`: exact runner output before adaptation;
- `envelopes/`: provenance-linked adapter output;
- `cases.jsonl`: canonical cases only;
- `evaluations.jsonl`: verifier results;
- `runs.jsonl`: run metadata and experimental measurements;
- `metrics.json`: aggregate verifier metrics plus experiment-specific metrics;
- `report.md`: human-readable methodology, counts, caveats, and reproducibility commands.

All JSON is emitted deterministically with sorted keys. The manifest stores SHA-256 digests for every artifact except itself, then stores its own schema and creation metadata.

## Metrics

Existing verifier metrics remain unchanged. The experiment layer adds:

- `injected_failure_runs`;
- `recovered_failure_runs`;
- `recovery_rate_given_injected_failure`;
- `unnecessary_retry_runs`;
- `unnecessary_retry_rate`;
- `refusal_runs`;
- `refusal_rate`;
- `mean_elapsed_ms` when all relevant values are known;
- `mean_input_tokens` and `mean_output_tokens` when all values are known;
- per-group status, claim-quality, recovery, retry, refusal, time, and token summaries;
- per-scenario status and recovery summaries.

A retry is unnecessary only when the immediately preceding tool event was already an evidenced success for the required action. A refusal is explicit runner metadata, not inferred from missing events.

## CLI

```bash
completion-verifier-benchmark \
  --config examples/benchmark_config.json \
  --output benchmark_runs/reference-v1 \
  --runner scripted-reference
```

The command:

1. validates configuration;
2. refuses unsafe overwrite;
3. runs every group × scenario × repetition combination;
4. writes all artifacts;
5. prints the output path and headline metrics;
6. exits non-zero on incomplete artifacts or verification mismatch.

A `--dry-run` option prints the resolved run matrix without executing it.

## Reproducibility

- run IDs derive deterministically from experiment ID, group, scenario, repetition, and seed;
- scenario ordering and group ordering are preserved from config;
- per-run seeds derive from the experiment seed using SHA-256, not process-global randomness;
- no current timestamp affects scientific output or run IDs;
- report generation uses a supplied or source-controlled `generated_at` value when a timestamp is needed;
- repeated runs in separate empty directories with the same config and runner produce byte-identical scientific JSON artifacts.

## Error handling

The harness fails closed for:

- duplicate group or scenario IDs;
- unknown treatment labels;
- empty scenario schedules;
- invalid evidence objects;
- inconsistent action names;
- unsupported runner names;
- non-positive repetitions;
- output directory overwrite attempts;
- missing raw, envelope, case, evaluation, or metric artifacts;
- digest mismatch during post-run verification.

## Testing

At minimum, tests cover:

- configuration validation and deterministic digest;
- deterministic run matrix and run IDs;
- all eight scenario schedules;
- behavior of all three scripted groups;
- timeout recovery;
- terminal permission and exception behavior;
- partial-write and malformed-success handling;
- rollback regression;
- unnecessary retry and refusal counting;
- per-group and per-scenario metrics;
- byte-identical repeated output excluding manifest self-digest;
- overwrite protection;
- artifact separation;
- manifest digest verification;
- CLI dry run and full run;
- installed wheel execution.

All existing 74 tests remain green. CI continues to run Python 3.10–3.13, editable and clean-wheel installations, evaluator and adapter commands, and adds the benchmark CLI with artifact verification.

## Documentation and claims

The public report must say:

- the included run uses deterministic scripted reference policies;
- it validates experiment methodology and software behavior;
- it is not evidence of external-model performance;
- future model comparisons require retained prompt/configuration versions, raw traces, model identifiers, sampling settings, dates, and costs;
- source-reported tool results are still not independent proof of external state.

## Out of scope

- paid or network model calls in CI;
- automatic secret handling;
- live email, calendar, file, payment, or repository mutations;
- claims about OpenAI, Anthropic, or any other model from scripted-reference results;
- statistical significance claims from the reference dataset;
- dashboard or web UI.
