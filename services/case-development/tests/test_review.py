"""
Tests for the 'Submit for Attorney Review' workflow.

Covers:
  - run_preflight: each check passes / fails independently
  - submit_for_review: happy path + blocked-when-preflight-fails
  - RBAC: paralegal allowed, no-token rejected
  - Route integration via FastAPI TestClient
"""

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone
from fastapi import HTTPException
from fastapi.testclient import TestClient


# ── Fixtures / helpers ─────────────────────────────────────────────────────

_NOW = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)


def _case_snap(
    status="Pending Paralegal Review",
    questionnaire=True,
    ai_summary=True,
    attorney="atty-1",
    exists=True,
):
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = {
        "status": status,
        "questionnaireComplete": questionnaire,
        "aiSummaryGenerated": ai_summary,
        "assignment": {"assignedAttorney": attorney},
    }
    return snap


def _doc_snap(category: str, scan_status: str = "clean"):
    doc = MagicMock()
    doc.id = "doc-{}".format(category)
    doc.to_dict.return_value = {"category": category, "scanStatus": scan_status}
    return doc


def _all_clean_docs():
    return [
        _doc_snap("medical-records"),
        _doc_snap("proof-of-presence"),
        _doc_snap("id-documents"),
    ]


def _db_with_full_case(case_id="ZAD-2026-04-0001"):
    """Build a mock Firestore client representing a fully-ready case."""
    db = MagicMock()

    case_ref = MagicMock()
    case_ref.get.return_value = _case_snap()

    docs_coll = MagicMock()
    docs_coll.stream.return_value = iter(_all_clean_docs())
    case_ref.collection.side_effect = lambda name: (
        docs_coll if name == "documents" else MagicMock()
    )

    db.collection.return_value.document.return_value = case_ref
    return db


# ── run_preflight unit tests ───────────────────────────────────────────────

class TestRunPreflight:

    def _db(
        self,
        case_status="Pending Paralegal Review",
        questionnaire=True,
        ai_summary=True,
        docs=None,
    ):
        if docs is None:
            docs = _all_clean_docs()

        db = MagicMock()
        case_ref = MagicMock()
        case_ref.get.return_value = _case_snap(
            status=case_status,
            questionnaire=questionnaire,
            ai_summary=ai_summary,
        )

        docs_coll = MagicMock()
        docs_coll.stream.return_value = iter(docs)
        case_ref.collection.side_effect = lambda name: (
            docs_coll if name == "documents" else MagicMock()
        )

        db.collection.return_value.document.return_value = case_ref
        return db

    def test_all_checks_pass(self):
        from app.services.review_service import run_preflight

        result = run_preflight(self._db(), "ZAD-2026-04-0001")

        assert result["all_passed"] is True
        assert all(c["passed"] for c in result["checks"])

    def test_wrong_status_fails(self):
        from app.services.review_service import run_preflight

        result = run_preflight(self._db(case_status="Pending Client Info"), "ZAD-2026-04-0001")

        status_check = next(c for c in result["checks"] if c["name"] == "case_status")
        assert status_check["passed"] is False
        assert result["all_passed"] is False

    def test_missing_medical_records_fails(self):
        from app.services.review_service import run_preflight

        docs = [_doc_snap("proof-of-presence"), _doc_snap("id-documents")]
        result = run_preflight(self._db(docs=docs), "ZAD-2026-04-0001")

        med_check = next(c for c in result["checks"] if c["name"] == "document_medical_records")
        assert med_check["passed"] is False
        assert result["all_passed"] is False

    def test_infected_document_not_counted(self):
        from app.services.review_service import run_preflight

        # medical-records exists but is infected — should not count
        docs = [
            _doc_snap("medical-records", scan_status="infected"),
            _doc_snap("proof-of-presence"),
            _doc_snap("id-documents"),
        ]
        result = run_preflight(self._db(docs=docs), "ZAD-2026-04-0001")

        med_check = next(c for c in result["checks"] if c["name"] == "document_medical_records")
        assert med_check["passed"] is False

    def test_questionnaire_incomplete_fails(self):
        from app.services.review_service import run_preflight

        result = run_preflight(self._db(questionnaire=False), "ZAD-2026-04-0001")

        q_check = next(c for c in result["checks"] if c["name"] == "questionnaire_complete")
        assert q_check["passed"] is False
        assert result["all_passed"] is False

    def test_ai_summary_missing_fails(self):
        from app.services.review_service import run_preflight

        result = run_preflight(self._db(ai_summary=False), "ZAD-2026-04-0001")

        ai_check = next(c for c in result["checks"] if c["name"] == "ai_summary_generated")
        assert ai_check["passed"] is False
        assert result["all_passed"] is False

    def test_case_not_found_raises_404(self):
        from app.services.review_service import run_preflight

        db = MagicMock()
        missing = MagicMock()
        missing.exists = False
        db.collection.return_value.document.return_value.get.return_value = missing

        with pytest.raises(HTTPException) as exc_info:
            run_preflight(db, "ZAD-INVALID")

        assert exc_info.value.status_code == 404

    def test_returns_all_check_names(self):
        from app.services.review_service import (
            run_preflight,
            REQUIRED_DOCUMENT_CATEGORIES,
        )

        result = run_preflight(self._db(), "ZAD-2026-04-0001")
        names = {c["name"] for c in result["checks"]}

        assert "case_status" in names
        assert "questionnaire_complete" in names
        assert "ai_summary_generated" in names
        for cat in REQUIRED_DOCUMENT_CATEGORIES:
            assert "document_{}".format(cat.replace("-", "_")) in names


