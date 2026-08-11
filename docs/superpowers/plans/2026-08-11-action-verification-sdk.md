# Action Verification SDK Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a provider-free, privacy-minimal postcondition verification SDK with exact text-file, directory, and structured-JSON verifiers that feed the existing completion evaluator.

**Architecture:** Add a new `completion_verifier.postconditions` package beside the proven v0.6 sandbox. Contracts and observations are strict immutable dataclasses; filesystem access is confined and read-only; an explicit registry dispatches known verifier kinds; a small adapter converts an observation into the existing `Case`/`Event` model so `evaluate_case` remains authoritative.

**Tech Stack:** Python 3.10-3.13 standard library only, `dataclasses`, `pathlib`, `os.lstat`, `stat`, `json`, existing `canonical_json_sha256`, existing evaluator/models, `unittest`.

## Global Constraints

- Existing v0.6 APIs, sandbox behaviour, CLI commands, and optional OpenAI live runner remain unchanged.
- No new runtime dependency.
- No network access, credentials, OAuth, environment-variable reads, action execution, retry loop, dynamic plugin loading, or background monitoring.
- Public serialization never emits raw expected text/JSON values, raw observed contents, resolved absolute roots, home-directory/user names, environment values, or undeclared directory/JSON data.
- Tests/examples use synthetic identifiers only.
- Invalid schemas, unsafe paths, symlinks, malformed JSON, duplicate JSON keys, I/O failures, and unknown verifier kinds fail closed.
- `exact_empty=True` cannot coexist with required directory children.
- The existing evaluator remains the only completion-status engine.
- TDD is mandatory: each behaviour is introduced by a failing test, the failing state is verified, then the minimum production code is added.

---

### Task 1: Strict contracts and privacy-safe observations

**Files:**
- Create: `src/completion_verifier/postconditions/models.py`
- Create: `src/completion_verifier/postconditions/__init__.py`
- Create: `tests/test_postconditions.py`

**Interfaces:**
- Produces `TextFileContract(path: str, expected_text: str, contract_id: str = "postcondition", schema_version: str = "1")`.
- Produces `DirectoryContract(path: str, required_children: tuple[str, ...] = (), exact_empty: bool = False, contract_id: str = "postcondition", schema_version: str = "1")`.
- Produces `JsonObjectContract(path: str, expected: dict[str, object], exact_keys: bool = False, contract_id: str = "postcondition", schema_version: str = "1")`.
- Produces `PostconditionObservation(contract_id: str, kind: str, path: str, trusted: bool, matches: bool, evidence: dict[str, object], reason: str | None = None, trust_basis: str = "independent_local_state")`.
- Each contract exposes `kind`, `identity_payload()`, `identity_digest`, and `to_public_dict()`; public dicts contain verification identity but not raw expected content.
- Observation exposes `to_dict()` containing only allow-listed evidence and contract-relative path.

- [ ] **Step 1: Write failing contract and privacy tests**

Add tests that construct each contract, assert deterministic `identity_digest`, reject traversal/absolute/backslash/empty path components, reject unknown schema versions, reject contradictory directory requirements, and assert public serialization does not contain sentinel expected values such as `PRIVATE_SENTINEL_TEXT` or `PRIVATE_SENTINEL_JSON`.

```python
class ContractTests(unittest.TestCase):
    def test_text_contract_public_identity_does_not_emit_expected_text(self) -> None:
        contract = TextFileContract("output/result.txt", "PRIVATE_SENTINEL_TEXT", contract_id="t1")
        payload = json.dumps(contract.to_public_dict(), sort_keys=True)
        self.assertNotIn("PRIVATE_SENTINEL_TEXT", payload)
        self.assertEqual(contract.kind, "text_file")
        self.assertEqual(len(contract.identity_digest), 64)

    def test_directory_contract_rejects_empty_plus_required_children(self) -> None:
        with self.assertRaisesRegex(ValueError, "exact_empty"):
            DirectoryContract("output", required_children=("a.txt",), exact_empty=True)

    def test_json_contract_public_identity_does_not_emit_expected_values(self) -> None:
        contract = JsonObjectContract("state.json", {"status": "PRIVATE_SENTINEL_JSON"})
        self.assertNotIn("PRIVATE_SENTINEL_JSON", json.dumps(contract.to_public_dict()))
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_postconditions.ContractTests -v`
Expected: FAIL because `completion_verifier.postconditions` does not exist.

