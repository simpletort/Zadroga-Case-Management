"""
Tests for lifecycle management endpoints:
  GET  /api/v1/storage/lifecycle
  PUT  /api/v1/storage/lifecycle
  POST /api/v1/storage/lifecycle/apply-default
  PUT  /api/v1/storage/lifecycle/soft-delete
  PUT  /api/v1/storage/cases/{case_id}/hold
"""

import pytest
from unittest.mock import MagicMock, patch, call
from fastapi.testclient import TestClient


# ── GET /lifecycle ─────────────────────────────────────────────────────────────

class TestGetLifecycle:
    def test_returns_rules_and_soft_delete(self, client, mock_gcs_client):
        with patch("app.routes.lifecycle.get_lifecycle_rules") as mock_get:
            mock_get.return_value = (
                [{"action": {"type": "SetStorageClass", "storageClass": "NEARLINE"},
                  "condition": {"age": 180}}],
                30,
            )
            resp = client.get("/api/v1/storage/lifecycle")

        assert resp.status_code == 200
        body = resp.json()
        assert body["bucket"] == "zadroga-case-files-simpletort-prod"
        assert len(body["rules"]) == 1
        assert body["soft_delete_retention_days"] == 30

    def test_returns_none_soft_delete_when_not_configured(self, client, mock_gcs_client):
        with patch("app.routes.lifecycle.get_lifecycle_rules") as mock_get:
            mock_get.return_value = ([], None)
            resp = client.get("/api/v1/storage/lifecycle")

        assert resp.status_code == 200
        assert resp.json()["soft_delete_retention_days"] is None


# ── PUT /lifecycle ─────────────────────────────────────────────────────────────

