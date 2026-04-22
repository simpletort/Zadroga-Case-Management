"""
conftest.py — Shared pytest fixtures for the settlement-financial service.
"""
from __future__ import annotations

import os
import sys

import pytest

# Make the service root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("FIRESTORE_DATABASE_ID", "(default)")
