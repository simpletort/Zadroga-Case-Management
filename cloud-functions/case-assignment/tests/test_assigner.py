"""
Unit tests for assigner.py

All Firestore calls are mocked — no live GCP dependency.
"""

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone

from assigner import (
    assign_case,
    _load_balance_pick,
    _round_robin_pick,
    _get_available_paralegals,
    _under_cap,
)


# ── Fixtures ───────────────────────────────────────────────────────────────

def _make_paralegal(user_id, active_count=0, max_caseload=None, created_at=None):
    return {
        "userId": user_id,
        "displayName": "Paralegal {}".format(user_id),
        "role": "Paralegal",
        "isActive": True,
        "activeCaseCount": active_count,
        "maxCaseload": max_caseload,
        "createdAt": created_at or datetime(2024, 1, 1, tzinfo=timezone.utc),
    }


def _mock_db_for_assigner(
    mode="load_balancing",
    paralegals=None,
    rr_pointer=0,
    case_already_assigned=False,
):
    """Return a mock Firestore client pre-wired for assigner tests."""
    if paralegals is None:
        paralegals = [_make_paralegal("p1"), _make_paralegal("p2"), _make_paralegal("p3")]

    db = MagicMock()

    # firmSettings/assignment_mode
    mode_snap = MagicMock()
    mode_snap.exists = True
    mode_snap.to_dict.return_value = {"value": mode}

    # firmSettings/assignment_rr_pointer
    rr_snap = MagicMock()
    rr_snap.exists = True
    rr_snap.to_dict.return_value = {"value": rr_pointer}

    def _collection_side_effect(col_name):
        col_mock = MagicMock()
        if col_name == "firmSettings":
            def _doc(doc_id):
                d = MagicMock()
                if doc_id == "assignment_mode":
                    d.get.return_value = mode_snap
                else:
                    d.get.return_value = rr_snap
                d.set = MagicMock()
                return d
            col_mock.document.side_effect = _doc
        elif col_name == "staff":
            # Simulate .where().where().stream()
            staff_docs = []
            for p in paralegals:
                doc = MagicMock()
                doc.to_dict.return_value = p
                staff_docs.append(doc)
            query = MagicMock()
            query.where.return_value = query
            query.stream.return_value = iter(staff_docs)
            col_mock.where.return_value = query
        elif col_name == "cases":
            case_doc = MagicMock()
            # sub-collection access for timeline
            case_doc.collection.return_value.document.return_value = MagicMock()

            # simulate staff + case reads inside transaction
            case_snap = MagicMock()
            existing_paralegal = "existing-p" if case_already_assigned else ""
            case_snap.to_dict.return_value = {
                "assignment": {"assignedParalegal": existing_paralegal}
            }
            case_doc.get.return_value = case_snap

            col_mock.document.return_value = case_doc

        return col_mock

    db.collection.side_effect = _collection_side_effect
    db.transaction.return_value = MagicMock()
    return db


# ── _under_cap ─────────────────────────────────────────────────────────────

def test_under_cap_no_max_caseload():
    p = _make_paralegal("p1", active_count=99, max_caseload=None)
    assert _under_cap(p) is True


def test_under_cap_under_limit():
    p = _make_paralegal("p1", active_count=4, max_caseload=5)
    assert _under_cap(p) is True


def test_under_cap_at_limit():
    p = _make_paralegal("p1", active_count=5, max_caseload=5)
    assert _under_cap(p) is False


def test_under_cap_over_limit():
    p = _make_paralegal("p1", active_count=6, max_caseload=5)
    assert _under_cap(p) is False


# ── _load_balance_pick ─────────────────────────────────────────────────────

def test_load_balance_picks_lowest_count():
    paralegals = [
        _make_paralegal("p1", active_count=5),
        _make_paralegal("p2", active_count=2),
        _make_paralegal("p3", active_count=8),
    ]
    result = _load_balance_pick(paralegals)
    assert result["userId"] == "p2"


def test_load_balance_skips_at_max_caseload():
    paralegals = [
        _make_paralegal("p1", active_count=5, max_caseload=5),  # at cap
        _make_paralegal("p2", active_count=3, max_caseload=5),  # eligible
        _make_paralegal("p3", active_count=2, max_caseload=5),  # lowest eligible
    ]
    result = _load_balance_pick(paralegals)
    assert result["userId"] == "p3"


def test_load_balance_all_at_cap_returns_none():
    paralegals = [
        _make_paralegal("p1", active_count=5, max_caseload=5),
        _make_paralegal("p2", active_count=5, max_caseload=5),
    ]
    assert _load_balance_pick(paralegals) is None


def test_load_balance_empty_list_returns_none():
    assert _load_balance_pick([]) is None


# ── _round_robin_pick ──────────────────────────────────────────────────────

