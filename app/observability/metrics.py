"""Application metrics for run orchestration outcomes."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

RUN_TOTAL = Counter(
    "api_change_radar_runs_total",
    "Total run processing attempts by outcome.",
    labelnames=("outcome",),
)
RUN_FAILURE_TOTAL = Counter(
    "api_change_radar_run_failures_total",
    "Total failed runs by failure stage and error code.",
    labelnames=("failure_stage", "error_code"),
)
BREAKING_FINDINGS_TOTAL = Counter(
    "api_change_radar_breaking_findings_total",
    "Total number of breaking deterministic findings produced by completed runs.",
)
RUN_DURATION_SECONDS = Histogram(
    "api_change_radar_run_duration_seconds",
    "Run processing duration in seconds by outcome.",
    labelnames=("outcome",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120),
)


def record_run_success(*, duration_seconds: float, breaking_change_count: int) -> None:
    """Record counters/histogram for a completed run."""
    RUN_TOTAL.labels(outcome="success").inc()
    RUN_DURATION_SECONDS.labels(outcome="success").observe(duration_seconds)
    BREAKING_FINDINGS_TOTAL.inc(max(0, breaking_change_count))


def record_run_failure(*, duration_seconds: float, failure_stage: str, error_code: str) -> None:
    """Record counters/histogram for a failed run."""
    RUN_TOTAL.labels(outcome="failure").inc()
    RUN_DURATION_SECONDS.labels(outcome="failure").observe(duration_seconds)
    RUN_FAILURE_TOTAL.labels(
        failure_stage=failure_stage or "unknown",
        error_code=error_code or "unknown",
    ).inc()


def collect_metrics_payload() -> bytes:
    """Collect Prometheus metrics payload."""
    return generate_latest()


def metrics_content_type() -> str:
    """Return Prometheus content type."""
    return CONTENT_TYPE_LATEST

