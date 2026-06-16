from __future__ import annotations

import re
import uuid
from collections.abc import AsyncGenerator
from datetime import date, time

import pytest
import pytest_asyncio
from fixtures import seed_public_mosque_bundle
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.domain import CandidateStatus, Confidence, Prayer
from uk_jamaat_directory.main import create_app
from uk_jamaat_directory.models.core import ScheduleCandidate

ADMIN_KEY = "test-admin-key"
SESSION_KEY = "unit-test-session-secret-key-0123456789"


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "no csrf token in form"
    return match.group(1)


def _make_app(settings: Settings):
    app = create_app(settings)
    return app


async def _client(app) -> AsyncClient:
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# --------------------------------------------------------------- auth (no DB)


@pytest.mark.asyncio
async def test_login_required_redirects_to_login() -> None:
    app = _make_app(
        Settings(allowed_hosts=["test"], admin_api_key=ADMIN_KEY, session_secret_key=SESSION_KEY)
    )
    async with await _client(app) as client:
        resp = await client.get("/admin", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"


@pytest.mark.asyncio
async def test_login_disabled_when_unconfigured() -> None:
    app = _make_app(Settings(allowed_hosts=["test"], admin_api_key=None, session_secret_key=None))
    async with await _client(app) as client:
        page = await client.get("/admin/login")
        assert page.status_code == 200
        assert "not configured" in page.text.lower()
        resp = await client.post("/admin/login", data={"key": "x", "csrf_token": "y"})
        assert resp.status_code == 503


@pytest.mark.asyncio
async def test_login_rejects_bad_csrf_then_wrong_key_then_succeeds() -> None:
    app = _make_app(
        Settings(allowed_hosts=["test"], admin_api_key=ADMIN_KEY, session_secret_key=SESSION_KEY)
    )
    async with await _client(app) as client:
        page = await client.get("/admin/login")
        token = _csrf(page.text)

        bad_csrf = await client.post("/admin/login", data={"key": ADMIN_KEY, "csrf_token": "wrong"})
        assert bad_csrf.status_code == 400

        page = await client.get("/admin/login")
        token = _csrf(page.text)
        wrong_key = await client.post("/admin/login", data={"key": "nope", "csrf_token": token})
        assert wrong_key.status_code == 401

        page = await client.get("/admin/login")
        token = _csrf(page.text)
        ok = await client.post(
            "/admin/login",
            data={"key": ADMIN_KEY, "csrf_token": token},
            follow_redirects=False,
        )
        assert ok.status_code == 303
        assert ok.headers["location"].startswith("/admin")

        # Authenticated now.
        dash = await client.get("/admin", follow_redirects=False)
        assert dash.status_code in (200, 500)  # 200 needs DB; route is reached, not redirected

        # Logout clears the session.
        await client.post("/admin/logout")
        after = await client.get("/admin", follow_redirects=False)
        assert after.status_code == 303


# --------------------------------------------------------------- DB-backed


@pytest_asyncio.fixture
async def admin_ui_client(
    db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    settings = Settings(
        environment="test",
        allowed_hosts=["test"],
        admin_api_key=ADMIN_KEY,
        session_secret_key=SESSION_KEY,
    )
    app = create_app(settings)

    async def _override() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/admin/login")
        token = _csrf(page.text)
        await client.post(
            "/admin/login",
            data={"key": ADMIN_KEY, "csrf_token": token},
            follow_redirects=False,
        )
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dashboard_renders_coverage(
    admin_ui_client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_public_mosque_bundle(db_session)
    resp = await admin_ui_client.get("/admin")
    assert resp.status_code == 200
    assert "Dashboard" in resp.text
    assert "With published times" in resp.text


@pytest.mark.asyncio
async def test_create_mosque_via_form_persists(
    admin_ui_client: AsyncClient, db_session: AsyncSession
) -> None:
    new_page = await admin_ui_client.get("/admin/mosques/new")
    token = _csrf(new_page.text)
    resp = await admin_ui_client.post(
        "/admin/mosques",
        data={
            "csrf_token": token,
            "name": "New Test Mosque",
            "city": "Leeds",
            "postcode": "LS1 1AA",
            "status": "active",
            "country": "GB",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin/mosques/")

    listing = await admin_ui_client.get("/admin/mosques", params={"q": "New Test"})
    assert listing.status_code == 200
    assert "New Test Mosque" in listing.text


@pytest.mark.asyncio
async def test_create_mosque_rejects_missing_csrf(
    admin_ui_client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await admin_ui_client.post(
        "/admin/mosques",
        data={"csrf_token": "bogus", "name": "No CSRF", "status": "active", "country": "GB"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "err=" in resp.headers["location"]
    listing = await admin_ui_client.get("/admin/mosques", params={"q": "No CSRF"})
    # The mosque was not created, so the filtered list is empty.
    assert "No mosques match." in listing.text


@pytest.mark.asyncio
async def test_update_source_policy(admin_ui_client: AsyncClient, db_session: AsyncSession) -> None:
    bundle = await seed_public_mosque_bundle(db_session)
    source = bundle["private_source"]
    detail = await admin_ui_client.get(f"/admin/mosques/{bundle['mosque'].id}")
    token = _csrf(detail.text)
    resp = await admin_ui_client.post(
        f"/admin/sources/{source.id}",
        data={
            "csrf_token": token,
            "publication_policy": "public_redistribution_allowed",
            "redirect_to": f"/admin/mosques/{bundle['mosque'].id}",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    await db_session.refresh(source)
    assert source.publication_policy.value == "public_redistribution_allowed"


@pytest.mark.asyncio
async def test_candidate_reject_transition(
    admin_ui_client: AsyncClient, db_session: AsyncSession
) -> None:
    bundle = await seed_public_mosque_bundle(db_session)
    candidate = ScheduleCandidate(
        id=uuid.uuid4(),
        mosque_id=bundle["mosque"].id,
        source_id=bundle["public_source"].id,
        date=date(2026, 6, 20),
        prayer=Prayer.ASR,
        jamaat_time=time(17, 30),
        timezone="Europe/London",
        confidence=Confidence.COMMUNITY,
        status=CandidateStatus.PENDING,
    )
    db_session.add(candidate)
    await db_session.commit()

    page = await admin_ui_client.get("/admin/candidates")
    assert page.status_code == 200
    token = _csrf(page.text)
    resp = await admin_ui_client.post(
        f"/admin/candidates/{candidate.id}/reject",
        data={"csrf_token": token, "redirect_to": "/admin/candidates"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    await db_session.refresh(candidate)
    assert candidate.status == CandidateStatus.REJECTED


@pytest.mark.asyncio
async def test_pipeline_page_renders(
    admin_ui_client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_public_mosque_bundle(db_session)
    resp = await admin_ui_client.get("/admin/pipeline")
    assert resp.status_code == 200
    assert "Source health" in resp.text
