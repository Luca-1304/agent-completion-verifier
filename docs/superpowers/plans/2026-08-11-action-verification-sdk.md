# Action Verification SDK Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a provider-free, privacy-minimal postcondition verification SDK with exact text-file, directory, and structured-JSON verifiers that feed the existing evaluator.

**Architecture:** Add `completion_verifier.postconditions` beside the proven v0.6 sandbox. Strict immutable contracts hold caller data in memory; read-only verifiers observe confined local state; public observations serialize only fixed labels, booleans, numeric counts, trust basis, and fixed reason codes. A closed registry dispatches built-ins and an adapter reuses `evaluate_case`.

**Tech Stack:** Python 3.10-3.13 standard library only: `dataclasses`, `pathlib`, `os`, `stat`, `json`, `hashlib`, existing evaluator/models, `unittest`.

## Global Constraints

- Existing v0.6 APIs, sandbox behaviour, CLIs, and optional OpenAI runner stay unchanged.
- No new dependency, network access, credentials, OAuth, environment-variable reads, action execution, retries, dynamic plugin loading, or monitoring.
- Public serialization emits no caller-controlled strings or digests: no paths, contract IDs, file/child names, JSON keys/values, expected/observed content, absolute roots, environment values, parser/OS messages, or content-derived digests.
- Tests/examples use synthetic sentinel values only.
- Unsafe/malformed inputs fail closed.
- `exact_empty=True` cannot coexist with required directory children.
- Existing evaluator is the only status engine.
- TDD: failing test commit first, verify the intended failure in CI, then minimal implementation commit.

---

### Task 1: Strict contracts and privacy-safe observation model

**Files:**
- Create `src/completion_verifier/postconditions/models.py`
- Create `src/completion_verifier/postconditions/__init__.py`
- Create `tests/test_postconditions.py`

**Interfaces:**

```python
TextFileContract(path: str, expected_text: str, contract_id: str = "postcondition", schema_version: str = "1")
DirectoryContract(path: str, required_children: tuple[str, ...] = (), exact_empty: bool = False, contract_id: str = "postcondition", schema_version: str = "1")
JsonObjectContract(path: str, expected: dict[str, object], exact_keys: bool = False, contract_id: str = "postcondition", schema_version: str = "1")
PostconditionObservation(kind: str, trusted: bool, matches: bool, evidence: dict[str, object], reason: str | None = None, trust_basis: str = "independent_local_state")
```

Each contract exposes `kind` and an internal `identity_digest` for exact reproducibility. The digest is not included by `to_public_dict()`. `PostconditionObservation.to_dict()` is privacy-safe by definition.

- [ ] Write failing tests for all three constructors, path validation, schema version rejection, contradictory directory requirements, deterministic internal digest, and public serialization leaks.

```python
def test_public_contract_view_contains_no_caller_strings(self) -> None:
    contract = TextFileContract(
        "PRIVATE_PATH/result.txt",
        "PRIVATE_EXPECTED_TEXT",
        contract_id="PRIVATE_CONTRACT_ID",
    )
    public = json.dumps(contract.to_public_dict(), sort_keys=True)
    for secret in ("PRIVATE_PATH", "PRIVATE_EXPECTED_TEXT", "PRIVATE_CONTRACT_ID"):
        self.assertNotIn(secret, public)
    self.assertNotIn(contract.identity_digest, public)
```

- [ ] Run `python -m unittest tests.test_postconditions.ContractTests -v`; expect import failure because the package does not exist.
- [ ] Implement strict dataclasses and shared portable relative-path validation. Reject `/`, drive prefixes, backslashes, empty/dot/parent components, unknown schema, duplicate/invalid child names, empty JSON keys, and contradictory directory options. Compute internal digests with canonical JSON/hash helpers but never serialize them publicly.
- [ ] Re-run ContractTests; expect PASS.
- [ ] Commit `feat: add strict postcondition contracts`.

---

### Task 2: Confined filesystem reader and exact text verifier

**Files:**
- Create `src/completion_verifier/postconditions/filesystem.py`
- Create `src/completion_verifier/postconditions/text_file.py`
- Modify `src/completion_verifier/postconditions/__init__.py`
- Modify `tests/test_postconditions.py`

