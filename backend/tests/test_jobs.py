import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

# Import backend application components
from app.api.main import app
from app.api.dependencies.auth import get_current_user_id
from app.service.exceptions import JobNotFoundException, JobNotCancellableException
from app.service.extraction_service import ExtractionService
from app.ai.orchestrator import OrchestratorResult
from app.ai.types import RunMetrics


class TestJobsAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        
        # Override auth dependency to return a static test user
        app.dependency_overrides[get_current_user_id] = lambda: "test_user_123"
        
        # Mock container in app.state
        self.mock_container = MagicMock()
        self.mock_job_service = AsyncMock()
        self.mock_container.job_service = self.mock_job_service
        app.state.container = self.mock_container

    def tearDown(self):
        # Clear dependency overrides
        app.dependency_overrides.clear()

    def test_create_job_success(self):
        # Force cache miss
        self.mock_job_service.get_cached_job.return_value = None
        
        # Mock create_job return value
        mock_job = {
            "id": "job_abc",
            "status": "pending",
            "pdf_filename": "bill.pdf",
            "pdf_path": "/app/pdfs/test_user_123/bill.pdf",
            "created_at": "2026-06-23T10:00:00Z",
            "updated_at": "2026-06-23T10:00:00Z",
        }
        self.mock_job_service.create_job.return_value = mock_job

        # Execute POST /jobs/
        files = {"file": ("bill.pdf", b"%PDF-1.4...", "application/pdf")}
        response = self.client.post("/jobs/", files=files)

        self.assertEqual(response.status_code, 200)
        json_data = response.json()
        self.assertTrue(json_data["success"])
        self.assertEqual(json_data["data"]["id"], "job_abc")
        self.mock_job_service.create_job.assert_called_once()

    def test_get_job_success(self):
        mock_job = {
            "id": "job_abc",
            "status": "completed",
            "pdf_filename": "bill.pdf",
            "pdf_path": "/app/pdfs/test_user_123/bill.pdf",
            "created_at": "2026-06-23T10:00:00Z",
            "updated_at": "2026-06-23T10:00:00Z",
            "result": {"billing_records": []},
        }
        self.mock_job_service.get_job.return_value = mock_job

        # Execute GET /jobs/{job_id}
        response = self.client.get("/jobs/job_abc")

        self.assertEqual(response.status_code, 200)
        json_data = response.json()
        self.assertTrue(json_data["success"])
        self.assertEqual(json_data["data"]["status"], "completed")

    def test_get_job_not_found(self):
        # Mock JobNotFoundException
        self.mock_job_service.get_job.side_effect = JobNotFoundException("Job not found")

        # Execute GET /jobs/{job_id}
        response = self.client.get("/jobs/non_existent")

        self.assertEqual(response.status_code, 404)
        json_data = response.json()
        self.assertFalse(json_data["success"])
        self.assertIn("not found", json_data["message"].lower())

    def test_cancel_job_success(self):
        self.mock_job_service.cancel_job.return_value = None

        # Execute DELETE /jobs/{job_id}
        response = self.client.delete("/jobs/job_abc")

        self.assertEqual(response.status_code, 200)
        json_data = response.json()
        self.assertTrue(json_data["success"])
        self.mock_job_service.cancel_job.assert_called_once_with("job_abc")

    def test_cancel_job_unhappy_path_conflict(self):
        # Mock JobNotCancellableException (already processing/completed)
        self.mock_job_service.cancel_job.side_effect = JobNotCancellableException("job_abc", "processing")

        # Execute DELETE /jobs/{job_id}
        response = self.client.delete("/jobs/job_abc")

        self.assertEqual(response.status_code, 409)
        json_data = response.json()
        self.assertFalse(json_data["success"])
        self.assertIn("cannot be cancelled", json_data["message"].lower())


