"""
services/template_service.py — Template retrieval and rendering.

Template documents live in Firestore under:
    /{sms_templates_collection}/{templateId}

Document schema (Firestore)
---------------------------
    templateId   : str          — document ID (e.g. "welcome_sms")
    name         : str          — human-readable label
    body         : str          — SMS body with {{variable}} placeholders
    subject      : str          — email subject with {{variable}} placeholders
    htmlBody     : str          — HTML email body (optional; auto-derived when absent)
    isActive     : bool         — False → template is disabled; dispatch refused
                                  (legacy field name: ``active``)
    channel      : str          — "SMS" | "EMAIL" | "BOTH"
    triggerEvent : str          — e.g. "new_lead_created"
    createdAt    : timestamp
    updatedAt    : timestamp

Placeholder syntax
------------------
Templates use **double-brace** syntax: ``{{variableName}}``.
The legacy single-brace ``{variableName}`` format is also supported via the
:func:`_render_body` / :func:`fetch_and_render` helpers for backward
compatibility with earlier code.

Public API
----------
    render_template(template_id, variables, db)  → RenderedTemplate
        Primary entry-point.  Fetches, validates, and renders a template.

    fetch_template(template_id, db)  → dict
        Low-level fetch; raises TemplateNotFoundError / TemplateDisabledError.

    fetch_and_render(template_id, variables, db)  → str
        Legacy helper used by sms_service; returns the SMS body string.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from typing import Optional

from google.cloud.firestore_v1.async_client import AsyncClient

from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)

# Matches {{variableName}} — the double-brace placeholder syntax used in
# Firestore template documents.
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")

# Matches any HTML tag — used to strip HTML from SMS-safe bodies.
_HTML_TAG_RE = re.compile(r"<[^>]+>")


# ── Custom exceptions ──────────────────────────────────────────────────────────

class TemplateNotFoundError(Exception):
    """Raised when the requested template does not exist in Firestore."""


class TemplateDisabledError(Exception):
    """Raised when the template exists but ``isActive`` (or ``active``) is False."""


class MissingVariableError(Exception):
    """
    Raised when one or more ``{{placeholder}}`` variables are absent from the
    supplied variables dict.

    Attributes
    ----------
    template_id : str
        The template that triggered the error.
    missing : list[str]
        Sorted list of variable names that were not supplied.

    The error message lists every missing variable in a human-readable form,
    e.g.:
        Template 'welcome_sms' requires variables that were not supplied:
        {{caseId}}, {{clientName}}
    """

    def __init__(self, template_id: str, missing: list[str]) -> None:
        self.template_id = template_id
        self.missing: list[str] = sorted(missing)
        missing_str = ", ".join(f"{{{{{v}}}}}" for v in self.missing)
        super().__init__(
            f"Template '{template_id}' requires variables that were not supplied: "
            f"{missing_str}"
        )


# ── RenderedTemplate result type ───────────────────────────────────────────────

@dataclass
class RenderedTemplate:
    """
    Fully-rendered template output returned by :func:`render_template`.

    Attributes
    ----------
    subject:
        Rendered email subject line.  Empty string for SMS-only templates.
    html_body:
        Rendered HTML email body.  Auto-generated from ``sms_safe`` (newlines
        converted to ``<br>``) when the template has no dedicated ``htmlBody``
        field.
    sms_safe:
        Rendered plain-text SMS body, ready to send via Twilio.
    """

    subject: str
    html_body: str
    sms_safe: str


# ── Private helpers ────────────────────────────────────────────────────────────

def _extract_placeholders(text: str) -> set[str]:
    """Return the set of ``{{varName}}`` placeholder names found in *text*."""
    return set(_PLACEHOLDER_RE.findall(text))


def _substitute(text: str, variables: dict) -> str:
    """
    Replace ``{{varName}}`` placeholders in *text* with values from *variables*.

    Unknown placeholders are left as ``{{varName}}`` rather than raising.
    All values are coerced to ``str``.
    """
    def _replace(match: re.Match) -> str:
        key = match.group(1)
        value = variables.get(key)
        return str(value) if value is not None else match.group(0)

    return _PLACEHOLDER_RE.sub(_replace, text)


def _strip_html_tags(text: str) -> str:
    """
    Remove HTML tags from *text* and decode HTML entities for SMS delivery.

    Examples
    --------
    >>> _strip_html_tags("<p>Hello &amp; welcome</p>")
    'Hello & welcome'
    >>> _strip_html_tags("Plain text — no change")
    'Plain text — no change'
    """
    stripped = _HTML_TAG_RE.sub("", text)
    return _html.unescape(stripped)


class _SafeFormatMap(dict):
    """
    dict subclass for str.format_map() that returns the placeholder text
    unchanged when a key is missing, rather than raising KeyError.

    Used by the legacy single-brace render path (:func:`_render_body`).

    Example::
        "{first_name} {unknown}".format_map(_SafeFormatMap({"first_name": "Jo"}))
        → "Jo {unknown}"
    """

    def __missing__(self, key: str) -> str:
        logger.warning("template_variable_missing", key=key)
        return f"{{{key}}}"


def _render_body(body: str, variables: dict) -> str:
    """
    Substitute *variables* into a single-brace ``{placeholder}`` body string.

    Unknown placeholders are left as ``{placeholder}`` rather than raising.
    This is the legacy rendering path used internally by :func:`fetch_and_render`.
    """
    rendered = body.format_map(_SafeFormatMap(variables))
    logger.debug(
        "template_body_rendered",
        char_count=len(rendered),
        variable_keys=list(variables.keys()),
    )
    return rendered


# ── Firestore fetch ────────────────────────────────────────────────────────────

async def fetch_template(template_id: str, db: AsyncClient) -> dict:
    """
    Fetch and return the raw template document dict from Firestore.

    Raises
    ------
    TemplateNotFoundError
        If the document does not exist.
    TemplateDisabledError
        If ``isActive`` (or legacy ``active``) is ``False``.
    """
    settings = get_settings()
    doc_ref = db.collection(settings.sms_templates_collection).document(template_id)
    doc = await doc_ref.get()

    if not doc.exists:
        logger.error("sms_template_not_found", template_id=template_id)
        raise TemplateNotFoundError(f"SMS template '{template_id}' not found")

    data = doc.to_dict()

    # Support both ``isActive`` (current schema) and ``active`` (legacy schema).
    is_active = data.get("isActive", data.get("active", True))
    if not is_active:
        logger.warning("sms_template_disabled", template_id=template_id)
        raise TemplateDisabledError(f"SMS template '{template_id}' is disabled")

    return data


# ── Primary public API ─────────────────────────────────────────────────────────

async def render_template(
    template_id: str,
    variables: dict,
    db: AsyncClient,
) -> RenderedTemplate:
    """
    Fetch a Firestore template and render it with the supplied variables.

    This is the primary public entry-point for template rendering.  It uses
    the ``{{variableName}}`` double-brace placeholder syntax that matches the
    Firestore template documents.

    Parameters
    ----------
    template_id:
        Firestore document ID inside the ``sms_templates`` collection,
        e.g. ``"welcome_sms"``.
    variables:
        Dict of substitution values, e.g.
        ``{"clientName": "Jane Doe", "caseId": "ZAD-2026-001"}``.
    db:
        Async Firestore client.

    Returns
    -------
    RenderedTemplate
        Dataclass with ``subject``, ``html_body``, and ``sms_safe`` fields.

    Raises
    ------
    TemplateNotFoundError
        If the template document does not exist in Firestore.
    TemplateDisabledError
        If the template is disabled (``isActive: false``).
    MissingVariableError
        If one or more ``{{placeholder}}`` variables are absent from
        *variables*.  The exception message lists every missing variable name.
    """
    template = await fetch_template(template_id, db)

    body_tmpl: str = template.get("body", "")
    subject_tmpl: str = template.get("subject", "")
    html_body_tmpl: str = template.get("htmlBody", "")

    # ── Validate: every placeholder must have a corresponding variable ────
    required: set[str] = (
        _extract_placeholders(body_tmpl)
        | _extract_placeholders(subject_tmpl)
        | _extract_placeholders(html_body_tmpl)
    )
    missing: set[str] = required - set(variables.keys())
    if missing:
        logger.warning(
            "template_variables_missing",
            template_id=template_id,
            missing=sorted(missing),
        )
        raise MissingVariableError(template_id, list(missing))

    # ── Render each field ─────────────────────────────────────────────────
    # Strip HTML tags and decode entities so the SMS body is always plain text
    # (guards against body fields that share HTML with email templates).
    sms_safe = _strip_html_tags(_substitute(body_tmpl, variables))
    subject = _substitute(subject_tmpl, variables)

    # Use dedicated htmlBody field when present; otherwise auto-generate
    # from the SMS body by converting newlines to <br> tags.
    if html_body_tmpl:
        html_body = _substitute(html_body_tmpl, variables)
    else:
        html_body = sms_safe.replace("\n", "<br>")

    logger.info(
        "template_rendered",
        template_id=template_id,
        sms_chars=len(sms_safe),
        variable_keys=list(variables.keys()),
    )

    return RenderedTemplate(subject=subject, html_body=html_body, sms_safe=sms_safe)


# ── Legacy helper (backward-compat) ───────────────────────────────────────────

async def fetch_and_render(
    template_id: str,
    variables: dict,
    db: AsyncClient,
) -> str:
    """
    Convenience wrapper: fetch a template from Firestore and render the SMS body.

    Supports both ``{{double_brace}}`` and ``{single_brace}`` placeholder syntax.
    Returns the rendered SMS body string.

    This helper is kept for backward compatibility.  New code should call
    :func:`render_template` which returns the full :class:`RenderedTemplate`
    (subject, html_body, sms_safe) and performs strict variable validation.

    Raises TemplateNotFoundError or TemplateDisabledError on template issues.
    """
    template = await fetch_template(template_id, db)
    body: str = template.get("body", "")

    # Auto-detect placeholder style and use the appropriate renderer.
    if _PLACEHOLDER_RE.search(body):
        return _substitute(body, variables)
    return _render_body(body, variables)
