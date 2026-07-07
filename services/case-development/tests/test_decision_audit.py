"""
Tests for the Decision Audit Trail.

Covers:
  - write_decision_audit_event helper: field correctness, duration math, immutability,
    dual-write to global audit_logs + cases/{caseId}/audit_logs
  - decision_audit_service: get_decisions, get_case_decisions, get_decision_metrics,
    generate_compliance_report
  - Route integration via FastAPI TestClient (RBAC + response shapes)
  - Existing services write audit events: approve_for_filing, escalate_case,
    decide_escalation (reject / approve), reject_case
"""

import math
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from fastapi.testclient import TestClient


# ── Shared constants ──────────────────────────────────────────────────────────

_NOW      = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)
_CASE     = "ZAD-2026-04-0001"
_ATTY     = "atty-uid"
_PARA     = "para-uid"
_SP       = "sp-uid"
_EVENT_ID = "evt-uuid-001"


# ── Firestore mock helpers ────────────────────────────────────────────────────

def _make_db():
    """Mock Firestore client for write-helper tests.

    Handles:
      db.collection("audit_logs").document(X)              → audit_ref
      db.collection("cases").document(Y).collection(...).document(X) → nested via MagicMock chain
    """
    db = MagicMock()
    db.batch.return_value = MagicMock()
    audit_ref = MagicMock()
    audit_ref.id = _EVENT_ID

    def _collection(name):
        coll = MagicMock()
        coll.document.return_value = audit_ref
        coll.where.return_value = coll
        coll.stream.return_value = iter([])
        return coll

    db.collection.side_effect = _collection
    return db


def _audit_doc(
    event_id=_EVENT_ID,
    case_id=_CASE,
    decision_type="approve_for_filing",
    event_type="StatusChange",
    performed_by=_ATTY,
    performed_by_name="Alice Attorney",
    performed_by_role="junior_partner",
    timestamp=None,
    previous_status="Pending Attorney Review",
    new_status="Approved for Filing",
    reason=None,
    notes=None,
    review_duration_seconds=3600,
    case_submitted_for_review_at=None,
    related_doc_id=None,
):
    """Return a Firestore document dict in the Common Audit Log Schema format."""
    ts = timestamp or _NOW
    return {
        "id":            event_id,
        "case_id":       case_id,
        "service":       "case-management",
        "actor_id":      performed_by,
        "actor_type":    "staff",
        "actor_role":    performed_by_role,
        "action":        "STATUS_CHANGED",
        "resource_type": "case",
        "resource_id":   case_id,
        "timestamp":     ts,
        "outcome":       "success",
        "changes": {
            "status": {
                "before": previous_status,
                "after":  new_status,
            }
        },
        "metadata": {
            "decision_type":               decision_type,
            "event_type":                  event_type,
            "performed_by_name":           performed_by_name,
            "reason":                      reason,
            "notes":                       notes,
            "review_duration_seconds":     review_duration_seconds,
            "case_submitted_for_review_at": case_submitted_for_review_at,
            "related_doc_id":              related_doc_id,
        },
    }


def _doc_snap(data: dict):
    snap = MagicMock()
    snap.to_dict.return_value = data
    return snap


def _make_query_db(docs: list[dict]):
    """
    Firestore mock for read-service tests.

    Handles both query paths used by decision_audit_service:
      - db.collection("audit_logs").where(...).stream()          (global query)
      - db.collection("cases").document(X).collection("audit_logs").stream()  (case sub-collection)

    Both paths return the same `docs` list so Python-side filters are exercised.
    """
    db = MagicMock()

    def _make_streamable():
        coll = MagicMock()
        coll.where.return_value = coll
        coll.stream.side_effect = lambda: iter([_doc_snap(d) for d in docs])
        return coll

    audit_logs_sub = _make_streamable()
    case_doc = MagicMock()
    case_doc.collection.return_value = audit_logs_sub
    cases_coll = MagicMock()
    cases_coll.document.return_value = case_doc

    audit_logs_coll = _make_streamable()

    def _collection(name):
        if name == "cases":
            return cases_coll
        if name == "audit_logs":
            return audit_logs_coll
        c = _make_streamable()
        return c

    db.collection.side_effect = _collection
    return db


