#!/usr/bin/env python3
"""Build local Cover Art Archive thumbnails for the African 100-album seed.

This is a release-preparation command, never a runtime dependency. It resolves
one MusicBrainz release group per catalogue row, downloads its bounded front
thumbnail from Cover Art Archive, and writes only local static assets plus a
traceability manifest. Review ``unmatched`` entries before any public release.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "api" / "app"
SEED_PATH = APP_DIR / "catalogue_seed.json"
COVERS_DIR = APP_DIR / "static" / "covers"
MANIFEST_PATH = COVERS_DIR / "index.json"
USER_AGENT = "100-african-albums-cover-import/0.1 (local release preparation)"
MUSICBRAINZ_INTERVAL_SECONDS = 1.05


@dataclass(frozen=True)
class Album:
    id: str
    rank: int
    title: str
    artist: str


def get_json(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:  # noqa: S310 - declared public release source
        return json.load(response)


def find_release_group(album: Album) -> tuple[str | None, str | None]:
    query = f'releasegroup:"{album.title}" AND artist:"{album.artist}"'
    queries = (query, f'releasegroup:"{album.title}"')
    candidates: list[dict] = []
    for candidate_query in queries:
        url = f"https://musicbrainz.org/ws/2/release-group/?fmt=json&limit=5&query={quote(candidate_query)}"
        try:
            payload = get_json(url)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            return None, f"musicbrainz:{type(error).__name__}"
        candidates = payload.get("release-groups", [])
        if candidates:
            break
        time.sleep(MUSICBRAINZ_INTERVAL_SECONDS)
    if not candidates:
        return None, "musicbrainz:no_match"
    normalized_title = album.title.casefold()
    source_artist_tokens = {
        token for token in re.findall(r"[\w]+", album.artist.casefold())
        if token not in {"and", "the"}
    }
    exact = [
        item for item in candidates
        if str(item.get("title", "")).casefold() == normalized_title
        and len(
            source_artist_tokens
            & {
                token
                for token in re.findall(
                    r"[\w]+",
                    " ".join(
                        credit.get("name", "") for credit in item.get("artist-credit", [])
                    ).casefold(),
                )
                if token not in {"and", "the"}
            }
        ) >= min(2, len(source_artist_tokens))
    ]
    if not exact:
        return None, "musicbrainz:no_confident_match"
    selected = exact[0]
    score = int(selected.get("score", 0))
    if score < 90:
        return None, f"musicbrainz:low_score:{score}"
    return str(selected.get("id")), None


def download_cover(album: Album, release_group_id: str, destination: Path) -> str | None:
    url = f"https://coverartarchive.org/release-group/{release_group_id}/front-250"
    request = Request(url, headers={"Accept": "image/*", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=45) as response:  # noqa: S310 - declared public release source
            content_type = response.headers.get_content_type()
            if content_type not in {"image/jpeg", "image/png", "image/webp"}:
                return f"coverartarchive:unexpected_content_type:{content_type}"
            with destination.open("wb") as output:
                shutil.copyfileobj(response, output)
    except (HTTPError, URLError, TimeoutError) as error:
        return f"coverartarchive:{type(error).__name__}"
    if destination.stat().st_size == 0 or destination.stat().st_size > 2_000_000:
        destination.unlink(missing_ok=True)
        return "coverartarchive:invalid_size"
    return None


def load_albums() -> list[Album]:
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    return [Album(str(row["id"]), int(row["rank"]), str(row["title"]), str(row["artist_credit"])) for row in payload["albums"]]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Process only the first N ranks (for a smoke run).")
    parser.add_argument("--from-rank", type=int, default=1, help="First source position to process (inclusive).")
    parser.add_argument("--to-rank", type=int, default=100, help="Last source position to process (inclusive).")
    parser.add_argument("--retry-unmatched", action="store_true", help="Retry entries recorded as unmatched.")
    parser.add_argument(
        "--retry-transient",
        action="store_true",
        help="Retry only prior HTTP, network, timeout, or JSON-response failures.",
    )
    parser.add_argument("--upgrade-500", action="store_true", help="Replace existing local covers with 500px CAA thumbnails.")
    args = parser.parse_args()
    albums = load_albums()
    if not 1 <= args.from_rank <= args.to_rank <= 100:
        parser.error("--from-rank and --to-rank must be within 1 through 100")
    albums = [album for album in albums if args.from_rank <= album.rank <= args.to_rank]
    if args.limit:
        albums = albums[:args.limit]
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    old_manifest = json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {"items": {}, "unmatched": {}}
    items: dict[str, dict] = old_manifest.get("items", {})
    unmatched: dict[str, str] = old_manifest.get("unmatched", {})
    if args.upgrade_500:
        selected_ids = {album.id for album in albums}
        upgraded = 0
        failed = 0
        for album_id, item in items.items():
            if album_id not in selected_ids:
                continue
            release_group_id = item.get("musicbrainz_release_group_id", "")
            if not release_group_id:
                continue
            destination = APP_DIR / "static" / item["path"]
            temporary = destination.with_suffix(".upgrade")
            request = Request(f"https://coverartarchive.org/release-group/{release_group_id}/front-500", headers={"Accept": "image/*", "User-Agent": USER_AGENT})
            try:
                with urlopen(request, timeout=45) as response, temporary.open("wb") as output:
                    if response.headers.get_content_type() not in {"image/jpeg", "image/png", "image/webp"}:
                        raise ValueError("unexpected_content_type")
                    shutil.copyfileobj(response, output)
                if temporary.stat().st_size == 0 or temporary.stat().st_size > 4_000_000:
                    raise ValueError("invalid_size")
                temporary.replace(destination)
                item["source_url"] = f"https://coverartarchive.org/release-group/{release_group_id}/front-500"
                upgraded += 1
            except (HTTPError, URLError, TimeoutError, ValueError):
                temporary.unlink(missing_ok=True)
                failed += 1
            MANIFEST_PATH.write_text(json.dumps({"schema_version": 1, "provider": "Cover Art Archive via MusicBrainz", "items": items, "unmatched": unmatched}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            time.sleep(MUSICBRAINZ_INTERVAL_SECONDS)
        MANIFEST_PATH.write_text(json.dumps({"schema_version": 1, "provider": "Cover Art Archive via MusicBrainz", "items": items, "unmatched": unmatched}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Complete: {upgraded} upgraded to 500px; {failed} kept existing assets.")
        return 0

    for index, album in enumerate(albums, start=1):
        relative_path = f"covers/{album.id}.jpg"
        destination = APP_DIR / "static" / relative_path
        if album.id in items and destination.is_file():
            print(f"[{index}/{len(albums)}] #{album.rank}: already imported")
            continue
        if album.id in unmatched:
            prior_error = unmatched[album.id]
            transient = any(
                marker in prior_error
                for marker in ("HTTPError", "URLError", "TimeoutError", "JSONDecodeError")
            )
            if not args.retry_unmatched and not (args.retry_transient and transient):
                print(f"[{index}/{len(albums)}] #{album.rank}: previously unmatched")
                continue
        release_group_id, error = find_release_group(album)
        time.sleep(MUSICBRAINZ_INTERVAL_SECONDS)
        if error or not release_group_id:
            unmatched[album.id] = error or "musicbrainz:unknown"
            print(f"[{index}/{len(albums)}] #{album.rank}: {unmatched[album.id]}")
            continue
        error = download_cover(album, release_group_id, destination)
        if error:
            unmatched[album.id] = error
            print(f"[{index}/{len(albums)}] #{album.rank}: {error}")
            continue
        items[album.id] = {
            "path": relative_path,
            "source_url": f"https://coverartarchive.org/release-group/{release_group_id}/front-250",
            "musicbrainz_release_group_id": release_group_id,
        }
        unmatched.pop(album.id, None)
        print(f"[{index}/{len(albums)}] #{album.rank}: imported")
        MANIFEST_PATH.write_text(json.dumps({"schema_version": 1, "provider": "Cover Art Archive via MusicBrainz", "items": items, "unmatched": unmatched}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    MANIFEST_PATH.write_text(json.dumps({"schema_version": 1, "provider": "Cover Art Archive via MusicBrainz", "items": items, "unmatched": unmatched}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Complete: {len(items)} local covers; {len(unmatched)} unmatched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
