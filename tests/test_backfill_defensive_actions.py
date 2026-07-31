"""Network-free tests for the defensive-actions backfill job.

Covers the pure, DB-free pieces: the team-name crosswalk (variant resolution, unknown and
ambiguous reporting), the external-roster builder (resolve + dedupe + unresolved clubs), the
end-to-end identity wiring on the synthetic fixture, and the 2025-26 overlap gate logic
(pass on a good alignment; fail on a DC mismatch; fail on a low identity match rate). The
DB-reading loaders and the DB wrapper are thin SQL exercised when the operator runs the job
against a real database.
"""

from __future__ import annotations

from pathlib import Path

from fpl.ingest.defensive_actions_csv import read_defensive_actions_csv
from fpl.jobs.backfill_defensive_actions import (
    FplTeamRow,
    align_overlap_observations,
    build_external_roster,
    build_team_name_index,
    evaluate_overlap_gate,
)
from fpl.transform.defensive_actions import (
    ExternalDefensiveActions,
    check_dc_reconstruction,
)
from fpl.transform.external_identity import (
    FplRosterEntry,
    build_identity_crosswalk,
)
from fpl.types import Position

FIXTURE = Path(__file__).parent / "fixtures" / "defensive_actions_sample.csv"


def _action(
    external_id: str,
    name: str,
    team: str,
    *,
    season: str = "2025-26",
    date: str = "2025-08-16",
    tackles: int = 0,
    interceptions: int = 0,
    blocks: int = 0,
    clearances: int = 0,
    recoveries: int = 0,
) -> ExternalDefensiveActions:
    return ExternalDefensiveActions(
        season=season,
        external_player_id=external_id,
        player_name=name,
        team_name=team,
        match_date=date,
        tackles=tackles,
        interceptions=interceptions,
        blocks=blocks,
        clearances=clearances,
        recoveries=recoveries,
    )


_FPL_TEAMS_2025_26 = [
    FplTeamRow("2025-26", 1, "Arsenal"),
    FplTeamRow("2025-26", 2, "Man Utd"),
    FplTeamRow("2025-26", 3, "Newcastle"),
    FplTeamRow("2025-26", 4, "Nott'm Forest"),
    FplTeamRow("2025-26", 5, "Man City"),
]


def test_team_name_index_resolves_variants_and_reports_unknown() -> None:
    index = build_team_name_index(_FPL_TEAMS_2025_26, season="2025-26")
    # Direct match.
    assert index.resolve("Arsenal") == 1
    # FBref-style long forms collapse to the FPL token regardless of either side's spelling.
    assert index.resolve("Manchester United") == 2
    assert index.resolve("Newcastle Utd") == 3
    assert index.resolve("Nottingham Forest") == 4
    assert index.resolve("Manchester City") == 5
    # Unknown club is unresolved, never guessed.
    assert index.resolve("Atlantis FC") is None


def test_team_name_index_reports_ambiguous() -> None:
    # Two clubs sharing a token -> not guessed.
    teams = [FplTeamRow("2025-26", 1, "Arsenal"), FplTeamRow("2025-26", 99, "Arsenal")]
    index = build_team_name_index(teams, season="2025-26")
    assert index.resolve("Arsenal") is None


def test_build_external_roster_resolves_and_reports_unresolved() -> None:
    actions = [
        _action("a", "X", "Arsenal"),
        _action("b", "Y", "Atlantis FC"),
    ]
    index = build_team_name_index(_FPL_TEAMS_2025_26, season="2025-26")
    entries, unresolved = build_external_roster(actions, index, season="2025-26")
    by_id = {entry.external_id: entry for entry in entries}
    assert by_id["a"].team_code == 1
    assert by_id["b"].team_code is None
    assert unresolved == ["Atlantis FC"]


