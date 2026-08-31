from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Protocol

from ...remote.github import GitHubPullRequestContract
from .artifacts import reserve_r1_output_dir, write_r1_artifacts, verify_r1_manifest
from .controller import (
    DryRunR1Controller,
    R1Controller,
    _validate_base_ref,
    _validate_oid,
    _validate_pull_number,
    validate_r1_branch_name,
    validate_r1_fixture_path,
)
from .metrics import calculate_r1_metrics
from .models import R1ControllerReceipt, R1ExperimentConfig, R1RunRecord, R1SourceClaim
from .orchestrator import R1Verifier, append_explicit_second_observation, evaluate_attempt, seal_source_claim
from .preflight import (
    R1LivePermit,
    R1LiveTarget,
    claim_live_permit,
    validate_live_permit_target,
)
from .scenarios import R1_SCENARIO_DEFINITIONS, R1ScenarioDefinition, get_r1_scenario


_RUNNER_ABORT_REASONS = frozenset(
    {
        "dry_controller_required", "live_permit_required", "live_permit_consumed",
        "live_mode_required", "dry_mode_required", "scenario_not_live_eligible",
        "controller_target_mismatch", "live_permit_rejected", "live_repetition_limit",
        "privacy_sentinel_required", "action_budget_exceeded", "action_not_allowed",
        "action_argument_mismatch", "action_sequence_invalid", "invalid_controller_receipt",
        "contract_unaddressable", "scaffold_invalid",
    }
)
_ARTIFACT_CLASSES = ("config", "runs", "observations", "evaluations", "metrics", "report", "manifest")


class R1RunnerAbort(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        if reason_code not in _RUNNER_ABORT_REASONS:
            raise ValueError("Unknown R1 runner abort reason.")
        self.reason_code = reason_code
        super().__init__(reason_code)

    def __repr__(self) -> str:
        return "R1RunnerAbort()"


@dataclass(frozen=True, repr=False)
class R1BoundedTask:
    scenario_id: str
    base_oid: str
    branch_name: str
    fixture_path: str
    fixture_content: str
    base_ref: str

    def __post_init__(self) -> None:
        get_r1_scenario(self.scenario_id)
        object.__setattr__(self, "base_oid", _validate_oid(self.base_oid))
        object.__setattr__(self, "branch_name", validate_r1_branch_name(self.branch_name))
        object.__setattr__(self, "fixture_path", validate_r1_fixture_path(self.fixture_path))
        if not isinstance(self.fixture_content, str) or not self.fixture_content:
            raise ValueError("R1 fixture content must be a non-empty string.")
        object.__setattr__(self, "base_ref", _validate_base_ref(self.base_ref))

    def __repr__(self) -> str:
        return "R1BoundedTask()"


@dataclass(frozen=True, repr=False)
class R1ContractExpectation:
    expected_state: str
    expected_head_oid: str | None = None
    expected_base_ref: str | None = None
    expected_pull_number: int | None = None
    expected_merge_oid: str | None = None

    def __post_init__(self) -> None:
        if self.expected_state not in {"open", "closed", "merged"}:
            raise ValueError("R1 expected state must be open, closed, or merged.")
        if self.expected_head_oid is not None:
            object.__setattr__(self, "expected_head_oid", _validate_oid(self.expected_head_oid))
        if self.expected_base_ref is not None:
            object.__setattr__(self, "expected_base_ref", _validate_base_ref(self.expected_base_ref))
        if self.expected_pull_number is not None:
            object.__setattr__(self, "expected_pull_number", _validate_pull_number(self.expected_pull_number))
        if self.expected_merge_oid is not None:
            if self.expected_state != "merged":
                raise ValueError("R1 expected merge object ID requires merged state.")
            object.__setattr__(self, "expected_merge_oid", _validate_oid(self.expected_merge_oid))

    def __repr__(self) -> str:
        return "R1ContractExpectation()"


@dataclass(frozen=True, repr=False)
class R1PreparedAttempt:
    target: R1LiveTarget
    task: R1BoundedTask
    expectation: R1ContractExpectation

    def __post_init__(self) -> None:
        if not isinstance(self.target, R1LiveTarget):
            raise ValueError("R1 prepared attempt requires an R1LiveTarget.")
        if not isinstance(self.task, R1BoundedTask):
            raise ValueError("R1 prepared attempt requires an R1BoundedTask.")
        if not isinstance(self.expectation, R1ContractExpectation):
            raise ValueError("R1 prepared attempt requires an R1ContractExpectation.")

    def __repr__(self) -> str:
        return "R1PreparedAttempt()"


@dataclass(frozen=True, repr=False)
class R1ScaffoldResult:
    completion_claimed: bool
    retry_count: int = 0
    refusal: bool = False
    private_trace_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.completion_claimed, bool):
            raise ValueError("R1 scaffold completion claim must be boolean.")
        if isinstance(self.retry_count, bool) or not isinstance(self.retry_count, int) or self.retry_count < 0:
            raise ValueError("R1 scaffold retry count must be a non-negative integer.")
        if not isinstance(self.refusal, bool):
            raise ValueError("R1 scaffold refusal flag must be boolean.")
        if self.private_trace_ref is not None:
            if not isinstance(self.private_trace_ref, str) or not self.private_trace_ref.strip():
                raise ValueError("R1 private trace reference must be a non-empty string.")
            object.__setattr__(self, "private_trace_ref", self.private_trace_ref.strip())

    def __repr__(self) -> str:
        return "R1ScaffoldResult()"


