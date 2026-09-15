"""One-GW memoization of the existing observed-workload reader, not new semantics.

Resolve each of its three windows once across the declared club scope, then use
the unchanged exact-player lower-bound interpreter. No database, files, model fit,
global cache, inferred registration or zero-filled workload. Call once per GW
with unique exact identities; map absent identities to unavailable in the caller.
Original captures, known times, NULLs and completion proxies remain on every row.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from fpl.validate.competitive_workload_view import (
    WINDOW_HOURS,
    CompetitiveFixtureKey,
    CompetitiveMatchVersion,
    ObservedParticipationSnapshot,
    ObservedPlayerIdentity,
    RetrospectiveCompetitiveWorkloadView,
)

type _Segments = tuple[tuple[int, datetime, datetime], ...]
type _CacheKey = tuple[_Segments, datetime, frozenset[CompetitiveFixtureKey]]
type _Resolution = tuple[
    tuple[CompetitiveMatchVersion, ...], tuple[CompetitiveFixtureKey, ...], tuple[str, ...]
]


class _BatchView(RetrospectiveCompetitiveWorkloadView):
    """Private immutable-data snapshot; only the resolver's redundant work changes."""

    def __init__(self, source: RetrospectiveCompetitiveWorkloadView) -> None:
        # The source already validated these frozen records and selected the exact
        # interpretation/version policy. Copy its only mutable source container.
        self.fixtures = source.fixtures
        self.catalogue = source.catalogue
        self.memberships = source.memberships
        self.competitions = source.competitions
        self._versions = dict(source._versions)
        self._resolved: dict[_CacheKey, _Resolution] = {}

    def _resolve(
        self,
        segments: list[tuple[int, datetime, datetime]],
        cutoff: datetime,
        excluded: frozenset[CompetitiveFixtureKey],
    ) -> tuple[list[CompetitiveMatchVersion], tuple[CompetitiveFixtureKey, ...], list[str]]:
        key = tuple(segments), cutoff, excluded
        if key not in self._resolved:
            if len(self._resolved) == len(WINDOW_HOURS):
                raise ValueError("workload cache is bounded to one GW's three window scopes")
            selected, expected, issues = super()._resolve(segments, cutoff, excluded)
            self._resolved[key] = tuple(selected), expected, tuple(issues)
        selected_tuple, expected, issues_tuple = self._resolved[key]
        # The unchanged observer appends player-specific errors to `issues`.
        # Returning a shared list would contaminate the next player's evidence.
        return list(selected_tuple), expected, list(issues_tuple)


def observe_workload_batch(
    source: RetrospectiveCompetitiveWorkloadView,
    identities: Sequence[ObservedPlayerIdentity],
    *,
    scope_team_codes: frozenset[int],
    as_of: datetime,
    excluded_target_gw_fixtures: frozenset[CompetitiveFixtureKey],
) -> tuple[ObservedParticipationSnapshot, ...]:
    """Exact ordinary-reader outputs in identity order, at most three scope scans.

    Scope is the declared catalogue club universe, not an inference from a
    player's current club. Every DGW leg reuses this player's same pre-GW result.
    No cache survives the call: a different cutoff/exclusion/source version must
    resolve its own windows. The caller validates the complete target-GW crosswalk.
    """
    if type(source) is not RetrospectiveCompetitiveWorkloadView:
        raise ValueError("exact separately retrospective workload capability required")
    if any(type(identity) is not ObservedPlayerIdentity for identity in identities):
        raise ValueError("exact typed player identity witnesses required")
    if len({i.code for i in identities}) != len(identities) or len(
        {i.provider_player_id for i in identities}
    ) != len(identities):
        raise ValueError("one exact player/provider identity per GW; no duplicates or ambiguity")
    if as_of.utcoffset() is None or not scope_team_codes:
        raise ValueError("explicit aware cutoff and nonempty declared club scope required")
    cached = _BatchView(source)
    return tuple(
        cached.observed_participation_snapshot(
            identity=identity,
            scope_team_codes=scope_team_codes,
            as_of=as_of,
            excluded_target_gw_fixtures=excluded_target_gw_fixtures,
        )
        for identity in identities
    )