def test_crosswalk_wiring_on_fixture() -> None:
    actions = read_defensive_actions_csv(FIXTURE)
    index = build_team_name_index(_FPL_TEAMS_2025_26, season="2025-26")
    external_roster, unresolved_teams = build_external_roster(actions, index, season="2025-26")
    # 2025-26 has six distinct external players (the blank-count row is dropped by the
    # reader; the 2024-25 row and Gordon's second club are filtered/deduped).
    assert len(external_roster) == 6
    assert unresolved_teams == []

    fpl_roster = [
        FplRosterEntry("2025-26", 1001, 1, "David Raya Martín"),
        FplRosterEntry("2025-26", 1002, 1, "William Saliba"),
        FplRosterEntry("2025-26", 1003, 1, "Declan Rice"),
        FplRosterEntry("2025-26", 1004, 1, "Bukayo Saka"),
        FplRosterEntry("2025-26", 1005, 2, "Joshua Zirkzee"),
        FplRosterEntry("2025-26", 1006, 3, "Anthony Gordon"),
    ]
    crosswalk = build_identity_crosswalk(fpl_roster, external_roster, season="2025-26")
    assert crosswalk.match_rate == 1.0
    assert crosswalk.matched_by_method == {"name_club": 6}


def _good_fpl_index() -> dict[tuple[int, str], tuple[Position, int]]:
    # Recorded DC set to equal the external-rebuilt DC for each player's position. Gordon
    # appears at two clubs/dates under one code (the two-club transfer).
    return {
        (1001, "2025-08-16"): (Position.GK, 0),  # GK: not scored, value irrelevant
        (1002, "2025-08-16"): (Position.DEF, 10),  # Saliba: 2 tackles + CBI 8
        (1003, "2025-08-16"): (Position.MID, 17),  # Rice: 4 + CBI 4 + recoveries 9
        (1004, "2025-08-16"): (Position.FWD, 4),  # Saka: 1 + CBI 0 + recoveries 3
        (1005, "2025-08-16"): (Position.FWD, 1),  # Zirkzee: 0 + CBI 0 + recoveries 1
        (1006, "2025-08-17"): (Position.MID, 8),  # Gordon @ Newcastle: 1 + CBI 3 + 4
        (1006, "2026-01-10"): (Position.MID, 13),  # Gordon @ Forest: 2 + CBI 6 + 5
    }


_CODE_BY_EXTERNAL = {
    "fb-raya": 1001,
    "fb-saliba": 1002,
    "fb-rice": 1003,
    "fb-saka": 1004,
    "fb-zirkzee": 1005,
    "fb-gordon": 1006,
}


def test_overlap_gate_passes_on_good_alignment() -> None:
    actions = read_defensive_actions_csv(FIXTURE)
    observations = align_overlap_observations(
        actions, _good_fpl_index(), _CODE_BY_EXTERNAL, season="2025-26"
    )
    report = check_dc_reconstruction(observations)
    # GK is counted but never scored; the six outfield rows all rebuild exactly.
    assert report.total_rows == 7
    assert report.scoring_rows == 6
    assert report.reconciles
    gate = evaluate_overlap_gate(report, match_rate=1.0)
    assert gate.passed


def test_overlap_gate_fails_on_dc_mismatch() -> None:
    actions = read_defensive_actions_csv(FIXTURE)
    index = _good_fpl_index()
    index[(1002, "2025-08-16")] = (Position.DEF, 99)  # Saliba rebuilds 10, recorded says 99
    observations = align_overlap_observations(actions, index, _CODE_BY_EXTERNAL, season="2025-26")
    report = check_dc_reconstruction(observations)
    assert not report.reconciles
    assert report.agreement_rate < 0.995  # 5/6
    gate = evaluate_overlap_gate(report, match_rate=1.0)
    assert not gate.passed


def test_overlap_gate_fails_on_low_match_rate() -> None:
    actions = read_defensive_actions_csv(FIXTURE)
    observations = align_overlap_observations(
        actions, _good_fpl_index(), _CODE_BY_EXTERNAL, season="2025-26"
    )
    report = check_dc_reconstruction(observations)
    # Perfect agreement but the identity match rate is below the bar -> still fails.
    assert report.reconciles
    gate = evaluate_overlap_gate(report, match_rate=0.5)
    assert not gate.passed


def test_align_skips_unresolved_and_unaligned() -> None:
    actions = [
        _action(
            "fb-saliba",
            "William Saliba",
            "Arsenal",
            tackles=2,
            interceptions=3,
            blocks=1,
            clearances=4,
        ),
        _action("fb-ghost", "Ghost Player", "Arsenal"),  # not in code_by_external
    ]
    # (fb-saliba, 2025-08-16) is absent from the index -> unaligned, skipped.
    observations = align_overlap_observations(actions, {}, _CODE_BY_EXTERNAL, season="2025-26")
    assert observations == []
