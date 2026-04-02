"""
Unit tests for the Communication Log service and route.
All Firestore and Firebase auth calls are mocked.
"""

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone
from fastapi.testclient import TestClient


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_comm_doc(
    comm_id,
    comm_type="call",
    direction="outbound",
    subject="Follow-up",
    notes=None,
    contact_name="Jane Smith",
    contact_method="212-555-0100",
    created_by="staff-uid",
    created_by_name="Sarah Chen",
    created_at=None,
):
    doc = MagicMock()
    doc.id = comm_id
    doc.to_dict.return_value = {
        "type":          comm_type,
        "direction":     direction,
        "subject":       subject,
        "notes":         notes,
        "contactName":   contact_name,
        "contactMethod": contact_method,
        "createdBy":     created_by,
        "createdByName": created_by_name,
        "createdAt":     created_at or datetime(2026, 1, 10, tzinfo=timezone.utc),
    }
    return doc


def _make_db(comm_docs=None, case_exists=True):
    """Build a mock Firestore client with a case doc and communications sub-collection."""
    db = MagicMock()

    # Case document
    case_snap = MagicMock()
    case_snap.exists = case_exists

    # Sub-collection query chain
    sub_query = MagicMock()
    sub_query.order_by.return_value = sub_query
    sub_query.stream.return_value = iter(comm_docs or [])

    case_ref = MagicMock()
    case_ref.get.return_value = case_snap
    case_ref.collection.return_value = sub_query

    db.collection.return_value.document.return_value = case_ref

    # Staff lookup (for actor display name)
    staff_snap = MagicMock()
    staff_snap.exists = True
    staff_snap.to_dict.return_value = {"displayName": "Sarah Chen"}
    db.collection.return_value.document.return_value = case_ref

    return db, case_ref


def _call_list(db, case_id="ZAD-2026-01-0001", **kwargs):
    from app.services.communication_service import list_communications
    defaults = dict(comm_type=None, page=1, page_size=20)
    defaults.update(kwargs)
    return list_communications(db=db, case_id=case_id, **defaults)


def _call_create(db, case_id="ZAD-2026-01-0001", actor_uid="staff-uid", **kwargs):
    from app.services.communication_service import create_communication
    defaults = dict(
        comm_type="call",
        direction="outbound",
        subject="Follow-up call",
        notes=None,
        contact_name="Jane Smith",
        contact_method="212-555-0100",
    )
    defaults.update(kwargs)
    return create_communication(db=db, case_id=case_id, actor_uid=actor_uid, **defaults)


# ── Service: list ──────────────────────────────────────────────────────────

class TestListCommunications:

    def test_returns_all_entries(self):
        docs = [_make_comm_doc("c1"), _make_comm_doc("c2")]
        db, _ = _make_db(docs)
        result = _call_list(db)
        assert result["total"] == 2
        assert len(result["items"]) == 2

    def test_empty_case_returns_valid_structure(self):
        db, _ = _make_db([])
        result = _call_list(db)
        assert result["items"] == []
        assert result["total"] == 0
        assert result["total_pages"] == 1

    def test_fields_mapped_correctly(self):
        docs = [_make_comm_doc("comm-abc", comm_type="email", direction="inbound",
                               subject="Request docs", contact_name="Client")]
        db, _ = _make_db(docs)
        result = _call_list(db)
        item = result["items"][0]
        assert item["comm_id"] == "comm-abc"
        assert item["type"] == "email"
        assert item["direction"] == "inbound"
        assert item["subject"] == "Request docs"
        assert item["contact_name"] == "Client"

    def test_type_filter_applied(self):
        docs = [
            _make_comm_doc("c1", comm_type="call"),
            _make_comm_doc("c2", comm_type="email"),
            _make_comm_doc("c3", comm_type="call"),
        ]
        db, _ = _make_db(docs)
        result = _call_list(db, comm_type="call")
        assert result["total"] == 2
        assert all(i["type"] == "call" for i in result["items"])

    def test_type_filter_no_match(self):
        docs = [_make_comm_doc("c1", comm_type="call")]
        db, _ = _make_db(docs)
        result = _call_list(db, comm_type="fax")
        assert result["total"] == 0

    def test_case_not_found_raises_404(self):
        from fastapi import HTTPException
        db, _ = _make_db(case_exists=False)
        with pytest.raises(HTTPException) as exc:
            _call_list(db)
        assert exc.value.status_code == 404

    def test_timestamp_normalised_to_utc(self):
        naive_dt = datetime(2026, 3, 1, 10, 0, 0)   # no tzinfo
        docs = [_make_comm_doc("c1", created_at=naive_dt)]
        db, _ = _make_db(docs)
        result = _call_list(db)
        assert result["items"][0]["created_at"].tzinfo is not None


# ── Service: pagination ────────────────────────────────────────────────────

