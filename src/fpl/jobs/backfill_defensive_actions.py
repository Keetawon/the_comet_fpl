"""Validate an external defensive-actions dump and run the 2025-26 overlap gate.

    python -m fpl.jobs.backfill_defensive_actions --csv <canonical.csv> [--database <fpl.duckdb>]

Stage C's DC component needs per-match defensive actions for 2021-22..2024-25, which FPL
never recorded. This job is the B-path precursor to any backfill: it reads a locally-pulled
FBref dump (`fpl.ingest.defensive_actions_csv`), resolves each external player to an FPL
`code` per season via the season-scoped identity crosswalk, and -- on the 2025-26 overlap
season, the one season carrying both FPL's own DC and the external actions -- rebuilds DC
from the external actions and requires it to reproduce FPL's recorded DC. Only if that gate
passes is the dump's definition trustworthy enough to backfill the four earlier seasons.

This job VALIDATES and REPORTS; it does not emit a backfill table. The acceptance gate
(non-negotiable, pinned as constants below) is:

    external-rebuilt DC reproduces FPL recorded DC at >= 99.5% exact agreement across
    DEF/MID/FWD scoring rows, AND the season-scoped identity match rate is >= 98%.

It exits non-zero if the overlap season is present and the gate fails, and it never writes a
backfill on failure. fbref.com is blocked here, so the CSV is operator-supplied; treat the
dump as an unverified assumption until the gate passes.
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import duckdb

from fpl.config import load_sources, repo_root
from fpl.ingest.defensive_actions_csv import count_null_count_rows, read_defensive_actions_csv
from fpl.storage.db import connect
from fpl.transform.defensive_actions import (
    DcObservation,
    DcReconstructionReport,
    ExternalDefensiveActions,
    check_dc_reconstruction,
)
from fpl.transform.external_identity import (
    ExternalRosterEntry,
    FplRosterEntry,
    IdentityCrosswalkReport,
    build_identity_crosswalk,
    normalise_name,
)
from fpl.types import Position, Season

logger = logging.getLogger("fpl.backfill_defensive_actions")

# Acceptance gate (objective, non-negotiable). Pinned as constants, not config-editable, so
# the bar cannot be relaxed after seeing a result -- the same discipline as the phase gates.
OVERLAP_SEASON: Final[str] = "2025-26"
MIN_DC_EXACT_AGREEMENT: Final[float] = 0.995
MIN_IDENTITY_MATCH_RATE: Final[float] = 0.98


# --------------------------------------------------------------------------------------
# Team-name crosswalk (external club string -> stable team_code). Pure + offline-testable.
# --------------------------------------------------------------------------------------
#
# FBref club strings diverge from FPL team names ("Manchester United" vs "Man Utd",
# "Nottingham Forest" vs "Nott'm Forest", ...). Both sides are reduced to one canonical token
# per club so a match does not depend on knowing either side's exact spelling: normalise first
# (strip diacritics/punctuation), then map any known variant to its canonical token, else keep
# the normalised name. A name that still does not resolve is reported, never guessed -- the
# operator extends this map from the unresolved report. Two clubs can never collapse to one
# token here (each token names a single club), so a wrong/missing alias cannot silently merge
# two clubs' players; it only leaves that club's external rows unresolved (visible in the
# report). team_code is 1:1 with the club across seasons, so the index is built per season from
# that season's 20 clubs.
_CLUB_VARIANTS: Final[dict[str, str]] = {
    "manchester city": "man city",
    "man city": "man city",
    "manchester united": "man utd",
    "manchester utd": "man utd",
    "man united": "man utd",
    "man utd": "man utd",
    "newcastle united": "newcastle",
    "newcastle utd": "newcastle",
    "newcastle": "newcastle",
    "tottenham hotspur": "spurs",
    "tottenham": "spurs",
    "spurs": "spurs",
    "west ham united": "west ham",
    "west ham": "west ham",
    "wolverhampton wanderers": "wolves",
    "wolverhampton": "wolves",
    "wolves": "wolves",
    "brighton and hove albion": "brighton",
    "brighton hove albion": "brighton",
    "brighton": "brighton",
    "nottingham forest": "forest",
    "nottm forest": "forest",
    "nott m forest": "forest",
    "forest": "forest",
    "leicester city": "leicester",
    "leicester": "leicester",
    "ipswich town": "ipswich",
    "ipswich": "ipswich",
    "leeds united": "leeds",
    "leeds": "leeds",
    "sheffield united": "sheffield utd",
    "sheffield utd": "sheffield utd",
}


def _canonical_club(name: str) -> str:
    return _CLUB_VARIANTS.get(normalise_name(name), normalise_name(name))


@dataclass(frozen=True, slots=True)
class FplTeamRow:
    season: Season
    team_code: int
    team_name: str


@dataclass(frozen=True, slots=True)
class TeamNameIndex:
    """Per-season map from canonical club token -> team_code(s). Built from FPL team names."""

    season: Season
    _canonical_to_codes: dict[str, frozenset[int]]

    def resolve(self, external_team_name: str) -> int | None:
        codes = self._canonical_to_codes.get(_canonical_club(external_team_name))
        if codes is not None and len(codes) == 1:
            return next(iter(codes))
        return None  # unresolved, or (rare) ambiguous across clubs


def build_team_name_index(teams: Iterable[FplTeamRow], *, season: Season) -> TeamNameIndex:
    by_canonical: dict[str, set[int]] = defaultdict(set)
    for team in teams:
        by_canonical[_canonical_club(team.team_name)].add(team.team_code)
    return TeamNameIndex(
        season=season,
        _canonical_to_codes={k: frozenset(v) for k, v in by_canonical.items()},
    )


def load_fpl_teams(con: duckdb.DuckDBPyConnection, *, season: Season) -> list[FplTeamRow]:
    rows = con.execute(
        """
        SELECT team_code, team_name
        FROM mart_dim_team
        WHERE season = ? AND team_code IS NOT NULL
        """,
        [season],
    ).fetchall()
    return [
        FplTeamRow(season=season, team_code=int(team_code), team_name=str(team_name))
        for team_code, team_name in rows
    ]


def load_fpl_roster(con: duckdb.DuckDBPyConnection, *, season: Season) -> list[FplRosterEntry]:
    """One FplRosterEntry per player in the season.

    `code` is the stable cross-season key; `team_code` is the club resolved through
    `mart_dim_team` (1:1 with the club). `full_name` is first_name + ' ' + second_name from
    `raw_players` (web_name drifts and is not used). `opta_code` is present only for 2024-25
    and 2025-26, so it anchors the recent join but cannot resolve the backfilled seasons. The
    INNER JOIN guarantees a team_code: every player finished the season on a registered club.
    Note this is the end-of-season club (a transfer's destination); identity disambiguation
    tolerates that, and ambiguous/unmatched rows are reported rather than guessed.
    """
    rows = con.execute(
        """
        SELECT CAST(rp.code AS INTEGER) AS code,
               rp.first_name,
               rp.second_name,
               rp.opta_code,
               mt.team_code
        FROM raw_players rp
        JOIN mart_dim_team mt
          ON mt.season = rp.season AND mt.team_id = TRY_CAST(rp.team AS INTEGER)
        WHERE rp.season = ?
          AND TRY_CAST(rp.element_type AS INTEGER) <> 5
        """,
        [season],
    ).fetchall()
    entries: list[FplRosterEntry] = []
    for code, first_name, second_name, opta_code, team_code in rows:
        full_name = f"{first_name} {second_name}".strip()
        entries.append(
            FplRosterEntry(
                season=season,
                code=int(code),
                team_code=int(team_code),
                full_name=full_name,
                opta_code=opta_code,
            )
        )
    return entries


def build_external_roster(
    actions: Iterable[ExternalDefensiveActions],
    team_index: TeamNameIndex,
    *,
    season: Season,
) -> tuple[list[ExternalRosterEntry], list[str]]:
    """One ExternalRosterEntry per external player in the season, plus unresolved team names.

    The external id is FBref's, not an Opta id, so opta_code is always None and the opta match
    path never fires for the external side; resolution runs on name+club then name-in-season.
    team_code is None when the club string did not resolve (reported in the second return).
    """
    entries: list[ExternalRosterEntry] = []
    seen: set[str] = set()
    unresolved: list[str] = []
    unresolved_seen: set[str] = set()
    for action in actions:
        if action.season != season or action.external_player_id in seen:
            continue
        seen.add(action.external_player_id)
        team_code = team_index.resolve(action.team_name)
        if team_code is None and action.team_name not in unresolved_seen:
            unresolved_seen.add(action.team_name)
            unresolved.append(action.team_name)
        entries.append(
            ExternalRosterEntry(
                season=season,
                external_id=action.external_player_id,
                full_name=action.player_name,
                team_code=team_code,
            )
        )
    return entries, unresolved


# --------------------------------------------------------------------------------------
# Overlap gate: rebuild DC from external actions, compare to FPL's recorded DC.
# --------------------------------------------------------------------------------------


def _load_fpl_overlap_index(
    con: duckdb.DuckDBPyConnection, *, season: Season
) -> dict[tuple[int, str], tuple[Position, int]]:
    """FPL (code, kickoff date) -> (position, recorded DC) for one season, NULL DC skipped."""
    rows = con.execute(
        """
        SELECT code, CAST(kickoff_time AS DATE) AS kickoff_date, position, defensive_contribution
        FROM mart_fact_player_fixture
        WHERE season = ? AND defensive_contribution IS NOT NULL
        """,
        [season],
    ).fetchall()
    index: dict[tuple[int, str], tuple[Position, int]] = {}
    for code, kickoff_date, position, recorded_dc in rows:
        index[(int(code), str(kickoff_date))] = (Position(position), int(recorded_dc))
    return index


def align_overlap_observations(
    actions: Iterable[ExternalDefensiveActions],
    fpl_by_key: dict[tuple[int, str], tuple[Position, int]],
    code_by_external: dict[str, int],
    *,
    season: Season,
) -> list[DcObservation]:
    """Pure alignment: each resolved external player-match -> a DcObservation.

    The join is (resolved code, match date): a player appears in one fixture per date, so the
    external match_date aligns to the FPL kickoff date. Unresolved or unaligned rows are
    skipped. Split out of `build_overlap_observations` so the alignment + gate are testable
    without a database.
    """
    observations: list[DcObservation] = []
    for action in actions:
        if action.season != season:
            continue
        code = code_by_external.get(action.external_player_id)
        if code is None:
            continue
        fpl = fpl_by_key.get((code, action.match_date))
        if fpl is None:
            continue
        position, recorded_dc = fpl
        observations.append(
            DcObservation(
                position=position,
                tackles=action.tackles,
                cbi=action.cbi,
                recoveries=action.recoveries,
                recorded_dc=recorded_dc,
            )
        )
    return observations


def build_overlap_observations(
    con: duckdb.DuckDBPyConnection,
    actions: Iterable[ExternalDefensiveActions],
    crosswalk: IdentityCrosswalkReport,
    *,
    season: Season,
) -> list[DcObservation]:
    """Align each resolved external player-match to its FPL fixture and build DcObservations.

    Thin DB wrapper over `align_overlap_observations`: it fetches FPL's recorded DC per
    (code, kickoff date), then aligns. NULL recorded DC is skipped at the SQL filter (never
    zeroed). A double gameweek with two of a player's fixtures on the same date is a rare
    collision; it would surface as a handful of mismatched rows in the gate, not silent
    corruption.
    """
    fpl_by_key = _load_fpl_overlap_index(con, season=season)
    code_by_external = {match.external_id: match.code for match in crosswalk.matches}
    return align_overlap_observations(actions, fpl_by_key, code_by_external, season=season)


@dataclass(frozen=True, slots=True)
class OverlapGateResult:
    agreement_rate: float
    match_rate: float
    scoring_rows: int
    mismatches: int
    passed: bool


def evaluate_overlap_gate(
    report: DcReconstructionReport,
    *,
    match_rate: float,
    min_agreement: float = MIN_DC_EXACT_AGREEMENT,
    min_match_rate: float = MIN_IDENTITY_MATCH_RATE,
) -> OverlapGateResult:
    """Pure gate decision: >= min_agreement exact DC AND >= min_match_rate identity match."""
    passed = report.agreement_rate >= min_agreement and match_rate >= min_match_rate
    return OverlapGateResult(
        agreement_rate=report.agreement_rate,
        match_rate=match_rate,
        scoring_rows=report.scoring_rows,
        mismatches=report.mismatches,
        passed=passed,
    )


def _log_season_report(
    season: Season, crosswalk: IdentityCrosswalkReport, unresolved_teams: list[str]
) -> None:
    logger.info("--- %s ---", season)
    logger.info(
        "identity match rate: %.4f (%d/%d external resolved)",
        crosswalk.match_rate,
        len(crosswalk.matches),
        crosswalk.external_count,
    )
    logger.info("matched by method: %s", crosswalk.matched_by_method)
    if crosswalk.ambiguous_external:
        logger.info(
            "ambiguous external ids (%d): %s",
            len(crosswalk.ambiguous_external),
            list(crosswalk.ambiguous_external)[:10],
        )
    if crosswalk.unmatched_external:
        logger.info(
            "unmatched external ids (%d): %s",
            len(crosswalk.unmatched_external),
            list(crosswalk.unmatched_external)[:10],
        )
    if unresolved_teams:
        logger.info("UNRESOLVED team names (%d): %s", len(unresolved_teams), unresolved_teams[:20])


def _log_overlap(report: DcReconstructionReport, gate: OverlapGateResult) -> None:
    logger.info("--- overlap gate (%s) ---", OVERLAP_SEASON)
    logger.info(
        "DC exact agreement: %.6f (%d/%d scoring rows; %d mismatch)",
        gate.agreement_rate,
        report.exact_matches,
        report.scoring_rows,
        gate.mismatches,
    )
    logger.info("identity match rate: %.4f", gate.match_rate)
    if report.mismatch_examples:
        logger.info("mismatch examples (pos, rebuilt, recorded): %s", report.mismatch_examples[:5])
    logger.info(
        "GATE %s (requires agreement >= %.3f AND match rate >= %.4f)",
        "PASSED" if gate.passed else "FAILED",
        MIN_DC_EXACT_AGREEMENT,
        MIN_IDENTITY_MATCH_RATE,
    )


def run(
    csv_path: str | Path,
    *,
    db_path: Path | None = None,
    overlap_season: str = OVERLAP_SEASON,
) -> int:
    """Validate the dump and run the overlap gate. Return 0 on pass / no-gate, 1 on failure."""
    actions = read_defensive_actions_csv(csv_path)
    null_count_rows = count_null_count_rows(csv_path)
    seasons = sorted({action.season for action in actions})
    logger.info(
        "loaded %d complete defensive-action rows across %d season(s) from %s",
        len(actions),
        len(seasons),
        csv_path,
    )
    if null_count_rows:
        logger.info(
            "skipped %d row(s) with at least one blank count (NULL preserved, never zeroed).",
            null_count_rows,
        )

    gate: OverlapGateResult | None = None
    con = connect(db_path, read_only=True)
    try:
        for season in seasons:
            fpl_roster = load_fpl_roster(con, season=season)
            teams = load_fpl_teams(con, season=season)
            team_index = build_team_name_index(teams, season=season)
            external_roster, unresolved_teams = build_external_roster(
                actions, team_index, season=season
            )
            crosswalk = build_identity_crosswalk(fpl_roster, external_roster, season=season)
            _log_season_report(season, crosswalk, unresolved_teams)
            if season == overlap_season:
                observations = build_overlap_observations(con, actions, crosswalk, season=season)
                report = check_dc_reconstruction(observations)
                gate = evaluate_overlap_gate(report, match_rate=crosswalk.match_rate)
                _log_overlap(report, gate)
    finally:
        con.close()

    if overlap_season not in seasons:
        logger.warning(
            "overlap season %s is absent from the dump; no gate ran. Provide it to gate the "
            "dump's definition before trusting a backfill.",
            overlap_season,
        )

    if gate is not None and not gate.passed:
        logger.error("overlap gate FAILED; refusing to emit any backfill.")
        return 1

    logger.info(
        "validation complete; no backfill emitted (this job gates the dump; the backfill is a "
        "later step)."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate an external defensive-actions dump and run the 2025-26 overlap gate."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Canonical-column defensive-actions CSV. Defaults to config "
        "defensive_actions_dump.csv_path.",
    )
    parser.add_argument("--database", type=Path, default=None, help="Path to the DuckDB file.")
    parser.add_argument(
        "--overlap-season",
        default=None,
        help="Overlap season to gate (default from config, else 2025-26).",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    sources = load_sources()
    csv_path = args.csv
    overlap_season = args.overlap_season
    dump = sources.defensive_actions_dump
    if csv_path is None:
        if dump is None:
            parser.error(
                "--csv is required (no defensive_actions_dump configured in sources.yaml)."
            )
        csv_path = repo_root() / dump.csv_path
    if overlap_season is None:
        overlap_season = dump.overlap_season if dump is not None else OVERLAP_SEASON
    return run(csv_path, db_path=args.database, overlap_season=overlap_season)


if __name__ == "__main__":
    raise SystemExit(main())
