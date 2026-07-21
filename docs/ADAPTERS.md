# Real trace adapters

Version 0.3 adds a strict conversion layer for external agent tool traces. The
layer makes trace transformation deterministic and provenance-linked; it does
**not** independently prove that a tool result is truthful or that external
state changed.

## Trust boundary

Keep these artifacts separate in experiments:

1. the raw source trace;
2. the requirements or acceptance contract;
3. the derived `TraceEnvelope`;
4. the canonical verifier `Case`;
5. the resulting evaluation and aggregate metrics.

The adapter copies source-reported `success` and `evidence` values into a
canonical event. It does not verify identity, authorisation, causality,
freshness, tamper resistance, or the current state of the external system.

Provenance fields are intentionally stored on the envelope rather than inside
`Event.evidence`, so a source ID or digest cannot accidentally satisfy a task
requirement.

## Requirements file

Requirements are supplied independently because the task's acceptance contract
must not be inferred from the agent's own result.

```json
[
  {
    "action": "send_email",
    "evidence_fields": ["message_id", "recipient"]
  }
]
```

The file must be a non-empty JSON array accepted by `Requirement.from_dict`.

## Generic JSON trace

```json
{
  "trace_id": "generic-email-retry",
  "task": "Send the customer update email.",
  "completion_claimed": true,
  "events": [
    {
      "source_event_id": "event-1",
      "action": "send_email",
      "success": false,
      "evidence": {"error": "timeout"}
    },
    {
      "source_event_id": "event-2",
      "action": "send_email",
      "success": true,
      "evidence": {
        "message_id": "msg-102",
        "recipient": "customer@example.com"
      }
    }
  ]
}
```

Rules:

- `trace_id`, `task`, and every `action` must be non-empty strings;
- `completion_claimed` and every `success` value must be booleans;
- `events` must be an ordered array;
- `evidence` must be an object;
- supplied `source_event_id` values must be non-empty and unique;
- unrelated action names are retained but do not satisfy other requirements;
- malformed or ambiguous records are rejected rather than guessed.

Convert to a canonical case:

```bash
completion-verifier-adapt generic \
  examples/generic_trace.json \
  examples/requirements.json \
  --source-ref run-2026-07-21
```

Emit the full provenance envelope:

```bash
completion-verifier-adapt generic \
  examples/generic_trace.json \
  examples/requirements.json \
  --source-ref run-2026-07-21 \
  --envelope
```

## Simplified OpenAI-style tool trace

This format is a dependency-free public example. It is not a promise to accept
private SDK classes or every historical API response shape.

```json
{
  "trace_id": "openai-style-email",
  "task": "Send the customer update email.",
  "completion_claimed": true,
  "records": [
    {
      "type": "tool_call",
      "tool_call_id": "call-1",
      "name": "send_email",
      "arguments": {"recipient": "customer@example.com"}
    },
    {
      "type": "tool_result",
      "tool_call_id": "call-1",
      "success": true,
      "evidence": {
        "message_id": "msg-103",
        "recipient": "customer@example.com"
      }
    }
  ]
}
```

The adapter pairs calls and results by `tool_call_id` and emits events in call
order, even when results arrive in another order. It rejects:

- duplicate call IDs;
- duplicate result IDs;
- calls without results;
- results without calls;
- unsupported record types;
- non-object arguments or evidence;
- absent or non-boolean success values.

Tool-call arguments are context only. They are not copied into evidence because
requesting an action is not proof that it completed.

```bash
completion-verifier-adapt openai \
  examples/openai_tool_trace.json \
  examples/requirements.json \
  --source-ref response-123
```

## Provenance envelope

An envelope includes:

- `source.adapter`: adapter name and schema version;
- `source.source_type`: source trace family;
- `source.source_ref`: caller-supplied stable trace reference;
- `source.raw_sha256`: SHA-256 of the parsed trace's canonical JSON encoding;
- each adapted event's optional `source_event_id`.

Canonical JSON is encoded with sorted keys, compact separators, UTF-8, and no
NaN values. Semantically equivalent JSON objects therefore produce the same
digest even if key order or whitespace differs.

The digest links a derived envelope to a source object. It is not a signature
and does not establish who created the trace.

## Raw trace retention

For reproducible research, retain the original trace bytes in a restricted
artifact store and record their path or run ID as `source_ref`. Do not place
secrets, customer data, private prompts, or authentication material into a
public benchmark repository.

## Out of scope

- direct network calls to model or tool providers;
- API keys, OAuth, session cookies, or other secret handling;
- automatic inference of requirements;
- independent postcondition checks;
- verification of identity, authorisation or causality;
- private provider SDK dependencies;
- permissive conversion of unknown record shapes.
