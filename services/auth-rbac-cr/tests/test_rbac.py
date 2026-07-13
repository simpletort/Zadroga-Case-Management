"""
tests/test_rbac.py — Unit tests for app/services/rbac_service.py
================================================================
Tests mock Firestore so no real GCP project is required.

Run:  pytest tests/test_rbac.py -v
"""

import sys
import time
from unittest.mock import MagicMock, patch

# ── Stub firebase and GCP deps so tests run without a real project ────────────
_fb = MagicMock()
for mod in [
    "firebase_admin", "firebase_admin.auth", "firebase_admin.credentials",
    "google.cloud.firestore", "google.cloud.firestore_v1",
]:
    sys.modules.setdefault(mod, _fb)

# Stub the firestore client getter so rbac_service doesn't call real Firestore
_fake_db = MagicMock()
sys.modules.setdefault("app.utils.firestore", MagicMock(get_firestore_client=lambda: _fake_db))
sys.modules.setdefault("app.config", MagicMock(get_settings=MagicMock(return_value=MagicMock(
    gcp_project_id="test-project",
    firestore_database_id="test-db",
    rbac_cache_ttl=300,
))))

import pytest
import app.services.rbac_service as rbac_module
from app.services.rbac_service import (
    has_permission,
    get_role_permissions,
    get_all_roles,
    get_all_role_ids,
    get_all_permissions,
    get_role_meta,
    refresh_rbac_cache,
    log_role_change,
    write_audit_event,
)


# ── Test role data — mirrors the Firestore roles collection schema ─────────────

_ROLES_FIXTURE = [
    {
        "roleId":      "client",
        "displayName": "Client",
        "description": "End client — limited read access",
        "permissions": ["cases.read", "documents.read", "documents.upload",
                        "communications.read", "timeline.read",
                        "storage.signed_url", "storage.upload.write",
                        "storage.upload.read", "storage.documents.read"],
    },
    {
        "roleId":      "admin_staff",
        "displayName": "Admin Staff",
        "description": "Front-office staff",
        "permissions": ["cases.read", "cases.write", "cases.status.update",
                        "clients.read", "clients.write",
                        "documents.read", "documents.upload",
                        "tasks.read", "tasks.write", "tasks.complete",
                        "communications.read", "communications.write",
                        "timeline.read", "expenses.read", "expenses.write",
                        "disbursements.read", "staff.read", "staff.manage",
                        "storage.signed_url", "storage.metadata.read",
                        "storage.upload.write", "storage.upload.read",
                        "storage.documents.read", "storage.documents.write"],
    },
    {
        "roleId":      "paralegal",
        "displayName": "Paralegal",
        "description": "Paralegal — document review and case handling",
        "permissions": ["cases.read", "cases.write", "cases.status.update",
                        "clients.read", "clients.write",
                        "documents.read", "documents.upload", "documents.verify",
                        "tasks.read", "tasks.write", "tasks.complete", "tasks.assign",
                        "communications.read", "communications.write",
                        "timeline.read", "expenses.read", "expenses.write",
                        "disbursements.read", "staff.read", "reports.read",
                        "storage.signed_url", "storage.metadata.read",
                        "storage.upload.write", "storage.upload.read",
                        "storage.documents.read", "storage.documents.write"],
    },
    {
        "roleId":      "junior_partner",
        "displayName": "Junior Partner",
        "description": "Attorney — case approval and escalation",
        "permissions": ["cases.read", "cases.write", "cases.status.update", "cases.approve",
                        "clients.read", "clients.write",
                        "documents.read", "documents.upload", "documents.verify",
                        "tasks.read", "tasks.write", "tasks.complete",
                        "tasks.assign", "tasks.skip",
                        "communications.read", "communications.write",
                        "timeline.read", "expenses.read", "expenses.write",
                        "disbursements.read", "disbursements.write",
                        "staff.read", "reports.read", "analytics.read",
                        "settings.read", "auditLog.read",
                        "storage.signed_url", "storage.metadata.read",
                        "storage.upload.write", "storage.upload.read",
                        "storage.documents.read", "storage.documents.write",
                        "storage.lifecycle.read", "storage.hold.write"],
    },
    {
        "roleId":      "senior_partner",
        "displayName": "Senior Partner",
        "description": "Full access except system administration",
        "permissions": ["cases.read", "cases.write", "cases.status.update",
                        "cases.approve", "cases.delete",
                        "clients.read", "clients.write",
                        "documents.read", "documents.upload", "documents.verify",
                        "documents.override",
                        "tasks.read", "tasks.write", "tasks.complete",
                        "tasks.assign", "tasks.skip", "tasks.delete",
                        "communications.read", "communications.write",
                        "timeline.read", "expenses.read", "expenses.write",
                        "disbursements.read", "disbursements.write", "disbursements.approve",
                        "staff.read", "staff.write", "staff.manage",
                        "reports.read", "analytics.read",
                        "settings.read", "settings.write", "auditLog.read",
                        "storage.signed_url", "storage.metadata.read",
                        "storage.lifecycle.read", "storage.lifecycle.write",
                        "storage.hold.write", "storage.upload.write", "storage.upload.read",
                        "storage.documents.read", "storage.documents.write"],
    },
    {
        "roleId":      "system_admin",
        "displayName": "System Admin",
        "description": "Full platform access including role management",
        "permissions": ["system.admin", "staff.manage", "auditLog.read",
                        "cases.read", "cases.write", "cases.delete",
                        "settings.read", "settings.write"],
    },
]


