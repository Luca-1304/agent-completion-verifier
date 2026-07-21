# Real Agent Trace Adapters — Design

Date: 2026-07-21
Issue: #4 — Add adapters for real agent tool traces

## Purpose

Convert external tool-use traces into the verifier's canonical `Case`, `Requirement`, and `Event` models without treating transformation as independent proof. The adapter layer must preserve ordering and source references, reject ambiguous mappings, and keep raw trace data separate from derived evaluation cases.

## Approaches considered

### 1. Loose field-mapping importer

Accept a configurable dictionary of source-field names and map them directly into `Case` objects.

- Advantage: quick to support arbitrary JSON.
- Risk: easy to make lossy or misleading mappings; difficult to audit; configuration errors can silently change meaning.

### 2. Provider-specific adapters only

Implement one adapter per provider or agent framework.

- Advantage: source semantics can be handled precisely.
- Risk: duplicated validation logic and no stable cross-provider contract.

### 3. Strict canonical trace envelope with provider translators — selected

Define one small, validated intermediate trace schema. Generic JSON and provider-specific translators must produce this envelope before it is converted into verifier models.

- Advantage: one auditable conversion boundary, deterministic behavior, clear provenance, and reusable provider integration.
- Cost: slightly more structure upfront.

## Architecture

### `TraceEnvelope`

A validated representation of one agent run:

- `trace_id`: stable, non-empty identifier.
- `task`: original task text.
- `completion_claimed`: explicit boolean supplied by the trace producer or caller.
- `requirements`: canonical action/evidence contracts supplied independently of tool results.
- `events`: ordered tool events.
- `source`: provenance metadata describing the trace origin.

The envelope is not considered trusted evidence by itself. It records what the source trace reported.

### `TraceSource`

Provenance metadata:

- `adapter`: adapter identifier and version.
- `source_type`: generic JSON, OpenAI-style tool trace, or future provider type.
- `source_ref`: non-empty local path, run ID, URI, or other stable reference.
- `raw_sha256`: SHA-256 digest of the canonicalised raw input bytes.

The digest allows users to establish which raw trace produced a derived case without storing raw private content inside the `Case` model.

### Adapter protocol

A small protocol exposes:

```python
class TraceAdapter(Protocol):
    name: str
    version: str

    def adapt(self, raw: object, *, requirements: Sequence[Requirement], source_ref: str) -> TraceEnvelope:
        ...
```

Adapters must not infer missing requirements or fabricate evidence. Requirements are passed separately because they represent the task's acceptance contract, not the agent's self-report.

### Generic JSON adapter

Accepts a documented source object containing:

- `trace_id`
- `task`
- `completion_claimed`
- ordered `events`

Each event must contain:

- `action`
- explicit boolean `success`
- object-valued `evidence`
- optional `source_event_id`

Unknown top-level fields may be retained in raw input but are not silently converted. Unknown event actions are allowed only when they do not collide with or pretend to satisfy a requirement; the evaluator naturally ignores unrelated actions. Empty or malformed event actions, non-boolean success values, non-object evidence, and duplicate source event IDs are rejected.

### OpenAI-style tool trace translator

A dependency-free example translator supports a public, simplified function/tool-call trace shape rather than private API objects. It pairs tool-call records with tool-result records using `tool_call_id`.

It rejects:

- results with no matching call;
- calls with no result;
- duplicate call or result IDs;
- success values that are absent or non-boolean;
- ambiguous action names;
- evidence that is not an object.

The paired result becomes one canonical event. Call order determines sequence. Tool-call arguments may be included in provenance metadata but do not count as completion evidence unless explicitly copied into the result evidence by the trace producer.

### Conversion to `Case`

`TraceEnvelope.to_case()` constructs the existing immutable `Case` model. It does not modify evaluator behavior. Provenance is available on the envelope and through serialisation helpers, rather than being inserted into `Event.evidence`, because provenance must not accidentally satisfy task evidence requirements.

## Data flow

1. Read raw trace bytes or an already parsed object.
2. Compute a deterministic SHA-256 digest from canonical JSON encoding.
3. Validate source-specific structure.
4. Produce a `TraceEnvelope` with explicit provenance.
5. Convert the envelope into an existing `Case`.
6. Evaluate and calculate metrics using the unchanged verifier core.
7. Save raw trace, derived envelope, case, and evaluation as separate artifacts when running experiments.

## Error handling

Adapters fail closed with `TraceAdapterError`, including a field path or event identifier where possible. There is no permissive mode in the first release.

Errors include:

- missing or empty identifiers;
- malformed task or completion claim;
- missing source reference;
- duplicate source event/tool-call IDs;
- unmatched calls and results;
- unsupported record types;
- invalid success or evidence fields;
- requirements missing or malformed.

## CLI scope

Add a separate subcommand-style entry point rather than overloading the existing case evaluator:

```bash
completion-verifier-adapt generic trace.json requirements.json --source-ref run-123
completion-verifier-adapt openai trace.json requirements.json --source-ref run-123
```

The command emits one canonical case JSON object by default and an envelope including provenance with `--envelope`. It never overwrites files; shell redirection or an explicit future output option can be added later.

## Testing

At least 14 adapter tests will cover:

- generic success;
- timeout failure;
- permission failure;
- successful retry;
- later rollback/failure;
- missing receipt/evidence;
- unrelated/unknown tool action;
- deterministic digest and output;
- malformed success value;
- duplicate source event IDs;
- matched OpenAI-style call/result;
- unmatched call;
- unmatched result;
- duplicate call/result IDs;
- provenance not satisfying evidence requirements;
- CLI conversion output.

All existing 44 tests remain green. CI continues to test Python 3.10–3.13, editable install, wheel build, clean-wheel installation, release verification, both evaluator CLI paths, and the new adapter CLI.

## Documentation and limitations

Documentation must explicitly distinguish:

- transformed source-reported evidence;
- independently verified external state;
- raw trace retention;
- derived canonical cases and metrics.

The adapter release does not claim that a tool result is truthful, causally linked, authorised, or tamper-proof. It only makes conversion deterministic, inspectable, and provenance-linked.

## Out of scope

- direct network calls to provider APIs;
- authentication or secret handling;
- automatic inference of acceptance requirements;
- independent postcondition checks;
- private SDK dependencies;
- provider-specific streaming internals beyond the documented example shape.
