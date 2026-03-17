"""
services/template_service.py — SMS template retrieval and rendering.

Template documents live in Firestore under:
    /{sms_templates_collection}/{templateId}

Document schema
---------------
    templateId  : str          — document ID (e.g. "welcome_sms")
    name        : str          — human-readable label
    body        : str          — message body with {variable} placeholders
    active      : bool         — if False the template is disabled; dispatch
                                  will be refused
    createdAt   : timestamp
    updatedAt   : timestamp

Rendering
---------
Variable substitution uses Python's str.format_map() with a safe mapping
that leaves unresolved placeholders as-is (instead of raising KeyError).
This prevents a template with a missing variable from crashing the dispatch.
"""
from __future__ import annotations

from typing import Optional

from google.cloud.firestore_v1.async_client import AsyncClient

from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)


class TemplateNotFoundError(Exception):
    """Raised when the requested template does not exist in Firestore."""


class TemplateDisabledError(Exception):
    """Raised when the template exists but its ``active`` flag is False."""


class _SafeFormatMap(dict):
    """
    dict subclass for str.format_map() that returns the placeholder text
    unchanged when a key is missing, rather than raising KeyError.

    Example::
        "{first_name} {unknown}".format_map(_SafeFormatMap({"first_name": "Jo"}))
        → "Jo {unknown}"
    """

    def __missing__(self, key: str) -> str:
        logger.warning("template_variable_missing", key=key)
        return f"{{{key}}}"


async def fetch_template(template_id: str, db: AsyncClient) -> dict:
    """
    Fetch and return the raw template document dict from Firestore.

    Raises
    ------
    TemplateNotFoundError
        If the document does not exist.
    TemplateDisabledError
        If ``active`` is False.
    """
    settings = get_settings()
    doc_ref = db.collection(settings.sms_templates_collection).document(template_id)
    doc = await doc_ref.get()

    if not doc.exists:
        logger.error("sms_template_not_found", template_id=template_id)
        raise TemplateNotFoundError(f"SMS template '{template_id}' not found")

    data = doc.to_dict()

    if not data.get("active", True):
        logger.warning("sms_template_disabled", template_id=template_id)
        raise TemplateDisabledError(f"SMS template '{template_id}' is disabled")

    return data


def render_template(body: str, variables: dict) -> str:
    """
    Substitute *variables* into *body* using safe format-map substitution.

    Unknown placeholders are left as ``{placeholder}`` in the output rather
    than raising an exception.

    Parameters
    ----------
    body:
        Template body string, e.g.
        ``"Hi {first_name}, your case {case_id} is under review."``
    variables:
        Dict of substitution values, e.g.
        ``{"first_name": "Jane", "case_id": "ZAD-2025-03-0001"}``.

    Returns
    -------
    str
        Rendered message body.
    """
    rendered = body.format_map(_SafeFormatMap(variables))
    logger.debug(
        "template_rendered",
        char_count=len(rendered),
        variable_keys=list(variables.keys()),
    )
    return rendered


async def fetch_and_render(
    template_id: str,
    variables: dict,
    db: AsyncClient,
) -> str:
    """
    Convenience wrapper: fetch template from Firestore and render it.

    Returns the rendered SMS body string.
    Raises TemplateNotFoundError or TemplateDisabledError on template issues.
    """
    template = await fetch_template(template_id, db)
    body = template.get("body", "")
    return render_template(body, variables)
