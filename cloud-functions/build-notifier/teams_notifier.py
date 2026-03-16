"""
Microsoft Teams incoming-webhook poster for deployment notifications.

Uses the MessageCard format supported by Teams Incoming Webhook connectors.
Only stdlib (urllib) is used — no extra dependencies.

Errors are logged but never re-raised so a Teams outage cannot break the
Cloud Function and cause Cloud Build event retries.

MessageCard docs:
  https://learn.microsoft.com/en-us/outlook/actionable-messages/message-card-reference
"""

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


def post_to_teams(
    *,
    webhook_url: str,
    service_name: str,
    status_label: str,
    emoji: str,
    color: str,          # hex with leading '#', e.g. "#2EB67D"
    short_sha: str,
    env: str,
    log_url: str,
    duration_str: str,
) -> None:
    """Post a deployment status MessageCard to the Teams incoming webhook."""
    title = f"{emoji} Deployment {status_label}"
    theme_color = color.lstrip("#")   # Teams expects hex without '#'

    facts = [
        {"name": "Service",     "value": service_name},
        {"name": "Environment", "value": env},
        {"name": "Version",     "value": short_sha},
    ]
    if duration_str:
        facts.append({"name": "Duration", "value": duration_str})

    section: dict = {
        "activityTitle": title,
        "activitySubtitle": f"{service_name} · {env} · `{short_sha}`",
        "facts": facts,
        "markdown": True,
    }

    card: dict = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"{title} — {service_name} ({env})",
        "themeColor": theme_color,
        "sections": [section],
    }

    if log_url:
        card["potentialAction"] = [
            {
                "@type": "OpenUri",
                "name": "View Build Logs",
                "targets": [{"os": "default", "uri": log_url}],
            }
        ]

    try:
        data = json.dumps(card).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("Teams notification sent (HTTP %s)", resp.status)
    except urllib.error.URLError as exc:
        logger.error("Failed to post to Teams: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error posting to Teams: %s", exc)
