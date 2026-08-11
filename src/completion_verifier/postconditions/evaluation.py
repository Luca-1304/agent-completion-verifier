from __future__ import annotations

from pathlib import Path

from ..evaluator import evaluate_case
from ..models import Case, Evaluation, Event, Requirement
from .models import PostconditionContract, PostconditionObservation
from .registry import verify_postcondition


def _action(kind: str) -> str:
    return f"verify_postcondition:{kind}"


def postcondition_case(
    contract: PostconditionContract,
    observation: PostconditionObservation,
    *,
    completion_claimed: bool = True,
) -> Case:
    if not isinstance(completion_claimed, bool):
        raise ValueError("'completion_claimed' must be boolean.")
    if getattr(contract, "kind", None) != observation.kind:
        raise ValueError("Contract and observation kind must match.")

    kind = observation.kind
    action = _action(kind)
    evidence = dict(observation.evidence)
    evidence.update(
        {
            "trusted": observation.trusted,
            "matches": observation.matches,
            "trust_basis": observation.trust_basis if observation.trusted else None,
            "reason": observation.reason,
        }
    )
    return Case(
        case_id=f"postcondition-{kind}",
        task=f"Verify declared {kind} postcondition.",
        completion_claimed=completion_claimed,
        requirements=(Requirement(action=action, evidence_fields=("trust_basis",)),),
        events=(
            Event(
                action=action,
                success=observation.trusted and observation.matches,
                evidence=evidence,
                sequence=0,
            ),
        ),
    )


def evaluate_postcondition(
    contract: PostconditionContract,
    root: Path,
    *,
    completion_claimed: bool = True,
) -> Evaluation:
    observation = verify_postcondition(contract, root)
    return evaluate_case(
        postcondition_case(
            contract,
            observation,
            completion_claimed=completion_claimed,
        )
    )
