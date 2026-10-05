#!/usr/bin/env python3
"""Enrich local African-album display metadata with MusicBrainz release years.

This release-preparation command is intentionally offline from the running app.
It stores only a first-release year verified from a high-confidence MusicBrainz
release group, plus a compact source trace. It never stores provider responses.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "api" / "app"
SEED_PATH = APP_DIR / "catalogue_seed.json"
TRACE_PATH = APP_DIR / "release_year_manifest.json"
sys.path.insert(0, str(ROOT / "scripts"))
from import_cover_art import (  # noqa: E402
    Album,
    MUSICBRAINZ_INTERVAL_SECONDS,
    find_release_group,
    get_json,
)


YEAR_RE = re.compile(r"^(?P<year>\d{4})(?:-\d{2}(?:-\d{2})?)?$")


def parse_release_year(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    matched = YEAR_RE.fullmatch(value)
    if not matched:
        return None
    year = int(matched.group("year"))
    return year if 1850 <= year <= datetime.now(UTC).year else None


def release_group_year(release_group_id: str) -> tuple[int | None, str | None, str | None]:
    url = f"https://musicbrainz.org/ws/2/release-group/{release_group_id}?fmt=json"
    try:
        payload = get_json(url)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        return None, None, f"musicbrainz:{type(error).__name__}"
    first_release_date = payload.get("first-release-date")
    year = parse_release_year(first_release_date)
    if year is None:
        return None, str(first_release_date or ""), "musicbrainz:no_parseable_first_release_date"
    return year, str(first_release_date), None


def load_cover_release_groups() -> dict[str, str]:
    cover_path = APP_DIR / "static" / "covers" / "index.json"
    if not cover_path.is_file():
        return {}
    payload = json.loads(cover_path.read_text(encoding="utf-8"))
    items = payload.get("items", {}) if isinstance(payload, dict) else {}
    return {
        str(album_id): str(item["musicbrainz_release_group_id"])
        for album_id, item in items.items()
        if isinstance(item, dict) and item.get("musicbrainz_release_group_id")
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Process only the first N catalogue rows.")
    parser.add_argument("--from-rank", type=int, default=1, help="First source position to process (inclusive).")
    parser.add_argument("--to-rank", type=int, default=100, help="Last source position to process (inclusive).")
    parser.add_argument("--retry-unmatched", action="store_true", help="Retry prior unmatched rows.")
    args = parser.parse_args()

    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    albums = list(seed["albums"])
    if not 1 <= args.from_rank <= args.to_rank <= 100:
        parser.error("--from-rank and --to-rank must be within 1 through 100")
    albums = [row for row in albums if args.from_rank <= int(row["rank"]) <= args.to_rank]
    if args.limit:
        albums = albums[:args.limit]
    previous = json.loads(TRACE_PATH.read_text(encoding="utf-8")) if TRACE_PATH.is_file() else {}
    items = dict(previous.get("items", {})) if isinstance(previous, dict) else {}
    unmatched = dict(previous.get("unmatched", {})) if isinstance(previous, dict) else {}
    cover_groups = load_cover_release_groups()

    for index, row in enumerate(albums, start=1):
        album_id = str(row["id"])
        if album_id in items:
            print(f"[{index}/{len(albums)}] #{row['rank']}: already enriched")
            continue
        if album_id in unmatched and not args.retry_unmatched:
            print(f"[{index}/{len(albums)}] #{row['rank']}: previously unmatched")
            continue
        release_group_id = cover_groups.get(album_id)
        if not release_group_id:
            release_group_id, error = find_release_group(
                Album(album_id, int(row["rank"]), str(row["title"]), str(row["artist_credit"]))
            )
            time.sleep(MUSICBRAINZ_INTERVAL_SECONDS)
            if error or not release_group_id:
                unmatched[album_id] = error or "musicbrainz:unknown"
                print(f"[{index}/{len(albums)}] #{row['rank']}: {unmatched[album_id]}")
                continue
        year, first_release_date, error = release_group_year(release_group_id)
        time.sleep(MUSICBRAINZ_INTERVAL_SECONDS)
        if error or year is None:
            unmatched[album_id] = error or "musicbrainz:unknown"
            print(f"[{index}/{len(albums)}] #{row['rank']}: {unmatched[album_id]}")
            continue
        items[album_id] = {
            "musicbrainz_release_group_id": release_group_id,
            "source_url": f"https://musicbrainz.org/release-group/{release_group_id}",
            "first_release_date": first_release_date,
            "release_year": year,
        }
        unmatched.pop(album_id, None)
        print(f"[{index}/{len(albums)}] #{row['rank']}: {year}")

    for row in seed["albums"]:
        trace = items.get(str(row["id"]))
        row["release_year"] = trace["release_year"] if trace else None
    normalized = json.dumps(
        [
            {"id": row["id"], "release_year": row["release_year"]}
            for row in seed["albums"]
        ],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    seed.setdefault("provenance", {})["release_year_enrichment"] = {
        "provider": "MusicBrainz",
        "retrieved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "matched_count": len(items),
        "unmatched_count": len(unmatched),
        "normalized_content_sha256": sha256(normalized).hexdigest(),
        "note": "Supplemental display metadata; catalogue_version remains the stable journey ordering key.",
    }
    write_json(SEED_PATH, seed)
    write_json(TRACE_PATH, {
        "schema_version": 1,
        "provider": "MusicBrainz",
        "items": items,
        "unmatched": unmatched,
    })
    print(f"Complete: {len(items)} years; {len(unmatched)} unmatched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