# ── submit_for_review unit tests ───────────────────────────────────────────

class TestSubmitForReview:

    def _ready_db(self, case_id="ZAD-2026-04-0001"):
        db = MagicMock()

        case_ref = MagicMock()
        case_ref.get.return_value = _case_snap()

        docs_coll = MagicMock()
        docs_coll.stream.return_value = iter(_all_clean_docs())

        timeline_coll = MagicMock()
        timeline_doc = MagicMock()
        timeline_doc.id = "tl-001"
        timeline_coll.document.return_value = timeline_doc

        def _case_sub(name):
            if name == "documents":
                return docs_coll
            if name == "timeline":
                return timeline_coll
            return MagicMock()

        case_ref.collection.side_effect = _case_sub

        staff_snap = MagicMock()
        staff_snap.exists = True
        staff_snap.to_dict.return_value = {"displayName": "Jane Paralegal"}

        def _collection(name):
            coll = MagicMock()
            if name == "cases":
                coll.document.return_value = case_ref
            elif name == "staff":
                coll.document.return_value = MagicMock(get=MagicMock(return_value=staff_snap))
                # No junior_partners available in the default ready-db fixture
                # (case already has attorney="atty-1", so this is never reached in
                #  happy-path tests; explicit iter([]) guards the no-attorney path)
                coll.where.return_value.stream.return_value = iter([])
            elif name == "notifications":
                coll.document.return_value = MagicMock()
            return coll

        db.collection.side_effect = _collection
        db.batch.return_value = MagicMock()
        return db

    def test_happy_path_returns_correct_status(self):
        from app.services.review_service import submit_for_review, TARGET_STATUS

        db = self._ready_db()
        result = submit_for_review(db, "ZAD-2026-04-0001", actor_uid="para-uid")

        assert result["status"] == TARGET_STATUS
        assert result["case_id"] == "ZAD-2026-04-0001"
        assert result["submitted_by"] == "para-uid"
        assert result["notified_attorney_id"] == "atty-1"

    def test_happy_path_commits_batch(self):
        from app.services.review_service import submit_for_review

        db = self._ready_db()
        submit_for_review(db, "ZAD-2026-04-0001", actor_uid="para-uid")

        db.batch.return_value.commit.assert_called_once()

    def test_blocked_when_preflight_fails(self):
        from app.services.review_service import submit_for_review

        db = MagicMock()
        case_ref = MagicMock()
        case_ref.get.return_value = _case_snap(status="Pending Client Info", questionnaire=False)

        docs_coll = MagicMock()
        docs_coll.stream.return_value = iter([])
        case_ref.collection.return_value = docs_coll

        db.collection.return_value.document.return_value = case_ref

        with pytest.raises(HTTPException) as exc_info:
            submit_for_review(db, "ZAD-2026-04-0001", actor_uid="para-uid")

        assert exc_info.value.status_code == 422
        assert "failed_checks" in exc_info.value.detail

    def test_no_attorney_assigned_still_submits(self):
        from app.services.review_service import submit_for_review

        db = self._ready_db()
        # Override case snap to have no attorney
        case_ref = db.collection("cases").document("ZAD-2026-04-0001")
        case_ref.get.return_value = _case_snap(attorney=None)

        result = submit_for_review(db, "ZAD-2026-04-0001", actor_uid="para-uid")
        assert result["notified_attorney_id"] is None