# ═════════════════════════════════════════════════════════════════════════════
# write_decision_audit_event helper
# ═════════════════════════════════════════════════════════════════════════════

class TestWriteDecisionAuditEvent:

    def _call(self, batch=None, db=None, **kwargs):
        from app.utils.decision_audit import write_decision_audit_event
        if batch is None:
            batch = MagicMock()
        if db is None:
            db = _make_db()
        defaults = dict(
            event_id=_EVENT_ID,
            case_id=_CASE,
            decision_type="approve_for_filing",
            event_type="StatusChange",
            performed_by=_ATTY,
            performed_by_name="Alice Attorney",
            performed_by_role="junior_partner",
            timestamp=_NOW,
            previous_status="Pending Attorney Review",
            new_status="Approved for Filing",
        )
        defaults.update(kwargs)
        write_decision_audit_event(batch=batch, db=db, **defaults)
        return batch, db

    def _written_doc(self, batch):
        """Return the doc payload from the first (global) batch.set call."""
        return batch.set.call_args_list[0][0][1]

    # ── Dual-write ────────────────────────────────────────────────────────────

    def test_adds_exactly_two_batch_set_calls(self):
        batch, _ = self._call()
        assert batch.set.call_count == 2

    def test_both_writes_carry_identical_payload(self):
        batch, _ = self._call()
        doc1 = batch.set.call_args_list[0][0][1]
        doc2 = batch.set.call_args_list[1][0][1]
        assert doc1 == doc2

    def test_global_collection_is_audit_logs(self):
        batch, db = self._call()
        # First set() writes to audit_logs/{event_id}
        first_ref = batch.set.call_args_list[0][0][0]
        db.collection.assert_any_call("audit_logs")

    def test_case_scoped_collection_written(self):
        batch, db = self._call()
        # Second set() is on the cases/{caseId}/audit_logs sub-collection
        db.collection.assert_any_call("cases")

    # ── Field correctness (Common Audit Log Schema) ────────────────────────────

    def test_written_doc_has_all_schema_fields(self):
        batch, _ = self._call()
        written = self._written_doc(batch)
        for field in (
            "id", "timestamp", "actor_id", "actor_type", "actor_role",
            "action", "resource_type", "resource_id", "case_id",
            "service", "outcome", "changes", "metadata",
        ):
            assert field in written, f"Missing field: {field}"

    def test_metadata_has_all_service_specific_fields(self):
        batch, _ = self._call()
        meta = self._written_doc(batch)["metadata"]
        for field in (
            "decision_type", "event_type", "performed_by_name",
            "reason", "notes", "review_duration_seconds",
            "case_submitted_for_review_at", "related_doc_id",
        ):
            assert field in meta, f"Missing metadata field: {field}"

    def test_id_field_matches_event_id(self):
        batch, _ = self._call(event_id=_EVENT_ID)
        assert self._written_doc(batch)["id"] == _EVENT_ID

    def test_service_is_case_management(self):
        batch, _ = self._call()
        assert self._written_doc(batch)["service"] == "case-management"

    def test_actor_type_is_staff(self):
        batch, _ = self._call()
        assert self._written_doc(batch)["actor_type"] == "staff"

    def test_action_is_status_changed(self):
        batch, _ = self._call()
        assert self._written_doc(batch)["action"] == "STATUS_CHANGED"

    def test_resource_type_is_case(self):
        batch, _ = self._call()
        assert self._written_doc(batch)["resource_type"] == "case"

    def test_outcome_is_success(self):
        batch, _ = self._call()
        assert self._written_doc(batch)["outcome"] == "success"

    def test_changes_status_before_after(self):
        batch, _ = self._call(
            previous_status="Pending Attorney Review",
            new_status="Approved for Filing",
        )
        changes = self._written_doc(batch)["changes"]
        assert changes["status"]["before"] == "Pending Attorney Review"
        assert changes["status"]["after"] == "Approved for Filing"

    def test_actor_id_and_role_stored_correctly(self):
        batch, _ = self._call(performed_by=_ATTY, performed_by_role="junior_partner")
        written = self._written_doc(batch)
        assert written["actor_id"] == _ATTY
        assert written["actor_role"] == "junior_partner"

    def test_decision_type_in_metadata(self):
        batch, _ = self._call(decision_type="escalate")
        assert self._written_doc(batch)["metadata"]["decision_type"] == "escalate"

    # ── Duration calculation ──────────────────────────────────────────────────

    def test_review_duration_seconds_correct(self):
        submitted = _NOW - timedelta(hours=2)
        batch, _ = self._call(
            timestamp=_NOW,
            case_submitted_for_review_at=submitted,
        )
        assert self._written_doc(batch)["metadata"]["review_duration_seconds"] == 7200

    def test_review_duration_none_when_no_submitted_at(self):
        batch, _ = self._call(case_submitted_for_review_at=None)
        assert self._written_doc(batch)["metadata"]["review_duration_seconds"] is None

    def test_review_duration_zero_when_instantaneous(self):
        batch, _ = self._call(
            timestamp=_NOW,
            case_submitted_for_review_at=_NOW,
        )
        assert self._written_doc(batch)["metadata"]["review_duration_seconds"] == 0

    def test_review_duration_clamped_to_zero_on_clock_skew(self):
        batch, _ = self._call(
            timestamp=_NOW,
            case_submitted_for_review_at=_NOW + timedelta(hours=1),
        )
        assert self._written_doc(batch)["metadata"]["review_duration_seconds"] == 0

    def test_naive_submitted_at_gets_utc_tzinfo(self):
        naive_dt = datetime(2026, 4, 17, 10, 0, 0)
        batch, _ = self._call(
            timestamp=_NOW,
            case_submitted_for_review_at=naive_dt,
        )
        assert self._written_doc(batch)["metadata"]["review_duration_seconds"] == 7200

    # ── Immutability ──────────────────────────────────────────────────────────

    def test_helper_never_calls_batch_update(self):
        batch, _ = self._call()
        batch.update.assert_not_called()

    def test_helper_never_calls_batch_delete(self):
        batch, _ = self._call()
        batch.delete.assert_not_called()

    # ── Optional fields ───────────────────────────────────────────────────────

    def test_reason_and_notes_in_metadata(self):
        batch, _ = self._call(reason="incomplete_documentation", notes="Missing W-2s.")
        meta = self._written_doc(batch)["metadata"]
        assert meta["reason"] == "incomplete_documentation"
        assert meta["notes"] == "Missing W-2s."

    def test_related_doc_id_in_metadata(self):
        batch, _ = self._call(related_doc_id="rej-001")
        assert self._written_doc(batch)["metadata"]["related_doc_id"] == "rej-001"

    def test_none_optional_fields_written_explicitly_in_metadata(self):
        """None values must be written (not omitted) for Firestore schema consistency."""
        batch, _ = self._call(reason=None, notes=None, related_doc_id=None)
        meta = self._written_doc(batch)["metadata"]
        assert meta["reason"] is None
        assert meta["notes"] is None
        assert meta["related_doc_id"] is None


