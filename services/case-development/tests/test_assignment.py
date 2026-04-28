"""
Unit tests for the case-development assignment service and routes.

All Firestore and Firebase auth calls are mocked.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from fastapi.testclient import TestClient


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_staff_snap(user_id, role="Paralegal", active_count=3, max_caseload=None, is_active=True):
    snap = MagicMock()
    snap.exists = True
    snap.id = user_id
    snap.to_dict.return_value = {
        "userId": user_id,
        "displayName": "Paralegal {}".format(user_id),
        "role": role,
        "isActive": is_active,
        "activeCaseCount": active_count,
        "maxCaseload": max_caseload,
    }
    return snap


def _make_case_snap(case_id, assigned_paralegal=""):
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = {
        "caseId": case_id,
        "status": "Pending Paralegal Review",
        "assignment": {"assignedParalegal": assigned_paralegal},
    }
    return snap


def _app_with_mocked_auth(role="admin_staff"):
    """Return a TestClient with Firebase auth bypassed."""
    with patch("app.utils.firestore.get_firestore_client"), \
         patch("firebase_admin._apps", [True]):
        from main import app
    client = TestClient(app, raise_server_exceptions=True)
    return client


# ── assignment_service unit tests ──────────────────────────────────────────

class TestGetAssignmentInfo:

    def test_returns_assignment_data(self):
        from app.services.assignment_service import get_assignment_info

        db = MagicMock()
        case_snap = _make_case_snap("ZAD-2024-01-0001", assigned_paralegal="p1")
        staff_snap = _make_staff_snap("p1")

        db.collection.return_value.document.return_value.get.side_effect = [
            case_snap,
            staff_snap,
        ]

        result = get_assignment_info(db, "ZAD-2024-01-0001")

        assert result["assigned_paralegal"] == "p1"
        assert result["assigned_paralegal_name"] == "Paralegal p1"

    def test_case_not_found_raises_404(self):
        from app.services.assignment_service import get_assignment_info
        from fastapi import HTTPException

        db = MagicMock()
        missing = MagicMock()
        missing.exists = False
        db.collection.return_value.document.return_value.get.return_value = missing

        with pytest.raises(HTTPException) as exc_info:
            get_assignment_info(db, "ZAD-INVALID")

        assert exc_info.value.status_code == 404

    def test_unassigned_case_returns_none(self):
        from app.services.assignment_service import get_assignment_info

        db = MagicMock()
        case_snap = _make_case_snap("ZAD-2024-01-0001", assigned_paralegal="")
        db.collection.return_value.document.return_value.get.return_value = case_snap

        result = get_assignment_info(db, "ZAD-2024-01-0001")
        assert result["assigned_paralegal"] is None
        assert result["assigned_paralegal_name"] is None


class TestManualAssign:

    def _build_db(self, case_id, old_paralegal, new_paralegal_id,
                   new_role="Paralegal", case_exists=True, staff_exists=True):
        db = MagicMock()

        new_staff_snap = _make_staff_snap(new_paralegal_id, role=new_role)
        new_staff_snap.exists = staff_exists

        case_snap = _make_case_snap(case_id, assigned_paralegal=old_paralegal)
        case_snap.exists = case_exists

        # First call is the pre-validation read of new staff
        db.collection.return_value.document.return_value.get.side_effect = [
            new_staff_snap,  # pre-validation
        ]

        # For transaction internals, simulate case + staff reads
        txn_case_snap = _make_case_snap(case_id, assigned_paralegal=old_paralegal)
        txn_staff_snap = _make_staff_snap(new_paralegal_id, active_count=2)
        db.transaction.return_value = MagicMock()

        return db

    def test_unknown_paralegal_raises_404(self):
        from app.services.assignment_service import manual_assign
        from fastapi import HTTPException

        db = MagicMock()
        missing_staff = MagicMock()
        missing_staff.exists = False
        db.collection.return_value.document.return_value.get.return_value = missing_staff

        with pytest.raises(HTTPException) as exc_info:
            manual_assign(db, "ZAD-2024-01-0001", "unknown-uid", "admin-uid", None)

        assert exc_info.value.status_code == 404

    def test_non_paralegal_role_raises_422(self):
        from app.services.assignment_service import manual_assign
        from fastapi import HTTPException

        db = MagicMock()
        attorney_snap = _make_staff_snap("atty-1", role="Junior Partner")
        db.collection.return_value.document.return_value.get.return_value = attorney_snap

        with pytest.raises(HTTPException) as exc_info:
            manual_assign(db, "ZAD-2024-01-0001", "atty-1", "admin-uid", None)

        assert exc_info.value.status_code == 422


class TestGetWorkload:

    def test_returns_sorted_by_active_count_desc(self):
        from app.services.assignment_service import get_workload

        db = MagicMock()
        docs = [
            _make_staff_snap("p1", active_count=5),
            _make_staff_snap("p2", active_count=1),
            _make_staff_snap("p3", active_count=8),
        ]
        for d in docs:
            d.id = d.to_dict()["userId"]

        query = MagicMock()
        query.where.return_value = query
        query.stream.return_value = iter(docs)
        db.collection.return_value.where.return_value = query

        result = get_workload(db)

        counts = [r["active_case_count"] for r in result]
        assert counts == sorted(counts, reverse=True)

    def test_empty_staff_returns_empty_list(self):
        from app.services.assignment_service import get_workload

        db = MagicMock()
        query = MagicMock()
        query.where.return_value = query
        query.stream.return_value = iter([])
        db.collection.return_value.where.return_value = query

        assert get_workload(db) == []


# ── Route smoke tests ─────────────────────────────────────────────────────

class TestRBAC:

    def test_paralegal_can_read_workload(self):
        with patch("app.utils.firestore.get_firestore_client") as mock_db_factory, \
             patch("app.services.assignment_service.get_workload", return_value=[]):
            mock_db_factory.return_value = MagicMock()
            from importlib import reload
            import main as m
            client = TestClient(m.app, raise_server_exceptions=False)
            resp = client.get("/api/v1/staff/paralegals/workload")
        assert resp.status_code == 200
