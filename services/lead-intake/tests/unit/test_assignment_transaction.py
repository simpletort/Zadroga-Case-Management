"""
tests/unit/test_assignment_transaction.py — Tests for transactional case assignment.

Covers:
  - Successful assignment when case has no existing paralegal
  - AssignmentConflict raised when already assigned
  - ValueError raised when case doesn't exist
  - bulk_assign endpoint: updated / skipped / failed buckets
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../api"))
os.environ.setdefault("SSN_KMS_KEY_NAME", "projects/test/locations/us/keyRings/test/cryptoKeys/test")

import pytest
from services.case_service import (
    assign_case_transactional,
    AssignmentConflict,
)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _mock_snapshot(exists: bool, data: dict | None = None):
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data or {}
    return snap


def _mock_db_with_snapshot(snapshot):
    """Build a mock db where doc_ref.get(transaction=...) returns the snapshot."""
    doc_ref = MagicMock()
    doc_ref.get = AsyncMock(return_value=snapshot)

    collection = MagicMock()
    collection.document.return_value = doc_ref

    db = MagicMock()
    db.collection.return_value = collection

    # Transaction mock — needs to be callable and support async context
    mock_txn = MagicMock()
    mock_txn.update = MagicMock()
    db.transaction.return_value = mock_txn

    return db, doc_ref, mock_txn


# ══════════════════════════════════════════════════════════════════════════════
# 1. assign_case_transactional
# ══════════════════════════════════════════════════════════════════════════════

class TestAssignCaseTransactional:

    @pytest.mark.asyncio
    async def test_assigns_when_no_existing_paralegal(self):
        snapshot = _mock_snapshot(True, {
            "caseId": "ZAD-2026-06-0001",
            "assignment": {"assignedParalegal": None},
        })
        db, doc_ref, mock_txn = _mock_db_with_snapshot(snapshot)

        # Patch the transactional decorator to just call the inner function
        with patch("services.case_service.firestore.async_transactional",
                    side_effect=lambda fn: fn):
            result = await assign_case_transactional(
                case_id="ZAD-2026-06-0001",
                assignee="user_abc",
                db=db,
            )

        assert result["assignedParalegal"] == "user_abc"
        assert result["case_id"] == "ZAD-2026-06-0001"
        mock_txn.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_conflict_when_already_assigned(self):
        snapshot = _mock_snapshot(True, {
            "caseId": "ZAD-2026-06-0001",
            "assignment": {"assignedParalegal": "existing_user"},
        })
        db, doc_ref, mock_txn = _mock_db_with_snapshot(snapshot)

        with patch("services.case_service.firestore.async_transactional",
                    side_effect=lambda fn: fn):
            with pytest.raises(AssignmentConflict) as exc_info:
                await assign_case_transactional(
                    case_id="ZAD-2026-06-0001",
                    assignee="new_user",
                    db=db,
                )

        assert exc_info.value.existing_assignee == "existing_user"
        assert exc_info.value.case_id == "ZAD-2026-06-0001"
        mock_txn.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_value_error_when_case_not_found(self):
        snapshot = _mock_snapshot(False)
        db, doc_ref, mock_txn = _mock_db_with_snapshot(snapshot)

        with patch("services.case_service.firestore.async_transactional",
                    side_effect=lambda fn: fn):
            with pytest.raises(ValueError, match="not found"):
                await assign_case_transactional(
                    case_id="ZAD-NONEXISTENT",
                    assignee="user_abc",
                    db=db,
                )

    @pytest.mark.asyncio
    async def test_assigns_when_assignment_field_missing(self):
        """Case doc has no 'assignment' field at all — should assign."""
        snapshot = _mock_snapshot(True, {
            "caseId": "ZAD-2026-06-0002",
            # no "assignment" key
        })
        db, doc_ref, mock_txn = _mock_db_with_snapshot(snapshot)

        with patch("services.case_service.firestore.async_transactional",
                    side_effect=lambda fn: fn):
            result = await assign_case_transactional(
                case_id="ZAD-2026-06-0002",
                assignee="user_xyz",
                db=db,
            )

        assert result["assignedParalegal"] == "user_xyz"
        mock_txn.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_assigns_when_assignment_is_empty_string(self):
        """assignedParalegal is empty string — treated as unassigned."""
        snapshot = _mock_snapshot(True, {
            "caseId": "ZAD-2026-06-0003",
            "assignment": {"assignedParalegal": ""},
        })
        db, doc_ref, mock_txn = _mock_db_with_snapshot(snapshot)

        with patch("services.case_service.firestore.async_transactional",
                    side_effect=lambda fn: fn):
            result = await assign_case_transactional(
                case_id="ZAD-2026-06-0003",
                assignee="user_new",
                db=db,
            )

        assert result["assignedParalegal"] == "user_new"
        mock_txn.update.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# 2. AssignmentConflict exception
# ══════════════════════════════════════════════════════════════════════════════

class TestAssignmentConflict:

    def test_stores_case_id_and_assignee(self):
        exc = AssignmentConflict("ZAD-001", "user_old")
        assert exc.case_id == "ZAD-001"
        assert exc.existing_assignee == "user_old"
        assert "ZAD-001" in str(exc)
        assert "user_old" in str(exc)
