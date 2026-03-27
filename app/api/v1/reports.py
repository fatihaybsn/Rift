"""Report retrieval endpoints."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import AnalysisRun, DeterministicFinding, MigrationTask, get_db_session

reports_router = APIRouter(prefix="/reports", tags=["reports"])
DB_SESSION_DEP = Depends(get_db_session)


class ReportFormat(StrEnum):
    """Supported response formats for report retrieval."""

    JSON = "json"
    MARKDOWN = "markdown"


ReportFormatQueryParam = Annotated[ReportFormat, Query()]


class SeverityBreakdown(BaseModel):
    """Stable severity count structure for report responses."""

    high: int
    medium: int
    low: int


class CategoryCount(BaseModel):
    """Count of findings for one category."""

    category: str
    count: int


class SummaryCounts(BaseModel):
    """Aggregate report counters."""

    total_findings: int
    findings_by_category: list[CategoryCount]


class ReportMetadata(BaseModel):
    """Lifecycle metadata copied from the authoritative run record."""

    created_at: datetime
    updated_at: datetime
    processing_started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    attempt_count: int


class ReportFindingItem(BaseModel):
    """Stable finding shape for read/report surface."""

    order: int
    key: str
    category: str
    code: str | None
    location: str
    http_method: str | None
    severity: str
    compatibility: str | None
    title: str
    detail: str | None


class ReportCategoryFindingGroup(BaseModel):
    """Category-grouped findings inside one severity bucket."""

    category: str
    count: int
    items: list[ReportFindingItem]


class ReportSeverityFindingGroup(BaseModel):
    """Severity-grouped findings containing category buckets."""

    severity: str
    count: int
    categories: list[ReportCategoryFindingGroup]


class ChangelogTaskItem(BaseModel):
    """Read model for migration/changelog task entries."""

    id: uuid.UUID
    finding_id: uuid.UUID | None
    source: str
    status: str
    title: str
    detail: str
    priority: int
    created_at: datetime
    updated_at: datetime


class ChangelogTasksSection(BaseModel):
    """Optional placeholder for changelog-derived tasks."""

    note: str
    items: list[ChangelogTaskItem] = Field(default_factory=list)


class ReportReadResponse(BaseModel):
    """Stable report payload returned to API clients."""

    report_id: uuid.UUID
    run_id: uuid.UUID
    status: str
    metadata: ReportMetadata
    summary_counts: SummaryCounts
    severity_breakdown: SeverityBreakdown
    findings_grouped: list[ReportSeverityFindingGroup]
    changelog_tasks: ChangelogTasksSection


def _get_run_or_404(*, db: Session, run_id: uuid.UUID) -> AnalysisRun:
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} was not found.",
        )
    return run


def _load_findings(*, db: Session, run_id: uuid.UUID) -> list[DeterministicFinding]:
    return (
        db.execute(
            select(DeterministicFinding)
            .where(DeterministicFinding.run_id == run_id)
            .order_by(DeterministicFinding.finding_order, DeterministicFinding.finding_key)
        )
        .scalars()
        .all()
    )


def _load_changelog_tasks(*, db: Session, run_id: uuid.UUID) -> list[MigrationTask]:
    return (
        db.execute(
            select(MigrationTask)
            .where(MigrationTask.run_id == run_id)
            .order_by(MigrationTask.priority, MigrationTask.created_at, MigrationTask.id)
        )
        .scalars()
        .all()
    )


def _to_report_finding_item(finding: DeterministicFinding) -> ReportFindingItem:
    metadata = finding.metadata_json
    compatibility_raw = metadata.get("compatibility")
    code_raw = metadata.get("code")
    compatibility = str(compatibility_raw) if compatibility_raw is not None else None
    code = str(code_raw) if code_raw is not None else None
    return ReportFindingItem(
        order=finding.finding_order,
        key=finding.finding_key,
        category=finding.category,
        code=code,
        location=finding.location,
        http_method=finding.http_method,
        severity=finding.severity,
        compatibility=compatibility,
        title=finding.title,
        detail=finding.detail,
    )


def _build_report_response(
    *,
    run: AnalysisRun,
    findings: list[DeterministicFinding],
    changelog_tasks: list[MigrationTask],
) -> ReportReadResponse:
    grouped_items: dict[str, dict[str, list[ReportFindingItem]]] = defaultdict(
        lambda: defaultdict(list)
    )
    severity_counts = {"high": 0, "medium": 0, "low": 0}
    category_totals: dict[str, int] = defaultdict(int)

    for finding in findings:
        finding_item = _to_report_finding_item(finding)
        if finding_item.severity in severity_counts:
            severity_counts[finding_item.severity] += 1
        grouped_items[finding_item.severity][finding_item.category].append(finding_item)
        category_totals[finding_item.category] += 1

    severity_order = ("high", "medium", "low")
    unknown_severity_levels = sorted(
        level for level in grouped_items if level not in severity_order
    )
    ordered_severity_levels = [
        *[level for level in severity_order if level in grouped_items],
        *unknown_severity_levels,
    ]

    findings_grouped: list[ReportSeverityFindingGroup] = []
    for severity in ordered_severity_levels:
        category_map = grouped_items[severity]
        category_groups = [
            ReportCategoryFindingGroup(
                category=category,
                count=len(category_map[category]),
                items=category_map[category],
            )
            for category in sorted(category_map)
        ]
        findings_grouped.append(
            ReportSeverityFindingGroup(
                severity=severity,
                count=sum(group.count for group in category_groups),
                categories=category_groups,
            )
        )

    category_counts = [
        CategoryCount(category=category, count=category_totals[category])
        for category in sorted(category_totals)
    ]

    task_items = [
        ChangelogTaskItem(
            id=task.id,
            finding_id=task.finding_id,
            source=task.source,
            status=task.status,
            title=task.title,
            detail=task.detail,
            priority=task.priority,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in changelog_tasks
    ]

    return ReportReadResponse(
        report_id=run.id,
        run_id=run.id,
        status=run.status,
        metadata=ReportMetadata(
            created_at=run.created_at,
            updated_at=run.updated_at,
            processing_started_at=run.processing_started_at,
            completed_at=run.completed_at,
            failed_at=run.failed_at,
            attempt_count=run.attempt_count,
        ),
        summary_counts=SummaryCounts(
            total_findings=len(findings),
            findings_by_category=category_counts,
        ),
        severity_breakdown=SeverityBreakdown(
            high=severity_counts["high"],
            medium=severity_counts["medium"],
            low=severity_counts["low"],
        ),
        findings_grouped=findings_grouped,
        changelog_tasks=ChangelogTasksSection(
            note=(
                "Placeholder section for changelog-derived tasks. "
                "Deterministic findings remain authoritative."
            ),
            items=task_items,
        ),
    )


def _render_report_markdown(report: ReportReadResponse) -> str:
    lines = [
        "# API Change Radar Report",
        "",
        f"- Report ID: `{report.report_id}`",
        f"- Run ID: `{report.run_id}`",
        f"- Status: `{report.status}`",
        f"- Created At: `{report.metadata.created_at.isoformat()}`",
        f"- Updated At: `{report.metadata.updated_at.isoformat()}`",
        "",
        "## Summary Counts",
        f"- Total findings: {report.summary_counts.total_findings}",
        f"- High: {report.severity_breakdown.high}",
        f"- Medium: {report.severity_breakdown.medium}",
        f"- Low: {report.severity_breakdown.low}",
        "",
        "## Findings Grouped by Severity and Category",
    ]

    if not report.findings_grouped:
        lines.append("_No findings recorded for this run._")
    else:
        for severity_group in report.findings_grouped:
            lines.extend(
                [
                    "",
                    f"### {severity_group.severity.upper()} ({severity_group.count})",
                ]
            )
            for category_group in severity_group.categories:
                lines.append(f"#### {category_group.category} ({category_group.count})")
                for index, finding in enumerate(category_group.items, start=1):
                    lines.append(
                        f"{index}. **[{finding.severity.upper()}]** "
                        f"`{finding.code or 'unknown'}` at `{finding.location}`"
                    )
                    lines.append(f"   - Key: `{finding.key}`")
                    if finding.http_method is not None:
                        lines.append(f"   - Method: `{finding.http_method}`")
                    if finding.compatibility is not None:
                        lines.append(f"   - Compatibility: `{finding.compatibility}`")
                    lines.append(f"   - Title: {finding.title}")
                    if finding.detail is not None:
                        lines.append(f"   - Detail: {finding.detail}")

    lines.extend(
        [
            "",
            "## Changelog-derived Tasks (Placeholder)",
            report.changelog_tasks.note,
        ]
    )
    if not report.changelog_tasks.items:
        lines.append("_No changelog-derived tasks yet._")
    else:
        for index, task in enumerate(report.changelog_tasks.items, start=1):
            lines.append(
                f"{index}. [priority={task.priority}] {task.title} "
                f"(source={task.source}, status={task.status})"
            )
            lines.append(f"   - Task ID: `{task.id}`")
            if task.finding_id is not None:
                lines.append(f"   - Related finding: `{task.finding_id}`")
            lines.append(f"   - Detail: {task.detail}")
    return "\n".join(lines)


@reports_router.get(
    "/{report_id}",
    response_model=ReportReadResponse,
    responses={200: {"content": {"text/markdown": {}}}},
)
def get_report(
    report_id: uuid.UUID,
    format: ReportFormatQueryParam = ReportFormat.JSON,
    db: Session = DB_SESSION_DEP,
) -> ReportReadResponse | PlainTextResponse:
    """Fetch one report in JSON (default) or markdown format."""
    run = _get_run_or_404(db=db, run_id=report_id)
    findings = _load_findings(db=db, run_id=report_id)
    changelog_tasks = _load_changelog_tasks(db=db, run_id=report_id)
    response_payload = _build_report_response(
        run=run,
        findings=findings,
        changelog_tasks=changelog_tasks,
    )

    if format is ReportFormat.MARKDOWN:
        return PlainTextResponse(
            content=_render_report_markdown(response_payload),
            media_type="text/markdown",
        )
    return response_payload

