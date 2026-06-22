"""
Tests for the Case Status Registry feature.

Coverage:
  Service unit tests:
    - get_statuses: doc exists, doc missing
    - create_status: happy path, duplicate value → 409
    - update_status: happy path (partial merge), not found → 404
    - delete_status: happy path, not found → 404
    - updatedAt / updatedBy written on every mutation

  Route integration tests (service layer patched):
    - GET  200 with ordered list
    - POST 201 with new entry, 409 on duplicate
    - PATCH 200, 404 on missing value
    - DELETE 200, 404 on missing value
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient


# ── Constants ──────────────────────────────────────────────────────────────────

_NOW  = datetime(2026, 6, 22, 10, 0, 0, tzinfo=timezone.utc)
_UID  = "admin-uid-001"

_ENTRY_1 = {"value": "New Lead",    "label": "New Lead",    "category": "active",  "order": 1, "color": "#6B7280"}
_ENTRY_2 = {"value": "Awarded",     "label": "Awarded",     "category": "closed",  "order": 9, "color": "#22C55E"}


# ── Firestore mock helpers ─────────────────────────────────────────────────────

def _make_db(statuses=None, doc_exists=True):
    db   = MagicMock()
    snap = MagicMock()
    snap.exists = doc_exists
    snap.to_dict.return_value = (
        {"statuses": statuses or [], "updatedAt": _NOW, "updatedBy": _UID}
        if doc_exists else {}
    )
    db.collection.return_value.document.return_value.get.return_value = snap
    return db


# ── get_statuses ───────────────────────────────────────────────────────────────

class TestGetStatuses:

    def test_returns_list_when_doc_exists(self):
        from app.services.case_status_registry_service import get_statuses
        db = _make_db(statuses=[_ENTRY_1, _ENTRY_2])
        result = get_statuses(db)
        assert len(result["statuses"]) == 2
        assert result["statuses"][0]["value"] == "New Lead"

    def test_returns_empty_list_when_doc_missing(self):
        from app.services.case_status_registry_service import get_statuses
        db = _make_db(doc_exists=False)
        result = get_statuses(db)
        assert result["statuses"] == []
        assert result["updated_at"] is None
        assert result["updated_by"] is None


# ── create_status ──────────────────────────────────────────────────────────────

class TestCreateStatus:

    def test_happy_path_appends_entry(self):
        from app.services.case_status_registry_service import create_status
        db  = _make_db(statuses=[_ENTRY_1])
        ref = db.collection.return_value.document.return_value

        with patch("app.services.case_status_registry_service.datetime") as mock_dt:
            mock_dt.now.return_value = _NOW
            result = create_status(db=db, entry=_ENTRY_2, actor_uid=_UID)

        assert len(result["statuses"]) == 2
        assert result["statuses"][1]["value"] == "Awarded"
        assert result["updated_by"] == _UID
        ref.set.assert_called_once()

    def test_duplicate_value_raises_409(self):
        from app.services.case_status_registry_service import create_status
        db = _make_db(statuses=[_ENTRY_1])

        with pytest.raises(HTTPException) as exc:
            create_status(db=db, entry=_ENTRY_1, actor_uid=_UID)

        assert exc.value.status_code == 409
        assert "New Lead" in exc.value.detail

    def test_updatedAt_and_updatedBy_written(self):
        from app.services.case_status_registry_service import create_status
        db  = _make_db(statuses=[])
        ref = db.collection.return_value.document.return_value

        with patch("app.services.case_status_registry_service.datetime") as mock_dt:
            mock_dt.now.return_value = _NOW
            create_status(db=db, entry=_ENTRY_1, actor_uid=_UID)

        written = ref.set.call_args[0][0]
        assert written["updatedAt"] == _NOW
        assert written["updatedBy"] == _UID


# ── update_status ──────────────────────────────────────────────────────────────

class TestUpdateStatus:

    def test_happy_path_merges_fields(self):
        from app.services.case_status_registry_service import update_status
        db  = _make_db(statuses=[_ENTRY_1, _ENTRY_2])
        ref = db.collection.return_value.document.return_value

        with patch("app.services.case_status_registry_service.datetime") as mock_dt:
            mock_dt.now.return_value = _NOW
            result = update_status(
                db=db,
                value="New Lead",
                fields={"color": "#FF0000", "label": "Lead"},
                actor_uid=_UID,
            )

        updated = next(s for s in result["statuses"] if s["value"] == "New Lead")
        assert updated["color"] == "#FF0000"
        assert updated["label"] == "Lead"
        # Other fields preserved
        assert updated["category"] == "active"
        assert updated["order"]    == 1

    def test_not_found_raises_404(self):
        from app.services.case_status_registry_service import update_status
        db = _make_db(statuses=[_ENTRY_1])

        with pytest.raises(HTTPException) as exc:
            update_status(db=db, value="Does Not Exist", fields={"color": "#000"}, actor_uid=_UID)

        assert exc.value.status_code == 404

    def test_unrelated_entries_untouched(self):
        from app.services.case_status_registry_service import update_status
        db = _make_db(statuses=[_ENTRY_1, _ENTRY_2])

        with patch("app.services.case_status_registry_service.datetime") as mock_dt:
            mock_dt.now.return_value = _NOW
            result = update_status(db=db, value="New Lead", fields={"order": 99}, actor_uid=_UID)

        awarded = next(s for s in result["statuses"] if s["value"] == "Awarded")
        assert awarded["order"] == 9   # unchanged


# ── delete_status ──────────────────────────────────────────────────────────────

class TestDeleteStatus:

    def test_happy_path_removes_entry(self):
        from app.services.case_status_registry_service import delete_status
        db  = _make_db(statuses=[_ENTRY_1, _ENTRY_2])
        ref = db.collection.return_value.document.return_value

        with patch("app.services.case_status_registry_service.datetime") as mock_dt:
            mock_dt.now.return_value = _NOW
            result = delete_status(db=db, value="New Lead", actor_uid=_UID)

        assert len(result["statuses"]) == 1
        assert result["statuses"][0]["value"] == "Awarded"
        ref.set.assert_called_once()

    def test_not_found_raises_404(self):
        from app.services.case_status_registry_service import delete_status
        db = _make_db(statuses=[_ENTRY_1])

        with pytest.raises(HTTPException) as exc:
            delete_status(db=db, value="Ghost Status", actor_uid=_UID)

        assert exc.value.status_code == 404

    def test_updatedAt_and_updatedBy_written(self):
        from app.services.case_status_registry_service import delete_status
        db  = _make_db(statuses=[_ENTRY_1])
        ref = db.collection.return_value.document.return_value

        with patch("app.services.case_status_registry_service.datetime") as mock_dt:
            mock_dt.now.return_value = _NOW
            delete_status(db=db, value="New Lead", actor_uid=_UID)

        written = ref.set.call_args[0][0]
        assert written["updatedAt"] == _NOW
        assert written["updatedBy"] == _UID


# ── Route integration tests ────────────────────────────────────────────────────

def _bypass_auth(uid: str, role: str):
    async def _call(self_middleware, scope, receive, send):
        if scope["type"] == "http":
            from starlette.requests import Request
            request = Request(scope, receive, send)
            request.state.user = {"uid": uid, "role": role}
        await self_middleware.app(scope, receive, send)
    return _call


def _good_registry():
    return {
        "statuses":   [_ENTRY_1, _ENTRY_2],
        "updated_at": _NOW,
        "updated_by": _UID,
    }


class TestCaseStatusRegistryRoutes:

    def test_get_returns_200_with_list(self):
        from main import app
        client = TestClient(app)

        with patch("app.routes.case_status_registry.get_statuses", return_value=_good_registry()), \
             patch("app.routes.case_status_registry.get_firestore_client", return_value=MagicMock()), \
             patch("shared.middlewares.auth.AuthMiddleware.__call__", new=_bypass_auth(_UID, "paralegal")):
            resp = client.get("/api/v1/settings/case-statuses")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["statuses"]) == 2
        assert data["statuses"][0]["value"] == "New Lead"

    def test_post_returns_201_on_success(self):
        from main import app
        client = TestClient(app)

        with patch("app.routes.case_status_registry.create_status", return_value=_good_registry()), \
             patch("app.routes.case_status_registry.get_firestore_client", return_value=MagicMock()), \
             patch("shared.middlewares.auth.AuthMiddleware.__call__", new=_bypass_auth(_UID, "admin_staff")):
            resp = client.post(
                "/api/v1/settings/case-statuses",
                json={"value": "New Lead", "label": "New Lead", "category": "active", "order": 1, "color": "#6B7280"},
            )

        assert resp.status_code == 201

    def test_post_409_on_duplicate(self):
        from main import app
        client = TestClient(app)

        with patch(
                "app.routes.case_status_registry.create_status",
                side_effect=HTTPException(status_code=409, detail="Status 'New Lead' already exists."),
             ), \
             patch("app.routes.case_status_registry.get_firestore_client", return_value=MagicMock()), \
             patch("shared.middlewares.auth.AuthMiddleware.__call__", new=_bypass_auth(_UID, "admin_staff")):
            resp = client.post(
                "/api/v1/settings/case-statuses",
                json={"value": "New Lead", "label": "New Lead", "category": "active", "order": 1, "color": "#6B7280"},
            )

        assert resp.status_code == 409

    def test_patch_returns_200(self):
        from main import app
        client = TestClient(app)

        with patch("app.routes.case_status_registry.update_status", return_value=_good_registry()), \
             patch("app.routes.case_status_registry.get_firestore_client", return_value=MagicMock()), \
             patch("shared.middlewares.auth.AuthMiddleware.__call__", new=_bypass_auth(_UID, "admin_staff")):
            resp = client.patch(
                "/api/v1/settings/case-statuses/New%20Lead",
                json={"color": "#FF0000"},
            )

        assert resp.status_code == 200

    def test_patch_404_when_not_found(self):
        from main import app
        client = TestClient(app)

        with patch(
                "app.routes.case_status_registry.update_status",
                side_effect=HTTPException(status_code=404, detail="Status 'Ghost' not found."),
             ), \
             patch("app.routes.case_status_registry.get_firestore_client", return_value=MagicMock()), \
             patch("shared.middlewares.auth.AuthMiddleware.__call__", new=_bypass_auth(_UID, "admin_staff")):
            resp = client.patch("/api/v1/settings/case-statuses/Ghost", json={"color": "#000"})

        assert resp.status_code == 404

    def test_delete_returns_200(self):
        from main import app
        client = TestClient(app)

        remaining = {"statuses": [_ENTRY_2], "updated_at": _NOW, "updated_by": _UID}

        with patch("app.routes.case_status_registry.delete_status", return_value=remaining), \
             patch("app.routes.case_status_registry.get_firestore_client", return_value=MagicMock()), \
             patch("shared.middlewares.auth.AuthMiddleware.__call__", new=_bypass_auth(_UID, "admin_staff")):
            resp = client.delete("/api/v1/settings/case-statuses/New%20Lead")

        assert resp.status_code == 200
        assert len(resp.json()["statuses"]) == 1

    def test_delete_404_when_not_found(self):
        from main import app
        client = TestClient(app)

        with patch(
                "app.routes.case_status_registry.delete_status",
                side_effect=HTTPException(status_code=404, detail="Status 'Ghost' not found."),
             ), \
             patch("app.routes.case_status_registry.get_firestore_client", return_value=MagicMock()), \
             patch("shared.middlewares.auth.AuthMiddleware.__call__", new=_bypass_auth(_UID, "admin_staff")):
            resp = client.delete("/api/v1/settings/case-statuses/Ghost")

        assert resp.status_code == 404
