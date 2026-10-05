from __future__ import annotations

import asyncio

from httpx import ASGITransport, AsyncClient

from app.main import APP_ROOT, app, journey_page
from app.project_repository import InMemoryProjectRepository


def test_journey_uses_a_readable_collision_safe_url() -> None:
    app.state.project_repository = InMemoryProjectRepository()
    async def scenario():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post(
                "/api/v1/journeys",
                json={"name": "Um Ano e Meio de Música", "timezone": "America/Sao_Paulo"},
            )
            second = await client.post(
                "/api/v1/journeys",
                json={"name": "Um Ano e Meio de Música", "timezone": "America/Sao_Paulo"},
            )
            return first, second

    first, second = asyncio.run(scenario())
    page = asyncio.run(journey_page("um-ano-e-meio-de-musica"))

    assert first.status_code == 201
    assert first.json()["slug"] == "um-ano-e-meio-de-musica"
    assert second.json()["slug"] == "um-ano-e-meio-de-musica-2"
    assert page.path == APP_ROOT / "static" / "index.html"
    assert "100 Discos Africanos" in (APP_ROOT / "static" / "index.html").read_text()


def test_journey_requires_a_real_name_and_iana_timezone() -> None:
    app.state.project_repository = InMemoryProjectRepository()
    async def scenario():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            blank_name = await client.post(
                "/api/v1/journeys", json={"name": "  ", "timezone": "America/Sao_Paulo"}
            )
            invalid_timezone = await client.post(
                "/api/v1/journeys", json={"name": "Valid", "timezone": "Mars/Olympus"}
            )
            return blank_name, invalid_timezone

    blank_name, invalid_timezone = asyncio.run(scenario())

    assert blank_name.status_code == 422
    assert invalid_timezone.status_code == 422
