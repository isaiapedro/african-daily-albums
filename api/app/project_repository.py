"""Persistence for URL-addressed local album journeys."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
import re
import sqlite3
from typing import Literal, Protocol, Sequence
import unicodedata
from uuid import UUID, uuid4

from .static_catalogue import StaticAlbum, create_user_journey


@dataclass(frozen=True, slots=True)
class Project:
    id: UUID
    slug: str
    name: str
    timezone: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Rating:
    score: int
    review: str | None


@dataclass(frozen=True, slots=True)
class Assignment:
    id: UUID
    project_id: UUID
    local_date: date
    album: StaticAlbum
    rating: Rating | None = None


@dataclass(frozen=True, slots=True)
class DailyRollout:
    """The current automatic-rollout state for one local journey."""

    assignment: Assignment | None
    state: Literal["awaiting_start", "active", "frozen", "complete"]
    inactive_days: int = 0


class ProjectRepository(Protocol):
    def initialize(self, catalogue: Sequence[StaticAlbum] = (), catalogue_version: str = "") -> None: ...
    def create(self, *, name: str, timezone: str) -> Project: ...
    def list(self) -> list[Project]: ...
    def get(self, slug: str) -> Project | None: ...
    def assign_today(self, slug: str, local_date: date) -> Assignment | None: ...
    def rollout_today(self, slug: str, local_date: date) -> DailyRollout: ...
    def today(self, slug: str, local_date: date) -> Assignment | None: ...
    def assignments(self, slug: str) -> list[Assignment]: ...
    def albums(self) -> list[StaticAlbum]: ...
    def save_rating(self, slug: str, assignment_id: UUID, score: int, review: str | None) -> Rating: ...


def slugify(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:64] or "minha-jornada"


class InMemoryProjectRepository:
    """Hermetic repository used by API tests."""

    def __init__(self) -> None:
        self._projects: list[Project] = []
        self._albums: tuple[StaticAlbum, ...] = ()
        self._version = ""
        self._assignments: dict[UUID, list[Assignment]] = {}
        self._last_show_dates: dict[UUID, date | None] = {}
        self._frozen_on: dict[UUID, date | None] = {}

    def initialize(self, catalogue: Sequence[StaticAlbum] = (), catalogue_version: str = "") -> None:
        if catalogue:
            self._albums, self._version = tuple(catalogue), catalogue_version

    def _available_slug(self, name: str) -> str:
        base = slugify(name)
        used = {project.slug for project in self._projects}
        if base not in used:
            return base
        suffix = 2
        while f"{base}-{suffix}" in used:
            suffix += 1
        return f"{base}-{suffix}"

    def create(self, *, name: str, timezone: str) -> Project:
        project = Project(uuid4(), self._available_slug(name), name, timezone, datetime.now(UTC))
        self._projects.append(project)
        self._assignments[project.id] = []
        self._last_show_dates[project.id] = None
        self._frozen_on[project.id] = None
        return project

    def list(self) -> list[Project]:
        return list(self._projects)

    def get(self, slug: str) -> Project | None:
        return next((project for project in self._projects if project.slug == slug), None)

    def _assign_for_date(self, project: Project, local_date: date) -> Assignment | None:
        existing = next(
            (item for item in self._assignments[project.id] if item.local_date == local_date), None
        )
        if existing:
            return existing
        assigned = {item.album.id for item in self._assignments[project.id]}
        order = create_user_journey(
            user_id=project.id, catalogue=self._albums, catalogue_version=self._version
        ) if self._albums else ()
        pending = next((item for item in order if item.album_id not in assigned), None)
        if not pending:
            return None
        album = next(album for album in self._albums if album.id == pending.album_id)
        assignment = Assignment(uuid4(), project.id, local_date, album)
        self._assignments[project.id].append(assignment)
        return assignment

    def rollout_today(self, slug: str, local_date: date) -> DailyRollout:
        project = self.get(slug)
        if not project:
            raise KeyError(slug)
        last_show_date = self._last_show_dates[project.id]
        frozen_on = self._frozen_on[project.id]
        if last_show_date is None:
            return DailyRollout(None, "awaiting_start")
        if frozen_on is not None:
            return DailyRollout(None, "frozen", 3)

        inactive_days = max(0, (local_date - last_show_date).days)
        if inactive_days > 3:
            self._frozen_on[project.id] = local_date
            return DailyRollout(None, "frozen", 3)

        assignment: Assignment | None = None
        for offset in range(1, inactive_days + 1):
            assignment = self._assign_for_date(
                project, date.fromordinal(last_show_date.toordinal() + offset)
            )
        if inactive_days == 0:
            assignment = self._assign_for_date(project, local_date)
        return DailyRollout(assignment, "active" if assignment else "complete", inactive_days)

    def assign_today(self, slug: str, local_date: date) -> Assignment | None:
        project = self.get(slug)
        if not project:
            raise KeyError(slug)
        rollout = self.rollout_today(slug, local_date)
        if rollout.state == "frozen":
            # An explicit reveal resumes the journey from today. Days after the
            # three-day grace period remain intentionally unassigned.
            self._frozen_on[project.id] = None
            assignment = self._assign_for_date(project, local_date)
        else:
            assignment = rollout.assignment or self._assign_for_date(project, local_date)
        self._last_show_dates[project.id] = local_date
        return assignment

    def today(self, slug: str, local_date: date) -> Assignment | None:
        project = self.get(slug)
        if not project:
            raise KeyError(slug)
        return next((item for item in self._assignments[project.id] if item.local_date == local_date), None)

    def assignments(self, slug: str) -> list[Assignment]:
        project = self.get(slug)
        if not project:
            raise KeyError(slug)
        return sorted(self._assignments[project.id], key=lambda item: item.local_date, reverse=True)

    def albums(self) -> list[StaticAlbum]:
        return list(self._albums)

    def save_rating(self, slug: str, assignment_id: UUID, score: int, review: str | None) -> Rating:
        project = self.get(slug)
        if not project:
            raise KeyError(slug)
        items = self._assignments[project.id]
        for index, assignment in enumerate(items):
            if assignment.id == assignment_id:
                rating = Rating(score, review)
                items[index] = Assignment(
                    assignment.id, assignment.project_id, assignment.local_date, assignment.album, rating
                )
                return rating
        raise KeyError(assignment_id)


class SQLiteProjectRepository:
    """Single-file persistence for one low-traffic application process."""

    def __init__(self, database_path: Path) -> None:
        self._path = database_path
        self._catalogue_version = ""

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self, catalogue: Sequence[StaticAlbum] = (), catalogue_version: str = "") -> None:
        self._catalogue_version = catalogue_version
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 120),
                    timezone TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_show_date TEXT,
                    frozen_on TEXT
                );
                CREATE TABLE IF NOT EXISTS albums (
                    id TEXT PRIMARY KEY,
                    source_rank INTEGER NOT NULL UNIQUE CHECK (source_rank BETWEEN 1 AND 100),
                    title TEXT NOT NULL,
                    artist_credit TEXT NOT NULL,
                    release_year INTEGER,
                    country_label TEXT
                );
                CREATE TABLE IF NOT EXISTS assignments (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    album_id TEXT NOT NULL REFERENCES albums(id) ON DELETE RESTRICT,
                    local_date TEXT NOT NULL,
                    UNIQUE (project_id, local_date),
                    UNIQUE (project_id, album_id)
                );
                CREATE TABLE IF NOT EXISTS ratings (
                    assignment_id TEXT PRIMARY KEY REFERENCES assignments(id) ON DELETE CASCADE,
                    score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
                    review TEXT CHECK (review IS NULL OR length(review) <= 4000)
                );
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(projects)")}
            if "last_show_date" not in columns:
                connection.execute("ALTER TABLE projects ADD COLUMN last_show_date TEXT")
            if "frozen_on" not in columns:
                connection.execute("ALTER TABLE projects ADD COLUMN frozen_on TEXT")
            connection.executemany(
                """INSERT INTO albums
                   (id, source_rank, title, artist_credit, release_year, country_label)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     source_rank = excluded.source_rank,
                     title = excluded.title,
                     artist_credit = excluded.artist_credit,
                     release_year = excluded.release_year,
                     country_label = excluded.country_label""",
                [
                    (str(a.id), a.rank, a.title, a.artist_credit, a.release_year, a.country_label)
                    for a in catalogue
                ],
            )

    def _available_slug(self, connection: sqlite3.Connection, name: str) -> str:
        base = slugify(name)
        if not connection.execute("SELECT 1 FROM projects WHERE slug = ?", (base,)).fetchone():
            return base
        suffix = 2
        while connection.execute("SELECT 1 FROM projects WHERE slug = ?", (f"{base}-{suffix}",)).fetchone():
            suffix += 1
        return f"{base}-{suffix}"

    def create(self, *, name: str, timezone: str) -> Project:
        project_id = uuid4()
        created_at = datetime.now(UTC)
        with self._connect() as connection:
            slug = self._available_slug(connection, name)
            connection.execute(
                "INSERT INTO projects (id, slug, name, timezone, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(project_id), slug, name, timezone, created_at.isoformat()),
            )
        return Project(project_id, slug, name, timezone, created_at)

    @staticmethod
    def _project(row: sqlite3.Row) -> Project:
        return Project(
            UUID(row["id"]), row["slug"], row["name"], row["timezone"],
            datetime.fromisoformat(row["created_at"]),
        )

    def list(self) -> list[Project]:
        with self._connect() as connection:
            return [self._project(row) for row in connection.execute(
                "SELECT * FROM projects ORDER BY created_at, id"
            ).fetchall()]

    def get(self, slug: str) -> Project | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM projects WHERE slug = ?", (slug,)).fetchone()
        return self._project(row) if row else None

    @staticmethod
    def _assignment(row: sqlite3.Row) -> Assignment:
        rating = Rating(row["score"], row["review"]) if row["score"] is not None else None
        album = StaticAlbum(
            UUID(row["album_id"]), row["source_rank"], row["title"],
            row["artist_credit"], row["release_year"], row["country_label"],
        )
        return Assignment(
            UUID(row["assignment_id"]), UUID(row["project_id"]),
            date.fromisoformat(row["local_date"]), album, rating,
        )

    @staticmethod
    def _assignment_query() -> str:
        return """
            SELECT a.id AS assignment_id, a.project_id, a.local_date,
                   al.id AS album_id, al.source_rank, al.title, al.artist_credit,
                   al.release_year, al.country_label,
                   r.score, r.review
            FROM assignments a
            JOIN albums al ON al.id = a.album_id
            LEFT JOIN ratings r ON r.assignment_id = a.id
        """

    def _assign_for_date(
        self, connection: sqlite3.Connection, project_id: str, local_date: date,
    ) -> Assignment | None:
        existing = connection.execute(
            self._assignment_query() + " WHERE a.project_id = ? AND a.local_date = ?",
            (project_id, local_date.isoformat()),
        ).fetchone()
        if existing:
            return self._assignment(existing)
        albums = self._albums(connection)
        assigned = {
            UUID(row["album_id"])
            for row in connection.execute(
                "SELECT album_id FROM assignments WHERE project_id = ?", (project_id,)
            ).fetchall()
        }
        order = create_user_journey(
            user_id=UUID(project_id), catalogue=albums,
            catalogue_version=self._catalogue_version or "static-v1",
        ) if albums else ()
        candidate = next((item for item in order if item.album_id not in assigned), None)
        if not candidate:
            return None
        assignment_id = uuid4()
        connection.execute(
            "INSERT INTO assignments (id, project_id, album_id, local_date) VALUES (?, ?, ?, ?)",
            (str(assignment_id), project_id, str(candidate.album_id), local_date.isoformat()),
        )
        row = connection.execute(
            self._assignment_query() + " WHERE a.id = ?", (str(assignment_id),)
        ).fetchone()
        assert row is not None
        return self._assignment(row)

    def _rollout_today(
        self, connection: sqlite3.Connection, slug: str, local_date: date,
    ) -> tuple[sqlite3.Row, DailyRollout]:
        project = connection.execute(
            "SELECT id, last_show_date, frozen_on FROM projects WHERE slug = ?", (slug,)
        ).fetchone()
        if not project:
            raise KeyError(slug)
        if project["last_show_date"] is None:
            return project, DailyRollout(None, "awaiting_start")
        if project["frozen_on"] is not None:
            return project, DailyRollout(None, "frozen", 3)

        last_show_date = date.fromisoformat(project["last_show_date"])
        inactive_days = max(0, (local_date - last_show_date).days)
        if inactive_days > 3:
            connection.execute(
                "UPDATE projects SET frozen_on = ? WHERE id = ?", (local_date.isoformat(), project["id"])
            )
            return project, DailyRollout(None, "frozen", 3)

        assignment: Assignment | None = None
        for offset in range(1, inactive_days + 1):
            assignment = self._assign_for_date(
                connection, project["id"], date.fromordinal(last_show_date.toordinal() + offset)
            )
        if inactive_days == 0:
            assignment = self._assign_for_date(connection, project["id"], local_date)
        return project, DailyRollout(assignment, "active" if assignment else "complete", inactive_days)

    def rollout_today(self, slug: str, local_date: date) -> DailyRollout:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _, rollout = self._rollout_today(connection, slug, local_date)
        return rollout

    def assign_today(self, slug: str, local_date: date) -> Assignment | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            project, rollout = self._rollout_today(connection, slug, local_date)
            if rollout.state == "frozen":
                # An explicit reveal resumes the journey from today. Days after the
                # three-day grace period remain intentionally unassigned.
                connection.execute("UPDATE projects SET frozen_on = NULL WHERE id = ?", (project["id"],))
                assignment = self._assign_for_date(connection, project["id"], local_date)
            else:
                assignment = rollout.assignment or self._assign_for_date(connection, project["id"], local_date)
            connection.execute(
                "UPDATE projects SET last_show_date = ? WHERE id = ?",
                (local_date.isoformat(), project["id"]),
            )
        return assignment

    def today(self, slug: str, local_date: date) -> Assignment | None:
        with self._connect() as connection:
            project = connection.execute("SELECT id FROM projects WHERE slug = ?", (slug,)).fetchone()
            if not project:
                raise KeyError(slug)
            row = connection.execute(
                self._assignment_query() + " WHERE a.project_id = ? AND a.local_date = ?",
                (project["id"], local_date.isoformat()),
            ).fetchone()
        return self._assignment(row) if row else None

    def assignments(self, slug: str) -> list[Assignment]:
        with self._connect() as connection:
            project = connection.execute("SELECT id FROM projects WHERE slug = ?", (slug,)).fetchone()
            if not project:
                raise KeyError(slug)
            rows = connection.execute(
                self._assignment_query() + " WHERE a.project_id = ? ORDER BY a.local_date DESC, a.id DESC",
                (project["id"],),
            ).fetchall()
        return [self._assignment(row) for row in rows]

    @staticmethod
    def _albums(connection: sqlite3.Connection) -> list[StaticAlbum]:
        return [
            StaticAlbum(
                UUID(row["id"]), row["source_rank"], row["title"],
                row["artist_credit"], row["release_year"], row["country_label"],
            )
            for row in connection.execute(
                """SELECT id, source_rank, title, artist_credit, release_year, country_label
                   FROM albums ORDER BY source_rank"""
            ).fetchall()
        ]

    def albums(self) -> list[StaticAlbum]:
        with self._connect() as connection:
            return self._albums(connection)

    def save_rating(self, slug: str, assignment_id: UUID, score: int, review: str | None) -> Rating:
        with self._connect() as connection:
            owned = connection.execute(
                """SELECT 1 FROM assignments a JOIN projects p ON p.id = a.project_id
                   WHERE p.slug = ? AND a.id = ?""",
                (slug, str(assignment_id)),
            ).fetchone()
            if not owned:
                raise KeyError(assignment_id)
            connection.execute(
                """INSERT INTO ratings (assignment_id, score, review) VALUES (?, ?, ?)
                   ON CONFLICT(assignment_id) DO UPDATE SET score = excluded.score, review = excluded.review""",
                (str(assignment_id), score, review),
            )
        return Rating(score, review)
