"""Deterministic OFFLINE tests for the Stage B (player minutes) walk-forward harness.

No network, no built archive. Every database is a tiny in-memory DuckDB built by ``_build_db``
with only the columns the harness reads. These tests pin the contract
(``config/phase2_evaluation.yaml`` 1.0) as the harness honours it: observed (non-contiguous)
gameweek iteration, cross-season warmup, first-kickoff UTC cutoffs, the strict leakage assertion,
the exact nine-column target proxy / label split, zero-minute retention, the same population
scored by all four refit-per-fold baselines at 100% coverage, double-gameweek grain, team-id reuse
and transfer classification, history cohorts/cold starts, all six slice dimensions, the
season-filter-restricts-folds-only rule, determinism, and every fail-closed path (missing/duplicate
team mapping, duplicate grain, empty archive).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import duckdb
import pytest

from fpl.config import load_phase2_evaluation
from fpl.models.minutes_v1 import ShrunkTrailing5PlayerMinutesV1
from fpl.storage.db import connect
from fpl.types import Position
from fpl.validate.minutes_baselines import MinuteBins, TargetRow
from fpl.validate.minutes_harness import (
    COHORT_NO_POSITIVE,
    COHORT_NO_PRIOR,
    COHORT_PRIOR_POSITIVE,
    TRANSFER_CHANGED,
    TRANSFER_NO_PRIOR,
    TRANSFER_SAME,
    MinutesFold,
    assert_no_minutes_leakage,
    generate_minutes_folds,
    run_minutes_fold,
    run_minutes_harness,
    team_code_map,
)

CONFIG = load_phase2_evaluation()
MIN_WARMUP = CONFIG.training.minimum_observed_gameweeks  # pinned to 8


# --------------------------------------------------------------------------------------
# Synthetic database helper
# --------------------------------------------------------------------------------------


def _kick(month: int, day: int, hour: int = 12) -> datetime:
    return datetime(2024, month, day, hour, 0, tzinfo=UTC)


def _build_db(
    rows: list[dict[str, object]],
    teams: list[tuple[str, int, int]] | None = None,
) -> duckdb.DuckDBPyConnection:
    """A tiny in-memory DB with exactly the columns the harness reads.

    No primary keys: a test that needs to inject a duplicate ``(season, code, fixture)`` grain
    must be able to, so the harness's own uniqueness check is what catches it.
    """
    con = connect(":memory:")
    con.execute(
        """
        CREATE TABLE mart_fact_player_fixture (
            season           VARCHAR,
            gw               INTEGER,
            fixture          INTEGER,
            kickoff_time     TIMESTAMPTZ,
            code             INTEGER,
            position         VARCHAR,
            team_id          INTEGER,
            opponent_team_id INTEGER,
            was_home         BOOLEAN,
            minutes          INTEGER
        )
        """
    )
    con.execute(
        """
        CREATE TABLE mart_dim_team (
            season    VARCHAR,
            team_id   INTEGER,
            team_code INTEGER
        )
        """
    )
    if teams is not None:
        con.executemany(
            "INSERT INTO mart_dim_team (season, team_id, team_code) VALUES (?, ?, ?)", teams
        )
    if rows:
        con.executemany(
            """
            INSERT INTO mart_fact_player_fixture (
                season, gw, fixture, kickoff_time, code, position,
                team_id, opponent_team_id, was_home, minutes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r["season"],
                    r["gw"],
                    r["fixture"],
                    r["kickoff"],
                    r["code"],
                    r["position"],
                    r["team_id"],
                    r.get("opponent_team_id", 2),
                    r.get("was_home", True),
                    r["minutes"],
                )
                for r in rows
            ],
        )
    return con


def _row(
    *,
    season: str,
    gw: int,
    fixture: int,
    kickoff: datetime,
    code: int,
    position: Literal["GK", "DEF", "MID", "FWD"] = "DEF",
    team_id: int = 1,
    minutes: int | None,
    opponent_team_id: int = 2,
    was_home: bool = True,
) -> dict[str, object]:
    return {
        "season": season,
        "gw": gw,
        "fixture": fixture,
        "kickoff": kickoff,
        "code": code,
        "position": position,
        "team_id": team_id,
        "opponent_team_id": opponent_team_id,
        "was_home": was_home,
        "minutes": minutes,
    }


def _bins() -> MinuteBins:
    return MinuteBins.from_config(CONFIG)


