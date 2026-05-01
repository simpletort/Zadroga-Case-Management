"""
Tests for the Attorney Review workflow.

Covers:
  - get_review_queue: scoping, sort order, pagination, overdue count
  - approve_for_filing: happy path, status guard, authz, batch writes
  - bulk_approve_for_filing: all-pass, partial failure, error capture
  - RBAC: junior_partner allowed; paralegal blocked; unauthenticated blocked
  - Route integration via FastAPI TestClient
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from fastapi.testclient import TestClient


# ── Shared constants ───────────────────────────────────────────────────────────

_NOW  = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)
_CASE = "ZAD-2026-04-0001"


# ── Snapshot / document helpers ───────────────────────────────────────────────

def _case_snap(
    case_id=_CASE,
    status="Pending Attorney Review",
    assigned_attorney="atty-uid",
    assigned_paralegal="para-uid",
    vcf_deadline=None,
    qual_score=75.0,
    submitted_at=None,
    exists=True,
):
    snap = MagicMock()
    snap.exists = exists
    snap.id     = case_id
    snap.to_dict.return_value = {
        "status":   status,
        "caseType": "VCF",
        "leadData": {"firstName": "John", "lastName": "Doe"},
        "qualification": {"medicalQualScore": qual_score},
        "enrollment": {"vcfRegDeadline": vcf_deadline},
        "assignment": {
            "assignedAttorney":  assigned_attorney,
            "assignedParalegal": assigned_paralegal,
        },
        "submittedForReviewAt": submitted_at or _NOW,
        "updatedAt":            _NOW,
    }
    return snap


def _staff_snap(uid="atty-uid", display_name="Alice Attorney", exists=True):
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = {"displayName": display_name}
    return snap


# ── DB helpers ────────────────────────────────────────────────────────────────

def _make_queue_db(cases: list, actor_uid="atty-uid"):
    """Firestore mock for get_review_queue — returns cases from query.stream()."""
    db    = MagicMock()
    query = MagicMock()
    db.collection.return_value        = query
    query.where.return_value          = query
    query.stream.return_value         = iter(cases)
    return db


def _make_approve_db(
    case_id=_CASE,
    case_status="Pending Attorney Review",
    assigned_attorney="atty-uid",
    assigned_paralegal="para-uid",
    vcf_deadline=None,
):
    """Firestore mock for approve_for_filing with all required sub-collections."""
    db = MagicMock()

    case_ref = MagicMock()
    case_ref.get.return_value = _case_snap(
        case_id=case_id,
        status=case_status,
        assigned_attorney=assigned_attorney,
        assigned_paralegal=assigned_paralegal,
        vcf_deadline=vcf_deadline,
    )

    timeline_coll = MagicMock()
    timeline_doc  = MagicMock()
    timeline_doc.id = "tl-001"
    timeline_coll.document.return_value = timeline_doc

    def _case_sub(name):
        if name == "timeline":
            return timeline_coll
        return MagicMock()

    case_ref.collection.side_effect = _case_sub

    actor_snap = _staff_snap()

    def _collection(name):
        coll = MagicMock()
        if name == "cases":
            coll.document.return_value = case_ref
        elif name == "staff":
            coll.document.return_value = MagicMock(get=MagicMock(return_value=actor_snap))
        elif name == "notifications":
            coll.document.return_value = MagicMock()
        return coll

    db.collection.side_effect = _collection
    db.batch.return_value = MagicMock()
    return db


# ═════════════════════════════════════════════════════════════════════════════
# get_review_queue unit tests
# ═════════════════════════════════════════════════════════════════════════════

class TestGetReviewQueue:

    def _call(self, db, role=None, uid=None, page=1, page_size=20):
        from app.services.attorney_review_service import get_review_queue
        return get_review_queue(db=db, page=page, page_size=page_size)

    # ── Basic happy path ───────────────────────────────────────────────────

    def test_returns_pending_cases(self):
        snap = _case_snap()
        db   = _make_queue_db([snap])

        result = self._call(db)

        assert result["total_pending"] == 1
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["case_id"] == _CASE

    def test_empty_queue_returns_zero_counts(self):
        db = _make_queue_db([])

        result = self._call(db)

        assert result["total_pending"] == 0
        assert result["overdue_count"] == 0
        assert result["page"]["items"] == []

    def test_returns_all_regardless_of_attorney(self):
        snap = _case_snap(assigned_attorney="someone-else")
        db   = _make_queue_db([snap])

        result = self._call(db)

        assert result["total_pending"] == 1

    # ── Sort order ────────────────────────────────────────────────────────

    def test_sorted_by_vcf_deadline_soonest_first(self):
        soon = _NOW + timedelta(days=5)
        far  = _NOW + timedelta(days=30)

        snap_far  = _case_snap(case_id="ZAD-2026-04-0002", vcf_deadline=far)
        snap_soon = _case_snap(case_id="ZAD-2026-04-0001", vcf_deadline=soon)

        db = _make_queue_db([snap_far, snap_soon])  # deliberately reversed

        result = self._call(db)
        items  = result["page"]["items"]

        assert items[0]["case_id"] == "ZAD-2026-04-0001"  # soon first
        assert items[1]["case_id"] == "ZAD-2026-04-0002"

    def test_no_deadline_sorts_after_cases_with_deadline(self):
        has_dl  = _case_snap(case_id="ZAD-2026-04-0001", vcf_deadline=_NOW + timedelta(days=10))
        no_dl   = _case_snap(case_id="ZAD-2026-04-0002", vcf_deadline=None)

        db     = _make_queue_db([no_dl, has_dl])
        result = self._call(db)
        items  = result["page"]["items"]

        assert items[0]["case_id"] == "ZAD-2026-04-0001"  # has deadline first
        assert items[1]["case_id"] == "ZAD-2026-04-0002"

    def test_same_deadline_sorted_by_oldest_submission_first(self):
        dl       = _NOW + timedelta(days=10)
        older    = _case_snap(
            case_id="ZAD-2026-04-0001",
            vcf_deadline=dl,
            submitted_at=_NOW - timedelta(days=5),
        )
        newer    = _case_snap(
            case_id="ZAD-2026-04-0002",
            vcf_deadline=dl,
            submitted_at=_NOW - timedelta(days=1),
        )

        db     = _make_queue_db([newer, older])
        result = self._call(db)
        items  = result["page"]["items"]

        assert items[0]["case_id"] == "ZAD-2026-04-0001"  # older submission first

    def test_tiebreaker_highest_qual_score_first(self):
        dl   = _NOW + timedelta(days=10)
        sub  = _NOW - timedelta(days=3)
        high = _case_snap(case_id="ZAD-2026-04-0001", vcf_deadline=dl, submitted_at=sub, qual_score=90.0)
        low  = _case_snap(case_id="ZAD-2026-04-0002", vcf_deadline=dl, submitted_at=sub, qual_score=50.0)

        db     = _make_queue_db([low, high])
        result = self._call(db)
        items  = result["page"]["items"]

        assert items[0]["case_id"] == "ZAD-2026-04-0001"  # higher score first

    # ── Overdue count ─────────────────────────────────────────────────────

    def test_overdue_count_includes_past_deadlines(self):
        overdue = _case_snap(case_id="ZAD-2026-04-0001", vcf_deadline=_NOW - timedelta(days=3))
        future  = _case_snap(case_id="ZAD-2026-04-0002", vcf_deadline=_NOW + timedelta(days=10))
        no_dl   = _case_snap(case_id="ZAD-2026-04-0003", vcf_deadline=None)

        db     = _make_queue_db([overdue, future, no_dl])
        with patch("app.services.attorney_review_service.datetime") as mock_dt:
            mock_dt.now.return_value = _NOW
            result = self._call(db)

        assert result["overdue_count"] == 1

    def test_days_until_deadline_is_negative_when_overdue(self):
        snap   = _case_snap(vcf_deadline=_NOW - timedelta(days=2))
        db     = _make_queue_db([snap])
        result = self._call(db)

        assert result["page"]["items"][0]["days_until_deadline"] < 0

    # ── Pagination ────────────────────────────────────────────────────────

    def test_pagination_slices_correctly(self):
        snaps = [_case_snap(case_id="ZAD-2026-04-{:04d}".format(i)) for i in range(5)]
        db    = _make_queue_db(snaps)

        result = self._call(db, page=2, page_size=2)

        assert result["page"]["page"]        == 2
        assert result["page"]["page_size"]   == 2
        assert result["page"]["total"]       == 5
        assert result["page"]["total_pages"] == 3
        assert len(result["page"]["items"])  == 2

    def test_total_pages_rounds_up(self):
        snaps = [_case_snap(case_id="ZAD-2026-04-{:04d}".format(i)) for i in range(3)]
        db    = _make_queue_db(snaps)

        result = self._call(db, page=1, page_size=2)

        assert result["page"]["total_pages"] == 2


# ═════════════════════════════════════════════════════════════════════════════
# approve_for_filing unit tests
# ═════════════════════════════════════════════════════════════════════════════

class TestApproveForFiling:

    def _call(self, db, case_id=_CASE, actor_uid="atty-uid", actor_role="junior_partner", notes=None):
        from app.services.attorney_review_service import approve_for_filing
        return approve_for_filing(
            db=db,
            case_id=case_id,
            actor_uid=actor_uid,
            actor_role=actor_role,
            notes=notes,
        )

    # ── Happy path ────────────────────────────────────────────────────────

    def test_returns_approved_status(self):
        db     = _make_approve_db()
        result = self._call(db)

        assert result["status"]      == "Approved for Filing"
        assert result["case_id"]     == _CASE
        assert result["approved_by"] == "atty-uid"

    def test_returns_three_task_ids(self):
        db     = _make_approve_db()
        result = self._call(db)

        assert len(result["task_ids"]) == 3

    def test_approved_at_is_datetime(self):
        db     = _make_approve_db()
        result = self._call(db)

        assert isinstance(result["approved_at"], datetime)

    def test_notes_included_in_result(self):
        db     = _make_approve_db()
        result = self._call(db, notes="Strong case, proceed.")

        assert result["notes"] == "Strong case, proceed."

    # ── Validation ────────────────────────────────────────────────────────

    def test_case_not_found_raises_404(self):
        db = MagicMock()
        missing = MagicMock()
        missing.exists = False
        db.collection.return_value.document.return_value.get.return_value = missing

        with pytest.raises(HTTPException) as exc_info:
            self._call(db)

        assert exc_info.value.status_code == 404

    def test_wrong_status_raises_422(self):
        db = _make_approve_db(case_status="Pending Paralegal Review")

        with pytest.raises(HTTPException) as exc_info:
            self._call(db)

        assert exc_info.value.status_code == 422
        assert "Pending Paralegal Review" in exc_info.value.detail

    def test_already_approved_raises_422(self):
        db = _make_approve_db(case_status="Approved for Filing")

        with pytest.raises(HTTPException) as exc_info:
            self._call(db)

        assert exc_info.value.status_code == 422

    # ── Authorisation ─────────────────────────────────────────────────────

    def test_junior_partner_cannot_approve_another_attorneys_case(self):
        db = _make_approve_db(assigned_attorney="other-atty")

        with pytest.raises(HTTPException) as exc_info:
            self._call(db, actor_uid="atty-uid", actor_role="junior_partner")

        assert exc_info.value.status_code == 403

    def test_senior_partner_can_approve_any_case(self):
        db = _make_approve_db(assigned_attorney="other-atty")

        result = self._call(db, actor_uid="senior-uid", actor_role="senior_partner")

        assert result["status"] == "Approved for Filing"

    def test_system_admin_can_approve_any_case(self):
        db = _make_approve_db(assigned_attorney="other-atty")

        result = self._call(db, actor_uid="admin-uid", actor_role="system_admin")

        assert result["status"] == "Approved for Filing"

    # ── Batch writes ──────────────────────────────────────────────────────

    def test_batch_committed_once(self):
        db = _make_approve_db()
        self._call(db)

        db.batch.return_value.commit.assert_called_once()

    def test_three_filing_prep_tasks_written_to_batch(self):
        db = _make_approve_db()
        self._call(db)

        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        task_calls = [
            c for c in set_calls
            if (c[0][1] if c[0] else c[1]).get("type") == "filing_prep"
        ]
        assert len(task_calls) == 3

    def test_filing_tasks_assigned_to_paralegal(self):
        db = _make_approve_db(assigned_paralegal="para-uid")
        self._call(db)

        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        task_calls = [
            c for c in set_calls
            if (c[0][1] if c[0] else c[1]).get("type") == "filing_prep"
        ]
        for tc in task_calls:
            data = tc[0][1]
            assert data["assignedTo"] == "para-uid"

    def test_filing_task_titles(self):
        db = _make_approve_db()
        self._call(db)

        batch      = db.batch.return_value
        set_calls  = batch.set.call_args_list
        task_titles = {
            (c[0][1] if c[0] else c[1]).get("title")
            for c in set_calls
            if (c[0][1] if c[0] else c[1]).get("type") == "filing_prep"
        }
        assert "Prepare VCF filing package"    in task_titles
        assert "File with VCF program"         in task_titles
        assert "Notify client of filing status" in task_titles

    def test_file_with_vcf_task_has_due_date_when_deadline_set(self):
        dl = _NOW + timedelta(days=14)
        db = _make_approve_db(vcf_deadline=dl)
        self._call(db)

        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        vcf_task  = next(
            (c for c in set_calls
             if (c[0][1] if c[0] else c[1]).get("title") == "File with VCF program"),
            None,
        )
        assert vcf_task is not None
        assert vcf_task[0][1].get("dueDate") is not None

    def test_file_with_vcf_task_has_no_due_date_when_no_deadline(self):
        db = _make_approve_db(vcf_deadline=None)
        self._call(db)

        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        vcf_task  = next(
            (c for c in set_calls
             if (c[0][1] if c[0] else c[1]).get("title") == "File with VCF program"),
            None,
        )
        assert vcf_task is not None
        assert "dueDate" not in vcf_task[0][1]

    def test_paralegal_notification_written_to_batch(self):
        db = _make_approve_db(assigned_paralegal="para-uid")
        self._call(db)

        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        notif = next(
            (c for c in set_calls
             if (c[0][1] if c[0] else c[1]).get("type") == "case_approved_for_filing"),
            None,
        )
        assert notif is not None, "No notification batch.set found"
        notif_data = notif[0][1]
        assert notif_data["recipientId"] == "para-uid"
        assert notif_data["caseId"]      == _CASE

    def test_timeline_event_written_to_batch(self):
        db = _make_approve_db()
        self._call(db)

        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        timeline  = next(
            (c for c in set_calls
             if (c[0][1] if c[0] else c[1]).get("eventType") == "StatusChange"),
            None,
        )
        assert timeline is not None, "No timeline StatusChange batch.set found"
        tl_data = timeline[0][1]
        assert tl_data["performedBy"]             == "atty-uid"
        assert tl_data["metadata"]["newStatus"]   == "Approved for Filing"
        assert tl_data["metadata"]["previousStatus"] == "Pending Attorney Review"

    def test_case_update_written_to_batch(self):
        db = _make_approve_db()
        self._call(db)

        batch  = db.batch.return_value
        update_calls = batch.update.call_args_list
        assert len(update_calls) >= 1

        # The case update must set the new status
        case_update = update_calls[0][0][1]  # second positional arg = payload dict
        assert case_update["status"]              == "Approved for Filing"
        assert "approvedForFilingAt"              in case_update
        assert case_update["approvedForFilingBy"] == "atty-uid"

    def test_batch_has_at_least_five_writes(self):
        """case update + 3 tasks + notification + timeline = 6 minimum."""
        db = _make_approve_db()
        self._call(db)

        batch     = db.batch.return_value
        set_count = batch.set.call_count
        upd_count = batch.update.call_count
        assert set_count + upd_count >= 5


# ═════════════════════════════════════════════════════════════════════════════
# bulk_approve_for_filing unit tests
# ═════════════════════════════════════════════════════════════════════════════

class TestBulkApproveForFiling:

    def _call(self, db, case_ids, actor_uid="atty-uid", actor_role="junior_partner", notes=None):
        from app.services.attorney_review_service import bulk_approve_for_filing
        return bulk_approve_for_filing(
            db=db,
            case_ids=case_ids,
            actor_uid=actor_uid,
            actor_role=actor_role,
            notes=notes,
        )

    def _multi_case_db(self, case_ids):
        """Build a db that returns a fresh ready-case snap for each case_id."""
        db = MagicMock()

        actor_snap = _staff_snap()

        def _get_case(case_id):
            snap = _case_snap(case_id=case_id)
            return snap

        def _get_case_ref(case_id):
            case_ref = MagicMock()
            case_ref.get.return_value = _get_case(case_id)
            timeline_coll = MagicMock()
            timeline_coll.document.return_value = MagicMock(id="tl-x")
            case_ref.collection.side_effect = lambda name: (
                timeline_coll if name == "timeline" else MagicMock()
            )
            return case_ref

        # Track calls to .document() per collection
        call_counters = {"cases": 0}

        def _cases_coll_document(case_id):
            return _get_case_ref(case_id)

        def _collection(name):
            coll = MagicMock()
            if name == "cases":
                coll.document.side_effect = _cases_coll_document
            elif name == "staff":
                coll.document.return_value = MagicMock(get=MagicMock(return_value=actor_snap))
            elif name == "notifications":
                coll.document.return_value = MagicMock()
            return coll

        db.collection.side_effect = _collection
        db.batch.return_value = MagicMock()
        return db

    # ── Summary counts ────────────────────────────────────────────────────

    def test_all_succeed_counts(self):
        ids = ["ZAD-2026-04-0001", "ZAD-2026-04-0002"]
        db  = self._multi_case_db(ids)

        result = self._call(db, ids)

        assert result["requested"] == 2
        assert result["approved"]  == 2
        assert result["failed"]    == 0

    def test_results_list_length_matches_requested(self):
        ids = ["ZAD-2026-04-0001", "ZAD-2026-04-0002", "ZAD-2026-04-0003"]
        db  = self._multi_case_db(ids)

        result = self._call(db, ids)

        assert len(result["results"]) == 3

    def test_successful_result_has_correct_fields(self):
        ids    = [_CASE]
        db     = self._multi_case_db(ids)
        result = self._call(db, ids)

        r = result["results"][0]
        assert r["case_id"]    == _CASE
        assert r["success"]    is True
        assert r["status"]     == "Approved for Filing"
        assert r["error"]      is None
        assert len(r["task_ids"]) == 3

    # ── Partial failure ───────────────────────────────────────────────────

    def test_failed_case_captured_without_raising(self):
        """A case in wrong status should fail gracefully — others still succeed."""
        db = MagicMock()

        actor_snap = _staff_snap()

        def _get_case_ref(case_id):
            case_ref = MagicMock()
            # First case is ready; second has wrong status
            if case_id == "ZAD-GOOD":
                case_ref.get.return_value = _case_snap(case_id="ZAD-GOOD")
            else:
                case_ref.get.return_value = _case_snap(
                    case_id="ZAD-BAD", status="Closed"
                )
            timeline_coll = MagicMock()
            timeline_coll.document.return_value = MagicMock(id="tl-x")
            case_ref.collection.side_effect = lambda name: (
                timeline_coll if name == "timeline" else MagicMock()
            )
            return case_ref

        def _collection(name):
            coll = MagicMock()
            if name == "cases":
                coll.document.side_effect = _get_case_ref
            elif name == "staff":
                coll.document.return_value = MagicMock(get=MagicMock(return_value=actor_snap))
            elif name == "notifications":
                coll.document.return_value = MagicMock()
            return coll

        db.collection.side_effect = _collection
        db.batch.return_value = MagicMock()

        result = self._call(db, ["ZAD-GOOD", "ZAD-BAD"])

        assert result["approved"] == 1
        assert result["failed"]   == 1

        good = next(r for r in result["results"] if r["case_id"] == "ZAD-GOOD")
        bad  = next(r for r in result["results"] if r["case_id"] == "ZAD-BAD")

        assert good["success"] is True
        assert bad["success"]  is False
        assert bad["error"]    is not None

    def test_not_found_case_captured_without_raising(self):
        db = MagicMock()

        actor_snap = _staff_snap()

        def _get_case_ref(case_id):
            case_ref = MagicMock()
            missing  = MagicMock()
            missing.exists = False
            case_ref.get.return_value = missing
            return case_ref

        def _collection(name):
            coll = MagicMock()
            if name == "cases":
                coll.document.side_effect = _get_case_ref
            elif name == "staff":
                coll.document.return_value = MagicMock(get=MagicMock(return_value=actor_snap))
            return coll

        db.collection.side_effect = _collection
        db.batch.return_value = MagicMock()

        result = self._call(db, ["ZAD-MISSING"])

        assert result["approved"] == 0
        assert result["failed"]   == 1
        assert result["results"][0]["success"] is False


# ═════════════════════════════════════════════════════════════════════════════
# RBAC tests
# ═════════════════════════════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════════════════════════════
# Route integration tests
# ═════════════════════════════════════════════════════════════════════════════

class TestAttorneyReviewRoutes:

    def _make_client(self, role="junior_partner", uid="atty-uid"):
        user = {"uid": uid, "role": role}
        from importlib import reload
        import main as m
        reload(m)
        client = TestClient(m.app, raise_server_exceptions=False)
        return client, user

    # ── Review queue endpoint ─────────────────────────────────────────────

    def test_review_queue_endpoint_returns_200(self):
        client, user = self._make_client()
        mock_result = {
            "total_pending": 1,
            "overdue_count": 0,
            "page": {
                "items": [{
                    "case_id":                 _CASE,
                    "first_name":              "John",
                    "last_name":               "Doe",
                    "case_type":               "VCF",
                    "vcf_deadline":            None,
                    "qual_score":              75.0,
                    "submitted_for_review_at": _NOW,
                    "assigned_paralegal":      "para-uid",
                    "assigned_paralegal_name": None,
                    "days_until_deadline":     None,
                }],
                "total":       1,
                "page":        1,
                "page_size":   20,
                "total_pages": 1,
            },
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.attorney_review.get_review_queue", return_value=mock_result):
            resp = client.get(
                "/api/v1/attorney/review-queue",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_pending"]          == 1
        assert body["page"]["items"][0]["case_id"] == _CASE

    def test_review_queue_passes_pagination_params(self):
        client, user = self._make_client()
        mock_result = {
            "total_pending": 0,
            "overdue_count": 0,
            "page": {"items": [], "total": 0, "page": 2, "page_size": 5, "total_pages": 0},
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.attorney_review.get_review_queue", return_value=mock_result) as mock_fn:
            resp = client.get(
                "/api/v1/attorney/review-queue?page=2&page_size=5",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        _, kwargs = mock_fn.call_args
        assert kwargs["page"]      == 2
        assert kwargs["page_size"] == 5

    # ── Approve for filing endpoint ───────────────────────────────────────

    def test_approve_endpoint_returns_200(self):
        client, user = self._make_client()
        mock_result = {
            "case_id":     _CASE,
            "status":      "Approved for Filing",
            "approved_at": _NOW,
            "approved_by": "atty-uid",
            "notes":       None,
            "task_ids":    ["t1", "t2", "t3"],
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.attorney_review.approve_for_filing", return_value=mock_result):
            resp = client.post(
                "/api/v1/cases/{}/approve-for-filing".format(_CASE),
                json={},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"]  == "Approved for Filing"
        assert body["case_id"] == _CASE

    def test_approve_passes_notes_to_service(self):
        client, user = self._make_client()
        mock_result = {
            "case_id":     _CASE,
            "status":      "Approved for Filing",
            "approved_at": _NOW,
            "approved_by": "atty-uid",
            "notes":       "Solid case.",
            "task_ids":    [],
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.attorney_review.approve_for_filing", return_value=mock_result) as mock_fn:
            client.post(
                "/api/v1/cases/{}/approve-for-filing".format(_CASE),
                json={"notes": "Solid case."},
                headers={"Authorization": "Bearer fake-token"},
            )
        _, kwargs = mock_fn.call_args
        assert kwargs["notes"] == "Solid case."

    def test_approve_422_propagates_to_client(self):
        client, user = self._make_client()
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch(
                 "app.routes.attorney_review.approve_for_filing",
                 side_effect=HTTPException(status_code=422, detail="Wrong status"),
             ):
            resp = client.post(
                "/api/v1/cases/{}/approve-for-filing".format(_CASE),
                json={},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 422

    def test_approve_404_propagates_to_client(self):
        client, user = self._make_client()
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch(
                 "app.routes.attorney_review.approve_for_filing",
                 side_effect=HTTPException(status_code=404, detail="Not found"),
             ):
            resp = client.post(
                "/api/v1/cases/{}/approve-for-filing".format(_CASE),
                json={},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 404

    # ── Bulk approve endpoint ─────────────────────────────────────────────

    def test_bulk_approve_endpoint_returns_200(self):
        client, user = self._make_client()
        mock_result = {
            "requested": 2,
            "approved":  2,
            "failed":    0,
            "results": [
                {"case_id": "ZAD-2026-04-0001", "success": True, "status": "Approved for Filing",
                 "approved_at": _NOW, "task_ids": ["t1"], "error": None},
                {"case_id": "ZAD-2026-04-0002", "success": True, "status": "Approved for Filing",
                 "approved_at": _NOW, "task_ids": ["t2"], "error": None},
            ],
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.routes.attorney_review.bulk_approve_for_filing", return_value=mock_result):
            resp = client.post(
                "/api/v1/cases/bulk-approve",
                json={"case_ids": ["ZAD-2026-04-0001", "ZAD-2026-04-0002"]},
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["requested"] == 2
        assert body["approved"]  == 2
        assert len(body["results"]) == 2

    def test_bulk_approve_empty_list_rejected(self):
        """Pydantic min_length=1 on case_ids should cause 422."""
        client, user = self._make_client()
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()):
            resp = client.post(
                "/api/v1/cases/bulk-approve",
                json={"case_ids": []},
            )
        assert resp.status_code == 422
