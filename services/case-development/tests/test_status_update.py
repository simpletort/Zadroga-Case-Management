"""
Tests for the generic Case Status Update feature.

Coverage:
  - update_case_status service: happy path, 404 on missing case
  - Firestore batch writes: case fields + timeline event shape
  - logger.info called after commit
  - Route integration via FastAPI TestClient
    - 200 on success
    - 404 when case not found
    - actor name resolved from staff collection
    - notes optional (omitted and included)
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call
from fastapi import HTTPException
from fastapi.testclient import TestClient


# ── Constants ──────────────────────────────────────────────────────────────────

_NOW   = datetime(2026, 6, 22, 9, 0, 0, tzinfo=timezone.utc)
_CASE  = "ZAD-2026-06-0001"
_UID   = "staff-uid-001"
_NAME  = "Alice Smith"


# ── Firestore mock helpers ─────────────────────────────────────────────────────

def _make_db(exists=True, current_status="Pending Paralegal Review"):
    db = MagicMock()

    case_snap = MagicMock()
    case_snap.exists = exists
    case_snap.to_dict.return_value = {"status": current_status} if exists else {}

    case_ref = MagicMock()
    case_ref.get.return_value = case_snap

    timeline_ref = MagicMock()
    timeline_ref.id = "tl-uuid-001"

    def _sub(name):
        coll = MagicMock()
        coll.document.return_value = timeline_ref
        return coll

    case_ref.collection.side_effect = _sub
    db.collection.return_value.document.return_value = case_ref
    db.batch.return_value = MagicMock()
    return db, case_ref, timeline_ref


# ── Service unit tests ─────────────────────────────────────────────────────────

class TestUpdateCaseStatusService:

    def test_happy_path_updates_case_and_writes_timeline(self):
        from app.services.status_update_service import update_case_status

        db, case_ref, timeline_ref = _make_db(current_status="Pending Paralegal Review")
        batch = db.batch.return_value

        with patch("app.services.status_update_service.datetime") as mock_dt:
            mock_dt.now.return_value = _NOW
            result = update_case_status(
                db=db,
                case_id=_CASE,
                new_status="Awarded",
                actor_uid=_UID,
                actor_name=_NAME,
                notes="Settlement reached",
            )

        # Return value
        assert result["case_id"]         == _CASE
        assert result["previous_status"] == "Pending Paralegal Review"
        assert result["new_status"]      == "Awarded"
        assert result["updated_by"]      == _UID

        # Case document updated
        case_update_kwargs = batch.update.call_args[0][1]
        assert case_update_kwargs["status"]              == "Awarded"
        assert "updatedAt"           in case_update_kwargs
        assert "lastStatusChangedAt" in case_update_kwargs

        # statusHistory entry appended
        history_entry = case_update_kwargs["statusHistory"].values[0]
        assert history_entry["status"]    == "Awarded"
        assert history_entry["updatedBy"] == _UID
        assert history_entry["note"]      == "Settlement reached"
        assert "timestamp" in history_entry

        # Timeline event written
        timeline_set_kwargs = batch.set.call_args[0][1]
        assert timeline_set_kwargs["eventType"]                    == "StatusChange"
        assert timeline_set_kwargs["metadata"]["previousStatus"]   == "Pending Paralegal Review"
        assert timeline_set_kwargs["metadata"]["newStatus"]        == "Awarded"
        assert timeline_set_kwargs["metadata"]["notes"]            == "Settlement reached"
        assert timeline_set_kwargs["metadata"]["source"]           == "manual_override"
        assert timeline_set_kwargs["performedBy"]                  == _UID
        assert timeline_set_kwargs["performedByName"]              == _NAME

        # Batch committed
        batch.commit.assert_called_once()

    def test_notes_none_written_to_timeline(self):
        from app.services.status_update_service import update_case_status

        db, _, _ = _make_db(current_status="New Lead")
        batch = db.batch.return_value

        with patch("app.services.status_update_service.datetime") as mock_dt:
            mock_dt.now.return_value = _NOW
            update_case_status(
                db=db,
                case_id=_CASE,
                new_status="Closed",
                actor_uid=_UID,
                actor_name=_NAME,
                notes=None,
            )

        timeline_set_kwargs = batch.set.call_args[0][1]
        assert timeline_set_kwargs["metadata"]["notes"] is None

    def test_default_note_when_notes_none(self):
        from app.services.status_update_service import update_case_status

        db, _, _ = _make_db(current_status="New Lead")
        batch = db.batch.return_value

        with patch("app.services.status_update_service.datetime") as mock_dt:
            mock_dt.now.return_value = _NOW
            update_case_status(
                db=db,
                case_id=_CASE,
                new_status="Closed",
                actor_uid=_UID,
                actor_name=_NAME,
                notes=None,
            )

        case_update_kwargs = batch.update.call_args[0][1]
        history_entry = case_update_kwargs["statusHistory"].values[0]
        assert history_entry["note"] == "Manual status update"

    def test_404_when_case_not_found(self):
        from app.services.status_update_service import update_case_status

        db, _, _ = _make_db(exists=False)

        with pytest.raises(HTTPException) as exc_info:
            update_case_status(
                db=db,
                case_id="ZAD-MISSING",
                new_status="Awarded",
                actor_uid=_UID,
                actor_name=_NAME,
            )

        assert exc_info.value.status_code == 404
        assert "ZAD-MISSING" in exc_info.value.detail

    def test_logger_called_after_commit(self):
        from app.services.status_update_service import update_case_status

        db, _, _ = _make_db(current_status="Pending Paralegal Review")

        with patch("app.services.status_update_service.datetime") as mock_dt, \
             patch("app.services.status_update_service.logger") as mock_log:
            mock_dt.now.return_value = _NOW
            update_case_status(
                db=db,
                case_id=_CASE,
                new_status="Settled",
                actor_uid=_UID,
                actor_name=_NAME,
            )

        mock_log.info.assert_called_once()
        log_args = mock_log.info.call_args[0]
        assert _CASE   in str(log_args)
        assert "Settled" in str(log_args)

    def test_previous_status_captured_correctly(self):
        from app.services.status_update_service import update_case_status

        db, _, _ = _make_db(current_status="VCF - Submitted")
        batch = db.batch.return_value

        with patch("app.services.status_update_service.datetime") as mock_dt:
            mock_dt.now.return_value = _NOW
            result = update_case_status(
                db=db,
                case_id=_CASE,
                new_status="Awarded",
                actor_uid=_UID,
                actor_name=_NAME,
            )

        assert result["previous_status"] == "VCF - Submitted"
        timeline_kwargs = batch.set.call_args[0][1]
        assert timeline_kwargs["metadata"]["previousStatus"] == "VCF - Submitted"


# ── Route integration tests ────────────────────────────────────────────────────

def _make_client(user=None):
    from main import app
    client = TestClient(app, raise_server_exceptions=False)
    if user is None:
        user = {"uid": _UID, "role": "admin_staff"}
    client.app.state  # ensure state exists
    return client, user


class TestStatusUpdateRoute:

    def _patch_service(self, result):
        return patch(
            "app.routes.status_update.update_case_status",
            return_value=result,
        )

    def _patch_firestore(self, actor_name=_NAME):
        staff_snap = MagicMock()
        staff_snap.exists = True
        staff_snap.to_dict.return_value = {"displayName": actor_name}

        db = MagicMock()
        db.collection.return_value.document.return_value.get.return_value = staff_snap

        return patch("app.routes.status_update.get_firestore_client", return_value=db)

    def _good_result(self):
        return {
            "case_id":         _CASE,
            "previous_status": "Pending Paralegal Review",
            "new_status":      "Awarded",
            "updated_at":      _NOW,
            "updated_by":      _UID,
        }

    def test_patch_returns_200_on_success(self):
        from main import app
        client = TestClient(app)

        with self._patch_service(self._good_result()), \
             self._patch_firestore(), \
             patch("shared.middlewares.auth.AuthMiddleware.__call__", new=_bypass_auth(_UID, "admin_staff")):
            resp = client.patch(
                f"/api/v1/cases/{_CASE}/status",
                json={"status": "Awarded"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["new_status"]      == "Awarded"
        assert data["previous_status"] == "Pending Paralegal Review"
        assert data["case_id"]         == _CASE

    def test_patch_with_notes(self):
        from main import app
        client = TestClient(app)

        with self._patch_service(self._good_result()), \
             self._patch_firestore(), \
             patch("shared.middlewares.auth.AuthMiddleware.__call__", new=_bypass_auth(_UID, "admin_staff")):
            resp = client.patch(
                f"/api/v1/cases/{_CASE}/status",
                json={"status": "Awarded", "notes": "Settled out of court"},
            )

        assert resp.status_code == 200

    def test_patch_404_propagated(self):
        from main import app
        client = TestClient(app)

        with patch(
                "app.routes.status_update.update_case_status",
                side_effect=HTTPException(status_code=404, detail="Case 'ZAD-MISSING' not found."),
             ), \
             self._patch_firestore(), \
             patch("shared.middlewares.auth.AuthMiddleware.__call__", new=_bypass_auth(_UID, "admin_staff")):
            resp = client.patch(
                "/api/v1/cases/ZAD-MISSING/status",
                json={"status": "Awarded"},
            )

        assert resp.status_code == 404

    def test_actor_name_resolved_from_staff(self):
        from main import app
        client = TestClient(app)

        captured = {}

        def _spy(db, case_id, new_status, actor_uid, actor_name, notes=None):
            captured["actor_name"] = actor_name
            return self._good_result()

        with patch("app.routes.status_update.update_case_status", side_effect=_spy), \
             self._patch_firestore(actor_name="Bob Jones"), \
             patch("shared.middlewares.auth.AuthMiddleware.__call__", new=_bypass_auth(_UID, "admin_staff")):
            client.patch(
                f"/api/v1/cases/{_CASE}/status",
                json={"status": "Closed"},
            )

        assert captured.get("actor_name") == "Bob Jones"

    def test_actor_name_none_when_staff_not_found(self):
        from main import app
        client = TestClient(app)

        captured = {}

        def _spy(db, case_id, new_status, actor_uid, actor_name, notes=None):
            captured["actor_name"] = actor_name
            return self._good_result()

        staff_snap = MagicMock()
        staff_snap.exists = False
        db = MagicMock()
        db.collection.return_value.document.return_value.get.return_value = staff_snap

        with patch("app.routes.status_update.update_case_status", side_effect=_spy), \
             patch("app.routes.status_update.get_firestore_client", return_value=db), \
             patch("shared.middlewares.auth.AuthMiddleware.__call__", new=_bypass_auth(_UID, "admin_staff")):
            client.patch(
                f"/api/v1/cases/{_CASE}/status",
                json={"status": "Closed"},
            )

        assert captured.get("actor_name") is None


# ── Auth bypass helper ─────────────────────────────────────────────────────────

def _bypass_auth(uid: str, role: str):
    """Return an ASGI middleware call that injects user into request.state."""
    async def _call(self_middleware, scope, receive, send):
        if scope["type"] == "http":
            from starlette.requests import Request
            from starlette.datastructures import State
            request = Request(scope, receive, send)
            request.state.user = {"uid": uid, "role": role}
        await self_middleware.app(scope, receive, send)
    return _call
