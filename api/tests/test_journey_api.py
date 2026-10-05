from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path
import sqlite3
from uuid import UUID, uuid5

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.project_repository import InMemoryProjectRepository, SQLiteProjectRepository
from app.static_catalogue import StaticAlbum


def approved_catalogue() -> list[StaticAlbum]:
    return [
        StaticAlbum(
            uuid5(UUID(int=0), str(rank)), rank, f"Album {rank}", f"Artist {rank}",
            2000, "South Africa",
        )
        for rank in range(1, 101)
    ]


def test_today_rating_and_history_share_the_journey_slug() -> None:
    repository = InMemoryProjectRepository()
    repository.initialize(approved_catalogue(), "fixture-v1")
    app.state.project_repository = repository
    async def scenario():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            journey = (
                await client.post(
                    "/api/v1/journeys", json={"name": "My journey", "timezone": "UTC"}
                )
            ).json()
            slug = journey["slug"]
            first = await client.post(f"/api/v1/journeys/{slug}/today")
            replay = await client.post(f"/api/v1/journeys/{slug}/today")
            saved = await client.put(
                f"/api/v1/journeys/{slug}/assignments/{first.json()['id']}/rating",
                json={"score": 5, "review": "A private note"},
            )
            history = await client.get(f"/api/v1/journeys/{slug}/history")
            return first, replay, saved, history

    first, replay, saved, history = asyncio.run(scenario())

    assert first.status_code == 200
    assert first.json()["id"] == replay.json()["id"]
    assert saved.json() == {"score": 5, "review": "A private note"}
    assert history.json()[0]["rating"] == saved.json()
    assert "OkayAfrica" in history.json()[0]["catalogue_attribution"]["source_license"]


def test_catalogue_is_local_and_complete() -> None:
    repository = InMemoryProjectRepository()
    repository.initialize(approved_catalogue(), "fixture-v1")
    app.state.project_repository = repository
    async def scenario():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get("/api/v1/albums")

    albums = asyncio.run(scenario())
    assert albums.status_code == 200
    assert len(albums.json()["items"]) == 100
    assert albums.json()["items"][0]["country_label"] == "South Africa"
    assert albums.json()["items"][0]["cover_url"] is None


def test_sqlite_persists_journey_and_rating(tmp_path: Path) -> None:
    path = tmp_path / "journey.db"
    first = SQLiteProjectRepository(path)
    first.initialize(approved_catalogue(), "fixture-v1")
    project = first.create(name="Persistent journey", timezone="UTC")
    assignment = first.assign_today(project.slug, date.today())
    assert assignment is not None
    first.save_rating(project.slug, assignment.id, 4, "Still here")

    reopened = SQLiteProjectRepository(path)
    reopened.initialize(approved_catalogue(), "fixture-v1")
    history = reopened.assignments(project.slug)

    assert len(history) == 1
    assert history[0].rating is not None
    assert history[0].rating.review == "Still here"
    with sqlite3.connect(path) as connection:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert tables == {"albums", "assignments", "projects", "ratings"}


def test_sqlite_refreshes_catalogue_metadata_without_changing_journey_data(tmp_path: Path) -> None:
    path = tmp_path / "journey.db"
    original = approved_catalogue()
    repository = SQLiteProjectRepository(path)
    repository.initialize(original, "fixture-v1")
    project = repository.create(name="Metadata-safe journey", timezone="UTC")
    assignment = repository.assign_today(project.slug, date.today())
    assert assignment is not None
    repository.save_rating(project.slug, assignment.id, 5, "Keep this private note")

    refreshed = [
        StaticAlbum(album.id, album.rank, album.title, album.artist_credit, 1984, album.country_label)
        for album in original
    ]
    SQLiteProjectRepository(path).initialize(refreshed, "fixture-v1")

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT release_year FROM albums WHERE source_rank = 1").fetchone()[0] == 1984
        assert connection.execute("SELECT review FROM ratings").fetchone()[0] == "Keep this private note"


def test_daily_rollout_resumes_when_the_user_reveals_after_a_freeze() -> None:
    repository = InMemoryProjectRepository()
    repository.initialize(approved_catalogue(), "fixture-v1")
    project = repository.create(name="Automatic journey", timezone="UTC")
    started_on = date(2026, 9, 1)

    assert repository.rollout_today(project.slug, started_on).state == "awaiting_start"
    assert repository.assign_today(project.slug, started_on) is not None
    third_unattended_day = repository.rollout_today(project.slug, started_on + timedelta(days=3))
    frozen = repository.rollout_today(project.slug, started_on + timedelta(days=4))

    assert third_unattended_day.state == "active"
    assert third_unattended_day.assignment is not None
    assert third_unattended_day.assignment.local_date == started_on + timedelta(days=3)
    assert len(repository.assignments(project.slug)) == 4
    assert frozen.state == "frozen"
    assert frozen.assignment is None
    assert frozen.inactive_days == 3
    resumed = repository.assign_today(project.slug, started_on + timedelta(days=4))
    assert resumed is not None
    assert resumed.local_date == started_on + timedelta(days=4)
    assert repository.rollout_today(project.slug, started_on + timedelta(days=4)).state == "active"


def test_sqlite_reveal_resumes_a_frozen_journey(tmp_path: Path) -> None:
    repository = SQLiteProjectRepository(tmp_path / "journey.db")
    repository.initialize(approved_catalogue(), "fixture-v1")
    project = repository.create(name="Resumable journey", timezone="UTC")
    started_on = date(2026, 9, 1)
    repository.assign_today(project.slug, started_on)

    assert repository.rollout_today(project.slug, started_on + timedelta(days=4)).state == "frozen"
    resumed = repository.assign_today(project.slug, started_on + timedelta(days=4))

    assert resumed is not None
    assert resumed.local_date == started_on + timedelta(days=4)
    assert repository.rollout_today(project.slug, started_on + timedelta(days=4)).state == "active"


def test_clicking_on_the_third_day_keeps_the_automatic_rollout_active() -> None:
    repository = InMemoryProjectRepository()
    repository.initialize(approved_catalogue(), "fixture-v1")
    project = repository.create(name="Engaged journey", timezone="UTC")
    started_on = date(2026, 9, 1)
    repository.assign_today(project.slug, started_on)
    repository.rollout_today(project.slug, started_on + timedelta(days=3))

    repository.assign_today(project.slug, started_on + timedelta(days=3))
    following_day = repository.rollout_today(project.slug, started_on + timedelta(days=4))

    assert following_day.state == "active"
    assert following_day.inactive_days == 1
    assert following_day.assignment is not None


def test_sqlite_adds_rollout_columns_to_an_existing_journey_database(tmp_path: Path) -> None:
    path = tmp_path / "legacy-journey.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE projects (
                id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                timezone TEXT NOT NULL, created_at TEXT NOT NULL
            )"""
        )

    SQLiteProjectRepository(path).initialize(approved_catalogue(), "fixture-v1")

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(projects)")}
    assert {"last_show_date", "frozen_on"} <= columns
