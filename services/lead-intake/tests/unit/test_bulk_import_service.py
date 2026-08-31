"""
tests/unit/test_bulk_import_service.py — Tests for the bulk-import job
pipeline: scan-check state transitions, row-chunk processing (best-effort,
never aborts the batch), and per-row idempotency.

Uses a tiny in-memory fake Firestore (FakeFirestoreClient below) rather than
mocking every collection().document() call by hand — process_chunk/
handle_scan_check touch several distinct doc paths (job, rows/{n},
results/{n}) and a real dict-backed store makes the resulting state easy to
assert on directly instead of chasing MagicMock call args.
"""
from __future__ import annotations

import io
import os
import sys
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../api"))
os.environ.setdefault("FIREBASE_PROJECT_ID", "test-project")

import openpyxl
import pytest
from fastapi import HTTPException

from models.bulk_import import LeadImportJobStatus, RowOutcome
from models.lead import CaseStatus, LeadCreatedResponse, VCFEligibility
from services import bulk_import_service


# ── Minimal in-memory fake Firestore ─────────────────────────────────────────

class FakeSnapshot:
    def __init__(self, exists: bool, data: dict | None = None, doc_id: str = ""):
        self.exists = exists
        self._data = data or {}
        self.id = doc_id

    def to_dict(self):
        return dict(self._data)


class FakeDocRef:
    def __init__(self, store: dict, path: str):
        self.store = store
        self.path = path

    async def get(self, transaction=None):
        data = self.store.get(self.path)
        return FakeSnapshot(data is not None, data, doc_id=self.path.rsplit("/", 1)[-1])

    async def set(self, data: dict):
        self.store[self.path] = dict(data)

    async def update(self, data: dict):
        self.store.setdefault(self.path, {}).update(data)

    def collection(self, name: str) -> "FakeCollectionRef":
        return FakeCollectionRef(self.store, f"{self.path}/{name}")


class FakeQuery:
    """Minimal chainable query — enough for list_job_results()'s
    order_by/where/limit/start_after/stream usage against a flat, single-level
    subcollection. Not a general Firestore query emulator."""

    def __init__(self, store, prefix, filters=None, order_field=None, limit_n=None, start_after_id=None):
        self.store = store
        self.prefix = prefix
        self.filters = filters or []
        self.order_field = order_field
        self.limit_n = limit_n
        self.start_after_id = start_after_id

    def where(self, field, op, value):
        return FakeQuery(self.store, self.prefix, self.filters + [(field, op, value)],
                          self.order_field, self.limit_n, self.start_after_id)

    def order_by(self, field, direction=None):
        return FakeQuery(self.store, self.prefix, self.filters, field, self.limit_n, self.start_after_id)

    def limit(self, n):
        return FakeQuery(self.store, self.prefix, self.filters, self.order_field, n, self.start_after_id)

    def start_after(self, doc_snapshot):
        return FakeQuery(self.store, self.prefix, self.filters, self.order_field, self.limit_n, doc_snapshot.id)

    async def stream(self):
        items = []
        for path, data in self.store.items():
            if not path.startswith(self.prefix + "/"):
                continue
            rest = path[len(self.prefix) + 1:]
            if "/" in rest:
                continue  # direct children of this collection only
            ok = True
            for field, op, value in self.filters:
                if op == "==" and data.get(field) != value:
                    ok = False
                    break
            if ok:
                items.append((rest, data))

        if self.order_field:
            items.sort(key=lambda kv: kv[1].get(self.order_field))
        if self.start_after_id:
            idx = next((i for i, (doc_id, _) in enumerate(items) if doc_id == self.start_after_id), None)
            if idx is not None:
                items = items[idx + 1:]
        if self.limit_n:
            items = items[: self.limit_n]
        for doc_id, data in items:
            yield FakeSnapshot(True, data, doc_id=doc_id)


