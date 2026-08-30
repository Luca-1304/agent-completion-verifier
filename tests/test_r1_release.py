from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
R1_ROOT = ROOT / "src/completion_verifier/experiments/r1"


def _normalized_text(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").lower().split())


class R1ReleaseBoundaryTests(unittest.TestCase):
    def test_r1_source_does_not_discover_credentials_from_environment_or_secret_stores(self) -> None:
        forbidden = (
            "os.environ",
            "os.getenv",
            "getenv(",
            "load_dotenv",
            "dotenv",
            "keyring",
            ".netrc",
            "credential.helper",
        )
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(R1_ROOT.glob("*.py"))
        )
        for needle in forbidden:
            self.assertNotIn(needle, source, needle)

    def test_github_controller_request_methods_are_fixed_and_never_delete(self) -> None:
        path = R1_ROOT / "github_controller.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        methods: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "_request":
                continue
            for keyword in node.keywords:
                if keyword.arg == "method" and isinstance(keyword.value, ast.Constant):
                    methods.add(keyword.value.value)
        self.assertEqual(methods, {"POST", "PUT", "PATCH"})
        self.assertNotIn("DELETE", path.read_text(encoding="utf-8"))

    def test_live_runner_requires_permit_validation_path(self) -> None:
        source = (R1_ROOT / "runner.py").read_text(encoding="utf-8")
        self.assertIn("R1LivePermit", source)
        self.assertIn("validate_live_permit", source)
        self.assertIn("live_permit_required", source)
        self.assertIn("controller_target_mismatch", source)

    def test_r1_release_script_exists_and_is_network_free_by_construction(self) -> None:
        path = ROOT / "scripts/verify_r1_release.py"
        self.assertTrue(path.is_file())
        source = path.read_text(encoding="utf-8")
        self.assertNotIn("GitHubR1Controller", source)
        self.assertNotIn("http.client", source)
        self.assertNotIn("requests", source)
        self.assertNotIn("os.environ", source)
        self.assertIn("DryRunR1Controller", source)
        self.assertIn("verify_r1_manifest", source)

    def test_normal_release_verifier_invokes_r1_gate(self) -> None:
        source = (ROOT / "scripts/verify_release.py").read_text(encoding="utf-8")
        self.assertIn('"scripts/verify_r1_release.py"', source)

    def test_r1_documentation_states_experimental_and_real_provider_claim_boundary(self) -> None:
        path = ROOT / "docs/R1_EXPERIMENT.md"
        self.assertTrue(path.is_file())
        text = _normalized_text(path)
        for phrase in (
            "experimental",
            "no real-provider reliability claim",
            "disposable",
            "preflight",
            "no polling",
            "source claim",
            "independent verifier",
            "causality",
            "authorization",
            "permanence",
        ):
            self.assertIn(phrase, text)

    def test_readme_and_roadmap_expose_r1_without_claiming_completed_live_results(self) -> None:
        readme = _normalized_text(ROOT / "README.md")
        roadmap = _normalized_text(ROOT / "docs/RESEARCH_ROADMAP.md")
        self.assertIn("r1", readme)
        self.assertIn("experimental", readme)
        self.assertIn("no real-provider reliability claim", readme)
        self.assertIn("r1", roadmap)
        self.assertIn("pilot", roadmap)
        self.assertNotIn("r1 pilot completed", readme)
        self.assertNotIn("r1 pilot completed", roadmap)

    def test_r1_does_not_change_package_release_version(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        package = (ROOT / "src/completion_verifier/__init__.py").read_text(encoding="utf-8")
        self.assertIn('version = "0.8.0"', pyproject)
        self.assertIn('__version__ = "0.8.0"', package)


if __name__ == "__main__":
    unittest.main()
