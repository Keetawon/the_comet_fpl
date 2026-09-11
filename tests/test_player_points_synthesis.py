"""Synthetic fixtures only: keep CURRENT composition and one appearance gate."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest

from fpl.models.attacking_baselines import poisson_pmf
from fpl.models.points_composition import ComponentDistributions, FixturePlayer
from fpl.types import Position
from fpl.validate import player_points_synthesis as synthesis
from fpl.validate.development_reference_components import (
    DevelopmentReferenceComponents,
    ReferencePlayerComponents,
    compose_reference_fixture,
)
from fpl.validate.minutes_baselines import TargetRow

ZERO = (1.0,) + (0.0,) * 10
SIX = (0.0,) * 6 + (1.0,) + (0.0,) * 4
CUTOFF = datetime(2025, 8, 15, 18, tzinfo=UTC)


def synthetic_reference(roster_size=8):
    """Invented outcome-free rosters; first two players per club are GKs."""
    rows = []
    for i in range(roster_size):
        team = 1 if i < roster_size // 2 else 2
        slot = i % (roster_size // 2)
        pos = Position.GK if slot < 2 else (Position.DEF, Position.MID, Position.FWD)[slot % 3]
        code = 1000 + i
        target = TargetRow("2025-26", 1, 901, CUTOFF, code, pos, team, 3 - team, team == 1)
        components = ComponentDistributions(
            pos,
            (1.0, 0.0, 0.0, 0.0) if slot == 0 else (0.2, 0.1, 0.2, 0.5),
            poisson_pmf(0.18),
            poisson_pmf(0.12),
            poisson_pmf(1.35),
            poisson_pmf(3) if pos == Position.GK else ZERO,
            0 if pos == Position.GK else 0.25,
        )
        rows.append(
            ReferencePlayerComponents(
                target,
                100 + team,
                FixturePlayer(code, components, 5 + i, 2.3),
                False,
                False,
                (),
                (),
                "{}",
                None,
                None,
                0.1,
                0.1,
                0.1,
                0.1,
                False,
            )
        )
    return DevelopmentReferenceComponents(
        "2025-26",
        1,
        CUTOFF,
        tuple(reversed(rows)),
        ((901, 101, poisson_pmf(1.35)), (901, 102, poisson_pmf(1.35))),
        "{}",
        "{}",
    )


@pytest.fixture(scope="module")
def context():
    return synthesis.build_composer_context()


@pytest.fixture
def reference():
    return synthetic_reference()


def all_gks(reference, pmf=SIX):
    return {
        row.player.code: pmf
        for row in reference.rows
        if row.player.components.position == Position.GK
    }


@pytest.mark.parametrize("replacements", [None, {}])
def test_empty_replacements_are_bit_exact_current_full_fixture(reference, context, replacements):
    expected = compose_reference_fixture(reference, 901)
    actual = synthesis.compose_synthesis_fixture(
        reference, 901, context, saves_replacements=replacements
    )
    assert actual == expected
    assert [r.code for r in actual] == sorted(r.target.code for r in reference.rows)
    assert all(len(r.distribution) == 35 for r in actual)
    assert all(sum(r.distribution) == pytest.approx(1, abs=1e-13) for r in actual)


def test_incumbent_gk_replacements_are_also_bit_exact(reference, context):
    replacements = {
        r.player.code: r.player.components.saves
        for r in reference.rows
        if r.player.components.position == Position.GK
    }
    assert synthesis.compose_synthesis_fixture(
        reference, 901, context, saves_replacements=replacements
    ) == compose_reference_fixture(reference, 901)


def test_exact_unchanged_composer_call_and_no_reference_mutation(reference, context, monkeypatch):
    before = repr(reference)
    captured = {}

    def spy(players, points, bps, extra, **kwargs):
        captured.update(players=players, points=points, bps=bps, extra=extra, kwargs=kwargs)
        return []

    monkeypatch.setattr(synthesis, "compose_fixture_full_points", spy)
    assert (
        synthesis.compose_synthesis_fixture(
            reference, 901, context, saves_replacements=all_gks(reference)
        )
        == ()
    )
    assert repr(reference) == before
    assert captured["points"] is context.points
    assert captured["bps"] is context.bps
    assert captured["extra"] is context.extra
    assert captured["kwargs"] == {
        "fixture_seed": synthesis._fixture_seed(202627, "2025-26", 901),
        "draws": 2000,
        "max_points": 34,
        "conceded_exposure": (0.0, 0.344, 0.813, 1.0),
    }
    assert len(captured["players"]) == len(reference.rows)
    for original, actual in zip(reference.rows, captured["players"], strict=True):
        expected = original.player
        if expected.components.position == Position.GK:
            expected = replace(expected, components=replace(expected.components, saves=SIX))
        assert actual == expected


def test_one_drawn_minutes_gate_and_exact_zero_for_predicted_nonappearance(reference, context):
    rows = []
    appearing_code = next(r.player.code for r in reference.rows if r.target.position == Position.GK)
    for row in reference.rows:
        c = replace(
            row.player.components,
            minutes=(0.4, 0.0, 0.0, 0.6) if row.player.code == appearing_code else (1, 0, 0, 0),
            goals=ZERO,
            assists=ZERO,
            team_goals_conceded=ZERO,
            saves=ZERO,
            dc_hit_probability=0,
        )
        rows.append(replace(row, player=replace(row.player, components=c)))
    reference = replace(reference, rows=tuple(rows))
    old = {r.code: r for r in synthesis.compose_synthesis_fixture(reference, 901, context)}
    new = {
        r.code: r
        for r in synthesis.compose_synthesis_fixture(
            reference, 901, context, saves_replacements=all_gks(reference)
        )
    }
    before, after = old[appearing_code], new[appearing_code]
    assert 0 < before.distribution[0] < 1
    assert before.distribution[0] == after.distribution[0]
    # Six conditional saves add two points in the SAME appearing worlds only.
    assert sum(i * p for i, p in enumerate(after.distribution)) - sum(
        i * p for i, p in enumerate(before.distribution)
    ) == pytest.approx(2 * (1 - before.distribution[0]), abs=1e-12)
    assert before.expected_bonus == after.expected_bonus
    assert before.expected_bonus == pytest.approx(3 * (1 - before.distribution[0]), abs=1e-12)
    assert all(
        r.distribution == (1.0,) + (0.0,) * 34 for c, r in new.items() if c != appearing_code
    )


@pytest.mark.parametrize("defect", ["missing_gk", "extra_code", "non_gk", "string_code"])
def test_replacement_roster_is_exact_all_gks_not_appeared_subset(reference, context, defect):
    replacements = all_gks(reference)
    if defect == "missing_gk":
        replacements.pop(next(iter(replacements)))
    elif defect == "extra_code":
        replacements[99999] = SIX
    elif defect == "non_gk":
        replacements[
            next(r.player.code for r in reference.rows if r.target.position != Position.GK)
        ] = SIX
    else:
        code = next(iter(replacements))
        replacements[str(code)] = replacements.pop(code)
    with pytest.raises(ValueError, match="exactly every fixture GK"):
        synthesis.compose_synthesis_fixture(
            reference, 901, context, saves_replacements=replacements
        )


@pytest.mark.parametrize(
    "pmf",
    [
        (1.0,) * 11,
        ZERO[:10],
        (*ZERO, 0.0),
        (float("nan"), *ZERO[1:]),
        (float("inf"), *ZERO[1:]),
        (-0.1, 1.1) + (0.0,) * 9,
        (True, *ZERO[1:]),
        ("1.0", *ZERO[1:]),
        list(ZERO),
    ],
)
def test_invalid_replacement_pmf_rejected(reference, context, pmf):
    with pytest.raises(ValueError, match=r"unit-mass 0\.\.10"):
        synthesis.compose_synthesis_fixture(
            reference, 901, context, saves_replacements=all_gks(reference, pmf)
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_class", "strict_prospective"),
        ("identity", synthesis.NAME),
        ("promotion_permitted", True),
        ("promotion_permitted", 0),
    ],
)
def test_reference_cannot_be_relabelled_or_promoted(reference, context, field, value):
    with pytest.raises(ValueError, match="development CURRENT"):
        synthesis.compose_synthesis_fixture(replace(reference, **{field: value}), 901, context)


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate",
        "one_side",
        "opponent",
        "kickoff",
        "code",
        "position",
        "minutes",
        "goals",
        "saves",
        "dc",
        "residual",
        "sigma",
        "target_outcome",
    ],
)
def test_invalid_reference_identity_or_components_fail_closed(reference, context, defect):
    rows = list(reference.rows)
    row = rows[0]
    if defect == "duplicate":
        rows.append(row)
    elif defect == "one_side":
        rows = [r for r in rows if r.team_code == row.team_code]
    elif defect == "opponent":
        rows[0] = replace(row, target=replace(row.target, opponent_team_id=99))
    elif defect == "kickoff":
        rows[0] = replace(
            row, target=replace(row.target, kickoff_time=CUTOFF - timedelta(seconds=1))
        )
    elif defect == "code":
        rows[0] = replace(row, player=replace(row.player, code=98765))
    elif defect == "position":
        rows[0] = replace(
            row,
            player=replace(
                row.player, components=replace(row.player.components, position=Position.GK)
            ),
        )
    elif defect == "target_outcome":

        @dataclass(frozen=True, slots=True)
        class UnsafeTarget(TargetRow):
            actual_saves: int = 3

        rows[0] = replace(
            row,
            target=UnsafeTarget(
                **{name: getattr(row.target, name) for name in TargetRow.__dataclass_fields__}
            ),
        )
    else:
        values = {
            "minutes": (0.1, 0.1, 0.1, 0.1),
            "goals": (1.0,),
            "saves": (float("nan"),) * 11,
            "dc": float("nan"),
            "residual": float("inf"),
            "sigma": -1,
        }
        if defect in {"residual", "sigma"}:
            player = replace(
                row.player,
                **{"residual_mean" if defect == "residual" else "residual_sigma": values[defect]},
            )
        else:
            player = replace(
                row.player,
                components=replace(
                    row.player.components,
                    **{"dc_hit_probability" if defect == "dc" else defect: values[defect]},
                ),
            )
        rows[0] = replace(row, player=player)
    messages = {
        "duplicate": "duplicate",
        "one_side": "both complete",
        "opponent": "both complete",
        "kickoff": "precedes cutoff",
        "code": "identity/position",
        "position": "identity/position",
        "minutes": "sum to one",
        "goals": "unit-mass",
        "saves": "unit-mass",
        "dc": "invalid incumbent",
        "residual": "invalid incumbent",
        "sigma": "invalid incumbent",
        "target_outcome": "outcome-free reference predictor types",
    }
    with pytest.raises(ValueError, match=messages[defect]):
        synthesis.compose_synthesis_fixture(replace(reference, rows=tuple(rows)), 901, context)


def test_unknown_fixture_and_unsupported_components_rejected(reference, context):
    with pytest.raises(ValueError, match="absent"):
        synthesis.compose_synthesis_fixture(reference, 123, context)
    with pytest.raises(TypeError, match="dc_replacements"):
        synthesis.compose_synthesis_fixture(reference, 901, context, dc_replacements={})
    with pytest.raises(TypeError, match="targets"):
        synthesis.compose_synthesis_fixture(reference, 901, context, targets={})


def test_active_saves_cannot_enable_a_new_random_stream(reference, context):
    rows = tuple(
        replace(r, player=replace(r.player, components=replace(r.player.components, saves=None)))
        if r.target.position == Position.GK
        else r
        for r in reference.rows
    )
    reference = replace(reference, rows=rows)
    with pytest.raises(ValueError, match="random stream"):
        synthesis.compose_synthesis_fixture(
            reference, 901, context, saves_replacements=all_gks(reference)
        )


@pytest.mark.parametrize("position", [Position.DEF, Position.MID, Position.FWD])
def test_non_gk_current_reference_cannot_carry_nonzero_saves(reference, context, position):
    row = next(r for r in reference.rows if r.target.position != Position.GK)
    changed = replace(
        row,
        target=replace(row.target, position=position),
        player=replace(
            row.player, components=replace(row.player.components, position=position, saves=SIX)
        ),
    )
    reference = replace(reference, rows=tuple(changed if r is row else r for r in reference.rows))
    with pytest.raises(ValueError, match="non-GK saves"):
        synthesis.compose_synthesis_fixture(reference, 901, context)


def test_exact_predictor_type_rejects_hidden_outcome_fields(reference, context):
    @dataclass(frozen=True, slots=True)
    class UnsafePlayer(FixturePlayer):
        actual_saves: int = 4

    row = reference.rows[0]
    changed = replace(
        row,
        player=UnsafePlayer(
            row.player.code,
            row.player.components,
            row.player.residual_mean,
            row.player.residual_sigma,
        ),
    )
    reference = replace(reference, rows=(changed, *reference.rows[1:]))
    with pytest.raises(ValueError, match="outcome-free reference predictor types"):
        synthesis.compose_synthesis_fixture(reference, 901, context)


def test_inconsistent_same_gw_identity_in_other_fixture_is_rejected(reference, context):
    changed = tuple(
        replace(r, target=replace(r.target, fixture=902), team_code=r.team_code + 20)
        for r in reference.rows
    )
    reference = replace(reference, rows=(*reference.rows, *changed))
    with pytest.raises(ValueError, match="same-GW club/position identity conflict"):
        synthesis.compose_synthesis_fixture(reference, 901, context)


@pytest.mark.parametrize("replacements", [[], (), [(1000, SIX)]])
def test_replacement_container_requires_a_mapping(reference, context, replacements):
    with pytest.raises(ValueError, match="must be a mapping"):
        synthesis.compose_synthesis_fixture(
            reference, 901, context, saves_replacements=replacements
        )


def test_reused_context_is_deterministic_and_does_not_rebuild_lookups(
    reference, context, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("lookup was rebuilt during fixture composition")

    monkeypatch.setattr(synthesis, "PointsLookup", forbidden)
    monkeypatch.setattr(synthesis, "BpsExactLookup", forbidden)
    first = synthesis.compose_synthesis_fixture(
        reference, 901, context, saves_replacements=all_gks(reference)
    )
    second = synthesis.compose_synthesis_fixture(
        reference, 901, context, saves_replacements=all_gks(reference)
    )
    assert first == second
