"""
Cloud Build deployment notifier.

Triggered by the `cloud-builds` Pub/Sub topic that Cloud Build publishes to
automatically for every build event.  Filters to builds that carry a
`_SERVICE_NAME` substitution (i.e. our managed services) and posts a
formatted MessageCard to the team Microsoft Teams channel via incoming webhook.

Statuses handled:
  WORKING   → deployment started
  SUCCESS   → deployment succeeded
  FAILURE   → deployment failed
  TIMEOUT   → deployment timed out
  CANCELLED → deployment cancelled
  PENDING   → awaiting manual approval gate
"""

import base64
import json
import logging
import os
from datetime import datetime

import functions_framework
from cloudevents.http import CloudEvent

from teams_notifier import post_to_teams

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Statuses that warrant a Teams notification
NOTIFY_STATUSES = {"WORKING", "SUCCESS", "FAILURE", "TIMEOUT", "CANCELLED", "PENDING"}

STATUS_CONFIG: dict[str, dict] = {
    "WORKING":   {"emoji": "🔨", "label": "started",          "color": "#439FE0"},
    "SUCCESS":   {"emoji": "✅", "label": "succeeded",         "color": "#2EB67D"},
    "FAILURE":   {"emoji": "❌", "label": "failed",            "color": "#E01E5A"},
    "TIMEOUT":   {"emoji": "⏱️", "label": "timed out",         "color": "#E01E5A"},
    "CANCELLED": {"emoji": "🚫", "label": "cancelled",         "color": "#ECB22E"},
    "PENDING":   {"emoji": "⏳", "label": "awaiting approval", "color": "#ECB22E"},
}


@functions_framework.cloud_event
def on_build_event(cloud_event: CloudEvent) -> None:
    """Cloud Function entry point — triggered by Cloud Build Pub/Sub messages."""
    pubsub_data = cloud_event.data.get("message", {}).get("data", "")
    if not pubsub_data:
        logger.warning("Empty Pub/Sub message data — skipping")
        return

    try:
        build = json.loads(base64.b64decode(pubsub_data).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error("Failed to decode build message: %s", exc)
        return

    status = build.get("status", "")
    if status not in NOTIFY_STATUSES:
        logger.debug("Skipping status=%s build=%s", status, build.get("id"))
        return

    substitutions = build.get("substitutions", {})
    service_name = substitutions.get("_SERVICE_NAME", "")
    if not service_name:
        # Not one of our managed services — skip silently
        return

    env = substitutions.get("_ENV", "unknown")
    commit_sha = substitutions.get("COMMIT_SHA", build.get("id", ""))
    short_sha = commit_sha[:7] if commit_sha else "unknown"
    log_url = build.get("logUrl", "")

    duration_str = _calc_duration(build)

    webhook_url = os.environ.get("TEAMS_WEBHOOK_URL", "")
    if not webhook_url:
        logger.error("TEAMS_WEBHOOK_URL env var not set — cannot send notification")
        return

    cfg = STATUS_CONFIG.get(
        status, {"emoji": "❓", "label": status.lower(), "color": "#AAAAAA"}
    )

    logger.info(
        "Notifying Teams: service=%s status=%s env=%s sha=%s",
        service_name, status, env, short_sha,
    )

    post_to_teams(
        webhook_url=webhook_url,
        service_name=service_name,
        status_label=cfg["label"],
        emoji=cfg["emoji"],
        color=cfg["color"],
        short_sha=short_sha,
        env=env,
        log_url=log_url,
        duration_str=duration_str,
    )


def _calc_duration(build: dict) -> str:
    """Return human-readable build duration (e.g. '3m 42s'), or '' if unavailable."""
    start = build.get("startTime")
    finish = build.get("finishTime")
    if not start or not finish:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            t_start = datetime.strptime(start, fmt)
            t_finish = datetime.strptime(finish, fmt)
            secs = int((t_finish - t_start).total_seconds())
            return f"{secs // 60}m {secs % 60}s"
        except ValueError:
            continue
    return ""
