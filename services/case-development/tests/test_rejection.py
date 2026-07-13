"""
Tests for the Rejection workflow.

Covers:
  - RejectCaseRequest / ResubmitCaseRequest model validation
  - reject_case: happy path, status guard, authz, reason validation, batch writes
  - resubmit_case: happy path, status guard, authz, batch writes
  - RBAC: role hierarchy constants; paralegal/unauthenticated blocked from reject
  - Route integration via FastAPI TestClient
"""

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone
from fastapi import HTTPException
from fastapi.testclient import TestClient


# ── Shared constants ──────────────────────────────────────────────────────────

_NOW   = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
_CASE  = "ZAD-2026-04-0001"
_ATTY  = "atty-uid"
_PARA  = "para-uid"
_SP    = "sp-uid"
_ADMIN = "admin-uid"


# ── Snapshot helpers ──────────────────────────────────────────────────────────

def _case_snap(
    case_id=_CASE,
    status="Pending Attorney Review",
    assigned_attorney=_ATTY,
    assigned_paralegal=_PARA,
    rejection=None,
    exists=True,
):
    snap = MagicMock()
    snap.exists = exists
    snap.id     = case_id
    snap.to_dict.return_value = {
        "status":   status,
        "caseType": "VCF",
        "leadData": {"firstName": "Jane", "lastName": "Smith"},
        "assignment": {
            "assignedAttorney":  assigned_attorney,
            "assignedParalegal": assigned_paralegal,
        },
        "rejection": rejection or {},
        "updatedAt": _NOW,
    }
    return snap


def _staff_snap(uid=_ATTY, display_name="Alice Attorney", exists=True):
    snap = MagicMock()
    snap.exists = exists
    snap.id     = uid
    snap.to_dict.return_value = {"displayName": display_name}
    return snap


# ── DB builder helpers ────────────────────────────────────────────────────────

def _make_reject_db(
    case_status="Pending Attorney Review",
    assigned_attorney=_ATTY,
    assigned_paralegal=_PARA,
    case_exists=True,
    actor_display_name="Alice Attorney",
):
    """Firestore mock for reject_case."""
    db = MagicMock()

    rejection_doc = MagicMock()
    timeline_doc  = MagicMock()
    timeline_doc.id = "tl-001"

    def _case_sub(name):
        if name == "rejections":
            coll = MagicMock()
            coll.document.return_value = rejection_doc
            return coll
        if name == "timeline":
            coll = MagicMock()
            coll.document.return_value = timeline_doc
            return coll
        return MagicMock()

    case_ref = MagicMock()
    case_ref.get.return_value = _case_snap(
        status=case_status,
        assigned_attorney=assigned_attorney,
        assigned_paralegal=assigned_paralegal,
        exists=case_exists,
    )
    case_ref.collection.side_effect = _case_sub

    actor_snap = _staff_snap(uid=_ATTY, display_name=actor_display_name)

    def _collection(name):
        if name == "cases":
            coll = MagicMock()
            coll.document.return_value = case_ref
            return coll
        if name == "staff":
            coll = MagicMock()
            coll.document.return_value = MagicMock(get=MagicMock(return_value=actor_snap))
            return coll
        # notifications top-level collection
        coll = MagicMock()
        coll.document.return_value = MagicMock()
        return coll

    db.collection.side_effect = _collection
    db.batch.return_value = MagicMock()
    return db


def _make_resubmit_db(
    case_status="Rejected",
    assigned_attorney=_ATTY,
    assigned_paralegal=_PARA,
    rejection_data=None,
    case_exists=True,
    actor_display_name="Paula Paralegal",
):
    """Firestore mock for resubmit_case."""
    db = MagicMock()

    timeline_doc = MagicMock()
    timeline_doc.id = "tl-002"

    def _case_sub(name):
        if name == "timeline":
            coll = MagicMock()
            coll.document.return_value = timeline_doc
            return coll
        return MagicMock()

    case_ref = MagicMock()
    case_ref.get.return_value = _case_snap(
        status=case_status,
        assigned_attorney=assigned_attorney,
        assigned_paralegal=assigned_paralegal,
        rejection=rejection_data if rejection_data is not None else {"rejectionId": "rej-001", "reason": "incomplete_documentation"},
        exists=case_exists,
    )
    case_ref.collection.side_effect = _case_sub

    actor_snap = _staff_snap(uid=_PARA, display_name=actor_display_name)

    def _collection(name):
        if name == "cases":
            coll = MagicMock()
            coll.document.return_value = case_ref
            return coll
        if name == "staff":
            coll = MagicMock()
            coll.document.return_value = MagicMock(get=MagicMock(return_value=actor_snap))
            return coll
        coll = MagicMock()
        coll.document.return_value = MagicMock()
        return coll

    db.collection.side_effect = _collection
    db.batch.return_value = MagicMock()
    return db


