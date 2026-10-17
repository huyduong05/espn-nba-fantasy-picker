# Phase 1 Source Evaluation

Research date: 2026-10-15.

The machine-readable decision record is `config/sources.yaml`. This document
explains why each source was selected, rejected, or left for a user decision.
Terms and subscription tiers can change, so they must be reviewed when the data
is refreshed for a future season.

## Selected by user direction: NBA statistics

NBA.com season-average snapshots are the selected input for this local,
educational side project. The downloader has acquired the 2021-22 through
2025-26 regular seasons with 2,867 player-season rows and all required raw
nine-category fields. `fantasy-picker data coverage` verifies this five-season
gate directly from the cached files and manifests.

This selection is not a legal conclusion or a license grant. Section 9 of the
[NBA.com Terms of Use](https://www.nba.com/termsofuse) restricts using NBA
Statistics in connection with a fantasy game. Every snapshot remains labeled
with that restriction in its provenance manifest.

## Optional: NBA statistics, identity, and current injuries

Primary candidate: [BALLDONTLIE NBA API](https://docs.balldontlie.io/).

Why it fits:

- The provider documents NBA coverage from 1946 to current and season averages
  from 1996 onward.
- Season-average records expose the required games, minutes, counting stats,
  shooting makes, and shooting attempts.
- Player records contain provider IDs, positions, college/country, and draft
  metadata.
- A current player-injury endpoint provides status, description, and return-date
  text.
- The [BALLDONTLIE terms](https://www.balldontlie.io/terms.html) expressly allow
  fantasy sports and AI/model development and describe the data as unofficial,
  aggregated, and best-effort.

Access constraint:

- Five-season aggregate statistics require the NBA GOAT tier, listed at USD
  39.99/month at research time.
- Active-player and current-injury endpoints require ALL-STAR or higher.
- An API key must be supplied only through `BALLDONTLIE_API_KEY`.

The downloader remains implemented, but no BALLDONTLIE data will be acquired
unless the user later chooses to supply a key and subscription. Its empty cache
is reported separately from the selected NBA.com snapshot coverage, so the
optional provider cannot make the five-season gate appear to fail.

The unofficial
[`nba_api` endpoint documentation](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/leaguedashplayerstats.md)
confirms that the endpoint has the desired fields, but the wrapper's open-source
license does not override the data terms. Run
`.venv/bin/fantasy-picker data fetch-nba-com` to acquire the five most recently
completed seasons for learning and exploration.

## Selected: college statistics

Primary source:
[SportsDataverse NCAA men's basketball player boxes](https://github.com/sportsdataverse/ncaa-mbb-hoops-data),
published as release assets in
[`sportsdataverse-data`](https://github.com/sportsdataverse/sportsdataverse-data).

Why it fits:

- The producer states that its upstream records are from `stats.ncaa.org`.
- The central dataset is licensed under CC BY 4.0.
- It publishes stable player and contest identifiers plus points, rebounds,
  assists, steals, blocks, turnovers, FGM/FGA, 3PM/3PA, FTM/FTA, and minutes.
- The release workflow documents 51 historical seasons through 2025-26.

Measured local coverage:

- 2024-25: 127,466 player-game records; 10,003,990 compressed bytes.
- 2025-26: 127,465 player-game records; 9,910,401 compressed bytes.
- Both files include the fields required to derive the nine-category per-game
  inputs after Phase 2 aggregation.

Attribution: data copyright belongs to the SportsDataverse contributors and is
used under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The local
pipeline does not claim endorsement by the NCAA or SportsDataverse.

Fallback candidate:
[CollegeBasketballData](https://api.collegebasketballdata.com/getting-started).
Its terms permit model and commercial use, but it requires a user-specific key;
the selected CC BY dataset avoids that dependency. It should be reconsidered if
the selected release has a material coverage gap.

## Scope decided; source still required: international statistics

[BALLDONTLIE's catalog](https://www.balldontlie.io/docs/) lists fifteen relevant
international competitions, including EuroLeague, EuroCup, Basketball Champions
League, Liga ACB, and several major domestic leagues. Its league documentation
states that player statistics require the GOAT tier for each sport. ALL-ACCESS,
which spans every provider sport, was listed at USD 299.99/month.

The user limited acquisition to rookies/newly drafted players on active NBA
rosters. Phase 2 identity work must derive that allowlist from those players'
career histories rather than treating birthplace as evidence of league
experience. When a qualifying league lacks a free public dataset, that player is
omitted from international acquisition and explicitly marked low-information.

The cached NBA player index is measured by `fantasy-picker data coverage`: it
reports the active-player and new-NBA-player counts while explicitly recording
that it has no prior club or league history. Therefore it does **not** claim
international coverage by inference. The present decision for each qualifying
player is either to fund a licensed provider (such as BALLDONTLIE) or omit the
unavailable international record and carry the low-information flag. That gap is
documented rather than silently filled with a name or country match.

The official [FIBA GDAP](https://gdap-portal.fiba.basketball/) was not selected.
It requires registration and may restrict access to specifically authorized
competitions, so it cannot be assumed to provide universal public coverage.

## Selected: historical injuries and absences

The selected event dataset is Randall Hopkins's
[NBA Injuries from 2010-2020](https://www.kaggle.com/datasets/ghopkins/nba-injuries-2010-2018).
Kaggle metadata declares version 3 as `CC0: Public Domain`; its 27,105 records
cover 2010-11 through 2019-20 and the publisher attributes the underlying scrape
to Pro Sports Transactions.

The archive is old, so Phase 5 must combine its recurrence/type evidence with
games missed derived from recent season participation. It cannot provide current
status, and missing recent events must not be treated as evidence of perfect
health. Run `.venv/bin/fantasy-picker data fetch-injuries` to acquire or verify
the archive and its publisher metadata.

During `fantasy-picker data normalize`, only `Relinquished` archive entries are
converted to historical absence events. The archive has no stable player IDs, so
each source name must be explicitly reviewed in `injury_manual_mappings` in
`config/identity-review.yaml` and mapped to an NBA player ID. Unmapped names and
name-based candidate IDs are written to `data/processed/unresolved_injury_matches.json`;
they are not linked automatically. The archive has no defensible end dates or
games-missed totals, so those normalized fields remain unknown.

Current status may be acquired from the NBA's official injury reports under the
same user-directed educational-use decision as NBA.com statistics. Those reports
must remain separately labeled with NBA.com terms and cached before draft time.

## Phase 5 availability scoring

`config/injury-risk.yaml` defines a fully local, inspectable recommendation
penalty. It uses recency-weighted historical games missed, repeated event
descriptions, current status, reported return timeline, and current suspension,
personal-absence, or load-management status. The result is bounded at 15% and
does not modify projected per-game statistics. Confirmed current IR eligibility
reduces the recommendation penalty by the configured amount.

An absence of current data is emitted as `CURRENT_STATUS_UNAVAILABLE` and
`NO_INJURY_DATA` or `HISTORICAL_ONLY`. It is neither evidence that a player is
healthy nor a synthetic injury event. The historical Kaggle archive must be
identity-resolved through a reviewed mapping before it enters this scorer;
unmatched source names remain excluded rather than auto-linked.

## Refresh and provenance behavior

- Raw files are stored under `data/raw/<source>/<batch>/` and excluded from Git.
- Every file receives an adjacent schema-validated manifest containing its exact
  stable request URL, UTC retrieval timestamp, SHA-256 digest, byte count, media
  type, source, dataset, license, and notes.
- A same-day rerun reuses a snapshot only after checksum verification.
- `--refresh` creates a timestamped immutable batch.
- Requests retry transient network/server failures, honor `Retry-After`, apply a
  minimum request interval, and never write an API key to a URL or manifest.
- NBA.com educational snapshots are stored under the distinct `nba_stats` source
  and appear in a separate coverage-report section that records both the user's
  selection and the absence of a permissive data license.