def _make_fake_doc(data: dict):
    doc = MagicMock()
    doc.id = data["roleId"]
    doc.to_dict.return_value = data
    return doc


def _patch_firestore(roles=None):
    if roles is None:
        roles = _ROLES_FIXTURE
    fake_docs = [_make_fake_doc(r) for r in roles]
    fake_db = MagicMock()
    fake_db.return_value.collection.return_value.stream.return_value = iter(fake_docs)
    return patch.object(rbac_module, "_get_db", fake_db)


def _force_cache_reload():
    rbac_module._cache_loaded_at = float("-inf")
    rbac_module._roles_cache = {}


# ── Cache loading ─────────────────────────────────────────────────────────────

class TestCacheLoading:
    def test_loads_all_roles(self):
        _force_cache_reload()
        with _patch_firestore():
            roles = get_all_roles()
        assert len(roles) == len(_ROLES_FIXTURE)
        role_ids = {r["roleId"] for r in roles}
        assert "admin_staff" in role_ids
        assert "system_admin" in role_ids

    def test_permissions_stored_as_frozenset(self):
        _force_cache_reload()
        with _patch_firestore():
            rbac_module._ensure_cache_fresh()
        for record in rbac_module._roles_cache.values():
            assert isinstance(record["permissions"], frozenset)

    def test_serves_stale_data_on_refresh_failure(self):
        _force_cache_reload()
        with _patch_firestore():
            get_all_roles()

        fake_db = MagicMock()
        fake_db.return_value.collection.return_value.stream.side_effect = Exception("Firestore down")
        rbac_module._cache_loaded_at = 0.0
        with patch.object(rbac_module, "_get_db", fake_db):
            roles = get_all_roles()
        assert len(roles) > 0

    def test_empty_permissions_field_defaults_to_empty(self):
        role_with_no_perms = [{"roleId": "empty_role", "displayName": "Empty", "description": ""}]
        _force_cache_reload()
        with _patch_firestore(roles=role_with_no_perms):
            perms = get_role_permissions("empty_role")
        assert perms == []


# ── has_permission ────────────────────────────────────────────────────────────

class TestHasPermission:
    def setup_method(self):
        _force_cache_reload()
        self._patcher = _patch_firestore()
        self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()

    def test_admin_staff_has_staff_manage(self):
        assert has_permission("admin_staff", "staff.manage")

    def test_client_does_not_have_staff_manage(self):
        assert not has_permission("client", "staff.manage")

    def test_junior_partner_can_approve(self):
        assert has_permission("junior_partner", "cases.approve")

    def test_paralegal_cannot_approve(self):
        assert not has_permission("paralegal", "cases.approve")

    def test_system_admin_has_system_admin(self):
        assert has_permission("system_admin", "system.admin")

    def test_client_cannot_use_system_admin(self):
        assert not has_permission("client", "system.admin")

    def test_unknown_role_returns_false(self):
        assert not has_permission("hacker", "cases.read")

    def test_empty_role_returns_false(self):
        assert not has_permission("", "cases.read")

    def test_senior_partner_has_all_standard_perms(self):
        assert has_permission("senior_partner", "disbursements.approve")
        assert has_permission("senior_partner", "documents.override")
        assert has_permission("senior_partner", "staff.manage")


