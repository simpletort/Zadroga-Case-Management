"""
tests/test_template_service.py — Unit tests for services/template_service.py

Covers
------
- fetch_template: document found + active
- fetch_template: document not found → TemplateNotFoundError
- fetch_template: document found but active=False → TemplateDisabledError
- render_template: all variables resolved
- render_template: unknown placeholder left intact (safe format-map)
- render_template: empty variables dict
- fetch_and_render: integration of fetch + render
- fetch_and_render: propagates TemplateNotFoundError
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from services.template_service import (
    TemplateDisabledError,
    TemplateNotFoundError,
    fetch_and_render,
    fetch_template,
    render_template,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_doc(exists: bool, data: dict | None = None) -> MagicMock:
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data or {}
    return snap


def _make_db(doc_data: dict | None = None, doc_exists: bool = True) -> AsyncMock:
    """Build a minimal async Firestore client stub."""
    snap = _make_doc(doc_exists, doc_data)
    doc_ref = AsyncMock()
    doc_ref.get = AsyncMock(return_value=snap)
    col = MagicMock()
    col.document = MagicMock(return_value=doc_ref)
    db = AsyncMock()
    db.collection = MagicMock(return_value=col)
    return db


# ── fetch_template ────────────────────────────────────────────────────────────

class TestFetchTemplate:

    @pytest.mark.asyncio
    async def test_returns_template_dict_when_found_and_active(self):
        template_data = {
            "templateId": "welcome_sms",
            "name": "Welcome SMS",
            "body": "Hi {first_name}, case {case_id} received.",
            "active": True,
        }
        db = _make_db(template_data, doc_exists=True)

        result = await fetch_template("welcome_sms", db)

        assert result["templateId"] == "welcome_sms"
        assert result["body"] == "Hi {first_name}, case {case_id} received."

    @pytest.mark.asyncio
    async def test_raises_not_found_when_document_missing(self):
        db = _make_db(doc_exists=False)

        with pytest.raises(TemplateNotFoundError, match="welcome_sms"):
            await fetch_template("welcome_sms", db)

    @pytest.mark.asyncio
    async def test_raises_disabled_when_active_is_false(self):
        template_data = {"templateId": "t1", "body": "Hello", "active": False}
        db = _make_db(template_data, doc_exists=True)

        with pytest.raises(TemplateDisabledError, match="t1"):
            await fetch_template("t1", db)

    @pytest.mark.asyncio
    async def test_active_defaults_to_true_when_field_absent(self):
        """If the 'active' field is missing it should default to True (not disabled)."""
        template_data = {"templateId": "t2", "body": "Hello {name}"}
        db = _make_db(template_data, doc_exists=True)

        result = await fetch_template("t2", db)
        assert result["body"] == "Hello {name}"

    @pytest.mark.asyncio
    async def test_firestore_collection_name_is_correct(self):
        """fetch_template must query the sms_templates collection."""
        db = _make_db({"body": "Hi", "active": True}, doc_exists=True)

        await fetch_template("my_template", db)

        # The collection name should come from settings
        from config import get_settings
        expected_col = get_settings().sms_templates_collection
        db.collection.assert_called_once_with(expected_col)
        db.collection.return_value.document.assert_called_once_with("my_template")


# ── render_template ───────────────────────────────────────────────────────────

class TestRenderTemplate:

    def test_all_variables_substituted(self):
        body = "Hi {first_name}, your case {case_id} is under review."
        variables = {"first_name": "Jane", "case_id": "ZAD-2025-03-0001"}

        result = render_template(body, variables)

        assert result == "Hi Jane, your case ZAD-2025-03-0001 is under review."

    def test_unknown_placeholder_left_intact(self):
        """Missing variables must NOT raise KeyError — leave placeholder as-is."""
        body = "Hi {first_name}, your ref is {unknown_var}."
        variables = {"first_name": "Bob"}

        result = render_template(body, variables)

        assert result == "Hi Bob, your ref is {unknown_var}."

    def test_empty_variables_leaves_all_placeholders(self):
        body = "Hello {name}, case {id}."
        result = render_template(body, {})
        assert result == "Hello {name}, case {id}."

    def test_no_placeholders_returns_body_unchanged(self):
        body = "Your case has been received. We will be in touch."
        result = render_template(body, {"irrelevant": "value"})
        assert result == body

    def test_extra_variables_are_ignored(self):
        """Variables that don't appear in the template are silently ignored."""
        body = "Hi {name}."
        result = render_template(body, {"name": "Alice", "extra": "ignored"})
        assert result == "Hi Alice."

    def test_numeric_values_are_coerced_to_string(self):
        body = "You have {count} documents."
        result = render_template(body, {"count": 3})
        assert result == "You have 3 documents."

    def test_special_characters_in_value_not_escaped(self):
        body = "Note: {note}"
        result = render_template(body, {"note": "Use <form> & 'quotes'"})
        assert result == "Note: Use <form> & 'quotes'"


# ── fetch_and_render ──────────────────────────────────────────────────────────

class TestFetchAndRender:

    @pytest.mark.asyncio
    async def test_full_pipeline_returns_rendered_string(self):
        template_data = {
            "body": "Hi {first_name}, case {case_id} received.",
            "active": True,
        }
        db = _make_db(template_data, doc_exists=True)

        result = await fetch_and_render(
            "welcome_sms",
            {"first_name": "Tom", "case_id": "ZAD-2025-01-0007"},
            db,
        )

        assert result == "Hi Tom, case ZAD-2025-01-0007 received."

    @pytest.mark.asyncio
    async def test_propagates_template_not_found(self):
        db = _make_db(doc_exists=False)

        with pytest.raises(TemplateNotFoundError):
            await fetch_and_render("missing_template", {}, db)

    @pytest.mark.asyncio
    async def test_propagates_template_disabled(self):
        db = _make_db({"body": "Hi", "active": False}, doc_exists=True)

        with pytest.raises(TemplateDisabledError):
            await fetch_and_render("disabled_template", {}, db)
