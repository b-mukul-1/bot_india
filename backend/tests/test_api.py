"""
Tests for APEX-IN FastAPI REST Endpoints
Verifies health, status, CSV streaming, and authenticated kill-switch.
"""

import pytest
from fastapi.testclient import TestClient
from backend.app.main import app, settings

@pytest.fixture
def client():
    return TestClient(app)

def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["paper_mode_only"] is True
    assert "market_state" in data

def test_status_endpoint(client):
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert data["initial_capital"] == 500000.0
    assert data["paper_mode_only"] is True
    assert "drawdown_pct" in data

def test_csv_download_endpoint(client):
    # Unauthenticated -> 401
    res_unauth = client.get("/api/trades.csv")
    assert res_unauth.status_code == 401

    # Authenticated with shared secret -> 200
    headers = {"X-Shared-Secret": settings.API_SHARED_SECRET}
    res = client.get("/api/trades.csv", headers=headers)
    assert res.status_code == 200
    assert res.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment; filename=apex_trades_" in res.headers["content-disposition"]
    # Check UTF-8 BOM at start
    assert res.content.startswith(b"\xef\xbb\xbf")

def test_kill_switch_authentication_and_confirmation(client):
    # 1. Unauthenticated -> 401
    res = client.post("/api/kill-switch?confirm=HALT")
    assert res.status_code == 401

    # 2. Authenticated but missing confirm=HALT -> 400
    headers = {"X-Shared-Secret": settings.API_SHARED_SECRET}
    res = client.post("/api/kill-switch?confirm=NO", headers=headers)
    assert res.status_code == 400

    # 3. Authenticated with confirm=HALT -> 200
    res = client.post("/api/kill-switch?confirm=HALT", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["details"]["status"] == "HALTED"
