"""
Tests for the Case Update feature.

Coverage:
  - Model validation (CreateUpdateRequest, EditUpdateRequest)
  - list_updates: happy path, sort order, pagination, 404
  - create_update: happy path, field values, batch write, author name fallback, 404
  - edit_update: author can edit, non-author 403, first-edit audit fields,
                 subsequent edits, 404 for case/update
  - delete_update: author can delete, role-based override, non-author 403, 404
  - Route integration via FastAPI TestClient (patches service layer)
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call
from fastapi import HTTPException
from fastapi.testclient import TestClient


# ── Constants ──────────────────────────────────────────────────────────────────

_NOW   = datetime(2026, 6, 4, 10, 0, 0, tzinfo=timezone.utc)
_LATER = datetime(2026, 6, 4, 11, 0, 0, tzinfo=timezone.utc)
_CASE  = "ZAD-2026-06-0001"
_UID   = "author-uid"
_OTHER = "other-uid"
_UPD   = "upd-uuid-0001"


# ── Firestore mock helpers ─────────────────────────────────────────────────────

def _make_case_ref(exists=True, update_doc=None):
    """Return (db, case_ref, update_ref) mocks."""
    db = MagicMock()

    case_snap = MagicMock()
    case_snap.exists = exists

    case_ref = MagicMock()
    case_ref.get.return_value = case_snap

    # Sub-collection routing
    def _sub(name):
        coll = MagicMock()
        if name == "updates" and update_doc is not None:
            coll.document.return_value = update_doc
            coll.stream.return_value   = iter([update_doc])
        elif name == "updates":
            coll.document.return_value = MagicMock()
            coll.stream.return_value   = iter([])
        else:
            coll.document.return_value = MagicMock()
        return coll

    case_ref.collection.side_effect = _sub
    db.collection.return_value.document.return_value = case_ref
    db.batch.return_value = MagicMock()
    return db, case_ref


def _make_update_snap(
    update_id=_UPD,
    case_id=_CASE,
    text="Hello world",
    author_id=_UID,
    author_name="Alice",
    author_role="paralegal",
    created_at=None,
    updated_at=None,
    is_edited=False,
    original_text=None,
    edit_history=None,
    exists=True,
):
    snap = MagicMock()
    snap.exists = exists
    snap.id     = update_id
    snap.to_dict.return_value = {
        "updateId":    update_id,
        "caseId":      case_id,
        "text":        text,
        "authorId":    author_id,
        "authorName":  author_name,
        "authorRole":  author_role,
        "createdAt":   created_at or _NOW,
        "updatedAt":   updated_at or _NOW,
        "isEdited":    is_edited,
        "originalText": original_text,
        "editHistory": edit_history or [],
    }
    return snap


def _make_db_for_list(update_snaps, case_exists=True):
    db = MagicMock()

    case_snap = MagicMock()
    case_snap.exists = case_exists

    updates_coll = MagicMock()
    updates_coll.stream.return_value = iter(update_snaps)

    case_ref = MagicMock()
    case_ref.get.return_value = case_snap
    case_ref.collection.return_value = updates_coll

    db.collection.return_value.document.return_value = case_ref
    return db


def _make_db_for_create(case_exists=True, staff_name=None):
    db = MagicMock()

    case_snap = MagicMock()
    case_snap.exists = case_exists

    staff_snap = MagicMock()
    staff_snap.exists = staff_name is not None
    staff_snap.to_dict.return_value = {"displayName": staff_name} if staff_name else {}

    case_ref = MagicMock()
    case_ref.get.return_value = case_snap

    def _case_sub(name):
        coll = MagicMock()
        coll.document.return_value = MagicMock()
        return coll

    case_ref.collection.side_effect = _case_sub

    def _top_coll(name):
        coll = MagicMock()
        if name == "cases":
            coll.document.return_value = case_ref
        elif name == "staff":
            coll.document.return_value = MagicMock(get=MagicMock(return_value=staff_snap))
        else:
            coll.document.return_value = MagicMock()
        return coll

    db.collection.side_effect = _top_coll
    db.batch.return_value = MagicMock()
    return db


def _make_db_for_edit(update_snap, case_exists=True, update_exists=True):
    db = MagicMock()

    case_snap = MagicMock()
    case_snap.exists = case_exists

    update_ref = MagicMock()
    update_ref.get.return_value = update_snap if update_exists else _missing_snap()

    updates_coll = MagicMock()
    updates_coll.document.return_value = update_ref

    case_ref = MagicMock()
    case_ref.get.return_value = case_snap

    def _case_sub(name):
        if name == "updates":
            return updates_coll
        coll = MagicMock()
        coll.document.return_value = MagicMock()
        return coll

    case_ref.collection.side_effect = _case_sub
    db.collection.return_value.document.return_value = case_ref
    db.batch.return_value = MagicMock()
    return db, update_ref


def _make_db_for_delete(update_snap, case_exists=True, update_exists=True):
    db = MagicMock()

    case_snap = MagicMock()
    case_snap.exists = case_exists

    update_ref = MagicMock()
    update_ref.get.return_value = update_snap if update_exists else _missing_snap()

    updates_coll = MagicMock()
    updates_coll.document.return_value = update_ref

    case_ref = MagicMock()
    case_ref.get.return_value = case_snap

    def _case_sub(name):
        if name == "updates":
            return updates_coll
        return MagicMock()

    case_ref.collection.side_effect = _case_sub
    db.collection.return_value.document.return_value = case_ref
    return db, update_ref


def _missing_snap():
    snap = MagicMock()
    snap.exists = False
    return snap


# ═══════════════════════════════════════════════════════════════════════════════
# Model validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestUpdateModels:

    def test_create_empty_text_raises(self):
        from pydantic import ValidationError
        from app.models.update import CreateUpdateRequest
        with pytest.raises(ValidationError):
            CreateUpdateRequest(text="")

    def test_create_whitespace_only_raises(self):
        from pydantic import ValidationError
        from app.models.update import CreateUpdateRequest
        with pytest.raises(ValidationError):
            CreateUpdateRequest(text="   ")

    def test_create_valid_text_accepted(self):
        from app.models.update import CreateUpdateRequest
        req = CreateUpdateRequest(text="Some update text")
        assert req.text == "Some update text"

    def test_edit_empty_text_raises(self):
        from pydantic import ValidationError
        from app.models.update import EditUpdateRequest
        with pytest.raises(ValidationError):
            EditUpdateRequest(text="")

    def test_edit_whitespace_only_raises(self):
        from pydantic import ValidationError
        from app.models.update import EditUpdateRequest
        with pytest.raises(ValidationError):
            EditUpdateRequest(text="\t\n")

    def test_edit_valid_text_accepted(self):
        from app.models.update import EditUpdateRequest
        req = EditUpdateRequest(text="New text")
        assert req.text == "New text"


# ═══════════════════════════════════════════════════════════════════════════════
# list_updates
# ═══════════════════════════════════════════════════════════════════════════════

class TestListUpdates:

    def _call(self, db, case_id=_CASE, page=1, page_size=20):
        from app.services.update_service import list_updates
        return list_updates(db=db, case_id=case_id, page=page, page_size=page_size)

    def test_empty_case_returns_valid_structure(self):
        db = _make_db_for_list([])
        result = self._call(db)
        assert result["items"] == []
        assert result["total"] == 0
        assert result["total_pages"] == 1
        assert result["page"] == 1

    def test_returns_all_items(self):
        snaps = [_make_update_snap(f"u{i}") for i in range(3)]
        db    = _make_db_for_list(snaps)
        result = self._call(db)
        assert result["total"] == 3
        assert len(result["items"]) == 3

    def test_sorted_newest_first(self):
        older = _make_update_snap("u1", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        newer = _make_update_snap("u2", created_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
        db    = _make_db_for_list([older, newer])
        result = self._call(db)
        assert result["items"][0]["update_id"] == "u2"
        assert result["items"][1]["update_id"] == "u1"

    def test_pagination_first_page(self):
        snaps  = [_make_update_snap(f"u{i}") for i in range(25)]
        db     = _make_db_for_list(snaps)
        result = self._call(db, page=1, page_size=20)
        assert len(result["items"]) == 20
        assert result["total"] == 25
        assert result["total_pages"] == 2

    def test_pagination_second_page_remainder(self):
        snaps  = [_make_update_snap(f"u{i}") for i in range(25)]
        db     = _make_db_for_list(snaps)
        result = self._call(db, page=2, page_size=20)
        assert len(result["items"]) == 5

    def test_pagination_beyond_last_returns_empty(self):
        snaps  = [_make_update_snap("u1")]
        db     = _make_db_for_list(snaps)
        result = self._call(db, page=99, page_size=20)
        assert result["items"] == []

    def test_case_not_found_raises_404(self):
        db = _make_db_for_list([], case_exists=False)
        with pytest.raises(HTTPException) as exc:
            self._call(db)
        assert exc.value.status_code == 404

    def test_timestamp_normalised_to_utc(self):
        naive_dt = datetime(2026, 3, 1, 10, 0, 0)
        snap = _make_update_snap("u1", created_at=naive_dt)
        db   = _make_db_for_list([snap])
        result = self._call(db)
        assert result["items"][0]["created_at"].tzinfo is not None

    def test_fields_mapped_correctly(self):
        snap = _make_update_snap(
            "u1",
            text="Test text",
            author_id="uid-001",
            author_name="Bob",
            author_role="paralegal",
        )
        db     = _make_db_for_list([snap])
        result = self._call(db)
        item = result["items"][0]
        assert item["update_id"] == "u1"
        assert item["text"]        == "Test text"
        assert item["author_id"]   == "uid-001"
        assert item["author_name"] == "Bob"
        assert item["author_role"] == "paralegal"
        assert item["is_edited"]   is False
        assert item["original_text"] is None
        assert item["edit_history"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# create_update
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreateUpdate:

    def _call(self, db, case_id=_CASE, actor_uid=_UID,
              actor_role="paralegal", text="New update"):
        from app.services.update_service import create_update
        return create_update(
            db=db, case_id=case_id, actor_uid=actor_uid,
            actor_role=actor_role, text=text,
        )

    def test_returns_correct_fields(self):
        db     = _make_db_for_create(staff_name="Alice")
        result = self._call(db)
        assert result["text"]        == "New update"
        assert result["author_id"]   == _UID
        assert result["author_name"] == "Alice"
        assert result["author_role"] == "paralegal"
        assert result["case_id"]     == _CASE
        assert "update_id" in result
        assert result["is_edited"]    is False
        assert result["original_text"] is None
        assert result["edit_history"] == []

    def test_created_at_and_updated_at_set(self):
        db     = _make_db_for_create(staff_name="Alice")
        result = self._call(db)
        assert result["created_at"] is not None
        assert result["updated_at"] == result["created_at"]

    def test_update_id_is_unique(self):
        db1 = _make_db_for_create(staff_name="Alice")
        db2 = _make_db_for_create(staff_name="Alice")
        r1  = self._call(db1)
        r2  = self._call(db2)
        assert r1["update_id"] != r2["update_id"]

    def test_batch_committed_once(self):
        db = _make_db_for_create(staff_name="Alice")
        self._call(db)
        db.batch.return_value.commit.assert_called_once()

    def test_timeline_event_written(self):
        db = _make_db_for_create(staff_name="Alice")
        self._call(db)
        batch = db.batch.return_value
        set_calls = batch.set.call_args_list
        # First set() is the update doc, second is the timeline event
        assert len(set_calls) == 2
        timeline_data = set_calls[1][0][1]
        assert timeline_data["eventType"] == "CaseUpdate"

    def test_author_name_fallback_when_staff_doc_missing(self):
        db     = _make_db_for_create(staff_name=None)
        result = self._call(db, actor_uid="no-staff-uid")
        assert result["author_name"] == "no-staff-uid"

    def test_case_not_found_raises_404(self):
        db = _make_db_for_create(case_exists=False)
        with pytest.raises(HTTPException) as exc:
            self._call(db)
        assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# edit_update
# ═══════════════════════════════════════════════════════════════════════════════

class TestEditUpdate:

    def _call(self, db, case_id=_CASE, update_id=_UPD,
              actor_uid=_UID, new_text="Edited text"):
        from app.services.update_service import edit_update
        return edit_update(
            db=db, case_id=case_id, update_id=update_id,
            actor_uid=actor_uid, new_text=new_text,
        )

    def test_author_can_edit(self):
        snap = _make_update_snap(author_id=_UID, text="Original")
        db, _ = _make_db_for_edit(snap)
        result = self._call(db, actor_uid=_UID, new_text="Edited")
        assert result["text"] == "Edited"

    def test_non_author_raises_403(self):
        snap = _make_update_snap(author_id=_UID, text="Original")
        db, _ = _make_db_for_edit(snap)
        with pytest.raises(HTTPException) as exc:
            self._call(db, actor_uid=_OTHER)
        assert exc.value.status_code == 403

    def test_first_edit_sets_original_text(self):
        snap = _make_update_snap(author_id=_UID, text="First text", is_edited=False)
        db, update_ref = _make_db_for_edit(snap)
        result = self._call(db, actor_uid=_UID, new_text="Second text")
        assert result["original_text"] == "First text"

    def test_first_edit_adds_one_history_entry(self):
        snap = _make_update_snap(author_id=_UID, text="First text", is_edited=False)
        db, _ = _make_db_for_edit(snap)
        result = self._call(db, actor_uid=_UID, new_text="Second text")
        assert len(result["edit_history"]) == 1
        assert result["edit_history"][0]["text"] == "First text"

    def test_first_edit_sets_is_edited_true(self):
        snap = _make_update_snap(author_id=_UID, text="First text", is_edited=False)
        db, _ = _make_db_for_edit(snap)
        result = self._call(db, actor_uid=_UID, new_text="Second text")
        assert result["is_edited"] is True

    def test_subsequent_edit_grows_history(self):
        existing_history = [{"text": "First text", "editedAt": _NOW}]
        snap = _make_update_snap(
            author_id=_UID,
            text="Second text",
            is_edited=True,
            original_text="First text",
            edit_history=existing_history,
        )
        db, _ = _make_db_for_edit(snap)
        result = self._call(db, actor_uid=_UID, new_text="Third text")
        assert len(result["edit_history"]) == 2
        assert result["edit_history"][0]["text"] == "First text"
        assert result["edit_history"][1]["text"] == "Second text"

    def test_subsequent_edit_does_not_change_original_text(self):
        existing_history = [{"text": "First text", "editedAt": _NOW}]
        snap = _make_update_snap(
            author_id=_UID,
            text="Second text",
            is_edited=True,
            original_text="First text",
            edit_history=existing_history,
        )
        db, _ = _make_db_for_edit(snap)
        result = self._call(db, actor_uid=_UID, new_text="Third text")
        assert result["original_text"] == "First text"

    def test_text_replaced_with_new_text(self):
        snap = _make_update_snap(author_id=_UID, text="Old text")
        db, _ = _make_db_for_edit(snap)
        result = self._call(db, actor_uid=_UID, new_text="Brand new text")
        assert result["text"] == "Brand new text"

    def test_batch_committed_once(self):
        snap = _make_update_snap(author_id=_UID, text="Hello")
        db, _ = _make_db_for_edit(snap)
        self._call(db, actor_uid=_UID)
        db.batch.return_value.commit.assert_called_once()

    def test_batch_update_contains_correct_fields(self):
        snap = _make_update_snap(author_id=_UID, text="Hello", is_edited=False)
        db, update_ref = _make_db_for_edit(snap)
        self._call(db, actor_uid=_UID, new_text="World")
        batch = db.batch.return_value
        update_calls = batch.update.call_args_list
        assert len(update_calls) == 1
        fields = update_calls[0][0][1]
        assert fields["text"]         == "World"
        assert fields["isEdited"]     is True
        assert fields["originalText"] == "Hello"
        assert "updatedAt" in fields
        assert "editHistory" in fields

    def test_case_not_found_raises_404(self):
        snap = _make_update_snap(author_id=_UID)
        db, _ = _make_db_for_edit(snap, case_exists=False)
        with pytest.raises(HTTPException) as exc:
            self._call(db)
        assert exc.value.status_code == 404

    def test_update_not_found_raises_404(self):
        snap = _make_update_snap(author_id=_UID)
        db, _ = _make_db_for_edit(snap, update_exists=False)
        with pytest.raises(HTTPException) as exc:
            self._call(db)
        assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# delete_update
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeleteUpdate:

    def _call(self, db, case_id=_CASE, update_id=_UPD,
              actor_uid=_UID, actor_role="paralegal"):
        from app.services.update_service import delete_update
        return delete_update(
            db=db, case_id=case_id, update_id=update_id,
            actor_uid=actor_uid, actor_role=actor_role,
        )

    def test_author_can_delete(self):
        snap = _make_update_snap(author_id=_UID)
        db, update_ref = _make_db_for_delete(snap)
        result = self._call(db, actor_uid=_UID, actor_role="paralegal")
        assert result["deleted"] is True
        assert result["update_id"] == _UPD

    def test_non_author_paralegal_raises_403(self):
        snap = _make_update_snap(author_id=_UID)
        db, _ = _make_db_for_delete(snap)
        with pytest.raises(HTTPException) as exc:
            self._call(db, actor_uid=_OTHER, actor_role="paralegal")
        assert exc.value.status_code == 403

    def test_non_author_junior_partner_raises_403(self):
        snap = _make_update_snap(author_id=_UID)
        db, _ = _make_db_for_delete(snap)
        with pytest.raises(HTTPException) as exc:
            self._call(db, actor_uid=_OTHER, actor_role="junior_partner")
        assert exc.value.status_code == 403

    def test_admin_staff_can_delete_any_update(self):
        snap = _make_update_snap(author_id=_UID)
        db, _ = _make_db_for_delete(snap)
        result = self._call(db, actor_uid=_OTHER, actor_role="admin_staff")
        assert result["deleted"] is True

    def test_senior_partner_can_delete_any_update(self):
        snap = _make_update_snap(author_id=_UID)
        db, _ = _make_db_for_delete(snap)
        result = self._call(db, actor_uid=_OTHER, actor_role="senior_partner")
        assert result["deleted"] is True

    def test_system_admin_can_delete_any_update(self):
        snap = _make_update_snap(author_id=_UID)
        db, _ = _make_db_for_delete(snap)
        result = self._call(db, actor_uid=_OTHER, actor_role="system_admin")
        assert result["deleted"] is True

    def test_delete_calls_firestore_delete(self):
        snap = _make_update_snap(author_id=_UID)
        db, update_ref = _make_db_for_delete(snap)
        self._call(db, actor_uid=_UID)
        update_ref.delete.assert_called_once()

    def test_case_not_found_raises_404(self):
        snap = _make_update_snap(author_id=_UID)
        db, _ = _make_db_for_delete(snap, case_exists=False)
        with pytest.raises(HTTPException) as exc:
            self._call(db)
        assert exc.value.status_code == 404

    def test_update_not_found_raises_404(self):
        snap = _make_update_snap(author_id=_UID)
        db, _ = _make_db_for_delete(snap, update_exists=False)
        with pytest.raises(HTTPException) as exc:
            self._call(db)
        assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# Route integration (TestClient — patches service layer)
# ═══════════════════════════════════════════════════════════════════════════════

_LIST_RESULT = {
    "items": [], "total": 0, "page": 1, "page_size": 20, "total_pages": 1,
}

_UPDATE_RESULT = {
    "update_id":    _UPD,
    "case_id":      _CASE,
    "text":         "Test update",
    "author_id":    _UID,
    "author_name":  "Alice",
    "author_role":  "paralegal",
    "created_at":   _NOW,
    "updated_at":   _NOW,
    "is_edited":    False,
    "original_text": None,
    "edit_history": [],
}

_DELETE_RESULT = {"update_id": _UPD, "deleted": True}


class TestUpdateRoutes:

    def _client(self):
        from main import app
        return TestClient(app, raise_server_exceptions=False)

    def test_get_returns_200(self):
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.services.update_service.list_updates", return_value=_LIST_RESULT):
            resp = self._client().get(
                f"/api/v1/cases/{_CASE}/updates",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_post_returns_201(self):
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.update.create_update", return_value=_UPDATE_RESULT):
            resp = self._client().post(
                f"/api/v1/cases/{_CASE}/updates",
                json={"text": "Test update"},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["update_id"] == _UPD
        assert data["text"]      == "Test update"

    def test_patch_returns_200(self):
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.update.edit_update", return_value=_UPDATE_RESULT):
            resp = self._client().patch(
                f"/api/v1/cases/{_CASE}/updates/{_UPD}",
                json={"text": "Edited"},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        assert resp.json()["update_id"] == _UPD

    def test_delete_returns_200(self):
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.update.delete_update", return_value=_DELETE_RESULT):
            resp = self._client().delete(
                f"/api/v1/cases/{_CASE}/updates/{_UPD}",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_404_propagates_from_service(self):
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.update.create_update",
                   side_effect=HTTPException(status_code=404, detail="not found")):
            resp = self._client().post(
                f"/api/v1/cases/NOPE/updates",
                json={"text": "hi"},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 404

    def test_403_propagates_from_service(self):
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.update.edit_update",
                   side_effect=HTTPException(status_code=403, detail="forbidden")):
            resp = self._client().patch(
                f"/api/v1/cases/{_CASE}/updates/{_UPD}",
                json={"text": "attempt"},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 403

    def test_post_empty_text_returns_422(self):
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()):
            resp = self._client().post(
                f"/api/v1/cases/{_CASE}/updates",
                json={"text": ""},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 422

    def test_patch_empty_text_returns_422(self):
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()):
            resp = self._client().patch(
                f"/api/v1/cases/{_CASE}/updates/{_UPD}",
                json={"text": "   "},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 422