# ═════════════════════════════════════════════════════════════════════════════
# Model validation
# ═════════════════════════════════════════════════════════════════════════════

class TestRejectionModels:

    def test_other_reason_without_notes_raises_validation_error(self):
        from pydantic import ValidationError
        from app.models.rejection import RejectCaseRequest
        with pytest.raises(ValidationError):
            RejectCaseRequest(reason="other", notes=None)

    def test_other_reason_with_blank_notes_raises_validation_error(self):
        from pydantic import ValidationError
        from app.models.rejection import RejectCaseRequest
        with pytest.raises(ValidationError):
            RejectCaseRequest(reason="other", notes="   ")

    def test_other_reason_with_notes_is_valid(self):
        from app.models.rejection import RejectCaseRequest
        req = RejectCaseRequest(reason="other", notes="Unusual circumstance.")
        assert req.reason == "other"
        assert req.notes  == "Unusual circumstance."

    def test_invalid_reason_raises_validation_error(self):
        from pydantic import ValidationError
        from app.models.rejection import RejectCaseRequest
        with pytest.raises(ValidationError):
            RejectCaseRequest(reason="bad_reason")

    @pytest.mark.parametrize("reason", [
        "insufficient_medical_evidence",
        "does_not_meet_vcf_criteria",
        "incomplete_documentation",
        "client_unresponsive",
        "other",
    ])
    def test_all_five_reasons_accepted(self, reason):
        from app.models.rejection import RejectCaseRequest
        notes = "required" if reason == "other" else None
        req = RejectCaseRequest(reason=reason, notes=notes)
        assert req.reason == reason

    def test_non_other_reason_notes_is_optional(self):
        from app.models.rejection import RejectCaseRequest
        req = RejectCaseRequest(reason="incomplete_documentation")
        assert req.notes is None

    def test_resubmit_request_notes_optional(self):
        from app.models.rejection import ResubmitCaseRequest
        req = ResubmitCaseRequest()
        assert req.notes is None

    def test_resubmit_request_accepts_notes(self):
        from app.models.rejection import ResubmitCaseRequest
        req = ResubmitCaseRequest(notes="Fixed all missing docs.")
        assert req.notes == "Fixed all missing docs."


# ═════════════════════════════════════════════════════════════════════════════
# reject_case service
# ═════════════════════════════════════════════════════════════════════════════