# A canonical two-season, warmup-clearing dataset used by several tests. team_id 1 -> club 11 in
# 2023-24 and club 21 in 2024-25 (the team-id reuse failure mode).
_TEAM_MAP: list[tuple[str, int, int]] = [
    ("2023-24", 1, 11),
    ("2023-24", 2, 12),
    ("2024-25", 1, 21),
    ("2024-25", 2, 22),
]


def _two_season_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    # 2023-24: GWs 1..5, one DEF + one MID per gameweek, all club 11/12.
    for gw in range(1, 6):
        day = gw
        rows.append(
            _row(season="2023-24", gw=gw, fixture=gw, kickoff=_kick(8, day), code=101, minutes=90)
        )
        rows.append(
            _row(
                season="2023-24",
                gw=gw,
                fixture=gw,
                kickoff=_kick(8, day),
                code=102,
                position="MID",
                minutes=60,
            )
        )
    # 2024-25: GWs 1..5; player 101 continues at club 21 (team_id reused, same player).
    for gw in range(1, 6):
        day = gw
        rows.append(
            _row(season="2024-25", gw=gw, fixture=gw, kickoff=_kick(9, day), code=101, minutes=90)
        )
        rows.append(
            _row(
                season="2024-25",
                gw=gw,
                fixture=gw,
                kickoff=_kick(9, day),
                code=102,
                position="MID",
                minutes=0,
            )
        )
    return rows


# --------------------------------------------------------------------------------------
# Observed (non-contiguous) gameweek iteration
# --------------------------------------------------------------------------------------


def test_folds_iterate_observed_gameweeks_not_range_one_to_39() -> None:
    # GW9 is absent (the 2022-23 GW7 analogue). A `range(1, 39)` assumption would fabricate GW9
    # and shift the split; observed iteration must skip it. GWs 1..8 clear the warmup, so the
    # folds are exactly observed[8:] = {10, 11}, and 9 never appears.
    rows = [
        _row(season="2023-24", gw=gw, fixture=gw, kickoff=_kick(8, gw), code=1, minutes=90)
        for gw in (1, 2, 3, 4, 5, 6, 7, 8, 10, 11)
    ]
    con = _build_db(rows, _TEAM_MAP)
    folds = generate_minutes_folds(con, CONFIG)
    gws = [f.gw for f in folds if f.season == "2023-24"]
    assert gws == [10, 11]
    assert 9 not in gws


def test_null_minute_gameweek_is_not_observed() -> None:
    # A GW whose only row has NULL minutes is not an observed gameweek.
    con = _build_db(
        [
            _row(season="2023-24", gw=1, fixture=1, kickoff=_kick(8, 1), code=1, minutes=90),
            _row(season="2023-24", gw=2, fixture=2, kickoff=_kick(8, 2), code=1, minutes=90),
        ],
        _TEAM_MAP,
    )
    con.execute(
        "INSERT INTO mart_fact_player_fixture VALUES "
        "('2023-24', 9, 9, '2024-08-09 12:00:00+00', 1, 'DEF', 1, 2, TRUE, NULL)"
    )
    folds = generate_minutes_folds(con, CONFIG)
    assert 9 not in {f.gw for f in folds}


# --------------------------------------------------------------------------------------
# Cross-season warmup: counted across seasons, only the earliest season loses gameweeks
# --------------------------------------------------------------------------------------


def test_warmup_is_counted_across_seasons() -> None:
    con = _build_db(_two_season_rows(), _TEAM_MAP)
    folds = generate_minutes_folds(con, CONFIG)
    # 2023-24 has 5 observed GWs; cumulative positions 0..4 are all < 8 -> no 2023-24 folds.
    assert {f.season for f in folds if f.season == "2023-24"} == set()
    # 2024-25: gameweeks_before = 5. GW1..3 (cumulative 5,6,7) are < 8 -> skipped; GW4 (8), GW5 (9).
    by_gw = {f.gw for f in folds if f.season == "2024-25"}
    assert by_gw == {4, 5}
    first = next(f for f in folds if f.season == "2024-25" and f.gw == 4)
    assert first.prior_observed_gameweeks == MIN_WARMUP


def test_fold_indices_are_one_based_and_contiguous() -> None:
    con = _build_db(_two_season_rows(), _TEAM_MAP)
    folds = generate_minutes_folds(con, CONFIG)
    assert [f.index for f in folds] == list(range(1, len(folds) + 1))


def test_181_formula_holds_on_observed_minus_warmup_shape() -> None:
    # The archive shape (189 observed - 8 warmup = 181) reproduced structurally on a small scale:
    # 10 observed GWs, 8 warmup -> exactly 2 folds. No archive is run here.
    rows = [
        _row(season="2023-24", gw=gw, fixture=gw, kickoff=_kick(8, gw), code=1, minutes=90)
        for gw in range(1, 11)
    ]
    con = _build_db(rows, _TEAM_MAP)
    folds = generate_minutes_folds(con, CONFIG)
    assert len(folds) == 10 - MIN_WARMUP