class R1AgentScaffold(Protocol):
    def run(self, task: R1BoundedTask, controller: R1Controller) -> R1ScaffoldResult: ...


class ScriptedR1Scaffold:
    """Deterministic reference scaffold used to prove harness mechanics only."""

    def __repr__(self) -> str:
        return "ScriptedR1Scaffold()"

    def run(self, task: R1BoundedTask, controller: R1Controller) -> R1ScaffoldResult:
        definition = get_r1_scenario(task.scenario_id)
        if not definition.capabilities:
            return R1ScaffoldResult(completion_claimed=True)
        branch = controller.create_branch(task.base_oid, task.branch_name)
        if not branch.success:
            return R1ScaffoldResult(completion_claimed=False)
        write = controller.write_fixture(task.branch_name, task.fixture_path, task.fixture_content)
        if not write.success:
            return R1ScaffoldResult(completion_claimed=False)
        pull = controller.create_pull_request(task.branch_name, task.base_ref)
        return R1ScaffoldResult(completion_claimed=pull.success)


@dataclass(frozen=True, repr=False)
class R1ExperimentResult:
    runs: tuple[R1RunRecord, ...]
    metrics: Mapping[str, object]
    output_dir: Path
    manifest_verified: bool
    live: bool

    def __post_init__(self) -> None:
        if not isinstance(self.runs, tuple) or not self.runs:
            raise ValueError("R1 experiment result requires runs.")
        if not isinstance(self.manifest_verified, bool) or not isinstance(self.live, bool):
            raise ValueError("R1 experiment result flags must be boolean.")
        object.__setattr__(self, "output_dir", Path(self.output_dir))
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))

    def __repr__(self) -> str:
        return "R1ExperimentResult()"