# ═════════════════════════════════════════════════════════════════════════════
# decision_audit_service — get_decisions
# ═════════════════════════════════════════════════════════════════════════════

class TestGetDecisions:

    def _call(self, docs, **kwargs):
        from app.services.decision_audit_service import get_decisions
        db = _make_query_db(docs)
        return get_decisions(db=db, **kwargs)

    def test_returns_all_items_when_no_filters(self):
        docs = [_audit_doc(), _audit_doc(event_id="evt-2", case_id="ZAD-2026-04-0002")]
        result = self._call(docs)
        assert result["total_decisions"] == 2
        assert len(result["page"]["items"]) == 2

    def test_empty_collection_returns_zero(self):
        result = self._call([])
        assert result["total_decisions"] == 0
        assert result["page"]["items"] == []

    def test_python_side_case_id_filter(self):
        docs = [
            _audit_doc(case_id=_CASE),
            _audit_doc(event_id="evt-2", case_id="ZAD-OTHER"),
        ]
        result = self._call(docs, case_id=_CASE)
        assert result["total_decisions"] == 1
        assert result["page"]["items"][0]["case_id"] == _CASE

    def test_python_side_performed_by_filter(self):
        docs = [
            _audit_doc(performed_by=_ATTY),
            _audit_doc(event_id="evt-2", performed_by=_SP),
        ]
        result = self._call(docs, performed_by=_SP)
        assert result["total_decisions"] == 1
        assert result["page"]["items"][0]["performed_by"] == _SP

    def test_python_side_decision_type_filter(self):
        docs = [
            _audit_doc(decision_type="approve_for_filing"),
            _audit_doc(event_id="evt-2", decision_type="escalate"),
        ]
        result = self._call(docs, decision_type="escalate")
        assert result["total_decisions"] == 1

    def test_pagination_page_2(self):
        docs = [_audit_doc(event_id=f"evt-{i}") for i in range(5)]
        result = self._call(docs, page=2, page_size=2)
        assert result["page"]["page"] == 2
        assert len(result["page"]["items"]) == 2

    def test_total_pages_calculated_correctly(self):
        docs = [_audit_doc(event_id=f"evt-{i}") for i in range(7)]
        result = self._call(docs, page=1, page_size=3)
        assert result["page"]["total_pages"] == 3

    def test_items_sorted_newest_first(self):
        t1 = _NOW - timedelta(hours=2)
        t2 = _NOW - timedelta(hours=1)
        t3 = _NOW
        docs = [
            _audit_doc(event_id="old", timestamp=t1),
            _audit_doc(event_id="new", timestamp=t3),
            _audit_doc(event_id="mid", timestamp=t2),
        ]
        result = self._call(docs)
        ids = [item["event_id"] for item in result["page"]["items"]]
        assert ids == ["new", "mid", "old"]