# ── get_role_permissions ──────────────────────────────────────────────────────

class TestGetRolePermissions:
    def setup_method(self):
        _force_cache_reload()
        self._patcher = _patch_firestore()
        self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()

    def test_returns_sorted_list(self):
        perms = get_role_permissions("admin_staff")
        assert perms == sorted(perms)

    def test_unknown_role_returns_empty(self):
        assert get_role_permissions("ghost") == []

    def test_paralegal_has_documents_verify(self):
        assert "documents.verify" in get_role_permissions("paralegal")

    def test_client_does_not_have_documents_verify(self):
        assert "documents.verify" not in get_role_permissions("client")


# ── Discovery ─────────────────────────────────────────────────────────────────

class TestDiscovery:
    def setup_method(self):
        _force_cache_reload()
        self._patcher = _patch_firestore()
        self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()

    def test_get_all_roles_deduplicates(self):
        roles = get_all_roles()
        role_ids = [r["roleId"] for r in roles]
        assert len(role_ids) == len(set(role_ids))

    def test_get_all_roles_sorted(self):
        roles = get_all_roles()
        ids = [r["roleId"] for r in roles]
        assert ids == sorted(ids)

    def test_get_all_role_ids_sorted(self):
        ids = get_all_role_ids()
        assert ids == sorted(ids)
        assert "admin_staff" in ids

    def test_get_all_permissions_sorted_and_deduped(self):
        perms = get_all_permissions()
        assert perms == sorted(perms)
        assert len(perms) == len(set(perms))
        assert "cases.read" in perms
        assert "system.admin" in perms

    def test_get_role_meta_returns_metadata(self):
        meta = get_role_meta("paralegal")
        assert meta is not None
        assert meta["roleId"] == "paralegal"
        assert meta["displayName"] == "Paralegal"
        assert "permissions" not in meta

    def test_get_role_meta_unknown_returns_none(self):
        assert get_role_meta("nonexistent_role") is None


# ── Hierarchy invariants ──────────────────────────────────────────────────────

class TestHierarchyInvariants:
    def setup_method(self):
        _force_cache_reload()
        self._patcher = _patch_firestore()
        self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()

    def test_paralegal_is_subset_of_junior_partner(self):
        shared = {"cases.read", "cases.write", "documents.verify", "tasks.assign"}
        junior_perms = set(get_role_permissions("junior_partner"))
        para_perms   = set(get_role_permissions("paralegal"))
        assert shared.issubset(junior_perms)
        assert shared.issubset(para_perms)

    def test_client_cannot_approve(self):
        assert not has_permission("client", "cases.approve")

    def test_only_system_admin_has_system_admin_perm(self):
        for role in ["client", "admin_staff", "paralegal", "junior_partner", "senior_partner"]:
            assert not has_permission(role, "system.admin"), f"{role} should not have system.admin"
        assert has_permission("system_admin", "system.admin")


# ── log_role_change ───────────────────────────────────────────────────────────

class TestLogRoleChange:
    def test_calls_write_audit_event(self):
        mock_write = MagicMock()
        with patch.object(rbac_module, "write_audit_event", mock_write):
            _force_cache_reload()
            with _patch_firestore():
                log_role_change("admin-uid", "target-uid", "client", "paralegal")
        mock_write.assert_called_once()
        call_args = mock_write.call_args
        assert call_args[0][0] == "role_change"
        assert call_args[1]["old_role"] == "client"
        assert call_args[1]["new_role"] == "paralegal"
        assert call_args[1]["target_user"] == "target-uid"
        assert call_args[1]["changed_by"] == "admin-uid"
