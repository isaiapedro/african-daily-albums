from __future__ import annotations

import json
from pathlib import Path
import sys
from uuid import UUID

from app.cover_manifest import load_cover_manifest


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import import_cover_art  # noqa: E402


def test_musicbrainz_match_requires_title_and_artist(monkeypatch) -> None:
    album = import_cover_art.Album("album-id", 1, "Africa to the World", "Sun-El Musician")
    monkeypatch.setattr(
        import_cover_art,
        "get_json",
        lambda _url: {
            "release-groups": [
                {
                    "id": "release-group-id",
                    "title": "Africa to the World",
                    "score": 100,
                    "artist-credit": [{"name": "Sun-El Musician"}],
                }
            ]
        },
    )

    assert import_cover_art.find_release_group(album) == ("release-group-id", None)


def test_musicbrainz_match_rejects_same_title_by_another_artist(monkeypatch) -> None:
    album = import_cover_art.Album("album-id", 1, "Promise", "Sade")
    monkeypatch.setattr(
        import_cover_art,
        "get_json",
        lambda _url: {
            "release-groups": [
                {
                    "id": "wrong-release-group",
                    "title": "Promise",
                    "score": 100,
                    "artist-credit": [{"name": "Another Artist"}],
                }
            ]
        },
    )

    assert import_cover_art.find_release_group(album) == (None, "musicbrainz:no_confident_match")


def test_cover_manifest_exposes_only_safe_local_paths(tmp_path: Path) -> None:
    album_id = UUID("6953beec-2ca3-5332-b468-f1391fbad41f")
    path = tmp_path / "index.json"
    path.write_text(
        json.dumps(
            {
                "items": {
                    str(album_id): {
                        "path": f"covers/{album_id}.jpg",
                        "source_url": "https://coverartarchive.org/release-group/example/front-250",
                        "musicbrainz_release_group_id": "example",
                    },
                    "9989c936-f9d1-5f50-8a29-7b117e71704c": {
                        "path": "covers/../private.txt"
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    assets = load_cover_manifest(path)

    assert assets[album_id].path == f"covers/{album_id}.jpg"
    assert len(assets) == 1