# --------------------------------------------------------------------------------------
# First-kickoff cutoffs, timezone-aware UTC, leakage assertion
# --------------------------------------------------------------------------------------


def test_as_of_is_the_first_kickoff_and_is_aware_utc() -> None:
    con = _build_db(_two_season_rows(), _TEAM_MAP)
    folds = generate_minutes_folds(con, CONFIG)
    fold = next(f for f in folds if f.season == "2024-25" and f.gw == 4)
    # GW4 of 2024-25 kicks off at 2024-09-04 12:00 UTC (the only kickoff that day).
    assert fold.as_of == datetime(2024, 9, 4, 12, 0, tzinfo=UTC)
    assert fold.as_of.tzinfo is not None
    assert fold.as_of.utcoffset() == UTC.utcoffset(None)


def test_as_of_is_the_minimum_even_when_fixtures_span_times() -> None:
    # GW10 has two fixtures at 12:00 and 18:00: as_of must be the earlier (12:00), so the strict
    # `<` still excludes the whole gameweek including the earliest kickoff. GWs 1..8 clear warmup.
    rows = [
        _row(season="2023-24", gw=gw, fixture=gw, kickoff=_kick(8, gw), code=1, minutes=90)
        for gw in range(1, 9)
    ]
    rows.append(
        _row(season="2023-24", gw=10, fixture=10, kickoff=_kick(8, 10, 12), code=1, minutes=90)
    )
    rows.append(
        _row(season="2023-24", gw=10, fixture=11, kickoff=_kick(8, 10, 18), code=2, minutes=90)
    )
    con = _build_db(rows, _TEAM_MAP)
    folds = [f for f in generate_minutes_folds(con, CONFIG) if f.season == "2023-24" and f.gw == 10]
    assert folds and folds[0].as_of == datetime(2024, 8, 10, 12, 0, tzinfo=UTC)


def test_null_outcome_row_cannot_move_cutoff_past_first_kickoff() -> None:
    # Eligibility is minutes-not-null, but the deadline proxy is still the gameweek's actual
    # first kickoff. A NULL label at 12:00 must not move as_of to the eligible 18:00 fixture.
    rows = [
        _row(season="2023-24", gw=gw, fixture=gw, kickoff=_kick(8, gw), code=1, minutes=90)
        for gw in range(1, 9)
    ]
    rows.append(
        _row(season="2023-24", gw=10, fixture=10, kickoff=_kick(8, 10, 12), code=1, minutes=None)
    )
    rows.append(
        _row(season="2023-24", gw=10, fixture=11, kickoff=_kick(8, 10, 18), code=2, minutes=90)
    )
    con = _build_db(rows, _TEAM_MAP)
    fold = next(
        f for f in generate_minutes_folds(con, CONFIG) if f.season == "2023-24" and f.gw == 10
    )
    assert fold.as_of == datetime(2024, 8, 10, 12, 0, tzinfo=UTC)
    assert fold.target_rows == 1


def test_leakage_assertion_holds_on_a_correct_fold() -> None:
    con = _build_db(_two_season_rows(), _TEAM_MAP)
    fold = next(
        f for f in generate_minutes_folds(con, CONFIG) if f.season == "2024-25" and f.gw == 4
    )
    assert_no_minutes_leakage(con, fold)  # no row in the GW kicks off before its own minimum


def test_leakage_assertion_fires_when_cutoff_moves_forward() -> None:
    con = _build_db(_two_season_rows(), _TEAM_MAP)
    fold = next(
        f for f in generate_minutes_folds(con, CONFIG) if f.season == "2024-25" and f.gw == 5
    )
    # Push as_of past every kickoff in GW5 -> those rows become "visible to training".
    leaky = MinutesFold(
        index=fold.index,
        season=fold.season,
        gw=fold.gw,
        as_of=datetime(2030, 1, 1, tzinfo=UTC),
        prior_observed_gameweeks=fold.prior_observed_gameweeks,
        target_rows=fold.target_rows,
    )
    with pytest.raises(AssertionError, match="visible to training"):
        assert_no_minutes_leakage(con, leaky)


# --------------------------------------------------------------------------------------
# Exact nine-column target proxy / label split
# --------------------------------------------------------------------------------------


