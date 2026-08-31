"""
tests/integration/test_bulk_import_flow.py — End-to-end bulk-import job flow.

No real Firestore emulator or Cloud Tasks queue is available in this
environment, so the "integration" boundary tested here is: an in-memory
.xlsx file -> create_import_job() -> handle_scan_check() -> process_chunk()
-> job/results state, all driven through the same Firestore-shaped fake
store used in tests/unit/test_bulk_import_service.py (not re-mocked per
call, so state genuinely flows between stages the way it would across
separate Cloud Tasks invocations hitting the same Firestore project).

The two real external boundaries — storage-gateway (HTTP) and Cloud Tasks
enqueue calls — are mocked; case_service.process_lead_submission is mocked
too since its own pipeline (dedup, VCF screening, pubsub, follow-up task)
is already covered by tests/unit/test_assignment_transaction.py and the
existing lead-model/screening-rule test files — this test's job is to prove
the mapping -> row -> LeadRequest -> process_lead_submission handoff is
correct, not to re-verify that pipeline's own internals.
"""
from __future__ import annotations

import io
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../api"))
os.environ.setdefault("FIREBASE_PROJECT_ID", "test-project")

import openpyxl
import pytest
from fastapi import HTTPException, Request

from models.bulk_import import BulkImportRequest, ColumnMapping, LeadImportJobStatus
from models.lead import CaseStatus, LeadCreatedResponse, VCFEligibility
from services import bulk_import_service
from tests.unit.test_bulk_import_service import FakeFirestoreClient  # reuse the fake store


def _fake_settings():
    return type("S", (), {
        "bulk_import_scan_poll_delay_seconds": 5,
        "bulk_import_scan_poll_max_attempts": 24,
        "bulk_import_chunk_size": 25,
    })()


