"""End-to-end walk-forward run: training windows, refitting, scoring, reporting.

Archive-backed throughout, because what is being asserted is that the harness produces a
defensible number on the real archive -- and, in particular, that its training window really
does stop at the fold cutoff.
"""

from __future__ import annotations

from dataclasses import replace

import duckdb
import pytest

from fpl.config import load_phase1_evaluation
from fpl.models.team_goals import StageATeamModel
from fpl.validate.baselines import build_baselines
from fpl.validate.folds import generate_folds
from fpl.validate.harness import (
    _fold_fixtures,
    _training_window,
    compare_xg_against_goals,
    evaluate_gate,
    format_report,
    passes_calibration_gate,
    run,
    run_fold,
)
from fpl.validate.metrics import ScoreReport, relative_lift

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
    assert set(result.cold_starts) == names
    assert len(result.promoted_status) == len(result.observed)
    assert len(result.home_away) == len(result.observed)


def test_candidate_v2_retains_fold_local_parameters(db: duckdb.DuckDBPyConnection) -> None:
    contract = load_phase1_evaluation()
    fold = generate_folds(db)[-1]
    candidate = StageATeamModel(
        contract.stage_a_candidate,
        minimum_team_matches=contract.training.minimum_team_matches,
    )
    result = run_fold(db, fold, [candidate])
    assert result is not None
    parameters = result.parameters[candidate.name]
    assert parameters["half_life_days"] in {
        *contract.stage_a_candidate.half_life_days,
        "no_decay",
    }
    assert parameters["prior_matches"] in contract.stage_a_candidate.prior_matches
    assert parameters["inner_holdout_observed_gameweeks"] == 6


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
    assert one_season.eligible_predictions == 760
    assert one_season.leakage_failures == 0
    assert one_season.folds_by_season == {"2025-26": 38}
    assert set(one_season.by_season) == {"2025-26"}


def test_every_baseline_is_scored_on_the_same_population(one_season) -> None:
    counts = {report.predictions for report in one_season.overall.values()}
    assert counts == {one_season.predictions}
    assert {report.eligible_predictions for report in one_season.overall.values()} == {760}
    assert {report.exclusions for report in one_season.overall.values()} == {0}


def test_every_contracted_report_dimension_is_materialised(one_season) -> None:
    assert len(one_season.by_fold) == 38
    assert set(one_season.by_promoted_status) == {"established", "promoted"}
    assert set(one_season.by_home_away) == {"home", "away"}
    assert len(one_season.parameters_by_fold) == 38
    for report in one_season.overall.values():
        assert report.mean_log_score_standard_error > 0.0
        assert report.mean_poisson_deviance > 0.0
        assert report.mean_predictive_variance > 0.0
        assert -1.0 <= report.spearman_within_gameweek <= 1.0


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
        eligible_predictions=100,
        exclusions=0,
        cold_starts=0,
        mean_log_score=1.0,
        mean_log_score_standard_error=0.1,
        mean_crps=1.0,
        mean_poisson_deviance=1.0,
        interval_80_coverage=0.80,
        pit_interval_80_coverage=0.55,
        mean_absolute_error=1.0,
        mean_predictive_variance=1.0,
        spearman_within_gameweek=0.0,
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
    assert "by promoted status" in text
    assert "by home/away" in text
    assert "raw80" in text
    assert "excl" in text


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
    assert one_season.best_baseline() in text.split("best required baseline: ")[1]