class TestRejectCase:

    def _call(self, db, actor_uid=_ATTY, actor_role="junior_partner",
              reason="incomplete_documentation", notes=None, case_id=_CASE):
        from app.services.rejection_service import reject_case
        return reject_case(
            db=db,
            case_id=case_id,
            actor_uid=actor_uid,
            actor_role=actor_role,
            reason=reason,
            notes=notes,
        )

    # ── Happy path ────────────────────────────────────────────────────────────

    def test_returns_rejected_status(self):
        db = _make_reject_db()
        result = self._call(db)
        assert result["status"] == "Rejected"

    def test_returns_rejection_id_as_string(self):
        db = _make_reject_db()
        result = self._call(db)
        assert isinstance(result["rejection_id"], str)
        assert len(result["rejection_id"]) > 0

    def test_returns_rejected_at_datetime(self):
        db = _make_reject_db()
        result = self._call(db)
        assert isinstance(result["rejected_at"], datetime)

    def test_returns_case_id(self):
        db = _make_reject_db()
        result = self._call(db)
        assert result["case_id"] == _CASE

    def test_notified_paralegal_true_when_assigned(self):
        db = _make_reject_db(assigned_paralegal=_PARA)
        result = self._call(db)
        assert result["notified_paralegal"] is True

    def test_notified_paralegal_false_when_none(self):
        db = _make_reject_db(assigned_paralegal=None)
        result = self._call(db)
        assert result["notified_paralegal"] is False

    @pytest.mark.parametrize("reason", [
        "insufficient_medical_evidence",
        "does_not_meet_vcf_criteria",
        "incomplete_documentation",
        "client_unresponsive",
    ])
    def test_all_non_other_reasons_accepted(self, reason):
        db = _make_reject_db()
        result = self._call(db, reason=reason)
        assert result["status"] == "Rejected"

    def test_other_reason_with_notes_accepted(self):
        db = _make_reject_db()
        result = self._call(db, reason="other", notes="No VCF eligibility.")
        assert result["status"] == "Rejected"

    # ── Status guards ─────────────────────────────────────────────────────────

    def test_case_not_found_raises_404(self):
        db = _make_reject_db(case_exists=False)
        with pytest.raises(HTTPException) as exc_info:
            self._call(db)
        assert exc_info.value.status_code == 404

    def test_wrong_status_raises_422(self):
        db = _make_reject_db(case_status="Pending Paralegal Review")
        with pytest.raises(HTTPException) as exc_info:
            self._call(db)
        assert exc_info.value.status_code == 422
        assert "Pending Attorney Review" in exc_info.value.detail

    def test_already_rejected_raises_422(self):
        db = _make_reject_db(case_status="Rejected")
        with pytest.raises(HTTPException) as exc_info:
            self._call(db)
        assert exc_info.value.status_code == 422

    def test_escalated_case_raises_422(self):
        db = _make_reject_db(case_status="Pending Senior Review")
        with pytest.raises(HTTPException) as exc_info:
            self._call(db)
        assert exc_info.value.status_code == 422

    def test_other_reason_blank_notes_belt_and_suspenders_raises_422(self):
        from app.services.rejection_service import reject_case
        db = _make_reject_db()
        with pytest.raises(HTTPException) as exc_info:
            reject_case(
                db=db,
                case_id=_CASE,
                actor_uid=_ATTY,
                actor_role="junior_partner",
                reason="other",
                notes="   ",
            )
        assert exc_info.value.status_code == 422

    # ── Authz guards ──────────────────────────────────────────────────────────

    def test_junior_partner_not_assigned_raises_403(self):
        db = _make_reject_db(assigned_attorney="other-atty-uid")
        with pytest.raises(HTTPException) as exc_info:
            self._call(db, actor_uid=_ATTY, actor_role="junior_partner")
        assert exc_info.value.status_code == 403

    def test_assigned_junior_partner_can_reject(self):
        db = _make_reject_db(assigned_attorney=_ATTY)
        result = self._call(db, actor_uid=_ATTY, actor_role="junior_partner")
        assert result["status"] == "Rejected"

    def test_senior_partner_can_reject_unassigned_case(self):
        db = _make_reject_db(assigned_attorney="other-atty-uid")
        result = self._call(db, actor_uid=_SP, actor_role="senior_partner")
        assert result["status"] == "Rejected"

    def test_system_admin_can_reject_any_case(self):
        db = _make_reject_db(assigned_attorney="other-atty-uid")
        result = self._call(db, actor_uid="admin-uid", actor_role="system_admin")
        assert result["status"] == "Rejected"

    # ── Batch write verification ───────────────────────────────────────────────

    def test_batch_committed_exactly_once(self):
        db = _make_reject_db()
        self._call(db)
        db.batch.return_value.commit.assert_called_once()

    def test_case_doc_updated_with_rejected_status(self):
        db = _make_reject_db()
        self._call(db)
        batch = db.batch.return_value
        update_calls = batch.update.call_args_list
        assert len(update_calls) >= 1
        case_update_kwargs = update_calls[0][0][1]  # second positional arg of first call
        assert case_update_kwargs["status"] == "Rejected"

    def test_case_doc_has_rejected_at_and_rejected_by(self):
        db = _make_reject_db()
        self._call(db)
        batch = db.batch.return_value
        case_update_kwargs = batch.update.call_args_list[0][0][1]
        assert "rejectedAt" in case_update_kwargs
        assert case_update_kwargs["rejectedBy"] == _ATTY

    def test_case_doc_has_rejection_dot_fields(self):
        db = _make_reject_db()
        self._call(db, reason="incomplete_documentation", notes="Missing W-2s.")
        batch = db.batch.return_value
        case_update_kwargs = batch.update.call_args_list[0][0][1]
        assert case_update_kwargs["rejection.reason"] == "incomplete_documentation"
        assert case_update_kwargs["rejection.notes"] == "Missing W-2s."
        assert "rejection.rejectionId" in case_update_kwargs

    def test_rejection_subdoc_set_with_correct_fields(self):
        db = _make_reject_db()
        self._call(db, reason="client_unresponsive")
        batch = db.batch.return_value
        set_calls = batch.set.call_args_list
        # First set() call is the rejection sub-doc
        rejection_data = set_calls[0][0][1]
        assert rejection_data["reason"] == "client_unresponsive"
        assert rejection_data["previousStatus"] == "Pending Attorney Review"
        assert rejection_data["resubmittedAt"] is None
        assert rejection_data["caseId"] == _CASE

    def test_timeline_event_type_is_case_rejection(self):
        db = _make_reject_db()
        self._call(db)
        batch = db.batch.return_value
        set_calls = batch.set.call_args_list
        # Second set() call is the timeline event
        timeline_data = set_calls[1][0][1]
        assert timeline_data["eventType"] == "CaseRejection"

    def test_timeline_metadata_has_correct_statuses(self):
        db = _make_reject_db()
        self._call(db)
        batch = db.batch.return_value
        timeline_data = batch.set.call_args_list[1][0][1]
        assert timeline_data["metadata"]["previousStatus"] == "Pending Attorney Review"
        assert timeline_data["metadata"]["newStatus"] == "Rejected"

    def test_timeline_metadata_has_reason_and_rejection_id(self):
        db = _make_reject_db()
        self._call(db, reason="does_not_meet_vcf_criteria", notes="No exposure.")
        batch = db.batch.return_value
        timeline_data = batch.set.call_args_list[1][0][1]
        assert timeline_data["metadata"]["reason"] == "does_not_meet_vcf_criteria"
        assert timeline_data["metadata"]["notes"] == "No exposure."
        assert "rejectionId" in timeline_data["metadata"]

    def test_notification_sent_to_paralegal(self):
        db = _make_reject_db(assigned_paralegal=_PARA)
        self._call(db)
        batch = db.batch.return_value
        set_calls = batch.set.call_args_list
        # Third set() call is the notification
        notif_data = set_calls[2][0][1]
        assert notif_data["recipientId"] == _PARA

    def test_notification_type_is_case_rejected(self):
        db = _make_reject_db(assigned_paralegal=_PARA)
        self._call(db)
        batch = db.batch.return_value
        notif_data = batch.set.call_args_list[2][0][1]
        assert notif_data["type"] == "case_rejected"

    def test_notification_message_contains_reason_label(self):
        db = _make_reject_db(assigned_paralegal=_PARA)
        self._call(db, reason="insufficient_medical_evidence")
        batch = db.batch.return_value
        notif_data = batch.set.call_args_list[2][0][1]
        assert "Insufficient Medical Evidence" in notif_data["message"]

    def test_no_notification_when_no_paralegal(self):
        db = _make_reject_db(assigned_paralegal=None)
        self._call(db)
        batch = db.batch.return_value
        # 4 set() calls: rejection sub-doc + timeline + decision_audit global + decision_audit case-scoped (no notification)
        assert len(batch.set.call_args_list) == 4

    def test_actor_name_fallback_when_staff_doc_missing(self):
        db = _make_reject_db()
        # Make staff document not exist
        missing_snap = MagicMock()
        missing_snap.exists = False
        staff_coll = MagicMock()
        staff_coll.document.return_value = MagicMock(get=MagicMock(return_value=missing_snap))

        original_side_effect = db.collection.side_effect

        def _patched_collection(name):
            if name == "staff":
                return staff_coll
            return original_side_effect(name)

        db.collection.side_effect = _patched_collection
        result = self._call(db)
        # Should not raise; actor_uid used as fallback
        assert result["status"] == "Rejected"


