"""
Tests for GET/PATCH /api/v1/settings/case-profile-editable-fields.

Covers:
  - get_editable_fields: defaults (unconfigured doc → full catalog enabled),
    reading a configured subset, and defence-in-depth filtering of unknown
    field names that may have been hand-written into Firestore.
  - update_editable_fields: happy path, rejection of names outside the fixed
    catalog (400), and that it can never enable status/case_id/created_at or
    other-service-owned fields because they're absent from the catalog.
  - Route integration via FastAPI TestClient.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.models.case_profile import ALLOWED_FIELDS


# ── Helpers ────────────────────────────────────────────────────────────────

def _settings_snap(enabled_fields=None, exists=True):
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = {"enabledFields": enabled_fields} if enabled_fields is not None else {}
    return snap


def _make_db(settings_snap=None):
    db = MagicMock()
    settings_ref = MagicMock()
    settings_ref.get.return_value = settings_snap or _settings_snap(exists=False)

    def _collection(name):
        coll = MagicMock()
        if name == "firmSettings":
            coll.document.return_value = settings_ref
        return coll

    db.collection.side_effect = _collection
    return db, settings_ref


# ── Service tests ─────────────────────────────────────────────────────────

class TestGetEditableFields:

    def test_unconfigured_doc_enables_full_catalog(self):
        from app.services.case_profile_fields_service import get_editable_fields

        db, _ = _make_db()
        result = get_editable_fields(db)
        enabled = {f["field"] for f in result["fields"] if f["enabled"]}
        assert enabled == set(ALLOWED_FIELDS)
        assert result["updated_at"] is None

    def test_configured_subset_reflected(self):
        from app.services.case_profile_fields_service import get_editable_fields

        db, _ = _make_db(_settings_snap(enabled_fields=["phone", "notes"]))
        result = get_editable_fields(db)
        enabled = {f["field"] for f in result["fields"] if f["enabled"]}
        assert enabled == {"phone", "notes"}
        disabled = {f["field"] for f in result["fields"] if not f["enabled"]}
        assert "date_of_birth" in disabled
        assert "assigned_attorney" in disabled

    def test_every_catalog_field_has_a_descriptor(self):
        from app.services.case_profile_fields_service import get_editable_fields

        db, _ = _make_db()
        result = get_editable_fields(db)
        assert {f["field"] for f in result["fields"]} == set(ALLOWED_FIELDS)

    def test_phi_classification_matches_catalog(self):
        from app.services.case_profile_fields_service import get_editable_fields

        db, _ = _make_db()
        result = get_editable_fields(db)
        by_field = {f["field"]: f for f in result["fields"]}
        assert by_field["notes"]["phi"] is False
        assert by_field["date_of_birth"]["phi"] is True

    def test_stale_doc_with_unknown_field_is_filtered_out(self):
        """Defence in depth: a hand-edited Firestore doc listing a field outside
        the catalog (e.g. a leftover 'status') must never surface as enabled."""
        from app.services.case_profile_fields_service import get_enabled_field_set

        db, _ = _make_db(_settings_snap(enabled_fields=["phone", "status", "assigned_paralegal"]))
        enabled = get_enabled_field_set(db)
        assert enabled == {"phone"}
        assert "status" not in enabled
        assert "assigned_paralegal" not in enabled


class TestUpdateEditableFields:

    def test_happy_path_updates_and_returns_new_state(self):
        from app.services.case_profile_fields_service import update_editable_fields

        db, settings_ref = _make_db()
        # After the write, a follow-up read reflects the new config.
        settings_ref.get.return_value = _settings_snap(enabled_fields=["phone", "notes"])
        result = update_editable_fields(db=db, enabled_fields=["phone", "notes"], actor_uid="admin-uid")

        settings_ref.set.assert_called_once()
        written = settings_ref.set.call_args[0][0]
        assert written["enabledFields"] == ["notes", "phone"]
        assert written["updatedBy"] == "admin-uid"

        enabled = {f["field"] for f in result["fields"] if f["enabled"]}
        assert enabled == {"phone", "notes"}

    def test_unknown_field_rejected_with_400(self):
        from app.services.case_profile_fields_service import update_editable_fields

        db, _ = _make_db()
        with pytest.raises(HTTPException) as exc_info:
            update_editable_fields(db=db, enabled_fields=["phone", "made_up_field"], actor_uid="admin-uid")
        assert exc_info.value.status_code == 400
        assert "made_up_field" in exc_info.value.detail

    def test_cannot_enable_status(self):
        """status is not in FIELD_CATALOG at all — always rejected, regardless of config."""
        from app.services.case_profile_fields_service import update_editable_fields

        db, _ = _make_db()
        with pytest.raises(HTTPException) as exc_info:
            update_editable_fields(db=db, enabled_fields=["status"], actor_uid="admin-uid")
        assert exc_info.value.status_code == 400

    def test_cannot_enable_assigned_paralegal(self):
        """Owned by POST /cases/{caseId}/assign — not in FIELD_CATALOG."""
        from app.services.case_profile_fields_service import update_editable_fields

        db, _ = _make_db()
        with pytest.raises(HTTPException) as exc_info:
            update_editable_fields(db=db, enabled_fields=["assigned_paralegal"], actor_uid="admin-uid")
        assert exc_info.value.status_code == 400

    def test_empty_list_disables_every_field(self):
        from app.services.case_profile_fields_service import update_editable_fields

        db, settings_ref = _make_db()
        settings_ref.get.return_value = _settings_snap(enabled_fields=[])
        result = update_editable_fields(db=db, enabled_fields=[], actor_uid="admin-uid")
        assert all(not f["enabled"] for f in result["fields"])


# ── Route integration tests ────────────────────────────────────────────────

class TestCaseProfileFieldsRoute:

    def _client(self):
        from importlib import reload
        import main as m
        reload(m)
        return TestClient(m.app, raise_server_exceptions=False)

    def test_get_returns_200_with_catalog(self):
        client = self._client()
        mock_result = {
            "fields": [{"field": "phone", "enabled": True, "phi": True}],
            "updated_at": None,
            "updated_by": None,
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.case_profile_fields.get_editable_fields", return_value=mock_result):
            resp = client.get(
                "/api/v1/settings/case-profile-editable-fields",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        assert resp.json()["fields"] == mock_result["fields"]

    def test_patch_returns_200(self):
        client = self._client()
        mock_result = {
            "fields": [{"field": "phone", "enabled": True, "phi": True}],
            "updated_at": None,
            "updated_by": "admin-uid",
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.case_profile_fields.update_editable_fields", return_value=mock_result):
            resp = client.patch(
                "/api/v1/settings/case-profile-editable-fields",
                json={"enabled_fields": ["phone"]},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        assert resp.json()["updated_by"] == "admin-uid"

    def test_patch_400_propagates(self):
        client = self._client()
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch(
                 "app.routes.case_profile_fields.update_editable_fields",
                 side_effect=HTTPException(status_code=400, detail="Unknown field(s): made_up"),
             ):
            resp = client.patch(
                "/api/v1/settings/case-profile-editable-fields",
                json={"enabled_fields": ["made_up"]},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 400