def test_targets_are_target_rows_without_minutes_and_labels_are_separate() -> None:
    con = _build_db(_two_season_rows(), _TEAM_MAP)
    fold = next(
        f for f in generate_minutes_folds(con, CONFIG) if f.season == "2024-25" and f.gw == 4
    )
    result = run_minutes_fold(con, fold, bins=_bins(), config=CONFIG)
    assert result is not None
    assert all(isinstance(t, TargetRow) for t in result.targets)
    # The label never rides on a TargetRow (its slots are exactly the nine proxy columns).
    for target in result.targets:
        assert not hasattr(target, "minutes")
    # Labels are carried alongside, aligned, and bin-indexed.
    assert len(result.observed_bins) == len(result.targets)
    assert all(0 <= b <= 3 for b in result.observed_bins)


# --------------------------------------------------------------------------------------
# Zero-minute retention in training
# --------------------------------------------------------------------------------------


def test_zero_minute_rows_are_kept_in_training() -> None:
    # 2024-25 GW5: player 102 (MID) has only zero-minute history. His position-frequency
    # prediction must reflect the zeros, proving they were not filtered out of training.
    con = _build_db(_two_season_rows(), _TEAM_MAP)
    fold = next(
        f for f in generate_minutes_folds(con, CONFIG) if f.season == "2024-25" and f.gw == 5
    )
    result = run_minutes_fold(con, fold, bins=_bins(), config=CONFIG)
    assert result is not None
    mid_index = next(i for i, p in enumerate(result.positions) if p == Position.MID)
    pos_name = "position_minutes_frequency"
    dist = result.by_baseline[pos_name][mid_index]
    # Prior MID minutes through 2024-25 GW4: five 60s (2023-24 GW1-5) and four 0s (2024-25 GW1-4).
    # The zeros are retained -> the zero-bin mass is exactly 4/9, proving they were not filtered.
    assert dist == pytest.approx((4 / 9, 0.0, 5 / 9, 0.0))


# --------------------------------------------------------------------------------------
# Same population, all four baselines, refit per fold, 100% coverage
# --------------------------------------------------------------------------------------


def test_all_four_baselines_predict_the_same_population_at_full_coverage() -> None:
    con = _build_db(_two_season_rows(), _TEAM_MAP)
    fold = next(
        f for f in generate_minutes_folds(con, CONFIG) if f.season == "2024-25" and f.gw == 4
    )
    result = run_minutes_fold(con, fold, bins=_bins(), config=CONFIG)
    assert result is not None
    assert set(result.by_baseline) == set(CONFIG.baselines.stage_b)
    counts = {len(dist) for dist in result.by_baseline.values()}
    assert counts == {len(result.targets)} == {fold.target_rows}


def test_baselines_are_refit_inside_each_fold() -> None:
    # Identical target fixture list, two different training windows -> different predictions.
    # GW4 and GW5 of 2024-25 share no training window: GW5 sees one more 0-minute MID row, so the
    # MID position-frequency distribution must differ between the two folds. (DEF is all-90 and so
    # is deliberately not the comparison -- it would not move.)
    con = _build_db(_two_season_rows(), _TEAM_MAP)
    folds = generate_minutes_folds(con, CONFIG)
    f4 = next(f for f in folds if f.season == "2024-25" and f.gw == 4)
    f5 = next(f for f in folds if f.season == "2024-25" and f.gw == 5)
    r4 = run_minutes_fold(con, f4, bins=_bins(), config=CONFIG)
    r5 = run_minutes_fold(con, f5, bins=_bins(), config=CONFIG)
    assert r4 is not None and r5 is not None
    mid4 = next(i for i, p in enumerate(r4.positions) if p == Position.MID)
    mid5 = next(i for i, p in enumerate(r5.positions) if p == Position.MID)
    assert r4.by_baseline["position_minutes_frequency"][mid4] != pytest.approx(
        r5.by_baseline["position_minutes_frequency"][mid5]
    )


def test_full_run_has_full_coverage_and_zero_leakage() -> None:
    con = _build_db(_two_season_rows(), _TEAM_MAP)
    result = run_minutes_harness(con, config=CONFIG)
    assert result.leakage_failures == 0
    expected_eligible = sum(fold.target_rows for fold in generate_minutes_folds(con, CONFIG))
    assert result.eligible_predictions == expected_eligible
    assert result.predictions == expected_eligible
    for report in result.overall.values():
        assert report.prediction_coverage == pytest.approx(1.0)
        assert report.exclusions == 0
        assert report.predictions == result.predictions


# --------------------------------------------------------------------------------------
# Double-gameweek grain: separate fixtures, both predicted
# --------------------------------------------------------------------------------------