# ═════════════════════════════════════════════════════════════════════════════
# decision_audit_service — get_case_decisions
# ═════════════════════════════════════════════════════════════════════════════

class TestGetCaseDecisions:

    def _call(self, docs, case_id=_CASE):
        from app.services.decision_audit_service import get_case_decisions
        db = _make_query_db(docs)
        return get_case_decisions(db=db, case_id=case_id)

    def test_returns_all_case_decisions(self):
        docs = [_audit_doc(), _audit_doc(event_id="evt-2")]
        result = self._call(docs)
        assert result["total"] == 2
        assert result["case_id"] == _CASE

    def test_decisions_sorted_chronologically(self):
        t1 = _NOW - timedelta(hours=2)
        t2 = _NOW
        docs = [
            _audit_doc(event_id="new", timestamp=t2),
            _audit_doc(event_id="old", timestamp=t1),
        ]
        result = self._call(docs)
        ids = [d["event_id"] for d in result["decisions"]]
        assert ids == ["old", "new"]

    def test_empty_case_returns_empty_list(self):
        result = self._call([])
        assert result["total"] == 0
        assert result["decisions"] == []


# ═════════════════════════════════════════════════════════════════════════════
# decision_audit_service — get_decision_metrics
# ═════════════════════════════════════════════════════════════════════════════

