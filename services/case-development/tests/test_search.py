"""
Unit tests for the Case Search service and routes.
All Firestore and Firebase auth calls are mocked.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from fastapi.testclient import TestClient


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_case_doc(
    case_id,
    status="Pending Paralegal Review",
    paralegal_id="sarah-chen-uid",
    attorney_id=None,
    first_name="John",
    last_name="Doe",
    email="john.doe@example.com",
    phone="555-1234",
    qual_score=75.0,
    vcf_qual_score=60.0,
    vcf_deadline=None,
    updated_at=None,
    created_at=None,
    screening_result="pass",
    case_type="WTC",
):
    doc = MagicMock()
    doc.id = case_id
    doc.to_dict.return_value = {
        "status":    status,
        "caseType":  case_type,
        "updatedAt": updated_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        "createdAt": created_at or datetime(2025, 6, 1, tzinfo=timezone.utc),
        "leadData":  {
            "firstName": first_name,
            "lastName":  last_name,
            "email":     email,
            "phone":     phone,
        },
        "qualification": {
            "medicalQualScore": qual_score,
            "vcfQualScore":     vcf_qual_score,
            "screeningResult":  screening_result,
        },
        "enrollment": {"vcfRegDeadline": vcf_deadline},
        "assignment": {
            "assignedParalegal": paralegal_id,
            "assignedAttorney":  attorney_id,
        },
    }
    return doc


def _make_db(docs):
    db    = MagicMock()
    query = MagicMock()
    db.collection.return_value  = query
    query.where.return_value    = query
    query.stream.return_value   = iter(docs)
    return db


def _make_preset_doc(preset_id, name="My Preset", filters=None):
    doc = MagicMock()
    doc.id = preset_id
    doc.exists = True
    doc.to_dict.return_value = {
        "name":      name,
        "filters":   filters or {"q": "test"},
        "createdAt": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updatedAt": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    return doc


def _call_service(db, user=None, **kwargs):
    from app.services.search_service import search_cases
    defaults = dict(
        q=None,
        statuses=None,
        case_type=None,
        assignees=None,
        attorney=None,
        deadline_from=None, deadline_to=None,
        created_from=None,  created_to=None,
        completeness_min=None, completeness_max=None,
        qual_min=None, qual_max=None,
        screening_result=None,
        sort_by="last_activity", sort_dir="desc",
        page=1, page_size=20,
    )
    defaults.update(kwargs)
    if user is None:
        user = {"uid": "sarah-chen-uid", "role": "paralegal"}
    return search_cases(db=db, user=user, **defaults)


# ── Service: basic retrieval ──────────────────────────────────────────────────

class TestSearchServiceRetrieval:

    def test_returns_all_assigned_cases(self):
        docs   = [_make_case_doc("c1"), _make_case_doc("c2")]
        result = _call_service(_make_db(docs))
        assert result["page"]["total"] == 2
        assert len(result["page"]["items"]) == 2

    def test_empty_returns_valid_structure(self):
        result = _call_service(_make_db([]))
        assert result["page"]["items"] == []
        assert result["page"]["total"] == 0
        assert result["page"]["total_pages"] == 1

    def test_extended_fields_materialised(self):
        doc    = _make_case_doc("ZAD-2026-01-0001", email="alice@test.com", phone="555-9999",
                                screening_result="pass", attorney_id="atty-uid")
        result = _call_service(_make_db([doc]))
        item   = result["page"]["items"][0]
        assert item["email"] == "alice@test.com"
        assert item["phone"] == "555-9999"
        assert item["screening_result"] == "pass"
        assert item["assigned_attorney"] == "atty-uid"
        assert item["is_flagged"] is False

    def test_created_at_field_present(self):
        created = datetime(2025, 3, 15, tzinfo=timezone.utc)
        doc     = _make_case_doc("c1", created_at=created)
        result  = _call_service(_make_db([doc]))
        assert result["page"]["items"][0]["created_at"] == created


# ── Service: full-text search ─────────────────────────────────────────────────

class TestSearchServiceFullText:

    def test_search_by_first_name(self):
        docs = [
            _make_case_doc("c1", first_name="Alice", last_name="Smith"),
            _make_case_doc("c2", first_name="Bob",   last_name="Jones"),
        ]
        result = _call_service(_make_db(docs), q="Alice")
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["first_name"] == "Alice"

    def test_search_by_last_name(self):
        docs = [
            _make_case_doc("c1", last_name="Smith"),
            _make_case_doc("c2", last_name="Jones"),
        ]
        result = _call_service(_make_db(docs), q="Jones")
        assert result["page"]["total"] == 1

    def test_search_by_case_id(self):
        docs = [
            _make_case_doc("ZAD-2026-01-0001"),
            _make_case_doc("ZAD-2026-01-0002"),
        ]
        result = _call_service(_make_db(docs), q="0001")
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["case_id"] == "ZAD-2026-01-0001"

    def test_search_by_email(self):
        docs = [
            _make_case_doc("c1", email="alice@law.com"),
            _make_case_doc("c2", email="bob@law.com"),
        ]
        result = _call_service(_make_db(docs), q="alice@law.com")
        assert result["page"]["total"] == 1

    def test_search_by_phone(self):
        docs = [
            _make_case_doc("c1", phone="555-1111"),
            _make_case_doc("c2", phone="555-2222"),
        ]
        result = _call_service(_make_db(docs), q="555-1111")
        assert result["page"]["total"] == 1

    def test_search_case_insensitive(self):
        docs = [_make_case_doc("c1", first_name="Alice")]
        result = _call_service(_make_db(docs), q="ALICE")
        assert result["page"]["total"] == 1

    def test_search_no_match_returns_empty(self):
        docs = [_make_case_doc("c1", first_name="Alice")]
        result = _call_service(_make_db(docs), q="zzznomatch")
        assert result["page"]["total"] == 0

    def test_search_combined_with_status_filter(self):
        docs = [
            _make_case_doc("c1", first_name="Alice", status="New Lead"),
            _make_case_doc("c2", first_name="Alice", status="Awarded"),
        ]
        result = _call_service(_make_db(docs), q="Alice", statuses=["New Lead"])
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["status"] == "New Lead"

    def test_empty_query_returns_all(self):
        docs = [_make_case_doc("c1"), _make_case_doc("c2")]
        result = _call_service(_make_db(docs), q=None)
        assert result["page"]["total"] == 2


# ── Service: filters ─────────────────────────────────────────────────────────

class TestSearchServiceFilters:

    def test_status_filter(self):
        docs = [
            _make_case_doc("c1", status="New Lead"),
            _make_case_doc("c2", status="Awarded"),
        ]
        result = _call_service(_make_db(docs), statuses=["Awarded"])
        assert result["page"]["total"] == 1

    def test_multi_status_filter(self):
        docs = [
            _make_case_doc("c1", status="New Lead"),
            _make_case_doc("c2", status="Awarded"),
            _make_case_doc("c3", status="Closed"),
        ]
        result = _call_service(_make_db(docs), statuses=["New Lead", "Awarded"])
        assert result["page"]["total"] == 2

    def test_case_type_filter_wtc(self):
        docs = [
            _make_case_doc("c1", case_type="WTC"),
            _make_case_doc("c2", case_type="VCF"),
        ]
        result = _call_service(_make_db(docs), case_type="wtc")
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["case_type"] == "WTC"

    def test_case_type_filter_vcf(self):
        docs = [
            _make_case_doc("c1", case_type="WTC"),
            _make_case_doc("c2", case_type="VCF"),
        ]
        result = _call_service(_make_db(docs), case_type="vcf")
        assert result["page"]["total"] == 1

    def test_case_type_all_returns_all(self):
        docs = [_make_case_doc("c1", case_type="WTC"), _make_case_doc("c2", case_type="VCF")]
        result = _call_service(_make_db(docs), case_type="all")
        assert result["page"]["total"] == 2

    def test_screening_result_filter(self):
        docs = [
            _make_case_doc("c1", screening_result="pass"),
            _make_case_doc("c2", screening_result="fail"),
        ]
        result = _call_service(_make_db(docs), screening_result="fail")
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["screening_result"] == "fail"

    def test_qual_min_filter(self):
        docs = [_make_case_doc("c1", qual_score=30.0), _make_case_doc("c2", qual_score=80.0)]
        result = _call_service(_make_db(docs), qual_min=50.0)
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["qual_score"] == 80.0

    def test_qual_max_filter(self):
        docs = [_make_case_doc("c1", qual_score=30.0), _make_case_doc("c2", qual_score=80.0)]
        result = _call_service(_make_db(docs), qual_max=50.0)
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["qual_score"] == 30.0

    def test_completeness_range_filter(self):
        docs = [
            _make_case_doc("c1", vcf_qual_score=20.0),
            _make_case_doc("c2", vcf_qual_score=60.0),
            _make_case_doc("c3", vcf_qual_score=90.0),
        ]
        result = _call_service(_make_db(docs), completeness_min=50.0, completeness_max=80.0)
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["doc_completeness_pct"] == 60.0

    def test_deadline_from_filter(self):
        past   = datetime(2025, 1, 1, tzinfo=timezone.utc)
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
        past   = datetime(2025, 1, 1, tzinfo=timezone.utc)
        future = datetime(2027, 1, 1, tzinfo=timezone.utc)
        cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
        docs = [
            _make_case_doc("c1", vcf_deadline=past),
            _make_case_doc("c2", vcf_deadline=future),
        ]
        result = _call_service(_make_db(docs), deadline_to=cutoff)
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["case_id"] == "c1"

    def test_created_from_filter(self):
        early = datetime(2024, 1, 1, tzinfo=timezone.utc)
        late  = datetime(2026, 1, 1, tzinfo=timezone.utc)
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        docs = [
            _make_case_doc("c1", created_at=early),
            _make_case_doc("c2", created_at=late),
        ]
        result = _call_service(_make_db(docs), created_from=cutoff)
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["case_id"] == "c2"

    def test_created_to_filter(self):
        early  = datetime(2024, 1, 1, tzinfo=timezone.utc)
        late   = datetime(2026, 1, 1, tzinfo=timezone.utc)
        cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
        docs = [
            _make_case_doc("c1", created_at=early),
            _make_case_doc("c2", created_at=late),
        ]
        result = _call_service(_make_db(docs), created_to=cutoff)
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["case_id"] == "c1"

    def test_attorney_filter_admin_only(self):
        docs = [
            _make_case_doc("c1", attorney_id="atty-001"),
            _make_case_doc("c2", attorney_id="atty-002"),
        ]
        admin  = {"uid": "admin-uid", "role": "admin_staff"}
        result = _call_service(_make_db(docs), user=admin, attorney=["atty-001"])
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["assigned_attorney"] == "atty-001"

    def test_attorney_filter_ignored_for_paralegal(self):
        # Paralegals cannot filter by attorney — filter is silently ignored
        docs = [
            _make_case_doc("c1", attorney_id="atty-001"),
            _make_case_doc("c2", attorney_id="atty-002"),
        ]
        paralegal = {"uid": "sarah-chen-uid", "role": "paralegal"}
        result = _call_service(_make_db(docs), user=paralegal, attorney=["atty-001"])
        assert result["page"]["total"] == 2

    def test_all_filters_combined(self):
        docs = [
            _make_case_doc("c1", status="New Lead", qual_score=80.0, screening_result="pass",
                           case_type="WTC"),
            _make_case_doc("c2", status="New Lead", qual_score=30.0, screening_result="pass",
                           case_type="WTC"),
            _make_case_doc("c3", status="Awarded",  qual_score=80.0, screening_result="pass",
                           case_type="WTC"),
        ]
        result = _call_service(
            _make_db(docs),
            statuses=["New Lead"], qual_min=50.0,
            screening_result="pass", case_type="wtc",
        )
        assert result["page"]["total"] == 1
        assert result["page"]["items"][0]["case_id"] == "c1"


# ── Service: sort ─────────────────────────────────────────────────────────────

class TestSearchServiceSort:

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

    def test_sort_by_case_id_asc(self):
        docs = [_make_case_doc("ZAD-B"), _make_case_doc("ZAD-A")]
        result = _call_service(_make_db(docs), sort_by="case_id", sort_dir="asc")
        ids = [c["case_id"] for c in result["page"]["items"]]
        assert ids == sorted(ids)

    def test_sort_by_created_at_desc(self):
        docs = [
            _make_case_doc("c1", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc)),
            _make_case_doc("c2", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        ]
        result = _call_service(_make_db(docs), sort_by="created_at", sort_dir="desc")
        ids = [c["case_id"] for c in result["page"]["items"]]
        assert ids == ["c2", "c1"]

    def test_sort_by_client_name(self):
        docs = [
            _make_case_doc("c1", first_name="Zoe",   last_name="Adams"),
            _make_case_doc("c2", first_name="Alice",  last_name="Brown"),
        ]
        result = _call_service(_make_db(docs), sort_by="client_name", sort_dir="asc")
        # Sort key is last_name + first_name
        names = [c["last_name"] for c in result["page"]["items"]]
        assert names == sorted(names)


# ── Service: pagination ───────────────────────────────────────────────────────

class TestSearchServicePagination:

    def test_first_page_correct_slice(self):
        docs   = [_make_case_doc(f"c{i:03d}") for i in range(25)]
        result = _call_service(_make_db(docs), page=1, page_size=20)
        assert len(result["page"]["items"]) == 20
        assert result["page"]["total"] == 25
        assert result["page"]["total_pages"] == 2

    def test_second_page_remainder(self):
        docs   = [_make_case_doc(f"c{i:03d}") for i in range(25)]
        result = _call_service(_make_db(docs), page=2, page_size=20)
        assert len(result["page"]["items"]) == 5

    def test_single_page_under_limit(self):
        docs   = [_make_case_doc(f"c{i}") for i in range(5)]
        result = _call_service(_make_db(docs), page=1, page_size=20)
        assert result["page"]["total_pages"] == 1

    def test_page_beyond_last_returns_empty(self):
        docs   = [_make_case_doc("c1")]
        result = _call_service(_make_db(docs), page=99, page_size=20)
        assert result["page"]["items"] == []


# ── Service: admin role visibility ────────────────────────────────────────────

class TestSearchServiceAdminRole:

    def test_admin_does_not_scope_to_paralegal(self):
        docs  = [_make_case_doc("c1", paralegal_id="someone-else")]
        db    = _make_db(docs)
        admin = {"uid": "admin-uid", "role": "senior_partner"}
        _call_service(db, user=admin)
        where_calls = [str(c) for c in db.collection.return_value.where.call_args_list]
        assert not any("assignedParalegal" in c for c in where_calls)

    def test_paralegal_scoped_to_own_uid(self):
        db        = _make_db([])
        paralegal = {"uid": "sarah-chen-uid", "role": "paralegal"}
        _call_service(db, user=paralegal)
        where_calls = [str(c) for c in db.collection.return_value.where.call_args_list]
        assert any("assignedParalegal" in c for c in where_calls)


# ── Service: CSV export ───────────────────────────────────────────────────────

class TestSearchServiceCsvExport:

    def _call_export(self, db, user=None, **kwargs):
        from app.services.search_service import export_cases_csv
        defaults = dict(
            q=None, statuses=None, case_type=None,
            assignees=None, attorney=None,
            deadline_from=None, deadline_to=None,
            created_from=None, created_to=None,
            completeness_min=None, completeness_max=None,
            qual_min=None, qual_max=None,
            screening_result=None,
            sort_by="last_activity", sort_dir="desc",
        )
        defaults.update(kwargs)
        if user is None:
            user = {"uid": "sarah-chen-uid", "role": "paralegal"}
        return export_cases_csv(db=db, user=user, **defaults)

    def test_csv_contains_header(self):
        csv_output = self._call_export(_make_db([]))
        assert "case_id" in csv_output
        assert "first_name" in csv_output
        assert "email" in csv_output

    def test_csv_contains_case_row(self):
        doc = _make_case_doc("ZAD-2026-01-0001", first_name="Alice", last_name="Smith",
                             email="alice@test.com")
        csv_output = self._call_export(_make_db([doc]))
        assert "ZAD-2026-01-0001" in csv_output
        assert "Alice" in csv_output
        assert "alice@test.com" in csv_output

    def test_csv_no_pagination_all_results(self):
        docs = [_make_case_doc(f"c{i:03d}") for i in range(50)]
        csv_output = self._call_export(_make_db(docs))
        # All 50 cases present: count data lines (exclude header)
        lines = [l for l in csv_output.strip().splitlines() if l]
        assert len(lines) == 51  # 1 header + 50 data rows

    def test_csv_filters_applied(self):
        docs = [
            _make_case_doc("c1", status="New Lead"),
            _make_case_doc("c2", status="Awarded"),
        ]
        csv_output = self._call_export(_make_db(docs), statuses=["Awarded"])
        lines = [l for l in csv_output.strip().splitlines() if l]
        assert len(lines) == 2  # 1 header + 1 data row

    def test_csv_datetime_as_iso_string(self):
        dt  = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        doc = _make_case_doc("c1", vcf_deadline=dt)
        csv_output = self._call_export(_make_db([doc]))
        assert "2026-03-15" in csv_output


# ── Service: filter presets ───────────────────────────────────────────────────

class TestFilterPresets:

    def _make_preset_collection(self, docs):
        col = MagicMock()
        col.stream.return_value = iter(docs)
        return col

    def test_list_presets_returns_all(self):
        from app.services.search_service import list_presets
        docs = [_make_preset_doc("p1", "Preset A"), _make_preset_doc("p2", "Preset B")]
        db   = MagicMock()
        db.collection.return_value.document.return_value.collection.return_value.stream.return_value = iter(docs)
        result = list_presets(db, "user-uid")
        assert len(result) == 2
        assert result[0]["preset_id"] in ("p1", "p2")

    def test_save_preset_writes_to_firestore(self):
        from app.services.search_service import save_preset
        db  = MagicMock()
        col = MagicMock()
        db.collection.return_value.document.return_value.collection.return_value = col
        result = save_preset(db, "user-uid", "My Preset", {"q": "alice"})
        col.document.return_value.set.assert_called_once()
        assert result["name"] == "My Preset"
        assert result["filters"] == {"q": "alice"}
        assert "preset_id" in result
        assert "createdAt" in result

    def test_update_preset_returns_updated_data(self):
        from app.services.search_service import update_preset
        existing_doc = _make_preset_doc("p1", "Old Name", {"q": "old"})
        ref = MagicMock()
        ref.get.return_value = existing_doc
        db  = MagicMock()
        db.collection.return_value.document.return_value.collection.return_value.document.return_value = ref
        result = update_preset(db, "user-uid", "p1", "New Name", {"q": "new"})
        ref.update.assert_called_once()
        assert result["name"] == "New Name"
        assert result["filters"] == {"q": "new"}
        assert result["preset_id"] == "p1"

    def test_update_preset_returns_none_if_not_found(self):
        from app.services.search_service import update_preset
        missing_doc     = MagicMock()
        missing_doc.exists = False
        ref = MagicMock()
        ref.get.return_value = missing_doc
        db  = MagicMock()
        db.collection.return_value.document.return_value.collection.return_value.document.return_value = ref
        result = update_preset(db, "user-uid", "nonexistent", "Name", {})
        assert result is None

    def test_delete_preset_returns_true_when_found(self):
        from app.services.search_service import delete_preset
        existing_doc     = MagicMock()
        existing_doc.exists = True
        ref = MagicMock()
        ref.get.return_value = existing_doc
        db  = MagicMock()
        db.collection.return_value.document.return_value.collection.return_value.document.return_value = ref
        assert delete_preset(db, "user-uid", "p1") is True
        ref.delete.assert_called_once()

    def test_delete_preset_returns_false_when_not_found(self):
        from app.services.search_service import delete_preset
        missing_doc     = MagicMock()
        missing_doc.exists = False
        ref = MagicMock()
        ref.get.return_value = missing_doc
        db  = MagicMock()
        db.collection.return_value.document.return_value.collection.return_value.document.return_value = ref
        assert delete_preset(db, "user-uid", "nonexistent") is False


# ── RBAC ──────────────────────────────────────────────────────────────────────

class TestSearchRBAC:

    def test_search_endpoint_200_for_paralegal(self):
        svc_result = {
            "page": {"items": [], "total": 0, "page": 1, "page_size": 20, "total_pages": 1},
        }
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.services.search_service.search_cases", return_value=svc_result):
            from importlib import reload
            import main as m
            client = TestClient(m.app, raise_server_exceptions=False)
            resp = client.get("/api/v1/cases/search")
        assert resp.status_code == 200

    def test_presets_endpoint_200_for_paralegal(self):
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.services.search_service.list_presets", return_value=[]):
            from importlib import reload
            import main as m
            client = TestClient(m.app, raise_server_exceptions=False)
            resp = client.get("/api/v1/search/presets")
        assert resp.status_code == 200

    def test_export_endpoint_200_for_paralegal(self):
        with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
             patch("app.services.search_service.export_cases_csv", return_value="case_id\n"):
            import main as m
            client = TestClient(m.app, raise_server_exceptions=False)
            resp = client.get("/api/v1/cases/search/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
