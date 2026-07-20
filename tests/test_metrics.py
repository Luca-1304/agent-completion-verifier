import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from completion_verifier.cli import main
from completion_verifier.evaluator import evaluate_cases
from completion_verifier.metrics import calculate_metrics
from completion_verifier.models import Case, Evaluation, Event, Requirement, Status


def case(
    case_id: str,
    *,
    claimed: bool,
    requirements: tuple[Requirement, ...] | None = None,
    events: tuple[Event, ...] = (),
) -> Case:
    return Case(
        case_id=case_id,
        task="Test task",
        completion_claimed=claimed,
        requirements=requirements or (Requirement("act", ("receipt",)),),
        events=events,
    )


class MetricsTests(unittest.TestCase):
    def test_counts_claim_quality_and_statuses(self) -> None:
        cases = [
            case(
                "verified_claim",
                claimed=True,
                events=(Event("act", True, {"receipt": "1"}),),
            ),
            case("unsupported_claim", claimed=True),
            case(
                "silent_verified",
                claimed=False,
                events=(Event("act", True, {"receipt": "2"}),),
            ),
            case("failed_claim", claimed=True, events=(Event("act", False, {}),)),
        ]
        metrics = calculate_metrics(cases, evaluate_cases(cases))

        self.assertEqual(metrics.total_cases, 4)
        self.assertEqual(metrics.claimed_completion_cases, 3)
        self.assertEqual(metrics.verified_complete_cases, 2)
        self.assertEqual(metrics.verified_claim_cases, 1)
        self.assertEqual(metrics.false_completion_cases, 2)
        self.assertEqual(metrics.unsupported_claim_cases, 1)
        self.assertEqual(metrics.failed_claim_cases, 1)
        self.assertEqual(metrics.silent_verified_cases, 1)
        self.assertAlmostEqual(metrics.false_completion_rate, 2 / 3)
        self.assertAlmostEqual(metrics.completion_claim_precision, 1 / 3)

    def test_no_claims_have_zero_claim_rates(self) -> None:
        cases = [case("unclaimed", claimed=False)]
        metrics = calculate_metrics(cases, evaluate_cases(cases))
        self.assertEqual(metrics.false_completion_rate, 0.0)
        self.assertEqual(metrics.completion_claim_precision, 0.0)

    def test_recovery_is_detected(self) -> None:
        cases = [
            case(
                "recovered",
                claimed=True,
                events=(
                    Event("act", False, {}, 0),
                    Event("act", True, {"receipt": "ok"}, 1),
                ),
            )
        ]
        metrics = calculate_metrics(cases, evaluate_cases(cases))
        self.assertEqual(metrics.recovered_cases, 1)
        self.assertEqual(metrics.regressed_cases, 0)

    def test_regression_is_detected(self) -> None:
        cases = [
            case(
                "regressed",
                claimed=True,
                events=(
                    Event("act", True, {"receipt": "ok"}, 0),
                    Event("act", False, {}, 1),
                ),
            )
        ]
        metrics = calculate_metrics(cases, evaluate_cases(cases))
        self.assertEqual(metrics.recovered_cases, 0)
        self.assertEqual(metrics.regressed_cases, 1)

    def test_success_without_required_evidence_is_not_recovery_source(self) -> None:
        cases = [
            case(
                "not_a_regression",
                claimed=True,
                events=(
                    Event("act", True, {}, 0),
                    Event("act", False, {}, 1),
                ),
            )
        ]
        metrics = calculate_metrics(cases, evaluate_cases(cases))
        self.assertEqual(metrics.regressed_cases, 0)

    def test_partial_claim_is_counted(self) -> None:
        requirements = (
            Requirement("first", ("id",)),
            Requirement("second", ("id",)),
        )
        cases = [
            case(
                "partial",
                claimed=True,
                requirements=requirements,
                events=(Event("first", True, {"id": "1"}),),
            )
        ]
        metrics = calculate_metrics(cases, evaluate_cases(cases))
        self.assertEqual(metrics.partial_claim_cases, 1)
        self.assertEqual(metrics.false_completion_cases, 1)

    def test_mismatched_case_and_evaluation_ids_are_rejected(self) -> None:
        cases = [case("case-a", claimed=False)]
        evaluations = [
            Evaluation("case-b", Status.UNVERIFIED, (), ("act",), (), ())
        ]
        with self.assertRaises(ValueError):
            calculate_metrics(cases, evaluations)

    def test_to_dict_contains_status_counts_and_rates(self) -> None:
        cases = [case("one", claimed=True)]
        payload = calculate_metrics(cases, evaluate_cases(cases)).to_dict()
        self.assertEqual(payload["status_counts"]["UNVERIFIED"], 1)
        self.assertEqual(payload["rates"]["false_completion_rate"], 1.0)
        self.assertEqual(payload["rates"]["completion_claim_precision"], 0.0)

    def test_duplicate_case_ids_are_rejected(self) -> None:
        cases = [case("duplicate", claimed=False), case("duplicate", claimed=True)]
        with self.assertRaises(ValueError):
            calculate_metrics(cases, evaluate_cases(cases))

    def test_cli_metrics_output(self) -> None:
        raw = {
            "case_id": "claim-only",
            "task": "Test task",
            "completion_claimed": True,
            "requirements": [{"action": "act", "evidence_fields": ["receipt"]}],
            "events": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.jsonl"
            path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                with mock.patch(
                    "sys.argv", ["completion-verifier", str(path), "--metrics"]
                ):
                    self.assertEqual(main(), 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["claim_counts"]["false_completion"], 1)
        self.assertEqual(payload["rates"]["false_completion_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
