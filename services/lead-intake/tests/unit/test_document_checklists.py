"""
tests/unit/test_document_checklists.py

Tests for the configurable document checklist feature:
  - DocumentChecklistsRequest validation
  - GET / PUT /api/v1/admin/settings/document-checklists endpoints
"""
from __future__ import annotations

import sys
import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../api"))

import pytest
from pydantic import ValidationError


# ── DocumentChecklistsRequest validation ─────────────────────────────────────

class TestDocumentChecklistsRequest:
    def _make(self, default, overrides=None):
        from routers.settings import DocumentChecklistsRequest
        return DocumentChecklistsRequest(default=default, overrides=overrides or {})

    def test_valid_default_only(self):
        req = self._make(["medical-records", "proof-of-presence", "id-documents"])
        assert req.default == ["medical-records", "proof-of-presence", "id-documents"]
        assert req.overrides == {}

    def test_valid_with_overrides(self):
        req = self._make(
            ["medical-records"],
            overrides={"wtc": ["medical-records", "employment-records"]},
        )
        assert req.overrides["wtc"] == ["medical-records", "employment-records"]

    def test_rejects_empty_default_list(self):
        with pytest.raises(ValidationError):
            self._make([])

    def test_overrides_defaults_to_empty_dict(self):
        from routers.settings import DocumentChecklistsRequest
        req = DocumentChecklistsRequest(default=["medical-records"])
        assert req.overrides == {}


# ── Settings router endpoints ─────────────────────────────────────────────────

def _make_partner_context(role: str = "system_admin"):
    """Build a minimal PartnerContext for auth override."""
    from middleware.auth import PartnerContext
    return PartnerContext(
        partner_id  = "test-partner",
        auth_method = "firebase_jwt",
        raw_claims  = {"role": role, "email": "admin@test.com"},
    )


class TestDocumentChecklistsRouter:
    def setup_method(self):
        from fastapi import FastAPI
        from routers.settings import router
        from middleware.auth import get_partner
        from services.firestore_client import get_db

        self.app         = FastAPI()
        self.app.include_router(router, prefix="/api/v1")
        self.get_partner = get_partner
        self.get_db      = get_db

    def _client(self, role="system_admin", mock_db=None):
        from fastapi.testclient import TestClient

        partner = _make_partner_context(role)
        self.app.dependency_overrides[self.get_partner] = lambda: partner
        self.app.dependency_overrides[self.get_db]      = lambda: mock_db or AsyncMock()
        return TestClient(self.app)

    def _mock_db_with_doc(self, default, overrides):
        """Return a MagicMock db where firmSettings/document_checklists returns the given config."""
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "default":   default,
            "overrides": overrides,
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
        """Return a MagicMock db where the firmSettings doc does not exist."""
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_doc_ref = AsyncMock()
        mock_doc_ref.get = AsyncMock(return_value=mock_doc)
        mock_col = MagicMock()
        mock_col.document.return_value = mock_doc_ref
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_col
        return mock_db

    def _mock_db_for_put(self):
        mock_db = MagicMock()
        mock_col = MagicMock()
        mock_doc_ref = AsyncMock()
        mock_doc_ref.set = AsyncMock()
        mock_col.document.return_value = mock_doc_ref
        mock_db.collection.return_value = mock_col
        return mock_db, mock_doc_ref

    # ── GET ──────────────────────────────────────────────────────────────────

    def test_get_returns_configured_checklist(self):
        mock_db = self._mock_db_with_doc(
            default=["medical-records", "proof-of-presence", "id-documents"],
            overrides={"wtc": ["medical-records", "proof-of-presence", "id-documents", "employment-records"]},
        )
        client = self._client(mock_db=mock_db)
        resp   = client.get("/api/v1/admin/settings/document-checklists")

        assert resp.status_code == 200
        data = resp.json()
        assert data["default"] == ["medical-records", "proof-of-presence", "id-documents"]
        assert data["overrides"]["wtc"] == ["medical-records", "proof-of-presence", "id-documents", "employment-records"]

    def test_get_returns_default_when_doc_missing(self):
        mock_db = self._mock_db_no_doc()
        client  = self._client(mock_db=mock_db)
        resp    = client.get("/api/v1/admin/settings/document-checklists")

        assert resp.status_code == 200
        data = resp.json()
        assert data["default"] == ["medical-records", "proof-of-presence", "id-documents"]
        assert data["overrides"] == {}

    def test_get_rejects_non_admin_role(self):
        client = self._client(role="paralegal")
        resp   = client.get("/api/v1/admin/settings/document-checklists")
        assert resp.status_code == 403

    # ── PUT ──────────────────────────────────────────────────────────────────

    def test_put_updates_firestore_and_returns_200(self):
        mock_db, mock_doc_ref = self._mock_db_for_put()
        client = self._client(mock_db=mock_db)
        resp   = client.put(
            "/api/v1/admin/settings/document-checklists",
            json={
                "default":   ["medical-records", "proof-of-presence", "id-documents"],
                "overrides": {"wtc": ["medical-records", "proof-of-presence", "id-documents", "employment-records"]},
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["default"] == ["medical-records", "proof-of-presence", "id-documents"]
        assert data["overrides"]["wtc"] == ["medical-records", "proof-of-presence", "id-documents", "employment-records"]
        assert data["updatedBy"] == "admin@test.com"
        mock_doc_ref.set.assert_awaited_once()

    def test_put_writes_full_replacement_not_merge(self):
        mock_db, mock_doc_ref = self._mock_db_for_put()
        client = self._client(mock_db=mock_db)
        client.put(
            "/api/v1/admin/settings/document-checklists",
            json={"default": ["medical-records"], "overrides": {}},
        )

        _, kwargs = mock_doc_ref.set.await_args
        assert kwargs.get("merge") is False

    def test_put_rejects_empty_default_list(self):
        client = self._client()
        resp   = client.put(
            "/api/v1/admin/settings/document-checklists",
            json={"default": [], "overrides": {}},
        )
        assert resp.status_code == 422

    def test_put_rejects_non_admin_role(self):
        mock_db, _ = self._mock_db_for_put()
        client = self._client(role="paralegal", mock_db=mock_db)
        resp   = client.put(
            "/api/v1/admin/settings/document-checklists",
            json={"default": ["medical-records"], "overrides": {}},
        )
        assert resp.status_code == 403

    def test_put_rejects_junior_partner(self):
        client = self._client(role="junior_partner")
        resp   = client.put(
            "/api/v1/admin/settings/document-checklists",
            json={"default": ["medical-records"], "overrides": {}},
        )
        assert resp.status_code == 403

    def test_get_then_put_then_get_reflects_update(self):
        """PUT followed by GET (against the same underlying doc state) reflects the new config."""
        mock_db, mock_doc_ref = self._mock_db_for_put()
        client = self._client(mock_db=mock_db)

        put_resp = client.put(
            "/api/v1/admin/settings/document-checklists",
            json={"default": ["id-documents"], "overrides": {"vcf": ["id-documents", "vcf-registration"]}},
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["default"] == ["id-documents"]
        assert put_resp.json()["overrides"]["vcf"] == ["id-documents", "vcf-registration"]
