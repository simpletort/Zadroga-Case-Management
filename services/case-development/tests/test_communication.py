"""
Unit tests for the Communication Log service and route.
All Firestore and Firebase auth calls are mocked.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from fastapi.testclient import TestClient


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_comm_doc(
    comm_id,
    channel="Email",
    direction="Outbound",
    subject="Follow-up",
    body=None,
    from_address="noreply@simpletort.com",
    to="jane.doe@example.com",
    delivery_status="Sent",
    is_automated=False,
    logged_by="staff-uid",
    sent_at=None,
):
    doc = MagicMock()
    doc.id = comm_id
    doc.to_dict.return_value = {
        "channel":           channel,
        "direction":         direction,
        "subject":           subject,
        "body":              body,
        "from":              from_address,
        "to":                to,
        "deliveryStatus":    delivery_status,
        "isAutomated":       is_automated,
        "loggedBy":          logged_by,
        "templateId":        "",
        "externalMessageId": "",
        "sentAt":            sent_at or datetime(2026, 1, 10, tzinfo=timezone.utc),
    }
    return doc


def _make_db(comm_docs=None, case_exists=True):
    db = MagicMock()

    case_snap = MagicMock()
    case_snap.exists = case_exists

    sub_col = MagicMock()
    sub_col.stream.return_value = iter(comm_docs or [])

    case_ref = MagicMock()
    case_ref.get.return_value = case_snap
    case_ref.collection.return_value = sub_col

    db.collection.return_value.document.return_value = case_ref
    return db, case_ref


def _call_list(db, case_id="ZAD-2026-01-0001", **kwargs):
    from app.services.communication_service import list_communications
    defaults = dict(channel=None, page=1, page_size=20)
    defaults.update(kwargs)
    return list_communications(db=db, case_id=case_id, **defaults)


def _call_create(db, case_id="ZAD-2026-01-0001", actor_uid="staff-uid", **kwargs):
    from app.services.communication_service import create_communication
    defaults = dict(
        channel="Call",
        direction="Outbound",
        subject="Follow-up call",
        body=None,
        from_address=None,
        to=None,
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
        docs = [_make_comm_doc(
            "comm-abc",
            channel="Email",
            direction="Inbound",
            subject="Request docs",
            from_address="client@example.com",
            to="noreply@simpletort.com",
            is_automated=True,
        )]
        db, _ = _make_db(docs)
        result = _call_list(db)
        item = result["items"][0]
        assert item["comm_id"] == "comm-abc"
        assert item["channel"] == "Email"
        assert item["direction"] == "Inbound"
        assert item["subject"] == "Request docs"
        assert item["from_address"] == "client@example.com"
        assert item["to"] == "noreply@simpletort.com"
        assert item["is_automated"] is True

    def test_channel_filter_applied(self):
        docs = [
            _make_comm_doc("c1", channel="Call"),
            _make_comm_doc("c2", channel="Email"),
            _make_comm_doc("c3", channel="Call"),
        ]
        db, _ = _make_db(docs)
        result = _call_list(db, channel="Call")
        assert result["total"] == 2
        assert all(i["channel"] == "Call" for i in result["items"])

    def test_channel_filter_no_match(self):
        docs = [_make_comm_doc("c1", channel="Call")]
        db, _ = _make_db(docs)
        result = _call_list(db, channel="Fax")
        assert result["total"] == 0

    def test_case_not_found_raises_404(self):
        from fastapi import HTTPException
        db, _ = _make_db(case_exists=False)
        with pytest.raises(HTTPException) as exc:
            _call_list(db)
        assert exc.value.status_code == 404

    def test_timestamp_normalised_to_utc(self):
        naive_dt = datetime(2026, 3, 1, 10, 0, 0)   # no tzinfo
        docs = [_make_comm_doc("c1", sent_at=naive_dt)]
        db, _ = _make_db(docs)
        result = _call_list(db)
        assert result["items"][0]["sent_at"].tzinfo is not None

    def test_sorted_newest_first(self):
        older = datetime(2026, 1, 1, tzinfo=timezone.utc)
        newer = datetime(2026, 3, 1, tzinfo=timezone.utc)
        docs = [_make_comm_doc("c1", sent_at=older), _make_comm_doc("c2", sent_at=newer)]
        db, _ = _make_db(docs)
        result = _call_list(db)
        assert result["items"][0]["comm_id"] == "c2"
        assert result["items"][1]["comm_id"] == "c1"


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

        case_ref = MagicMock()
        case_ref.get.return_value = case_snap

        batch = MagicMock()
        db.batch.return_value = batch
        db.collection.return_value.document.return_value = case_ref

        return db, batch

    def test_returns_comm_entry(self):
        db, _ = self._make_db_for_create()
        result = _call_create(db)
        assert result["channel"] == "Call"
        assert result["direction"] == "Outbound"
        assert result["subject"] == "Follow-up call"
        assert result["is_automated"] is False
        assert result["delivery_status"] == "Sent"
        assert result["logged_by"] == "staff-uid"
        assert "comm_id" in result
        assert result["sent_at"] is not None

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

    def test_get_endpoint_200(self):
        svc_result = {
            "items": [], "total": 0, "page": 1, "page_size": 20, "total_pages": 1
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.services.communication_service.list_communications",
                   return_value=svc_result):
            from importlib import reload
            import main as m
            client = TestClient(m.app, raise_server_exceptions=False)
            resp = client.get("/api/v1/cases/ZAD-2026-01-0001/communications")
        assert resp.status_code == 200

    def test_post_endpoint_201(self):
        svc_result = {
            "comm_id": "abc-123",
            "channel": "Call", "direction": "Outbound",
            "subject": "Test", "body": None,
            "from_address": None, "to": None,
            "delivery_status": "Sent", "is_automated": False,
            "logged_by": "staff-uid", "template_id": None,
            "external_message_id": None,
            "sent_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.communication.create_communication",
                   return_value=svc_result):
            from importlib import reload
            import main as m
            client = TestClient(m.app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/cases/ZAD-2026-01-0001/communications",
                json={"channel": "Call", "direction": "Outbound", "subject": "Test"},
            )
        assert resp.status_code == 201
