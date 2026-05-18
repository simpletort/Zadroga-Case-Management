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
    updated_at=None,
):
    doc = MagicMock()
    doc.id = case_id
    score = int(qual_score) if qual_score is not None else None
    doc.to_dict.return_value = {
        "caseId":    case_id,
        "status":    status,
        "updatedAt": updated_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        "firstName": "John",
        "lastName":  "Doe",
        "vcfScreeningDetails": {"score": score},
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
        doc = _make_case_doc("ZAD-2026-01-0001", qual_score=82.0)
        result = _call_service(_make_db([doc]))
        item = result["page"]["items"][0]
        assert item["case_id"] == "ZAD-2026-01-0001"
        assert item["first_name"] == "John"
        assert item["last_name"] == "Doe"
        assert item["qual_score"] == 82.0
        assert item["doc_completeness_pct"] is None
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
        docs = [_make_case_doc("c1"), _make_case_doc("c2"), _make_case_doc("c3")]
        result = _call_service(_make_db(docs))
        assert result["summary"]["overdue_deadline"] == 0

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


# ── Helpers for single-doc tests ───────────────────────────────────────────

def _make_single_doc(case_id, exists=True, **kwargs):
    doc = _make_case_doc(case_id, **kwargs)
    doc.exists = exists
    return doc


def _make_single_db(doc):
    db = MagicMock()
    db.collection.return_value.document.return_value.get.return_value = doc
    return db


# ── Service: get_case_detail ───────────────────────────────────────────────

class TestGetCaseDetail:

    def test_returns_none_when_not_found(self):
        from app.services.dashboard_service import get_case_detail
        doc = MagicMock()
        doc.exists = False
        assert get_case_detail(_make_single_db(doc), "ZAD-MISSING") is None

    def test_returns_correct_fields(self):
        from app.services.dashboard_service import get_case_detail
        doc = _make_single_doc(
            "ZAD-2026-01-0001",
            qual_score=72.0,
            paralegal_id="uid-p1",
        )
        result = get_case_detail(_make_single_db(doc), "ZAD-2026-01-0001")
        assert result is not None
        assert result["case_id"] == "ZAD-2026-01-0001"
        assert result["first_name"] == "John"
        assert result["last_name"] == "Doe"
        assert result["qual_score"] == 72.0
        assert result["doc_completeness_pct"] is None
        assert result["vcf_deadline"] is None
        assert result["assigned_paralegal"] == "uid-p1"
        assert result["is_flagged"] is False

    def test_naive_datetimes_made_aware(self):
        from app.services.dashboard_service import get_case_detail
        naive_updated = datetime(2026, 3, 1)
        doc = _make_single_doc("ZAD-X", updated_at=naive_updated)
        result = get_case_detail(_make_single_db(doc), "ZAD-X")
        assert result["last_activity"].tzinfo is not None

    def test_missing_nested_fields_default_gracefully(self):
        from app.services.dashboard_service import get_case_detail
        doc = MagicMock()
        doc.exists = True
        doc.id = "ZAD-SPARSE"
        doc.to_dict.return_value = {"status": "New Lead"}
        result = get_case_detail(_make_single_db(doc), "ZAD-SPARSE")
        assert result["first_name"] == ""
        assert result["last_name"] == ""
        assert result["vcf_deadline"] is None
        assert result["qual_score"] is None
        assert result["doc_completeness_pct"] is None
        assert result["assigned_paralegal"] is None

    def test_case_type_and_status_mapped(self):
        from app.services.dashboard_service import get_case_detail
        doc = MagicMock()
        doc.exists = True
        doc.id = "ZAD-T"
        doc.to_dict.return_value = {
            "status":    "Awarded",
            "firstName": "",
            "lastName":  "",
            "assignment": {},
        }
        result = get_case_detail(_make_single_db(doc), "ZAD-T")
        assert result["status"] == "Awarded"
        assert result["case_type"] is None


# ── Route: GET /api/v1/dashboard/cases/{caseId} ────────────────────────────

def _make_route_db(doc):
    """Return a mock Firestore client wired for a single document fetch."""
    db = MagicMock()
    db.collection.return_value.document.return_value.get.return_value = doc
    return db


class TestGetDashboardCaseRoute:

    def test_returns_200_with_full_document(self):
        full_doc = {
            "caseId": "ZAD-2026-01-0001",
            "status": "Pending Paralegal Review",
            "caseType": "VCF",
            "leadData": {"firstName": "Jane", "lastName": "Smith"},
            "qualification": {"medicalQualScore": 80.0, "vcfQualScore": 60.0},
            "enrollment": {"vcfRegDeadline": None},
            "assignment": {"assignedParalegal": "uid-p1"},
            "updatedAt": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
            "customField": "extra data returned as-is",
        }
        snap = MagicMock()
        snap.exists = True
        snap.to_dict.return_value = full_doc

        with patch("app.routes.dashboard.get_firestore_client", return_value=_make_route_db(snap)):
            import main as m
            client = TestClient(m.app, raise_server_exceptions=False)
            resp = client.get("/api/v1/dashboard/cases/ZAD-2026-01-0001")

        assert resp.status_code == 200
        body = resp.json()
        assert body["caseId"] == "ZAD-2026-01-0001"
        assert body["status"] == "Pending Paralegal Review"
        assert body["caseType"] == "VCF"
        assert body["leadData"] == {"firstName": "Jane", "lastName": "Smith"}
        assert body["qualification"]["medicalQualScore"] == 80.0
        assert body["assignment"]["assignedParalegal"] == "uid-p1"
        assert body["customField"] == "extra data returned as-is"

    def test_returns_404_when_not_found(self):
        snap = MagicMock()
        snap.exists = False

        with patch("app.routes.dashboard.get_firestore_client", return_value=_make_route_db(snap)):
            import main as m
            client = TestClient(m.app, raise_server_exceptions=False)
            resp = client.get("/api/v1/dashboard/cases/ZAD-DOES-NOT-EXIST")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Case not found"

    def test_full_document_not_filtered_to_summary_fields(self):
        """Verify the route returns the raw Firestore doc, not the CaseSummary subset."""
        full_doc = {
            "caseId": "ZAD-2026-01-0002",
            "status": "Awarded",
            "extraNestedData": {"someKey": "someValue"},
        }
        snap = MagicMock()
        snap.exists = True
        snap.to_dict.return_value = full_doc

        with patch("app.routes.dashboard.get_firestore_client", return_value=_make_route_db(snap)):
            import main as m
            client = TestClient(m.app, raise_server_exceptions=False)
            resp = client.get("/api/v1/dashboard/cases/ZAD-2026-01-0002")

        assert resp.status_code == 200
        body = resp.json()
        assert body["extraNestedData"] == {"someKey": "someValue"}
        assert "case_id" not in body  # CaseSummary field — should not be present
