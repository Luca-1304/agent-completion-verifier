from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "completion_verifier"


class PublicSurfaceTests(unittest.TestCase):
    def test_private_experiment_namespace_is_not_in_stable_tree(self) -> None:
        self.assertFalse((SOURCE / "experiments").exists())

    def test_live_r1_runbooks_are_not_in_stable_tree(self) -> None:
        forbidden = (
            ROOT / "docs" / "R1_EXPERIMENT.md",
            ROOT / "docs" / "superpowers" / "plans" / "2026-08-29-r1-real-provider-experiment.md",
            ROOT / "docs" / "superpowers" / "specs" / "2026-08-29-r1-real-provider-experiment-design.md",
            ROOT / "scripts" / "verify_r1_release.py",
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

    def test_public_security_policies_are_present(self) -> None:
        self.assertTrue((ROOT / "SECURITY.md").is_file())
        self.assertTrue((ROOT / "docs" / "PUBLIC_SURFACE.md").is_file())


if __name__ == "__main__":
    unittest.main()
