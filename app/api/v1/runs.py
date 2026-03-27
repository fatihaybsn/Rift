"""Run ingestion endpoints."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Final

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import (
    AnalysisRun,
    ArtifactKind,
    RunStatus,
    SpecArtifact,
    get_db_session,
)

runs_router = APIRouter(prefix="/runs", tags=["runs"])

READ_CHUNK_SIZE: Final[int] = 64 * 1024
MAX_SPEC_BYTES: Final[int] = 2 * 1024 * 1024
MAX_CHANGELOG_TEXT_BYTES: Final[int] = 128 * 1024
CHANGELOG_MEDIA_TYPE: Final[str] = "text/plain"

ALLOWED_SPEC_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/json",
        "application/yaml",
        "application/x-yaml",
        "text/yaml",
        "text/x-yaml",
        "application/vnd.oai.openapi+json",
        "application/vnd.oai.openapi+yaml",
        "application/octet-stream",
    }
)

SPEC_FILES_FIELD = File(..., description="Exactly two OpenAPI spec files.")
CHANGELOG_TEXT_FIELD = Form(default=None)
DB_SESSION_DEP = Depends(get_db_session)


class RunCreateResponse(BaseModel):
    """Response payload for run creation."""

    run_id: uuid.UUID
    status: str


class RunReadResponse(BaseModel):
    """Response payload for reading one run."""

    run_id: uuid.UUID
    status: str
    attempt_count: int
    created_at: datetime
    updated_at: datetime
    processing_started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    failure_stage: str | None
    error_code: str | None
    failure_reason: str | None


def _normalize_media_type(content_type: str | None) -> str:
    if content_type is None:
        return ""
    return content_type.split(";", maxsplit=1)[0].strip().lower()


def _validate_spec_media_type(upload_file: UploadFile) -> str:
    normalized_media_type = _normalize_media_type(upload_file.content_type)
    if normalized_media_type not in ALLOWED_SPEC_MEDIA_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported spec content type: {upload_file.content_type!r}.",
        )
    return normalized_media_type


async def _read_upload_bytes(
    upload_file: UploadFile,
    *,
    max_bytes: int,
    field_name: str,
) -> tuple[bytes, str, int]:
    chunks: list[bytes] = []
    checksum = hashlib.sha256()
    byte_size = 0

    while True:
        chunk = await upload_file.read(READ_CHUNK_SIZE)
        if not chunk:
            break
        byte_size += len(chunk)
        if byte_size > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"{field_name} exceeds the {max_bytes} byte limit.",
            )
        chunks.append(chunk)
        checksum.update(chunk)

    if byte_size == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field_name} must not be empty.",
        )

    return b"".join(chunks), checksum.hexdigest(), byte_size


def _build_text_artifact(run_id: uuid.UUID, changelog_text: str) -> SpecArtifact:
    encoded = changelog_text.encode("utf-8")
    byte_size = len(encoded)
    if byte_size > MAX_CHANGELOG_TEXT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"changelog_text exceeds the {MAX_CHANGELOG_TEXT_BYTES} byte limit.",
        )

    return SpecArtifact(
        run_id=run_id,
        kind=ArtifactKind.CHANGELOG_TEXT,
        filename=None,
        media_type=CHANGELOG_MEDIA_TYPE,
        sha256=hashlib.sha256(encoded).hexdigest(),
        byte_size=byte_size,
        payload_bytes=None,
        payload_text=changelog_text,
    )


@runs_router.post("", status_code=status.HTTP_201_CREATED, response_model=RunCreateResponse)
async def create_analysis_run(
    specs: list[UploadFile] = SPEC_FILES_FIELD,
    changelog_text: str | None = CHANGELOG_TEXT_FIELD,
    db: Session = DB_SESSION_DEP,
) -> RunCreateResponse:
    """Create a pending analysis run from raw upload artifacts."""
    if len(specs) != 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Exactly two spec files are required in the specs field.",
        )

    run = AnalysisRun(
        id=uuid.uuid4(),
        status=RunStatus.PENDING.value,
    )
    db.add(run)

    try:
        spec_kinds = (ArtifactKind.OLD_SPEC, ArtifactKind.NEW_SPEC)
        for artifact_kind, upload_file in zip(spec_kinds, specs, strict=True):
            media_type = _validate_spec_media_type(upload_file)
            payload_bytes, sha256, byte_size = await _read_upload_bytes(
                upload_file,
                max_bytes=MAX_SPEC_BYTES,
                field_name=artifact_kind.value,
            )

            spec_artifact = SpecArtifact(
                run_id=run.id,
                kind=artifact_kind,
                filename=upload_file.filename,
                media_type=media_type,
                sha256=sha256,
                byte_size=byte_size,
                payload_bytes=payload_bytes,
                payload_text=None,
            )
            db.add(spec_artifact)

        if changelog_text is not None:
            db.add(_build_text_artifact(run.id, changelog_text))

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create analysis run.",
        ) from exc
    finally:
        for upload_file in specs:
            await upload_file.close()

    return RunCreateResponse(run_id=run.id, status=run.status)


@runs_router.get("/{run_id}", response_model=RunReadResponse)
def get_analysis_run(
    run_id: uuid.UUID,
    db: Session = DB_SESSION_DEP,
) -> RunReadResponse:
    """Fetch lifecycle metadata for one analysis run."""
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} was not found.",
        )

    return RunReadResponse(
        run_id=run.id,
        status=run.status,
        attempt_count=run.attempt_count,
        created_at=run.created_at,
        updated_at=run.updated_at,
        processing_started_at=run.processing_started_at,
        completed_at=run.completed_at,
        failed_at=run.failed_at,
        failure_stage=run.failure_stage,
        error_code=run.error_code,
        failure_reason=run.failure_reason,
    )