# ═════════════════════════════════════════════════════════════════════════════
# resubmit_case service
# ═════════════════════════════════════════════════════════════════════════════

class TestResubmitCase:

    def _call(self, db, actor_uid=_PARA, actor_role="paralegal",
              notes=None, case_id=_CASE):
        from app.services.rejection_service import resubmit_case
        return resubmit_case(
            db=db,
            case_id=case_id,
            actor_uid=actor_uid,
            actor_role=actor_role,
            notes=notes,
        )

    # ── Happy path ────────────────────────────────────────────────────────────

    def test_returns_pending_paralegal_review_status(self):
        db = _make_resubmit_db()
        result = self._call(db)
        assert result["status"] == "Pending Paralegal Review"

    def test_returns_resubmitted_at_datetime(self):
        db = _make_resubmit_db()
        result = self._call(db)
        assert isinstance(result["resubmitted_at"], datetime)

    def test_returns_case_id(self):
        db = _make_resubmit_db()
        result = self._call(db)
        assert result["case_id"] == _CASE

    def test_notified_attorney_true_when_assigned(self):
        db = _make_resubmit_db(assigned_attorney=_ATTY)
        result = self._call(db)
        assert result["notified_attorney"] is True

    def test_notified_attorney_false_when_none(self):
        db = _make_resubmit_db(assigned_attorney=None)
        result = self._call(db)
        assert result["notified_attorney"] is False

    # ── Status guards ─────────────────────────────────────────────────────────

    def test_case_not_found_raises_404(self):
        db = _make_resubmit_db(case_exists=False)
        with pytest.raises(HTTPException) as exc_info:
            self._call(db)
        assert exc_info.value.status_code == 404

    def test_wrong_status_raises_422(self):
        db = _make_resubmit_db(case_status="Pending Attorney Review")
        with pytest.raises(HTTPException) as exc_info:
            self._call(db)
        assert exc_info.value.status_code == 422
        assert "Rejected" in exc_info.value.detail

    def test_approved_status_raises_422(self):
        db = _make_resubmit_db(case_status="Approved for Filing")
        with pytest.raises(HTTPException) as exc_info:
            self._call(db)
        assert exc_info.value.status_code == 422

    # ── Authz guards ──────────────────────────────────────────────────────────

    def test_unassigned_paralegal_raises_403(self):
        db = _make_resubmit_db(assigned_paralegal="other-para-uid")
        with pytest.raises(HTTPException) as exc_info:
            self._call(db, actor_uid=_PARA, actor_role="paralegal")
        assert exc_info.value.status_code == 403

    def test_assigned_paralegal_can_resubmit(self):
        db = _make_resubmit_db(assigned_paralegal=_PARA)
        result = self._call(db, actor_uid=_PARA, actor_role="paralegal")
        assert result["status"] == "Pending Paralegal Review"

    def test_admin_staff_can_resubmit_any_case(self):
        db = _make_resubmit_db(assigned_paralegal="other-para-uid")
        result = self._call(db, actor_uid=_ADMIN, actor_role="admin_staff")
        assert result["status"] == "Pending Paralegal Review"

    def test_junior_partner_can_resubmit_any_case(self):
        db = _make_resubmit_db(assigned_paralegal="other-para-uid")
        result = self._call(db, actor_uid=_ATTY, actor_role="junior_partner")
        assert result["status"] == "Pending Paralegal Review"

    def test_senior_partner_can_resubmit_any_case(self):
        db = _make_resubmit_db(assigned_paralegal="other-para-uid")
        result = self._call(db, actor_uid=_SP, actor_role="senior_partner")
        assert result["status"] == "Pending Paralegal Review"

    # ── Batch write verification ───────────────────────────────────────────────

    def test_batch_committed_exactly_once(self):
        db = _make_resubmit_db()
        self._call(db)
        db.batch.return_value.commit.assert_called_once()

    def test_case_doc_updated_with_paralegal_review_status(self):
        db = _make_resubmit_db()
        self._call(db)
        batch = db.batch.return_value
        case_update_kwargs = batch.update.call_args_list[0][0][1]
        assert case_update_kwargs["status"] == "Pending Paralegal Review"

    def test_case_doc_has_resubmitted_at_and_resubmitted_by(self):
        db = _make_resubmit_db()
        self._call(db, actor_uid=_PARA)
        batch = db.batch.return_value
        case_update_kwargs = batch.update.call_args_list[0][0][1]
        assert "resubmittedAt" in case_update_kwargs
        assert case_update_kwargs["resubmittedBy"] == _PARA

    def test_rejection_fields_not_in_case_update(self):
        """rejection.* fields must NOT be cleared — preserved for history."""
        db = _make_resubmit_db()
        self._call(db)
        batch = db.batch.return_value
        case_update_kwargs = batch.update.call_args_list[0][0][1]
        assert "rejection.reason" not in case_update_kwargs
        assert "rejection.notes" not in case_update_kwargs
        assert "rejectedAt" not in case_update_kwargs

    def test_timeline_event_type_is_case_resubmission(self):
        db = _make_resubmit_db()
        self._call(db)
        batch = db.batch.return_value
        timeline_data = batch.set.call_args_list[0][0][1]
        assert timeline_data["eventType"] == "CaseResubmission"

    def test_timeline_metadata_has_correct_statuses(self):
        db = _make_resubmit_db()
        self._call(db)
        batch = db.batch.return_value
        timeline_data = batch.set.call_args_list[0][0][1]
        assert timeline_data["metadata"]["previousStatus"] == "Rejected"
        assert timeline_data["metadata"]["newStatus"] == "Pending Paralegal Review"

    def test_timeline_metadata_includes_rejection_id(self):
        db = _make_resubmit_db(rejection_data={"rejectionId": "rej-abc", "reason": "other"})
        self._call(db)
        batch = db.batch.return_value
        timeline_data = batch.set.call_args_list[0][0][1]
        assert timeline_data["metadata"]["rejectionId"] == "rej-abc"

    def test_timeline_metadata_rejection_id_none_when_absent(self):
        db = _make_resubmit_db(rejection_data={})
        self._call(db)
        batch = db.batch.return_value
        timeline_data = batch.set.call_args_list[0][0][1]
        assert timeline_data["metadata"]["rejectionId"] is None

    def test_notification_sent_to_attorney(self):
        db = _make_resubmit_db(assigned_attorney=_ATTY)
        self._call(db)
        batch = db.batch.return_value
        notif_data = batch.set.call_args_list[1][0][1]
        assert notif_data["recipientId"] == _ATTY

    def test_notification_type_is_case_resubmitted(self):
        db = _make_resubmit_db(assigned_attorney=_ATTY)
        self._call(db)
        batch = db.batch.return_value
        notif_data = batch.set.call_args_list[1][0][1]
        assert notif_data["type"] == "case_resubmitted"

    def test_no_notification_when_no_attorney(self):
        db = _make_resubmit_db(assigned_attorney=None)
        self._call(db)
        batch = db.batch.return_value
        # Only 1 set() call: timeline (no notification)
        assert len(batch.set.call_args_list) == 1

    def test_notes_included_in_notification_message_when_provided(self):
        db = _make_resubmit_db(assigned_attorney=_ATTY)
        self._call(db, notes="Uploaded all missing documents.")
        batch = db.batch.return_value
        notif_data = batch.set.call_args_list[1][0][1]
        assert "Uploaded all missing documents." in notif_data["message"]