class TestListCommunicationsPagination:

    def test_first_page(self):
        docs = [_make_comm_doc(f"c{i}") for i in range(25)]
        db, _ = _make_db(docs)
        result = _call_list(db, page=1, page_size=20)
        assert len(result["items"]) == 20
        assert result["total"] == 25
        assert result["total_pages"] == 2

    def test_second_page_remainder(self):
        docs = [_make_comm_doc(f"c{i}") for i in range(25)]
        db, _ = _make_db(docs)
        result = _call_list(db, page=2, page_size=20)
        assert len(result["items"]) == 5

    def test_page_beyond_last_returns_empty(self):
        docs = [_make_comm_doc("c1")]
        db, _ = _make_db(docs)
        result = _call_list(db, page=99, page_size=20)
        assert result["items"] == []


# ── Service: create ────────────────────────────────────────────────────────

class TestCreateCommunication:

    def _make_db_for_create(self, case_exists=True):
        db = MagicMock()

        case_snap = MagicMock()
        case_snap.exists = case_exists

        staff_snap = MagicMock()
        staff_snap.exists = True
        staff_snap.to_dict.return_value = {"displayName": "Sarah Chen"}

        case_ref  = MagicMock()
        case_ref.get.return_value = case_snap

        batch = MagicMock()
        db.batch.return_value = batch

        # Route all collection().document() calls through side_effect
        def _col_doc(col_name):
            col = MagicMock()
            if col_name == "cases":
                col.document.return_value = case_ref
            elif col_name == "staff":
                col.document.return_value = MagicMock(get=lambda: staff_snap)
            return col

        db.collection.side_effect = _col_doc
        return db, batch

    def test_returns_comm_entry(self):
        db, _ = self._make_db_for_create()
        result = _call_create(db)
        assert result["type"] == "call"
        assert result["direction"] == "outbound"
        assert result["subject"] == "Follow-up call"
        assert result["created_by"] == "staff-uid"
        assert "comm_id" in result
        assert result["created_at"] is not None

    def test_batch_committed(self):
        db, batch = self._make_db_for_create()
        _call_create(db)
        batch.commit.assert_called_once()

    def test_case_not_found_raises_404(self):
        from fastapi import HTTPException
        db, _ = self._make_db_for_create(case_exists=False)
        with pytest.raises(HTTPException) as exc:
            _call_create(db)
        assert exc.value.status_code == 404

    def test_comm_id_is_unique(self):
        db1, _ = self._make_db_for_create()
        db2, _ = self._make_db_for_create()
        r1 = _call_create(db1)
        r2 = _call_create(db2)
        assert r1["comm_id"] != r2["comm_id"]


# ── RBAC ───────────────────────────────────────────────────────────────────

class TestCommunicationRBAC:

    def test_paralegal_can_read(self):
        from app.utils.auth import ROLE_HIERARCHY, ENDPOINT_MIN_ROLES
        assert ROLE_HIERARCHY["paralegal"] >= ROLE_HIERARCHY[ENDPOINT_MIN_ROLES["comm_read"]]

    def test_paralegal_can_write(self):
        from app.utils.auth import ROLE_HIERARCHY, ENDPOINT_MIN_ROLES
        assert ROLE_HIERARCHY["paralegal"] >= ROLE_HIERARCHY[ENDPOINT_MIN_ROLES["comm_write"]]

    def test_get_endpoint_200(self):
        user = {"uid": "staff-uid", "role": "paralegal"}
        svc_result = {
            "items": [], "total": 0, "page": 1, "page_size": 20, "total_pages": 1
        }
        with patch("app.utils.auth.get_current_user", return_value=user), \
             patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.services.communication_service.list_communications",
                   return_value=svc_result), \
             patch("firebase_admin._apps", [True]):
            from importlib import reload
            import main as m
            client = TestClient(m.app, raise_server_exceptions=False)
            resp = client.get("/api/v1/cases/ZAD-2026-01-0001/communications")
        assert resp.status_code == 200

    def test_post_endpoint_201(self):
        user = {"uid": "staff-uid", "role": "paralegal"}
        svc_result = {
            "comm_id": "abc-123",
            "type": "call", "direction": "outbound",
            "subject": "Test", "notes": None,
            "contact_name": None, "contact_method": None,
            "created_by": "staff-uid", "created_by_name": "Sarah Chen",
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }
        with patch("app.utils.auth.get_current_user", return_value=user), \
             patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.communication.create_communication",
                   return_value=svc_result), \
             patch("firebase_admin._apps", [True]):
            from importlib import reload
            import main as m
            client = TestClient(m.app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/cases/ZAD-2026-01-0001/communications",
                json={"type": "call", "direction": "outbound", "subject": "Test"},
            )
        assert resp.status_code == 201

    def test_unauthenticated_get_rejected(self):
        with patch("firebase_admin._apps", [True]):
            import main as m
            client = TestClient(m.app, raise_server_exceptions=False)
            resp = client.get("/api/v1/cases/ZAD-2026-01-0001/communications")
        assert resp.status_code == 403

    def test_unauthenticated_post_rejected(self):
        with patch("firebase_admin._apps", [True]):
            import main as m
            client = TestClient(m.app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/cases/ZAD-2026-01-0001/communications",
                json={"type": "call", "direction": "outbound", "subject": "Test"},
            )
        assert resp.status_code == 403