**Interfaces:**

```python
ObservationRoot(root: Path)
ObservationRoot.target(relative: str) -> Path
TextFileVerifier.verify(contract: TextFileContract, root: Path) -> PostconditionObservation
```

Text evidence is limited to `exists`, `regular_file`, `size_matches`, `content_matches`.

- [ ] Add failing tests for exact UTF-8 success, missing file, mismatch, wrong type, root/parent/final symlink, traversal, and privacy.

```python
def test_text_observation_exposes_no_path_or_content(self) -> None:
    with tempfile.TemporaryDirectory(prefix="PRIVATE_ROOT_SENTINEL-") as directory:
        root = Path(directory)
        (root / "PRIVATE_FILE_NAME.txt").write_text("PRIVATE_OBSERVED_TEXT")
        obs = TextFileVerifier().verify(
            TextFileContract("PRIVATE_FILE_NAME.txt", "PRIVATE_OBSERVED_TEXT", "PRIVATE_ID"), root
        )
        public = json.dumps(obs.to_dict(), sort_keys=True)
        for secret in (str(root), "PRIVATE_FILE_NAME", "PRIVATE_OBSERVED_TEXT", "PRIVATE_ID"):
            self.assertNotIn(secret, public)
```

- [ ] Run `python -m unittest tests.test_postconditions.TextFileVerifierTests -v`; expect missing verifier failure.
- [ ] Implement read-only traversal with `os.lstat`/`stat` for each existing component. Reject symlinks before reading. Use fixed reasons only: `missing`, `unsafe_path`, `wrong_type`, `io_error`. Never `str(exc)`.
- [ ] Run TextFileVerifierTests and `python -m unittest tests.test_sandbox -v`; expect PASS.
- [ ] Commit `feat: verify exact local text postconditions`.

---

### Task 3: Directory-state verifier

**Files:**
- Create `src/completion_verifier/postconditions/directory.py`
- Modify `src/completion_verifier/postconditions/__init__.py`
- Modify `tests/test_postconditions.py`

**Interface:**

```python
DirectoryVerifier.verify(contract: DirectoryContract, root: Path) -> PostconditionObservation
```

Evidence: `exists`, `directory`, `required_children_present`, and optional `empty`. No names are serialized.

- [ ] Add failing tests: success, missing, wrong type, required children all/some, exact-empty success/failure, symlink rejection, undeclared and declared child-name privacy.
- [ ] Run `python -m unittest tests.test_postconditions.DirectoryVerifierTests -v`; expect missing verifier failure.
- [ ] Implement using `ObservationRoot`. `os.scandir` may compare names in memory; public evidence receives only aggregate booleans/counts. For emptiness, stop on first entry.
- [ ] Re-run DirectoryVerifierTests; expect PASS.
- [ ] Commit `feat: verify local directory postconditions`.

---

### Task 4: Strict structured-JSON verifier

**Files:**
- Create `src/completion_verifier/postconditions/json_object.py`
- Modify `src/completion_verifier/postconditions/__init__.py`
- Modify `tests/test_postconditions.py`

**Interface:**

```python
JsonObjectVerifier.verify(contract: JsonObjectContract, root: Path) -> PostconditionObservation
```

Evidence: `exists`, `regular_file`, `valid_utf8`, `valid_json`, `top_level_object`, `expected_keys_present`, `expected_values_match`, optional `key_count_matches`. No raw keys/values are serialized.

- [ ] Add failing tests for success, value mismatch, missing key, extra key allowed/non-allowed modes, malformed UTF-8, malformed JSON, duplicate keys, non-object top level, symlink, and key/value privacy.

```python
def test_duplicate_json_does_not_echo_content(self) -> None:
    raw = '{"PRIVATE_KEY":"PRIVATE_A","PRIVATE_KEY":"PRIVATE_B"}'
    # Write raw to a temporary synthetic file, verify it, then assert PRIVATE_KEY,
    # PRIVATE_A and PRIVATE_B are absent from json.dumps(observation.to_dict()).
```

