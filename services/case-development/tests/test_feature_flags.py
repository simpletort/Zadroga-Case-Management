"""
Tests for the configurable feature-flags gate (firmSettings/feature_flags).

Coverage:
  Service unit tests:
    - get_feature_flags: doc missing → defaults (require_ai_summary=True)
    - get_feature_flags: doc exists → returns stored value
    - update_feature_flags: merges fields, writes updatedAt/updatedBy, returns full flag set

  Route integration tests (service layer patched):
    - GET  200 with current flags
    - PATCH 200 with updated flags
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


_NOW = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
_UID = "admin-uid-001"


def _make_db(data=None, doc_exists=True):
    db = MagicMock()
    snap = MagicMock()
    snap.exists = doc_exists
    snap.to_dict.return_value = data if (doc_exists and data is not None) else {}
    db.collection.return_value.document.return_value.get.return_value = snap
    return db


# ── get_feature_flags ───────────────────────────────────────────────────────

class TestGetFeatureFlags:

    def test_defaults_true_when_doc_missing(self):
        from app.services.feature_flags_service import get_feature_flags
        db = _make_db(doc_exists=False)

        result = get_feature_flags(db)

        assert result["require_ai_summary"] is True
        assert result["updated_at"] is None
        assert result["updated_by"] is None

    def test_returns_stored_false_value(self):
        from app.services.feature_flags_service import get_feature_flags
        db = _make_db(data={"require_ai_summary": False, "updatedAt": _NOW, "updatedBy": _UID})

        result = get_feature_flags(db)

        assert result["require_ai_summary"] is False
        assert result["updated_at"] == _NOW
        assert result["updated_by"] == _UID

    def test_defaults_true_when_key_absent_from_existing_doc(self):
        from app.services.feature_flags_service import get_feature_flags
        db = _make_db(data={"updatedAt": _NOW, "updatedBy": _UID})

        result = get_feature_flags(db)

        assert result["require_ai_summary"] is True


# ── update_feature_flags ─────────────────────────────────────────────────────

class TestUpdateFeatureFlags:

    def test_disables_flag_and_returns_result(self):
        from app.services.feature_flags_service import update_feature_flags
        db = _make_db(data={"require_ai_summary": True})
        ref = db.collection.return_value.document.return_value

        with patch("app.services.feature_flags_service.datetime") as mock_dt:
            mock_dt.now.return_value = _NOW
            # After the write, get_feature_flags re-reads — simulate the new value.
            ref.get.return_value.to_dict.return_value = {
                "require_ai_summary": False, "updatedAt": _NOW, "updatedBy": _UID,
            }
            result = update_feature_flags(db=db, fields={"require_ai_summary": False}, actor_uid=_UID)

        assert result["require_ai_summary"] is False
        assert result["updated_by"] == _UID
        ref.set.assert_called_once()
        written = ref.set.call_args[0][0]
        assert written["require_ai_summary"] is False
        assert written["updatedBy"] == _UID
        assert ref.set.call_args[1]["merge"] is True

    def test_merge_true_preserves_other_settings(self):
        from app.services.feature_flags_service import update_feature_flags
        db = _make_db(data={"require_ai_summary": True})
        ref = db.collection.return_value.document.return_value

        update_feature_flags(db=db, fields={"require_ai_summary": True}, actor_uid=_UID)

        assert ref.set.call_args[1]["merge"] is True


# ── Route integration tests ─────────────────────────────────────────────────

def _bypass_auth(uid: str, role: str):
    async def _call(self_middleware, scope, receive, send):
        if scope["type"] == "http":
            from starlette.requests import Request
            request = Request(scope, receive, send)
            request.state.user = {"uid": uid, "role": role}
        await self_middleware.app(scope, receive, send)
    return _call


class TestFeatureFlagsRoutes:

    def test_get_returns_200_with_flags(self):
        from main import app
        client = TestClient(app)

        flags = {"require_ai_summary": True, "updated_at": _NOW, "updated_by": _UID}
        with patch("app.routes.feature_flags.get_feature_flags", return_value=flags), \
             patch("app.routes.feature_flags.get_firestore_client", return_value=MagicMock()), \
             patch("shared.middlewares.auth.AuthMiddleware.__call__", new=_bypass_auth(_UID, "junior_partner")):
            resp = client.get("/api/v1/settings/feature-flags")

        assert resp.status_code == 200
        assert resp.json()["require_ai_summary"] is True

    def test_patch_returns_200_with_updated_flags(self):
        from main import app
        client = TestClient(app)

        updated = {"require_ai_summary": False, "updated_at": _NOW, "updated_by": _UID}
        with patch("app.routes.feature_flags.update_feature_flags", return_value=updated), \
             patch("app.routes.feature_flags.get_firestore_client", return_value=MagicMock()), \
             patch("shared.middlewares.auth.AuthMiddleware.__call__", new=_bypass_auth(_UID, "senior_partner")):
            resp = client.patch(
                "/api/v1/settings/feature-flags",
                json={"require_ai_summary": False},
            )

        assert resp.status_code == 200
        assert resp.json()["require_ai_summary"] is False

    def test_patch_omitted_field_not_forwarded_to_service(self):
        """Sending an empty body should not overwrite require_ai_summary."""
        from main import app
        client = TestClient(app)

        current = {"require_ai_summary": True, "updated_at": _NOW, "updated_by": _UID}
        with patch("app.routes.feature_flags.update_feature_flags", return_value=current) as mock_update, \
             patch("app.routes.feature_flags.get_firestore_client", return_value=MagicMock()), \
             patch("shared.middlewares.auth.AuthMiddleware.__call__", new=_bypass_auth(_UID, "senior_partner")):
            resp = client.patch("/api/v1/settings/feature-flags", json={})

        assert resp.status_code == 200
        assert mock_update.call_args.kwargs["fields"] == {}
