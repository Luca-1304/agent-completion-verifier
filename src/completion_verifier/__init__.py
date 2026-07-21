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

__version__ = "0.3.0"

__all__ = [
    "AdaptedEvent",
    "BenchmarkMetrics",
    "GenericJsonTraceAdapter",
    "OpenAIToolTraceAdapter",
    "TraceAdapter",
    "TraceAdapterError",
    "TraceEnvelope",
    "TraceSource",
    "Case",
    "Event",
    "Evaluation",
    "Requirement",
    "Status",
    "calculate_metrics",
    "canonical_json_sha256",
    "evaluate_case",
    "evaluate_cases",
]
