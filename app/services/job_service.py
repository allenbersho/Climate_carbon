"""Job service managing asynchronous task execution, lifecycles, and background processing."""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import session as db_session
from app.models.job import Job, JobStatus
from app.services.farmer_service import bulk_import_farmers_from_csv

logger = logging.getLogger(__name__)


def create_job(
    db: Session,
    job_type: str,
    payload: dict[str, Any] | None = None,
) -> Job:
    """Create a new job in PENDING status.

    Why: Provides an immediate ticket identifier before asynchronous execution begins.
    Inputs: db (Session), job_type (str), optional payload dictionary
    Outputs: Newly persisted Job record.
    """
    job = Job(
        job_type=job_type,
        status=JobStatus.PENDING,
        payload=payload,
        error_message=None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job_by_id(db: Session, job_id: int) -> Job | None:
    """Retrieve a single job by its ID.

    Why: Allows clients to poll job status and inspect results or failure reasons.
    Inputs: db (Session), job_id (int)
    Outputs: Job instance or None if not found.
    """
    return db.get(Job, job_id)


def list_jobs(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    status_filter: JobStatus | None = None,
) -> tuple[list[Job], int]:
    """Retrieve a paginated slice of background jobs.

    Why: Administrative observability to monitor running, pending, and completed tasks.
    Inputs: db (Session), page (int), page_size (int), optional status filter
    Outputs: Tuple of (list of Job instances, total count).
    """
    query = select(Job)
    if status_filter:
        query = query.where(Job.status == status_filter)

    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar_one() or 0

    offset = (page - 1) * page_size
    paged_query = (
        query.order_by(Job.created_at.desc(), Job.id.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = list(db.execute(paged_query).scalars().all())

    return items, total


def process_farmer_bulk_import_job(job_id: int, file_content: bytes) -> None:
    """Background task worker that executes farmer CSV bulk import asynchronously.

    Important: Runs after the HTTP response has terminated. It MUST create its
    own database session via SessionLocal() rather than sharing the request's
    closed session.
    Inputs: job_id (int), file_content (raw bytes of uploaded CSV)
    """
    with db_session.SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job:
            logger.error(f"Job {job_id} not found in background worker.")
            return

        # Transition status to PROCESSING
        job.status = JobStatus.PROCESSING
        job.started_at = datetime.now(UTC)
        db.commit()

        try:
            # Delegate to existing resilient CSV bulk import service
            import_result = bulk_import_farmers_from_csv(db, file_content)

            # Mark as COMPLETED with output payload
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            job.result = import_result.model_dump()
            db.commit()
            logger.info(
                f"Job {job_id} completed successfully: "
                f"{import_result.imported_count}/{import_result.total_rows} farmers imported."
            )
        except Exception as exc:
            db.rollback()
            # Reload job to ensure clean state after rollback
            job = db.get(Job, job_id)
            if job:
                job.status = JobStatus.FAILED
                job.completed_at = datetime.now(UTC)
                job.error_message = str(exc)
                db.commit()
            logger.exception(f"Job {job_id} failed with error: {exc}")