def test_double_gameweek_fixtures_are_separate_rows() -> None:
    # Player 101 has TWO fixtures in 2024-25 GW5 (fixtures 5 and 50). Both must be predicted,
    # separately, at the (season, code, fixture) grain.
    rows = _two_season_rows()
    rows.append(_row(season="2024-25", gw=5, fixture=50, kickoff=_kick(9, 7), code=101, minutes=30))
    con = _build_db(rows, _TEAM_MAP)
    fold = next(
        f for f in generate_minutes_folds(con, CONFIG) if f.season == "2024-25" and f.gw == 5
    )
    result = run_minutes_fold(con, fold, bins=_bins(), config=CONFIG)
    assert result is not None
    p101 = [i for i, t in enumerate(result.targets) if t.code == 101]
    assert len(p101) == 2
    fixtures = {result.targets[i].fixture for i in p101}
    assert fixtures == {5, 50}


# --------------------------------------------------------------------------------------
# Team-id reuse and transfer classification
# --------------------------------------------------------------------------------------


def _transfer_dataset() -> tuple[duckdb.DuckDBPyConnection, MinutesFold]:
    # team_id 1 -> club 11 (2023-24) and club 21 (2024-25). Three 2024-25 GW5 targets:
    #   301: prior rows only in 2023-24 at club 11; target at team_id 1 (club 21) -> CHANGED.
    #   302: prior row in 2024-25 at club 21 (team_id 1); target at team_id 1 -> SAME.
    #   303: no prior rows at all -> NO_PRIOR.
    rows: list[dict[str, object]] = []
    # Enough warmup history (8 GWs) so 2024-25 GW5 is a fold.
    for gw in range(1, 6):
        rows.append(
            _row(season="2023-24", gw=gw, fixture=gw, kickoff=_kick(8, gw), code=400, minutes=90)
        )
    for gw in range(1, 5):
        rows.append(
            _row(season="2024-25", gw=gw, fixture=gw, kickoff=_kick(9, gw), code=400, minutes=90)
        )
    # 301: 2023-24 club-11 history (team_id 1).
    rows.append(_row(season="2023-24", gw=1, fixture=70, kickoff=_kick(8, 1), code=301, minutes=90))
    # 302: 2024-25 club-21 history (team_id 1).
    rows.append(_row(season="2024-25", gw=1, fixture=71, kickoff=_kick(9, 1), code=302, minutes=90))
    # Targets in 2024-25 GW5.
    rows.append(_row(season="2024-25", gw=5, fixture=5, kickoff=_kick(9, 5), code=301, minutes=90))
    rows.append(_row(season="2024-25", gw=5, fixture=5, kickoff=_kick(9, 5), code=302, minutes=90))
    rows.append(_row(season="2024-25", gw=5, fixture=5, kickoff=_kick(9, 5), code=303, minutes=0))
    con = _build_db(rows, _TEAM_MAP)
    fold = next(
        f for f in generate_minutes_folds(con, CONFIG) if f.season == "2024-25" and f.gw == 5
    )
    return con, fold


def test_transfer_status_classifies_team_id_reuse_as_a_change() -> None:
    con, fold = _transfer_dataset()
    result = run_minutes_fold(con, fold, bins=_bins(), config=CONFIG)
    assert result is not None
    by_code = {
        result.targets[i].code: result.transfer_status[i] for i in range(len(result.targets))
    }
    assert by_code[301] == TRANSFER_CHANGED  # club 11 -> club 21 via reused team_id 1
    assert by_code[302] == TRANSFER_SAME
    assert by_code[303] == TRANSFER_NO_PRIOR


def test_team_code_map_is_built_from_dim_team_only_and_resolves() -> None:
    con, _fold = _transfer_dataset()
    tcm = team_code_map(con)
    assert tcm.code("2023-24", 1) == 11
    assert tcm.code("2024-25", 1) == 21  # same team_id, different club


def test_team_code_map_rejects_a_duplicate_season_team_mapping() -> None:
    con = _build_db([], [("2024-25", 1, 21), ("2024-25", 1, 99)])
    with pytest.raises(ValueError, match="duplicate team_code mapping"):
        team_code_map(con)


# --------------------------------------------------------------------------------------
# History cohorts and cold starts
# --------------------------------------------------------------------------------------