class FakeCollectionRef:
    def __init__(self, store: dict, path: str):
        self.store = store
        self.path = path

    def document(self, doc_id: str) -> FakeDocRef:
        return FakeDocRef(self.store, f"{self.path}/{doc_id}")

    def where(self, field, op, value):
        return FakeQuery(self.store, self.path).where(field, op, value)

    def order_by(self, field, direction=None):
        return FakeQuery(self.store, self.path).order_by(field, direction)

    def limit(self, n):
        return FakeQuery(self.store, self.path).limit(n)

    def stream(self):
        return FakeQuery(self.store, self.path).stream()


class FakeBatch:
    def __init__(self, store: dict):
        self.store = store
        self._ops = []

    def set(self, doc_ref: FakeDocRef, data: dict):
        self._ops.append((doc_ref.path, dict(data)))

    async def commit(self):
        for path, data in self._ops:
            self.store[path] = data
        self._ops = []


class FakeTransaction:
    def __init__(self, store: dict):
        self.store = store

    def update(self, doc_ref: FakeDocRef, data: dict):
        self.store.setdefault(doc_ref.path, {}).update(data)


class FakeFirestoreClient:
    def __init__(self):
        self.store: dict[str, dict] = {}

    def collection(self, name: str) -> FakeCollectionRef:
        return FakeCollectionRef(self.store, name)

    def batch(self) -> FakeBatch:
        return FakeBatch(self.store)

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self.store)


def _job_path(job_id: str) -> str:
    return f"{bulk_import_service.JOBS_COLLECTION}/{job_id}"


def _seed_job(db: FakeFirestoreClient, job_id: str, **overrides) -> dict:
    job = {
        "jobId": job_id,
        "status": LeadImportJobStatus.PROCESSING.value,
        "scanStatus": "clean",
        "storageFileId": "storage-file-1",
        "partnerId": "partner-1",
        "requestId": "req-1",
        "fileName": "leads.xlsx",
        "columnMappings": [],
        "sheetName": None,
        "headerRowIndex": 0,
        "marketingSource": "google_ads",
        "defaultReferralCode": None,
        "totalRows": 3,
        "processedRows": 0,
        "createdCount": 0,
        "skippedCount": 0,
        "failedCount": 0,
        "chunkCount": 1,
        "chunksCompleted": 0,
        "scanPollAttempts": 0,
        "createdAt": datetime.now(tz=timezone.utc),
        "updatedAt": datetime.now(tz=timezone.utc),
        "completedAt": None,
        "errorMessage": None,
    }
    job.update(overrides)
    db.store[_job_path(job_id)] = job
    return job


