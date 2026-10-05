# Data pipeline contract

```text
OkayAfrica article (explicit release preparation only)
  -> parse album heading facts only
  -> validate exactly 100 positions and deterministic normalized hash
  -> discard raw HTML
  -> bundle immutable JSON seed
  -> initialize application-owned SQLite albums table
  -> derive per-journey order from journey UUID + catalogue version
  -> persist only assignments, ratings, and reviews

Optional cover preparation (explicit command only)
  -> query MusicBrainz by normalized album + artist
  -> accept only high-confidence title-and-artist matches
  -> download a bounded CAA front thumbnail
  -> store local image + source/release-group manifest
  -> serve same-origin, or use the typographic fallback

Optional release-year preparation (explicit command only)
  -> reuse a cover manifest release group or resolve a high-confidence MusicBrainz match
  -> accept only a parseable `first-release-date` year
  -> store the year in the local seed plus a release-group trace manifest
  -> refresh immutable album metadata on application startup without changing private journeys
```

The source country labels are retained verbatim as labels rather than corrected
or reinterpreted. A future source correction or catalogue change requires a new
reviewed seed version. Private journey data never enters source preparation,
provenance, logs, external research, or the Brazilian app.
