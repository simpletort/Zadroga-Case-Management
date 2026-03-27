"""
tests/test_opt_out_service.py — Unit tests for services/opt_out_service.py

Covers
------
- is_opted_out: document missing → False
- is_opted_out: smsOptedOut=False → False
- is_opted_out: smsOptedOut=True → True
- is_opted_out: smsOptedOut field absent → False
- record_opt_out: writes correct payload to correct document
- clear_opt_out: sets smsOptedOut=False on the document
- Collection name comes from settings
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, call

from services.opt_out_service import clear_opt_out, is_opted_out, record_opt_out


# ── Helpers ───────────────────────────────────────────────────────────────────

PHONE = "+12125551234"


def _make_db(exists: bool, data: dict | None = None) -> AsyncMock:
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data or {}

    doc_ref = AsyncMock()
    doc_ref.get = AsyncMock(return_value=snap)
    doc_ref.set = AsyncMock()

    col = MagicMock()
    col.document = MagicMock(return_value=doc_ref)

    db = AsyncMock()
    db.collection = MagicMock(return_value=col)
    return db


# ── is_opted_out ──────────────────────────────────────────────────────────────

class TestIsOptedOut:

    @pytest.mark.asyncio
    async def test_document_absent_returns_false(self):
        db = _make_db(exists=False)
        assert await is_opted_out(PHONE, db) is False

    @pytest.mark.asyncio
    async def test_opted_out_true_returns_true(self):
        db = _make_db(exists=True, data={"smsOptedOut": True, "reason": "STOP"})
        assert await is_opted_out(PHONE, db) is True

    @pytest.mark.asyncio
    async def test_opted_out_false_returns_false(self):
        db = _make_db(exists=True, data={"smsOptedOut": False})
        assert await is_opted_out(PHONE, db) is False

    @pytest.mark.asyncio
    async def test_opted_out_field_absent_returns_false(self):
        """If the field is missing (malformed doc), default to not opted-out."""
        db = _make_db(exists=True, data={"phone": PHONE})
        assert await is_opted_out(PHONE, db) is False

    @pytest.mark.asyncio
    async def test_queries_correct_collection_and_document(self):
        """Document ID must be the E.164 phone number in the opt_outs collection."""
        from config import get_settings
        db = _make_db(exists=False)
        await is_opted_out(PHONE, db)

        expected_col = get_settings().opt_outs_collection
        db.collection.assert_called_once_with(expected_col)
        db.collection.return_value.document.assert_called_once_with(PHONE)


# ── record_opt_out ────────────────────────────────────────────────────────────

class TestRecordOptOut:

    @pytest.mark.asyncio
    async def test_writes_to_correct_document(self):
        from config import get_settings
        db = _make_db(exists=False)

        await record_opt_out(PHONE, reason="STOP", db=db)

        expected_col = get_settings().opt_outs_collection
        db.collection.assert_called_once_with(expected_col)
        db.collection.return_value.document.assert_called_once_with(PHONE)

    @pytest.mark.asyncio
    async def test_sets_opted_out_true(self):
        db = _make_db(exists=False)
        await record_opt_out(PHONE, reason="UNSUBSCRIBE", db=db)

        doc_ref = db.collection.return_value.document.return_value
        doc_ref.set.assert_awaited_once()

        # Extract the data argument
        call_args = doc_ref.set.call_args
        written_data = call_args[0][0]

        assert written_data["smsOptedOut"] is True
        assert written_data["phone"] == PHONE
        assert written_data["reason"] == "UNSUBSCRIBE"

    @pytest.mark.asyncio
    async def test_uses_merge_true(self):
        """set() must be called with merge=True to preserve existing fields."""
        db = _make_db(exists=False)
        await record_opt_out(PHONE, reason="STOP", db=db)

        doc_ref = db.collection.return_value.document.return_value
        call_kwargs = doc_ref.set.call_args[1]
        assert call_kwargs.get("merge") is True

    @pytest.mark.asyncio
    async def test_reason_is_stored(self):
        db = _make_db(exists=False)
        await record_opt_out(PHONE, reason="CANCEL", db=db)

        doc_ref = db.collection.return_value.document.return_value
        written_data = doc_ref.set.call_args[0][0]
        assert written_data["reason"] == "CANCEL"


# ── clear_opt_out ─────────────────────────────────────────────────────────────

class TestClearOptOut:

    @pytest.mark.asyncio
    async def test_sets_opted_out_false(self):
        db = _make_db(exists=True, data={"smsOptedOut": True})
        await clear_opt_out(PHONE, db=db)

        doc_ref = db.collection.return_value.document.return_value
        doc_ref.set.assert_awaited_once()
        written_data = doc_ref.set.call_args[0][0]
        assert written_data["smsOptedOut"] is False

    @pytest.mark.asyncio
    async def test_uses_merge_true(self):
        db = _make_db(exists=True, data={"smsOptedOut": True})
        await clear_opt_out(PHONE, db=db)

        doc_ref = db.collection.return_value.document.return_value
        call_kwargs = doc_ref.set.call_args[1]
        assert call_kwargs.get("merge") is True

    @pytest.mark.asyncio
    async def test_clears_correct_phone(self):
        from config import get_settings
        db = _make_db(exists=True)
        await clear_opt_out(PHONE, db=db)

        db.collection.return_value.document.assert_called_once_with(PHONE)
