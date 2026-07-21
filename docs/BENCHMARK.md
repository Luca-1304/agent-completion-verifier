# Controlled failure-injection benchmark

Version 0.4 adds a reproducible experiment harness for testing completion claims
under controlled tool failures.

The included results use deterministic **scripted reference policies**. They
validate the benchmark method, artifact pipeline, metrics and verifier behavior.
They are not measurements of OpenAI, Anthropic, local models or any other AI
system.

## Run the reference experiment

```bash
completion-verifier-benchmark \
  --config examples/benchmark_config.json \
  --output benchmark_runs/reference-v1
```

Preview the deterministic run matrix without writing files:

```bash
completion-verifier-benchmark \
  --config examples/benchmark_config.json \
  --output benchmark_runs/reference-v1 \
  --dry-run
```

The command refuses to overwrite a non-empty output directory.

## Included groups

- `baseline`: claims completion after the first attempt, even if the attempt
  failed or lacks required evidence;
- `evidence_contract`: retries an explicitly retryable failure once and only
  claims completion when the required evidence exists;
- `verifier_feedback`: also retries a success-shaped result when verifier checks
  show that required evidence is missing.

These are fixed reference behaviors, not prompts claimed to represent model
behavior.

## Included scenarios

1. `success` — immediate evidenced success;
2. `timeout` — retryable timeout followed by success;
3. `permission_denied` — terminal permission failure;
4. `partial_write` — success-shaped partial result missing required evidence;
5. `stale_read` — stale success-shaped result followed by a current receipt;
6. `malformed_success` — apparent success without contract evidence;
7. `tool_exception` — terminal tool exception;
8. `rollback` — evidenced success followed by rollback.

The scenario schedule is fixed before a run. The injector does not change a
failure based on what a runner says.

## Configuration

A configuration records:

- stable experiment ID;
- integer seed;
- positive repetition count;
- ordered groups and scenarios;
- task text;
- exactly one independent requirement contract in the first release;
- source-controlled `generated_at` value.

Run IDs and per-run seeds derive from SHA-256 over the configuration identity.
No wall-clock timestamp affects scientific output.

## Artifact layout

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

Raw runner output, provenance-linked envelopes, canonical verifier cases,
evaluations and aggregate metrics remain separate. This prevents transformation
metadata from being mistaken for task evidence.

`manifest.json` stores SHA-256 digests for every other artifact. Use:

```python
from completion_verifier.benchmark import verify_manifest
verify_manifest("benchmark_runs/reference-v1")
```

## Metrics

The harness retains the existing false-completion and claim-precision metrics
and adds:

- injected-failure runs;
- recovered injected-failure runs;
- recovery rate conditioned on injected failure;
- unnecessary retry count and rate;
- explicit refusal count and rate;
- per-group summaries;
- per-scenario status and recovery summaries;
- timing and token means only when every relevant run supplies real values.

The scripted runner leaves time and token fields as `null`; the harness does not
invent performance overhead.

## Reproducibility

With the same configuration and runner version, separate runs produce
byte-identical scientific JSON, JSONL and Markdown artifacts. Output-directory
paths are not written into scientific artifacts. The manifest can detect later
tampering or accidental modification.

## Adding a real runner

A future model runner must implement the provider-neutral `ExperimentRunner`
protocol and retain:

- exact model identifier and provider;
- prompt and treatment configuration versions;
- sampling parameters;
- tool schemas;
- raw tool-call and tool-result traces;
- run date;
- token counts and costs when available;
- errors, retries and refusals;
- any external postcondition checks.

Real runs should be written to a new output directory and compared only when the
methodology and configurations are held constant.

## Trust boundary

The harness controls the injected result schedule and evaluates the resulting
trace. It still does not establish that source-reported evidence is authentic,
authorised, causally linked to the agent, or the latest external state. Stronger
production evidence requires independent reads, signed receipts, identity and
authorisation checks, and temporal rollback detection.