def test_gate_enforces_coverage_leakage_and_every_season_guardrail(one_season) -> None:
    comparator = one_season.best_baseline()
    baseline = one_season.overall[comparator]
    candidate = replace(
        baseline,
        name="candidate",
        mean_log_score=baseline.mean_log_score * 0.98,
        mean_crps=baseline.mean_crps * 0.99,
        pit_interval_80_coverage=0.80,
    )
    season_baseline = one_season.by_season["2025-26"][comparator]
    season_candidate = replace(
        season_baseline,
        name="candidate",
        mean_log_score=season_baseline.mean_log_score * 0.98,
        mean_crps=season_baseline.mean_crps * 0.99,
        pit_interval_80_coverage=0.80,
    )
    passing = replace(
        one_season,
        required_baselines=frozenset({comparator}),
        overall={comparator: baseline, "candidate": candidate},
        by_season={"2025-26": {comparator: season_baseline, "candidate": season_candidate}},
    )
    assert all(check.passed for check in evaluate_gate(passing, "candidate"))

    low_coverage = replace(
        passing,
        overall={
            comparator: baseline,
            "candidate": replace(candidate, predictions=97, eligible_predictions=100, exclusions=3),
        },
    )
    failed = {check.name for check in evaluate_gate(low_coverage, "candidate") if not check.passed}
    assert "same eligible prediction population" in failed
    assert "fixture coverage" in failed

    leaky = replace(passing, leakage_failures=1)
    failed = {check.name for check in evaluate_gate(leaky, "candidate") if not check.passed}
    assert "zero leakage failures" in failed

    season_crps_regression = replace(
        passing,
        by_season={
            "2025-26": {
                comparator: season_baseline,
                "candidate": replace(season_candidate, mean_crps=season_baseline.mean_crps * 1.01),
            }
        },
    )
    failed = {
        check.name
        for check in evaluate_gate(season_crps_regression, "candidate")
        if not check.passed
    }
    assert "every season avoids CRPS regression" in failed


def test_the_xg_comparison_reports_both_baselines_and_a_signed_lift(
    one_season,
) -> None:
    text = compare_xg_against_goals(one_season)
    assert "trailing goals" in text
    assert "trailing xG" in text
    assert "relative lift of xG over goals" in text
    assert "winner on the contract's primary metric" in text


def test_xg_wins_wherever_xg_is_actually_measured(db: duckdb.DuckDBPyConnection) -> None:
    """The specification's open question, answered on the seasons that can answer it.

    Pooled over all five seasons the goals baseline wins, but that number cannot be read as
    "goals beat xG": two of the five seasons have no xG to train on. 2021-22 carries none at
    all, so the xG baseline degenerates exactly to the league intercept there, and 2022-23
    carries it for only 64% of team-fixtures. The pooled figure is therefore mostly measuring
    xG's absence.

    Restricted to the three seasons with complete xG coverage, xG wins outright -- every
    season individually, on both proper scores. That is the honest answer: use xG where it
    exists, and expect no benefit from it in a season that lacks it.
    """
    coverage = {
        season: (measured, total)
        for season, total, measured in db.execute(
            """
            SELECT season, count(*), count(team_xg) FROM mart_fact_team_match
            GROUP BY season ORDER BY season
            """
        ).fetchall()
    }
    assert coverage["2021-22"][0] == 0, "2021-22 was expected to carry no xG at all"
    assert coverage["2022-23"][0] < coverage["2022-23"][1], "2022-23 xG is partial"
    complete = ["2023-24", "2024-25", "2025-26"]
    for season in complete:
        assert coverage[season][0] == coverage[season][1], season

    result = run(db)
    goals = result.overall["trailing_goals_attack_defence"]
    xg = result.overall["trailing_xg_attack_defence"]
    assert goals.mean_log_score < xg.mean_log_score, "pooled, xG loses to its own absence"

    league_2021 = result.by_season["2021-22"]["league_home_away_goals"].mean_log_score
    xg_2021 = result.by_season["2021-22"]["trailing_xg_attack_defence"].mean_log_score
    assert xg_2021 == pytest.approx(league_2021), "with no xG the baseline is the intercept"

    for season in complete:
        reports = result.by_season[season]
        assert (
            reports["trailing_xg_attack_defence"].mean_log_score
            < reports["trailing_goals_attack_defence"].mean_log_score
        ), season

    measured = run(db, seasons=complete)
    goals_only = measured.overall["trailing_goals_attack_defence"]
    xg_only = measured.overall["trailing_xg_attack_defence"]
    assert relative_lift(goals_only.mean_log_score, xg_only.mean_log_score) > 0.005
    assert xg_only.mean_crps < goals_only.mean_crps
