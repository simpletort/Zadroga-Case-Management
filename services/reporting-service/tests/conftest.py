"""
conftest.py — Shared pytest fixtures for the reporting-service.
"""
import sys
from unittest.mock import MagicMock

# get_cors_origins() now fetches from GCP Secret Manager at import time (see
# shared/shared/middlewares/cors.py). Stub it so tests don't make a real
# network call / hang without live GCP credentials.
_cors_stub_mod = MagicMock()
_cors_stub_mod.get_cors_origins = lambda environment, gcp_project_id: ["http://localhost:3000"]
sys.modules.setdefault("shared.middlewares.cors", _cors_stub_mod)
