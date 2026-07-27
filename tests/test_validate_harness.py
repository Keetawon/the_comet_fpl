"""End-to-end walk-forward run: training windows, refitting, scoring, reporting.

Archive-backed throughout, because what is being asserted is that the harness produces a
defensible number on the real archive -- and, in particular, that its training window really
does stop at the fold cutoff.
"""

from __future__ import annotations

import duckdb
import pytest

from fpl.config import load_phase1_evaluation
from fpl.validate.baselines import build_baselines
from fpl.validate.folds import generate_folds
from fpl.validate.harness import (
    _fold_fixtures,
    _training_window,
    compare_xg_against_goals,
    format_report,
    passes_calibration_gate,
    run,
    run_fold,
)
from fpl.validate.metrics import ScoreReport

pytestmark = pytest.mark.archive


@pytest.fixture(scope="module")
def one_season(db: duckdb.DuckDBPyConnection):
    """A single season keeps the module fast; the full run is exercised once, below."""
    return run(db, seasons=["2025-26"])


# --------------------------------------------------------------------------------------
# Point-in-time behaviour
# --------------------------------------------------------------------------------------


def test_the_training_window_stops_at_the_cutoff(db: duckdb.DuckDBPyConnection) -> None:
    """The whole harness rests on this one filter."""
    folds = generate_folds(db)
    for fold in (folds[0], folds[len(folds) // 2], folds[-1]):
        window = _training_window(db, fold)
        assert not window.is_empty
        latest = window.frame["kickoff_time"].max()
        assert latest < fold.as_of, fold


def test_the_training_window_never_contains_the_predicted_gameweek(
    db: duckdb.DuckDBPyConnection,
) -> None:
    folds = generate_folds(db)
    for fold in (folds[0], folds[len(folds) // 2], folds[-1]):
        window = _training_window(db, fold)
        overlap = window.frame.filter(
            (window.frame["season"] == fold.season) & (window.frame["gw"] == fold.gw)
        )
        assert overlap.is_empty(), fold


def test_the_training_window_expands_across_seasons(db: duckdb.DuckDBPyConnection) -> None:
    """A team model with no cross-season history has no prior at all in August.

    Gameweek 1 of 2025-26 must still see four previous seasons of matches.
    """
    folds = generate_folds(db)
    opener = next(fold for fold in folds if fold.season == "2025-26" and fold.gw == 1)
    window = _training_window(db, opener)
    seasons = set(window.frame["season"].to_list())
    assert seasons == {"2021-22", "2022-23", "2023-24", "2024-25"}
    assert window.frame.height == 4 * 760


def test_the_earliest_fold_still_has_a_training_window(
    db: duckdb.DuckDBPyConnection,
) -> None:
    fold = generate_folds(db)[0]
    window = _training_window(db, fold)
    assert window.frame.height > 0
    assert set(window.frame["season"].to_list()) == {"2021-22"}


def test_fold_fixtures_are_the_gameweek_and_only_the_gameweek(
    db: duckdb.DuckDBPyConnection,
) -> None:
    fold = generate_folds(db)[-1]
    fixtures = _fold_fixtures(db, fold)
    assert set(fixtures["season"].to_list()) == {fold.season}
    assert set(fixtures["gw"].to_list()) == {fold.gw}
    assert fixtures["goals_for"].null_count() == 0, "unplayed rows must not be scored"


# --------------------------------------------------------------------------------------
# One fold
# --------------------------------------------------------------------------------------


def test_run_fold_predicts_every_baseline_on_the_same_rows(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """`comparison_population: same_eligible_predictions`.

    Every baseline must be scored on an identical population, or the comparison is between
    different questions rather than different answers.
    """
    fold = generate_folds(db)[-1]
    result = run_fold(db, fold, build_baselines())
    assert result is not None
    names = {baseline.name for baseline in build_baselines()}
    assert set(result.distributions) == names
    for distributions in result.distributions.values():
        assert len(distributions) == len(result.observed)


def test_baselines_are_refitted_inside_each_fold(db: duckdb.DuckDBPyConnection) -> None:
    """`fit_transforms_within_fold`. A rating carried over would embed later matches.

    The same baseline object is reused across folds by design, so the check that matters is
    that fitting it on a later window actually changes what it predicts -- if it did not, a
    stale fit from a future fold could survive undetected.
    """
    folds = generate_folds(db)
    early, late = folds[0], folds[-1]
    fixtures = _fold_fixtures(db, late)

    baseline = build_baselines()[1]  # trailing_goals_attack_defence
    baseline.fit(_training_window(db, early))
    early_rates = baseline.predict_rates(fixtures)
    baseline.fit(_training_window(db, late))
    late_rates = baseline.predict_rates(fixtures)

    assert early_rates != pytest.approx(late_rates)


# --------------------------------------------------------------------------------------
# Full run
# --------------------------------------------------------------------------------------


def test_a_single_season_run_scores_every_played_fixture(one_season) -> None:
    assert one_season.folds_evaluated == 38
    assert one_season.predictions == 760  # 380 fixtures x 2 sides
    assert set(one_season.by_season) == {"2025-26"}


def test_every_baseline_is_scored_on_the_same_population(one_season) -> None:
    counts = {report.predictions for report in one_season.overall.values()}
    assert counts == {one_season.predictions}


def test_reported_scores_are_finite_and_plausible(one_season) -> None:
    """A single Premier League match is mostly irreducible, so a log score near 1.5 is the
    honest scale here -- not a sign the baselines are broken."""
    for report in one_season.overall.values():
        assert 1.0 < report.mean_log_score < 2.5, report.name
        assert 0.3 < report.mean_crps < 1.2, report.name
        assert 0.5 < report.mean_absolute_error < 2.0, report.name


def test_best_baseline_is_the_lowest_log_score(one_season) -> None:
    """The bar a candidate must clear -- chosen by the metric, never by hand."""
    best = one_season.best_baseline()
    assert best in one_season.overall
    assert one_season.overall[best].mean_log_score == min(
        report.mean_log_score for report in one_season.overall.values()
    )


def test_the_run_is_deterministic(db: duckdb.DuckDBPyConnection, one_season) -> None:
    """Same seed, same archive, same numbers -- a report that moves is not evidence."""
    repeat = run(db, seasons=["2025-26"])
    for name, report in one_season.overall.items():
        assert repeat.overall[name].mean_log_score == report.mean_log_score
        assert repeat.overall[name].pit_values == report.pit_values


def test_season_filter_restricts_the_evaluated_folds_only(
    db: duckdb.DuckDBPyConnection, one_season
) -> None:
    """Filtering the report must not shorten the training history behind it.

    A season-restricted run still trains on everything before each cutoff; if it did not,
    2025-26 would be evaluated cold and the numbers would not be comparable to a full run.
    """
    opener = next(fold for fold in generate_folds(db) if fold.season == "2025-26" and fold.gw == 1)
    assert _training_window(db, opener).frame.height == 4 * 760
    assert one_season.folds_evaluated == 38


def test_a_full_run_covers_every_fold_and_prediction(db: duckdb.DuckDBPyConnection) -> None:
    contract = load_phase1_evaluation()
    result = run(db)
    assert result.folds_evaluated == 181
    assert result.folds_evaluated >= contract.promotion.minimum_fold_count
    assert set(result.by_season) == {
        "2021-22",
        "2022-23",
        "2023-24",
        "2024-25",
        "2025-26",
    }
    # 3,800 team-fixtures across five seasons, less the eight warm-up gameweeks of 2021-22.
    assert result.predictions == 3_800 - 8 * 20

    coverage = result.predictions / (3_800 - 8 * 20)
    assert coverage >= contract.promotion.minimum_fixture_coverage


def test_every_baseline_passes_the_amended_calibration_gate(one_season) -> None:
    """Amendment 1.1, measured on the archive rather than on a swept Poisson.

    Every baseline lands within 0.05 of 80% on the PIT coverage and none of them does on the
    raw coverage. Since these are the comparators a candidate is judged against, a gate they
    all fail would not be a demanding bar -- it would be a broken measurement.
    """
    gate = load_phase1_evaluation().promotion.pit_interval_80_maximum_absolute_error
    for report in one_season.overall.values():
        assert passes_calibration_gate(report), report.name
        assert report.pit_interval_80_absolute_error <= gate, report.name
        assert abs(report.interval_80_coverage - 0.80) > gate, (
            f"{report.name} was expected to breach the superseded raw-interval gate"
        )


def test_the_calibration_gate_reads_its_tolerance_from_the_contract() -> None:
    """The gate has to be able to fail, and has to follow the config rather than a constant."""
    report = ScoreReport(
        name="badly_calibrated",
        predictions=100,
        mean_log_score=1.0,
        mean_crps=1.0,
        interval_80_coverage=0.80,
        pit_interval_80_coverage=0.55,
        mean_absolute_error=1.0,
        pit_values=(),
    )
    assert not passes_calibration_gate(report)
    assert report.pit_interval_80_absolute_error == pytest.approx(0.25)


def test_the_report_shows_the_gate_and_names_the_contract_version(one_season) -> None:
    text = format_report(one_season)
    contract = load_phase1_evaluation()
    assert "calibration gate" in text
    assert f"contract {contract.contract_version}" in text
    assert "reported, not gated" in text


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------


def test_format_report_lists_every_baseline_in_score_order(one_season) -> None:
    text = format_report(one_season)
    for name in one_season.overall:
        assert name in text
    ordered = sorted(one_season.overall.values(), key=lambda r: r.mean_log_score)
    positions = [text.index(report.name) for report in ordered]
    assert positions == sorted(positions)
    assert one_season.best_baseline() in text.split("best baseline: ")[1]


def test_the_xg_comparison_reports_both_baselines_and_a_signed_lift(
    one_season,
) -> None:
    text = compare_xg_against_goals(one_season)
    assert "trailing goals" in text
    assert "trailing xG" in text
    assert "relative lift of xG over goals" in text
    assert "winner on the contract's primary metric" in text


def test_xg_beats_goals_once_the_2022_23_zero_prefix_is_repaired(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """The specification's open question, answered on the contract's own metric.

    The original quick test favoured recorded goals, but it ran before the 2022-23
    `expected_*` defect was repaired -- that season's first fifteen gameweeks carried zeros
    where xG was unmeasured, which held its mean team xG at 0.963 against a true 1.499.
    With the repair in place xG wins overall and in every season that has any.

    2021-22 is the exception and cannot be otherwise: it carries no xG at all, so the xG
    baseline degenerates to the league intercept and ties with it rather than competing.
    """
    result = run(db)
    goals = result.overall["trailing_goals_attack_defence"]
    xg = result.overall["trailing_xg_attack_defence"]
    assert xg.mean_log_score < goals.mean_log_score
    assert xg.mean_crps < goals.mean_crps

    per_season_winner = {
        season: (
            "xg"
            if reports["trailing_xg_attack_defence"].mean_log_score
            < reports["trailing_goals_attack_defence"].mean_log_score
            else "goals"
        )
        for season, reports in result.by_season.items()
    }
    assert per_season_winner["2021-22"] == "goals"
    for season in ("2022-23", "2023-24", "2024-25", "2025-26"):
        assert per_season_winner[season] == "xg", season

    league = result.by_season["2021-22"]["league_home_away_goals"].mean_log_score
    xg_2021 = result.by_season["2021-22"]["trailing_xg_attack_defence"].mean_log_score
    assert xg_2021 == pytest.approx(league), "with no xG the baseline must be the intercept"