class _GatedR1Controller:
    def __init__(self, delegate: R1Controller, *, target: R1LiveTarget, task: R1BoundedTask,
                 definition: R1ScenarioDefinition, max_actions: int, permit: R1LivePermit | None) -> None:
        self._delegate = delegate
        self._target = target
        self._task = task
        self._definition = definition
        self._max_actions = max_actions
        self._permit = permit
        self.receipts: list[R1ControllerReceipt] = []
        self.open_pull_number: int | None = None

    @property
    def actions_used(self) -> int:
        return sum(receipt.action_cost for receipt in self.receipts)

    @property
    def _action_names(self) -> tuple[str, ...]:
        return tuple(receipt.action for receipt in self.receipts)

    def _authorize(self, action: str, *, reserve_cleanup: bool = False) -> None:
        if action not in self._definition.capabilities:
            raise R1RunnerAbort("action_not_allowed")
        required = 1 + (1 if reserve_cleanup else 0)
        if self.actions_used + required > self._max_actions:
            raise R1RunnerAbort("action_budget_exceeded")
        if self._permit is not None and not validate_live_permit_target(
            self._permit, scenario_id=self._definition.scenario_id, target=self._target,
            capabilities=self._definition.capabilities, actions_used=self.actions_used,
            action_cost=required,
        ):
            raise R1RunnerAbort("live_permit_rejected")

    def _require_sequence(self, expected: tuple[str, ...]) -> None:
        if self._action_names != expected or any(not receipt.success for receipt in self.receipts):
            raise R1RunnerAbort("action_sequence_invalid")

    def _record(self, expected_action: str, receipt: object) -> R1ControllerReceipt:
        if not isinstance(receipt, R1ControllerReceipt) or receipt.action != expected_action or receipt.action_cost != 1:
            raise R1RunnerAbort("invalid_controller_receipt")
        self.receipts.append(receipt)
        return receipt

    def create_branch(self, base_oid: str, branch_name: str) -> R1ControllerReceipt:
        self._require_sequence(())
        try:
            oid = _validate_oid(base_oid); branch = validate_r1_branch_name(branch_name)
        except ValueError as exc:
            raise R1RunnerAbort("action_argument_mismatch") from exc
        if oid != self._task.base_oid or branch != self._task.branch_name:
            raise R1RunnerAbort("action_argument_mismatch")
        self._authorize("create_branch")
        return self._record("create_branch", self._delegate.create_branch(oid, branch))

    def write_fixture(self, branch_name: str, relative_path: str, content: str,
                      *, existing_blob_sha: str | None = None) -> R1ControllerReceipt:
        self._require_sequence(("create_branch",))
        try:
            branch = validate_r1_branch_name(branch_name); path = validate_r1_fixture_path(relative_path)
        except ValueError as exc:
            raise R1RunnerAbort("action_argument_mismatch") from exc
        if branch != self._task.branch_name or path != self._task.fixture_path or content != self._task.fixture_content or existing_blob_sha is not None:
            raise R1RunnerAbort("action_argument_mismatch")
        self._authorize("write_fixture")
        return self._record("write_fixture", self._delegate.write_fixture(branch, path, content, existing_blob_sha=None))

    def create_pull_request(self, branch_name: str, base_ref: str) -> R1ControllerReceipt:
        self._require_sequence(("create_branch", "write_fixture"))
        try:
            branch = validate_r1_branch_name(branch_name); base = _validate_base_ref(base_ref)
        except ValueError as exc:
            raise R1RunnerAbort("action_argument_mismatch") from exc
        if branch != self._task.branch_name or base != self._task.base_ref:
            raise R1RunnerAbort("action_argument_mismatch")
        self._authorize("create_pull_request", reserve_cleanup=True)
        receipt = self._record("create_pull_request", self._delegate.create_pull_request(branch, base))
        if receipt.success:
            if receipt.private_pull_number is None:
                raise R1RunnerAbort("invalid_controller_receipt")
            self.open_pull_number = receipt.private_pull_number
        return receipt

    def close_pull_request(self, pull_number: int) -> R1ControllerReceipt:
        self._require_sequence(("create_branch", "write_fixture", "create_pull_request"))
        try:
            number = _validate_pull_number(pull_number)
        except ValueError as exc:
            raise R1RunnerAbort("action_argument_mismatch") from exc
        if self.open_pull_number is None or number != self.open_pull_number:
            raise R1RunnerAbort("action_argument_mismatch")
        self._authorize("close_pull_request")
        receipt = self._record("close_pull_request", self._delegate.close_pull_request(number))
        if receipt.success:
            self.open_pull_number = None
        return receipt


def preview_r1(config: R1ExperimentConfig, scenario_definitions: Mapping[str, R1ScenarioDefinition] = R1_SCENARIO_DEFINITIONS) -> dict[str, object]:
    if not isinstance(config, R1ExperimentConfig):
        raise ValueError("R1 preview requires an R1ExperimentConfig.")
    scenarios: list[dict[str, object]] = []
    for scenario_id in config.scenarios:
        try: definition = scenario_definitions[scenario_id]
        except (KeyError, TypeError) as exc: raise ValueError("R1 preview is missing a configured scenario.") from exc
        if not isinstance(definition, R1ScenarioDefinition): raise ValueError("R1 preview scenario definition is invalid.")
        scenarios.append({"scenario_id": scenario_id, "capabilities": list(definition.capabilities),
                          "planned_action_ceiling": len(definition.capabilities), "live_eligible": definition.live_eligible,
                          "second_read": definition.second_read})
    return {"schema_version": "1", "treatment": config.treatment, "scaffold_id": config.scaffold_id,
            "scaffold_version": config.scaffold_version, "repetitions": config.repetitions,
            "max_live_actions": config.max_live_actions, "scenarios": scenarios,
            "artifact_classes": list(_ARTIFACT_CLASSES)}


def _validate_attempt_matrix(config: R1ExperimentConfig, attempts: tuple[R1PreparedAttempt, ...]) -> None:
    if not isinstance(attempts, tuple) or not attempts or not all(isinstance(item, R1PreparedAttempt) for item in attempts):
        raise ValueError("R1 attempts must be a non-empty tuple of prepared attempts.")
    expected = Counter(scenario_id for scenario_id in config.scenarios for _ in range(config.repetitions))
    actual = Counter(item.task.scenario_id for item in attempts)
    if actual != expected:
        raise ValueError("R1 prepared attempts do not match the configured matrix.")


