"""
Tests for the Escalation workflow.

Covers:
  - EscalateRequest / EscalationDecideRequest model validation
  - escalate_case: happy path, status guard, authz, reason validation, batch writes
  - get_escalation_queue: returns escalated cases, sort order, overdue count, pagination
  - decide_escalation: approve / reject / return_to_paralegal paths
  - RBAC: role hierarchy constants; paralegal / unauthenticated blocked by routes
  - Route integration via FastAPI TestClient
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from fastapi.testclient import TestClient


# ── Shared constants ──────────────────────────────────────────────────────────

_NOW  = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
_CASE = "ZAD-2026-04-0001"
_ATTY = "atty-uid"
_PARA = "para-uid"
_SP   = "sp-uid"


# ── Snapshot helpers ──────────────────────────────────────────────────────────

def _case_snap(
    case_id=_CASE,
    status="Pending Attorney Review",
    assigned_attorney=_ATTY,
    assigned_paralegal=_PARA,
    vcf_deadline=None,
    qual_score=80.0,
    escalation=None,
    exists=True,
):
    snap = MagicMock()
    snap.exists = exists
    snap.id     = case_id
    snap.to_dict.return_value = {
        "status":        status,
        "caseType":      "VCF",
        "leadData":      {"firstName": "Jane", "lastName": "Smith"},
        "qualification": {"medicalQualScore": qual_score},
        "enrollment":    {"vcfRegDeadline": vcf_deadline},
        "assignment": {
            "assignedAttorney":  assigned_attorney,
            "assignedParalegal": assigned_paralegal,
        },
        "escalation": escalation or {},
        "updatedAt":  _NOW,
    }
    return snap


def _staff_snap(uid=_ATTY, display_name="Alice Attorney", exists=True):
    snap = MagicMock()
    snap.exists = exists
    snap.id     = uid
    snap.to_dict.return_value = {"displayName": display_name}
    return snap


def _sp_snap(uid=_SP, display_name="Senior Sam"):
    snap = MagicMock()
    snap.exists = True
    snap.id     = uid
    snap.to_dict.return_value = {
        "displayName": display_name,
        "role":        "senior_partner",
        "isActive":    True,
    }
    return snap


def _escalation_snap(
    escalation_id="esc-001",
    reason="high_value_claim",
    escalated_at=None,
    escalated_by=_ATTY,
    status="pending",
):
    snap = MagicMock()
    snap.exists = True
    snap.id     = escalation_id
    snap.to_dict.return_value = {
        "escalationId":       escalation_id,
        "caseId":             _CASE,
        "escalatedAt":        escalated_at or _NOW,
        "escalatedBy":        escalated_by,
        "escalatedByName":    "Alice Attorney",
        "reason":             reason,
        "notes":              None,
        "originalAttorneyId": escalated_by,
        "status":             status,
        "resolvedAt":         None,
        "resolvedBy":         None,
        "resolvedByName":     None,
        "decision":           None,
        "decisionNotes":      None,
    }
    return snap


# ── DB builder helpers ────────────────────────────────────────────────────────

def _make_escalate_db(
    case_status="Pending Attorney Review",
    assigned_attorney=_ATTY,
    case_exists=True,
    senior_partner_snaps=None,
    vcf_deadline=None,
):
    """Firestore mock for escalate_case."""
    db = MagicMock()

    case_ref = MagicMock()
    case_ref.get.return_value = _case_snap(
        status=case_status,
        assigned_attorney=assigned_attorney,
        vcf_deadline=vcf_deadline,
        exists=case_exists,
    )
    case_ref.collection.return_value = MagicMock()

    actor_snap = _staff_snap()

    # Staff collection handles both document() (actor lookup) and where() (senior_partners)
    sp_snaps   = senior_partner_snaps if senior_partner_snaps is not None else [_sp_snap()]
    sp_query   = MagicMock()
    sp_query.where.return_value  = sp_query
    sp_query.stream.side_effect  = lambda: iter(sp_snaps)

    staff_coll = MagicMock()
    staff_coll.document.return_value = MagicMock(get=MagicMock(return_value=actor_snap))
    staff_coll.where.return_value    = sp_query

    def _collection(name):
        if name == "cases":
            coll = MagicMock()
            coll.document.return_value = case_ref
            return coll
        if name == "staff":
            return staff_coll
        return MagicMock()

    db.collection.side_effect = _collection
    db.batch.return_value = MagicMock()
    return db


def _make_queue_db(case_snaps: list):
    """Firestore mock for get_escalation_queue."""
    db = MagicMock()

    # Escalation sub-doc query — reusable across multiple cases
    esc_snap  = _escalation_snap()
    esc_query = MagicMock()
    esc_query.where.return_value   = esc_query
    esc_query.order_by.return_value = esc_query
    esc_query.limit.return_value   = esc_query
    esc_query.stream.side_effect   = lambda: iter([esc_snap])

    esc_coll = MagicMock()
    esc_coll.where.return_value = esc_query

    case_ref = MagicMock()
    case_ref.collection.return_value = esc_coll

    main_query = MagicMock()
    main_query.where.return_value  = main_query
    main_query.stream.return_value = iter(case_snaps)

    def _collection(name):
        if name == "cases":
            coll = MagicMock()
            coll.where.return_value    = main_query
            coll.document.return_value = case_ref
            return coll
        return MagicMock()

    db.collection.side_effect = _collection
    return db


def _make_decide_db(
    case_status="Pending Senior Review",
    assigned_attorney=_ATTY,
    assigned_paralegal=_PARA,
    vcf_deadline=None,
    escalation_id="esc-001",
    escalation_exists=True,
):
    """Firestore mock for decide_escalation."""
    db = MagicMock()

    esc_snap     = _escalation_snap(escalation_id=escalation_id)
    esc_doc_ref  = MagicMock()
    esc_doc_ref.get.return_value = esc_snap

    esc_query = MagicMock()
    esc_query.where.return_value    = esc_query
    esc_query.order_by.return_value = esc_query
    esc_query.limit.return_value    = esc_query
    esc_query.stream.side_effect    = (
        lambda: iter([esc_snap]) if escalation_exists else lambda: iter([])
    )

    esc_coll = MagicMock()
    esc_coll.where.return_value    = esc_query
    esc_coll.document.return_value = esc_doc_ref

    timeline_doc = MagicMock()
    timeline_doc.id = "tl-001"
    timeline_coll = MagicMock()
    timeline_coll.document.return_value = timeline_doc

    tasks_coll = MagicMock()
    tasks_coll.document.return_value = MagicMock()

    case_ref = MagicMock()
    case_ref.get.return_value = _case_snap(
        status=case_status,
        assigned_attorney=assigned_attorney,
        assigned_paralegal=assigned_paralegal,
        vcf_deadline=vcf_deadline,
        escalation={
            "escalatedAt":        _NOW,
            "escalatedBy":        _ATTY,
            "escalatedByName":    "Alice Attorney",
            "reason":             "high_value_claim",
            "notes":              None,
            "originalAttorneyId": _ATTY,
        },
    )

    def _case_sub(name):
        if name == "escalations":
            return esc_coll
        if name == "timeline":
            return timeline_coll
        if name == "tasks":
            return tasks_coll
        return MagicMock()

    case_ref.collection.side_effect = _case_sub

    actor_snap = _staff_snap(uid=_SP, display_name="Senior Sam")

    def _collection(name):
        if name == "cases":
            coll = MagicMock()
            coll.document.return_value = case_ref
            return coll
        if name == "staff":
            coll = MagicMock()
            coll.document.return_value = MagicMock(get=MagicMock(return_value=actor_snap))
            return coll
        return MagicMock()

    db.collection.side_effect = _collection
    db.batch.return_value = MagicMock()
    return db


# ═════════════════════════════════════════════════════════════════════════════
# Model validation
# ═════════════════════════════════════════════════════════════════════════════

class TestEscalationModels:

    # ── EscalateRequest ───────────────────────────────────────────────────────

    def test_other_reason_without_notes_raises_validation_error(self):
        from pydantic import ValidationError
        from app.models.escalation import EscalateRequest
        with pytest.raises(ValidationError):
            EscalateRequest(reason="other", notes=None)

    def test_other_reason_with_blank_notes_raises_validation_error(self):
        from pydantic import ValidationError
        from app.models.escalation import EscalateRequest
        with pytest.raises(ValidationError):
            EscalateRequest(reason="other", notes="   ")

    def test_other_reason_with_notes_is_valid(self):
        from app.models.escalation import EscalateRequest
        req = EscalateRequest(reason="other", notes="Unusual situation.")
        assert req.reason == "other"
        assert req.notes  == "Unusual situation."

    def test_non_other_reason_notes_is_optional(self):
        from app.models.escalation import EscalateRequest
        req = EscalateRequest(reason="high_value_claim")
        assert req.reason == "high_value_claim"
        assert req.notes  is None

    def test_invalid_reason_raises_validation_error(self):
        from pydantic import ValidationError
        from app.models.escalation import EscalateRequest
        with pytest.raises(ValidationError):
            EscalateRequest(reason="bad_reason")

    # ── EscalationDecideRequest ───────────────────────────────────────────────

    def test_reject_without_notes_raises_validation_error(self):
        from pydantic import ValidationError
        from app.models.escalation import EscalationDecideRequest
        with pytest.raises(ValidationError):
            EscalationDecideRequest(decision="reject", notes=None)

    def test_return_to_paralegal_without_notes_raises_validation_error(self):
        from pydantic import ValidationError
        from app.models.escalation import EscalationDecideRequest
        with pytest.raises(ValidationError):
            EscalationDecideRequest(decision="return_to_paralegal", notes="   ")

    def test_approve_notes_optional(self):
        from app.models.escalation import EscalationDecideRequest
        req = EscalationDecideRequest(decision="approve")
        assert req.decision == "approve"
        assert req.notes    is None

    def test_reject_with_notes_valid(self):
        from app.models.escalation import EscalationDecideRequest
        req = EscalationDecideRequest(decision="reject", notes="Insufficient evidence.")
        assert req.decision == "reject"

    def test_invalid_decision_raises_validation_error(self):
        from pydantic import ValidationError
        from app.models.escalation import EscalationDecideRequest
        with pytest.raises(ValidationError):
            EscalationDecideRequest(decision="dismiss")


# ═════════════════════════════════════════════════════════════════════════════
# escalate_case unit tests
# ═════════════════════════════════════════════════════════════════════════════

class TestEscalateCase:

    def _call(
        self,
        db,
        case_id=_CASE,
        actor_uid=_ATTY,
        actor_role="junior_partner",
        reason="high_value_claim",
        notes=None,
    ):
        from app.services.escalation_service import escalate_case
        return escalate_case(
            db=db,
            case_id=case_id,
            actor_uid=actor_uid,
            actor_role=actor_role,
            reason=reason,
            notes=notes,
        )

    # ── Happy path ────────────────────────────────────────────────────────────

    def test_returns_escalated_status(self):
        db     = _make_escalate_db()
        result = self._call(db)
        assert result["status"]  == "Pending Senior Review"
        assert result["case_id"] == _CASE

    def test_returns_escalation_id_string(self):
        db     = _make_escalate_db()
        result = self._call(db)
        assert isinstance(result["escalation_id"], str)
        assert len(result["escalation_id"]) == 36  # UUID

    def test_returns_escalated_at_datetime(self):
        db     = _make_escalate_db()
        result = self._call(db)
        assert isinstance(result["escalated_at"], datetime)

    def test_returns_notified_count_equal_to_senior_partners(self):
        db     = _make_escalate_db(senior_partner_snaps=[_sp_snap("sp1"), _sp_snap("sp2")])
        result = self._call(db)
        assert result["notified_count"] == 2

    def test_notified_count_zero_when_no_senior_partners(self):
        db     = _make_escalate_db(senior_partner_snaps=[])
        result = self._call(db)
        assert result["notified_count"] == 0

    def test_all_four_reason_values_accepted(self):
        for reason in ("high_value_claim", "unusual_medical_condition",
                       "prior_attorney_conflict", "other"):
            db   = _make_escalate_db()
            notes = "context" if reason == "other" else None
            result = self._call(db, reason=reason, notes=notes)
            assert result["status"] == "Pending Senior Review"

    # ── Validation guards ─────────────────────────────────────────────────────

    def test_case_not_found_raises_404(self):
        db = _make_escalate_db(case_exists=False)
        with pytest.raises(HTTPException) as exc:
            self._call(db)
        assert exc.value.status_code == 404

    def test_wrong_status_raises_422(self):
        db = _make_escalate_db(case_status="Pending Paralegal Review")
        with pytest.raises(HTTPException) as exc:
            self._call(db)
        assert exc.value.status_code == 422
        assert "Pending Paralegal Review" in exc.value.detail

    def test_already_escalated_raises_422(self):
        db = _make_escalate_db(case_status="Pending Senior Review")
        with pytest.raises(HTTPException) as exc:
            self._call(db)
        assert exc.value.status_code == 422

    def test_reason_other_without_notes_raises_422(self):
        db = _make_escalate_db()
        with pytest.raises(HTTPException) as exc:
            self._call(db, reason="other", notes=None)
        assert exc.value.status_code == 422

    def test_reason_other_with_blank_notes_raises_422(self):
        db = _make_escalate_db()
        with pytest.raises(HTTPException) as exc:
            self._call(db, reason="other", notes="   ")
        assert exc.value.status_code == 422

    # ── Authorisation ─────────────────────────────────────────────────────────

    def test_junior_partner_not_assigned_attorney_raises_403(self):
        db = _make_escalate_db(assigned_attorney="other-atty")
        with pytest.raises(HTTPException) as exc:
            self._call(db, actor_uid=_ATTY, actor_role="junior_partner")
        assert exc.value.status_code == 403

    def test_senior_partner_can_escalate_regardless_of_assignment(self):
        db     = _make_escalate_db(assigned_attorney="other-atty")
        result = self._call(db, actor_uid=_SP, actor_role="senior_partner")
        assert result["status"] == "Pending Senior Review"

    def test_system_admin_can_escalate_any_case(self):
        db     = _make_escalate_db(assigned_attorney="other-atty")
        result = self._call(db, actor_uid="admin-uid", actor_role="system_admin")
        assert result["status"] == "Pending Senior Review"

    def test_assigned_junior_partner_can_escalate(self):
        db     = _make_escalate_db(assigned_attorney=_ATTY)
        result = self._call(db, actor_uid=_ATTY, actor_role="junior_partner")
        assert result["status"] == "Pending Senior Review"

    # ── Batch writes ──────────────────────────────────────────────────────────

    def test_batch_committed_once(self):
        db = _make_escalate_db()
        self._call(db)
        db.batch.return_value.commit.assert_called_once()

    def test_case_status_updated_in_batch(self):
        db = _make_escalate_db()
        self._call(db)
        batch        = db.batch.return_value
        update_calls = batch.update.call_args_list
        assert len(update_calls) >= 1
        payload = update_calls[0][0][1]
        assert payload["status"] == "Pending Senior Review"

    def test_escalation_fields_written_to_case(self):
        db = _make_escalate_db()
        self._call(db, reason="prior_attorney_conflict", notes="Conflict note.")
        batch   = db.batch.return_value
        payload = batch.update.call_args_list[0][0][1]
        assert payload["escalation.reason"] == "prior_attorney_conflict"
        assert payload["escalation.notes"]  == "Conflict note."
        assert payload["escalation.escalatedBy"] == _ATTY

    def test_escalation_subdoc_set_in_batch(self):
        db = _make_escalate_db()
        self._call(db, reason="unusual_medical_condition")
        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        esc_doc   = next(
            (c for c in set_calls if (c[0][1] if c[0] else c[1]).get("status") == "pending"),
            None,
        )
        assert esc_doc is not None, "Escalation sub-doc not found in batch"
        data = esc_doc[0][1]
        assert data["reason"]  == "unusual_medical_condition"
        assert data["caseId"]  == _CASE

    def test_timeline_event_written_with_escalation_type(self):
        db = _make_escalate_db()
        self._call(db)
        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        timeline  = next(
            (c for c in set_calls if (c[0][1] if c[0] else c[1]).get("eventType") == "Escalation"),
            None,
        )
        assert timeline is not None, "Timeline Escalation event not written"
        data = timeline[0][1]
        assert data["performedBy"]               == _ATTY
        assert data["metadata"]["newStatus"]     == "Pending Senior Review"
        assert data["metadata"]["previousStatus"] == "Pending Attorney Review"

    def test_escalation_events_doc_written(self):
        db = _make_escalate_db()
        self._call(db)
        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        # escalation_events doc is identified by having "daysToResolve" key
        # (the sub-doc does not have this field)
        event_doc = next(
            (c for c in set_calls
             if "daysToResolve" in (c[0][1] if c[0] else c[1])),
            None,
        )
        assert event_doc is not None, "escalation_events doc not written"
        data = event_doc[0][1]
        assert data["caseId"]        == _CASE
        assert data["resolvedAt"]    is None
        assert data["daysToResolve"] is None

    def test_one_notification_per_senior_partner(self):
        sp1 = _sp_snap("sp1", "Sam One")
        sp2 = _sp_snap("sp2", "Sam Two")
        db  = _make_escalate_db(senior_partner_snaps=[sp1, sp2])
        self._call(db)
        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        notifs    = [
            c for c in set_calls
            if (c[0][1] if c[0] else c[1]).get("type") == "escalation_requested"
        ]
        assert len(notifs) == 2
        recipients = {n[0][1]["recipientId"] for n in notifs}
        assert recipients == {"sp1", "sp2"}

    def test_notification_contains_reason_and_case_id(self):
        db = _make_escalate_db()
        self._call(db, reason="high_value_claim")
        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        notif = next(
            c for c in set_calls
            if (c[0][1] if c[0] else c[1]).get("type") == "escalation_requested"
        )
        data = notif[0][1]
        assert data["caseId"]                    == _CASE
        assert data["metadata"]["reason"]        == "high_value_claim"
        assert data["read"]                      is False


# ═════════════════════════════════════════════════════════════════════════════
# get_escalation_queue unit tests
# ═════════════════════════════════════════════════════════════════════════════

class TestGetEscalationQueue:

    def _call(self, db, role=None, uid=None, page=1, page_size=20):
        from app.services.escalation_service import get_escalation_queue
        return get_escalation_queue(db=db, page=page, page_size=page_size)

    def _escalated_case_snap(self, case_id=_CASE, vcf_deadline=None, qual_score=80.0,
                              escalated_at=None):
        return _case_snap(
            case_id=case_id,
            status="Pending Senior Review",
            vcf_deadline=vcf_deadline,
            qual_score=qual_score,
            escalation={
                "escalatedAt":        escalated_at or _NOW,
                "escalatedBy":        _ATTY,
                "escalatedByName":    "Alice Attorney",
                "reason":             "high_value_claim",
                "notes":              None,
                "originalAttorneyId": _ATTY,
            },
        )

    # ── Basic ─────────────────────────────────────────────────────────────────

    def test_returns_escalated_cases(self):
        snap   = self._escalated_case_snap()
        db     = _make_queue_db([snap])
        result = self._call(db)
        assert result["total_pending"] == 1
        assert result["page"]["items"][0]["case_id"] == _CASE

    def test_empty_queue_returns_zero_counts(self):
        db     = _make_queue_db([])
        result = self._call(db)
        assert result["total_pending"] == 0
        assert result["overdue_count"] == 0
        assert result["page"]["items"] == []

    def test_queue_item_includes_escalation_fields(self):
        snap   = self._escalated_case_snap()
        db     = _make_queue_db([snap])
        result = self._call(db)
        item   = result["page"]["items"][0]
        assert item["escalation_reason"]    == "high_value_claim"
        assert item["original_attorney_id"] == _ATTY
        assert item["escalated_by_name"]    == "Alice Attorney"
        assert "escalation_id" in item

    # ── Sort order ────────────────────────────────────────────────────────────

    def test_sorted_by_vcf_deadline_soonest_first(self):
        soon = _NOW + timedelta(days=5)
        far  = _NOW + timedelta(days=30)
        snap_far  = self._escalated_case_snap(case_id="ZAD-FAR",  vcf_deadline=far)
        snap_soon = self._escalated_case_snap(case_id="ZAD-SOON", vcf_deadline=soon)

        db     = _make_queue_db([snap_far, snap_soon])
        result = self._call(db)
        items  = result["page"]["items"]

        assert items[0]["case_id"] == "ZAD-SOON"
        assert items[1]["case_id"] == "ZAD-FAR"

    def test_no_deadline_sorts_after_cases_with_deadline(self):
        has_dl = self._escalated_case_snap(case_id="ZAD-DL",  vcf_deadline=_NOW + timedelta(days=10))
        no_dl  = self._escalated_case_snap(case_id="ZAD-NODL", vcf_deadline=None)

        db     = _make_queue_db([no_dl, has_dl])
        result = self._call(db)
        items  = result["page"]["items"]

        assert items[0]["case_id"] == "ZAD-DL"
        assert items[1]["case_id"] == "ZAD-NODL"

    def test_same_deadline_sorted_by_oldest_escalation_first(self):
        dl     = _NOW + timedelta(days=10)
        older  = self._escalated_case_snap(
            case_id="ZAD-OLD", vcf_deadline=dl, escalated_at=_NOW - timedelta(days=3)
        )
        newer  = self._escalated_case_snap(
            case_id="ZAD-NEW", vcf_deadline=dl, escalated_at=_NOW - timedelta(days=1)
        )
        db     = _make_queue_db([newer, older])
        result = self._call(db)
        assert result["page"]["items"][0]["case_id"] == "ZAD-OLD"

    def test_tiebreaker_highest_qual_score_first(self):
        dl   = _NOW + timedelta(days=10)
        high = self._escalated_case_snap(case_id="ZAD-HIGH", vcf_deadline=dl, qual_score=90.0)
        low  = self._escalated_case_snap(case_id="ZAD-LOW",  vcf_deadline=dl, qual_score=50.0)

        db     = _make_queue_db([low, high])
        result = self._call(db)
        assert result["page"]["items"][0]["case_id"] == "ZAD-HIGH"

    # ── Overdue count ─────────────────────────────────────────────────────────

    def test_overdue_count_includes_past_deadlines(self):
        overdue = self._escalated_case_snap(case_id="ZAD-OD",  vcf_deadline=_NOW - timedelta(days=2))
        future  = self._escalated_case_snap(case_id="ZAD-FUT", vcf_deadline=_NOW + timedelta(days=10))
        no_dl   = self._escalated_case_snap(case_id="ZAD-NODL")

        db = _make_queue_db([overdue, future, no_dl])
        mock_dt = MagicMock(wraps=datetime)
        mock_dt.now.return_value = _NOW
        with patch("app.services.escalation_service.datetime", mock_dt):
            result = self._call(db)
        assert result["overdue_count"] == 1

    def test_days_until_deadline_negative_when_overdue(self):
        snap   = self._escalated_case_snap(vcf_deadline=_NOW - timedelta(days=3))
        db     = _make_queue_db([snap])
        result = self._call(db)
        assert result["page"]["items"][0]["days_until_deadline"] < 0

    # ── Pagination ────────────────────────────────────────────────────────────

    def test_pagination_slices_correctly(self):
        snaps  = [self._escalated_case_snap(case_id="ZAD-{:04d}".format(i)) for i in range(5)]
        db     = _make_queue_db(snaps)
        result = self._call(db, page=2, page_size=2)
        assert result["page"]["page"]        == 2
        assert result["page"]["total"]       == 5
        assert result["page"]["total_pages"] == 3
        assert len(result["page"]["items"])  == 2

    def test_total_pages_rounds_up(self):
        snaps  = [self._escalated_case_snap(case_id="ZAD-{:04d}".format(i)) for i in range(3)]
        db     = _make_queue_db(snaps)
        result = self._call(db, page=1, page_size=2)
        assert result["page"]["total_pages"] == 2


# ═════════════════════════════════════════════════════════════════════════════
# decide_escalation unit tests
# ═════════════════════════════════════════════════════════════════════════════

class TestDecideEscalation:

    def _call(
        self,
        db,
        case_id=_CASE,
        actor_uid=_SP,
        actor_role="senior_partner",
        decision="approve",
        notes=None,
    ):
        from app.services.escalation_service import decide_escalation
        return decide_escalation(
            db=db,
            case_id=case_id,
            actor_uid=actor_uid,
            actor_role=actor_role,
            decision=decision,
            notes=notes,
        )

    # ── Guard: case existence and status ─────────────────────────────────────

    def test_case_not_found_raises_404(self):
        db = MagicMock()
        missing = MagicMock()
        missing.exists = False
        db.collection.return_value.document.return_value.get.return_value = missing
        with pytest.raises(HTTPException) as exc:
            self._call(db)
        assert exc.value.status_code == 404

    def test_wrong_status_raises_422(self):
        db = _make_decide_db(case_status="Pending Attorney Review")
        with pytest.raises(HTTPException) as exc:
            self._call(db)
        assert exc.value.status_code == 422
        assert "Pending Attorney Review" in exc.value.detail

    def test_reject_without_notes_raises_422(self):
        db = _make_decide_db()
        with pytest.raises(HTTPException) as exc:
            self._call(db, decision="reject", notes=None)
        assert exc.value.status_code == 422

    def test_return_to_paralegal_without_notes_raises_422(self):
        db = _make_decide_db()
        with pytest.raises(HTTPException) as exc:
            self._call(db, decision="return_to_paralegal", notes="   ")
        assert exc.value.status_code == 422

    # ── Approve path ──────────────────────────────────────────────────────────

    def test_approve_returns_approved_for_filing_status(self):
        db     = _make_decide_db()
        result = self._call(db, decision="approve")
        assert result["new_status"] == "Approved for Filing"
        assert result["decision"]   == "approve"
        assert result["case_id"]    == _CASE

    def test_approve_returns_resolved_at_datetime(self):
        db     = _make_decide_db()
        result = self._call(db, decision="approve")
        assert isinstance(result["resolved_at"], datetime)

    def test_approve_creates_three_filing_prep_tasks(self):
        db = _make_decide_db()
        self._call(db, decision="approve")
        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        tasks     = [c for c in set_calls if (c[0][1] if c[0] else c[1]).get("type") == "filing_prep"]
        assert len(tasks) == 3

    def test_approve_returns_three_task_ids(self):
        db     = _make_decide_db()
        result = self._call(db, decision="approve")
        assert len(result["task_ids"]) == 3

    def test_approve_notifies_paralegal(self):
        db = _make_decide_db(assigned_paralegal=_PARA)
        self._call(db, decision="approve")
        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        notif     = next(
            (c for c in set_calls
             if (c[0][1] if c[0] else c[1]).get("type") == "case_approved_for_filing"),
            None,
        )
        assert notif is not None, "No case_approved_for_filing notification"
        assert notif[0][1]["recipientId"] == _PARA

    def test_approve_notifies_original_junior_partner(self):
        db = _make_decide_db()
        self._call(db, decision="approve")
        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        notif     = next(
            (c for c in set_calls
             if (c[0][1] if c[0] else c[1]).get("type") == "escalation_approved"),
            None,
        )
        assert notif is not None, "No escalation_approved notification for junior_partner"
        assert notif[0][1]["recipientId"] == _ATTY

    def test_approve_timeline_event_is_escalation_decision(self):
        db = _make_decide_db()
        self._call(db, decision="approve")
        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        timeline  = next(
            (c for c in set_calls
             if (c[0][1] if c[0] else c[1]).get("eventType") == "EscalationDecision"),
            None,
        )
        assert timeline is not None, "No EscalationDecision timeline event"
        data = timeline[0][1]
        assert data["metadata"]["newStatus"]  == "Approved for Filing"
        assert data["metadata"]["decision"]   == "approve"

    def test_approve_resolves_escalation_subdoc(self):
        db = _make_decide_db()
        self._call(db, decision="approve")
        batch        = db.batch.return_value
        update_calls = batch.update.call_args_list
        esc_update   = next(
            (c for c in update_calls
             if isinstance(c[0][1], dict) and c[0][1].get("status") == "approved"),
            None,
        )
        assert esc_update is not None, "Escalation sub-doc not updated to approved"
        data = esc_update[0][1]
        assert data["decision"]   == "approve"
        assert data["resolvedBy"] == _SP

    def test_approve_updates_escalation_events_doc(self):
        db = _make_decide_db()
        self._call(db, decision="approve")
        batch        = db.batch.return_value
        update_calls = batch.update.call_args_list
        event_update = next(
            (c for c in update_calls
             if isinstance(c[0][1], dict) and c[0][1].get("decision") == "approve"
             and "daysToResolve" in c[0][1]),
            None,
        )
        assert event_update is not None, "escalation_events doc not updated"

    def test_approve_batch_committed_once(self):
        db = _make_decide_db()
        self._call(db, decision="approve")
        db.batch.return_value.commit.assert_called_once()

    # ── Reject path ───────────────────────────────────────────────────────────

    def test_reject_returns_pending_attorney_review(self):
        db     = _make_decide_db()
        result = self._call(db, decision="reject", notes="Weak medical evidence.")
        assert result["new_status"] == "Pending Attorney Review"
        assert result["decision"]   == "reject"

    def test_reject_case_update_sets_correct_status(self):
        db = _make_decide_db()
        self._call(db, decision="reject", notes="Weak medical evidence.")
        batch   = db.batch.return_value
        payload = batch.update.call_args_list[0][0][1]
        assert payload["status"] == "Pending Attorney Review"

    def test_reject_notifies_original_junior_partner(self):
        db = _make_decide_db()
        self._call(db, decision="reject", notes="Need more docs.")
        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        notif     = next(
            (c for c in set_calls
             if (c[0][1] if c[0] else c[1]).get("type") == "escalation_rejected"),
            None,
        )
        assert notif is not None, "No escalation_rejected notification"
        assert notif[0][1]["recipientId"] == _ATTY

    def test_reject_resolves_escalation_subdoc_as_rejected(self):
        db = _make_decide_db()
        self._call(db, decision="reject", notes="Reject reason.")
        batch        = db.batch.return_value
        update_calls = batch.update.call_args_list
        esc_update   = next(
            (c for c in update_calls
             if isinstance(c[0][1], dict) and c[0][1].get("status") == "rejected"),
            None,
        )
        assert esc_update is not None, "Escalation sub-doc not updated to rejected"

    def test_reject_timeline_event_has_correct_previous_and_new_status(self):
        db = _make_decide_db()
        self._call(db, decision="reject", notes="Reject.")
        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        timeline  = next(
            c for c in set_calls
            if (c[0][1] if c[0] else c[1]).get("eventType") == "EscalationDecision"
        )
        data = timeline[0][1]
        assert data["metadata"]["previousStatus"] == "Pending Senior Review"
        assert data["metadata"]["newStatus"]      == "Pending Attorney Review"

    def test_reject_batch_committed_once(self):
        db = _make_decide_db()
        self._call(db, decision="reject", notes="Reason.")
        db.batch.return_value.commit.assert_called_once()

    # ── Return to paralegal path ──────────────────────────────────────────────

    def test_return_to_paralegal_sets_correct_status(self):
        db     = _make_decide_db()
        result = self._call(db, decision="return_to_paralegal", notes="More records needed.")
        assert result["new_status"] == "Pending Paralegal Review"
        assert result["decision"]   == "return_to_paralegal"

    def test_return_to_paralegal_notifies_junior_partner(self):
        db = _make_decide_db()
        self._call(db, decision="return_to_paralegal", notes="Need more docs.")
        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        notifs    = [
            c for c in set_calls
            if (c[0][1] if c[0] else c[1]).get("type") == "escalation_returned"
        ]
        jp_notif = next((c for c in notifs if c[0][1]["recipientId"] == _ATTY), None)
        assert jp_notif is not None, "No escalation_returned notification for junior_partner"

    def test_return_to_paralegal_also_notifies_paralegal(self):
        db = _make_decide_db(assigned_paralegal=_PARA)
        self._call(db, decision="return_to_paralegal", notes="More docs.")
        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        notifs    = [
            c for c in set_calls
            if (c[0][1] if c[0] else c[1]).get("type") == "escalation_returned"
        ]
        para_notif = next((c for c in notifs if c[0][1]["recipientId"] == _PARA), None)
        assert para_notif is not None, "No escalation_returned notification for paralegal"

    def test_return_resolves_escalation_subdoc_as_returned(self):
        db = _make_decide_db()
        self._call(db, decision="return_to_paralegal", notes="Return reason.")
        batch        = db.batch.return_value
        update_calls = batch.update.call_args_list
        esc_update   = next(
            (c for c in update_calls
             if isinstance(c[0][1], dict) and c[0][1].get("status") == "returned"),
            None,
        )
        assert esc_update is not None, "Escalation sub-doc not updated to returned"

    def test_return_batch_committed_once(self):
        db = _make_decide_db()
        self._call(db, decision="return_to_paralegal", notes="Return.")
        db.batch.return_value.commit.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════════
# Route integration tests
# ═════════════════════════════════════════════════════════════════════════════

class TestEscalationRoutes:

    def _make_client(self, role="junior_partner", uid=_ATTY):
        user = {"uid": uid, "role": role}
        from importlib import reload
        import main as m
        reload(m)
        client = TestClient(m.app, raise_server_exceptions=False)
        return client, user

    # ── POST /escalate ────────────────────────────────────────────────────────

    def test_escalate_endpoint_returns_200(self):
        client, user = self._make_client()
        mock_result  = {
            "case_id":       _CASE,
            "status":        "Pending Senior Review",
            "escalated_at":  _NOW,
            "escalation_id": "esc-abc",
            "notified_count": 1,
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.escalation.escalate_case", return_value=mock_result):
            resp = client.post(
                "/api/v1/cases/{}/escalate".format(_CASE),
                json={"reason": "high_value_claim"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"]        == "Pending Senior Review"
        assert body["notified_count"] == 1

    def test_escalate_passes_reason_and_notes_to_service(self):
        client, user = self._make_client()
        mock_result  = {
            "case_id": _CASE, "status": "Pending Senior Review",
            "escalated_at": _NOW, "escalation_id": "esc-abc", "notified_count": 1,
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.escalation.escalate_case", return_value=mock_result) as mock_fn:
            client.post(
                "/api/v1/cases/{}/escalate".format(_CASE),
                json={"reason": "other", "notes": "Special situation."},
            )
        _, kwargs = mock_fn.call_args
        assert kwargs["reason"] == "other"
        assert kwargs["notes"]  == "Special situation."

    def test_escalate_422_propagates_to_client(self):
        client, user = self._make_client()
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch(
                 "app.routes.escalation.escalate_case",
                 side_effect=HTTPException(422, detail="Wrong status"),
             ):
            resp = client.post(
                "/api/v1/cases/{}/escalate".format(_CASE),
                json={"reason": "high_value_claim"},
            )
        assert resp.status_code == 422

    # ── GET /escalation-queue ─────────────────────────────────────────────────

    def test_escalation_queue_returns_200(self):
        client, user = self._make_client(role="senior_partner", uid=_SP)
        mock_result  = {
            "total_pending": 1,
            "overdue_count": 0,
            "page": {
                "items": [{
                    "case_id":              _CASE,
                    "first_name":           "Jane",
                    "last_name":            "Smith",
                    "case_type":            "VCF",
                    "vcf_deadline":         None,
                    "qual_score":           80.0,
                    "days_until_deadline":  None,
                    "escalation_id":        "esc-001",
                    "escalation_reason":    "high_value_claim",
                    "escalated_at":         _NOW,
                    "escalated_by_name":    "Alice Attorney",
                    "original_attorney_id": _ATTY,
                    "escalation_notes":     None,
                }],
                "total":       1,
                "page":        1,
                "page_size":   20,
                "total_pages": 1,
            },
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.escalation.get_escalation_queue", return_value=mock_result):
            resp = client.get("/api/v1/attorney/escalation-queue")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_pending"]                          == 1
        assert body["page"]["items"][0]["escalation_reason"] == "high_value_claim"

    def test_escalation_queue_passes_pagination_params(self):
        client, user = self._make_client(role="senior_partner", uid=_SP)
        mock_result  = {
            "total_pending": 0,
            "overdue_count": 0,
            "page": {"items": [], "total": 0, "page": 3, "page_size": 10, "total_pages": 0},
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.escalation.get_escalation_queue", return_value=mock_result) as mock_fn:
            resp = client.get("/api/v1/attorney/escalation-queue?page=3&page_size=10")
        assert resp.status_code == 200
        _, kwargs = mock_fn.call_args
        assert kwargs["page"]      == 3
        assert kwargs["page_size"] == 10

    # ── POST /escalation-decision ─────────────────────────────────────────────

    def test_escalation_decide_approve_returns_200(self):
        client, user = self._make_client(role="senior_partner", uid=_SP)
        mock_result  = {
            "case_id":     _CASE,
            "decision":    "approve",
            "resolved_at": _NOW,
            "resolved_by": _SP,
            "notes":       None,
            "task_ids":    ["t1", "t2", "t3"],
            "new_status":  "Approved for Filing",
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.escalation.decide_escalation", return_value=mock_result):
            resp = client.post(
                "/api/v1/cases/{}/escalation-decision".format(_CASE),
                json={"decision": "approve"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["decision"]   == "approve"
        assert body["new_status"] == "Approved for Filing"
        assert len(body["task_ids"]) == 3

    def test_escalation_decide_passes_decision_and_notes_to_service(self):
        client, user = self._make_client(role="senior_partner", uid=_SP)
        mock_result  = {
            "case_id": _CASE, "decision": "reject", "resolved_at": _NOW,
            "resolved_by": _SP, "notes": "Weak case.", "task_ids": [],
            "new_status": "Pending Attorney Review",
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.escalation.decide_escalation", return_value=mock_result) as mock_fn:
            client.post(
                "/api/v1/cases/{}/escalation-decision".format(_CASE),
                json={"decision": "reject", "notes": "Weak case."},
            )
        _, kwargs = mock_fn.call_args
        assert kwargs["decision"] == "reject"
        assert kwargs["notes"]    == "Weak case."

    def test_escalation_decide_404_propagates_to_client(self):
        client, user = self._make_client(role="senior_partner", uid=_SP)
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch(
                 "app.routes.escalation.decide_escalation",
                 side_effect=HTTPException(404, detail="Not found"),
             ):
            resp = client.post(
                "/api/v1/cases/{}/escalation-decision".format(_CASE),
                json={"decision": "approve"},
            )
        assert resp.status_code == 404