class TestUpdateLifecycle:
    def test_applies_rules_to_bucket(self, client, mock_gcs_client):
        with patch("app.routes.lifecycle.update_lifecycle_rules") as mock_update:
            resp = client.put(
                "/api/v1/storage/lifecycle",
                json={"rules": [
                    {"action": "SetStorageClass", "storage_class": "NEARLINE",
                     "condition": {"age_days": 180}},
                    {"action": "SetStorageClass", "storage_class": "COLDLINE",
                     "condition": {"age_days": 365}},
                ]},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["rules_applied"] == 2
        mock_update.assert_called_once()

    def test_matches_prefix_propagates_to_sdk_rule(self, client, mock_gcs_client):
        captured = {}
        def _capture(gcs_client, rules):
            captured["rules"] = rules

        with patch("app.routes.lifecycle.update_lifecycle_rules", side_effect=_capture):
            resp = client.put(
                "/api/v1/storage/lifecycle",
                json={"rules": [
                    {"action": "Delete",
                     "condition": {"age_days": 1, "matches_prefix": ["staging/", "tmp/"]}},
                ]},
            )

        assert resp.status_code == 200
        sdk_rule = captured["rules"][0]
        assert sdk_rule["condition"]["age"] == 1
        assert sdk_rule["condition"]["matchesPrefix"] == ["staging/", "tmp/"]

    def test_no_prefix_in_sdk_rule_when_not_provided(self, client, mock_gcs_client):
        captured = {}
        def _capture(gcs_client, rules):
            captured["rules"] = rules

        with patch("app.routes.lifecycle.update_lifecycle_rules", side_effect=_capture):
            resp = client.put(
                "/api/v1/storage/lifecycle",
                json={"rules": [
                    {"action": "SetStorageClass", "storage_class": "COLDLINE",
                     "condition": {"age_days": 365}},
                ]},
            )

        assert resp.status_code == 200
        assert "matchesPrefix" not in captured["rules"][0]["condition"]

    def test_rejects_empty_rules_array(self, client):
        resp = client.put(
            "/api/v1/storage/lifecycle",
            json={"rules": []},
        )
        assert resp.status_code == 422

    def test_rejects_age_days_zero(self, client):
        resp = client.put(
            "/api/v1/storage/lifecycle",
            json={"rules": [
                {"action": "Delete", "condition": {"age_days": 0}},
            ]},
        )
        assert resp.status_code == 422


# ── POST /lifecycle/apply-default ─────────────────────────────────────────────

class TestApplyDefaultLifecycle:
    def test_applies_exactly_five_rules(self, client, mock_gcs_client):
        """Was 4; a 5th rule (system-uploads/ 2-day delete) was added for
        bulk-import spreadsheet staging — see DEFAULT_LIFECYCLE_RULES."""
        with patch("app.routes.lifecycle.update_lifecycle_rules") as mock_update:
            resp = client.post("/api/v1/storage/lifecycle/apply-default")

        assert resp.status_code == 200
        body = resp.json()
        assert body["rules_applied"] == 5
        mock_update.assert_called_once()

    def test_default_rules_include_system_uploads_delete(self, client, mock_gcs_client):
        captured = {}
        def _capture(gcs_client, rules):
            captured["rules"] = rules

        with patch("app.routes.lifecycle.update_lifecycle_rules", side_effect=_capture):
            client.post("/api/v1/storage/lifecycle/apply-default")

        rules = captured["rules"]
        system_uploads_rule = next(
            r for r in rules
            if r["condition"].get("matchesPrefix") == ["system-uploads/"]
        )
        assert system_uploads_rule["action"]["type"] == "Delete"
        assert system_uploads_rule["condition"]["age"] == 2

    def test_default_rules_include_staging_delete(self, client, mock_gcs_client):
        captured = {}
        def _capture(gcs_client, rules):
            captured["rules"] = rules

        with patch("app.routes.lifecycle.update_lifecycle_rules", side_effect=_capture):
            client.post("/api/v1/storage/lifecycle/apply-default")

        rules = captured["rules"]
        staging_rule = next(
            r for r in rules
            if r["action"]["type"] == "Delete"
            and "staging/" in r["condition"].get("matchesPrefix", [])
        )
        assert staging_rule["condition"]["age"] == 1

    def test_default_rules_include_quarantine_delete(self, client, mock_gcs_client):
        captured = {}
        def _capture(gcs_client, rules):
            captured["rules"] = rules

        with patch("app.routes.lifecycle.update_lifecycle_rules", side_effect=_capture):
            client.post("/api/v1/storage/lifecycle/apply-default")

        rules = captured["rules"]
        quarantine_rule = next(
            r for r in rules
            if r["action"]["type"] == "Delete"
            and "quarantine/" in r["condition"].get("matchesPrefix", [])
        )
        assert quarantine_rule["condition"]["age"] == 90

    def test_default_rules_include_nearline_at_180(self, client, mock_gcs_client):
        captured = {}
        def _capture(gcs_client, rules):
            captured["rules"] = rules

        with patch("app.routes.lifecycle.update_lifecycle_rules", side_effect=_capture):
            client.post("/api/v1/storage/lifecycle/apply-default")

        rules = captured["rules"]
        nearline_rule = next(
            r for r in rules
            if r["action"].get("storageClass") == "NEARLINE"
        )
        assert nearline_rule["condition"]["age"] == 180

    def test_default_rules_include_coldline_at_365(self, client, mock_gcs_client):
        captured = {}
        def _capture(gcs_client, rules):
            captured["rules"] = rules

        with patch("app.routes.lifecycle.update_lifecycle_rules", side_effect=_capture):
            client.post("/api/v1/storage/lifecycle/apply-default")

        rules = captured["rules"]
        coldline_rule = next(
            r for r in rules
            if r["action"].get("storageClass") == "COLDLINE"
        )
        assert coldline_rule["condition"]["age"] == 365


# ── PUT /lifecycle/soft-delete ─────────────────────────────────────────────────

class TestSoftDelete:
    def test_sets_retention_days(self, client, mock_gcs_client):
        with patch("app.routes.lifecycle.configure_soft_delete") as mock_cfg:
            resp = client.put(
                "/api/v1/storage/lifecycle/soft-delete",
                json={"retention_days": 30},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["retention_days"] == 30
        mock_cfg.assert_called_once()
        assert mock_cfg.call_args.kwargs["retention_days"] == 30

    def test_uses_default_30_days(self, client, mock_gcs_client):
        with patch("app.routes.lifecycle.configure_soft_delete") as mock_cfg:
            resp = client.put(
                "/api/v1/storage/lifecycle/soft-delete",
                json={},
            )

        assert resp.status_code == 200
        mock_cfg.assert_called_once()
        assert mock_cfg.call_args.kwargs["retention_days"] == 30

    def test_rejects_below_minimum_7_days(self, client):
        resp = client.put(
            "/api/v1/storage/lifecycle/soft-delete",
            json={"retention_days": 6},
        )
        assert resp.status_code == 422

    def test_rejects_above_maximum_90_days(self, client):
        resp = client.put(
            "/api/v1/storage/lifecycle/soft-delete",
            json={"retention_days": 91},
        )
        assert resp.status_code == 422


# ── PUT /cases/{case_id}/hold ──────────────────────────────────────────────────

class TestCaseHold:
    def test_sets_hold_on_case_documents(self, client, mock_gcs_client):
        with patch("app.routes.lifecycle.set_case_documents_hold") as mock_hold:
            mock_hold.return_value = 5
            resp = client.put(
                "/api/v1/storage/cases/ZAD-2024-01-0001/hold",
                json={"hold": True},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["case_id"] == "ZAD-2024-01-0001"
        assert body["hold"] is True
        assert body["documents_updated"] == 5
        mock_hold.assert_called_once()
        assert mock_hold.call_args.kwargs["case_id"] == "ZAD-2024-01-0001"
        assert mock_hold.call_args.kwargs["hold"] is True

    def test_releases_hold_on_case_documents(self, client, mock_gcs_client):
        with patch("app.routes.lifecycle.set_case_documents_hold") as mock_hold:
            mock_hold.return_value = 3
            resp = client.put(
                "/api/v1/storage/cases/ZAD-2024-01-0001/hold",
                json={"hold": False},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["hold"] is False
        assert body["documents_updated"] == 3
        mock_hold.assert_called_once()
        assert mock_hold.call_args.kwargs["case_id"] == "ZAD-2024-01-0001"
        assert mock_hold.call_args.kwargs["hold"] is False

    def test_zero_documents_is_valid(self, client, mock_gcs_client):
        with patch("app.routes.lifecycle.set_case_documents_hold") as mock_hold:
            mock_hold.return_value = 0
            resp = client.put(
                "/api/v1/storage/cases/ZAD-2024-01-9999/hold",
                json={"hold": True},
            )

        assert resp.status_code == 200
        assert resp.json()["documents_updated"] == 0

    def test_missing_hold_field_is_422(self, client):
        resp = client.put(
            "/api/v1/storage/cases/ZAD-2024-01-0001/hold",
            json={},
        )
        assert resp.status_code == 422


# ── Service unit tests ─────────────────────────────────────────────────────────

class TestGetLifecycleRulesService:
    def test_reads_rules_and_soft_delete_from_bucket(self):
        from app.services.gcs_service import get_lifecycle_rules

        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.get_bucket.return_value = mock_bucket
        mock_bucket.lifecycle_rules = [
            {"action": {"type": "Delete"}, "condition": {"age": 1}}
        ]
        mock_bucket.soft_delete_policy.retention_duration_seconds = 2592000  # 30 days

        rules, retention_days = get_lifecycle_rules(mock_client)

        assert len(rules) == 1
        assert retention_days == 30

    def test_returns_none_when_soft_delete_not_set(self):
        from app.services.gcs_service import get_lifecycle_rules

        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.get_bucket.return_value = mock_bucket
        mock_bucket.lifecycle_rules = []
        mock_bucket.soft_delete_policy.retention_duration_seconds = 0

        _, retention_days = get_lifecycle_rules(mock_client)
        assert retention_days is None


class TestConfigureSoftDeleteService:
    def test_sets_correct_seconds_on_bucket(self):
        from app.services.gcs_service import configure_soft_delete

        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        configure_soft_delete(mock_client, retention_days=30)

        assert mock_bucket.soft_delete_policy.retention_duration_seconds == 30 * 86400
        mock_bucket.patch.assert_called_once()

    def test_default_is_30_days(self):
        from app.services.gcs_service import configure_soft_delete

        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        configure_soft_delete(mock_client)

        assert mock_bucket.soft_delete_policy.retention_duration_seconds == 2592000


class TestSetCaseDocumentsHoldService:
    def test_sets_hold_and_metadata_on_all_blobs(self):
        from app.services.gcs_service import set_case_documents_hold

        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        blob1, blob2 = MagicMock(), MagicMock()
        blob1.metadata = {}
        blob2.metadata = None
        mock_client.list_blobs.return_value = [blob1, blob2]

        count = set_case_documents_hold(mock_client, "ZAD-2024-01-0001", hold=True)

        assert count == 2
        assert blob1.temporary_hold is True
        assert blob1.metadata["case-status"] == "active"
        assert blob2.temporary_hold is True
        assert blob2.metadata["case-status"] == "active"
        assert blob1.patch.call_count == 1
        assert blob2.patch.call_count == 1

    def test_releases_hold_sets_archived_metadata(self):
        from app.services.gcs_service import set_case_documents_hold

        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        blob = MagicMock()
        blob.metadata = {"case-status": "active"}
        mock_client.list_blobs.return_value = [blob]

        count = set_case_documents_hold(mock_client, "ZAD-2024-01-0001", hold=False)

        assert count == 1
        assert blob.temporary_hold is False
        assert blob.metadata["case-status"] == "archived"

    def test_returns_zero_when_no_blobs(self):
        from app.services.gcs_service import set_case_documents_hold

        mock_client = MagicMock()
        mock_client.bucket.return_value = MagicMock()
        mock_client.list_blobs.return_value = []

        count = set_case_documents_hold(mock_client, "ZAD-2024-01-9999", hold=True)
        assert count == 0

    def test_uses_correct_prefix_for_listing(self):
        from app.services.gcs_service import set_case_documents_hold

        mock_client = MagicMock()
        mock_client.bucket.return_value = MagicMock()
        mock_client.list_blobs.return_value = []

        set_case_documents_hold(mock_client, "ZAD-2024-01-0001", hold=True)

        mock_client.list_blobs.assert_called_once_with(
            "zadroga-case-files-simpletort-prod",
            prefix="ZAD-2024-01-0001/",
        )