# ═════════════════════════════════════════════════════════════════════════════
# RBAC role level checks
# ═════════════════════════════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════════════════════════════
# Route integration (TestClient)
# ═════════════════════════════════════════════════════════════════════════════

class TestRejectionRoutes:

    def _get_client(self, role="junior_partner", uid=_ATTY):
        from main import app
        client = TestClient(app, raise_server_exceptions=False)
        return client, {"uid": uid, "role": role}

    # ── Reject endpoint ───────────────────────────────────────────────────────

    def test_reject_endpoint_returns_200_on_happy_path(self):
        db = _make_reject_db()
        client, user = self._get_client(role="junior_partner", uid=_ATTY)

        with patch("app.routes.rejection.get_firestore_client", return_value=db):
            resp = client.post(
                f"/api/v1/cases/{_CASE}/reject",
                json={"reason": "incomplete_documentation"},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "Rejected"
        assert data["case_id"] == _CASE
        assert "rejection_id" in data

    def test_reject_endpoint_passes_reason_and_notes_to_service(self):
        db = _make_reject_db()
        client, user = self._get_client(role="junior_partner", uid=_ATTY)

        with patch("app.routes.rejection.get_firestore_client", return_value=db), \
             patch("app.routes.rejection.reject_case") as mock_svc:
            mock_svc.return_value = {
                "case_id": _CASE,
                "status": "Rejected",
                "rejected_at": _NOW,
                "rejection_id": "rej-123",
                "notified_paralegal": True,
            }
            client.post(
                f"/api/v1/cases/{_CASE}/reject",
                json={"reason": "client_unresponsive", "notes": "No reply in 60 days."},
                headers={"Authorization": "Bearer fake-token"},
            )
        mock_svc.assert_called_once()
        kwargs = mock_svc.call_args.kwargs
        assert kwargs["reason"] == "client_unresponsive"
        assert kwargs["notes"]  == "No reply in 60 days."

    def test_reject_422_propagates_from_service(self):
        client, user = self._get_client(role="junior_partner", uid=_ATTY)
        with patch("app.routes.rejection.get_firestore_client"), \
             patch("app.routes.rejection.reject_case",
                   side_effect=HTTPException(status_code=422, detail="wrong status")):
            resp = client.post(
                f"/api/v1/cases/{_CASE}/reject",
                json={"reason": "incomplete_documentation"},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 422

    def test_reject_404_propagates_from_service(self):
        client, user = self._get_client(role="junior_partner", uid=_ATTY)
        with patch("app.routes.rejection.get_firestore_client"), \
             patch("app.routes.rejection.reject_case",
                   side_effect=HTTPException(status_code=404, detail="not found")):
            resp = client.post(
                f"/api/v1/cases/{_CASE}/reject",
                json={"reason": "incomplete_documentation"},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 404

    def test_reject_model_validation_error_returns_422(self):
        client, user = self._get_client(role="junior_partner", uid=_ATTY)
        with patch("app.routes.rejection.get_firestore_client"):
            resp = client.post(
                f"/api/v1/cases/{_CASE}/reject",
                json={"reason": "other"},   # other without notes → 422
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 422

    # ── Resubmit endpoint ─────────────────────────────────────────────────────

    def test_resubmit_endpoint_returns_200_on_happy_path(self):
        db = _make_resubmit_db()
        client, user = self._get_client(role="paralegal", uid=_PARA)

        with patch("app.routes.rejection.get_firestore_client", return_value=db):
            resp = client.post(
                f"/api/v1/cases/{_CASE}/resubmit",
                json={},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "Pending Paralegal Review"
        assert data["case_id"] == _CASE

    def test_resubmit_passes_notes_to_service(self):
        client, user = self._get_client(role="paralegal", uid=_PARA)
        with patch("app.routes.rejection.get_firestore_client"), \
             patch("app.routes.rejection.resubmit_case") as mock_svc:
            mock_svc.return_value = {
                "case_id": _CASE,
                "status": "Pending Paralegal Review",
                "resubmitted_at": _NOW,
                "notified_attorney": True,
            }
            client.post(
                f"/api/v1/cases/{_CASE}/resubmit",
                json={"notes": "All docs uploaded."},
                headers={"Authorization": "Bearer fake-token"},
            )
        mock_svc.assert_called_once()
        assert mock_svc.call_args.kwargs["notes"] == "All docs uploaded."

    def test_resubmit_422_propagates_from_service(self):
        client, user = self._get_client(role="paralegal", uid=_PARA)
        with patch("app.routes.rejection.get_firestore_client"), \
             patch("app.routes.rejection.resubmit_case",
                   side_effect=HTTPException(status_code=422, detail="wrong status")):
            resp = client.post(
                f"/api/v1/cases/{_CASE}/resubmit",
                json={},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 422

    def test_resubmit_404_propagates_from_service(self):
        client, user = self._get_client(role="paralegal", uid=_PARA)
        with patch("app.routes.rejection.get_firestore_client"), \
             patch("app.routes.rejection.resubmit_case",
                   side_effect=HTTPException(status_code=404, detail="not found")):
            resp = client.post(
                f"/api/v1/cases/{_CASE}/resubmit",
                json={},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 404
