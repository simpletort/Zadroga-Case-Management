"""Unit tests for the build-notifier Cloud Function."""

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from main import _calc_duration, on_build_event

FAKE_WEBHOOK = "https://outlook.office.com/webhook/fake-teams-url"


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_cloud_event(build: dict) -> MagicMock:
    """Wrap a build dict in a minimal CloudEvent mock."""
    encoded = base64.b64encode(json.dumps(build).encode()).decode()
    event = MagicMock()
    event.data = {"message": {"data": encoded}}
    return event


def _base_build(**overrides) -> dict:
    build = {
        "id": "abc123def456",
        "status": "SUCCESS",
        "logUrl": "https://console.cloud.google.com/cloud-build/builds/abc123",
        "startTime": "2024-01-15T10:00:00.000Z",
        "finishTime": "2024-01-15T10:03:42.000Z",
        "substitutions": {
            "COMMIT_SHA": "abc123def456",
            "_SERVICE_NAME": "reporting-service",
            "_ENV": "prod",
            "_REGION": "us-central1",
            "_REPO": "us-central1-docker.pkg.dev/my-project/simpletort",
        },
    }
    build.update(overrides)
    return build


# ── _calc_duration ────────────────────────────────────────────────────────────

class TestCalcDuration:
    def test_returns_formatted_duration(self):
        build = {
            "startTime": "2024-01-15T10:00:00.000Z",
            "finishTime": "2024-01-15T10:03:42.000Z",
        }
        assert _calc_duration(build) == "3m 42s"

    def test_missing_start_returns_empty(self):
        assert _calc_duration({"finishTime": "2024-01-15T10:03:42.000Z"}) == ""

    def test_missing_finish_returns_empty(self):
        assert _calc_duration({"startTime": "2024-01-15T10:00:00.000Z"}) == ""

    def test_handles_no_microseconds(self):
        build = {
            "startTime": "2024-01-15T10:00:00Z",
            "finishTime": "2024-01-15T10:01:05Z",
        }
        assert _calc_duration(build) == "1m 5s"

    def test_invalid_format_returns_empty(self):
        build = {"startTime": "not-a-date", "finishTime": "also-not-a-date"}
        assert _calc_duration(build) == ""


# ── on_build_event — filtering ────────────────────────────────────────────────

class TestOnBuildEventFiltering:
    @patch("main.post_to_teams")
    @patch.dict("os.environ", {"TEAMS_WEBHOOK_URL": FAKE_WEBHOOK})
    def test_notifies_for_success(self, mock_post):
        on_build_event(_make_cloud_event(_base_build(status="SUCCESS")))
        mock_post.assert_called_once()

    @patch("main.post_to_teams")
    @patch.dict("os.environ", {"TEAMS_WEBHOOK_URL": FAKE_WEBHOOK})
    def test_notifies_for_working(self, mock_post):
        on_build_event(_make_cloud_event(_base_build(status="WORKING")))
        mock_post.assert_called_once()

    @patch("main.post_to_teams")
    @patch.dict("os.environ", {"TEAMS_WEBHOOK_URL": FAKE_WEBHOOK})
    def test_notifies_for_failure(self, mock_post):
        on_build_event(_make_cloud_event(_base_build(status="FAILURE")))
        mock_post.assert_called_once()

    @patch("main.post_to_teams")
    @patch.dict("os.environ", {"TEAMS_WEBHOOK_URL": FAKE_WEBHOOK})
    def test_notifies_for_pending(self, mock_post):
        on_build_event(_make_cloud_event(_base_build(status="PENDING")))
        mock_post.assert_called_once()

    @patch("main.post_to_teams")
    @patch.dict("os.environ", {"TEAMS_WEBHOOK_URL": FAKE_WEBHOOK})
    def test_skips_queued_status(self, mock_post):
        on_build_event(_make_cloud_event(_base_build(status="QUEUED")))
        mock_post.assert_not_called()

    @patch("main.post_to_teams")
    @patch.dict("os.environ", {"TEAMS_WEBHOOK_URL": FAKE_WEBHOOK})
    def test_skips_build_without_service_name(self, mock_post):
        build = _base_build()
        del build["substitutions"]["_SERVICE_NAME"]
        on_build_event(_make_cloud_event(build))
        mock_post.assert_not_called()

    @patch("main.post_to_teams")
    @patch.dict("os.environ", {}, clear=True)  # no TEAMS_WEBHOOK_URL
    def test_logs_error_when_webhook_url_missing(self, mock_post):
        on_build_event(_make_cloud_event(_base_build()))
        mock_post.assert_not_called()

    @patch("main.post_to_teams")
    @patch.dict("os.environ", {"TEAMS_WEBHOOK_URL": FAKE_WEBHOOK})
    def test_handles_empty_pubsub_data(self, mock_post):
        event = MagicMock()
        event.data = {"message": {"data": ""}}
        on_build_event(event)
        mock_post.assert_not_called()

    @patch("main.post_to_teams")
    @patch.dict("os.environ", {"TEAMS_WEBHOOK_URL": FAKE_WEBHOOK})
    def test_handles_malformed_json(self, mock_post):
        event = MagicMock()
        event.data = {"message": {"data": base64.b64encode(b"not-json").decode()}}
        on_build_event(event)
        mock_post.assert_not_called()


# ── on_build_event — payload correctness ─────────────────────────────────────

class TestOnBuildEventPayload:
    @patch("main.post_to_teams")
    @patch.dict("os.environ", {"TEAMS_WEBHOOK_URL": FAKE_WEBHOOK})
    def test_passes_correct_fields(self, mock_post):
        on_build_event(_make_cloud_event(_base_build(status="SUCCESS")))
        _, kwargs = mock_post.call_args
        assert kwargs["service_name"] == "reporting-service"
        assert kwargs["env"] == "prod"
        assert kwargs["short_sha"] == "abc123d"
        assert kwargs["status_label"] == "succeeded"
        assert kwargs["color"] == "#2EB67D"
        assert "console.cloud.google.com" in kwargs["log_url"]
        assert kwargs["duration_str"] == "3m 42s"

    @patch("main.post_to_teams")
    @patch.dict("os.environ", {"TEAMS_WEBHOOK_URL": FAKE_WEBHOOK})
    def test_failure_uses_red_color(self, mock_post):
        on_build_event(_make_cloud_event(_base_build(status="FAILURE")))
        _, kwargs = mock_post.call_args
        assert kwargs["color"] == "#E01E5A"
        assert kwargs["status_label"] == "failed"

    @patch("main.post_to_teams")
    @patch.dict("os.environ", {"TEAMS_WEBHOOK_URL": FAKE_WEBHOOK})
    def test_pending_label(self, mock_post):
        on_build_event(_make_cloud_event(_base_build(status="PENDING")))
        _, kwargs = mock_post.call_args
        assert kwargs["status_label"] == "awaiting approval"
