"""
tests/unit/test_case_id_prefix.py

Tests for the configurable case-ID prefix feature:
  - _case_id() / _counter_doc_id() pure formatters
  - _fetch_prefix() async Firestore read + module-level cache
  - reset_prefix_cache()
  - LeadCreatedResponse.leadId pattern (prefix-agnostic)
  - UpdateCaseIdPrefixRequest validation
  - GET / PATCH /api/v1/admin/settings/case-id-prefix endpoints
"""
from __future__ import annotations

import asyncio
import sys
import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../api"))

import pytest
from pydantic import ValidationError


# ── Pure helper functions ─────────────────────────────────────────────────────

class TestCaseIdFormatter:
    """_case_id() and _counter_doc_id() are pure string formatters."""

    def setup_method(self):
        # Import fresh each test so module state doesn't bleed
        from services.case_service import _case_id, _counter_doc_id
        self._case_id       = _case_id
        self._counter_doc_id = _counter_doc_id

    def test_case_id_default_prefix(self):
        assert self._case_id("ZAD", 2026, 5, 1) == "ZAD-2026-05-0001"

    def test_case_id_custom_prefix(self):
        assert self._case_id("CASE", 2026, 5, 1) == "CASE-2026-05-0001"

    def test_case_id_zero_pads_month(self):
        assert self._case_id("ZAD", 2026, 1, 1) == "ZAD-2026-01-0001"

    def test_case_id_zero_pads_count(self):
        assert self._case_id("ZAD", 2026, 5, 42) == "ZAD-2026-05-0042"

    def test_case_id_max_count(self):
        assert self._case_id("ZAD", 2026, 5, 9999) == "ZAD-2026-05-9999"

    def test_case_id_single_letter_prefix(self):
        assert self._case_id("A", 2026, 5, 1) == "A-2026-05-0001"

    def test_counter_doc_id_default_prefix(self):
        assert self._counter_doc_id("ZAD", 2026, 5) == "ZAD-2026-05"

    def test_counter_doc_id_custom_prefix(self):
        assert self._counter_doc_id("TORT", 2026, 12) == "TORT-2026-12"

    def test_counter_doc_id_zero_pads_month(self):
        assert self._counter_doc_id("ZAD", 2026, 1) == "ZAD-2026-01"

    def test_case_id_and_counter_doc_share_prefix(self):
        """The counter doc key must be a prefix-segment of the case ID."""
        prefix = "MYCO"
        counter = self._counter_doc_id(prefix, 2026, 5)
        case    = self._case_id(prefix, 2026, 5, 1)
        assert case.startswith(counter)


# ── Module-level cache: reset_prefix_cache + _fetch_prefix ───────────────────

