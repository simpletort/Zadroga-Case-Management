"""
tests/test_rbac.py — Unit tests for auth/rbac.py (database-driven RBAC)
========================================================================
The RBAC layer reads roles and permissions from Firestore at runtime.
Tests mock the Firestore collection so no real project is required.

Run:  pytest tests/test_rbac.py -v
"""

import sys
import time
from unittest.mock import MagicMock, patch

# ── Stub firebase deps so tests run without a real project ────────────────────
_fb = MagicMock()
for mod in ["firebase_admin", "firebase_admin.firestore", "firebase_functions",
            "firebase_functions.https_fn", "firebase_functions.options"]:
    sys.modules.setdefault(mod, _fb)

_mw = MagicMock()
_mw.json_err          = lambda msg, code: ({"error": msg}, code)
_mw.json_ok           = lambda data, code=200: (data, code)
_mw.CORS_HEADERS      = {}
_mw.write_audit_event = MagicMock()
_mw.REGION            = "us-central1"
_mw.CORS_OPTIONS      = MagicMock()
_mw.handle_options    = MagicMock(return_value=None)
sys.modules.setdefault("middleware.http", _mw)
sys.modules.setdefault("middleware.jwt_middleware", _mw)
sys.modules.setdefault("config", MagicMock(Config=MagicMock(DATABASE_ID="test-db", RBAC_CACHE_TTL=300)))

import pytest
import auth.rbac as rbac_module
from auth.rbac import (
    has_permission,
    get_role_permissions,
    get_all_roles,
    get_all_role_ids,
    get_all_permissions,
    get_role_meta,
    require_permission,
    require_any,
    log_role_change,
    refresh_rbac_cache,
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
    """Return a context manager that patches db() to return fake role documents."""
    if roles is None:
        roles = _ROLES_FIXTURE
    fake_docs = [_make_fake_doc(r) for r in roles]
    fake_db = MagicMock()
    fake_db.return_value.collection.return_value.stream.return_value = iter(fake_docs)
    return patch.object(rbac_module, "db", fake_db)


def _force_cache_reload():
    """Force-expire the RBAC in-memory cache so the next call re-reads Firestore."""
    rbac_module._cache_loaded_at = float("-inf")  # guarantees stale regardless of process uptime
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
            get_all_roles()  # populate cache

        # Simulate Firestore failure on refresh
        fake_db = MagicMock()
        fake_db.return_value.collection.return_value.stream.side_effect = Exception("Firestore down")
        rbac_module._cache_loaded_at = 0.0  # mark stale but don't clear cache
        with patch.object(rbac_module, "db", fake_db):
            roles = get_all_roles()
        assert len(roles) > 0  # stale data served

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


# ── get_all_roles, get_all_role_ids, get_all_permissions, get_role_meta ───────

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
        assert "system_admin" in ids

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
        assert "permissions" not in meta  # meta only, no permission list

    def test_get_role_meta_unknown_returns_none(self):
        assert get_role_meta("nonexistent_role") is None


# ── require_permission ────────────────────────────────────────────────────────

class TestRequirePermission:
    def setup_method(self):
        _force_cache_reload()
        self._patcher = _patch_firestore()
        self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()

    def _u(self, role):
        return {"uid": "test-uid", "role": role}

    def test_passes_when_permitted(self):
        assert require_permission(self._u("admin_staff"), "staff.manage") is None

    def test_returns_response_when_denied(self):
        result = require_permission(self._u("client"), "staff.manage")
        assert result is not None

    def test_system_admin_can_use_system_admin_perm(self):
        assert require_permission(self._u("system_admin"), "system.admin") is None

    def test_paralegal_cannot_use_system_admin_perm(self):
        assert require_permission(self._u("paralegal"), "system.admin") is not None

    def test_missing_role_denied(self):
        assert require_permission({"uid": "x"}, "cases.read") is not None

    def test_writes_audit_event_on_deny(self):
        _mw.write_audit_event.reset_mock()
        require_permission(self._u("client"), "system.admin")
        _mw.write_audit_event.assert_called_once()
        assert _mw.write_audit_event.call_args[0][0] == "permission_denied"


# ── require_any ───────────────────────────────────────────────────────────────

class TestRequireAny:
    def setup_method(self):
        _force_cache_reload()
        self._patcher = _patch_firestore()
        self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()

    def _u(self, role):
        return {"uid": "test-uid", "role": role}

    def test_passes_if_first_permission_matches(self):
        assert require_any(self._u("admin_staff"), "staff.manage", "system.admin") is None

    def test_passes_if_second_permission_matches(self):
        assert require_any(self._u("junior_partner"), "system.admin", "cases.approve") is None

    def test_denied_if_none_match(self):
        assert require_any(self._u("client"), "staff.manage", "system.admin") is not None

    def test_empty_permissions_list_denied(self):
        assert require_any(self._u("senior_partner")) is not None


# ── log_role_change ───────────────────────────────────────────────────────────

class TestLogRoleChange:
    def test_calls_write_audit_event(self):
        _mw.write_audit_event.reset_mock()
        log_role_change("admin-uid", "target-uid", "client", "paralegal")
        _mw.write_audit_event.assert_called_once()
        call_args = _mw.write_audit_event.call_args
        assert call_args[0][0] == "role_change"
        assert call_args[1]["old_role"] == "client"
        assert call_args[1]["new_role"] == "paralegal"
        assert call_args[1]["target_user"] == "target-uid"
        assert call_args[1]["changed_by"] == "admin-uid"


# ── Hierarchy invariants ──────────────────────────────────────────────────────

class TestHierarchyInvariants:
    def setup_method(self):
        _force_cache_reload()
        self._patcher = _patch_firestore()
        self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()

    def test_paralegal_is_subset_of_junior_partner(self):
        para_perms   = set(get_role_permissions("paralegal"))
        junior_perms = set(get_role_permissions("junior_partner"))
        # junior_partner has all paralegal perms plus more
        shared = {"cases.read", "cases.write", "documents.verify", "tasks.assign"}
        assert shared.issubset(junior_perms)
        assert shared.issubset(para_perms)

    def test_client_cannot_approve(self):
        assert not has_permission("client", "cases.approve")

    def test_only_system_admin_has_system_admin_perm(self):
        for role in ["client", "admin_staff", "paralegal", "junior_partner", "senior_partner"]:
            assert not has_permission(role, "system.admin"), f"{role} should not have system.admin"
        assert has_permission("system_admin", "system.admin")
