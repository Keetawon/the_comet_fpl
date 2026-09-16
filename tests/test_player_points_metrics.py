"""Hand-computable synthetic points scores only; no real forecasts loaded."""

import json
import math
import random
from dataclasses import asdict

import pytest

from fpl.validate.metrics import randomised_pit, score_predictions
from fpl.validate.player_points_metrics import summarize_points


def pmf(values):
    return tuple(values.get(i, 0.0) for i in range(35))


def row(**changes):
    return {
        "season": "2025-26",
        "gw": 1,
        "fixture": 1,
        "code": 100,
        "position": "DEF",
        "was_home": True,
        "signed_target": 5,
        "scored_target": 5,
        "incumbent_pmf": pmf({0: 0.5, 5: 0.5}),
        "candidate_pmf": pmf({0: 0.25, 5: 0.75}),
        "cold_start": False,
        "direct_price_proxy": False,
        "team_price_proxy": True,
        "fixture_price_proxy": True,
        "promoted_team": False,
        "rotation_risk": False,
        "role_confidence": "unavailable",
        "workload_scope": "unavailable",
        **changes,
    }


def test_hand_computable_scores_endpoints_and_proper_count_reuse():
    r = row()
    result = summarize_points([r])
    old, new = (result["overall"][a] for a in ("incumbent", "candidate"))
    assert old["mean_log_score"] == -math.log(0.5)
    assert new["mean_log_score"] == -math.log(0.75)
    assert old["mean_crps"] == 1.25 and new["mean_crps"] == 0.3125
    assert new["mean_xp"] == 3.75
    assert new["mean_absolute_error"] == 1.25
    assert new["events"]["blank_le2"]["brier"] == 0.0625
    assert new["events"]["points_ge5"]["brier"] == 0.0625
    assert new["events"]["points_ge10"]["brier"] == 0
    assert new["events"]["points_ge5"]["reliability"][7]["rows"] == 1
    reference = asdict(score_predictions("candidate", [r["candidate_pmf"]], [5], seed=202627))
    for key in ("mean_log_score", "mean_crps", "pit_interval_80_coverage", "mean_absolute_error"):
        assert new[key] == reference[key]
    pit = randomised_pit(r["candidate_pmf"], 5, random.Random(202627))
    assert new["pit_interval_80_coverage"] == int(0.1 <= pit <= 0.9)
    assert new["spearman_within_gameweek"] is None
    assert new["spearman_within_gameweek_position"] is None
    assert new["mean_log_score_standard_error"] is None
    assert sum(new["pit_histogram"]) == 1
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(("signed", "scored", "bias"), [(-3, 0, 3.0), (40, 34, -6.0)])
def test_signed_target_is_retained_separately_from_coarsened_primary(signed, scored, bias):
    r = row(
        signed_target=signed,
        scored_target=scored,
        incumbent_pmf=pmf({scored: 1.0}),
        candidate_pmf=pmf({scored: 1.0}),
    )
    result = summarize_points([r])
    values = result["overall"]["candidate"]
    assert values["mean_log_score"] == values["mean_crps"] == values["mean_absolute_error"] == 0
    assert values["signed_target_mean_error"] == bias
    assert values["signed_target_mae"] == abs(bias)
    assert result["signed_targets_below_zero"] == int(signed < 0)
    assert result["signed_targets_above_34"] == int(signed > 34)


def test_floor_and_zero_bin_counts_distinguish_sparse_monte_carlo():
    r = row(candidate_pmf=pmf({0: 1.0}))
    values = summarize_points([r])["overall"]["candidate"]
    assert values["mean_log_score"] == -math.log(1e-12)
    assert values["log_floor_hit_count"] == values["zero_target_bin_count"] == 1
    r["candidate_pmf"] = pmf({0: 1 - 1e-13, 5: 1e-13})
    values = summarize_points([r])["overall"]["candidate"]
    assert values["zero_target_bin_count"] == 0 and values["log_floor_hit_count"] == 1


def test_loss_pairing_clusters_gameweeks_not_fixtures_or_players():
    rows = [
        row(code=1, signed_target=0, scored_target=0),
        row(code=2, fixture=2, signed_target=0, scored_target=0),
        row(code=3, gw=2, fixture=3, signed_target=0, scored_target=0, candidate_pmf=pmf({0: 1.0})),
    ]
    paired = summarize_points(rows)["paired_vs_incumbent"]
    d = math.log(2)
    assert paired["paired_mean"] == pytest.approx(d / 3)
    assert paired["gw_clustered_standard_error"] == pytest.approx(8 * d / 9)
    assert paired["clusters"] == 2
    assert len(paired["fixture_losses"]) == len(paired["row_losses"]) == 3
    assert paired["fixture_losses"][0]["difference"] == pytest.approx(d)
    assert summarize_points(rows) == summarize_points(list(reversed(rows)))


