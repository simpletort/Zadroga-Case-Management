"""
app/services/rbac_service.py — Role-Based Access Control & Audit Log
=====================================================================
Fully database-driven. No role IDs, permission strings, or descriptions
are hardcoded here. Everything is read from the `roles` collection in
Firestore (simpletort-dev database).

Public API
──────────
  refresh_rbac_cache()
  get_all_roles()        → List[dict]
  get_all_role_ids()     → List[str]
  get_all_permissions()  → List[str]
  get_role_meta(role_id) → dict | None
  get_role_display_name(role_id) → str
  has_permission(role, permission) → bool
  get_role_permissions(role)       → List[str]
  write_audit_event(event_type, **fields) → None
  serialise_doc(doc_dict, *, strip_phi, ...) → dict
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── PHI fields stripped when strip_phi=True ───────────────────────────────────
PHI_FIELDS: frozenset[str] = frozenset({"phi_data", "ssn", "dob", "medical_info"})

# ── Cache state ───────────────────────────────────────────────────────────────
_CACHE_TTL_SECONDS: int = 300
_cache_lock = threading.Lock()
_cache_loaded_at: float = float("-inf")
_roles_cache: Dict[str, dict] = {}


def _get_db():
    from app.utils.firestore import get_firestore_client
    return get_firestore_client()


def _cache_is_stale() -> bool:
    return (time.monotonic() - _cache_loaded_at) > _CACHE_TTL_SECONDS


def _load_roles_from_firestore() -> Dict[str, dict]:
    docs = _get_db().collection("roles").stream()
    result: Dict[str, dict] = {}
    for doc in docs:
        data = doc.to_dict() or {}
        role_id_field = data.get("roleId", "").strip()
        canonical_key = role_id_field or doc.id
        raw_perms = data.get("permissions", [])
        if not isinstance(raw_perms, list):
            raw_perms = []
        role_record = {
            "roleId":      canonical_key,
            "displayName": data.get("displayName", canonical_key),
            "description": data.get("description", ""),
            "permissions": frozenset(str(p) for p in raw_perms if p),
        }
        result[canonical_key] = role_record
        if canonical_key != doc.id:
            result[doc.id] = role_record
    return result


def _ensure_cache_fresh() -> None:
    global _roles_cache, _cache_loaded_at
    if not _cache_is_stale():
        return
    with _cache_lock:
        if not _cache_is_stale():
            return
        try:
            fresh = _load_roles_from_firestore()
            _roles_cache = fresh
            _cache_loaded_at = time.monotonic()
            logger.info("RBAC cache refreshed: %d roles loaded", len(fresh))
        except Exception as exc:
            if _roles_cache:
                logger.error("RBAC cache refresh failed — serving stale data: %s", exc)
            else:
                logger.critical("RBAC initial load failed and cache is empty: %s", exc)
                raise


def _role_record(role_id: str) -> dict:
    _ensure_cache_fresh()
    return _roles_cache.get(role_id, {
        "roleId": role_id,
        "displayName": role_id,
        "description": "",
        "permissions": frozenset(),
    })


# ── Public cache control ──────────────────────────────────────────────────────

def refresh_rbac_cache() -> None:
    global _cache_loaded_at
    with _cache_lock:
        _cache_loaded_at = float("-inf")
    _ensure_cache_fresh()
    logger.info("RBAC cache force-refreshed.")


# ── Discovery helpers ─────────────────────────────────────────────────────────

def get_all_roles() -> List[dict]:
    _ensure_cache_fresh()
    seen: set = set()
    roles: List[dict] = []
    for record in _roles_cache.values():
        rid = record["roleId"]
        if rid in seen:
            continue
        seen.add(rid)
        roles.append({
            "roleId":      rid,
            "displayName": record["displayName"],
            "description": record["description"],
            "permissions": sorted(record["permissions"]),
        })
    return sorted(roles, key=lambda r: r["roleId"])


def get_all_role_ids() -> List[str]:
    return [r["roleId"] for r in get_all_roles()]


def get_role_display_name(role_id: str) -> str:
    return _role_record(role_id).get("displayName", role_id)


def get_all_permissions() -> List[str]:
    _ensure_cache_fresh()
    all_perms: set = set()
    for record in _roles_cache.values():
        all_perms.update(record["permissions"])
    return sorted(all_perms)


def get_role_meta(role_id: str) -> Optional[dict]:
    _ensure_cache_fresh()
    record = _roles_cache.get(role_id)
    if record is None:
        return None
    return {
        "roleId":      record["roleId"],
        "displayName": record["displayName"],
        "description": record["description"],
    }


# ── Core lookup ───────────────────────────────────────────────────────────────

def has_permission(role: str, permission: str) -> bool:
    return permission in _role_record(role)["permissions"]


def get_role_permissions(role: str) -> List[str]:
    return sorted(_role_record(role)["permissions"])


# ── Audit helpers ─────────────────────────────────────────────────────────────

def write_audit_event(event_type: str, **fields: Any) -> None:
    from firebase_admin import firestore as _fs
    SERVER_TIMESTAMP = _fs.SERVER_TIMESTAMP
    try:
        payload = {
            "event_type": event_type,
            "timestamp":  SERVER_TIMESTAMP,
            **fields,
        }
        _get_db().collection("auditLog").add(payload)
    except Exception as exc:
        logger.error("Failed to write audit event '%s': %s", event_type, exc)


def log_role_change(
    changed_by: str, target_uid: str, old_role: str, new_role: str
) -> None:
    write_audit_event(
        "role_change",
        changed_by=changed_by,
        target_user=target_uid,
        old_role=old_role,
        new_role=new_role,
    )


# ── Firestore document serialization ─────────────────────────────────────────

def _serialise_value(v: Any) -> Any:
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _serialise_value(vv) for k, vv in v.items()}
    if isinstance(v, list):
        return [_serialise_value(item) for item in v]
    return v


def serialise_doc(
    doc_dict: dict,
    *,
    strip_phi: bool = False,
) -> dict:
    d = dict(doc_dict)
    if strip_phi:
        for field in PHI_FIELDS:
            d.pop(field, None)
    return {k: _serialise_value(v) for k, v in d.items()}