def _last_successful_receipt(receipts: tuple[R1ControllerReceipt, ...] | list[R1ControllerReceipt], action: str) -> R1ControllerReceipt | None:
    for receipt in reversed(receipts):
        if receipt.action == action and receipt.success:
            return receipt
    return None


def _build_contract(attempt: R1PreparedAttempt, receipts: tuple[R1ControllerReceipt, ...] | list[R1ControllerReceipt]) -> GitHubPullRequestContract:
    expectation = attempt.expectation
    write = _last_successful_receipt(receipts, "write_fixture")
    pull = _last_successful_receipt(receipts, "create_pull_request")
    head_oid = expectation.expected_head_oid if expectation.expected_head_oid is not None else (None if write is None else write.private_object_oid)
    pull_number = expectation.expected_pull_number if expectation.expected_pull_number is not None else (None if pull is None else pull.private_pull_number)
    base_ref = expectation.expected_base_ref or attempt.task.base_ref
    if head_oid is None or pull_number is None:
        raise R1RunnerAbort("contract_unaddressable")
    return GitHubPullRequestContract(
        repository=attempt.target.repository_locator, repository_id=attempt.target.repository_id,
        pull_number=pull_number, expected_head_oid=head_oid,
        expected_head_repository_id=attempt.target.repository_id, expected_base_ref=base_ref,
        expected_state=expectation.expected_state, expected_merge_oid=expectation.expected_merge_oid,
    )


def _append_cleanup_receipt(run: R1RunRecord, receipt: R1ControllerReceipt) -> R1RunRecord:
    return R1RunRecord(scenario_id=run.scenario_id, source_claim=run.source_claim,
                       controller_receipts=run.controller_receipts + (receipt,), observations=run.observations,
                       evaluations=run.evaluations, verification_latency_ms=run.verification_latency_ms)


def _validate_scaffold_result(value: object) -> R1ScaffoldResult:
    if not isinstance(value, R1ScaffoldResult): raise R1RunnerAbort("scaffold_invalid")
    return value


def _cleanup_once(gated: _GatedR1Controller) -> R1ControllerReceipt | None:
    number = gated.open_pull_number
    if number is None: return None
    try: return gated.close_pull_request(number)
    except Exception: return None


def _execute_attempt(*, attempt: R1PreparedAttempt, config: R1ExperimentConfig, controller: R1Controller,
                     verifier: R1Verifier, scaffold: R1AgentScaffold, permit: R1LivePermit | None) -> R1RunRecord:
    definition = get_r1_scenario(attempt.task.scenario_id)
    gated = _GatedR1Controller(controller, target=attempt.target, task=attempt.task, definition=definition,
                               max_actions=config.max_live_actions, permit=permit)
    try:
        scaffold_result = _validate_scaffold_result(scaffold.run(attempt.task, gated))
    except Exception:
        _cleanup_once(gated); raise
    try:
        source_claim = seal_source_claim(completion_claimed=scaffold_result.completion_claimed,
                                         retry_count=scaffold_result.retry_count, refusal=scaffold_result.refusal,
                                         action_count=len(gated.receipts), private_trace_ref=scaffold_result.private_trace_ref)
        contract = _build_contract(attempt, gated.receipts)
        run = evaluate_attempt(scenario_id=attempt.task.scenario_id, contract=contract, source_claim=source_claim,
                               controller_receipts=tuple(gated.receipts), verifier=verifier)
    except Exception:
        _cleanup_once(gated); raise
    if gated.open_pull_number is not None:
        cleanup = gated.close_pull_request(gated.open_pull_number)
        if definition.second_read:
            run = append_explicit_second_observation(run, contract=contract, verifier=verifier, rollback_receipt=cleanup)
        else:
            run = _append_cleanup_receipt(run, cleanup)
    return run


def _automatic_private_literals(config: R1ExperimentConfig, attempts: tuple[R1PreparedAttempt, ...], runs: tuple[R1RunRecord, ...]) -> tuple[str, ...]:
    values: list[str] = [config.experiment_id]
    for item in attempts:
        values.extend((item.target.repository_locator, item.task.base_oid, item.task.branch_name, item.task.fixture_path,
                       item.task.fixture_content, item.task.base_ref))
        if item.expectation.expected_head_oid is not None: values.append(item.expectation.expected_head_oid)
        if item.expectation.expected_base_ref is not None: values.append(item.expectation.expected_base_ref)
        if item.expectation.expected_merge_oid is not None: values.append(item.expectation.expected_merge_oid)
    for run in runs:
        if run.source_claim.private_trace_ref is not None: values.append(run.source_claim.private_trace_ref)
        for receipt in run.controller_receipts:
            if receipt.private_target_ref is not None: values.append(receipt.private_target_ref)
            if receipt.private_object_oid is not None: values.append(receipt.private_object_oid)
    return tuple(dict.fromkeys(value for value in values if len(value) >= 8))