def _cohort_dataset() -> tuple[duckdb.DuckDBPyConnection, MinutesFold]:
    rows: list[dict[str, object]] = []
    for gw in range(1, 6):
        rows.append(
            _row(season="2023-24", gw=gw, fixture=gw, kickoff=_kick(8, gw), code=400, minutes=90)
        )
    for gw in range(1, 5):
        rows.append(
            _row(season="2024-25", gw=gw, fixture=gw, kickoff=_kick(9, gw), code=400, minutes=90)
        )
    # 501: prior positive minutes. 502: prior rows but all zero. 503: no prior rows.
    rows.append(_row(season="2024-25", gw=1, fixture=80, kickoff=_kick(9, 1), code=501, minutes=90))
    rows.append(_row(season="2024-25", gw=1, fixture=81, kickoff=_kick(9, 1), code=502, minutes=0))
    rows.append(_row(season="2024-25", gw=2, fixture=82, kickoff=_kick(9, 2), code=502, minutes=0))
    for code in (501, 502, 503):
        rows.append(
            _row(season="2024-25", gw=5, fixture=5, kickoff=_kick(9, 5), code=code, minutes=90)
        )
    con = _build_db(rows, _TEAM_MAP)
    fold = next(
        f for f in generate_minutes_folds(con, CONFIG) if f.season == "2024-25" and f.gw == 5
    )
    return con, fold


def test_history_cohorts_and_cold_starts_are_derived_from_prior_history() -> None:
    con, fold = _cohort_dataset()
    result = run_minutes_fold(con, fold, bins=_bins(), config=CONFIG)
    assert result is not None
    i = {result.targets[k].code: k for k in range(len(result.targets))}
    cohort = {c: result.player_history_cohort[i[c]] for c in (501, 502, 503)}
    cold = {c: result.cold_starts[i[c]] for c in (501, 502, 503)}
    assert cohort == {501: COHORT_PRIOR_POSITIVE, 502: COHORT_NO_POSITIVE, 503: COHORT_NO_PRIOR}
    assert cold == {501: False, 502: True, 503: True}


# --------------------------------------------------------------------------------------
# All six slice dimensions materialise
# --------------------------------------------------------------------------------------


def test_all_six_reporting_dimensions_are_materialised() -> None:
    con = _build_db(_two_season_rows(), _TEAM_MAP)
    result = run_minutes_harness(con, config=CONFIG)
    # fold + season both populated; positions/venues/history cohorts present.
    assert len(result.by_fold) == result.folds_evaluated
    assert set(result.by_season) == {"2024-25"}
    assert Position.DEF in result.by_position and Position.MID in result.by_position
    assert set(result.by_home_away) >= {"home"}
    assert COHORT_PRIOR_POSITIVE in result.by_player_history_cohort
    # transfer_status dimension is exercised by the transfer dataset.
    assert set(result.by_transfer_status)  # at least one value reported


def test_each_slice_carries_counts_uncertainty_and_calibration() -> None:
    con = _build_db(_two_season_rows(), _TEAM_MAP)
    result = run_minutes_harness(con, config=CONFIG)
    for name, report in result.overall.items():
        assert report.predictions > 0
        assert report.mean_log_score_standard_error >= 0.0
        assert 0.0 <= report.pit_interval_80_coverage <= 1.0
        assert len(report.reliability_any_minutes.buckets) == 10
        assert name  # every baseline represented


def test_best_baseline_is_lowest_mean_log_score() -> None:
    con = _build_db(_two_season_rows(), _TEAM_MAP)
    result = run_minutes_harness(con, config=CONFIG)
    best = result.best_baseline()
    assert result.overall[best].mean_log_score == min(
        r.mean_log_score for r in result.overall.values()
    )


# --------------------------------------------------------------------------------------
# Season filter restricts folds only, never the prior training history
# --------------------------------------------------------------------------------------


def test_season_filter_restricts_folds_only_and_leaves_training_intact() -> None:
    # A season-restricted run must score the kept season identically to the full run, because
    # the training history behind each fold is unchanged. If the filter had shortened training,
    # the numbers would diverge.
    rows = _two_season_rows()
    # Add a third season so a filter actually drops something while 2024-25 keeps all its history.
    for gw in range(1, 6):
        rows.append(
            _row(season="2025-26", gw=gw, fixture=gw, kickoff=_kick(10, gw), code=101, minutes=90)
        )
    teams = [*_TEAM_MAP, ("2025-26", 1, 31), ("2025-26", 2, 32)]
    con_full = _build_db(rows, teams)
    con_filt = _build_db(rows, teams)
    full = run_minutes_harness(con_full, config=CONFIG)
    filt = run_minutes_harness(con_filt, config=CONFIG, seasons=["2024-25"])
    assert set(full.folds_by_season) >= {"2024-25"}
    assert set(filt.folds_by_season) == {"2024-25"}  # only the filtered season's folds
    # The kept season's slice is identical down to the PIT values: the filter restricted folds
    # only, so the training history behind each 2024-25 fold is unchanged. (The *overall*
    # tuples differ by construction -- a full run also scores 2025-26 -- so the comparison is the
    # shared 2024-25 season slice.)
    for name in CONFIG.baselines.stage_b:
        assert filt.by_season["2024-25"][name].mean_log_score == pytest.approx(
            full.by_season["2024-25"][name].mean_log_score
        )
        assert (
            filt.by_season["2024-25"][name].pit_values == full.by_season["2024-25"][name].pit_values
        )