class TestPrefixCache:
    """Tests for the lazy Firestore fetch and module-level cache."""

    def _reset(self):
        import services.case_service as cs
        cs._case_id_prefix_cache = None

    def test_reset_clears_cache(self):
        import services.case_service as cs
        cs._case_id_prefix_cache = "ZAD"
        from services.case_service import reset_prefix_cache
        reset_prefix_cache()
        assert cs._case_id_prefix_cache is None

    def test_fetch_prefix_returns_cached_without_firestore(self):
        """If cache is warm, Firestore must NOT be called."""
        import services.case_service as cs
        cs._case_id_prefix_cache = "ZAD"
        from services.case_service import _fetch_prefix

        mock_db = AsyncMock()
        result  = asyncio.run(_fetch_prefix(mock_db))

        assert result == "ZAD"
        mock_db.collection.assert_not_called()

    def test_fetch_prefix_reads_firestore_on_cache_miss(self):
        self._reset()
        from services.case_service import _fetch_prefix

        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"prefix": "ZAD", "updatedAt": "2026-01-01"}

        mock_doc_ref = AsyncMock()
        mock_doc_ref.get = AsyncMock(return_value=mock_doc)
        mock_col = MagicMock()
        mock_col.document.return_value = mock_doc_ref
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_col

        result = asyncio.run(_fetch_prefix(mock_db))

        assert result == "ZAD"
        mock_db.collection.assert_called_once_with("firmSettings")
        mock_col.document.assert_called_once_with("case_id_prefix")

    def test_fetch_prefix_cached_after_first_read(self):
        """Second call must skip Firestore entirely."""
        self._reset()
        from services.case_service import _fetch_prefix

        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"prefix": "TORT"}

        mock_doc_ref = AsyncMock()
        mock_doc_ref.get = AsyncMock(return_value=mock_doc)
        mock_col = MagicMock()
        mock_col.document.return_value = mock_doc_ref
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_col

        asyncio.run(_fetch_prefix(mock_db))   # first call — populates cache
        asyncio.run(_fetch_prefix(mock_db))   # second call — should use cache

        assert mock_doc_ref.get.await_count == 1

    def test_fetch_prefix_fallback_when_doc_missing(self):
        self._reset()
        from services.case_service import _fetch_prefix

        mock_doc = MagicMock()
        mock_doc.exists = False

        mock_doc_ref = AsyncMock()
        mock_doc_ref.get = AsyncMock(return_value=mock_doc)
        mock_col = MagicMock()
        mock_col.document.return_value = mock_doc_ref
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_col

        result = asyncio.run(_fetch_prefix(mock_db))
        assert result == "CASE"

    def test_fetch_prefix_fallback_when_prefix_field_absent(self):
        """Doc exists but has no 'prefix' key — should fall back to 'CASE'."""
        self._reset()
        from services.case_service import _fetch_prefix

        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {}        # empty doc

        mock_doc_ref = AsyncMock()
        mock_doc_ref.get = AsyncMock(return_value=mock_doc)
        mock_col = MagicMock()
        mock_col.document.return_value = mock_doc_ref
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_col

        result = asyncio.run(_fetch_prefix(mock_db))
        assert result == "CASE"

    def test_fetch_prefix_fallback_when_to_dict_returns_none(self):
        """to_dict() returning None (deleted doc) is handled safely."""
        self._reset()
        from services.case_service import _fetch_prefix

        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = None

        mock_doc_ref = AsyncMock()
        mock_doc_ref.get = AsyncMock(return_value=mock_doc)
        mock_col = MagicMock()
        mock_col.document.return_value = mock_doc_ref
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_col

        result = asyncio.run(_fetch_prefix(mock_db))
        assert result == "CASE"


# ── LeadCreatedResponse.leadId validation ────────────────────────────────────

class TestLeadCreatedResponseLeadId:
    """The leadId pattern was widened from ^ZAD- to ^[A-Z]+- ."""

    def _make(self, lead_id: str):
        from models.lead import LeadCreatedResponse, CaseStatus, VCFEligibility
        return LeadCreatedResponse(
            leadId             = lead_id,
            status             = CaseStatus.NEW_LEAD,
            vcfScreeningStatus = VCFEligibility.PENDING,
            requestId          = "req-1",
            timestamp          = datetime.utcnow(),
        )

    def test_zad_prefix_accepted(self):
        r = self._make("ZAD-2026-05-0001")
        assert r.leadId == "ZAD-2026-05-0001"

    def test_case_prefix_accepted(self):
        r = self._make("CASE-2026-05-0001")
        assert r.leadId == "CASE-2026-05-0001"

    def test_single_letter_prefix_accepted(self):
        r = self._make("A-2026-05-0001")
        assert r.leadId == "A-2026-05-0001"

    def test_ten_letter_prefix_accepted(self):
        r = self._make("ABCDEFGHIJ-2026-05-0001")
        assert r.leadId == "ABCDEFGHIJ-2026-05-0001"

    def test_lowercase_prefix_rejected(self):
        with pytest.raises(ValidationError):
            self._make("zad-2026-05-0001")

    def test_mixed_case_prefix_rejected(self):
        with pytest.raises(ValidationError):
            self._make("Zad-2026-05-0001")

    def test_numeric_prefix_rejected(self):
        with pytest.raises(ValidationError):
            self._make("123-2026-05-0001")

    def test_missing_count_segment_rejected(self):
        with pytest.raises(ValidationError):
            self._make("ZAD-2026-05")

    def test_extra_segments_rejected(self):
        with pytest.raises(ValidationError):
            self._make("ZAD-2026-05-0001-EXTRA")

    def test_count_not_zero_padded_rejected(self):
        with pytest.raises(ValidationError):
            self._make("ZAD-2026-05-1")   # must be 4 digits


