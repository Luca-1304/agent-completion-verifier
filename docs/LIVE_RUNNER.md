<!-- R1 post-merge hardening verification trigger: comment-only; documentation semantics unchanged. -->
# Optional OpenAI Responses sandbox runner

Version 0.6 adds an optional bridge from the deterministic verifier to a real OpenAI Responses API model operating under the existing confined file-write contract.

The model is not trusted to declare its own success. Completion is evaluated from an independent read of the final local sandbox state.

## Safety boundary

A live request is impossible unless all of these are present:

- an explicit `--model` value;
- `--confirm-live`;
- `OPENAI_API_KEY` in the process environment;
- an empty output directory;
- a valid relative-path file contract.

The runner:

- sends `store: false` on every request;
- disables SDK retries;
- exposes exactly one strict function, `write_file`;
- validates the path and content for exact equality before writing;
- disables parallel tool calls;
- bounds tool rounds and output tokens;
- provides no shell, code execution, web, MCP, file-search or remote-mutation tools;
- stores no API key or authorization header;
- never makes a live call from tests or GitHub Actions.

The optional SDK dependency is loaded only for a confirmed live run:

```bash
python -m pip install --editable '.[openai]'
```

## Preview without a key or SDK

```bash
completion-verifier-live openai \
  --config examples/openai_live_config.json \
  --output live_runs/openai-example \
  --model <explicit-model-id> \
  --dry-run
```

The preview prints the exact redacted request shape, tool schema, configuration digest and maximum number of API requests. It performs no write and creates no output directory.

## Confirmed live run

```bash
export OPENAI_API_KEY='<set securely outside the repository>'
completion-verifier-live openai \
  --config examples/openai_live_config.json \
  --output live_runs/openai-example \
  --model <explicit-model-id> \
  --confirm-live
```

One command performs one bounded run. There is no default model and no automatic retry.

## Replay without another API call

```bash
completion-verifier-live replay --input live_runs/openai-example
```

Replay verifies every artifact digest and re-evaluates the stored canonical case. It performs no API call and does not execute the tool again.

## Artifact boundary

Each run keeps these records separate:

- configuration;
- requests;
- responses;
- function calls;
- tool outputs;
- source report;
- independent observation;
- canonical case;
- evaluation;
- exact API usage;
- report and SHA-256 manifest.

The model completion claim is source data only. It cannot override an independent observation showing that the contracted file is absent, altered or outside the sandbox.

## Data handling

The task, contract content and model output are retained locally for reproducibility. Do not place secrets or unnecessary personal data in the configuration. `live_runs/` is ignored by Git, but local run directories should still be treated as potentially sensitive.

A single live run is not representative model-performance evidence. Any comparison requires fixed configurations, repeated runs, exact model identifiers, dates, usage records and uncertainty reporting.
