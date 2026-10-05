from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from prepare_catalogue_seed import CatalogueValidationError, parse_article  # noqa: E402


def article(headings: list[str]) -> str:
    return "".join(f'<h3 data-role="headline">{heading}</h3>' for heading in headings)


def complete_headings() -> list[str]:
    return [f"Artist {position} - ‘Album {position}’ [Country]" for position in range(1, 101)]


def test_parses_article_headings_without_editorial_content() -> None:
    rows = parse_article("<h3>RELATED</h3>" + article(complete_headings()) + "<p>Editorial prose</p>")

    assert len(rows) == 100
    assert rows[0].artist_credit == "Artist 1"
    assert rows[0].title == "Album 1"
    assert rows[0].country_label == "Country"
    assert rows[-1].rank == 100


def test_rejects_an_incomplete_list_without_leaking_source_text() -> None:
    sentinel = "RAW_SOURCE_MUST_NOT_ESCAPE"
    with pytest.raises(CatalogueValidationError, match="^catalogue_must_have_100_albums$") as error:
        parse_article(article(complete_headings()[:-1]) + sentinel)
    assert sentinel not in str(error.value)
