"""One-process local album journey web application."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime
import os
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .cover_manifest import CoverAsset, load_cover_manifest
from .project_repository import (
    Assignment, DailyRollout, Project, ProjectRepository,
    Rating, SQLiteProjectRepository,
)
from .static_catalogue import StaticAlbum, StaticCatalogueSeed, load_static_catalogue_seed


APP_ROOT = Path(__file__).resolve().parent


class JourneyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("journey_name_required")
        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("invalid_timezone") from error
        return value


class RatingRequest(BaseModel):
    score: int = Field(ge=1, le=5)
    review: str | None = Field(default=None, max_length=4000)

    @field_validator("review")
    @classmethod
    def normalize_review(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else None
        return normalized or None


class ProjectResponse(BaseModel):
    id: str
    slug: str
    name: str
    timezone: str
    progress: int
    total: int = 100


class AlbumResponse(BaseModel):
    id: str
    rank: int
    title: str
    artist_credit: str
    release_year: int | None
    country_label: str | None
    cover_url: str | None = None


class AttributionResponse(BaseModel):
    source_url: str
    source_license: str
    attribution_text: str
    normalized_content_sha256: str


class RatingResponse(BaseModel):
    score: int
    review: str | None


class AssignmentResponse(BaseModel):
    id: str
    local_date: str
    album: AlbumResponse
    rating: RatingResponse | None
    catalogue_attribution: AttributionResponse


class TodayResponse(BaseModel):
    assignment: AssignmentResponse | None
    state: str
    inactive_days: int = Field(ge=0, le=3)


class CatalogueResponse(BaseModel):
    items: list[AlbumResponse]
    catalogue_attribution: AttributionResponse


@asynccontextmanager
async def lifespan(application: FastAPI):
    repository: ProjectRepository = application.state.project_repository
    seed: StaticCatalogueSeed | None = application.state.static_seed
    repository.initialize(seed.albums if seed else (), seed.version if seed else "")
    task = asyncio.create_task(daily_rollout_worker(application))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="100 African Albums", version="0.1.0", docs_url=None,
    redoc_url=None, lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")
app.state.project_repository = SQLiteProjectRepository(
    Path(os.environ.get("ALBUM_JOURNEY_DB", "data/african_album_journey.db"))
)
app.state.static_seed = load_static_catalogue_seed(
    Path(os.environ.get("CATALOGUE_SEED_PATH", APP_ROOT / "catalogue_seed.json"))
)
app.state.cover_assets = load_cover_manifest(APP_ROOT / "static" / "covers" / "index.json")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
        "style-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    return response


@app.get("/health", tags=["operations"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/robots.txt", include_in_schema=False)
async def robots() -> FileResponse:
    return FileResponse(APP_ROOT / "static" / "robots.txt", media_type="text/plain")


def repository(request: Request) -> ProjectRepository:
    return request.app.state.project_repository


def attribution(request: Request) -> AttributionResponse:
    seed: StaticCatalogueSeed | None = request.app.state.static_seed
    if not seed:
        raise HTTPException(status_code=503, detail="catalogue_not_available")
    return AttributionResponse(
        source_url=seed.source_url,
        source_license=seed.source_license,
        attribution_text=seed.attribution_text,
        normalized_content_sha256=seed.normalized_content_sha256,
    )


def album_payload(album: StaticAlbum) -> AlbumResponse:
    cover: CoverAsset | None = app.state.cover_assets.get(album.id)
    return AlbumResponse(
        id=str(album.id), rank=album.rank, title=album.title,
        artist_credit=album.artist_credit, release_year=album.release_year,
        country_label=album.country_label,
        cover_url=f"/static/{cover.path}" if cover else None,
    )


def assignment_payload(item: Assignment, source: AttributionResponse) -> AssignmentResponse:
    rating = RatingResponse(score=item.rating.score, review=item.rating.review) if item.rating else None
    return AssignmentResponse(
        id=str(item.id), local_date=item.local_date.isoformat(), album=album_payload(item.album),
        rating=rating, catalogue_attribution=source,
    )


def project_payload(project: Project, repo: ProjectRepository) -> ProjectResponse:
    return ProjectResponse(
        id=str(project.id), slug=project.slug, name=project.name, timezone=project.timezone,
        progress=len(repo.assignments(project.slug)),
    )


def local_date_for(project: Project) -> date:
    return datetime.now(ZoneInfo(project.timezone)).date()


async def daily_rollout_worker(application: FastAPI) -> None:
    """Materialize unattended daily albums while the local service is running."""
    while True:
        repository: ProjectRepository = application.state.project_repository
        for project in repository.list():
            repository.rollout_today(project.slug, local_date_for(project))
        await asyncio.sleep(60)


def require_project(repo: ProjectRepository, slug: str) -> Project:
    project = repo.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail="journey_not_found")
    return project


@app.get("/api/v1/journeys", response_model=list[ProjectResponse], tags=["journeys"])
async def list_journeys(request: Request) -> list[ProjectResponse]:
    repo = repository(request)
    return [project_payload(project, repo) for project in repo.list()]


@app.post("/api/v1/journeys", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED, tags=["journeys"])
async def create_journey(payload: JourneyCreateRequest, request: Request) -> ProjectResponse:
    repo = repository(request)
    return project_payload(repo.create(name=payload.name, timezone=payload.timezone), repo)


@app.get("/api/v1/journeys/{slug}", response_model=ProjectResponse, tags=["journeys"])
async def get_journey(slug: str, request: Request) -> ProjectResponse:
    repo = repository(request)
    return project_payload(require_project(repo, slug), repo)


@app.get("/api/v1/journeys/{slug}/today", response_model=TodayResponse, tags=["journeys"])
async def get_today(slug: str, request: Request) -> TodayResponse:
    repo = repository(request)
    project = require_project(repo, slug)
    rollout: DailyRollout = repo.rollout_today(slug, local_date_for(project))
    item = assignment_payload(rollout.assignment, attribution(request)) if rollout.assignment else None
    return TodayResponse(assignment=item, state=rollout.state, inactive_days=rollout.inactive_days)


@app.post("/api/v1/journeys/{slug}/today", response_model=AssignmentResponse, tags=["journeys"])
async def reveal_today(slug: str, request: Request) -> AssignmentResponse:
    repo = repository(request)
    project = require_project(repo, slug)
    item = repo.assign_today(slug, local_date_for(project))
    if not item:
        raise HTTPException(status_code=409, detail="journey_complete")
    return assignment_payload(item, attribution(request))


@app.get("/api/v1/journeys/{slug}/history", response_model=list[AssignmentResponse], tags=["journeys"])
async def get_history(slug: str, request: Request) -> list[AssignmentResponse]:
    repo = repository(request)
    require_project(repo, slug)
    source = attribution(request)
    return [assignment_payload(item, source) for item in repo.assignments(slug)]


@app.put("/api/v1/journeys/{slug}/assignments/{assignment_id}/rating", response_model=RatingResponse, tags=["journeys"])
async def save_rating(slug: str, assignment_id: UUID, payload: RatingRequest, request: Request) -> RatingResponse:
    repo = repository(request)
    require_project(repo, slug)
    try:
        saved: Rating = repo.save_rating(slug, assignment_id, payload.score, payload.review)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="assignment_not_found") from error
    return RatingResponse(score=saved.score, review=saved.review)


@app.get("/api/v1/albums", response_model=CatalogueResponse, tags=["catalogue"])
async def list_albums(request: Request) -> CatalogueResponse:
    return CatalogueResponse(
        items=[album_payload(album) for album in repository(request).albums()],
        catalogue_attribution=attribution(request),
    )


def application_shell() -> FileResponse:
    return FileResponse(APP_ROOT / "static" / "index.html")


@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return application_shell()


@app.get("/journey/{slug}", include_in_schema=False)
@app.get("/journey/{slug}/{section}", include_in_schema=False)
async def journey_page(slug: str, section: str = "today") -> FileResponse:
    if section not in {"today", "history", "catalogue"}:
        raise HTTPException(status_code=404, detail="page_not_found")
    return application_shell()


@app.get("/catalogue", include_in_schema=False)
@app.get("/{slug}", include_in_schema=False)
@app.get("/{slug}/{section}", include_in_schema=False)
async def clean_page(slug: str = "catalogue", section: str | None = None) -> FileResponse:
    if slug != "catalogue" and section not in {None, "history"}:
        raise HTTPException(status_code=404, detail="page_not_found")
    return application_shell()
