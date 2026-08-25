"""Integration test for the H-2 IDOR fix on GET /cmc/pilot-metrics.

Before the fix, `pilot_metrics` did `district=district or user.district`
with zero enforcement: any authenticated SP could pass
`?district=<other-district>` and read another district's
conviction-rate metrics, despite the service docstring implying
protection. The fix applies the same pattern already used by
`list_patrol_dispatches` in `aranmanai/api/v1/safety.py`:
non-admins are pinned to their own district; admins may cross
districts explicitly.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def sp_user_a(db_session):
    from aranmanai.db.models.user import User, UserRole
    from aranmanai.security import encrypt_field, hash_password
    u = User(
        username="sp_district_a", hashed_password=hash_password("t"),
        name_encrypted=encrypt_field("SP A"), role=UserRole.SP,
        district="district-a", is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def sp_user_b(db_session):
    from aranmanai.db.models.user import User, UserRole
    from aranmanai.security import encrypt_field, hash_password
    u = User(
        username="sp_district_b", hashed_password=hash_password("t"),
        name_encrypted=encrypt_field("SP B"), role=UserRole.SP,
        district="district-b", is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def admin_user(db_session):
    from aranmanai.db.models.user import User, UserRole
    from aranmanai.security import encrypt_field, hash_password
    u = User(
        username="admin_x", hashed_password=hash_password("t"),
        name_encrypted=encrypt_field("Admin"), role=UserRole.ADMIN,
        district="district-a", is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


def _token_for(user) -> str:
    from aranmanai.security import generate_token
    return generate_token(user.id, {"role": user.role.value, "district": user.district})


@pytest.fixture
def app_client(tmp_env, db_session):
    from fastapi.testclient import TestClient

    from aranmanai.api.main import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_h2_pilot_metrics_cross_district_read_rejected(app_client, sp_user_a, sp_user_b):
    """Non-admin SP passing another district's name gets 403 (the IDOR)."""
    headers = {"Authorization": f"Bearer {_token_for(sp_user_a)}"}
    r = app_client.get(
        "/api/v1/cmc/pilot-metrics",
        params={"district": sp_user_b.district},
        headers=headers,
    )
    assert r.status_code == 403


def test_h2_pilot_metrics_own_district_allowed_implicit(app_client, sp_user_a):
    """SP reading with no district param falls back to their own district."""
    headers = {"Authorization": f"Bearer {_token_for(sp_user_a)}"}
    r = app_client.get("/api/v1/cmc/pilot-metrics", headers=headers)
    assert r.status_code == 200
    assert r.json()["district"] == sp_user_a.district


def test_h2_pilot_metrics_own_district_allowed_explicit(app_client, sp_user_a):
    """SP explicitly passing their OWN district is still allowed."""
    headers = {"Authorization": f"Bearer {_token_for(sp_user_a)}"}
    r = app_client.get(
        "/api/v1/cmc/pilot-metrics",
        params={"district": sp_user_a.district},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["district"] == sp_user_a.district


def test_h2_pilot_metrics_admin_can_cross_district(app_client, admin_user, sp_user_b):
    """Admin is exempt from the district-match check, same as safety.py."""
    headers = {"Authorization": f"Bearer {_token_for(admin_user)}"}
    r = app_client.get(
        "/api/v1/cmc/pilot-metrics",
        params={"district": sp_user_b.district},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["district"] == sp_user_b.district