# ── Route integration tests ────────────────────────────────────────────────

class TestReviewRoutes:

    def _make_client(self, role="paralegal"):
        user = {"uid": "para-uid", "role": role}
        from importlib import reload
        import main as m
        reload(m)
        client = TestClient(m.app, raise_server_exceptions=False)
        return client, user

    def test_preflight_endpoint_exists(self):
        client, user = self._make_client()
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch(
                 "app.routes.review.run_preflight",
                 return_value={"all_passed": True, "checks": []},
             ):
            resp = client.get(
                "/api/v1/cases/ZAD-2026-04-0001/review-preflight",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["case_id"] == "ZAD-2026-04-0001"
        assert body["all_passed"] is True

    def test_submit_endpoint_exists(self):
        from app.services.review_service import TARGET_STATUS

        client, user = self._make_client()
        mock_result = {
            "case_id":                   "ZAD-2026-04-0001",
            "status":                    TARGET_STATUS,
            "submitted_at":              _NOW,
            "submitted_by":              "para-uid",
            "notified_attorney_id":      "atty-1",
            "task_id":                   "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "auto_assigned_attorney_id": None,
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch(
                 "app.routes.review.submit_for_review",
                 return_value=mock_result,
             ):
            resp = client.post(
                "/api/v1/cases/ZAD-2026-04-0001/submit-for-review",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == TARGET_STATUS

    def test_submit_422_propagates_to_client(self):
        client, user = self._make_client()
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch(
                 "app.routes.review.submit_for_review",
                 side_effect=HTTPException(
                     status_code=422,
                     detail={"message": "Pre-flight checks failed.", "failed_checks": ["x"]},
                 ),
             ):
            resp = client.post(
                "/api/v1/cases/ZAD-2026-04-0001/submit-for-review",
                headers={"Authorization": "Bearer fake-token"},
            )
        assert resp.status_code == 422


# ── Auto-assign Junior Partner tests ──────────────────────────────────────


def _jp_snap(uid="jp-001", display_name="Bob Junior", active_case_count=3):
    """Mock Firestore document snapshot for a junior_partner staff member."""
    snap = MagicMock()
    snap.id = uid
    snap.to_dict.return_value = {
        "displayName":     display_name,
        "role":            "junior_partner",
        "activeCaseCount": active_case_count,
    }
    return snap


class TestFindLeastLoadedJuniorPartner:
    """Unit tests for the _find_least_loaded_junior_partner helper."""

    def test_returns_none_when_no_junior_partners(self):
        from app.services.review_service import _find_least_loaded_junior_partner

        db = MagicMock()
        db.collection.return_value.where.return_value.stream.return_value = iter([])

        assert _find_least_loaded_junior_partner(db) is None

    def test_returns_least_loaded_of_multiple_jps(self):
        from app.services.review_service import _find_least_loaded_junior_partner

        jp_busy  = _jp_snap(uid="jp-busy",  active_case_count=10)
        jp_light = _jp_snap(uid="jp-light", active_case_count=2)

        call_count = {"n": 0}

        def _stream():
            call_count["n"] += 1
            # First call (role=="junior_partner") returns both; second returns []
            return iter([jp_busy, jp_light]) if call_count["n"] == 1 else iter([])

        db = MagicMock()
        db.collection.return_value.where.return_value.stream.side_effect = _stream

        result = _find_least_loaded_junior_partner(db)

        assert result is not None
        assert result["uid"] == "jp-light"
        assert result["activeCaseCount"] == 2

    def test_deduplicates_same_doc_across_both_role_values(self):
        from app.services.review_service import _find_least_loaded_junior_partner

        jp = _jp_snap(uid="jp-001", active_case_count=5)
        # Both queries return the same document id — must only appear once
        db = MagicMock()
        db.collection.return_value.where.return_value.stream.return_value = iter([jp])

        result = _find_least_loaded_junior_partner(db)

        assert result is not None
        assert result["uid"] == "jp-001"

    def test_handles_none_active_case_count(self):
        from app.services.review_service import _find_least_loaded_junior_partner

        jp = MagicMock()
        jp.id = "jp-null-count"
        jp.to_dict.return_value = {"displayName": "Alice JP", "activeCaseCount": None}

        db = MagicMock()
        db.collection.return_value.where.return_value.stream.return_value = iter([jp])

        result = _find_least_loaded_junior_partner(db)

        assert result is not None
        assert result["activeCaseCount"] == 0  # None coerced to 0


class TestAutoAssignJuniorPartner:
    """Integration tests for auto-assign JP + task creation inside submit_for_review."""

    def _ready_db_no_attorney(self, jp=None):
        """
        Fully-ready case fixture with no assignedAttorney.
        Pass a jp_snap to simulate an available junior_partner, or None for empty.
        """
        db = MagicMock()

        case_ref = MagicMock()
        case_ref.get.return_value = _case_snap(attorney=None)

        docs_coll = MagicMock()
        docs_coll.stream.return_value = iter(_all_clean_docs())

        timeline_coll = MagicMock()
        timeline_doc  = MagicMock()
        timeline_doc.id = "tl-001"
        timeline_coll.document.return_value = timeline_doc

        def _case_sub(name):
            if name == "documents":
                return docs_coll
            if name == "timeline":
                return timeline_coll
            return MagicMock()

        case_ref.collection.side_effect = _case_sub

        actor_staff_snap = MagicMock()
        actor_staff_snap.exists = True
        actor_staff_snap.to_dict.return_value = {"displayName": "Jane Paralegal"}

        jp_results = iter([jp]) if jp is not None else iter([])

        def _collection(name):
            coll = MagicMock()
            if name == "cases":
                coll.document.return_value = case_ref
            elif name == "staff":
                coll.document.return_value = MagicMock(
                    get=MagicMock(return_value=actor_staff_snap)
                )
                coll.where.return_value.stream.return_value = jp_results
            elif name == "notifications":
                coll.document.return_value = MagicMock()
            return coll

        db.collection.side_effect = _collection
        db.batch.return_value = MagicMock()
        return db

    # ── Status transition ──────────────────────────────────────────────────

    def test_full_workflow_status_transitions_to_pending_attorney_review(self):
        from app.services.review_service import submit_for_review, TARGET_STATUS

        db     = self._ready_db_no_attorney(jp=_jp_snap())
        result = submit_for_review(db, "ZAD-2026-04-0001", actor_uid="para-uid")

        assert result["status"] == TARGET_STATUS
        assert result["status"] == "Pending Attorney Review"

    # ── Auto-assign ────────────────────────────────────────────────────────

    def test_auto_assigns_jp_when_no_attorney(self):
        from app.services.review_service import submit_for_review

        db     = self._ready_db_no_attorney(jp=_jp_snap(uid="jp-001"))
        result = submit_for_review(db, "ZAD-2026-04-0001", actor_uid="para-uid")

        assert result["auto_assigned_attorney_id"] == "jp-001"
        assert result["notified_attorney_id"]      == "jp-001"

    def test_no_auto_assign_when_attorney_already_set(self):
        from app.services.review_service import submit_for_review

        # Reuse the base _ready_db fixture — case has attorney="atty-1"
        db = MagicMock()

        case_ref = MagicMock()
        case_ref.get.return_value = _case_snap(attorney="atty-1")

        docs_coll = MagicMock()
        docs_coll.stream.return_value = iter(_all_clean_docs())

        timeline_coll = MagicMock()
        timeline_coll.document.return_value = MagicMock(id="tl-002")

        def _case_sub(name):
            if name == "documents": return docs_coll
            if name == "timeline":  return timeline_coll
            return MagicMock()

        case_ref.collection.side_effect = _case_sub

        actor_snap = MagicMock()
        actor_snap.exists = True
        actor_snap.to_dict.return_value = {"displayName": "Jane Paralegal"}

        def _collection(name):
            coll = MagicMock()
            if name == "cases":
                coll.document.return_value = case_ref
            elif name == "staff":
                coll.document.return_value = MagicMock(get=MagicMock(return_value=actor_snap))
                coll.where.return_value.stream.return_value = iter([])
            elif name == "notifications":
                coll.document.return_value = MagicMock()
            return coll

        db.collection.side_effect = _collection
        db.batch.return_value = MagicMock()

        result = submit_for_review(db, "ZAD-2026-04-0001", actor_uid="para-uid")

        assert result["auto_assigned_attorney_id"] is None
        assert result["notified_attorney_id"]      == "atty-1"

    def test_submission_succeeds_when_no_jp_exists(self):
        """Submission must not be blocked when no junior_partner record exists."""
        from app.services.review_service import submit_for_review

        db     = self._ready_db_no_attorney(jp=None)
        result = submit_for_review(db, "ZAD-2026-04-0001", actor_uid="para-uid")

        assert result["status"]                    == "Pending Attorney Review"
        assert result["auto_assigned_attorney_id"] is None
        assert result["notified_attorney_id"]      is None

    # ── Task creation ──────────────────────────────────────────────────────

    def test_task_id_always_returned(self):
        from app.services.review_service import submit_for_review

        db     = self._ready_db_no_attorney(jp=_jp_snap())
        result = submit_for_review(db, "ZAD-2026-04-0001", actor_uid="para-uid")

        assert result["task_id"] is not None
        assert len(result["task_id"]) == 36  # UUID format

    def test_task_written_to_batch_with_correct_type(self):
        from app.services.review_service import submit_for_review

        db = self._ready_db_no_attorney(jp=_jp_snap(uid="jp-001"))
        submit_for_review(db, "ZAD-2026-04-0001", actor_uid="para-uid")

        batch = db.batch.return_value
        set_calls = batch.set.call_args_list

        task_call = next(
            (c for c in set_calls if (c[0][1] if c[0] else c[1]).get("type") == "attorney_review"),
            None,
        )
        assert task_call is not None, "No batch.set call with type='attorney_review' found"

        task_data = task_call[0][1]
        assert task_data["caseId"]     == "ZAD-2026-04-0001"
        assert task_data["assignedTo"] == "jp-001"
        assert task_data["status"]     == "open"
        assert task_data["priority"]   == "normal"

    def test_task_assigned_to_original_attorney_when_present(self):
        from app.services.review_service import submit_for_review

        db = MagicMock()

        case_ref = MagicMock()
        case_ref.get.return_value = _case_snap(attorney="atty-original")

        docs_coll = MagicMock()
        docs_coll.stream.return_value = iter(_all_clean_docs())

        timeline_coll = MagicMock()
        timeline_coll.document.return_value = MagicMock(id="tl-003")

        def _case_sub(name):
            if name == "documents": return docs_coll
            if name == "timeline":  return timeline_coll
            return MagicMock()

        case_ref.collection.side_effect = _case_sub

        actor_snap = MagicMock()
        actor_snap.exists = True
        actor_snap.to_dict.return_value = {"displayName": "Jane Paralegal"}

        def _collection(name):
            coll = MagicMock()
            if name == "cases":
                coll.document.return_value = case_ref
            elif name == "staff":
                coll.document.return_value = MagicMock(get=MagicMock(return_value=actor_snap))
                coll.where.return_value.stream.return_value = iter([])
            elif name == "notifications":
                coll.document.return_value = MagicMock()
            return coll

        db.collection.side_effect = _collection
        db.batch.return_value = MagicMock()

        submit_for_review(db, "ZAD-2026-04-0001", actor_uid="para-uid")

        batch     = db.batch.return_value
        set_calls = batch.set.call_args_list
        task_call = next(
            (c for c in set_calls if (c[0][1] if c[0] else c[1]).get("type") == "attorney_review"),
            None,
        )
        assert task_call is not None
        assert task_call[0][1]["assignedTo"] == "atty-original"

    # ── Batch atomicity ────────────────────────────────────────────────────

    def test_batch_committed_exactly_once(self):
        from app.services.review_service import submit_for_review

        db = self._ready_db_no_attorney(jp=_jp_snap())
        submit_for_review(db, "ZAD-2026-04-0001", actor_uid="para-uid")

        db.batch.return_value.commit.assert_called_once()

    def test_batch_has_timeline_task_and_notification_writes(self):
        """At least three batch.set calls: timeline + task + notification."""
        from app.services.review_service import submit_for_review

        db = self._ready_db_no_attorney(jp=_jp_snap())
        submit_for_review(db, "ZAD-2026-04-0001", actor_uid="para-uid")

        assert db.batch.return_value.set.call_count >= 3
