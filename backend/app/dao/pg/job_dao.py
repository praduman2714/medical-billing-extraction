from __future__ import annotations
import uuid
from sqlalchemy import select
from app.core.common.time import utc_now
from app.core.context_manager import ContextManager, current_user_id_ctx
from app.core.common.id.short_id import generate_id
from app.dao.base_pg_dao import BasePgDAO
from app.dao.models.job import Job


class JobDAO(BasePgDAO[Job]):
    """Data access for the jobs table.

    All SQL lives here. No business logic — status transition rules
    belong in JobService, not here.
    """

    def __init__(self, context_manager: ContextManager) -> None:
        super().__init__(context_manager, Job)

    def _to_orm(self, data: dict) -> Job:
        """Build a Job ORM instance from a plain dict."""
        return Job(
            id=data.get("id"),
            user_id=data.get("user_id"),
            pdf_filename=data.get("pdf_filename"),
            pdf_path=data.get("pdf_path"),
            pdf_hash=data.get("pdf_hash"),
            status=data.get("status", "pending"),
            result=data.get("result"),
            error=data.get("error"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            token_usage=data.get("token_usage"),
            cost_usd=data.get("cost_usd"),
            processing_duration_seconds=data.get("processing_duration_seconds"),
        )

    def _to_dto(self, orm: Job) -> dict:
        """Convert a Job ORM instance to a plain dict."""
        return {
            "id": orm.id,
            "user_id": orm.user_id,
            "pdf_filename": orm.pdf_filename,
            "pdf_path": orm.pdf_path,
            "pdf_hash": orm.pdf_hash,
            "status": orm.status,
            "result": orm.result,
            "error": orm.error,
            "started_at": orm.started_at,
            "completed_at": orm.completed_at,
            "created_at": orm.created_at,
            "updated_at": orm.updated_at,
            "token_usage": orm.token_usage,
            "cost_usd": orm.cost_usd,
            "processing_duration_seconds": orm.processing_duration_seconds,
        }

    def _apply_filters(self, query, filters: dict):
        """Apply optional status and search filters to a select query."""
        if "status" in filters and filters["status"] is not None:
            query = query.where(Job.status == filters["status"])
        if "pdf_hash" in filters and filters["pdf_hash"] is not None:
            query = query.where(Job.pdf_hash == filters["pdf_hash"])
        if "user_id" in filters and filters["user_id"] is not None:
            query = query.where(Job.user_id == filters["user_id"])
        return query

    async def create(self, pdf_filename: str, pdf_path: str, pdf_hash: str | None = None, job_id: str | None = None) -> dict:
        """Insert a new job with status=pending. Returns the created job as a dict."""
        user_id = current_user_id_ctx.get()
        if not user_id:
            raise ValueError("No authenticated user in context for job creation")
        
        job = Job(
            id=job_id or generate_id(prefix="job"),
            user_id=user_id,
            pdf_filename=pdf_filename,
            pdf_path=pdf_path,
            pdf_hash=pdf_hash,
            status="pending",
        )
        created = await self._create(job)
        return self._to_dto(created)

    async def get(self, job_id: str) -> dict | None:
        """Return a job by ID, or None if not found."""
        orm = await self._get_by_id(job_id)
        return self._to_dto(orm) if orm else None

    async def list(self, status: str | None = None) -> list[dict]:
        """Return all jobs ordered by created_at desc. Optionally filter by status."""
        filters = {}
        if status:
            filters["status"] = status
        orms = await self._get_all(filters=filters, order_by=Job.created_at.desc())
        return [self._to_dto(orm) for orm in orms]

    async def get_active(self) -> list[dict]:
        """Return all jobs currently in processing status, or an empty list if all workers are idle."""
        filters = {"status": "processing"}
        orms = await self._get_all(filters=filters, order_by=Job.created_at.desc())
        return [self._to_dto(orm) for orm in orms]

    async def update_status(
        self,
        job_id: str,
        status: str,
        result: dict | None = None,
        error: str | None = None,
        token_usage: dict | None = None,
        cost_usd: float | None = None,
        processing_duration_seconds: float | None = None,
    ) -> dict | None:
        """Update job status and optionally write result, error, or metrics.

        Always update updated_at when calling this method.
        Returns the updated job as a dict, or None if job not found.
        """
        orm = await self._get_by_id(job_id)
        if not orm:
            return None
        
        orm.status = status
        if result is not None:
            orm.result = result
        if error is not None:
            orm.error = error
        if token_usage is not None:
            orm.token_usage = token_usage
        if cost_usd is not None:
            orm.cost_usd = cost_usd
        if processing_duration_seconds is not None:
            orm.processing_duration_seconds = processing_duration_seconds
        
        if status == "processing" and orm.started_at is None:
            orm.started_at = utc_now()
        elif status in ("completed", "failed", "cancelled") and orm.completed_at is None:
            orm.completed_at = utc_now()
            
        updated = await self._update(orm)
        return self._to_dto(updated)

    async def cancel(self, job_id: str) -> bool:
        """Set a pending job to cancelled.

        Returns True if cancelled, False if job was not in pending status.
        Must be a no-op (return False, not raise) if job does not exist.
        """
        orm = await self._get_by_id(job_id)
        if not orm:
            return False
        if orm.status != "pending":
            return False
        
        orm.status = "cancelled"
        orm.completed_at = utc_now()
        await self._update(orm)
        return True

    async def reprocess(self, job_id: str) -> dict | None:
        """Reset a job back to pending status, clearing errors and results."""
        orm = await self._get_by_id(job_id)
        if not orm:
            return None
        
        orm.status = "pending"
        orm.result = None
        orm.error = None
        orm.token_usage = None
        orm.cost_usd = None
        orm.processing_duration_seconds = None
        orm.started_at = None
        orm.completed_at = None
        orm.updated_at = utc_now()
        
        updated = await self._update(orm)
        return self._to_dto(updated)


    async def claim_next_job(self) -> dict | None:
        """Atomically claim the next pending job for processing.

        Must guarantee that multiple concurrent workers never claim the same
        job. The implementation must be safe under concurrent access.

        Returns the claimed job with status already set to 'processing',
        or None if the queue is empty.
        """
        async with self.context_manager.session() as session:
            stmt = (
                select(Job)
                .where(Job.status == "pending")
                .order_by(Job.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            job = result.scalar_one_or_none()
            if job:
                job.status = "processing"
                job.started_at = utc_now()
                job.updated_at = utc_now()
                await session.flush()
                return self._to_dto(job)
            return None

    async def recover_stalled(self, timeout_minutes: int = 5) -> int:
        """Reset jobs stuck in processing back to pending.

        A job is stalled if its started_at is older than timeout_minutes
        and it is still in processing status. This recovers jobs from a
        worker that crashed before writing a completed or failed status.

        Returns the number of jobs recovered.
        """
        from datetime import timedelta
        cutoff = utc_now() - timedelta(minutes=timeout_minutes)
        async with self.context_manager.session() as session:
            stmt = (
                select(Job)
                .where(Job.status == "processing")
                .where(Job.started_at < cutoff)
            )
            result = await session.execute(stmt)
            stalled_jobs = result.scalars().all()
            count = 0
            for job in stalled_jobs:
                job.status = "pending"
                job.started_at = None
                job.updated_at = utc_now()
                count += 1
            await session.flush()
            return count

    async def get_completed_by_hash(self, pdf_hash: str) -> dict | None:
        """Return a completed job by its PDF hash, if any exists for the current user."""
        filters = {"status": "completed", "pdf_hash": pdf_hash}
        orms = await self._get_all(filters=filters, limit=1)
        return self._to_dto(orms[0]) if orms else None

