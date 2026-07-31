"""Season-scoped identity crosswalk from an external source to FPL `code`/`team_code`.

An external per-match source (FBref, an Understat mirror, a vendored dump) keys players by
its own ids and names; FPL keys them by the stable `code`. To join the two safely the
external roster must be resolved to FPL `code` **within a season**, never by a bare
cross-season id (R: `element_id`/`team_id` are reassigned yearly; only `code`/`team_code` are
1:1 with the permanent identity). This module builds that per-season map and reports exactly
which rows it could and could not resolve, so a downstream backfill can refuse anything
ambiguous rather than silently merge two players.

Matching precedence, per season:

  1. `opta_code` exact — the strongest anchor, but present only for 2024-25 and 2025-26 in the
     FPL archive, so it validates the recent join and cannot resolve the seasons being
     backfilled.
  2. normalised full name + club (`team_code`) — the working key when the club is resolved.
  3. normalised full name, unique within the season — the fallback when the club is unknown or
     unresolved; a name shared by two players in one season is reported ambiguous, not guessed.

Name normalisation strips diacritics and punctuation and lowercases, because `web_name`/full
names drift and accents vary between sources ("Raya Martín" vs "Raya Martin"). It is
deliberately exact-after-normalisation, not fuzzy: a residual unmatched set is reported for a
later, explicit fuzzy pass rather than hidden behind a similarity threshold here.

Pure and I/O-free: it operates on in-memory rosters so it can be exercised offline. A DB
loader that supplies the FPL roster from `raw_players`/`stg_player` lives with the ingest job
that consumes a chosen source.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from fpl.types import Season


def normalise_name(name: str) -> str:
    """Lowercase, strip diacritics, drop punctuation, collapse whitespace.

    "Raya Martín" and "Raya Martin" both normalise to "raya martin". An empty result (a name
    that is all punctuation) is returned as the empty string and never matches.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    kept = [ch.lower() if ch.isalnum() else " " for ch in without_marks]
    return " ".join("".join(kept).split())


@dataclass(frozen=True, slots=True)
class FplRosterEntry:
    """One FPL player in one season: the resolution target."""

    season: Season
    code: int
    team_code: int
    full_name: str
    opta_code: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalRosterEntry:
    """One external player in one season: the thing to resolve.

    `team_code` is the club resolved through a team-name crosswalk, or None when the external
    club could not be resolved (in which case only the name-in-season fallback can match).
    """

    season: Season
    external_id: str
    full_name: str
    team_code: int | None = None
    opta_code: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityMatch:
    """A resolved external -> FPL identity, tagged with how it was resolved."""

    season: Season
    external_id: str
    code: int
    method: str  # "opta" | "name_club" | "name_season"


@dataclass(frozen=True, slots=True)
class IdentityCrosswalkReport:
    """The full outcome of one season's resolution."""

    season: Season
    external_count: int
    fpl_count: int
    matches: tuple[IdentityMatch, ...]
    unmatched_external: tuple[str, ...]
    ambiguous_external: tuple[str, ...]
    unmatched_fpl: tuple[int, ...]

    @property
    def match_rate(self) -> float:
        """Fraction of external rows resolved to a unique FPL code."""
        if self.external_count == 0:
            return 1.0
        return len(self.matches) / self.external_count

    @property
    def matched_by_method(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for match in self.matches:
            counts[match.method] += 1
        return dict(counts)


def _index_by_opta(fpl: list[FplRosterEntry]) -> dict[str, list[FplRosterEntry]]:
    index: dict[str, list[FplRosterEntry]] = defaultdict(list)
    for entry in fpl:
        if entry.opta_code:
            index[entry.opta_code].append(entry)
    return index


def _index_by_name_club(fpl: list[FplRosterEntry]) -> dict[tuple[str, int], list[FplRosterEntry]]:
    index: dict[tuple[str, int], list[FplRosterEntry]] = defaultdict(list)
    for entry in fpl:
        index[(normalise_name(entry.full_name), entry.team_code)].append(entry)
    return index


def _index_by_name(fpl: list[FplRosterEntry]) -> dict[str, list[FplRosterEntry]]:
    index: dict[str, list[FplRosterEntry]] = defaultdict(list)
    for entry in fpl:
        index[normalise_name(entry.full_name)].append(entry)
    return index


def build_identity_crosswalk(
    fpl_roster: Iterable[FplRosterEntry],
    external_roster: Iterable[ExternalRosterEntry],
    *,
    season: Season,
) -> IdentityCrosswalkReport:
    """Resolve one season's external roster to FPL `code`, reporting every outcome.

    Both rosters are filtered to `season` first, so a bare cross-season id can never leak into
    a match. Each external row resolves by the highest-precedence rule that yields a *unique*
    FPL code; a rule that yields two or more candidates makes the row ambiguous and it is
    reported, not guessed.
    """
    fpl = [e for e in fpl_roster if e.season == season]
    external = [e for e in external_roster if e.season == season]

    by_opta = _index_by_opta(fpl)
    by_name_club = _index_by_name_club(fpl)
    by_name = _index_by_name(fpl)

    matches: list[IdentityMatch] = []
    unmatched: list[str] = []
    ambiguous: list[str] = []
    matched_codes: set[int] = set()

    for ext in external:
        resolved: tuple[int, str] | None = None
        blocked = False

        if ext.opta_code:
            candidates = by_opta.get(ext.opta_code, [])
            if len(candidates) == 1:
                resolved = (candidates[0].code, "opta")
            elif len(candidates) > 1:
                blocked = True

        if resolved is None and not blocked and ext.team_code is not None:
            candidates = by_name_club.get((normalise_name(ext.full_name), ext.team_code), [])
            if len(candidates) == 1:
                resolved = (candidates[0].code, "name_club")
            elif len(candidates) > 1:
                blocked = True

        if resolved is None and not blocked:
            candidates = by_name.get(normalise_name(ext.full_name), [])
            if len(candidates) == 1:
                resolved = (candidates[0].code, "name_season")
            elif len(candidates) > 1:
                blocked = True

        if resolved is not None:
            code, method = resolved
            matches.append(
                IdentityMatch(season=season, external_id=ext.external_id, code=code, method=method)
            )
            matched_codes.add(code)
        elif blocked:
            ambiguous.append(ext.external_id)
        else:
            unmatched.append(ext.external_id)

    unmatched_fpl = tuple(sorted(e.code for e in fpl if e.code not in matched_codes))

    return IdentityCrosswalkReport(
        season=season,
        external_count=len(external),
        fpl_count=len(fpl),
        matches=tuple(matches),
        unmatched_external=tuple(unmatched),
        ambiguous_external=tuple(ambiguous),
        unmatched_fpl=unmatched_fpl,
    )
