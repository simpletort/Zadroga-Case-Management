import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta


def _make_case(status: str, days_old: int = 10, score: int = None) -> dict:
    now = datetime.now(timezone.utc)
    case = {
        "status": status,
        "createdAt": now - timedelta(days=days_old),
        "lastStatusChangedAt": now - timedelta(days=days_old),
    }
    if score is not None:
        case["qualificationScore"] = score
    return case


class TestTrendCalculation:
    def test_positive_trend(self):
        from app.services.kpi_service import _trend
        pct, direction = _trend(120, 100)
        assert pct == 20.0
        assert direction == "up"

    def test_negative_trend(self):
        from app.services.kpi_service import _trend
        pct, direction = _trend(80, 100)
        assert pct == -20.0
        assert direction == "down"

    def test_zero_previous_returns_none(self):
        from app.services.kpi_service import _trend
        pct, direction = _trend(50, 0)
        assert pct is None
        assert direction is None

    def test_flat_trend(self):
        from app.services.kpi_service import _trend
        pct, direction = _trend(100, 100)
        assert pct == 0.0
        assert direction == "neutral"


class TestAggregationService:

    @patch("app.services.aggregation_service.get_firestore_client")
    def test_get_cases_by_status_counts_correctly(self, mock_db):
        from app.services.aggregation_service import get_cases_by_status

        now = datetime.now(timezone.utc)
        mock_docs = []

        for status, count in [
            ("New Lead", 3),
            ("Pending Paralegal Review", 5),
            ("Settled", 2),
        ]:
            for _ in range(count):
                doc = MagicMock()
                doc.to_dict.return_value = {
                    "status": status,
                    "lastStatusChangedAt": now - timedelta(days=7),
                }
                mock_docs.append(doc)

        mock_db.return_value.collection.return_value.stream.return_value = mock_docs

        result = get_cases_by_status()
        counts = {r["status"]: r["count"] for r in result}

        assert counts["New Lead"] == 3
        assert counts["Pending Paralegal Review"] == 5
        assert counts["Settled"] == 2

    @patch("app.services.aggregation_service.get_firestore_client")
    def test_bottleneck_excludes_recent_cases(self, mock_db):
        from app.services.aggregation_service import get_bottleneck_cases

        now = datetime.now(timezone.utc)

        recent_doc = MagicMock()
        recent_doc.id = "ZAD-2026-03-0001"
        recent_doc.to_dict.return_value = {
            "status": "Pending Paralegal Review",
            "lastStatusChangedAt": now - timedelta(days=5),
        }

        old_doc = MagicMock()
        old_doc.id = "ZAD-2026-03-0002"
        old_doc.to_dict.return_value = {
            "status": "Pending Paralegal Review",
            "lastStatusChangedAt": now - timedelta(days=45),
        }

        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 3:
                return [recent_doc, old_doc]
            return []

        mock_db.return_value.collection.return_value \
            .where.return_value.stream.side_effect = side_effect

        results = get_bottleneck_cases(threshold_days=30)
        case_ids = [r["caseId"] for r in results]

        assert "ZAD-2026-03-0002" in case_ids
        assert "ZAD-2026-03-0001" not in case_ids


class TestLeadConversionRoute:

    @patch("app.routes.leads.get_leads_in_period")
    def test_qualification_rate_calculation(self, mock_leads):
        from fastapi.testclient import TestClient
        from main import app
        from app.utils.auth import require_min_role

        now = datetime.now(timezone.utc)

        mock_leads.return_value = [
            {"status": "Pending Paralegal Review", "createdAt": now},
            {"status": "Pending Paralegal Review", "createdAt": now},
            {"status": "VCF - Submitted",          "createdAt": now},
            {"status": "Settled",                  "createdAt": now},
            {"status": "Does Not Qualify",         "createdAt": now},
            {"status": "Does Not Qualify",         "createdAt": now},
        ]

        # Override the base auth dependency — all role checks call this
        from app.utils.auth import get_current_user
        app.dependency_overrides[get_current_user] = \
            lambda: {"uid": "test", "role": "junior_partner"}

        client = TestClient(app)
        response = client.get("/reports/lead-conversion?period_days=30")

        assert response.status_code == 200
        data = response.json()
        assert data["total_leads"] == 6
        assert data["disqualified"] == 2
        assert abs(data["qualification_rate"] - 66.7) < 0.1

        app.dependency_overrides.clear()


class TestCacheService:

    def test_cache_hit_and_miss(self):
        from app.services.cache_service import TTLCache
        cache = TTLCache(default_ttl_seconds=60)
        assert cache.get("missing_key") is None
        cache.set("my_key", {"value": 42})
        assert cache.get("my_key") == {"value": 42}

    def test_cache_expiry(self):
        import time
        from app.services.cache_service import TTLCache
        cache = TTLCache(default_ttl_seconds=1)
        cache.set("expiring_key", "hello", ttl=1)
        assert cache.get("expiring_key") == "hello"
        time.sleep(1.1)
        assert cache.get("expiring_key") is None

    def test_cache_invalidate(self):
        from app.services.cache_service import TTLCache
        cache = TTLCache()
        cache.set("k", "v")
        cache.invalidate("k")
        assert cache.get("k") is None
