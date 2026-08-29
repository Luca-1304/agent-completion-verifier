from __future__ import annotations

from ..evaluator import evaluate_case
from ..models import Case, Evaluation, Event, Requirement
from .models import RemoteObservation, RemoteOutcome


def _action(observation: RemoteObservation) -> str:
    return f"verify_remote:{observation.provider}:{observation.kind}"


def remote_postcondition_case(
    observation: RemoteObservation,
    *,
    completion_claimed: bool = True,
) -> Case:
    if not isinstance(completion_claimed, bool):
        raise ValueError("'completion_claimed' must be boolean.")

    action = _action(observation)
    requirement = Requirement(action=action, evidence_fields=("trust_basis",))

    events: tuple[Event, ...]
    if observation.outcome is RemoteOutcome.INDETERMINATE:
        events = ()
    else:
        evidence = dict(observation.evidence)
        evidence.update(
            {
                "provider": observation.provider,
                "kind": observation.kind,
                "outcome": observation.outcome.value,
                "trusted": observation.trusted,
                "reason": observation.reason,
                "trust_basis": observation.trust_basis,
            }
        )
        events = (
            Event(
                action=action,
                success=observation.outcome is RemoteOutcome.MATCH,
                evidence=evidence,
                sequence=0,
            ),
        )

    return Case(
        case_id="remote-github-pull-request",
        task="Verify declared GitHub pull request remote state.",
        completion_claimed=completion_claimed,
        requirements=(requirement,),
        events=events,
    )


def evaluate_remote_observation(
    observation: RemoteObservation,
    *,
    completion_claimed: bool = True,
) -> Evaluation:
    return evaluate_case(
        remote_postcondition_case(
            observation,
            completion_claimed=completion_claimed,
        )
    )