def _build_xlsx(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _full_mapping() -> BulkImportRequest:
    return BulkImportRequest(
        columnMappings=[
            ColumnMapping(excelColumn="First Name", leadField="firstName"),
            ColumnMapping(excelColumn="Last Name", leadField="lastName"),
            ColumnMapping(excelColumn="Email", leadField="email"),
            ColumnMapping(excelColumn="Phone", leadField="phone"),
            ColumnMapping(excelColumn="Location", leadField="exposureLocation"),
            ColumnMapping(excelColumn="Start", leadField="exposureDates.start"),
            ColumnMapping(excelColumn="End", leadField="exposureDates.end"),
            ColumnMapping(excelColumn="WTC Status", leadField="wtcHealthProgramStatus"),
            ColumnMapping(excelColumn="Prior Attorney", leadField="priorAttorney"),
        ],
        marketingSource="bulk_import_2026",
    )


@pytest.fixture(autouse=True)
def bypass_transaction_wrapper():
    with patch("services.bulk_import_service.firestore.async_transactional", side_effect=lambda fn: fn):
        yield


class TestFullBulkImportFlow:
    @pytest.mark.asyncio
    async def test_clean_scan_creates_a_lead_per_row_via_shared_pipeline(self):
        db = FakeFirestoreClient()
        settings = _fake_settings()

        xlsx_bytes = _build_xlsx([
            ["First Name", "Last Name", "Email", "Phone", "Location", "Start", "End", "WTC Status", "Prior Attorney"],
            ["John", "Doe", "john@example.com", "+12125551234", "World Trade Center", "2001-09-11", "2001-12-31", "enrolled", False],
            ["Jane", "Smith", "jane@example.com", "+12125555678", "World Trade Center", "2001-09-11", "2002-01-15", "applied", True],
        ])

        submitted_leads = []

        async def fake_process_lead_submission(lead, partner_id, request_id, db, sa_email):
            submitted_leads.append((lead, partner_id, request_id))
            case_num = len(submitted_leads)
            return LeadCreatedResponse(
                leadId=f"ZAD-2026-05-000{case_num}", status=CaseStatus.NEW_LEAD,
                vcfScreeningStatus=VCFEligibility.PENDING, requestId=request_id,
                timestamp=datetime.now(tz=timezone.utc),
            )

        chunk_calls = []

        async def fake_create_bulk_import_chunk_task(job_id, row_start, row_end, service_account_email):
            chunk_calls.append((job_id, row_start, row_end))
            return f"projects/test/tasks/{job_id}-{row_start}"

        with patch("services.storage_gateway_client.register_system_upload",
                   new=AsyncMock(return_value={
                       "file_id": "storage-file-1", "staging_path": "staging/storage-file-1/leads.xlsx",
                       "signed_url": "https://example.com/put", "expires_at": datetime.now(tz=timezone.utc),
                       "bucket": "test-bucket",
                   })), \
             patch("services.storage_gateway_client.put_file_bytes", new=AsyncMock()), \
             patch("services.bulk_import_service.create_scan_check_task", new=AsyncMock()), \
             patch("services.storage_gateway_client.get_upload_status", new=AsyncMock(return_value={"scan_status": "clean"})), \
             patch("services.storage_gateway_client.get_system_upload_read_url",
                   new=AsyncMock(return_value={"signed_url": "https://example.com/read"})), \
             patch("services.storage_gateway_client.fetch_bytes", new=AsyncMock(return_value=xlsx_bytes)), \
             patch("services.bulk_import_service.create_bulk_import_chunk_task", side_effect=fake_create_bulk_import_chunk_task), \
             patch("services.bulk_import_service.process_lead_submission", side_effect=fake_process_lead_submission), \
             patch("services.bulk_import_service.is_idempotent_retry", new=AsyncMock(return_value=None)):

            # Stage 1 — POST /leads/bulk-import equivalent
            job = await bulk_import_service.create_import_job(
                file_bytes=xlsx_bytes, file_name="leads.xlsx", mapping=_full_mapping(),
                partner_id="partner-1", request_id="req-1", db=db, settings=settings,
                sa_email="sa@test.iam.gserviceaccount.com",
            )
            assert job.status == LeadImportJobStatus.QUEUED

            # Stage 2 — Cloud Tasks invoking the scan-check handler
            scan_result = await bulk_import_service.handle_scan_check(
                job_id=job.jobId, db=db, settings=settings, sa_email="sa@test.iam.gserviceaccount.com",
            )
            assert scan_result["status"] == "processing_started"
            assert scan_result["totalRows"] == 2
            assert len(chunk_calls) == 1

            # Stage 3 — Cloud Tasks invoking the row-chunk processor
            _, row_start, row_end = chunk_calls[0]
            await bulk_import_service.process_chunk(
                job_id=job.jobId, row_start=row_start, row_end=row_end, db=db,
                sa_email="sa@test.iam.gserviceaccount.com",
            )

        # The shared pipeline was invoked once per row with correctly-mapped data.
        assert len(submitted_leads) == 2
        assert submitted_leads[0][0].firstName == "John"
        assert submitted_leads[0][0].marketingSource == "bulk_import_2026"
        assert submitted_leads[1][0].firstName == "Jane"
        assert submitted_leads[0][2] == f"{job.jobId}:1"  # deterministic per-row idempotency key
        assert submitted_leads[1][2] == f"{job.jobId}:2"

        final_job = await bulk_import_service.get_job(job.jobId, db)
        assert final_job.status == LeadImportJobStatus.SUCCEEDED
        assert final_job.summary.created == 2
        assert final_job.summary.failed == 0

        results = await bulk_import_service.list_job_results(job.jobId, db)
        assert {r.caseId for r in results.results} == {"ZAD-2026-05-0001", "ZAD-2026-05-0002"}

    @pytest.mark.asyncio
    async def test_infected_scan_fails_the_job_and_creates_no_leads(self):
        db = FakeFirestoreClient()
        settings = _fake_settings()
        xlsx_bytes = _build_xlsx([
            ["First Name", "Last Name", "Email", "Phone", "Location", "Start", "End", "WTC Status", "Prior Attorney"],
            ["John", "Doe", "john@example.com", "+12125551234", "World Trade Center", "2001-09-11", "2001-12-31", "enrolled", False],
        ])
        mock_submit = AsyncMock()

        with patch("services.storage_gateway_client.register_system_upload",
                   new=AsyncMock(return_value={
                       "file_id": "storage-file-2", "staging_path": "staging/storage-file-2/leads.xlsx",
                       "signed_url": "https://example.com/put", "expires_at": datetime.now(tz=timezone.utc),
                       "bucket": "test-bucket",
                   })), \
             patch("services.storage_gateway_client.put_file_bytes", new=AsyncMock()), \
             patch("services.bulk_import_service.create_scan_check_task", new=AsyncMock()), \
             patch("services.storage_gateway_client.get_upload_status", new=AsyncMock(return_value={"scan_status": "infected"})), \
             patch("services.bulk_import_service.process_lead_submission", mock_submit):

            job = await bulk_import_service.create_import_job(
                file_bytes=xlsx_bytes, file_name="leads.xlsx", mapping=_full_mapping(),
                partner_id="partner-1", request_id="req-2", db=db, settings=settings,
                sa_email="sa@test.iam.gserviceaccount.com",
            )
            await bulk_import_service.handle_scan_check(
                job_id=job.jobId, db=db, settings=settings, sa_email="sa@test.iam.gserviceaccount.com",
            )

        mock_submit.assert_not_awaited()
        final_job = await bulk_import_service.get_job(job.jobId, db)
        assert final_job.status == LeadImportJobStatus.FAILED
        assert final_job.summary.totalRows == 0
        assert final_job.summary.created == 0
        rows_written = [k for k in db.store if "/rows/" in k]
        assert rows_written == []

    @pytest.mark.asyncio
    async def test_create_import_job_rejects_incomplete_mapping_before_touching_storage_gateway(self):
        db = FakeFirestoreClient()
        settings = _fake_settings()
        xlsx_bytes = _build_xlsx([["First Name"], ["John"]])

        incomplete_mapping = BulkImportRequest(
            columnMappings=[ColumnMapping(excelColumn="First Name", leadField="firstName")],
            marketingSource="bulk_import_2026",
        )

        with patch("services.storage_gateway_client.register_system_upload", new=AsyncMock()) as mock_register:
            with pytest.raises(HTTPException) as exc_info:
                await bulk_import_service.create_import_job(
                    file_bytes=xlsx_bytes, file_name="leads.xlsx", mapping=incomplete_mapping,
                    partner_id="partner-1", request_id="req-3", db=db, settings=settings,
                    sa_email="sa@test.iam.gserviceaccount.com",
                )

        assert exc_info.value.status_code == 400
        mock_register.assert_not_awaited()  # fail-fast — never staged with storage-gateway


class TestRoutePermissionWiring:
    """Cheap smoke test for the RBAC wiring — doesn't need a running app/TestClient."""

    def test_bulk_import_routes_registered_with_expected_permissions(self):
        import main

        entries = {(method, path): perm for method, path, perm in main._ROUTE_PERMISSIONS}
        assert entries[("POST", r"^/api/v1/leads/bulk-import$")] == "cases.bulk.write"
        assert entries[("GET", r"^/api/v1/leads/bulk-import/[^/]+$")] == "cases.read"
        assert entries[("GET", r"^/api/v1/leads/bulk-import/[^/]+/results$")] == "cases.read"
        assert entries[("POST", r"^/api/v1/leads/internal/tasks/bulk-import-scan-check$")] == "tasks.internal"
        assert entries[("POST", r"^/api/v1/leads/internal/tasks/bulk-import$")] == "tasks.internal"


class TestInternalEndpointOidcGating:
    """_verify_cloud_tasks_oidc() is shared by all three internal task
    handlers (followup, bulk-import-scan-check, bulk-import) — exercise it
    directly against each expected_path rather than needing a live app."""

    def _fake_request(self, headers: dict):
        req = Request(scope={
            "type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        })
        return req

    def test_skipped_in_development(self, monkeypatch):
        from routers.leads import _verify_cloud_tasks_oidc
        monkeypatch.setenv("APP_ENV", "development")
        import config
        config.get_settings.cache_clear()
        try:
            _verify_cloud_tasks_oidc(self._fake_request({}), "/api/v1/leads/internal/tasks/bulk-import")
        finally:
            config.get_settings.cache_clear()

    def test_missing_token_rejected_outside_dev(self, monkeypatch):
        from routers.leads import _verify_cloud_tasks_oidc
        monkeypatch.setenv("APP_ENV", "staging")
        import config
        config.get_settings.cache_clear()
        try:
            with pytest.raises(HTTPException) as exc_info:
                _verify_cloud_tasks_oidc(self._fake_request({}), "/api/v1/leads/internal/tasks/bulk-import-scan-check")
            assert exc_info.value.status_code == 401
        finally:
            monkeypatch.setenv("APP_ENV", "test")
            config.get_settings.cache_clear()

    def test_invalid_token_rejected_outside_dev(self, monkeypatch):
        from routers.leads import _verify_cloud_tasks_oidc
        monkeypatch.setenv("APP_ENV", "staging")
        import config
        config.get_settings.cache_clear()
        try:
            with pytest.raises(HTTPException) as exc_info:
                _verify_cloud_tasks_oidc(
                    self._fake_request({"Authorization": "Bearer not-a-real-token"}),
                    "/api/v1/leads/internal/tasks/bulk-import",
                )
            assert exc_info.value.status_code == 401
        finally:
            monkeypatch.setenv("APP_ENV", "test")
            config.get_settings.cache_clear()
