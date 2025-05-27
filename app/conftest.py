from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from core.config import settings

# make sure to import your token endpoint credentials
from main import app


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Sync TestClient for tests that don’t need async."""
    return TestClient(app)


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient with no overrides (uses real auth)."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture(scope="session")
def token_headers(client: TestClient) -> dict:
    """
    Log in once as the default admin and return Authorization headers.
    """
    resp = client.post(
        "/auth/token",
        data={
            "username": settings.security.admin_username,
            "password": settings.security.admin_password,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, "Could not obtain admin token"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