# --------------------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------------------


def test_run_is_deterministic() -> None:
    con_a = _build_db(_two_season_rows(), _TEAM_MAP)
    con_b = _build_db(_two_season_rows(), _TEAM_MAP)
    a = run_minutes_harness(con_a, config=CONFIG)
    b = run_minutes_harness(con_b, config=CONFIG)
    for name in CONFIG.baselines.stage_b:
        assert a.overall[name].mean_log_score == b.overall[name].mean_log_score
        assert a.overall[name].pit_values == b.overall[name].pit_values
        assert a.overall[name].mean_brier_60_plus == b.overall[name].mean_brier_60_plus


# --------------------------------------------------------------------------------------
# Fail-closed paths
# --------------------------------------------------------------------------------------


def test_empty_archive_yields_no_folds() -> None:
    con = _build_db([], _TEAM_MAP)
    assert generate_minutes_folds(con, CONFIG) == []


def test_missing_team_mapping_for_a_target_fails_closed() -> None:
    # team_id 5 has no mart_dim_team mapping at all -> validate_minutes_inputs rejects it.
    rows = _two_season_rows()
    rows.append(
        _row(
            season="2024-25", gw=5, fixture=5, kickoff=_kick(9, 5), code=999, team_id=5, minutes=90
        )
    )
    con = _build_db(rows, _TEAM_MAP)
    fold = next(
        f for f in generate_minutes_folds(con, CONFIG) if f.season == "2024-25" and f.gw == 5
    )
    with pytest.raises(ValueError, match="no team_code mapping"):
        run_minutes_fold(con, fold, bins=_bins(), config=CONFIG)


def test_duplicate_player_fixture_grain_fails_closed() -> None:
    # Two rows with the same (season, code, fixture) in the predicted gameweek -> duplicate grain.
    rows = _two_season_rows()
    rows.append(_row(season="2024-25", gw=5, fixture=5, kickoff=_kick(9, 5), code=101, minutes=90))
    rows.append(
        _row(season="2024-25", gw=5, fixture=5, kickoff=_kick(9, 5, 18), code=101, minutes=0)
    )
    con = _build_db(rows, _TEAM_MAP)
    fold = next(
        f for f in generate_minutes_folds(con, CONFIG) if f.season == "2024-25" and f.gw == 5
    )
    with pytest.raises(ValueError, match="duplicate target grain"):
        run_minutes_fold(con, fold, bins=_bins(), config=CONFIG)


# --------------------------------------------------------------------------------------
# Opt-in candidate integration (development-only). Default behavior stays unchanged.
# --------------------------------------------------------------------------------------

CANDIDATE = "shrunk_trailing_5_player_minutes_v1"


class _Candidate:
    """A minimal predictor conforming to the harness MinutesCandidate protocol, wrapping V1."""

    def __init__(self, model: ShrunkTrailing5PlayerMinutesV1) -> None:
        self.name = model.name
        self._model = model

    def predict(self, target: TargetRow):  # type: ignore[no-untyped-def]
        return self._model.predict(target)

    def parameters(self):  # type: ignore[no-untyped-def]
        return self._model.parameters()


def _candidate_factory(history, as_of):  # type: ignore[no-untyped-def]
    return _Candidate(ShrunkTrailing5PlayerMinutesV1(config=CONFIG).fit(history, as_of=as_of))


def test_candidate_and_baselines_score_identical_eligible_rows() -> None:
    con = _build_db(_two_season_rows(), _TEAM_MAP)
    result = run_minutes_harness(con, config=CONFIG, candidate_factory=_candidate_factory)
    eligible = result.eligible_predictions
    assert result.predictions == eligible
    # Every model -- the four baselines AND the candidate -- scored exactly the eligible
    # population at full coverage, so identical eligible rows is structural, not aspirational.
    for name in (*CONFIG.baselines.stage_b, CANDIDATE):
        report = result.overall[name]
        assert report.predictions == eligible
        assert report.eligible_predictions == eligible
        assert report.exclusions == 0
        assert report.prediction_coverage == pytest.approx(1.0)


