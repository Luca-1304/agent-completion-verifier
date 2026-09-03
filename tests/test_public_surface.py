from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "completion_verifier"


class PublicSurfaceTests(unittest.TestCase):
    def test_private_execution_namespaces_are_not_in_stable_tree(self) -> None:
        self.assertFalse((SOURCE / "experiments").exists())
        self.assertFalse((SOURCE / "live").exists())
        self.assertFalse((SOURCE / "live_cli.py").exists())

    def test_internal_planning_and_live_runbooks_are_not_in_stable_tree(self) -> None:
        self.assertFalse((ROOT / "docs" / "superpowers").exists())
        forbidden = (
            ROOT / "docs" / "R1_EXPERIMENT.md",
            ROOT / "docs" / "LIVE_RUNNER.md",
            ROOT / "scripts" / "verify_r1_release.py",
            ROOT / "examples" / "openai_live_config.json",
            ROOT / ".github" / "workflows" / "live-runner-tests.yml",
        )
        for path in forbidden:
            with self.subTest(path=path):
                self.assertFalse(path.exists())

    def test_stable_python_source_has_no_literal_write_http_request(self) -> None:
        forbidden_methods = {"POST", "PUT", "PATCH", "DELETE"}
        findings: list[str] = []
        for path in SOURCE.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "request"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and node.args[0].value.upper() in forbidden_methods
                ):
                    findings.append(f"{path.relative_to(ROOT)}:{node.lineno}")
                for keyword in node.keywords:
                    if (
                        keyword.arg == "method"
                        and isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, str)
                        and keyword.value.value.upper() in forbidden_methods
                    ):
                        findings.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(findings, [])

    def test_stable_source_does_not_discover_common_local_secrets(self) -> None:
        forbidden_tokens = (
            "os.environ",
            "os.getenv(",
            "from os import getenv",
            "import keyring",
            "from keyring",
            "netrc.netrc",
            "from netrc",
        )
        findings: list[str] = []
        for path in SOURCE.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    findings.append(f"{path.relative_to(ROOT)}:{token}")
        self.assertEqual(findings, [])

    def test_package_has_no_live_execution_entry_point_or_provider_sdk_extra(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertNotIn("completion-verifier-live", pyproject)
        self.assertNotIn('openai = ["openai', pyproject)

    def test_repository_contains_no_obvious_secret_files(self) -> None:
        findings: list[str] = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts:
                continue
            name = path.name.lower()
            if (
                name == ".env"
                or name.startswith(".env.") and not name.endswith(".example")
                or path.suffix.lower() in {".pem", ".key"}
                or name in {"credentials.json", "secrets.json", "secrets.txt"}
                or name.startswith("credentials.") and name.endswith(".json")
            ):
                findings.append(str(path.relative_to(ROOT)))
        self.assertEqual(findings, [])

    def test_repository_contains_no_high_confidence_secret_literals(self) -> None:
        patterns = (
            re.compile(r"ghp_[A-Za-z0-9]{30,}"),
            re.compile(r"github_pat_[A-Za-z0-9_]{40,}"),
            re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"),
            re.compile(r"AKIA[0-9A-Z]{16}"),
            re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        )
        text_suffixes = {".py", ".md", ".json", ".jsonl", ".toml", ".yml", ".yaml", ".txt"}
        findings: list[str] = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts or path.suffix.lower() not in text_suffixes:
                continue
            text = path.read_text(encoding="utf-8", errors="strict")
            for pattern in patterns:
                if pattern.search(text):
                    findings.append(f"{path.relative_to(ROOT)}:{pattern.pattern}")
        self.assertEqual(findings, [])

    def test_public_security_policies_are_present(self) -> None:
        self.assertTrue((ROOT / "SECURITY.md").is_file())
        self.assertTrue((ROOT / "docs" / "PUBLIC_SURFACE.md").is_file())


if __name__ == "__main__":
    unittest.main()
