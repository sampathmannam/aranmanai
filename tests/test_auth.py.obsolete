"""Auth endpoints: login, /me, role enforcement."""
from __future__ import annotations

import pytest


def test_login_returns_jwt(client, auth_headers):
    r = client.post("/auth/login", json={"username": "admin", "password": "adminpass123"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in_minutes"] == 60


def test_login_rejects_wrong_password(client):
    r = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_me_returns_current_user(client, auth_headers):
    r = client.get("/auth/me", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "admin"
    assert body["role"] == "Admin"
    assert body["district"] == "Vellore"


def test_me_rejects_no_token(client):
    r = client.get("/auth/me")
    assert r.status_code == 401


def test_me_rejects_invalid_token(client):
    r = client.get("/auth/me", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401


def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["app"] == "Aranmanai"
    assert body["integrations"]["cctns"] == "mock"
