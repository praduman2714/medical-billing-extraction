from app.core.context_manager import ContextManager
from app.dao.pg.job_dao import JobDAO
from app.service.base_service import BaseService
from app.service.exceptions import JobNotFoundException, JobNotCancellableException


class JobService(BaseService):
    """Owns the job lifecycle: creation, status queries, and cancellation.

    All database access goes through JobDAO. This service does not interact
    with the AI layer — that is ExtractionService's responsibility.
    """

    def __init__(self, context_manager: ContextManager) -> None:
        super().__init__(context_manager)
        self.job_dao = JobDAO(context_manager)

    async def create_job(self, pdf_filename: str, pdf_path: str, pdf_hash: str | None = None, job_id: str | None = None) -> dict:
        """Create a new job in pending status. Returns the created job as a dict."""
        return await self.job_dao.create(
            pdf_filename=pdf_filename,
            pdf_path=pdf_path,
            pdf_hash=pdf_hash,
            job_id=job_id,
        )

    async def get_job(self, job_id: str) -> dict:
        """Return a job by ID. Raises JobNotFoundException if not found."""
        job = await self.job_dao.get(job_id)
        if not job:
            raise JobNotFoundException(job_id)
        return job

    async def list_jobs(self, status: str | None = None) -> list[dict]:
        """Return all jobs ordered by created_at desc. Optionally filter by status."""
        return await self.job_dao.list(status=status)

    async def get_active_jobs(self) -> list[dict]:
        """Return all currently processing jobs, or an empty list if all workers are idle."""
        return await self.job_dao.get_active()

    async def cancel_job(self, job_id: str) -> dict:
        """Cancel a pending job.

        Raises JobNotFoundException if job does not exist.
        Raises JobNotCancellableException if job is not in pending status.
        Returns the updated job as a dict.
        """
        job = await self.job_dao.get(job_id)
        if not job:
            raise JobNotFoundException(job_id)
        
        if job["status"] != "pending":
            raise JobNotCancellableException(job_id, job["status"])
            
        success = await self.job_dao.cancel(job_id)
        if not success:
            # Re-fetch just in case status changed concurrently
            job = await self.job_dao.get(job_id)
            if not job:
                raise JobNotFoundException(job_id)
            raise JobNotCancellableException(job_id, job["status"])
            
        job["status"] = "cancelled"
        return job

    async def get_cached_job(self, pdf_hash: str) -> dict | None:
        """Check if a successfully completed job exists with this hash for the current user."""
        return await self.job_dao.get_completed_by_hash(pdf_hash)

    async def reprocess_job(self, job_id: str) -> dict:
        """Reset a failed or cancelled job back to pending status for reprocessing.

        Raises JobNotFoundException if the job does not exist.
        Raises ValueError if the job is not in failed or cancelled status.
        Returns the updated job as a DTO dict.
        """
        job = await self.job_dao.get(job_id)
        if not job:
            raise JobNotFoundException(job_id)
            
        if job["status"] not in ("failed", "cancelled"):
            raise ValueError(f"Job {job_id} is in status '{job['status']}' and cannot be reprocessed.")
            
        updated = await self.job_dao.reprocess(job_id)
        if not updated:
            raise JobNotFoundException(job_id)
        return updated