class TestExtractionService(unittest.IsolatedAsyncioTestCase):
    @patch("app.service.extraction_service.JobDAO")
    @patch("pypdf.PdfReader")
    @patch("app.service.extraction_service.ExtractionOrchestrator")
    async def test_process_job_happy_path(self, mock_orchestrator_class, mock_pdf_reader_class, mock_job_dao_class):
        # Mock dependencies
        mock_context_manager = MagicMock()
        
        # Instance mock of DAO
        mock_dao = mock_job_dao_class.return_value
        mock_dao.get = AsyncMock(return_value={
            "id": "job_abc",
            "user_id": "user_123",
            "pdf_path": "/app/pdfs/test.pdf",
            "status": "pending",
        })
        mock_dao.update_status = AsyncMock()

        # Instance mock of PDF Reader
        mock_pdf = mock_pdf_reader_class.return_value
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Treatment on 2026-06-23. CPT: 99213. Charges: $150.00."
        mock_pdf.pages = [mock_page]

        # Instance mock of Orchestrator
        mock_orch = mock_orchestrator_class.return_value
        mock_orch.run = AsyncMock(return_value=OrchestratorResult(
            echo_result="Extracted successfully",
            billing_records=[{"treatment_date": "2026-06-23", "cpt_code": "99213", "charges": 150.00}],
            run_metrics={"stage_1": RunMetrics(total_input_tokens=10, total_output_tokens=5, cost_usd=0.01)},
            wall_clock_seconds=1.2
        ))

        # Instantiate and run service
        service = ExtractionService(mock_context_manager)
        await service.process_job("job_abc")

        # Verify calls
        mock_dao.get.assert_called_once_with("job_abc")
        mock_pdf_reader_class.assert_called_once_with("/app/pdfs/test.pdf")
        mock_orch.run.assert_called_once()
        
        # Check database update call
        mock_dao.update_status.assert_called_once()
        call_kwargs = mock_dao.update_status.call_args[1]
        self.assertEqual(call_kwargs["status"], "completed")
        self.assertEqual(call_kwargs["result"]["billing_records"][0]["cpt_code"], "99213")
        self.assertEqual(call_kwargs["token_usage"]["total_tokens"], 15)

    @patch("app.service.extraction_service.JobDAO")
    @patch("pypdf.PdfReader")
    async def test_process_job_corrupt_pdf_failure(self, mock_pdf_reader_class, mock_job_dao_class):
        mock_context_manager = MagicMock()
        
        # Instance mock of DAO
        mock_dao = mock_job_dao_class.return_value
        mock_dao.get = AsyncMock(return_value={
            "id": "job_abc",
            "user_id": "user_123",
            "pdf_path": "/app/pdfs/corrupt.pdf",
            "status": "pending",
        })
        mock_dao.update_status = AsyncMock()

        # Simulate corrupt PDF exception
        mock_pdf_reader_class.side_effect = Exception("PDF file is corrupted")

        # Instantiate and run service
        service = ExtractionService(mock_context_manager)
        await service.process_job("job_abc")

        # Check database update is flagged as failed
        mock_dao.update_status.assert_called_once()
        call_kwargs = mock_dao.update_status.call_args[1]
        self.assertEqual(call_kwargs["status"], "failed")
        self.assertIn("PDF file is corrupted", call_kwargs["error"])

    @patch("app.service.extraction_service.JobDAO")
    @patch("pypdf.PdfReader")
    @patch("app.service.extraction_service.ExtractionOrchestrator")
    @patch("asyncio.sleep")
    async def test_process_job_transient_retry_success(self, mock_sleep, mock_orchestrator_class, mock_pdf_reader_class, mock_job_dao_class):
        # Mock dependencies
        mock_context_manager = MagicMock()
        
        # Instance mock of DAO
        mock_dao = mock_job_dao_class.return_value
        mock_dao.get = AsyncMock(return_value={
            "id": "job_abc",
            "user_id": "user_123",
            "pdf_path": "/app/pdfs/test.pdf",
            "status": "pending",
        })
        mock_dao.update_status = AsyncMock()

        # Instance mock of PDF Reader
        mock_pdf = mock_pdf_reader_class.return_value
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Treatment on 2026-06-23. CPT: 99213. Charges: $150.00."
        mock_pdf.pages = [mock_page]

        # Instance mock of Orchestrator
        mock_orch = mock_orchestrator_class.return_value
        mock_orch.run = AsyncMock()
        
        # Raise rate limit error on first call, return success result on second
        mock_orch.run.side_effect = [
            Exception("Rate limit exceeded"),
            OrchestratorResult(
                echo_result="Extracted successfully after retry",
                billing_records=[{"treatment_date": "2026-06-23", "cpt_code": "99213", "charges": 150.00}],
                run_metrics={"stage_1": RunMetrics(total_input_tokens=10, total_output_tokens=5, cost_usd=0.01)},
                wall_clock_seconds=1.2
            )
        ]

        # Instantiate and run service
        service = ExtractionService(mock_context_manager)
        await service.process_job("job_abc")

        # Verify calls
        self.assertEqual(mock_orch.run.call_count, 2)
        mock_sleep.assert_called_once_with(1)  # 2^0 = 1 second sleep on 1st retry
        
        # Check database update is completed successfully
        mock_dao.update_status.assert_called_once()
        call_kwargs = mock_dao.update_status.call_args[1]
        self.assertEqual(call_kwargs["status"], "completed")


if __name__ == "__main__":
    unittest.main()