- [ ] Run `python -m unittest tests.test_postconditions.JsonObjectVerifierTests -v`; expect missing verifier failure.
- [ ] Implement strict UTF-8 decode and `json.loads(..., object_pairs_hook=...)` duplicate-key rejection. Compare declared keys/values only in memory. Fixed reasons: `invalid_utf8`, `invalid_json`, `duplicate_key`, `wrong_top_level`, plus filesystem reasons.
- [ ] Re-run JsonObjectVerifierTests; expect PASS.
- [ ] Commit `feat: verify strict JSON postconditions`.

---

### Task 5: Closed registry and existing-evaluator integration

**Files:**
- Create `src/completion_verifier/postconditions/registry.py`
- Create `src/completion_verifier/postconditions/evaluation.py`
- Modify `src/completion_verifier/postconditions/__init__.py`
- Modify `src/completion_verifier/__init__.py`
- Modify `tests/test_postconditions.py`

**Interfaces:**

```python
verify_postcondition(contract, root: Path) -> PostconditionObservation
postcondition_case(contract, observation, *, completion_claimed: bool = True) -> Case
evaluate_postcondition(contract, root: Path, *, completion_claimed: bool = True) -> Evaluation
```

Registry mapping is private/closed: `text_file`, `directory`, `json_object`. No registration API.

- [ ] Add failing tests that all built-ins dispatch, an unknown/artificial kind is rejected, match -> `VERIFIED_COMPLETE`, mismatch -> `FAILED`, and evaluator evidence contains only static action/kind labels, trust basis, booleans/counts/reason code.
- [ ] Run `python -m unittest tests.test_postconditions.RegistryAndEvaluationTests -v`; expect missing registry/evaluation functions.
- [ ] Implement registry and adapter. Canonical action string is `verify_postcondition:{kind}`. Construct `Requirement`, `Event`, `Case`; call existing `evaluate_case`; do not copy status logic.
- [ ] Run RegistryAndEvaluationTests and `python -m unittest discover -s tests -v`; expect PASS.
- [ ] Commit `feat: expose generic postcondition verification API`.

---

### Task 6: v0.7 release/docs/privacy gate

**Files:**
- Create `docs/POSTCONDITIONS.md`
- Modify `README.md`
- Modify `docs/RESEARCH_ROADMAP.md`
- Modify `pyproject.toml`
- Modify `src/completion_verifier/__init__.py`
- Modify `scripts/verify_release.py`
- Modify `tests/test_postconditions.py`

**Release identity:** `0.7.0` in `pyproject.toml` and `completion_verifier.__version__`.

- [ ] Add failing tests/release assertions for version consistency and representative privacy-safe public output from all three verifier kinds.
- [ ] Run `python -m unittest tests.test_postconditions -v`; expect version/release expectation failure.
- [ ] Update version and docs. Examples use synthetic paths/values only. Document that internal contract data/digests may be sensitive and that only public serializers are designed for disclosure.
- [ ] Extend `scripts/verify_release.py` with provider-free smoke verification for text/directory/JSON and assertions that public output excludes sentinel path, ID, file/child names, JSON keys/values, raw content, internal digest, and absolute temporary root.
- [ ] Run `python scripts/verify_release.py`; expect `Release verification passed.`
- [ ] Run normal CI Python 3.10-3.13 source/wheel matrix unchanged.
- [ ] Run manual 15-pass verification 15/15 on Python 3.10 and 3.13.
- [ ] Review exact diff for personal/secret values, `os.environ`/`getenv`, network/client imports, dynamic loading, new dependencies, public caller strings/digests, and v0.6 changes.
- [ ] Commit `release: prepare privacy-first action verification SDK v0.7.0`.

---

## Exact-head merge gate

Merge only when all are true:

1. exact PR head is the head that passed final verification;
2. branch is 0 commits behind `main`;
3. diff contains only planned SDK/tests/docs/release changes;
4. normal CI is green on exact head;
5. manual 15-pass gate is 15/15 on Python 3.10 and 3.13;
6. no unresolved review threads;
7. public evidence contains no caller-controlled identifiers/values, machine paths, or content-derived digests;
8. no new network, credential, execution, retry, monitoring, or dynamic-plugin capability;
9. merge through PR, never direct implementation push to `main`;
10. preserve feature branch after merge.