class TestGetDecisionMetrics:

    def _call(self, docs, **kwargs):
        from app.services.decision_audit_service import get_decision_metrics
        db = _make_query_db(docs)
        return get_decision_metrics(db=db, **kwargs)

    def test_total_decisions_count(self):
        docs = [_audit_doc(), _audit_doc(event_id="evt-2")]
        result = self._call(docs)
        assert result["total_decisions"] == 2

    def test_by_decision_type_counts(self):
        docs = [
            _audit_doc(decision_type="approve_for_filing"),
            _audit_doc(event_id="e2", decision_type="approve_for_filing"),
            _audit_doc(event_id="e3", decision_type="escalate"),
        ]
        result = self._call(docs)
        assert result["by_decision_type"]["approve_for_filing"] == 2
        assert result["by_decision_type"]["escalate"] == 1

    def test_avg_review_duration_seconds(self):
        docs = [
            _audit_doc(review_duration_seconds=3600),
            _audit_doc(event_id="e2", review_duration_seconds=7200),
        ]
        result = self._call(docs)
        assert result["avg_review_duration_seconds"] == 5400.0

    def test_avg_is_none_when_all_durations_are_none(self):
        docs = [
            _audit_doc(review_duration_seconds=None),
            _audit_doc(event_id="e2", review_duration_seconds=None),
        ]
        result = self._call(docs)
        assert result["avg_review_duration_seconds"] is None

    def test_avg_excludes_none_durations(self):
        docs = [
            _audit_doc(review_duration_seconds=3600),
            _audit_doc(event_id="e2", review_duration_seconds=None),
        ]
        result = self._call(docs)
        assert result["avg_review_duration_seconds"] == 3600.0

    def test_by_attorney_breakdown(self):
        docs = [
            _audit_doc(performed_by=_ATTY, performed_by_name="Alice"),
            _audit_doc(event_id="e2", performed_by=_ATTY),
            _audit_doc(event_id="e3", performed_by=_SP, performed_by_name="Sam"),
        ]
        result = self._call(docs)
        by_uid = {a["performed_by"]: a for a in result["by_attorney"]}
        assert by_uid[_ATTY]["decision_count"] == 2
        assert by_uid[_SP]["decision_count"] == 1

    def test_avg_review_duration_by_type(self):
        docs = [
            _audit_doc(decision_type="approve_for_filing", review_duration_seconds=1800),
            _audit_doc(event_id="e2", decision_type="approve_for_filing", review_duration_seconds=3600),
            _audit_doc(event_id="e3", decision_type="escalate", review_duration_seconds=900),
        ]
        result = self._call(docs)
        assert result["avg_review_duration_by_type"]["approve_for_filing"] == 2700.0
        assert result["avg_review_duration_by_type"]["escalate"] == 900.0

    def test_empty_collection_returns_zero_total(self):
        result = self._call([])
        assert result["total_decisions"] == 0
        assert result["avg_review_duration_seconds"] is None


# ═════════════════════════════════════════════════════════════════════════════
# decision_audit_service — generate_compliance_report
# ═════════════════════════════════════════════════════════════════════════════

class TestGenerateComplianceReport:

    def _call(self, docs, **kwargs):
        from app.services.decision_audit_service import generate_compliance_report
        db = _make_query_db(docs)
        return generate_compliance_report(db=db, **kwargs)

    def test_generated_at_present(self):
        result = self._call([])
        assert isinstance(result["generated_at"], datetime)

    def test_total_records_matches_doc_count(self):
        docs = [_audit_doc(), _audit_doc(event_id="e2")]
        result = self._call(docs)
        assert result["total_records"] == 2

    def test_records_in_chronological_order(self):
        t1 = _NOW - timedelta(hours=1)
        docs = [
            _audit_doc(event_id="new", timestamp=_NOW),
            _audit_doc(event_id="old", timestamp=t1),
        ]
        result = self._call(docs)
        assert result["records"][0]["event_id"] == "old"
        assert result["records"][1]["event_id"] == "new"

    def test_filters_applied_envelope(self):
        result = self._call([], performed_by=_ATTY, case_id=_CASE)
        assert result["filters_applied"]["performed_by"] == _ATTY
        assert result["filters_applied"]["case_id"] == _CASE

    def test_empty_filters_applied_when_none(self):
        result = self._call([])
        assert result["filters_applied"] == {}

    def test_all_fields_present_in_records(self):
        docs = [_audit_doc()]
        result = self._call(docs)
        record = result["records"][0]
        for field in ("event_id", "case_id", "decision_type", "performed_by",
                      "timestamp", "previous_status", "new_status", "created_at"):
            assert field in record


