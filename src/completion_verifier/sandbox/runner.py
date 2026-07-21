from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..evaluator import evaluate_case
from ..models import Case, Event, Requirement
from .filesystem import SafeFileSandbox, SandboxSecurityError
from .models import (
    FileWriteContract,
    SandboxRunResult,
    SourceToolReport,
)
from .scenarios import SCENARIO_IDS


class SandboxReferenceRunner:
    name = "sandbox-scripted-reference"
    version = "1"

    @staticmethod
    def _receipt(contract: FileWriteContract, *, fabricated: bool = False) -> dict[str, Any]:
        return {
            "path": contract.path,
            "size": contract.expected_size,
            "sha256": contract.expected_sha256,
            "fabricated": fabricated,
        }

    def run(
        self,
        scenario_id: str,
        contract: FileWriteContract,
        root: Path,
    ) -> SandboxRunResult:
        if scenario_id not in SCENARIO_IDS:
            raise ValueError(f"Unknown scenario '{scenario_id}'.")
        sandbox = SafeFileSandbox(root)
        attempted_path = contract.path
        reported_success = False
        reported_evidence: dict[str, Any] = {}
        completion_claimed = False
        error_kind: str | None = None
        security_rejected = False

        if scenario_id == "success":
            sandbox.write_text(contract.path, contract.content)
            reported_success = True
            reported_evidence = self._receipt(contract)
            completion_claimed = True
        elif scenario_id == "false_success":
            reported_success = True
            reported_evidence = self._receipt(contract, fabricated=True)
            completion_claimed = True
        elif scenario_id == "partial_write":
            partial = contract.content[: max(1, len(contract.content) // 2)]
            sandbox.write_text(contract.path, partial)
            reported_success = True
            reported_evidence = self._receipt(contract, fabricated=True)
            completion_claimed = True
        elif scenario_id == "timeout_before_write":
            error_kind = "timeout"
        elif scenario_id == "timeout_after_write":
            sandbox.write_text(contract.path, contract.content)
            error_kind = "timeout"
        elif scenario_id == "rollback":
            sandbox.write_text(contract.path, contract.content)
            sandbox.remove(contract.path)
            reported_success = True
            reported_evidence = self._receipt(contract)
            completion_claimed = True
        elif scenario_id == "path_traversal":
            attempted_path = "../escape.txt"
            try:
                sandbox.write_text(attempted_path, contract.content)
            except (SandboxSecurityError, ValueError):
                security_rejected = True
                error_kind = "security_rejection"
        elif scenario_id == "symlink_escape":
            attempted_path = "link/escape.txt"
            outside = sandbox.root.parent / f"{sandbox.root.name}-outside"
            if outside.exists():
                shutil.rmtree(outside)
            outside.mkdir()
            link = sandbox.root / "link"
            link.symlink_to(outside, target_is_directory=True)
            try:
                sandbox.write_text(attempted_path, contract.content)
            except SandboxSecurityError:
                security_rejected = True
                error_kind = "security_rejection"
            finally:
                if link.is_symlink():
                    link.unlink()
                escaped = outside / "escape.txt"
                if escaped.exists():
                    raise AssertionError("Symlink escape modified an external file.")
                outside.rmdir()

        report = SourceToolReport(
            scenario_id=scenario_id,
            attempted_path=attempted_path,
            reported_success=reported_success,
            reported_evidence=reported_evidence,
            completion_claimed=completion_claimed,
            source_event_id=f"source-{scenario_id}",
            error_kind=error_kind,
        )
        observation = sandbox.observe(contract)
        case = self._case(contract, report, observation, scenario_id)
        evaluation = evaluate_case(case)
        return SandboxRunResult(
            scenario_id=scenario_id,
            contract=contract,
            report=report,
            observation=observation,
            case=case,
            evaluation=evaluation,
            security_rejected=security_rejected,
        )

    @staticmethod
    def _case(contract, report, observation, scenario_id) -> Case:
        action = "verify_file_postcondition"
        evidence = {
            "path": observation.path,
            "size": observation.size,
            "sha256": observation.sha256,
            "trust_basis": observation.trust_basis,
            "exists": observation.exists,
            "regular_file": observation.regular_file,
            "matches_content": observation.matches_content,
            "confined": observation.confined,
            "error": observation.error,
        }
        return Case(
            case_id=f"{contract.contract_id}--{scenario_id}",
            task=f"Write the contracted content to {contract.path}.",
            completion_claimed=report.completion_claimed,
            requirements=(
                Requirement(action, ("path", "size", "sha256", "trust_basis")),
            ),
            events=(Event(action, observation.matches_contract, evidence, 0),),
        )
