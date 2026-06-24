import time
import pypdf
from app.core.context_manager import ContextManager, current_user_id_ctx
from app.dao.pg.job_dao import JobDAO
from app.service.base_service import BaseService
from app.ai.orchestrator import ExtractionOrchestrator
from app.ai.context import RunContext
from app.ai.types import Document, Page


class ExtractionService(BaseService):
    """Owns the extraction pipeline for a single job.

    Called by the worker loop with a job_id. Responsible for:
    - Loading the PDF from the mounted volume
    - Building RunContext and running ExtractionOrchestrator
    - Writing the extraction result or error back to the job record

    This service is the bridge between the job queue and the AI layer.
    Never raises — all exceptions must be caught and written to the job
    error field so the worker loop stays alive.
    """

    def __init__(self, context_manager: ContextManager) -> None:
        super().__init__(context_manager)
        self.job_dao = JobDAO(context_manager)

    async def process_job(self, job_id: str) -> None:
        """Run the full extraction pipeline for a job.

        Loads the PDF, builds RunContext, runs the orchestrator, writes
        result back. Updates job status to completed or failed.
        Must never raise — catch all exceptions and write to job.error.
        """
        start_time = time.perf_counter()
        user_id = None
        
        try:
            # 1. Fetch job to get file path and user ID
            job = await self.job_dao.get(job_id)
            if not job:
                # If job doesn't exist, we can't update it
                return
                
            user_id = job["user_id"]
            pdf_path = job["pdf_path"]
            
            # Since the worker is subject to RLS, it must set app.current_user_id 
            # to propagate the user context for updating the job status to 'completed'
            current_user_id_ctx.set(user_id)

            # 2. Extract text from PDF
            reader = pypdf.PdfReader(pdf_path)
            pages = []
            for idx, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                pages.append(Page(page_num=idx + 1, page_content=text))
                
            doc = Document(
                doc_id=job_id,
                num_pages=len(reader.pages),
                pages=pages,
            )
            
            # 3. Build RunContext and run orchestrator
            ctx = RunContext(document=doc)
            orchestrator = ExtractionOrchestrator()
            result = await orchestrator.run(ctx)
            
            # 4. Aggregate metrics
            total_prompt_tokens = 0
            total_completion_tokens = 0
            total_tokens = 0
            total_cost = 0.0
            
            for stage_name, stage_metrics in result.run_metrics.items():
                total_prompt_tokens += stage_metrics.total_input_tokens
                total_completion_tokens += stage_metrics.total_output_tokens
                total_tokens += stage_metrics.total_input_tokens + stage_metrics.total_output_tokens
                total_cost += stage_metrics.cost_usd
                
            token_usage = {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_tokens,
            }
            
            # 5. Save completed status and results
            job_result = {
                "billing_records": result.billing_records,
                "flagged_records": result.flagged_records,
            }
            
            await self.job_dao.update_status(
                job_id=job_id,
                status="completed",
                result=job_result,
                token_usage=token_usage,
                cost_usd=total_cost,
                processing_duration_seconds=time.perf_counter() - start_time,
            )
            
        except Exception as e:
            # Propagate current user context for writing error status
            if user_id:
                current_user_id_ctx.set(user_id)
            try:
                await self.job_dao.update_status(
                    job_id=job_id,
                    status="failed",
                    error=str(e),
                    processing_duration_seconds=time.perf_counter() - start_time,
                )
            except Exception as update_err:
                # Log final fallback error
                pass