# ── UpdateCaseIdPrefixRequest validation ─────────────────────────────────────

class TestUpdateCaseIdPrefixRequest:
    def _make(self, prefix):
        from routers.settings import UpdateCaseIdPrefixRequest
        return UpdateCaseIdPrefixRequest(prefix=prefix)

    def test_valid_zad(self):
        req = self._make("ZAD")
        assert req.prefix == "ZAD"

    def test_valid_single_letter(self):
        assert self._make("A").prefix == "A"

    def test_valid_max_length(self):
        assert self._make("ABCDEFGHIJ").prefix == "ABCDEFGHIJ"   # 10 chars

    def test_rejects_lowercase(self):
        with pytest.raises(ValidationError):
            self._make("zad")

    def test_rejects_mixed_case(self):
        with pytest.raises(ValidationError):
            self._make("Zad")

    def test_rejects_digits(self):
        with pytest.raises(ValidationError):
            self._make("ZAD1")

    def test_rejects_hyphen(self):
        with pytest.raises(ValidationError):
            self._make("ZAD-X")

    def test_rejects_empty_string(self):
        with pytest.raises(ValidationError):
            self._make("")

    def test_rejects_too_long(self):
        with pytest.raises(ValidationError):
            self._make("ABCDEFGHIJK")   # 11 chars


# ── Settings router endpoints ─────────────────────────────────────────────────

def _make_partner_context(role: str = "system_admin"):
    """Build a minimal PartnerContext for auth override."""
    from middleware.auth import PartnerContext
    return PartnerContext(
        partner_id  = "test-partner",
        auth_method = "firebase_jwt",
        raw_claims  = {"role": role, "email": "admin@test.com"},
    )