def test_fixed_slices_and_proxy_exclusion_do_not_change_overall_population():
    rows = [
        row(direct_price_proxy=True, cold_start=True),
        row(
            code=2,
            position="GK",
            gw=7,
            fixture=2,
            was_home=False,
            team_price_proxy=False,
            fixture_price_proxy=False,
            promoted_team=True,
            rotation_risk=True,
            role_confidence="high",
            workload_scope="witnessed_over90m_7d",
        ),
    ]
    result = summarize_points(rows)
    slices = result["slices"]
    for label in (
        "position:GK",
        "GW1-6",
        "GW7+",
        "home",
        "away",
        "cold_start",
        "established",
        "direct_price_proxy",
        "non_proxy",
        "team_price_proxy",
        "no_team_price_proxy",
        "fixture_price_proxy",
        "no_fixture_price_proxy",
        "promoted",
        "established_team",
        "rotation_risk",
        "no_rotation_risk",
        "role_confidence:high",
        "workload_scope:witnessed_over90m_7d",
        "direct_proxy_exclusion_diagnostic_only",
    ):
        assert slices[label]["rows"] == 1
    assert result["overall"]["rows"] == slices["season:2025-26"]["rows"] == 2
    assert result["primary_population_changed_by_proxy_diagnostic"] is False


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"signed_target": True}, "integer signed target"),
        ({"scored_target": 4}, "exact 0..34 coarsening"),
        ({"signed_target": 5.5}, "integer signed target"),
        ({"gw": 0}, "scoring identity"),
        ({"code": True}, "scoring identity"),
        ({"position": "Manager"}, "scoring identity"),
        ({"rotation_risk": 1}, "slice labels"),
        ({"role_confidence": "invented"}, "slice labels"),
        ({"workload_scope": "exact_zero"}, "slice labels"),
        ({"candidate_pmf": (1.0,)}, "35-mass points PMF"),
        ({"candidate_pmf": (float("nan"),) + (0.0,) * 34}, "finite normalized"),
        ({"candidate_pmf": (-0.1, 1.1) + (0.0,) * 33}, "finite normalized"),
        ({"candidate_pmf": (1.0 - 1e-10,) + (0.0,) * 34}, "finite normalized"),
        ({"candidate_pmf": (True,) + (0.0,) * 34}, "finite normalized"),
    ],
)
def test_invalid_labels_probabilities_and_identity_fail_closed(change, match):
    with pytest.raises(ValueError, match=match):
        summarize_points([row(**change)])


def test_no_silent_empty_duplicate_or_incomplete_population():
    for rows, match in (
        ([], "nonempty fixed points population"),
        ([row(), row()], "unique stable player-fixture"),
        ([{"season": "2025-26"}], "incomplete points scoring row"),
        ([row(), row(gw=2)], "unique stable player-fixture"),
        ([row(), row(gw=2, code=2)], "fixture requires one gameweek"),
    ):
        with pytest.raises(ValueError, match=match):
            summarize_points(rows)


def test_ties_and_single_position_ranking_remain_deterministic():
    rows = [
        row(code=1, signed_target=0, scored_target=0),
        row(code=2),
        row(
            code=3,
            signed_target=10,
            scored_target=10,
            incumbent_pmf=pmf({10: 1.0}),
            candidate_pmf=pmf({10: 1.0}),
        ),
    ]
    result = summarize_points(rows)
    values = result["overall"]["candidate"]
    assert values["spearman_within_gameweek"] == pytest.approx(math.sqrt(0.75))
    assert values["spearman_within_gameweek_position"] == values["spearman_within_gameweek"]
    assert "gate" not in result and "verdict" not in result
    assert summarize_points(rows) == result


def test_endpoint_boundaries_include_exact_two_five_ten_and_upper_support():
    distribution = pmf({2: 0.1, 3: 0.1, 4: 0.1, 5: 0.2, 9: 0.2, 10: 0.1, 34: 0.2})
    events = summarize_points(
        [row(signed_target=10, scored_target=10, candidate_pmf=distribution)]
    )["overall"]["candidate"]["events"]
    for label, probability, outcome in (
        ("blank_le2", 0.1, 0),
        ("points_ge5", 0.7, 1),
        ("points_ge10", 0.3, 1),
    ):
        assert events[label]["mean_probability"] == pytest.approx(probability)
        assert events[label]["brier"] == pytest.approx((probability - outcome) ** 2)
        assert events[label]["observed_rate"] == outcome


def test_empty_slices_and_reliability_buckets_remain_unavailable():
    result = summarize_points([row(direct_price_proxy=True)])
    for label in (
        "position:GK",
        "position:MID",
        "position:FWD",
        "GW7+",
        "away",
        "cold_start",
        "role_confidence:high",
        "role_confidence:low",
        "workload_scope:witnessed_up_to90m_7d",
        "direct_proxy_exclusion_diagnostic_only",
    ):
        assert result["slices"][label] == {"rows": 0, "incumbent": None, "candidate": None}
    assert result["slices"]["gameweek:2025-26:1"] == result["overall"]
    assert result["paired_vs_incumbent"]["gw_clustered_standard_error"] is None
    bucket = result["overall"]["candidate"]["events"]["points_ge5"]["reliability"][0]
    assert bucket == {"lower": 0.0, "upper": 0.1, "rows": 0, "predicted": None, "observed": None}
    json.dumps(result, allow_nan=False)


def test_seeded_pit_histogram_uses_exact_existing_randomisation():
    rows = [row(code=code, candidate_pmf=pmf({5: 1.0})) for code in range(1, 21)]
    result = summarize_points(rows)
    generator = random.Random(202627)
    pit = [randomised_pit(r["candidate_pmf"], r["scored_target"], generator) for r in rows]
    counts = [sum(min(int(p * 10), 9) == b for p in pit) for b in range(10)]
    assert result["overall"]["candidate"]["pit_histogram"] == counts
    assert summarize_points(list(reversed(rows))) == result
    changed = summarize_points(rows, seed=202628)
    assert changed["overall"]["candidate"]["pit_histogram"] != counts


@pytest.mark.parametrize("seed", [True, None, "202627"])
def test_seed_must_be_an_explicit_integer(seed):
    with pytest.raises(ValueError, match="integer scoring seed"):
        summarize_points([row()], seed=seed)
