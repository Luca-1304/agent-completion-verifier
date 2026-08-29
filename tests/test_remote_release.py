from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

import completion_verifier
from completion_verifier.models import Status
from completion_verifier.remote import RemoteOutcome, evaluate_remote_observation
from completion_verifier.remote.github import (
    GitHubPullRequestContract,
    GitHubPullRequestSnapshot,
    GitHubReadResult,
    verify_github_pull_request,
)


ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = ROOT / "src" / "completion_verifier" / "remote"
DOC_PATH = ROOT / "docs" / "REMOTE_GITHUB.md"
README_PATH = ROOT / "README.md"
ROADMAP_PATH = ROOT / "docs" / "RESEARCH_ROADMAP.md"
PYPROJECT = ROOT / "pyproject.toml"

PRIVATE_REPOSITORY = "PRIVATE_OWNER_SENTINEL/PRIVATE_REPO_SENTINEL"
PRIVATE_BASE = "PRIVATE_BASE_SENTINEL"
PRIVATE_HEAD = "a" * 40
PRIVATE_WRONG_HEAD = "b" * 40
PRIVATE_TOKEN = "PRIVATE_TOKEN_SENTINEL"
PRIVATE_BODY = "PRIVATE_PROVIDER_BODY_SENTINEL"
PRIVATE_ERROR = "PRIVATE_PROVIDER_ERROR_SENTINEL"
PRIVATE_PROVIDER_REPR = "PRIVATE_PROVIDER_REPR_SENTINEL"
PRIVATE_REPOSITORY_ID = 87654321
PRIVATE_PULL_NUMBER = 7654321
PRIVATE_HEAD_REPOSITORY_ID = 12345678
PRIVATE_TIMESTAMP = 1_234_567.0


def contract() -> GitHubPullRequestContract:
    return GitHubPullRequestContract(
        repository=PRIVATE_REPOSITORY,
        repository_id=PRIVATE_REPOSITORY_ID,
        pull_number=PRIVATE_PULL_NUMBER,
        expected_head_oid=PRIVATE_HEAD,
        expected_base_ref=PRIVATE_BASE,
        expected_state="open",
        expected_head_repository_id=PRIVATE_HEAD_REPOSITORY_ID,
    )


def snapshot(*, head_oid: str = PRIVATE_HEAD) -> GitHubPullRequestSnapshot:
    return GitHubPullRequestSnapshot(
        repository_id=PRIVATE_REPOSITORY_ID,
        pull_number=PRIVATE_PULL_NUMBER,
        state="open",
        merged=False,
        head_oid=head_oid,
        head_repository_id=PRIVATE_HEAD_REPOSITORY_ID,
        base_ref=PRIVATE_BASE,
        merge_oid=None,
        request_started_at=PRIVATE_TIMESTAMP - 1,
        request_finished_at=PRIVATE_TIMESTAMP,
        provider_date=PRIVATE_TIMESTAMP,
    )


class FakeReader:
    def __init__(self, result: GitHubReadResult) -> None:
        self.result = result

    def read_pull_request(self, requested: GitHubPullRequestContract) -> GitHubReadResult:
        return self.result


class RemoteReleaseBoundaryTests(unittest.TestCase):
    def test_release_version_is_0_8_0_everywhere(self) -> None:
        self.assertEqual(completion_verifier.__version__, "0.8.0")
        pyproject = PYPROJECT.read_text(encoding="utf-8")
        self.assertIn('version = "0.8.0"', pyproject)

    def test_remote_documentation_states_proof_and_non_proof_boundaries(self) -> None:
        self.assertTrue(DOC_PATH.exists())
        text = DOC_PATH.read_text(encoding="utf-8")
        required_phrases = (
            "authenticated",
            "read-only",
            "observation time",
            "does not prove causality",
            "does not prove user authorization",
            "does not guarantee permanence",
            "Pull requests: read",
            "Contents: read",
            "privacy",
            "UNVERIFIED",
            "FAILED",
            "VERIFIED_COMPLETE",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_release_docs_reflect_remote_verifier_as_implemented(self) -> None:
        readme = README_PATH.read_text(encoding="utf-8")
        roadmap = ROADMAP_PATH.read_text(encoding="utf-8")
        self.assertIn("Authenticated GitHub remote-state verification", readme)
        self.assertNotIn("It does not prove remote state", readme)
        self.assertIn("authenticated GitHub pull-request remote-state verifier", roadmap)
        self.assertNotIn("Design one separately reviewed remote-state verifier", roadmap)

    def test_public_remote_results_exclude_all_private_sentinels(self) -> None:
        expected = contract()
        observations = (
            verify_github_pull_request(
                expected,
                FakeReader(GitHubReadResult(snapshot=snapshot())),
                now=lambda: PRIVATE_TIMESTAMP,
            ),
            verify_github_pull_request(
                expected,
                FakeReader(GitHubReadResult(snapshot=snapshot(head_oid=PRIVATE_WRONG_HEAD))),
                now=lambda: PRIVATE_TIMESTAMP,
            ),
            verify_github_pull_request(
                expected,
                FakeReader(GitHubReadResult(snapshot=None, reason="provider_unavailable")),
                now=lambda: PRIVATE_TIMESTAMP,
            ),
        )
        self.assertEqual(
            [item.outcome for item in observations],
            [RemoteOutcome.MATCH, RemoteOutcome.MISMATCH, RemoteOutcome.INDETERMINATE],
        )
        self.assertEqual(
            [evaluate_remote_observation(item).status for item in observations],
            [Status.VERIFIED_COMPLETE, Status.FAILED, Status.UNVERIFIED],
        )

        public = json.dumps([item.to_dict() for item in observations], sort_keys=True)
        private_sentinels = (
            "PRIVATE_OWNER_SENTINEL",
            "PRIVATE_REPO_SENTINEL",
            PRIVATE_BASE,
            PRIVATE_HEAD,
            PRIVATE_WRONG_HEAD,
            PRIVATE_TOKEN,
            PRIVATE_BODY,
            PRIVATE_ERROR,
            PRIVATE_PROVIDER_REPR,
            str(PRIVATE_REPOSITORY_ID),
            str(PRIVATE_PULL_NUMBER),
            str(PRIVATE_HEAD_REPOSITORY_ID),
            str(PRIVATE_TIMESTAMP),
        )
        for secret in private_sentinels:
            with self.subTest(secret=secret):
                self.assertNotIn(secret, public)

    def test_remote_source_has_no_environment_secret_discovery(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(REMOTE_ROOT.rglob("*.py"))
        )
        for forbidden in ("os.environ", "os.getenv", "dotenv", ".env"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, combined)

    def test_remote_source_uses_no_third_party_runtime_imports(self) -> None:
        allowed_top_level = {
            "__future__",
            "dataclasses",
            "datetime",
            "email",
            "enum",
            "http",
            "json",
            "math",
            "re",
            "time",
            "types",
            "typing",
        }
        for path in sorted(REMOTE_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name.split(".")[0], allowed_top_level)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    self.assertIn(node.module.split(".")[0], allowed_top_level)

    def test_http_request_calls_are_get_only(self) -> None:
        request_methods: list[str] = []
        for path in sorted(REMOTE_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr != "request" or not node.args:
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    request_methods.append(first.value)
        self.assertTrue(request_methods)
        self.assertEqual(set(request_methods), {"GET"})

    def test_base_runtime_dependencies_remain_empty(self) -> None:
        text = PYPROJECT.read_text(encoding="utf-8")
        self.assertIn("dependencies = []", text)


if __name__ == "__main__":
    unittest.main()
