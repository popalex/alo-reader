"""Shared pytest fixtures.

WP-00 only exercises the HTTP surface; the real-Postgres harness (session-scoped
engine + rolled-back per-test transactions) is added in WP-01.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
