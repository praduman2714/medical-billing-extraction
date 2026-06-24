import os
import hashlib
import asyncio
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, Header, Query

from app.api.dependencies.container import get_container
from app.api.dependencies.auth import get_current_user_id
from app.api.schema import SuccessResponse
from app.service.container import ServiceContainer
from app.core.common.id.short_id import generate_id

router = APIRouter()


@router.post("/")
async def create_job(
    file: UploadFile = File(...),
    bypass_cache: bool = Query(False, description="Bypass content-based caching for this upload."),
    x_bypass_cache: str | None = Header(None, description="Bypass content-based caching for this upload."),
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_current_user_id),
) -> SuccessResponse:
    """Upload a PDF and create a new extraction job.

    Saves the uploaded PDF to the configured mount volume and enqueues
    a job for the worker. Returns the created job including job_id and
    initial status.
    """
    # 1. Read file content and compute hash
    content = await file.read()
    pdf_hash = hashlib.sha256(content).hexdigest()

    # 2. Check for cache hit (unless bypass is requested)
    bypass = bypass_cache or (x_bypass_cache is not None and x_bypass_cache.lower() in ("true", "1", "yes"))
    cached_job = None if bypass else await container.job_service.get_cached_job(pdf_hash)
    
    settings = container._context_manager._settings
    os.makedirs(settings.PDF_MOUNT_PATH, exist_ok=True)
    
    if cached_job:
        # Cache hit: Create a new job record in completed status, copying the result
        job_id = generate_id(prefix="job")
        pdf_path = os.path.join(settings.PDF_MOUNT_PATH, f"{job_id}.pdf")
        
        # Save file asynchronously
        def save_file():
            with open(pdf_path, "wb") as f:
                f.write(content)
        await asyncio.to_thread(save_file)
        
        # Create job
        job = await container.job_service.create_job(
            pdf_filename=file.filename,
            pdf_path=pdf_path,
            pdf_hash=pdf_hash,
            job_id=job_id,
        )
        
        # Complete job with cached results
        completed_job = await container.job_service.job_dao.update_status(
            job_id=job["id"],
            status="completed",
            result=cached_job["result"],
            token_usage=cached_job["token_usage"],
            cost_usd=cached_job["cost_usd"],
            processing_duration_seconds=0.0,  # 0 duration for cache hits
        )
        
        return SuccessResponse(
            success=True,
            message="Job created successfully (cache hit).",
            data=completed_job,
        )

    # Cache miss: Create job in pending status
    job_id = generate_id(prefix="job")
    pdf_path = os.path.join(settings.PDF_MOUNT_PATH, f"{job_id}.pdf")
    
    # Save file asynchronously
    def save_file_miss():
        with open(pdf_path, "wb") as f:
            f.write(content)
    await asyncio.to_thread(save_file_miss)
    
    job = await container.job_service.create_job(
        pdf_filename=file.filename,
        pdf_path=pdf_path,
        pdf_hash=pdf_hash,
        job_id=job_id,
    )
    
    return SuccessResponse(
        success=True,
        message="Job created successfully.",
        data=job,
    )


@router.get("/")
async def list_jobs(
    status: str | None = None,
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_current_user_id),
) -> SuccessResponse:
    """List all jobs, optionally filtered by status.

    Valid status values: pending, processing, completed, failed, cancelled.
    Returns jobs ordered by created_at descending.
    """
    jobs = await container.job_service.list_jobs(status=status)
    return SuccessResponse(
        success=True,
        message="Jobs retrieved successfully.",
        data=jobs,
    )


@router.get("/active")
async def get_active_job(
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_current_user_id),
) -> SuccessResponse:
    """Return the job currently being processed by the worker.

    Returns null if no job is currently processing.
    Must reflect live state on every call — do not cache.
    """
    active_jobs = await container.job_service.get_active_jobs()
    active_job = active_jobs[0] if active_jobs else None
    return SuccessResponse(
        success=True,
        message="Active job retrieved.",
        data=active_job,
    )


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_current_user_id),
) -> SuccessResponse:
    """Return full detail for a single job.

    Includes extraction result if completed, error detail if failed.
    Returns 404 if the job does not exist.
    """
    # job_service.get_job will automatically raise JobNotFoundException if not found,
    # which will be converted to a 404 response by the FastAPI exception handler.
    job = await container.job_service.get_job(job_id)
    return SuccessResponse(
        success=True,
        message="Job retrieved successfully.",
        data=job,
    )


@router.delete("/{job_id}")
async def cancel_job(
    job_id: str,
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_current_user_id),
) -> SuccessResponse:
    """Cancel a pending job before it is picked up by the worker.

    Returns 409 if the job is already processing, completed, or failed.
    Returns 404 if the job does not exist.
    """
    job = await container.job_service.cancel_job(job_id)
    return SuccessResponse(
        success=True,
        message="Job cancelled successfully.",
        data=job,
    )
