"""Immutable African-album catalogue and private ordered journeys.

The runtime never contacts the source. It loads one reviewed, normalized
100-row seed bundled with the application.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Sequence
from uuid import UUID, uuid5


class StaticCatalogueError(ValueError):
    """A static catalogue does not meet the immutable 100-item contract."""


@dataclass(frozen=True, slots=True)
class StaticAlbum:
    id: UUID
    rank: int
    title: str
    artist_credit: str
    release_year: int | None
    country_label: str | None = None


@dataclass(frozen=True, slots=True)
class JourneyItem:
    user_id: UUID
    album_id: UUID
    position: int
    status: str = "pending"


@dataclass(frozen=True, slots=True)
class StaticCatalogueSeed:
    version: str
    albums: tuple[StaticAlbum, ...]
    source_url: str
    source_license: str
    attribution_text: str
    normalized_content_sha256: str


def load_static_catalogue_seed(path: Path) -> StaticCatalogueSeed | None:
    """Read a release artifact only; this function never contacts a source."""

    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["albums"] if isinstance(payload, dict) else payload
    version = payload.get("catalogue_version", payload.get("version", "static-v1")) if isinstance(payload, dict) else "static-v1"
    provenance = payload.get("provenance", {}) if isinstance(payload, dict) else {}
    namespace = UUID("e0ba1899-cab3-44a0-9e2a-914c01937d34")
    albums = tuple(
        StaticAlbum(
            id=UUID(str(row["id"])) if row.get("id") else uuid5(namespace, f"{version}:{row['rank']}"),
            rank=int(row["rank"]), title=str(row["title"]).strip(),
            artist_credit=str(row["artist_credit"]).strip(),
            release_year=int(row["release_year"]) if row.get("release_year") else None,
            country_label=str(row["country_label"]).strip() if row.get("country_label") else None,
        )
        for row in rows
    )
    if not version or any(not album.title or not album.artist_credit for album in albums):
        raise StaticCatalogueError("catalogue_seed_fields_required")
    return StaticCatalogueSeed(
        version=version,
        albums=validate_static_catalogue(albums),
        source_url=str(provenance.get("source_url", "")),
        source_license=str(provenance.get("license", "Source page © OkayAfrica")),
        attribution_text=str(provenance.get("source_title", "OkayAfrica readers' list")),
        normalized_content_sha256=str(provenance.get("normalized_content_sha256", "")),
    )


def validate_static_catalogue(albums: Sequence[StaticAlbum]) -> tuple[StaticAlbum, ...]:
    """Accept one and only one complete immutable ranking."""

    if len(albums) != 100:
        raise StaticCatalogueError("catalogue_must_have_100_albums")
    ranks = [album.rank for album in albums]
    if len(set(ranks)) != 100 or set(ranks) != set(range(1, 101)):
        raise StaticCatalogueError("catalogue_ranks_must_be_1_through_100")
    if len({album.id for album in albums}) != 100:
        raise StaticCatalogueError("catalogue_album_ids_must_be_unique")
    return tuple(sorted(albums, key=lambda album: album.rank))


def create_user_journey(*, user_id: UUID, catalogue: Sequence[StaticAlbum], catalogue_version: str) -> tuple[JourneyItem, ...]:
    """Create a stable private permutation without a stored personal seed.

    Persist the returned 100 rows once. The sorting key is derived from the
    opaque user ID, immutable catalogue version, and shared album ID; no
    personal profile field or third-party data participates.
    """

    approved = validate_static_catalogue(catalogue)
    if not catalogue_version:
        raise StaticCatalogueError("catalogue_version_required")
    ordered = sorted(
        approved,
        key=lambda album: sha256(
            f"african-album-journey-v1\\n{user_id}\\n{catalogue_version}\\n{album.id}".encode("utf-8")
        ).digest(),
    )
    return tuple(
        JourneyItem(user_id=user_id, album_id=album.id, position=index)
        for index, album in enumerate(ordered, start=1)
    )


def next_pending(items: Sequence[JourneyItem]) -> JourneyItem | None:
    """Return the next position; ratings/reviews never affect ordering."""

    pending = [item for item in items if item.status == "pending"]
    return min(pending, key=lambda item: item.position, default=None)