def test_baselines_are_behaviorally_identical_with_candidate_disabled() -> None:
    # A run with the candidate factory and a run without must score the four baselines identically:
    # candidate integration is additive and never perturbs a baseline.
    con_with = _build_db(_two_season_rows(), _TEAM_MAP)
    con_without = _build_db(_two_season_rows(), _TEAM_MAP)
    with_factory = run_minutes_harness(
        con_with, config=CONFIG, candidate_factory=_candidate_factory
    )
    without = run_minutes_harness(con_without, config=CONFIG)
    for name in CONFIG.baselines.stage_b:
        baseline_with = with_factory.overall[name]
        baseline_without = without.overall[name]
        assert baseline_with.mean_log_score == baseline_without.mean_log_score
        assert baseline_with.pit_values == baseline_without.pit_values
        assert baseline_with.mean_brier_60_plus == baseline_without.mean_brier_60_plus
        assert (
            baseline_with.mean_ranked_probability_score
            == baseline_without.mean_ranked_probability_score
        )
    # The candidate appears only when a factory is supplied; the default run is baseline-only.
    assert CANDIDATE in with_factory.overall
    assert CANDIDATE not in without.overall
    assert with_factory.parameters_by_fold
    assert without.parameters_by_fold == {}


def test_cli_supplies_no_candidate_factory(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The ordinary minutes_harness CLI is baselines-only: its call to run_minutes_harness carries no
    # candidate factory, so candidate integration cannot leak into the default command.
    import fpl.validate.minutes_harness as mh

    real_run = mh.run_minutes_harness
    captured: dict[str, object] = {}

    class _FakeCon:
        def close(self) -> None:
            pass

    def capture_run(con, *, config, seasons, candidate_factory=None):  # type: ignore[no-untyped-def]
        captured["candidate_factory"] = candidate_factory
        tiny = _build_db(_two_season_rows(), _TEAM_MAP)
        return real_run(tiny, config=config, seasons=seasons)

    monkeypatch.setattr(mh, "connect", lambda db, *, read_only=False: _FakeCon())
    monkeypatch.setattr(mh, "run_minutes_harness", capture_run)
    rc = mh.main(["--db", str(tmp_path / "unused.duckdb")])
    assert rc == 0
    assert captured["candidate_factory"] is None


def test_candidate_fold_parameters_are_recorded() -> None:
    con = _build_db(_two_season_rows(), _TEAM_MAP)
    result = run_minutes_harness(con, config=CONFIG, candidate_factory=_candidate_factory)
    assert result.parameters_by_fold
    for fold_parameters in result.parameters_by_fold.values():
        candidate_parameters = fold_parameters[CANDIDATE]
        # The structured fold record carries at least the four required provenance scalars, and the
        # full per-fold mapping is preserved for independent reconciliation.
        for key in (
            "selected_alpha",
            "used_inner_holdout",
            "inner_holdout_observed_gameweeks",
            "inner_training_observed_gameweeks",
        ):
            assert key in candidate_parameters
        assert candidate_parameters["name"] == CANDIDATE
        assert candidate_parameters["history_window"] == 5


def test_candidate_is_never_the_best_baseline() -> None:
    con = _build_db(_two_season_rows(), _TEAM_MAP)
    result = run_minutes_harness(con, config=CONFIG, candidate_factory=_candidate_factory)
    best = result.best_baseline()
    # The comparator is always one of the four required baselines; the candidate is diagnostic only.
    assert best in result.required_baselines
    assert best != CANDIDATE


def test_candidate_inner_holdout_runs_with_enough_history() -> None:
    # Two seasons of ten observed gameweeks each: the later folds carry >=14 prior observed
    # gameweeks, so Candidate V1's nested alpha selection actually runs (used_inner_holdout=True).
    rows: list[dict[str, object]] = []
    for gw in range(1, 11):
        rows.append(
            _row(season="2023-24", gw=gw, fixture=gw, kickoff=_kick(8, gw), code=101, minutes=90)
        )
    for gw in range(1, 11):
        rows.append(
            _row(season="2024-25", gw=gw, fixture=gw, kickoff=_kick(9, gw), code=101, minutes=90)
        )
    con = _build_db(rows, _TEAM_MAP)
    result = run_minutes_harness(con, config=CONFIG, candidate_factory=_candidate_factory)
    used = [
        params[CANDIDATE]["used_inner_holdout"] for params in result.parameters_by_fold.values()
    ]
    assert any(used)
    # Earlier folds (fewer than 14 prior observed gameweeks) use the frozen fallback instead.
    assert not all(used)
