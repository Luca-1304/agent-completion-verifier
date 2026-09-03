from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "completion_verifier"
SCRIPTS = ROOT / "scripts"
EXECUTABLE_PYTHON_ROOTS = (SOURCE, SCRIPTS)
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _write_http_findings(path: Path, text: str) -> list[str]:
    tree = ast.parse(text, filename=str(path))
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr.upper() in WRITE_METHODS:
                findings.append(f"{path}:{node.lineno}:{func.attr.upper()}")
                continue
            if func.attr == "request":
                method: str | None = None
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    method = node.args[0].value
                for keyword in node.keywords:
                    if keyword.arg == "method" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                        method = keyword.value.value
                if method is not None and method.upper() in WRITE_METHODS:
                    findings.append(f"{path}:{node.lineno}:{method.upper()}")
        elif isinstance(func, ast.Name) and func.id.upper() in WRITE_METHODS:
            findings.append(f"{path}:{node.lineno}:{func.id.upper()}")
    return findings


def _secret_discovery_findings(path: Path, text: str) -> list[str]:
    tree = ast.parse(text, filename=str(path))
    findings: list[str] = []
    os_aliases: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os":
                    os_aliases.add(alias.asname or "os")
                if alias.name in {"keyring", "netrc"}:
                    findings.append(f"{path}:{node.lineno}:import-{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "os":
                for alias in node.names:
                    if alias.name in {"environ", "getenv"}:
                        findings.append(f"{path}:{node.lineno}:from-os-{alias.name}")
            if module in {"keyring", "netrc"}:
                findings.append(f"{path}:{node.lineno}:from-{module}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in os_aliases and node.attr in {"environ", "getenv"}:
                findings.append(f"{path}:{node.lineno}:os-{node.attr}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in os_aliases
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in {"environ", "getenv"}
        ):
            findings.append(f"{path}:{node.lineno}:os-getattr")
    return findings


def _iter_executable_python_files():
    for root in EXECUTABLE_PYTHON_ROOTS:
        yield from root.rglob("*.py")


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

    def test_executable_python_gate_covers_package_and_release_scripts(self) -> None:
        self.assertEqual(EXECUTABLE_PYTHON_ROOTS, (SOURCE, SCRIPTS))
        self.assertTrue(SCRIPTS.is_dir())

    def test_stable_executable_python_has_no_write_http_calls(self) -> None:
        findings: list[str] = []
        for path in _iter_executable_python_files():
            findings.extend(_write_http_findings(path.relative_to(ROOT), path.read_text(encoding="utf-8")))
        self.assertEqual(findings, [])

    def test_write_http_gate_detects_request_and_verb_specific_calls(self) -> None:
        samples = (
            'client.request("POST", "/resource")',
            'client.request("/resource", method="PATCH")',
            'client.put("/resource")',
            'session.delete("/resource")',
            'post("/resource")',
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(_write_http_findings(Path("sample.py"), sample))
        self.assertEqual(_write_http_findings(Path("sample.py"), 'client.get("/resource")'), [])

    def test_stable_executable_python_does_not_discover_common_local_secrets(self) -> None:
        findings: list[str] = []
        for path in _iter_executable_python_files():
            findings.extend(_secret_discovery_findings(path.relative_to(ROOT), path.read_text(encoding="utf-8")))
        self.assertEqual(findings, [])

    def test_secret_discovery_gate_detects_aliases(self) -> None:
        samples = (
            'import os as operating_system\nvalue = operating_system.environ.get("TOKEN")',
            'from os import environ as env\nvalue = env.get("TOKEN")',
            'from os import getenv as read_env\nvalue = read_env("TOKEN")',
            'import keyring as secrets\nvalue = secrets.get_password("svc", "user")',
            'from netrc import netrc as read_netrc\nvalue = read_netrc()',
            'import os as operating_system\nvalue = getattr(operating_system, "environ")',
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(_secret_discovery_findings(Path("sample.py"), sample))
        self.assertEqual(_secret_discovery_findings(Path("sample.py"), "import pathlib\nvalue = pathlib.Path('.')"), [])

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
                or (name.startswith(".env.") and not name.endswith(".example"))
                or path.suffix.lower() in {".pem", ".key"}
                or name in {"credentials.json", "secrets.json", "secrets.txt"}
                or (name.startswith("credentials.") and name.endswith(".json"))
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
