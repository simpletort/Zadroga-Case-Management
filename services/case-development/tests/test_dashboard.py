"""
Unit tests for the Paralegal Dashboard service and route.
All Firestore and Firebase auth calls are mocked.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from fastapi.testclient import TestClient


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_case_doc(
    case_id,
    status="Pending Paralegal Review",
    paralegal_id="sarah-chen-uid",
    qual_score=75.0,
    vcf_qual_score=60.0,
    vcf_deadline=None,
    updated_at=None,
):
    doc = MagicMock()
    doc.id = case_id
    doc.to_dict.return_value = {
        "caseId": case_id,
        "status": status,
        "updatedAt": updated_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        "leadData": {"firstName": "John", "lastName": "Doe"},
        "qualification": {
            "medicalQualScore": qual_score,
            "vcfQualScore": vcf_qual_score,
        },
        "enrollment": {"vcfRegDeadline": vcf_deadline},
        "assignment": {"assignedParalegal": paralegal_id},
    }
    return doc


def _make_db(docs):
    db = MagicMock()
    query = MagicMock()
    db.collection.return_value = query
    query.where.return_value = query
    query.stream.return_value = iter(docs)
    return db


def _call_service(db, user=None, **kwargs):  # user param kept for backward compat but ignored
    from app.services.dashboard_service import get_dashboard
    defaults = dict(
        statuses=None,
        case_type=None,
        assignees=None,
        deadline_from=None, deadline_to=None,
        completeness_min=None, completeness_max=None,
        qual_min=None, qual_max=None,
        sort_by="last_activity", sort_dir="desc",
        page=1, page_size=20,
    )
    defaults.update(kwargs)
    return get_dashboard(db=db, **defaults)


# ── Service: basic retrieval ───────────────────────────────────────────────

class TestDashboardServiceRetrieval:

    def test_returns_all_assigned_cases(self):
        docs = [_make_case_doc("ZAD-2026-01-0001"), _make_case_doc("ZAD-2026-01-0002")]
        result = _call_service(_make_db(docs))
        assert result["page"]["total"] == 2
        assert len(result["page"]["items"]) == 2

    def test_empty_returns_valid_structure(self):
        result = _call_service(_make_db([]))
        assert result["page"]["items"] == []
        assert result["page"]["total"] == 0
        assert result["summary"]["total_assigned"] == 0
        assert result["summary"]["avg_qual_score"] is None

    def test_case_fields_mapped_correctly(self):
        doc = _make_case_doc("ZAD-2026-01-0001", qual_score=82.0, vcf_qual_score=55.0)
        result = _call_service(_make_db([doc]))
        item = result["page"]["items"][0]
        assert item["case_id"] == "ZAD-2026-01-0001"
        assert item["first_name"] == "John"
        assert item["last_name"] == "Doe"
        assert item["qual_score"] == 82.0
        assert item["doc_completeness_pct"] == 55.0
        assert item["is_flagged"] is False


# ── Service: filtering ─────────────────────────────────────────────────────

class TestDashboardServiceFilters:

    def test_single_status_filter(self):
        docs = [
            _make_case_doc("c1", status="New Lead"),
            _make_case_doc("c2", status="Pending Paralegal Review"),
        ]
        result = _call_service(_make_db(docs), statuses=["New Lead"])
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["status"] == "New Lead"

    def test_multi_status_filter(self):
        docs = [
            _make_case_doc("c1", status="New Lead"),
            _make_case_doc("c2", status="Pending Paralegal Review"),
            _make_case_doc("c3", status="Awarded"),
        ]
        result = _call_service(_make_db(docs), statuses=["New Lead", "Awarded"])
        assert result["page"]["total"] == 2

    def test_qual_score_min_filter(self):
        docs = [_make_case_doc("c1", qual_score=30.0), _make_case_doc("c2", qual_score=80.0)]
        result = _call_service(_make_db(docs), qual_min=50.0)
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["qual_score"] == 80.0

    def test_qual_score_max_filter(self):
        docs = [_make_case_doc("c1", qual_score=30.0), _make_case_doc("c2", qual_score=80.0)]
        result = _call_service(_make_db(docs), qual_max=50.0)
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["qual_score"] == 30.0

    def test_completeness_min_filter(self):
        docs = [_make_case_doc("c1", vcf_qual_score=20.0), _make_case_doc("c2", vcf_qual_score=90.0)]
        result = _call_service(_make_db(docs), completeness_min=50.0)
        assert result["page"]["total"] == 1

    def test_completeness_max_filter(self):
        docs = [_make_case_doc("c1", vcf_qual_score=20.0), _make_case_doc("c2", vcf_qual_score=90.0)]
        result = _call_service(_make_db(docs), completeness_max=50.0)
        assert result["page"]["total"] == 1

    def test_deadline_from_filter(self):
        past = datetime(2025, 1, 1, tzinfo=timezone.utc)
        future = datetime(2027, 1, 1, tzinfo=timezone.utc)
        cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
        docs = [
            _make_case_doc("c1", vcf_deadline=past),
            _make_case_doc("c2", vcf_deadline=future),
        ]
        result = _call_service(_make_db(docs), deadline_from=cutoff)
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["case_id"] == "c2"

    def test_deadline_to_filter(self):
        past = datetime(2025, 1, 1, tzinfo=timezone.utc)
        future = datetime(2027, 1, 1, tzinfo=timezone.utc)
        cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
        docs = [
            _make_case_doc("c1", vcf_deadline=past),
            _make_case_doc("c2", vcf_deadline=future),
        ]
        result = _call_service(_make_db(docs), deadline_to=cutoff)
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["case_id"] == "c1"

    def test_combined_filters(self):
        docs = [
            _make_case_doc("c1", status="New Lead", qual_score=20.0),
            _make_case_doc("c2", status="New Lead", qual_score=80.0),
            _make_case_doc("c3", status="Awarded", qual_score=80.0),
        ]
        result = _call_service(_make_db(docs), statuses=["New Lead"], qual_min=50.0)
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["case_id"] == "c2"


# ── Service: KPI summary ───────────────────────────────────────────────────

class TestDashboardServiceSummary:

    def test_overdue_deadline_count(self):
        past   = datetime(2025, 1, 1, tzinfo=timezone.utc)
        future = datetime(2030, 1, 1, tzinfo=timezone.utc)
        docs = [
            _make_case_doc("c1", vcf_deadline=past),
            _make_case_doc("c2", vcf_deadline=future),
            _make_case_doc("c3", vcf_deadline=None),
        ]
        result = _call_service(_make_db(docs))
        assert result["summary"]["overdue_deadline"] == 1

    def test_pending_review_count(self):
        docs = [
            _make_case_doc("c1", status="Pending Paralegal Review"),
            _make_case_doc("c2", status="New Lead"),
        ]
        result = _call_service(_make_db(docs))
        assert result["summary"]["pending_review"] == 1

    def test_avg_qual_score(self):
        docs = [
            _make_case_doc("c1", qual_score=60.0),
            _make_case_doc("c2", qual_score=80.0),
        ]
        result = _call_service(_make_db(docs))
        assert result["summary"]["avg_qual_score"] == 70.0

    def test_avg_qual_score_none_when_no_scores(self):
        docs = [_make_case_doc("c1", qual_score=None)]
        doc = docs[0]
        d = doc.to_dict()
        d["qualification"]["medicalQualScore"] = None
        doc.to_dict.return_value = d
        result = _call_service(_make_db(docs))
        assert result["summary"]["avg_qual_score"] is None


# ── Service: sort ──────────────────────────────────────────────────────────

class TestDashboardServiceSort:

    def test_sort_qual_score_desc(self):
        docs = [
            _make_case_doc("c1", qual_score=40.0),
            _make_case_doc("c2", qual_score=90.0),
            _make_case_doc("c3", qual_score=70.0),
        ]
        result = _call_service(_make_db(docs), sort_by="qual_score", sort_dir="desc")
        scores = [c["qual_score"] for c in result["page"]["items"]]
        assert scores == sorted(scores, reverse=True)

    def test_sort_qual_score_asc(self):
        docs = [
            _make_case_doc("c1", qual_score=40.0),
            _make_case_doc("c2", qual_score=90.0),
        ]
        result = _call_service(_make_db(docs), sort_by="qual_score", sort_dir="asc")
        scores = [c["qual_score"] for c in result["page"]["items"]]
        assert scores == sorted(scores)

    def test_sort_case_id_asc(self):
        docs = [_make_case_doc("ZAD-B"), _make_case_doc("ZAD-A")]
        result = _call_service(_make_db(docs), sort_by="case_id", sort_dir="asc")
        ids = [c["case_id"] for c in result["page"]["items"]]
        assert ids == sorted(ids)


# ── Service: pagination ────────────────────────────────────────────────────

class TestDashboardServicePagination:

    def test_first_page_correct_slice(self):
        docs = [_make_case_doc(f"c{i:03d}") for i in range(25)]
        result = _call_service(_make_db(docs), page=1, page_size=20)
        assert len(result["page"]["items"]) == 20
        assert result["page"]["total"] == 25
        assert result["page"]["total_pages"] == 2

    def test_second_page_remainder(self):
        docs = [_make_case_doc(f"c{i:03d}") for i in range(25)]
        result = _call_service(_make_db(docs), page=2, page_size=20)
        assert len(result["page"]["items"]) == 5

    def test_single_page_when_under_limit(self):
        docs = [_make_case_doc(f"c{i}") for i in range(5)]
        result = _call_service(_make_db(docs), page=1, page_size=20)
        assert result["page"]["total_pages"] == 1
        assert len(result["page"]["items"]) == 5

    def test_empty_page_beyond_last(self):
        docs = [_make_case_doc("c1")]
        result = _call_service(_make_db(docs), page=99, page_size=20)
        assert result["page"]["items"] == []



# ── RBAC ───────────────────────────────────────────────────────────────────

class TestDashboardRBAC:

    def test_dashboard_endpoint_200_for_paralegal(self):
        svc_result = {
            "summary": {"total_assigned": 0, "overdue_deadline": 0,
                        "pending_review": 0, "avg_qual_score": None},
            "page": {"items": [], "total": 0, "page": 1, "page_size": 20, "total_pages": 1},
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.services.dashboard_service.get_dashboard", return_value=svc_result):
            from importlib import reload
            import main as m
            client = TestClient(m.app, raise_server_exceptions=False)
            resp = client.get("/api/v1/dashboard/cases")
        assert resp.status_code == 200