def _build_test_app():
    """
    Build a minimal FastAPI app with just the settings router,
    overriding auth and db dependencies.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.settings import router
    from middleware.auth import get_partner
    from services.firestore_client import get_db

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app, get_partner, get_db, TestClient


class TestSettingsRouter:
    def setup_method(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.settings import router
        from middleware.auth import get_partner
        from services.firestore_client import get_db

        self.app       = FastAPI()
        self.app.include_router(router, prefix="/api/v1")
        self.get_partner = get_partner
        self.get_db      = get_db
        self.TestClient  = TestClient

    def _client(self, role="system_admin", mock_db=None):
        from fastapi.testclient import TestClient

        partner = _make_partner_context(role)
        self.app.dependency_overrides[self.get_partner] = lambda: partner
        self.app.dependency_overrides[self.get_db]      = lambda: mock_db or AsyncMock()
        return TestClient(self.app)

    def _mock_db_with_doc(self, prefix: str):
        """Return an AsyncMock db where firmSettings/case_id_prefix returns prefix."""
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "prefix":    prefix,
            "updatedAt": datetime.utcnow(),
            "updatedBy": "admin@test.com",
        }
        mock_doc_ref = AsyncMock()
        mock_doc_ref.get = AsyncMock(return_value=mock_doc)
        mock_col = MagicMock()
        mock_col.document.return_value = mock_doc_ref
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_col
        return mock_db

    def _mock_db_no_doc(self):
        """Return an AsyncMock db where the firmSettings doc does not exist."""
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_doc_ref = AsyncMock()
        mock_doc_ref.get = AsyncMock(return_value=mock_doc)
        mock_col = MagicMock()
        mock_col.document.return_value = mock_doc_ref
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_col
        return mock_db

    # ── PATCH ────────────────────────────────────────────────────────────────

    def test_patch_updates_firestore_and_returns_200(self):
        mock_db = MagicMock()
        mock_col = MagicMock()
        mock_doc_ref = AsyncMock()
        mock_doc_ref.set = AsyncMock()
        mock_col.document.return_value = mock_doc_ref
        mock_db.collection.return_value = mock_col

        with patch("routers.settings.reset_prefix_cache") as mock_reset:
            client = self._client(mock_db=mock_db)
            resp   = client.patch(
                "/api/v1/admin/settings/case-id-prefix",
                json={"prefix": "ZAD"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["prefix"] == "ZAD"
        assert "updatedAt" in data
        assert data["updatedBy"] == "admin@test.com"
        mock_doc_ref.set.assert_awaited_once()
        mock_reset.assert_called_once()

    def test_patch_resets_cache(self):
        mock_db = MagicMock()
        mock_col = MagicMock()
        mock_doc_ref = AsyncMock()
        mock_doc_ref.set = AsyncMock()
        mock_col.document.return_value = mock_doc_ref
        mock_db.collection.return_value = mock_col

        import services.case_service as cs
        cs._case_id_prefix_cache = "OLD"

        client = self._client(mock_db=mock_db)
        client.patch(
            "/api/v1/admin/settings/case-id-prefix",
            json={"prefix": "NEW"},
        )

        assert cs._case_id_prefix_cache is None

    def test_patch_rejects_lowercase_prefix(self):
        client = self._client()
        resp   = client.patch(
            "/api/v1/admin/settings/case-id-prefix",
            json={"prefix": "zad"},
        )
        assert resp.status_code == 422

    def test_patch_rejects_empty_prefix(self):
        client = self._client()
        resp   = client.patch(
            "/api/v1/admin/settings/case-id-prefix",
            json={"prefix": ""},
        )
        assert resp.status_code == 422

    def test_patch_rejects_prefix_with_digits(self):
        client = self._client()
        resp   = client.patch(
            "/api/v1/admin/settings/case-id-prefix",
            json={"prefix": "ZAD1"},
        )
        assert resp.status_code == 422

    def test_patch_rejects_non_admin_role(self):
        mock_db = MagicMock()
        mock_col = MagicMock()
        mock_doc_ref = AsyncMock()
        mock_doc_ref.set = AsyncMock()
        mock_col.document.return_value = mock_doc_ref
        mock_db.collection.return_value = mock_col

        client = self._client(role="paralegal", mock_db=mock_db)
        resp   = client.patch(
            "/api/v1/admin/settings/case-id-prefix",
            json={"prefix": "ZAD"},
        )
        assert resp.status_code == 403

    def test_patch_accepts_junior_partner_is_rejected(self):
        client = self._client(role="junior_partner")
        resp   = client.patch(
            "/api/v1/admin/settings/case-id-prefix",
            json={"prefix": "ZAD"},
        )
        assert resp.status_code == 403

    # ── GET ──────────────────────────────────────────────────────────────────

    def test_get_returns_current_prefix(self):
        mock_db = self._mock_db_with_doc("ZAD")
        client  = self._client(mock_db=mock_db)
        resp    = client.get("/api/v1/admin/settings/case-id-prefix")

        assert resp.status_code == 200
        assert resp.json()["prefix"] == "ZAD"

    def test_get_returns_404_when_doc_missing(self):
        mock_db = self._mock_db_no_doc()
        client  = self._client(mock_db=mock_db)
        resp    = client.get("/api/v1/admin/settings/case-id-prefix")

        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "NOT_FOUND"

    def test_get_rejects_non_admin_role(self):
        client = self._client(role="admin_staff")
        resp   = client.get("/api/v1/admin/settings/case-id-prefix")
        assert resp.status_code == 403