- [ ] **Step 3: Implement minimum strict models**

Implement shared relative-POSIX path validation without importing or changing the sandbox implementation. Require exact schema version `"1"`; reject unknown constructor/public parser fields; normalise `required_children` to unique sorted direct names; require JSON expected keys to be non-empty strings. Build identity digests from semantic metadata plus SHA-256 digests of caller-supplied expected values, but keep raw values out of `to_public_dict()`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m unittest tests.test_postconditions.ContractTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: add strict postcondition contracts`

---

### Task 2: Confined read-only filesystem boundary and text-file verifier

**Files:**
- Create: `src/completion_verifier/postconditions/filesystem.py`
- Create: `src/completion_verifier/postconditions/text_file.py`
- Modify: `src/completion_verifier/postconditions/__init__.py`
- Modify: `tests/test_postconditions.py`

**Interfaces:**
- Produces `ObservationRoot(root: Path)` with read-only `resolve(relative: str) -> Path` that rejects root symlinks, parent symlinks, final symlinks, traversal and non-directory roots without exposing resolved paths in exceptions.
- Produces `TextFileVerifier.verify(contract: TextFileContract, root: Path) -> PostconditionObservation`.
- Text evidence keys are limited to `exists`, `regular_file`, `size_matches`, `content_matches`; no bytes, text, digest, absolute path, owner, timestamps or unrelated metadata.

- [ ] **Step 1: Write failing text verifier tests**

Cover exact success, missing file, content mismatch, wrong final type, parent symlink, final symlink, and a privacy regression where a temporary root named `PRIVATE_ROOT_SENTINEL` never appears in `json.dumps(observation.to_dict())` or exception text.

```python
def test_text_verifier_matches_exact_utf8_without_exposing_content(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "result.txt").write_text("PRIVATE_OBSERVED_SENTINEL", encoding="utf-8")
        obs = TextFileVerifier().verify(
            TextFileContract("result.txt", "PRIVATE_OBSERVED_SENTINEL"), root
        )
        self.assertTrue(obs.matches)
        payload = json.dumps(obs.to_dict(), sort_keys=True)
        self.assertNotIn("PRIVATE_OBSERVED_SENTINEL", payload)
        self.assertNotIn(str(root), payload)
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_postconditions.TextFileVerifierTests -v`
Expected: FAIL because verifier/filesystem classes do not exist.

- [ ] **Step 3: Implement minimum boundary and verifier**

Use `os.lstat`/`stat` for every existing path component. Never call `.resolve()` on a target path before symlink checks. Read bytes only after final path is proven regular; compare to `expected_text.encode("utf-8")`; catch `OSError` and return a failed trusted/non-trusted observation with a fixed sanitized reason code such as `"io_error"`, never `str(exc)`.

- [ ] **Step 4: Verify GREEN and old sandbox compatibility**

Run:
- `python -m unittest tests.test_postconditions.TextFileVerifierTests -v`
- `python -m unittest tests.test_sandbox -v`
Expected: PASS for both.

- [ ] **Step 5: Commit**

Commit message: `feat: verify exact local text postconditions`

---

### Task 3: Directory-state verifier with declared-only evidence

**Files:**
- Create: `src/completion_verifier/postconditions/directory.py`
- Modify: `src/completion_verifier/postconditions/__init__.py`
- Modify: `tests/test_postconditions.py`

**Interfaces:**
- Produces `DirectoryVerifier.verify(contract: DirectoryContract, root: Path) -> PostconditionObservation`.
- Evidence keys: `exists`, `directory`, `required_children_present`, and when requested `empty`; undeclared child names are never serialized.

- [ ] **Step 1: Write failing directory tests**

Cover success, missing directory, file-at-directory path, all required direct children present, one required child absent, exact-empty success/failure, parent/final symlink rejection, and undeclared child privacy.

```python
def test_directory_observation_does_not_list_undeclared_children(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "output"
        target.mkdir()
        (target / "PRIVATE_UNDECLARED_SENTINEL.txt").write_text("x")
        obs = DirectoryVerifier().verify(DirectoryContract("output"), root)
        self.assertTrue(obs.matches)
        self.assertNotIn("PRIVATE_UNDECLARED_SENTINEL", json.dumps(obs.to_dict()))
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_postconditions.DirectoryVerifierTests -v`
Expected: FAIL because `DirectoryVerifier` does not exist.

- [ ] **Step 3: Implement minimum directory verifier**

Use `ObservationRoot`; call `os.scandir` only when checking declared children or emptiness. For required children, compare names in memory and serialize only a boolean aggregate. For `exact_empty`, stop after the first entry rather than recording names.

- [ ] **Step 4: Verify GREEN**

Run: `python -m unittest tests.test_postconditions.DirectoryVerifierTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: verify local directory postconditions`

---

### Task 4: Strict structured-JSON verifier

**Files:**
- Create: `src/completion_verifier/postconditions/json_object.py`
- Modify: `src/completion_verifier/postconditions/__init__.py`
- Modify: `tests/test_postconditions.py`

**Interfaces:**
- Produces `JsonObjectVerifier.verify(contract: JsonObjectContract, root: Path) -> PostconditionObservation`.
- Strict loader uses `json.loads(text, object_pairs_hook=...)` and raises a private internal duplicate-key marker on repeated keys.
- Evidence keys: `exists`, `regular_file`, `valid_utf8`, `valid_json`, `top_level_object`, `expected_keys_present`, `expected_values_match`, `key_count_matches` when `exact_keys=True`; no key values or undeclared keys are serialized.

- [ ] **Step 1: Write failing JSON tests**

Cover success, value mismatch, missing key, extra key accepted in non-exact mode, extra key rejected in exact mode, malformed UTF-8, malformed JSON, duplicate key, list top level, symlink rejection, and raw-value privacy.

```python
def test_json_verifier_rejects_duplicate_keys_without_echoing_values(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "state.json").write_text('{"status":"PRIVATE_A","status":"PRIVATE_B"}')
        obs = JsonObjectVerifier().verify(JsonObjectContract("state.json", {"status": "ready"}), root)
        self.assertFalse(obs.matches)
        payload = json.dumps(obs.to_dict())
        self.assertNotIn("PRIVATE_A", payload)
        self.assertNotIn("PRIVATE_B", payload)
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_postconditions.JsonObjectVerifierTests -v`
Expected: FAIL because `JsonObjectVerifier` does not exist.

- [ ] **Step 3: Implement minimum strict JSON verifier**

Read bytes from a proven regular file, decode UTF-8 strictly, parse with duplicate-key rejection, require `dict`, compare only declared keys/values in memory, and serialize booleans/count checks only. Use fixed reason codes (`invalid_utf8`, `invalid_json`, `duplicate_key`, `wrong_top_level`) rather than parser text that could echo content.

- [ ] **Step 4: Verify GREEN**

Run: `python -m unittest tests.test_postconditions.JsonObjectVerifierTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: verify strict JSON postconditions`

---

### Task 5: Explicit registry and existing-evaluator integration

**Files:**
- Create: `src/completion_verifier/postconditions/registry.py`
- Create: `src/completion_verifier/postconditions/evaluation.py`
- Modify: `src/completion_verifier/postconditions/__init__.py`
- Modify: `src/completion_verifier/__init__.py`
- Modify: `tests/test_postconditions.py`

**Interfaces:**
- Produces `verify_postcondition(contract, root: Path) -> PostconditionObservation` using a closed mapping of `text_file`, `directory`, `json_object` to verifier instances.
- Produces `postcondition_case(contract, observation, *, completion_claimed: bool = True) -> Case`.
- Produces `evaluate_postcondition(contract, root: Path, *, completion_claimed: bool = True) -> Evaluation`.
- Canonical action name: `verify_postcondition:{contract.kind}`.
- Event success is `observation.trusted and observation.matches`; required evidence field is `trust_basis`; observation evidence includes `trust_basis="independent_local_state"` only when the independent read boundary was valid.

- [ ] **Step 1: Write failing registry/integration tests**

Assert all three contract classes dispatch through `verify_postcondition`, an artificial unknown kind is rejected, and matching/mismatching observations become `VERIFIED_COMPLETE`/`FAILED` through the existing `evaluate_case` path.

```python
def test_evaluate_postcondition_uses_existing_evaluator(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "result.txt").write_text("ok")
        evaluation = evaluate_postcondition(TextFileContract("result.txt", "ok"), root)
        self.assertEqual(evaluation.status, Status.VERIFIED_COMPLETE)
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_postconditions.RegistryAndEvaluationTests -v`
Expected: FAIL because registry/evaluation functions do not exist.

- [ ] **Step 3: Implement closed registry and adapter**

Use a module constant mapping; do not expose registration hooks in v0.7. Construct one `Requirement`, one `Event`, and one `Case`; call existing `evaluate_case`. Do not copy evaluator logic.

- [ ] **Step 4: Verify GREEN plus complete source suite**

Run:
- `python -m unittest tests.test_postconditions.RegistryAndEvaluationTests -v`
- `python -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: expose generic postcondition verification API`

---

### Task 6: Documentation, release identity, privacy regression, and exact-head verification

**Files:**
- Create: `docs/POSTCONDITIONS.md`
- Modify: `README.md`
- Modify: `docs/RESEARCH_ROADMAP.md`
- Modify: `pyproject.toml`
- Modify: `src/completion_verifier/__init__.py`
- Modify: `scripts/verify_release.py`
- Modify: `tests/test_postconditions.py`

**Interfaces:**
- Package version becomes `0.7.0` in both `pyproject.toml` and `completion_verifier.__version__`.
- Release verifier runs a provider-free postcondition smoke test and asserts public serialization contains no sentinel raw values or absolute temporary root.

- [ ] **Step 1: Add failing release/privacy regression assertions**

Extend tests so the package version is consistent and a representative text + JSON + directory verification produces privacy-safe serialized output. Extend `verify_release.py` with a temporary-root smoke test using only synthetic values.

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_postconditions -v`
Expected: FAIL on version/docs/release expectations until release identity is updated.

- [ ] **Step 3: Update docs and version**

Document:
- what the three verifier kinds prove;
- public API examples using only synthetic values;
- privacy-minimal serialization boundary;
- no network/credentials/execution;
- local verification does not prove remote identity, authorization, causation or production safety;
- remote GitHub/email verifiers are follow-on work, not included in v0.7.

Update README roadmap so the immediate next step after v0.7 is one separately reviewed remote verifier rather than more local framework expansion.

- [ ] **Step 4: Run full local release command in CI-compatible form**

Run: `python scripts/verify_release.py`
Expected: `Release verification passed.`

- [ ] **Step 5: Run clean package checks**

Run the repository's existing Python 3.10, 3.11, 3.12 and 3.13 CI matrix and clean-wheel verification unchanged. Also run the manual 15-pass workflow on Python 3.10 and 3.13 before merge because this is a public API/release boundary change.
Expected: all exact-head checks green with zero source/test drift.

- [ ] **Step 6: Final privacy review**

Search the PR diff for sentinel strings, absolute temp/home paths, email-like fixture values, credential names, raw expected/observed values, and network/client imports. Confirm `.gitignore` secret/private-run exclusions remain unchanged or stricter.

- [ ] **Step 7: Commit**

Commit message: `release: prepare privacy-first action verification SDK v0.7.0`

---

## Exact-head merge gate

Before merging the implementation PR:

1. PR head SHA is unchanged after the final verification run.
2. Branch is not behind `main`.
3. Diff contains only the planned SDK/tests/docs/release changes.
4. All normal CI jobs pass on the exact head.
5. Manual 15-pass verification passes 15/15 on both Python 3.10 and 3.13.
6. No unresolved review threads.
7. No personal/secret content is introduced by fixtures, observations, docs, logs, or release evidence.
8. No new network, credential, external execution, retry, monitoring, or dynamic-plugin capability exists.
9. Merge through a reviewed PR; do not push implementation directly to `main`.
10. Preserve the feature branch after merge.
