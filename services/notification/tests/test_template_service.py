"""
tests/test_template_service.py — Unit tests for services/template_service.py

Covers
------
render_template (primary API — double-brace {{}} syntax + strict validation)
  - Happy path: all variables supplied → RenderedTemplate with correct fields
  - Missing variable: one or more {{placeholder}} absent → MissingVariableError
    with descriptive message listing exactly which variables are missing
  - Unknown templateId → TemplateNotFoundError propagated
  - Empty variable map with placeholders → MissingVariableError
  - Template with no placeholders + empty variables → succeeds
  - subject and htmlBody fields rendered alongside body
  - htmlBody auto-generated from sms_safe when template has no htmlBody field
  - Disabled template → TemplateDisabledError propagated

fetch_template (low-level Firestore fetch)
  - Document found and active → returns raw dict
  - Document not found → TemplateNotFoundError
  - isActive=False → TemplateDisabledError  (current Firestore schema)
  - active=False   → TemplateDisabledError  (legacy schema fallback)
  - isActive absent, active absent → defaults to active (True)
  - Queries correct collection/document path

MissingVariableError
  - Exception message lists missing variable names
  - .missing attribute is sorted
  - Multiple missing variables all listed

RenderedTemplate
  - Dataclass fields accessible as subject / html_body / sms_safe

fetch_and_render (legacy helper — backward-compat)
  - Returns rendered SMS body string (double-brace template)
  - Returns rendered SMS body string (single-brace template)
  - Propagates TemplateNotFoundError
  - Propagates TemplateDisabledError
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from services.template_service import (
    MissingVariableError,
    RenderedTemplate,
    TemplateDisabledError,
    TemplateNotFoundError,
    fetch_and_render,
    fetch_template,
    render_template,
)


# ── Firestore stub helpers ────────────────────────────────────────────────────

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


def _active_template(**extra) -> dict:
    """Return a minimal active template dict, optionally overriding fields."""
    base = {
        "templateId": "welcome_sms",
        "name": "Welcome SMS",
        "body": "Hi {{clientName}}, your Zadroga case {{caseId}} has been received.",
        "subject": "",
        "isActive": True,
    }
    base.update(extra)
    return base


# ── render_template — happy path ──────────────────────────────────────────────

class TestRenderTemplateHappyPath:

    @pytest.mark.asyncio
    async def test_returns_rendered_template_dataclass(self):
        db = _make_db(_active_template())
        result = await render_template(
            "welcome_sms",
            {"clientName": "Jane Doe", "caseId": "ZAD-2026-001"},
            db,
        )
        assert isinstance(result, RenderedTemplate)

    @pytest.mark.asyncio
    async def test_sms_safe_substitutes_all_variables(self):
        db = _make_db(_active_template())
        result = await render_template(
            "welcome_sms",
            {"clientName": "Jane Doe", "caseId": "ZAD-2026-001"},
            db,
        )
        assert result.sms_safe == (
            "Hi Jane Doe, your Zadroga case ZAD-2026-001 has been received."
        )

    @pytest.mark.asyncio
    async def test_subject_field_rendered(self):
        tmpl = _active_template(subject="Case {{caseId}} — Zadroga Claim Update")
        db = _make_db(tmpl)
        result = await render_template(
            "welcome_sms",
            {"clientName": "John", "caseId": "ZAD-2026-002"},
            db,
        )
        assert result.subject == "Case ZAD-2026-002 — Zadroga Claim Update"

    @pytest.mark.asyncio
    async def test_html_body_rendered_from_dedicated_field(self):
        tmpl = _active_template(htmlBody="<p>Hi {{clientName}},</p><p>Case {{caseId}}.</p>")
        db = _make_db(tmpl)
        result = await render_template(
            "welcome_sms",
            {"clientName": "Alice", "caseId": "ZAD-2026-003"},
            db,
        )
        assert result.html_body == "<p>Hi Alice,</p><p>Case ZAD-2026-003.</p>"

    @pytest.mark.asyncio
    async def test_html_body_auto_generated_when_field_absent(self):
        """When no htmlBody in template, html_body = sms_safe with \\n→<br>."""
        tmpl = _active_template(body="Line one\nLine two {{clientName}}")
        del tmpl["subject"]  # ensure missing subject is handled too
        db = _make_db(tmpl)
        result = await render_template(
            "welcome_sms",
            {"clientName": "Bob", "caseId": "ZAD-2026-004"},
            db,
        )
        assert result.html_body == "Line one<br>Line two Bob"

    @pytest.mark.asyncio
    async def test_template_with_no_placeholders_and_empty_variables(self):
        tmpl = _active_template(body="Your claim has been received. We will contact you shortly.")
        db = _make_db(tmpl)
        result = await render_template("welcome_sms", {}, db)
        assert result.sms_safe == (
            "Your claim has been received. We will contact you shortly."
        )

    @pytest.mark.asyncio
    async def test_extra_variables_are_silently_ignored(self):
        """Variables not referenced in any template field do not cause errors."""
        db = _make_db(_active_template())
        result = await render_template(
            "welcome_sms",
            {"clientName": "Sam", "caseId": "ZAD-2026-005", "extra": "ignored"},
            db,
        )
        assert "Sam" in result.sms_safe
        assert "ignored" not in result.sms_safe

    @pytest.mark.asyncio
    async def test_numeric_variable_values_coerced_to_string(self):
        tmpl = _active_template(body="You have {{count}} documents on file.")
        db = _make_db(tmpl)
        result = await render_template("welcome_sms", {"count": 7}, db)
        assert result.sms_safe == "You have 7 documents on file."

    @pytest.mark.asyncio
    async def test_empty_subject_stays_empty(self):
        db = _make_db(_active_template(subject=""))
        result = await render_template(
            "welcome_sms",
            {"clientName": "Lee", "caseId": "ZAD-2026-006"},
            db,
        )
        assert result.subject == ""


# ── render_template — MissingVariableError ────────────────────────────────────

class TestRenderTemplateMissingVariable:

    @pytest.mark.asyncio
    async def test_raises_when_one_variable_missing(self):
        db = _make_db(_active_template())
        # Provide caseId but NOT clientName
        with pytest.raises(MissingVariableError) as exc_info:
            await render_template("welcome_sms", {"caseId": "ZAD-2026-001"}, db)

        assert "clientName" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_when_multiple_variables_missing(self):
        db = _make_db(_active_template())
        with pytest.raises(MissingVariableError) as exc_info:
            await render_template("welcome_sms", {}, db)

        error_msg = str(exc_info.value)
        assert "clientName" in error_msg
        assert "caseId" in error_msg

    @pytest.mark.asyncio
    async def test_error_message_names_template(self):
        db = _make_db(_active_template())
        with pytest.raises(MissingVariableError) as exc_info:
            await render_template("welcome_sms", {}, db)

        assert "welcome_sms" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_attribute_contains_sorted_list(self):
        db = _make_db(_active_template())
        with pytest.raises(MissingVariableError) as exc_info:
            await render_template("welcome_sms", {}, db)

        exc = exc_info.value
        assert exc.missing == sorted(exc.missing)
        assert "caseId" in exc.missing
        assert "clientName" in exc.missing

    @pytest.mark.asyncio
    async def test_empty_variables_map_raises_when_placeholders_exist(self):
        db = _make_db(_active_template())
        with pytest.raises(MissingVariableError):
            await render_template("welcome_sms", {}, db)

    @pytest.mark.asyncio
    async def test_missing_variable_in_subject_detected(self):
        tmpl = _active_template(
            body="Hi {{clientName}}.",
            subject="Re: case {{caseId}} — {{missingField}}",
        )
        db = _make_db(tmpl)
        with pytest.raises(MissingVariableError) as exc_info:
            await render_template(
                "welcome_sms",
                {"clientName": "Jo", "caseId": "ZAD-001"},
                db,
            )
        assert "missingField" in exc_info.value.missing

    @pytest.mark.asyncio
    async def test_missing_variable_in_html_body_detected(self):
        tmpl = _active_template(htmlBody="<p>{{orphanVar}}</p>")
        db = _make_db(tmpl)
        with pytest.raises(MissingVariableError) as exc_info:
            await render_template(
                "welcome_sms",
                {"clientName": "Jo", "caseId": "ZAD-001"},
                db,
            )
        assert "orphanVar" in exc_info.value.missing


# ── render_template — template lookup errors ──────────────────────────────────

class TestRenderTemplateNotFound:

    @pytest.mark.asyncio
    async def test_raises_template_not_found_for_unknown_id(self):
        db = _make_db(doc_exists=False)
        with pytest.raises(TemplateNotFoundError, match="unknown_template"):
            await render_template("unknown_template", {}, db)

    @pytest.mark.asyncio
    async def test_raises_template_disabled_when_is_active_false(self):
        tmpl = _active_template(isActive=False)
        db = _make_db(tmpl)
        with pytest.raises(TemplateDisabledError, match="welcome_sms"):
            await render_template(
                "welcome_sms",
                {"clientName": "Jo", "caseId": "ZAD-001"},
                db,
            )


# ── MissingVariableError standalone ──────────────────────────────────────────

class TestMissingVariableError:

    def test_message_lists_all_missing_variables(self):
        exc = MissingVariableError("welcome_sms", ["caseId", "clientName"])
        msg = str(exc)
        assert "caseId" in msg
        assert "clientName" in msg
        assert "welcome_sms" in msg

    def test_missing_attribute_is_sorted(self):
        exc = MissingVariableError("t1", ["zzz", "aaa", "mmm"])
        assert exc.missing == ["aaa", "mmm", "zzz"]

    def test_template_id_attribute(self):
        exc = MissingVariableError("my_template", ["x"])
        assert exc.template_id == "my_template"

    def test_single_missing_variable(self):
        exc = MissingVariableError("t2", ["firstName"])
        assert "firstName" in str(exc)
        assert exc.missing == ["firstName"]


# ── RenderedTemplate dataclass ────────────────────────────────────────────────

class TestRenderedTemplate:

    def test_fields_accessible(self):
        rt = RenderedTemplate(
            subject="My Subject",
            html_body="<p>Body</p>",
            sms_safe="Body",
        )
        assert rt.subject == "My Subject"
        assert rt.html_body == "<p>Body</p>"
        assert rt.sms_safe == "Body"

    def test_empty_string_defaults(self):
        rt = RenderedTemplate(subject="", html_body="", sms_safe="")
        assert rt.subject == ""
        assert rt.html_body == ""
        assert rt.sms_safe == ""


# ── fetch_template ────────────────────────────────────────────────────────────

class TestFetchTemplate:

    @pytest.mark.asyncio
    async def test_returns_template_dict_when_found_and_active(self):
        template_data = _active_template()
        db = _make_db(template_data, doc_exists=True)

        result = await fetch_template("welcome_sms", db)

        assert result["templateId"] == "welcome_sms"
        assert "{{clientName}}" in result["body"]

    @pytest.mark.asyncio
    async def test_raises_not_found_when_document_missing(self):
        db = _make_db(doc_exists=False)

        with pytest.raises(TemplateNotFoundError, match="welcome_sms"):
            await fetch_template("welcome_sms", db)

    @pytest.mark.asyncio
    async def test_raises_disabled_when_is_active_is_false(self):
        """New Firestore schema uses isActive."""
        template_data = {"templateId": "t1", "body": "Hello", "isActive": False}
        db = _make_db(template_data, doc_exists=True)

        with pytest.raises(TemplateDisabledError, match="t1"):
            await fetch_template("t1", db)

    @pytest.mark.asyncio
    async def test_raises_disabled_when_legacy_active_is_false(self):
        """Legacy schema uses 'active' field — must still be respected."""
        template_data = {"templateId": "t1", "body": "Hello", "active": False}
        db = _make_db(template_data, doc_exists=True)

        with pytest.raises(TemplateDisabledError, match="t1"):
            await fetch_template("t1", db)

    @pytest.mark.asyncio
    async def test_is_active_takes_precedence_over_active(self):
        """isActive=True overrides active=False (isActive is the current field)."""
        template_data = {"body": "Hello", "isActive": True, "active": False}
        db = _make_db(template_data, doc_exists=True)

        # Should NOT raise — isActive wins
        result = await fetch_template("t2", db)
        assert result["body"] == "Hello"

    @pytest.mark.asyncio
    async def test_defaults_to_active_when_both_fields_absent(self):
        """If neither isActive nor active is set, template defaults to active."""
        template_data = {"templateId": "t2", "body": "Hello {{name}}"}
        db = _make_db(template_data, doc_exists=True)

        result = await fetch_template("t2", db)
        assert result["body"] == "Hello {{name}}"

    @pytest.mark.asyncio
    async def test_firestore_collection_name_is_correct(self):
        db = _make_db({"body": "Hi", "isActive": True}, doc_exists=True)

        await fetch_template("my_template", db)

        from config import get_settings
        expected_col = get_settings().sms_templates_collection
        db.collection.assert_called_once_with(expected_col)
        db.collection.return_value.document.assert_called_once_with("my_template")


# ── fetch_and_render (legacy) ─────────────────────────────────────────────────

class TestFetchAndRender:

    @pytest.mark.asyncio
    async def test_double_brace_template_rendered(self):
        tmpl = {"body": "Hi {{clientName}}, case {{caseId}}.", "isActive": True}
        db = _make_db(tmpl, doc_exists=True)

        result = await fetch_and_render(
            "welcome_sms",
            {"clientName": "Tom", "caseId": "ZAD-2025-01-0007"},
            db,
        )

        assert result == "Hi Tom, case ZAD-2025-01-0007."

    @pytest.mark.asyncio
    async def test_single_brace_template_rendered(self):
        tmpl = {"body": "Hi {first_name}, case {case_id}.", "isActive": True}
        db = _make_db(tmpl, doc_exists=True)

        result = await fetch_and_render(
            "legacy_template",
            {"first_name": "Tom", "case_id": "ZAD-2025-01-0007"},
            db,
        )

        assert result == "Hi Tom, case ZAD-2025-01-0007."

    @pytest.mark.asyncio
    async def test_propagates_template_not_found(self):
        db = _make_db(doc_exists=False)

        with pytest.raises(TemplateNotFoundError):
            await fetch_and_render("missing_template", {}, db)

    @pytest.mark.asyncio
    async def test_propagates_template_disabled(self):
        db = _make_db({"body": "Hi", "isActive": False}, doc_exists=True)

        with pytest.raises(TemplateDisabledError):
            await fetch_and_render("disabled_template", {}, db)
