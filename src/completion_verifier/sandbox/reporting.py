from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from ..models import Case, Status
from .models import SandboxRunResult, SandboxSuiteConfig


def json_text(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def jsonl_text(values: Iterable[object]) -> str:
    return "".join(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
        for value in values
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def case_dict(case: Case) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "task": case.task,
        "completion_claimed": case.completion_claimed,
        "requirements": [
            {
                "action": requirement.action,
                "evidence_fields": list(requirement.evidence_fields),
            }
            for requirement in case.requirements
        ],
        "events": [
            {
                "action": event.action,
                "success": event.success,
                "evidence": dict(event.evidence),
                "sequence": event.sequence,
            }
            for event in case.events
        ],
    }


def calculate_sandbox_metrics(results: list[SandboxRunResult]) -> dict[str, Any]:
    statuses = Counter(result.evaluation.status.value for result in results)
    claimed = sum(result.report.completion_claimed for result in results)
    false_completion = sum(
        result.report.completion_claimed
        and result.evaluation.status is not Status.VERIFIED_COMPLETE
        for result in results
    )
    independently_verified = sum(
        result.evaluation.status is Status.VERIFIED_COMPLETE for result in results
    )
    silent_verified = sum(
        not result.report.completion_claimed
        and result.evaluation.status is Status.VERIFIED_COMPLETE
        for result in results
    )
    agreement = sum(
        result.report.reported_success == result.observation.matches_contract
        for result in results
    )
    source_false_positive = sum(
        result.report.reported_success and not result.observation.matches_contract
        for result in results
    )
    source_false_negative = sum(
        not result.report.reported_success and result.observation.matches_contract
        for result in results
    )
    security_rejection = sum(result.security_rejected for result in results)
    return {
        "schema_version": "1",
        "total_scenarios": len(results),
        "status_counts": {status.value: statuses[status.value] for status in Status},
        "claimed_completion": claimed,
        "false_completion": false_completion,
        "false_completion_rate": false_completion / claimed if claimed else 0.0,
        "independently_verified_completion": independently_verified,
        "silent_verified_completion": silent_verified,
        "source_observation_agreement": agreement,
        "source_false_positive": source_false_positive,
        "source_false_negative": source_false_negative,
        "security_rejection": security_rejection,
        "scenarios": {
            result.scenario_id: {
                "status": result.evaluation.status.value,
                "reported_success": result.report.reported_success,
                "completion_claimed": result.report.completion_claimed,
                "matches_contract": result.observation.matches_contract,
                "security_rejected": result.security_rejected,
            }
            for result in results
        },
        "limitations": {
            "external_model_results": False,
            "observation_scope": "independent_local_file_state",
            "os_level_adversarial_isolation": False,
        },
    }


def build_report(config: SandboxSuiteConfig, metrics: dict[str, Any]) -> str:
    return f"""# Independent sandbox postcondition suite\n\nGenerated at: {config.generated_at}\n\nThis deterministic suite verifies local file state independently from source-reported tool receipts. It is **not external-model** performance evidence and does not provide production identity, authorization, remote-state proof, or adversarial OS isolation.\n\n## Configuration\n\n- Suite: `{config.suite_id}`\n- Configuration digest: `{config.digest}`\n- Contract: `{config.contract.contract_id}`\n- Path: `{config.contract.path}`\n- Scenarios: {', '.join(config.scenarios)}\n\n## Headline results\n\n- Total scenarios: {metrics['total_scenarios']}\n- Independently verified completions: {metrics['independently_verified_completion']}\n- False completions: {metrics['false_completion']}\n- False-completion rate: {metrics['false_completion_rate']:.6f}\n- Silent independently verified completions: {metrics['silent_verified_completion']}\n- Source false positives: {metrics['source_false_positive']}\n- Source false negatives: {metrics['source_false_negative']}\n- Security rejections: {metrics['security_rejection']}\n\n## Evidence boundary\n\nRaw source reports, independent observations, canonical cases and evaluations are stored separately. Canonical evidence is derived only from the local observer. Source-reported hashes or success flags cannot satisfy the verifier.\n\n## Reproduce\n\n```bash\ncompletion-verifier-sandbox --config examples/sandbox_config.json --output sandbox_runs/reference-v1 --scenario all\n```\n"""