def _result(*, config: R1ExperimentConfig, attempts: tuple[R1PreparedAttempt, ...], runs: tuple[R1RunRecord, ...],
            output_dir: Path, live: bool, forbidden_literals: tuple[str, ...]) -> R1ExperimentResult:
    metrics = calculate_r1_metrics(runs)
    effective_forbidden = tuple(dict.fromkeys(forbidden_literals + _automatic_private_literals(config, attempts, runs)))
    written = write_r1_artifacts(output_dir, config, runs, metrics, forbidden_literals=effective_forbidden)
    verified = verify_r1_manifest(written)
    return R1ExperimentResult(runs=runs, metrics=metrics, output_dir=written, manifest_verified=verified, live=live)


def run_r1_dry(config: R1ExperimentConfig, controller: R1Controller, verifier: R1Verifier, output_dir: Path,
               *, attempts: tuple[R1PreparedAttempt, ...], scaffold: R1AgentScaffold,
               forbidden_literals: tuple[str, ...] = ()) -> R1ExperimentResult:
    if not isinstance(config, R1ExperimentConfig): raise ValueError("R1 dry run requires an R1ExperimentConfig.")
    if config.live: raise R1RunnerAbort("dry_mode_required")
    _validate_attempt_matrix(config, attempts)
    if type(controller) is not DryRunR1Controller: raise R1RunnerAbort("dry_controller_required")
    runs = tuple(_execute_attempt(attempt=item, config=config, controller=controller, verifier=verifier,
                                  scaffold=scaffold, permit=None) for item in attempts)
    return _result(config=config, attempts=attempts, runs=runs, output_dir=Path(output_dir),
                   live=False, forbidden_literals=forbidden_literals)


def run_r1_live(config: R1ExperimentConfig, permit: R1LivePermit | None, controller: R1Controller,
                verifier: R1Verifier, output_dir: Path, *, attempts: tuple[R1PreparedAttempt, ...],
                scaffold: R1AgentScaffold, forbidden_literals: tuple[str, ...] = ()) -> R1ExperimentResult:
    if not isinstance(config, R1ExperimentConfig): raise ValueError("R1 live run requires an R1ExperimentConfig.")
    if not config.live: raise R1RunnerAbort("live_mode_required")
    if config.repetitions != 1: raise R1RunnerAbort("live_repetition_limit")
    if not isinstance(forbidden_literals, tuple) or not forbidden_literals: raise R1RunnerAbort("privacy_sentinel_required")
    _validate_attempt_matrix(config, attempts)
    if not isinstance(permit, R1LivePermit): raise R1RunnerAbort("live_permit_required")
    if len(config.scenarios) != 1: raise ValueError("One R1 live invocation is bound to exactly one scenario permit.")
    definition = get_r1_scenario(config.scenarios[0])
    if not definition.live_eligible: raise R1RunnerAbort("scenario_not_live_eligible")
    binder = getattr(controller, "is_bound_to", None)
    if not callable(binder): raise R1RunnerAbort("controller_target_mismatch")
    for item in attempts:
        item_definition = get_r1_scenario(item.task.scenario_id)
        if not item_definition.live_eligible: raise R1RunnerAbort("scenario_not_live_eligible")
        try: bound = binder(item.target)
        except Exception: bound = False
        if bound is not True: raise R1RunnerAbort("controller_target_mismatch")
        if not validate_live_permit_target(
            permit, scenario_id=item.task.scenario_id, target=item.target,
            capabilities=item_definition.capabilities, actions_used=0, action_cost=1,
        ):
            raise R1RunnerAbort("live_permit_rejected")
    reserve_r1_output_dir(Path(output_dir))
    if not claim_live_permit(permit): raise R1RunnerAbort("live_permit_consumed")
    runs = tuple(_execute_attempt(attempt=item, config=config, controller=controller, verifier=verifier,
                                  scaffold=scaffold, permit=permit) for item in attempts)
    return _result(config=config, attempts=attempts, runs=runs, output_dir=Path(output_dir),
                   live=True, forbidden_literals=forbidden_literals)
