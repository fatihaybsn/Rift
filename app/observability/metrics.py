"""Application metrics for run orchestration outcomes."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

ANALYSIS_RUNS_TOTAL = Counter(
    "analysis_runs_total",
    "Total run processing attempts by outcome.",
    labelnames=("outcome",),
)
ANALYSIS_DURATION_SECONDS = Histogram(
    "analysis_duration_seconds",
    "Run processing duration in seconds by outcome.",
    labelnames=("outcome",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120),
)
SPEC_VALIDATION_FAILURES_TOTAL = Counter(
    "spec_validation_failures_total",
    "Total spec validation stage failures by spec side and error code.",
    labelnames=("spec_side", "error_code"),
)
BREAKING_CHANGES_TOTAL = Counter(
    "breaking_changes_total",
    "Total number of breaking deterministic findings produced by completed runs.",
)
REPORT_GENERATION_FAILURES_TOTAL = Counter(
    "report_generation_failures_total",
    "Total report generation failures by error code.",
    labelnames=("error_code",),
)


def record_run_success(*, duration_seconds: float, breaking_change_count: int) -> None:
    """Record counters/histogram for a completed run."""
    ANALYSIS_RUNS_TOTAL.labels(outcome="success").inc()
    ANALYSIS_DURATION_SECONDS.labels(outcome="success").observe(duration_seconds)
    BREAKING_CHANGES_TOTAL.inc(max(0, breaking_change_count))


def record_run_failure(*, duration_seconds: float, failure_stage: str, error_code: str) -> None:
    """Record counters/histogram for a failed run."""
    ANALYSIS_RUNS_TOTAL.labels(outcome="failure").inc()
    ANALYSIS_DURATION_SECONDS.labels(outcome="failure").observe(duration_seconds)
    normalized_error_code = error_code or "unknown"
    stage = failure_stage or "unknown"

    if stage in {"validate_spec_old", "validate_spec_new"}:
        side = "old" if stage.endswith("_old") else "new"
        SPEC_VALIDATION_FAILURES_TOTAL.labels(
            spec_side=side,
            error_code=normalized_error_code,
        ).inc()

    if stage in {"persist_results", "persist_report"}:
        REPORT_GENERATION_FAILURES_TOTAL.labels(error_code=normalized_error_code).inc()


def collect_metrics_payload() -> bytes:
    """Collect Prometheus metrics payload."""
    return generate_latest()


def metrics_content_type() -> str:
    """Return Prometheus content type."""
    return CONTENT_TYPE_LATEST