def _valid_row(**overrides) -> dict:
    row = {
        "firstName": "John", "lastName": "Doe", "email": "john@example.com",
        "phone": "+12125551234", "exposureLocation": "World Trade Center",
        "exposureDates": {"start": "2001-09-11", "end": "2001-12-31"},
        "wtcHealthProgramStatus": "enrolled", "priorAttorney": False,
        "marketingSource": "google_ads",
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def bypass_transaction_wrapper():
    """process_chunk's counter-increment step uses @firestore.async_transactional,
    which expects a real google.cloud.firestore Transaction (checks internal
    attributes like _read_only). Bypass it the same way test_assignment_transaction.py
    does — FakeTransaction only needs to support .update(), not real retry semantics."""
    with patch("services.bulk_import_service.firestore.async_transactional", side_effect=lambda fn: fn):
        yield


def _lead_created_response(case_id="ZAD-2026-05-0001"):
    return LeadCreatedResponse(
        leadId=case_id, status=CaseStatus.NEW_LEAD,
        vcfScreeningStatus=VCFEligibility.PENDING,
        requestId="row-req", timestamp=datetime.now(tz=timezone.utc),
    )


class TestProcessChunkBestEffort:
    """One bad row must never abort the rest of the chunk (mirrors bulk-assign)."""

    @pytest.mark.asyncio
    async def test_mixed_outcomes_all_processed_independently(self):
        db = FakeFirestoreClient()
        job_id = "job-mixed"
        _seed_job(db, job_id, totalRows=4, chunkCount=1)

        rows_path = f"{_job_path(job_id)}/rows"
        db.store[f"{rows_path}/0001"] = {**_valid_row(), "rowNumber": 1}                 # -> created
        db.store[f"{rows_path}/0002"] = {"rowNumber": 2}                                  # missing required fields -> validation failure
        db.store[f"{rows_path}/0003"] = {**_valid_row(email="dup@example.com"), "rowNumber": 3}  # -> duplicate (409)
        db.store[f"{rows_path}/0004"] = {**_valid_row(firstName="Crash"), "rowNumber": 4}  # -> unexpected exception

        async def fake_process_lead_submission(lead, partner_id, request_id, db, sa_email):
            if lead.email == "dup@example.com":
                raise HTTPException(status_code=409, detail={
                    "error": "DUPLICATE_LEAD", "message": "A lead with this email and phone already exists", "details": [],
                })
            if lead.firstName == "Crash":
                raise RuntimeError("boom")
            return _lead_created_response("ZAD-2026-05-0001")

        with patch("services.bulk_import_service.process_lead_submission", side_effect=fake_process_lead_submission), \
             patch("services.bulk_import_service.is_idempotent_retry", new=AsyncMock(return_value=None)):
            result = await bulk_import_service.process_chunk(
                job_id=job_id, row_start=1, row_end=5, db=db, sa_email="sa@test.iam.gserviceaccount.com",
            )

        assert result["created"] == 1
        assert result["skipped"] == 1
        assert result["failed"] == 2

        results_path = f"{_job_path(job_id)}/results"
        assert db.store[f"{results_path}/0001"]["outcome"] == RowOutcome.CREATED.value
        assert db.store[f"{results_path}/0001"]["caseId"] == "ZAD-2026-05-0001"
        assert db.store[f"{results_path}/0002"]["outcome"] == RowOutcome.FAILED.value
        assert db.store[f"{results_path}/0003"]["outcome"] == RowOutcome.SKIPPED_DUPLICATE.value
        assert db.store[f"{results_path}/0004"]["outcome"] == RowOutcome.FAILED.value

        # Job counters reflect all four rows, and the chunk is marked complete.
        job = db.store[_job_path(job_id)]
        assert job["processedRows"] == 4
        assert job["createdCount"] == 1
        assert job["skippedCount"] == 1
        assert job["failedCount"] == 2
        assert job["chunksCompleted"] == 1
        assert job["status"] == LeadImportJobStatus.SUCCEEDED.value  # "succeeded" = ran to completion, not "all rows created"

    @pytest.mark.asyncio
    async def test_validation_error_message_excludes_raw_field_values(self):
        """A ValidationError's default str() can embed the offending value
        (PII) — the stored error message must not leak it."""
        db = FakeFirestoreClient()
        job_id = "job-phi"
        _seed_job(db, job_id, totalRows=1, chunkCount=1)
        rows_path = f"{_job_path(job_id)}/rows"
        db.store[f"{rows_path}/0001"] = {
            **_valid_row(email="not-a-real-email", ssn="123456789-SENTINEL"), "rowNumber": 1,
        }

        with patch("services.bulk_import_service.process_lead_submission", new=AsyncMock()), \
             patch("services.bulk_import_service.is_idempotent_retry", new=AsyncMock(return_value=None)):
            await bulk_import_service.process_chunk(
                job_id=job_id, row_start=1, row_end=2, db=db, sa_email="sa@test.iam.gserviceaccount.com",
            )

        stored = db.store[f"{_job_path(job_id)}/results/0001"]
        assert stored["outcome"] == RowOutcome.FAILED.value
        assert "not-a-real-email" not in stored["error"]["message"]
        assert "123456789-SENTINEL" not in stored["error"]["message"]

    @pytest.mark.asyncio
    async def test_missing_row_doc_is_skipped_without_error(self):
        """Defensive: a row doc that doesn't exist (shouldn't happen, but if
        it does) must not crash the chunk."""
        db = FakeFirestoreClient()
        job_id = "job-missing-row"
        _seed_job(db, job_id, totalRows=1, chunkCount=1)
        # rows/0001 intentionally not seeded

        with patch("services.bulk_import_service.process_lead_submission", new=AsyncMock()), \
             patch("services.bulk_import_service.is_idempotent_retry", new=AsyncMock(return_value=None)):
            result = await bulk_import_service.process_chunk(
                job_id=job_id, row_start=1, row_end=2, db=db, sa_email="sa@test.iam.gserviceaccount.com",
            )

        assert result["created"] == result["skipped"] == result["failed"] == 0


class TestProcessChunkIdempotency:
    @pytest.mark.asyncio
    async def test_redelivered_chunk_skips_already_written_results(self):
        """A row whose results/{n} doc already exists must not be
        reprocessed (Cloud Tasks can redeliver a chunk task)."""
        db = FakeFirestoreClient()
        job_id = "job-redelivered"
        _seed_job(db, job_id, totalRows=1, chunkCount=1, chunksCompleted=0, processedRows=1, createdCount=1)
        rows_path = f"{_job_path(job_id)}/rows"
        db.store[f"{rows_path}/0001"] = {**_valid_row(), "rowNumber": 1}
        db.store[f"{_job_path(job_id)}/results/0001"] = {
            "rowNumber": 1, "outcome": "created", "caseId": "ZAD-2026-05-0001",
        }

        mock_submit = AsyncMock()
        with patch("services.bulk_import_service.process_lead_submission", mock_submit), \
             patch("services.bulk_import_service.is_idempotent_retry", new=AsyncMock(return_value=None)):
            result = await bulk_import_service.process_chunk(
                job_id=job_id, row_start=1, row_end=2, db=db, sa_email="sa@test.iam.gserviceaccount.com",
            )

        mock_submit.assert_not_awaited()
        assert result["created"] == result["skipped"] == result["failed"] == 0

    @pytest.mark.asyncio
    async def test_is_idempotent_retry_fallback_records_created_without_resubmitting(self):
        """If the row was created by a prior (crashed-before-writing-result)
        delivery, is_idempotent_retry() finds it via the row's deterministic
        request_id — must not call process_lead_submission again."""
        db = FakeFirestoreClient()
        job_id = "job-idempotent-fallback"
        _seed_job(db, job_id, totalRows=1, chunkCount=1)
        rows_path = f"{_job_path(job_id)}/rows"
        db.store[f"{rows_path}/0001"] = {**_valid_row(), "rowNumber": 1}

        mock_submit = AsyncMock()
        fake_case = type("FakeCase", (), {"vcfEligibility": VCFEligibility.ELIGIBLE})()
        with patch("services.bulk_import_service.process_lead_submission", mock_submit), \
             patch("services.bulk_import_service.is_idempotent_retry", new=AsyncMock(return_value="ZAD-2026-05-0099")), \
             patch("services.bulk_import_service.get_case", new=AsyncMock(return_value=fake_case)):
            result = await bulk_import_service.process_chunk(
                job_id=job_id, row_start=1, row_end=2, db=db, sa_email="sa@test.iam.gserviceaccount.com",
            )

        mock_submit.assert_not_awaited()
        assert result["created"] == 1
        stored = db.store[f"{_job_path(job_id)}/results/0001"]
        assert stored["caseId"] == "ZAD-2026-05-0099"
        assert stored["vcfScreeningStatus"] == VCFEligibility.ELIGIBLE.value


class TestChunkCompletionRace:
    @pytest.mark.asyncio
    async def test_job_only_succeeds_after_all_chunks_report_in(self):
        db = FakeFirestoreClient()
        job_id = "job-multi-chunk"
        _seed_job(db, job_id, totalRows=2, chunkCount=2, chunksCompleted=0)
        rows_path = f"{_job_path(job_id)}/rows"
        db.store[f"{rows_path}/0001"] = {**_valid_row(), "rowNumber": 1}

        with patch("services.bulk_import_service.process_lead_submission", new=AsyncMock(return_value=_lead_created_response())), \
             patch("services.bulk_import_service.is_idempotent_retry", new=AsyncMock(return_value=None)):
            await bulk_import_service.process_chunk(
                job_id=job_id, row_start=1, row_end=2, db=db, sa_email="sa@test.iam.gserviceaccount.com",
            )

        job = db.store[_job_path(job_id)]
        assert job["chunksCompleted"] == 1
        assert job["status"] == LeadImportJobStatus.PROCESSING.value  # second chunk hasn't reported yet

        db.store[f"{rows_path}/0002"] = {**_valid_row(), "rowNumber": 2}
        with patch("services.bulk_import_service.process_lead_submission", new=AsyncMock(return_value=_lead_created_response())), \
             patch("services.bulk_import_service.is_idempotent_retry", new=AsyncMock(return_value=None)):
            await bulk_import_service.process_chunk(
                job_id=job_id, row_start=2, row_end=3, db=db, sa_email="sa@test.iam.gserviceaccount.com",
            )

        job = db.store[_job_path(job_id)]
        assert job["chunksCompleted"] == 2
        assert job["status"] == LeadImportJobStatus.SUCCEEDED.value


class TestHandleScanCheck:
    @pytest.mark.asyncio
    async def test_pending_scan_reenqueues_with_incremented_attempts(self):
        db = FakeFirestoreClient()
        job_id = "job-scanning"
        _seed_job(db, job_id, status=LeadImportJobStatus.QUEUED.value, scanPollAttempts=2)

        settings = type("S", (), {
            "bulk_import_scan_poll_delay_seconds": 5,
            "bulk_import_scan_poll_max_attempts": 24,
            "bulk_import_chunk_size": 25,
        })()

        with patch("services.storage_gateway_client.get_upload_status", new=AsyncMock(return_value={"scan_status": "scanning"})), \
             patch("services.bulk_import_service.create_scan_check_task", new=AsyncMock()) as mock_reenqueue:
            result = await bulk_import_service.handle_scan_check(job_id=job_id, db=db, settings=settings, sa_email="sa@test")

        assert result["status"] == "still_scanning"
        job = db.store[_job_path(job_id)]
        assert job["scanPollAttempts"] == 3
        assert job["status"] == LeadImportJobStatus.SCANNING.value
        mock_reenqueue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scan_timeout_fails_job(self):
        db = FakeFirestoreClient()
        job_id = "job-timeout"
        _seed_job(db, job_id, status=LeadImportJobStatus.SCANNING.value, scanPollAttempts=23)

        settings = type("S", (), {
            "bulk_import_scan_poll_delay_seconds": 5,
            "bulk_import_scan_poll_max_attempts": 24,
            "bulk_import_chunk_size": 25,
        })()

        with patch("services.storage_gateway_client.get_upload_status", new=AsyncMock(return_value={"scan_status": "pending"})), \
             patch("services.bulk_import_service.create_scan_check_task", new=AsyncMock()) as mock_reenqueue:
            result = await bulk_import_service.handle_scan_check(job_id=job_id, db=db, settings=settings, sa_email="sa@test")

        assert result["status"] == "scan_timeout"
        job = db.store[_job_path(job_id)]
        assert job["status"] == LeadImportJobStatus.FAILED.value
        assert "timed out" in job["errorMessage"].lower()
        mock_reenqueue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_infected_scan_fails_job_with_zero_rows(self):
        db = FakeFirestoreClient()
        job_id = "job-infected"
        _seed_job(db, job_id, status=LeadImportJobStatus.SCANNING.value)

        settings = type("S", (), {
            "bulk_import_scan_poll_delay_seconds": 5,
            "bulk_import_scan_poll_max_attempts": 24,
            "bulk_import_chunk_size": 25,
        })()

        with patch("services.storage_gateway_client.get_upload_status", new=AsyncMock(return_value={"scan_status": "infected"})):
            result = await bulk_import_service.handle_scan_check(job_id=job_id, db=db, settings=settings, sa_email="sa@test")

        assert result["status"] == "infected"
        job = db.store[_job_path(job_id)]
        assert job["status"] == LeadImportJobStatus.FAILED.value
        assert job["totalRows"] == 3  # unchanged from seed — no rows were ever written
        rows_written = [k for k in db.store if k.startswith(f"{_job_path(job_id)}/rows/")]
        assert rows_written == []

    @pytest.mark.asyncio
    async def test_clean_scan_parses_rows_and_enqueues_chunks(self):
        db = FakeFirestoreClient()
        job_id = "job-clean"
        _seed_job(
            db, job_id, status=LeadImportJobStatus.SCANNING.value,
            columnMappings=[{"excelColumn": "First Name", "leadField": "firstName"}],
            totalRows=0, chunkCount=0,
        )

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["First Name"])
        ws.append(["John"])
        ws.append(["Jane"])
        buf = io.BytesIO()
        wb.save(buf)
        xlsx_bytes = buf.getvalue()

        settings = type("S", (), {
            "bulk_import_scan_poll_delay_seconds": 5,
            "bulk_import_scan_poll_max_attempts": 24,
            "bulk_import_chunk_size": 25,
        })()

        with patch("services.storage_gateway_client.get_upload_status", new=AsyncMock(return_value={"scan_status": "clean"})), \
             patch("services.storage_gateway_client.get_system_upload_read_url", new=AsyncMock(return_value={"signed_url": "https://example.com/read"})), \
             patch("services.storage_gateway_client.fetch_bytes", new=AsyncMock(return_value=xlsx_bytes)), \
             patch("services.bulk_import_service.create_bulk_import_chunk_task", new=AsyncMock()) as mock_chunk_task:
            result = await bulk_import_service.handle_scan_check(job_id=job_id, db=db, settings=settings, sa_email="sa@test")

        assert result["status"] == "processing_started"
        assert result["totalRows"] == 2
        job = db.store[_job_path(job_id)]
        assert job["status"] == LeadImportJobStatus.PROCESSING.value
        assert job["totalRows"] == 2
        assert job["chunkCount"] == 1
        assert db.store[f"{_job_path(job_id)}/rows/0001"]["firstName"] == "John"
        assert db.store[f"{_job_path(job_id)}/rows/0002"]["firstName"] == "Jane"
        mock_chunk_task.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_clean_scan_with_zero_data_rows_fails_job(self):
        db = FakeFirestoreClient()
        job_id = "job-empty"
        _seed_job(db, job_id, status=LeadImportJobStatus.SCANNING.value, columnMappings=[])

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["First Name"])  # header only, no data rows
        buf = io.BytesIO()
        wb.save(buf)

        settings = type("S", (), {
            "bulk_import_scan_poll_delay_seconds": 5,
            "bulk_import_scan_poll_max_attempts": 24,
            "bulk_import_chunk_size": 25,
        })()

        with patch("services.storage_gateway_client.get_upload_status", new=AsyncMock(return_value={"scan_status": "clean"})), \
             patch("services.storage_gateway_client.get_system_upload_read_url", new=AsyncMock(return_value={"signed_url": "https://example.com/read"})), \
             patch("services.storage_gateway_client.fetch_bytes", new=AsyncMock(return_value=buf.getvalue())):
            result = await bulk_import_service.handle_scan_check(job_id=job_id, db=db, settings=settings, sa_email="sa@test")

        assert result["status"] == "no_rows"
        assert db.store[_job_path(job_id)]["status"] == LeadImportJobStatus.FAILED.value