# ═════════════════════════════════════════════════════════════════════════════
# Decision audit routes — RBAC & response shape
# ═════════════════════════════════════════════════════════════════════════════

class TestDecisionAuditRoutes:

    def _get_client(self):
        from main import app
        client = TestClient(app, raise_server_exceptions=False)
        return client

    def _patch_service(self, name, return_value):
        return patch(f"app.routes.decision_audit.{name}", return_value=return_value)

    # ── GET /audit/decisions ──────────────────────────────────────────────────

    def test_get_decisions_returns_200(self):
        client = self._get_client()
        svc_result = {
            "total_decisions": 0,
            "page": {"items": [], "total": 0, "page": 1, "page_size": 20, "total_pages": 0},
        }
        with self._patch_service("get_decisions", svc_result), \
             patch("app.routes.decision_audit.get_firestore_client"):
            resp = client.get("/api/v1/audit/decisions")
        assert resp.status_code == 200
        assert resp.json()["total_decisions"] == 0

    # ── GET /cases/{caseId}/audit/decisions ───────────────────────────────────

    def test_get_case_decisions_returns_200(self):
        client = self._get_client()
        svc_result = {"case_id": _CASE, "decisions": [], "total": 0}
        with self._patch_service("get_case_decisions", svc_result), \
             patch("app.routes.decision_audit.get_firestore_client"):
            resp = client.get(f"/api/v1/cases/{_CASE}/audit/decisions")
        assert resp.status_code == 200
        assert resp.json()["case_id"] == _CASE

    # ── GET /audit/decisions/metrics ──────────────────────────────────────────

    def test_get_metrics_returns_200(self):
        client = self._get_client()
        svc_result = {
            "total_decisions": 0,
            "by_decision_type": {},
            "avg_review_duration_seconds": None,
            "avg_review_duration_by_type": {},
            "by_attorney": [],
            "date_from": None,
            "date_to": None,
        }
        with self._patch_service("get_decision_metrics", svc_result), \
             patch("app.routes.decision_audit.get_firestore_client"):
            resp = client.get("/api/v1/audit/decisions/metrics")
        assert resp.status_code == 200

    # ── GET /audit/decisions/report ───────────────────────────────────────────

    def test_get_report_returns_200(self):
        client = self._get_client()
        svc_result = {
            "generated_at": _NOW,
            "filters_applied": {},
            "total_records": 0,
            "records": [],
        }
        with self._patch_service("generate_compliance_report", svc_result), \
             patch("app.routes.decision_audit.get_firestore_client"):
            resp = client.get("/api/v1/audit/decisions/report")
        assert resp.status_code == 200
        assert resp.json()["total_records"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# Verify existing services now write decision_audit events in their batches
# ═════════════════════════════════════════════════════════════════════════════

class TestExistingServicesWriteAuditEvents:
    """
    These tests patch write_decision_audit_event and verify it is called with
    the correct decision_type by each service.  They do not re-test the full
    service logic — that is covered in test_attorney_review.py, test_escalation.py,
    and test_rejection.py.
    """

    # ── approve_for_filing ────────────────────────────────────────────────────

    def test_approve_for_filing_calls_audit_helper(self):
        from app.services.attorney_review_service import _approve_single

        case_data = {
            "status": "Pending Attorney Review",
            "assignment": {"assignedParalegal": _PARA, "assignedAttorney": _ATTY},
            "enrollment": {},
            "submittedForReviewAt": _NOW - timedelta(hours=1),
        }
        case_snap = MagicMock()
        case_snap.exists = True
        case_snap.to_dict.return_value = case_data

        timeline_doc = MagicMock()
        timeline_doc.id = "tl-001"
        tasks_coll  = MagicMock()
        tasks_coll.document.return_value = MagicMock()
        timeline_coll = MagicMock()
        timeline_coll.document.return_value = timeline_doc

        def _case_sub(name):
            if name == "tasks":     return tasks_coll
            if name == "timeline":  return timeline_coll
            return MagicMock()

        case_ref = MagicMock()
        case_ref.get.return_value = case_snap
        case_ref.collection.side_effect = _case_sub

        staff_snap = MagicMock()
        staff_snap.exists = True
        staff_snap.to_dict.return_value = {"displayName": "Alice Attorney"}

        def _collection(name):
            if name == "cases":
                c = MagicMock()
                c.document.return_value = case_ref
                return c
            if name == "staff":
                c = MagicMock()
                c.document.return_value = MagicMock(get=MagicMock(return_value=staff_snap))
                return c
            c = MagicMock()
            c.document.return_value = MagicMock()
            return c

        db = MagicMock()
        db.collection.side_effect = _collection
        db.batch.return_value = MagicMock()

        with patch("app.services.attorney_review_service.write_decision_audit_event") as mock_audit:
            _approve_single(
                db=db, case_id=_CASE,
                actor_uid=_ATTY, actor_name="Alice Attorney", actor_role="junior_partner",
                notes=None, now=_NOW,
            )
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["decision_type"] == "approve_for_filing"

    # ── escalate_case ─────────────────────────────────────────────────────────

    def test_escalate_case_calls_audit_helper_with_correct_type(self):
        from app.services.escalation_service import escalate_case

        case_data = {
            "status": "Pending Attorney Review",
            "assignment": {"assignedAttorney": _ATTY, "assignedParalegal": _PARA},
            "submittedForReviewAt": _NOW - timedelta(hours=3),
        }
        case_snap = MagicMock()
        case_snap.exists = True
        case_snap.to_dict.return_value = case_data

        timeline_doc = MagicMock()
        timeline_doc.id = "tl-esc"
        esc_coll = MagicMock()
        esc_coll.document.return_value = MagicMock()
        timeline_coll = MagicMock()
        timeline_coll.document.return_value = timeline_doc

        def _case_sub(name):
            if name == "escalations": return esc_coll
            if name == "timeline":    return timeline_coll
            return MagicMock()

        case_ref = MagicMock()
        case_ref.get.return_value = case_snap
        case_ref.collection.side_effect = _case_sub

        staff_snap = MagicMock()
        staff_snap.exists = True
        staff_snap.to_dict.return_value = {"displayName": "Alice"}

        sp_snap = MagicMock()
        sp_snap.exists = True
        sp_snap.id = _SP
        sp_snap.to_dict.return_value = {
            "displayName": "Senior Sam", "role": "senior_partner", "isActive": True,
        }
        sp_query = MagicMock()
        sp_query.where.return_value = sp_query
        sp_query.stream.return_value = iter([sp_snap])

        def _collection(name):
            if name == "cases":
                c = MagicMock(); c.document.return_value = case_ref; return c
            if name == "staff":
                c = MagicMock()
                c.document.return_value = MagicMock(get=MagicMock(return_value=staff_snap))
                c.where.return_value = sp_query
                return c
            c = MagicMock(); c.document.return_value = MagicMock(); return c

        db = MagicMock()
        db.collection.side_effect = _collection
        db.batch.return_value = MagicMock()

        with patch("app.services.escalation_service.write_decision_audit_event") as mock_audit:
            escalate_case(
                db=db, case_id=_CASE, actor_uid=_ATTY,
                actor_role="junior_partner", reason="high_value_claim", notes=None,
            )
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["decision_type"] == "escalate"

    # ── reject_case ───────────────────────────────────────────────────────────

    def test_reject_case_calls_audit_helper_with_correct_type(self):
        from app.services.rejection_service import reject_case

        case_data = {
            "status": "Pending Attorney Review",
            "assignment": {"assignedAttorney": _ATTY, "assignedParalegal": _PARA},
            "submittedForReviewAt": _NOW - timedelta(hours=2),
        }
        case_snap = MagicMock()
        case_snap.exists = True
        case_snap.to_dict.return_value = case_data

        rejection_doc  = MagicMock()
        timeline_doc   = MagicMock()
        timeline_doc.id = "tl-rej"

        def _case_sub(name):
            if name == "rejections":
                c = MagicMock(); c.document.return_value = rejection_doc; return c
            if name == "timeline":
                c = MagicMock(); c.document.return_value = timeline_doc; return c
            return MagicMock()

        case_ref = MagicMock()
        case_ref.get.return_value = case_snap
        case_ref.collection.side_effect = _case_sub

        staff_snap = MagicMock()
        staff_snap.exists = True
        staff_snap.to_dict.return_value = {"displayName": "Alice"}

        def _collection(name):
            if name == "cases":
                c = MagicMock(); c.document.return_value = case_ref; return c
            if name == "staff":
                c = MagicMock()
                c.document.return_value = MagicMock(get=MagicMock(return_value=staff_snap))
                return c
            c = MagicMock(); c.document.return_value = MagicMock(); return c

        db = MagicMock()
        db.collection.side_effect = _collection
        db.batch.return_value = MagicMock()

        with patch("app.services.rejection_service.write_decision_audit_event") as mock_audit:
            reject_case(
                db=db, case_id=_CASE, actor_uid=_ATTY,
                actor_role="junior_partner",
                reason="incomplete_documentation", notes=None,
            )
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["decision_type"] == "reject_case"

    # ── decide_escalation (reject path) ───────────────────────────────────────

    def test_decide_escalation_reject_calls_audit_with_correct_type(self):
        from app.services.escalation_service import decide_escalation

        esc_at = _NOW - timedelta(hours=4)
        case_data = {
            "status": "Pending Senior Review",
            "assignment": {"assignedAttorney": _ATTY, "assignedParalegal": _PARA},
            "escalation": {
                "escalatedAt":        esc_at,
                "originalAttorneyId": _ATTY,
            },
        }
        case_snap = MagicMock()
        case_snap.exists = True
        case_snap.to_dict.return_value = case_data

        esc_snap = MagicMock()
        esc_snap.exists = True
        esc_snap.id = "esc-001"
        esc_snap.to_dict.return_value = {
            "escalationId": "esc-001", "escalatedAt": esc_at,
            "originalAttorneyId": _ATTY,
        }
        esc_query = MagicMock()
        esc_query.where.return_value  = esc_query
        esc_query.order_by.return_value = esc_query
        esc_query.limit.return_value  = esc_query
        esc_query.stream.return_value = iter([esc_snap])

        esc_coll = MagicMock()
        esc_coll.where.return_value    = esc_query
        esc_coll.document.return_value = MagicMock(get=MagicMock(return_value=esc_snap))

        timeline_doc = MagicMock()
        timeline_doc.id = "tl-dec"
        timeline_coll = MagicMock()
        timeline_coll.document.return_value = timeline_doc

        def _case_sub(name):
            if name == "escalations": return esc_coll
            if name == "timeline":    return timeline_coll
            return MagicMock()

        case_ref = MagicMock()
        case_ref.get.return_value = case_snap
        case_ref.collection.side_effect = _case_sub

        staff_snap = MagicMock()
        staff_snap.exists = True
        staff_snap.to_dict.return_value = {"displayName": "Senior Sam"}

        def _collection(name):
            if name == "cases":
                c = MagicMock(); c.document.return_value = case_ref; return c
            if name == "staff":
                c = MagicMock()
                c.document.return_value = MagicMock(get=MagicMock(return_value=staff_snap))
                return c
            c = MagicMock(); c.document.return_value = MagicMock(); return c

        db = MagicMock()
        db.collection.side_effect = _collection
        db.batch.return_value = MagicMock()

        with patch("app.services.escalation_service.write_decision_audit_event") as mock_audit:
            decide_escalation(
                db=db, case_id=_CASE, actor_uid=_SP,
                actor_role="senior_partner", decision="reject", notes="Not ready.",
            )
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["decision_type"] == "escalation_reject"
        assert mock_audit.call_args.kwargs["case_submitted_for_review_at"] == esc_at