def test_round_robin_distributes_evenly():
    """Calling round_robin with pointer 0,1,2 should cycle through all paralegals."""
    db = MagicMock()
    paralegals = [
        _make_paralegal("p1", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc)),
        _make_paralegal("p2", created_at=datetime(2024, 1, 2, tzinfo=timezone.utc)),
        _make_paralegal("p3", created_at=datetime(2024, 1, 3, tzinfo=timezone.utc)),
    ]

    # Simulate transaction advancing pointer: return 0, 1, 2 in sequence
    pointer_doc = MagicMock()
    call_count = {"n": 0}

    def _snap_side_effect(**kwargs):
        val = call_count["n"]
        snap = MagicMock()
        snap.exists = True
        snap.to_dict.return_value = {"value": val}
        call_count["n"] += 1
        return snap

    pointer_doc.get.side_effect = _snap_side_effect
    pointer_doc.set = MagicMock()

    firm_col = MagicMock()
    firm_col.document.return_value = pointer_doc
    db.collection.return_value = firm_col

    # Mock transaction: call decorated function directly
    with patch("assigner.firestore.transactional", lambda f: f):
        with patch("assigner.firestore.Transaction", MagicMock):
            results = [_round_robin_pick(db, paralegals) for _ in range(3)]

    assigned = [r["userId"] for r in results]
    assert set(assigned) == {"p1", "p2", "p3"}


def test_round_robin_skips_at_cap():
    """Paralegals at max caseload should be excluded from round-robin eligible list."""
    paralegals = [
        _make_paralegal("p1", active_count=5, max_caseload=5,
                         created_at=datetime(2024, 1, 1, tzinfo=timezone.utc)),
        _make_paralegal("p2", active_count=2, max_caseload=5,
                         created_at=datetime(2024, 1, 2, tzinfo=timezone.utc)),
    ]
    db = MagicMock()
    pointer_doc = MagicMock()
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = {"value": 0}
    pointer_doc.get.return_value = snap
    pointer_doc.set = MagicMock()
    db.collection.return_value.document.return_value = pointer_doc

    with patch("assigner.firestore.transactional", lambda f: f):
        with patch("assigner.firestore.Transaction", MagicMock):
            result = _round_robin_pick(db, paralegals)

    assert result is not None
    assert result["userId"] == "p2"


def test_round_robin_all_at_cap_returns_none():
    paralegals = [
        _make_paralegal("p1", active_count=5, max_caseload=5),
        _make_paralegal("p2", active_count=5, max_caseload=5),
    ]
    db = MagicMock()
    result = _round_robin_pick(db, paralegals)
    assert result is None


# ── assign_case (integration-level unit test) ──────────────────────────────

def test_assign_case_no_paralegals_returns_none():
    db = _mock_db_for_assigner(paralegals=[])
    with patch("assigner._get_available_paralegals", return_value=[]):
        result = assign_case(db, "ZAD-2024-01-0001")
    assert result is None


def test_assign_case_load_balance_success():
    paralegals = [
        _make_paralegal("p1", active_count=3),
        _make_paralegal("p2", active_count=1),
    ]

    with patch("assigner._get_available_paralegals", return_value=paralegals), \
         patch("assigner._get_setting", return_value="load_balancing"), \
         patch("assigner._do_assign") as mock_do_assign:
        result = assign_case(MagicMock(), "ZAD-2024-01-0001")

    assert result == "p2"
    mock_do_assign.assert_called_once()
    _, call_case_id, call_paralegal, call_mode = mock_do_assign.call_args[0]
    assert call_case_id == "ZAD-2024-01-0001"
    assert call_paralegal["userId"] == "p2"
    assert call_mode == "load_balancing"


def test_assign_case_round_robin_success():
    paralegals = [_make_paralegal("p1"), _make_paralegal("p2")]

    with patch("assigner._get_available_paralegals", return_value=paralegals), \
         patch("assigner._get_setting", return_value="round_robin"), \
         patch("assigner._round_robin_pick", return_value=paralegals[0]) as mock_rr, \
         patch("assigner._do_assign") as mock_do_assign:
        result = assign_case(MagicMock(), "ZAD-2024-01-0002")

    assert result == "p1"
    mock_rr.assert_called_once()
    mock_do_assign.assert_called_once()


def test_idempotency_guard_in_do_assign(mocker):
    """If case already has an assignedParalegal inside the transaction, do not overwrite."""
    db = MagicMock()
    case_ref = MagicMock()
    staff_ref = MagicMock()
    timeline_ref = MagicMock()

    case_snap = MagicMock()
    case_snap.to_dict.return_value = {
        "assignment": {"assignedParalegal": "already-assigned-uid"}
    }

    db.collection.return_value.document.return_value = case_ref
    case_ref.get.return_value = case_snap
    case_ref.collection.return_value.document.return_value = timeline_ref

    with patch("assigner.firestore.transactional", lambda f: f), \
         patch("assigner.firestore.SERVER_TIMESTAMP", "ts"):
        from assigner import _do_assign
        _do_assign(db, "ZAD-2024-01-0001", _make_paralegal("p1"), "load_balancing")

    # transaction.update should NOT have been called (case already assigned)
    case_ref.update.assert_not_called()
