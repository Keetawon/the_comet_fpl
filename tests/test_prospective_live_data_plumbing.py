"""Offline tests for the two live prospective data-plumbing repairs (P0).

Defect 1: a prior season in which a player was not available to his club (loaned
abroad / out of the side all season, 38 zero-minute registry rows) must not read
as "benched all season". The prior-season appearance prior is the boundary-robust
nailed-ness signal; fed a zero rate with n = 38 it halves a returning starter's
P(play) through the in-season calendar blend (measured: N.Jackson, 2026-27).

Defect 2: the incumbent Stage A fit (`trailing_goals_attack_defence`) trains on
`mart_fact_team_match`, which the archive ends at 2025-26 -- so during 2026-27 the
ratings never see a current-season match. Finalized current-season team matches
(official home/away scores from the versioned live fixtures, the team-outcome
ledger's own source) must enter the training frame under knowledge-time discipline.

Both suites are offline and deterministic. No model constant, frozen evaluation,
or gate changes here: these tests pin data semantics the code already intended.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
import pytest

from fpl.config import load_phase2_evaluation
from fpl.ingest.live_snapshot import capture_payload, write_capture
from fpl.jobs.prospective_points_v1 import (
    prior_season_appearance_rate,
    prospective_team_scored,
    season_boundary_minutes,
    trailing5_minute_bins,
)
from fpl.storage.db import initialise
from fpl.validate.minutes_baselines import MinuteBins

AS_OF_NOVEMBER = datetime(2026, 11, 25, tzinfo=UTC)
CAPTURE_ONE = "cap-live-2026-11-20"
CAPTURE_ONE_AT = datetime(2026, 11, 20, 10, tzinfo=UTC)
_PRIOR_BASE = datetime(2025, 8, 9, tzinfo=UTC)

# team_id -> team_code, shared by the bootstrap payload and the seeded archive dimension.
TEAM_CODE = {1: 101, 2: 102}

JACKSON = 517052  # the measured case: AVL FWD, loaned at Bayern through 2025-26
CONTROL = 4242  # a same-club veteran who genuinely played the prior season
BOUNDARY_LOW = 4321  # 4 prior-season appearances: an unavailability season
BOUNDARY_HIGH = 4322  # 5 prior-season appearances: the first rotation prior kept


def _teams(*ids: int) -> list[dict[str, Any]]:
    return [{"id": i, "code": TEAM_CODE[i], "name": f"T{i}", "short_name": f"T{i}"} for i in ids]


def _element(pid: int, code: int, element_type: int, team: int) -> dict[str, Any]:
    return {
        "id": pid,
        "code": code,
        "web_name": f"P{code}",
        "element_type": element_type,
        "team": team,
        "now_cost": 75,
        "selected_by_percent": "12.3",
        "status": "a",
        "chance_of_playing_next_round": None,
    }


def _events(last: int = 11) -> list[dict[str, Any]]:
    return [
        {
            "id": gw,
            "name": f"Gameweek {gw}",
            "deadline_time": (
                datetime(2026, 8, 21, 17, 30, tzinfo=UTC) + timedelta(days=7 * (gw - 1))
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "finished": gw < 11,
        }
        for gw in range(1, last + 1)
    ]


def _live_fixture(
    fid: int,
    team_h: int,
    team_a: int,
    *,
    event: int,
    kickoff: datetime,
    finished: bool,
    h_score: int | None = None,
    a_score: int | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": fid,
        "code": 9000 + fid,
        "event": event,
        "finished": finished,
        "finished_provisional": finished,
        "kickoff_time": kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "team_h": team_h,
        "team_a": team_a,
        "team_h_difficulty": 3,
        "team_a_difficulty": 3,
        "pulse_id": 7000 + fid,
    }
    if h_score is not None and a_score is not None:
        row["team_h_score"] = h_score
        row["team_a_score"] = a_score
    return row


def _history_row(
    element: int,
    fixture: int,
    *,
    round_gw: int,
    kickoff: datetime,
    minutes: int,
    was_home: bool,
    opponent: int = 2,
) -> dict[str, Any]:
    return {
        "element": element,
        "fixture": fixture,
        "opponent_team": opponent,
        "total_points": 5,
        "was_home": was_home,
        "kickoff_time": kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "round": round_gw,
        "minutes": minutes,
        "starts": 1 if minutes >= 60 else 0,
        "goals_scored": 1 if minutes >= 60 else 0,
        "assists": 0,
        "clean_sheets": 0,
        "goals_conceded": 0,
        "bonus": 1,
        "bps": 24,
        "threat": 55.0,
        "creativity": 12.3,
        "influence": 44.2,
        "value": 75,
        "selected": 1000,
        "transfers_in": 5,
        "transfers_out": 1,
    }


def _write_live_capture(
    con,
    *,
    capture_id: str,
    captured_at: datetime,
    fixtures: list[dict[str, Any]],
    summaries: dict[int, list[dict[str, Any]]],
) -> None:
    payloads: list[Any] = [
        capture_payload(
            "bootstrap-static",
            {
                "events": _events(),
                "teams": _teams(*TEAM_CODE),
                "elements": [
                    _element(11, JACKSON, 3, 1),
                    _element(12, CONTROL, 3, 1),
                ],
            },
        ),
        capture_payload("fixtures", fixtures),
    ]
    for element, history in summaries.items():
        payloads.append(
            capture_payload(
                "element-summary", {"fixtures": [], "history": history}, parameter=str(element)
            )
        )
    write_capture(
        con,
        payloads,  # type: ignore[arg-type]
        season="2026-27",
        gw=10,
        mode="player-history",
        captured_at=captured_at,
        capture_id=capture_id,
    )


def _seed_prior_season(
    con,
    *,
    jackson_minutes: int,
    control_minutes: int,
) -> None:
    """38 archived 2025-26 registry rows per player at club 101 (weekly, Aug-May).

    Jackson: every row zero minutes (loaned abroad; the FPL registry keeps the DNP row).
    Control: a genuine ever-present. Team-match rows accompany them so Stage A has history.
    """
    con.executemany(
        "INSERT INTO mart_dim_team (season, team_id, team_code, team_name, short_name, pulse_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("2025-26", tid, code, f"T{tid}", f"T{tid}", 1000 + tid)
            for tid, code in TEAM_CODE.items()
        ],
    )
    player_rows: list[tuple[object, ...]] = []
    team_rows: list[tuple[object, ...]] = []
    for gw in range(1, 39):
        kickoff = _PRIOR_BASE + timedelta(days=7 * (gw - 1))
        fixture = 900 + gw
        was_home = gw % 2 == 0
        for code, minutes in (
            (JACKSON, jackson_minutes),
            (CONTROL, control_minutes),
            # The measured boundary: 4 prior-season appearances is an unavailability
            # season (Trafford/Pinnock 2025-26); 5 is the first rotation prior kept.
            (BOUNDARY_LOW, 90 if gw <= 4 else 0),
            (BOUNDARY_HIGH, 90 if gw <= 5 else 0),
        ):
            player_rows.append(
                (
                    "2025-26",
                    gw,
                    fixture,
                    kickoff,
                    code,
                    "FWD",
                    1,
                    2,
                    was_home,
                    minutes,
                    1 if minutes >= 60 else 0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    18,
                    0,
                    20.0 + gw,
                    15.0 + gw,
                    10.0 + gw,
                    0.10,
                )
            )
        team_rows.append(
            (
                "2025-26",
                gw,
                fixture,
                kickoff,
                1,
                2,
                was_home,
                1,
                1,
                1.2,
                1.1,
                3,
            )
        )
        team_rows.append(
            (
                "2025-26",
                gw,
                fixture,
                kickoff,
                2,
                1,
                not was_home,
                1,
                1,
                1.1,
                1.2,
                3,
            )
        )
    con.executemany(
        """
        INSERT INTO mart_fact_player_fixture
            (season, gw, fixture, kickoff_time, code, position, team_id, opponent_team_id,
             was_home, minutes, goals_scored, assists, clean_sheets, goals_conceded, saves,
             penalties_saved, bps, bonus, influence, creativity, threat, expected_assists)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        player_rows,
    )
    con.executemany(
        """
        INSERT INTO mart_fact_team_match
            (season, gw, fixture, kickoff_time, team_id, opponent_team_id, was_home,
             goals_for, goals_against, team_xg, team_xgc, fdr)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        team_rows,
    )


def _current_season_fixtures() -> list[dict[str, Any]]:
    """GW6-10 finalized (Jackson 85-90 minutes in each) plus the GW11 target."""
    fixtures: list[dict[str, Any]] = []
    for gw in range(6, 11):
        kickoff = datetime(2026, 9, 26, tzinfo=UTC) + timedelta(days=7 * (gw - 6))
        fixtures.append(
            _live_fixture(
                600 + gw,
                1,
                2,
                event=gw,
                kickoff=kickoff,
                finished=True,
                h_score=2,
                a_score=1,
            )
        )
    fixtures.append(
        _live_fixture(
            611,
            1,
            2,
            event=11,
            kickoff=datetime(2026, 11, 28, tzinfo=UTC),
            finished=False,
        )
    )
    return fixtures


def _current_season_summaries() -> dict[int, list[dict[str, Any]]]:
    history: list[dict[str, Any]] = []
    for index, gw in enumerate(range(6, 11)):
        kickoff = datetime(2026, 9, 26, tzinfo=UTC) + timedelta(days=7 * (gw - 6))
        history.append(
            _history_row(
                11,
                600 + gw,
                round_gw=gw,
                kickoff=kickoff,
                minutes=(85, 90, 88, 90, 86)[index],
                was_home=True,
            )
        )
    return {11: history}


def _jackson_db() -> Any:
    con = initialise(":memory:")
    _seed_prior_season(con, jackson_minutes=0, control_minutes=90)
    _write_live_capture(
        con,
        capture_id=CAPTURE_ONE,
        captured_at=CAPTURE_ONE_AT,
        fixtures=_current_season_fixtures(),
        summaries=_current_season_summaries(),
    )
    return con


def _play_probability(dist: tuple[float, float, float, float]) -> float:
    return 1.0 - dist[0]


# --------------------------------------------------------------------------------------
# Defect 1a: the Jackson pattern (failing first)
# --------------------------------------------------------------------------------------


def test_zero_appearance_prior_season_carries_no_appearance_prior() -> None:
    """38 prior-season rows, zero minutes: the season is 'not available to the club'.

    The prior-season rate map must not carry a (0.0, 38) entry for such a player: a
    zero rate here is the signature of a loan/out-all-season absence, not of a benching
    the current trailing window would confirm. The genuine ever-present keeps his entry,
    and the measured k=5 boundary holds: a 4-appearance season (Trafford/Pinnock 2025-26)
    is unavailability, a 5-appearance season is the first rotation prior kept.
    """
    con = _jackson_db()
    try:
        clubs = {JACKSON: 101, CONTROL: 101, BOUNDARY_LOW: 101, BOUNDARY_HIGH: 101}
        prior = prior_season_appearance_rate(con, AS_OF_NOVEMBER, current_club=clubs)
        assert JACKSON not in prior
        assert BOUNDARY_LOW not in prior
        assert prior[CONTROL][0] == 1.0
        assert prior[CONTROL][1] >= 10
        rate, n = prior[BOUNDARY_HIGH]
        assert rate == pytest.approx(5.0 / 38.0)
        assert n == 38
    finally:
        con.close()


def test_returning_starter_keeps_trailing5_play_probability_in_november() -> None:
    """Five 85-90-minute current-club rows + a November target: P(play) stays at trailing-5.

    This is the exact measured Jackson pattern. Under the defect the (0.0, 38) prior
    met the October/November calendar weight 0.5 and pulled P(play) to ~0.45, roughly
    halving xP. With no appearance prior the blend is a no-op and the equal-weighted
    shrunk trailing-5 estimate stands on its own.
    """
    con = _jackson_db()
    try:
        bins = MinuteBins.from_config(load_phase2_evaluation())
        clubs = {JACKSON: 101, CONTROL: 101}
        prior = prior_season_appearance_rate(con, AS_OF_NOVEMBER, current_club=clubs)
        recent = trailing5_minute_bins(con, AS_OF_NOVEMBER, bins, current_club=clubs)[JACKSON]
        assert recent[1] == 5  # the window is the five current-season rows, not May 2026
        rate, n = prior.get(JACKSON, (None, 0))
        blended = season_boundary_minutes(
            recent[0],
            prior_rate=rate,
            prior_n=n,
            target_month=11,
        )
        assert _play_probability(blended) == pytest.approx(_play_probability(recent[0]))
        assert _play_probability(blended) > 0.75
    finally:
        con.close()


def test_frozen_unfiltered_prior_path_keeps_zero_rate_semantics() -> None:
    """The Phase 4 EV backtest adapter path (no ``current_club``) is bit-identical.

    Its immutable 2026-08-07 run read the raw most-recent-season rate with no
    availability rule; the repair is scoped to the prospective path only.
    """
    con = _jackson_db()
    try:
        prior = prior_season_appearance_rate(con, AS_OF_NOVEMBER)
        assert prior[JACKSON] == (0.0, 38)
        assert prior[CONTROL] == (1.0, 38)
        assert prior[BOUNDARY_LOW][0] == pytest.approx(4.0 / 38.0)
    finally:
        con.close()


# --------------------------------------------------------------------------------------
# Defect 2a: the incumbent must see finalized current-season matches (failing first)
# --------------------------------------------------------------------------------------


def _stage_a_db(*, second_final_match: bool) -> Any:
    """Archive 2025-26 baseline plus live 2026-27 GW1 (and optionally GW2) finals."""
    con = initialise(":memory:")
    _seed_prior_season(con, jackson_minutes=0, control_minutes=90)
    fixtures = [
        _live_fixture(
            601,
            1,
            2,
            event=1,
            kickoff=datetime(2026, 8, 22, tzinfo=UTC),
            finished=True,
            h_score=5,
            a_score=0,
        ),
        _live_fixture(
            611,
            1,
            2,
            event=3,
            kickoff=datetime(2026, 11, 28, tzinfo=UTC),
            finished=False,
        ),
    ]
    summaries = {
        11: [
            _history_row(
                11,
                601,
                round_gw=1,
                kickoff=datetime(2026, 8, 22, tzinfo=UTC),
                minutes=90,
                was_home=True,
            )
        ]
    }
    _write_live_capture(
        con,
        capture_id=CAPTURE_ONE,
        captured_at=CAPTURE_ONE_AT,
        fixtures=fixtures,
        summaries=summaries,
    )
    if second_final_match:
        # GW2: the same club concedes a heavy defeat -- a genuinely new final match that
        # must move the incumbent's fitted ratings for the GW3 target.
        _write_live_capture(
            con,
            capture_id="cap-live-2026-11-21",
            captured_at=datetime(2026, 11, 21, 10, tzinfo=UTC),
            fixtures=[
                _live_fixture(
                    602,
                    2,
                    1,
                    event=2,
                    kickoff=datetime(2026, 8, 29, tzinfo=UTC),
                    finished=True,
                    h_score=6,
                    a_score=0,
                ),
                _live_fixture(
                    601,
                    1,
                    2,
                    event=1,
                    kickoff=datetime(2026, 8, 22, tzinfo=UTC),
                    finished=True,
                    h_score=5,
                    a_score=0,
                ),
                _live_fixture(
                    611,
                    1,
                    2,
                    event=3,
                    kickoff=datetime(2026, 11, 28, tzinfo=UTC),
                    finished=False,
                ),
            ],
            summaries={
                11: [
                    _history_row(
                        11,
                        602,
                        round_gw=2,
                        kickoff=datetime(2026, 8, 29, tzinfo=UTC),
                        minutes=90,
                        was_home=False,
                        opponent=2,
                    )
                ]
            },
        )
    return con


def _gw3_schedule() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "season": ["2026-27"],
            "gw": [3],
            "fixture": [611],
            "team_id": [1],
            "opponent_team_id": [2],
            "was_home": [True],
        }
    )


def _lambda_for_team(dist: tuple[float, ...]) -> float:
    return sum(i * mass for i, mass in enumerate(dist))


def test_incumbent_ratings_change_after_a_new_final_match() -> None:
    """With finalized current-season fixtures loaded, a new final match must move the fit.

    Under the defect both fits read only `mart_fact_team_match` (archive, ends 2025-26),
    so the GW3 lambda is identical before and after GW1/GW2 results -- the exact
    "identical to 6 decimals across 60 played matches" evidence from the published
    vintages.
    """
    before = _stage_a_db(second_final_match=False)
    after = _stage_a_db(second_final_match=True)
    try:
        scored_before, _ = prospective_team_scored(
            before,
            season="2026-27",
            as_of=AS_OF_NOVEMBER,
            team_map=dict(TEAM_CODE),
            schedule=_gw3_schedule(),
        )
        scored_after, _ = prospective_team_scored(
            after,
            season="2026-27",
            as_of=AS_OF_NOVEMBER,
            team_map=dict(TEAM_CODE),
            schedule=_gw3_schedule(),
        )
        lambda_before = _lambda_for_team(scored_before[(611, 101)])
        lambda_after = _lambda_for_team(scored_after[(611, 101)])
        assert lambda_after != pytest.approx(lambda_before, abs=1e-9)
    finally:
        before.close()
        after.close()


def test_live_team_match_rows_respect_knowledge_time_and_finality() -> None:
    """Frame-level contract: latest version per fixture at ``known_at <= as_of`` only,
    finished with both official scores only, NULL xG, and no duplicate against the archive."""
    from fpl.jobs.prospective_points_v1 import live_finalized_team_match_rows

    con = _stage_a_db(second_final_match=True)
    try:
        frame = live_finalized_team_match_rows(con, AS_OF_NOVEMBER)
        sides = {
            (row["season"], row["fixture"], row["team_code"]): row
            for row in frame.iter_rows(named=True)
        }
        # Two finalized fixtures -> four reciprocal team sides.
        assert len(sides) == 4
        for row in sides.values():
            assert row["team_xg"] is None and row["team_xgc"] is None  # never zero-filled
            assert row["goals_for"] is not None and row["goals_against"] is not None
            assert row["opponent_team_code"] is not None
        home = sides[("2026-27", 601, 101)]
        away = sides[("2026-27", 601, 102)]
        assert (home["goals_for"], home["goals_against"], home["was_home"]) == (5, 0, True)
        assert (away["goals_for"], away["goals_against"], away["was_home"]) == (0, 5, False)
        # The unfinished GW3 target contributes nothing.
        assert not any(key[1] == 611 for key in sides)
        # A capture known only after as_of cannot resurrect or alter evidence.
        late = live_finalized_team_match_rows(con, datetime(2026, 8, 21, tzinfo=UTC))
        assert late.is_empty()
    finally:
        con.close()


def test_archive_only_training_pin_stays_available() -> None:
    """The frozen Phase 4 EV backtest adapter pins archive-only training semantics.

    ``include_live_current_season=False`` must reproduce exactly the frame the adapter's
    immutable run consumed, independent of any live capture state.
    """
    before = _stage_a_db(second_final_match=False)
    after = _stage_a_db(second_final_match=True)
    try:
        pinned_before, _ = prospective_team_scored(
            before,
            season="2026-27",
            as_of=AS_OF_NOVEMBER,
            team_map=dict(TEAM_CODE),
            schedule=_gw3_schedule(),
            include_live_current_season=False,
        )
        pinned_after, _ = prospective_team_scored(
            after,
            season="2026-27",
            as_of=AS_OF_NOVEMBER,
            team_map=dict(TEAM_CODE),
            schedule=_gw3_schedule(),
            include_live_current_season=False,
        )
        assert pinned_before[(611, 101)] == pinned_after[(611, 101)]
    finally:
        before.close()
        after.close()


# --------------------------------------------------------------------------------------
# The rostered-decay appearance mode (preregistered, ships unevaluated)
# --------------------------------------------------------------------------------------


def test_rostered_decay_weight_keeps_boundary_anchor_and_fades() -> None:
    from fpl.jobs.prospective_points_v1 import rostered_decay_weight

    # The measured n = 0 boundary anchor is preserved for every c.
    for c in (1.0, 2.0, 3.0, 5.0, 8.0):
        assert rostered_decay_weight(0, c=c) == pytest.approx(0.7)
    # Monotonically fading in rostered GWs, toward zero.
    weights = [rostered_decay_weight(n, c=3.0) for n in range(0, 21)]
    assert all(a > b for a, b in itertools.pairwise(weights))
    assert weights[-1] < 0.1
    # The pre-registered grid's c=2 at n=8 reproduces ~0.14-0.3 measured-best in-season band.
    assert 0.10 < rostered_decay_weight(8, c=2.0) < 0.30


def test_rostered_decay_minutes_blends_and_is_a_noop_without_a_prior() -> None:
    from fpl.jobs.prospective_points_v1 import rostered_decay_minutes, season_boundary_minutes

    dist = (0.55, 0.05, 0.10, 0.30)
    # No prior / too few rows: untouched, exactly like the seasonal blend's no-op paths.
    assert (
        rostered_decay_minutes(dist, prior_rate=None, prior_n=0, rostered_gws=5, decay_c=3.0)
        == dist
    )
    assert (
        rostered_decay_minutes(dist, prior_rate=0.9, prior_n=3, rostered_gws=5, decay_c=3.0) == dist
    )
    # With a prior and n = 0 the arithmetic equals the seasonal blend at an August target
    # (both weights are 0.7): the boundary behaviour cannot change under the new mode.
    n_zero = rostered_decay_minutes(dist, prior_rate=0.92, prior_n=38, rostered_gws=0, decay_c=3.0)
    august = season_boundary_minutes(dist, prior_rate=0.92, prior_n=38, target_month=8)
    assert n_zero == august
    # In-season the weight is strictly smaller than the stale calendar 0.5: the benched-prior
    # drag of the Jackson defect shrinks monotonically with rostered evidence for every grid c.
    calendar = season_boundary_minutes(dist, prior_rate=0.0, prior_n=38, target_month=11)
    for c in (1.0, 2.0, 3.0, 5.0, 8.0):
        in_season = rostered_decay_minutes(
            dist, prior_rate=0.0, prior_n=38, rostered_gws=4, decay_c=c
        )
        assert (1.0 - in_season[0]) > (1.0 - calendar[0])
    # The when-playing shape is preserved.
    blended = rostered_decay_minutes(dist, prior_rate=0.8, prior_n=38, rostered_gws=3, decay_c=2.0)
    assert abs(sum(blended) - 1.0) < 1e-12
    assert abs(blended[3] / blended[2] - dist[3] / dist[2]) < 1e-9


def test_rostered_decay_mode_fails_closed_until_the_evaluation_selects_c() -> None:
    from fpl.jobs.prospective_points_v1 import ROSTERED_DECAY_C, predict_prospective_points

    if ROSTERED_DECAY_C is not None:  # already evaluated: the mode must simply run
        return
    con = _jackson_db()
    try:
        with pytest.raises(ValueError, match="ROSTERED_DECAY_C"):
            predict_prospective_points(
                con,
                as_of=AS_OF_NOVEMBER,
                season="2026-27",
                gw_from=11,
                gw_to=11,
                appearance="rostered_decay",
                db_path=None,
                repo=None,
            )
    finally:
        con.close()
