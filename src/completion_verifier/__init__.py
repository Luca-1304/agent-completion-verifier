from .adapters import (
    AdaptedEvent,
    GenericJsonTraceAdapter,
    OpenAIToolTraceAdapter,
    TraceAdapter,
    TraceAdapterError,
    TraceEnvelope,
    TraceSource,
    canonical_json_sha256,
)
from .evaluator import evaluate_case, evaluate_cases
from .metrics import BenchmarkMetrics, calculate_metrics
from .models import Case, Event, Evaluation, Requirement, Status
from .postconditions import (
    DirectoryContract,
    DirectoryVerifier,
    JsonObjectContract,
    JsonObjectVerifier,
    PostconditionContract,
    PostconditionObservation,
    TextFileContract,
    TextFileVerifier,
    evaluate_postcondition,
    postcondition_case,
    verify_postcondition,
)
from .remote import (
    RemoteObservation,
    RemoteOutcome,
    evaluate_remote_observation,
    remote_postcondition_case,
)
from .remote.github import (
    GitHubPullRequestContract,
    GitHubPullRequestSnapshot,
    GitHubReadResult,
    GitHubStateReader,
    evaluate_github_pull_request,
    verify_github_pull_request,
)

__version__ = "0.8.0"

__all__ = [
    "AdaptedEvent",
    "BenchmarkMetrics",
    "Case",
    "DirectoryContract",
    "DirectoryVerifier",
    "Event",
    "Evaluation",
    "GenericJsonTraceAdapter",
    "GitHubPullRequestContract",
    "GitHubPullRequestSnapshot",
    "GitHubReadResult",
    "GitHubStateReader",
    "JsonObjectContract",
    "JsonObjectVerifier",
    "OpenAIToolTraceAdapter",
    "PostconditionContract",
    "PostconditionObservation",
    "RemoteObservation",
    "RemoteOutcome",
    "Requirement",
    "Status",
    "TextFileContract",
    "TextFileVerifier",
    "TraceAdapter",
    "TraceAdapterError",
    "TraceEnvelope",
    "TraceSource",
    "calculate_metrics",
    "canonical_json_sha256",
    "evaluate_case",
    "evaluate_cases",
    "evaluate_github_pull_request",
    "evaluate_postcondition",
    "evaluate_remote_observation",
    "postcondition_case",
    "remote_postcondition_case",
    "verify_github_pull_request",
    "verify_postcondition",
]
