#!/usr/bin/env python3
"""Create the reviewed 100-album seed from the OkayAfrica article.

This release-preparation command reads source HTML into memory and writes only
normalized factual fields. It never retains article prose, images, embeds, or
the raw response. The running application does not call this command.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5


SOURCE_URL = "https://www.okayafrica.com/the-100-best-african-albums-according-to-our-readers/1404354"
SOURCE_TITLE = "The 100 Best African Albums (According To Our Readers)"
SOURCE_RIGHTS = "Source page copyright © OkayAfrica; normalized factual list used with attribution"
MAX_SOURCE_BYTES = 3 * 1024 * 1024
HEADING_PATTERN = re.compile(
    r"^(?P<artist>.+?)\s+[\-–]\s+[‘'](?P<title>.+)[’']\s+\[(?P<country>.+)\]$"
)


class CatalogueValidationError(ValueError):
    """A safe validation category that never includes raw source content."""


@dataclass(frozen=True, slots=True)
class SourceAlbum:
    rank: int
    title: str
    release_year: None
    artist_credit: str
    country_label: str


class ArticleHeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[str] = []
        self._parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "h3" and attributes.get("data-role") == "headline":
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._parts is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3" and self._parts is not None:
            self.headings.append(" ".join("".join(self._parts).split()))
            self._parts = None


def parse_article(html: str) -> tuple[SourceAlbum, ...]:
    parser = ArticleHeadingParser()
    parser.feed(html)
    parser.close()
    rows: list[SourceAlbum] = []
    for heading in parser.headings:
        match = HEADING_PATTERN.fullmatch(heading)
        if match:
            rows.append(
                SourceAlbum(
                    rank=len(rows) + 1,
                    title=match.group("title"),
                    release_year=None,
                    artist_credit=match.group("artist"),
                    country_label=match.group("country"),
                )
            )
    if len(rows) != 100:
        raise CatalogueValidationError("catalogue_must_have_100_albums")
    return tuple(rows)


def fetch_source() -> str:
    request = Request(SOURCE_URL, headers={"User-Agent": "african-album-journey-release-prep/1"})
    with urlopen(request, timeout=30) as response:
        payload = response.read(MAX_SOURCE_BYTES + 1)
    if len(payload) > MAX_SOURCE_BYTES:
        raise CatalogueValidationError("source_response_too_large")
    return payload.decode("utf-8")


def build_seed(rows: tuple[SourceAlbum, ...], retrieved_at: datetime) -> dict[str, object]:
    normalized = json.dumps(
        [asdict(row) for row in rows], ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    digest = hashlib.sha256(normalized).hexdigest()
    albums = []
    for row in rows:
        album = asdict(row)
        album["id"] = str(uuid5(NAMESPACE_URL, f"{SOURCE_URL}#position={row.rank}"))
        albums.append(album)
    return {
        "schema_version": 1,
        "catalogue_version": f"okayafrica-readers-100-{digest[:12]}",
        "provenance": {
            "source_url": SOURCE_URL,
            "source_title": SOURCE_TITLE,
            "license": SOURCE_RIGHTS,
            "retrieved_at": retrieved_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "normalized_content_sha256": digest,
            "ordering_note": "Position follows article display order and is not a best-to-worst ranking.",
        },
        "albums": albums,
    }


def write_seed(output: Path, payload: dict[str, object]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(output)
    output.chmod(0o644)


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--input", type=Path, help="reviewed HTML file; omit to fetch the source")
    arguments.add_argument(
        "--output",
        type=Path,
        default=project_root / "api" / "app" / "catalogue_seed.json",
    )
    args = arguments.parse_args()
    html = args.input.read_text(encoding="utf-8") if args.input else fetch_source()
    write_seed(args.output, build_seed(parse_article(html), datetime.now(UTC)))
    print(f"Wrote 100 normalized album facts to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
