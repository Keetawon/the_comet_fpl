"""Executable tests for the frozen BI semantic contract, version 6.

The contract's value is that it is enforced, not that it is written down, so most of these tests are
negative: they construct a contract that breaks an invariant and prove the validator rejects it.
The positive tests pin the published shape -- table set, grains, keys, null semantics -- so a later
change to the contract is a deliberate, reviewed edit rather than a silent drift.

Offline except for one `archive`-marked test that checks the declared source tables really exist.
"""

from __future__ import annotations

import duckdb
import pytest

from fpl.publish.contract import (
    CROSS_SEASON_KEYS,
    NOT_YET_SOURCED,
    SEASON_SCOPED_KEYS,
    SEMANTIC_CONTRACT_V1,
    SEMANTIC_CONTRACT_V2,
    SEMANTIC_CONTRACT_V3,
    SEMANTIC_CONTRACT_V4,
    SEMANTIC_CONTRACT_V5,
    SEMANTIC_CONTRACT_V6,
    Column,
    Join,
    SemanticContract,
    SemanticContractError,
    Table,
)

CONTRACT = SEMANTIC_CONTRACT_V6
LEDGER_SOURCE_TABLES = frozenset(
    {
        "ledger_forecast_run",
        "ledger_prediction_player_gameweek",
        "ledger_prediction_player_fixture",
        "ledger_prediction_team_fixture",
        "ledger_outcome_player_fixture",
        "ledger_outcome_team_fixture",
    }
)
FORECAST_LEDGER_SOURCE_TABLES = frozenset(
    {
        "ledger_forecast_run",
        "ledger_prediction_player_gameweek",
        "ledger_prediction_player_fixture",
        "ledger_prediction_team_fixture",
    }
)
OUTCOME_LEDGER_SOURCE_TABLES = LEDGER_SOURCE_TABLES - FORECAST_LEDGER_SOURCE_TABLES


# --------------------------------------------------------------------------------------
# The published shape
# --------------------------------------------------------------------------------------


def test_contract_publishes_the_expected_tables() -> None:
    assert CONTRACT.version == 6
    assert {table.name for table in CONTRACT.tables} == {
        # dimensions
        "dim_forecast_run",
        "dim_player",
        "dim_player_season",
        "dim_player_stint",
        "dim_team",
        "dim_team_season",
        "dim_fixture",
        "dim_gameweek",
        "dim_optimizer_run",
        # facts
        "fact_forecast_player_gameweek",
        "fact_forecast_player_fixture",
        "fact_forecast_team_fixture",
        "fact_player_fixture_actual",
        "fact_team_fixture_actual",
        "fact_provisional_player_fixture_observation",
        "fact_provisional_team_fixture_observation",
        "fact_finalized_player_fixture_outcome",
        "fact_finalized_team_fixture_outcome",
        "fact_player_form",
        "fact_team_form",
        "fact_optimizer_plan",
    }


def test_historical_v1_contract_remains_importable_without_schedule_fdr() -> None:
    assert SEMANTIC_CONTRACT_V1.version == 1
    fixture = SEMANTIC_CONTRACT_V1.table("dim_fixture")
    assert "home_official_fdr" not in fixture.column_names
    assert "away_official_fdr" not in fixture.column_names


def test_historical_v2_contract_remains_importable_without_v3_monitoring_additions() -> None:
    assert SEMANTIC_CONTRACT_V2.version == 2
    assert (
        "goals_for_distribution"
        not in SEMANTIC_CONTRACT_V2.table("fact_forecast_team_fixture").column_names
    )
    assert "fact_finalized_player_fixture_outcome" not in SEMANTIC_CONTRACT_V2.by_name
    assert "fact_finalized_team_fixture_outcome" not in SEMANTIC_CONTRACT_V2.by_name


def test_historical_v4_contract_remains_importable_without_team_actuals() -> None:
    assert SEMANTIC_CONTRACT_V4.version == 4
    assert "fact_team_fixture_actual" not in SEMANTIC_CONTRACT_V4.by_name


def test_historical_v5_contract_remains_importable_without_provisional_reporting() -> None:
    assert SEMANTIC_CONTRACT_V5.version == 5
    assert "fact_provisional_player_fixture_observation" not in SEMANTIC_CONTRACT_V5.by_name
    assert "fact_provisional_team_fixture_observation" not in SEMANTIC_CONTRACT_V5.by_name


def test_provisional_contract_keeps_raw_points_distinct_from_final_replay() -> None:
    player = CONTRACT.table("fact_provisional_player_fixture_observation")
    team = CONTRACT.table("fact_provisional_team_fixture_observation")
    assert player.grain == ("season", "fixture", "code")
    assert team.grain == ("season", "fixture", "team_id")
    assert player.forecast_scoped is False
    assert team.forecast_scoped is False
    assert "run_id" not in player.column_names
    assert "run_id" not in team.column_names
    assert "total_points_as_recorded" in player.column_names
    assert "points_under_rules_2026_27" not in player.column_names
    assert "observed_at" in player.column_names
    assert "observed_at" in team.column_names
    notes = " ".join((*player.notes, *team.notes))
    assert "finished_provisional=true or finished=true" in notes
    assert "whole fixture" in notes
    assert "never enters either finalized outcome ledger" in notes


def test_team_actual_contract_pins_finalised_match_grain_and_null_semantics() -> None:
    table = CONTRACT.table("fact_team_fixture_actual")
    assert table.grain == ("season", "fixture", "team_id")
    assert table.forecast_scoped is False
    assert {column.name: column.null_means for column in table.columns} == {
        "season": None,
        "fixture": None,
        "team_id": None,
        "team_code": None,
        "opponent_team_id": None,
        "gw": None,
        "kickoff_time": None,
        "was_home": None,
        "goals_for": None,
        "goals_against": None,
        "team_xg": "unmeasured",
        "team_xgc": "unmeasured",
        "team_bps": "unmeasured",
        "defensive_contribution": "unmeasured",
    }
    assert (
        ("season", "season"), ("opponent_team_id", "team_id")
    ) in {join.on for join in table.joins}
    assert (
        ("season", "season"),
        ("team_id", "team_id"),
        ("team_code", "team_code"),
    ) in {join.on for join in table.joins}
    assert "ledger_outcome_player_fixture" in table.source_owner


def test_historical_v3_contract_remains_importable_with_archive_only_actual_ownership() -> None:
    assert SEMANTIC_CONTRACT_V3.version == 3
    actual = SEMANTIC_CONTRACT_V3.table("fact_player_fixture_actual")
    assert "mart_fact_player_fixture_live" not in actual.source_owner
    assert "ledger_outcome_player_fixture" not in actual.source_owner


@pytest.mark.parametrize(
    ("table", "grain"),
    [
        ("dim_forecast_run", ("run_id",)),
        ("dim_player", ("code",)),
        ("dim_player_season", ("season", "code")),
        ("dim_player_stint", ("season", "code", "stint_index")),
        ("dim_team", ("team_code",)),
        ("dim_team_season", ("season", "team_id")),
        ("dim_fixture", ("season", "fixture")),
        ("dim_gameweek", ("season", "gw")),
        ("fact_forecast_player_gameweek", ("run_id", "season", "gw", "code")),
        ("fact_forecast_player_fixture", ("run_id", "season", "fixture", "code")),
        ("fact_forecast_team_fixture", ("run_id", "season", "fixture", "team_id")),
        ("fact_player_fixture_actual", ("season", "fixture", "code")),
        ("fact_finalized_player_fixture_outcome", ("season", "fixture", "code")),
        ("fact_finalized_team_fixture_outcome", ("season", "fixture", "team_id")),
        ("fact_player_form", ("season", "gw", "code", "window")),
        ("fact_team_form", ("season", "gw", "team_code", "window")),
        ("fact_optimizer_plan", ("optimizer_run_id", "gw", "code")),
    ],
)
def test_each_table_declares_its_frozen_grain(table: str, grain: tuple[str, ...]) -> None:
    assert CONTRACT.table(table).grain == grain


def test_player_fixture_facts_use_the_fixture_grain_not_player_gameweek() -> None:
    """Double gameweeks are real, so the fixture facts must key on fixture."""
    for name in (
        "fact_forecast_player_fixture",
        "fact_player_fixture_actual",
        "fact_finalized_player_fixture_outcome",
    ):
        grain = CONTRACT.table(name).grain
        assert "fixture" in grain
        assert "gw" not in grain


def test_cross_season_keys_are_the_only_single_column_identity_grains() -> None:
    """dim_player and dim_team are the join targets for cross-season questions."""
    assert CONTRACT.table("dim_player").grain == ("code",)
    assert CONTRACT.table("dim_team").grain == ("team_code",)
    assert {"code", "team_code"} == CROSS_SEASON_KEYS


def test_season_scoped_dimensions_never_key_on_a_bare_reassigned_id() -> None:
    for name in ("dim_player_season", "dim_team_season"):
        grain = CONTRACT.table(name).grain
        assert "season" in grain, f"{name} must be season-qualified"


def test_player_dimension_carries_no_club() -> None:
    """A player's club is a question with a time in it; it never belongs on the identity row."""
    columns = CONTRACT.table("dim_player").column_names
    assert not columns & {"team_id", "team_code", "season_end_team_id"}


def test_season_end_team_id_is_nullable_and_documented_as_unreliable() -> None:
    column = next(
        c for c in CONTRACT.table("dim_player_season").columns if c.name == "season_end_team_id"
    )
    assert column.nullable
    assert "120 of 242" in column.description
    assert "dim_player_stint" in column.description


# --------------------------------------------------------------------------------------
# Forecast / outcome separation
# --------------------------------------------------------------------------------------


def test_every_forecast_fact_carries_run_id_and_as_of_and_keys_on_the_vintage() -> None:
    forecast_facts = [table for table in CONTRACT.tables if table.forecast_scoped]
    assert {table.name for table in forecast_facts} == {
        "fact_forecast_player_gameweek",
        "fact_forecast_player_fixture",
        "fact_forecast_team_fixture",
    }
    for table in forecast_facts:
        assert {"run_id", "as_of"} <= table.column_names
        assert "run_id" in table.grain


def test_actual_and_form_facts_carry_no_run_id() -> None:
    """Outcomes stay separate from predictions until finalisation."""
    for name in (
        "fact_player_fixture_actual",
        "fact_finalized_player_fixture_outcome",
        "fact_finalized_team_fixture_outcome",
        "fact_player_form",
        "fact_team_form",
    ):
        assert "run_id" not in CONTRACT.table(name).column_names


def test_optimizer_plan_references_a_forecast_vintage_without_being_one() -> None:
    table = CONTRACT.table("fact_optimizer_plan")
    assert table.forecast_scoped is False
    assert "run_id" not in table.column_names
    assert "forecast_run_id" in table.column_names
    assert any(join.to_table == "dim_forecast_run" for join in table.joins)


def test_recorded_and_replayed_points_are_separate_measures() -> None:
    for name in ("fact_player_fixture_actual", "fact_finalized_player_fixture_outcome"):
        columns = CONTRACT.table(name).column_names
        assert {"total_points_as_recorded", "points_under_rules_2026_27"} <= columns


def test_team_fixture_ease_columns_are_additive_directed_and_versioned() -> None:
    table = CONTRACT.table("fact_forecast_team_fixture")
    by_name = {column.name: column for column in table.columns}
    for name in (
        "league_average_team_lambda",
        "attack_ease_index",
        "defence_ease_index",
        "overall_ease_index",
    ):
        assert by_name[name].nullable and by_name[name].null_means == "unmeasured"
    assert not by_name["ease_index_formula_version"].nullable
    for name in ("attack_ease_index", "defence_ease_index", "overall_ease_index"):
        assert "100 is league average" in by_name[name].description
        assert "higher means" in by_name[name].description
    assert "never blended" in by_name["official_fdr"].description
    pmf = by_name["goals_for_distribution"]
    assert pmf.dtype == "string" and not pmf.nullable
    assert "Exact JSON probability vector" in pmf.description


def test_outcome_facts_are_append_only_ledger_owned_and_vintage_independent() -> None:
    player = CONTRACT.table("fact_finalized_player_fixture_outcome")
    team = CONTRACT.table("fact_finalized_team_fixture_outcome")
    assert "ledger_outcome_player_fixture" in player.source_owner
    assert "mart_fact_player_fixture" not in player.source_owner
    assert team.source_owner == "fpl.storage.ledger:ledger_outcome_team_fixture"
    assert "attached_at" in player.column_names
    assert "attached_at" in team.column_names
    assert "run_id" not in player.column_names
    assert "run_id" not in team.column_names
    assert {
        "team_code",
        "opponent_team_id",
        "gw",
        "kickoff_time",
        "was_home",
        "goals_for",
        "goals_against",
    } <= team.column_names


def test_v4_actual_uses_live_components_only_with_ledger_owned_finality_and_points() -> None:
    actual = CONTRACT.table("fact_player_fixture_actual")
    assert "mart_fact_player_fixture" in actual.source_owner
    assert "mart_target_player_fixture" in actual.source_owner
    assert "mart_fact_player_fixture_live" in actual.source_owner
    assert "ledger_outcome_player_fixture" in actual.source_owner
    notes = " ".join(actual.notes)
    assert "deterministic latest" in notes
    assert "ledger" in notes
    assert "fails closed" in notes


def test_fixture_dimension_carries_current_official_fdr_for_both_sides() -> None:
    fixture = CONTRACT.table("dim_fixture")
    by_name = {column.name: column for column in fixture.columns}
    assert {"home_official_fdr", "away_official_fdr"} <= by_name.keys()
    for name in ("home_official_fdr", "away_official_fdr"):
        assert by_name[name].nullable
        assert by_name[name].dtype == "int"
        assert by_name[name].null_means == "unmeasured"


# --------------------------------------------------------------------------------------
# NULL semantics
# --------------------------------------------------------------------------------------


def test_every_nullable_column_declares_what_its_null_means() -> None:
    for table in CONTRACT.tables:
        for column in table.columns:
            if column.nullable:
                assert column.null_means is not None, f"{table.name}.{column.name}"
            else:
                assert column.null_means is None, f"{table.name}.{column.name}"


def test_unmeasured_signals_are_nullable_never_zero_filled() -> None:
    actual = CONTRACT.table("fact_player_fixture_actual")
    for name in ("expected_goals", "expected_assists", "expected_goals_conceded"):
        column = next(c for c in actual.columns if c.name == name)
        assert column.nullable and column.null_means == "unmeasured"


def test_player_form_defensive_measures_preserve_population_and_measurement_nulls() -> None:
    form = CONTRACT.table("fact_player_form")
    by_name = {column.name: column for column in form.columns}
    for name in ("clean_sheets", "goals_conceded", "saves"):
        column = by_name[name]
        assert column.nullable and column.dtype == "int"
        assert column.null_means == "not_applicable"
        assert "did not appear" in column.description
    xgc = by_name["expected_goals_conceded"]
    assert xgc.nullable and xgc.dtype == "float"
    assert xgc.null_means == "unmeasured"
    assert "never zero-filled" in xgc.description


def test_per_90_rates_document_their_matching_minutes_denominator() -> None:
    form = CONTRACT.table("fact_player_form")
    for name in ("expected_goals_per_90", "expected_assists_per_90"):
        column = next(c for c in form.columns if c.name == name)
        assert column.nullable
        assert "same measured" in column.description
        assert "NULL when that" in column.description


def test_form_starts_preserves_historical_measurement_coverage() -> None:
    """2021-22 never measured starts, so a form aggregate must not invent zero starts."""
    form = CONTRACT.table("fact_player_form")
    starts = next(column for column in form.columns if column.name == "starts")
    assert starts.nullable and starts.null_means == "unmeasured"
    assert "2021-22" in starts.description


def test_grain_columns_are_never_nullable() -> None:
    for table in CONTRACT.tables:
        by_name = {column.name: column for column in table.columns}
        for key in table.grain:
            assert not by_name[key].nullable, f"{table.name}.{key}"


# --------------------------------------------------------------------------------------
# Allowed joins
# --------------------------------------------------------------------------------------


def test_every_declared_join_resolves_to_real_tables_and_columns() -> None:
    for table in CONTRACT.tables:
        for join in table.joins:
            target = CONTRACT.table(join.to_table)
            for local, remote in join.on:
                assert local in table.column_names, f"{table.name}.{local}"
                assert remote in target.column_names, f"{target.name}.{remote}"


def test_no_declared_join_uses_a_season_scoped_id_without_season() -> None:
    """The invariant that already cost 0.022 of mean log score inside the Stage A baselines."""
    for table in CONTRACT.tables:
        for join in table.joins:
            locals_ = set(join.local_columns)
            if locals_ & SEASON_SCOPED_KEYS:
                assert "season" in locals_, f"{table.name} -> {join.to_table}"


def test_many_to_one_joins_bind_the_full_target_grain() -> None:
    for table in CONTRACT.tables:
        for join in table.joins:
            if join.cardinality == "many_to_one":
                target = CONTRACT.table(join.to_table)
                assert set(target.grain) <= set(join.remote_columns), (
                    f"{table.name} -> {target.name} would fan out"
                )


def test_club_is_resolvable_from_a_stint_and_from_a_fact_row() -> None:
    stint = CONTRACT.table("dim_player_stint")
    assert {"team_id", "team_code"} <= stint.column_names
    actual = CONTRACT.table("fact_player_fixture_actual")
    assert {"team_id", "team_code"} <= actual.column_names


# --------------------------------------------------------------------------------------
# The validator actually rejects violations
# --------------------------------------------------------------------------------------


def _column(name: str, *, nullable: bool = False) -> Column:
    return Column(
        name=name,
        dtype="int" if name != "season" else "string",
        nullable=nullable,
        null_means="unmeasured" if nullable else None,
        description=f"{name} for testing",
    )


def _dim(name: str, grain: tuple[str, ...], extra: tuple[str, ...] = ()) -> Table:
    return Table(
        name=name,
        role="dimension",
        subject="test",
        grain=grain,
        grain_note="test",
        source_owner="test",
        columns=tuple(_column(column) for column in (*grain, *extra)),
    )


def test_validator_rejects_a_cross_season_team_id_join() -> None:
    """The exact defect the contract exists to prevent."""
    target = _dim("dim_team_season", ("season", "team_id"))
    offender = Table(
        name="fact_offender",
        role="fact",
        subject="test",
        grain=("season", "team_id"),
        grain_note="test",
        source_owner="test",
        columns=(_column("season"), _column("team_id")),
        joins=(
            Join(
                to_table="dim_team_season",
                on=(("team_id", "team_id"),),  # season deliberately not bound
                cardinality="many_to_one",
            ),
        ),
    )
    with pytest.raises(SemanticContractError, match="without binding season"):
        SemanticContract(version=1, tables=(target, offender))


def test_validator_rejects_a_cross_season_element_id_join() -> None:
    target = _dim("dim_player_season", ("season", "element_id"))
    offender = Table(
        name="fact_offender",
        role="fact",
        subject="test",
        grain=("season", "element_id"),
        grain_note="test",
        source_owner="test",
        columns=(_column("season"), _column("element_id")),
        joins=(
            Join(
                to_table="dim_player_season",
                on=(("element_id", "element_id"),),
                cardinality="many_to_one",
            ),
        ),
    )
    with pytest.raises(SemanticContractError, match="without binding season"):
        SemanticContract(version=1, tables=(target, offender))


def test_validator_rejects_a_forecast_fact_missing_run_id_or_as_of() -> None:
    table = Table(
        name="fact_bad_forecast",
        role="fact",
        subject="test",
        grain=("season",),
        grain_note="test",
        source_owner="test",
        columns=(_column("season"),),
        forecast_scoped=True,
    )
    with pytest.raises(SemanticContractError, match="run_id and as_of"):
        SemanticContract(version=1, tables=(table,))


def test_validator_rejects_a_forecast_fact_that_does_not_key_on_the_vintage() -> None:
    """Without run_id in the grain a later vintage would collide with an earlier one."""
    table = Table(
        name="fact_bad_forecast",
        role="fact",
        subject="test",
        grain=("season",),
        grain_note="test",
        source_owner="test",
        columns=(
            _column("season"),
            Column(name="run_id", dtype="string", description="vintage"),
            Column(name="as_of", dtype="timestamp", description="knowledge time"),
        ),
        forecast_scoped=True,
    )
    with pytest.raises(SemanticContractError, match="part of a forecast fact's grain"):
        SemanticContract(version=1, tables=(table,))


def test_validator_rejects_an_outcome_fact_carrying_run_id() -> None:
    table = Table(
        name="fact_bad_actual",
        role="fact",
        subject="test",
        grain=("season",),
        grain_note="test",
        source_owner="test",
        columns=(_column("season"), Column(name="run_id", dtype="string", description="vintage")),
    )
    with pytest.raises(SemanticContractError, match="must not carry run_id"):
        SemanticContract(version=1, tables=(table,))


def test_validator_rejects_a_fanning_many_to_one_join() -> None:
    target = _dim("dim_two_part", ("season", "code"))
    offender = Table(
        name="fact_offender",
        role="fact",
        subject="test",
        grain=("season", "code"),
        grain_note="test",
        source_owner="test",
        columns=(_column("season"), _column("code")),
        joins=(Join(to_table="dim_two_part", on=(("code", "code"),), cardinality="many_to_one"),),
    )
    with pytest.raises(SemanticContractError, match="fan out"):
        SemanticContract(version=1, tables=(target, offender))


def test_validator_rejects_an_unknown_join_target_or_column() -> None:
    offender = Table(
        name="fact_offender",
        role="fact",
        subject="test",
        grain=("season",),
        grain_note="test",
        source_owner="test",
        columns=(_column("season"),),
        joins=(
            Join(to_table="dim_missing", on=(("season", "season"),), cardinality="many_to_one"),
        ),
    )
    with pytest.raises(SemanticContractError, match="unknown table"):
        SemanticContract(version=1, tables=(offender,))


def test_validator_rejects_duplicate_table_names() -> None:
    table = _dim("dim_dupe", ("season",))
    with pytest.raises(SemanticContractError, match="unique"):
        SemanticContract(version=1, tables=(table, table))


def test_table_rejects_a_grain_column_that_is_nullable_or_absent() -> None:
    with pytest.raises(ValueError, match="must be non-nullable"):
        Table(
            name="dim_bad",
            role="dimension",
            subject="test",
            grain=("season",),
            grain_note="test",
            source_owner="test",
            columns=(_column("season", nullable=True),),
        )
    with pytest.raises(ValueError, match="not a published column"):
        Table(
            name="dim_bad",
            role="dimension",
            subject="test",
            grain=("missing",),
            grain_note="test",
            source_owner="test",
            columns=(_column("season"),),
        )


def test_column_requires_null_semantics_exactly_when_nullable() -> None:
    with pytest.raises(ValueError, match="must declare what its NULL means"):
        Column(name="x", dtype="int", nullable=True, description="d")
    with pytest.raises(ValueError, match="must not declare a NULL meaning"):
        Column(name="x", dtype="int", null_means="unmeasured", description="d")


# --------------------------------------------------------------------------------------
# Source ownership
# --------------------------------------------------------------------------------------


def test_every_contract_table_is_now_sourced_for_the_exporter() -> None:
    """P1.6 sources the last P1.1 declaration, so P1.4 can require the complete contract."""
    assert frozenset() == NOT_YET_SOURCED
    for table in CONTRACT.tables:
        assert "NOT YET IMPLEMENTED" not in table.source_owner
    assert CONTRACT.table("fact_player_form").source_owner == (
        "fpl.transform.facts:mart_fact_player_form"
    )
    assert CONTRACT.table("fact_team_form").source_owner == (
        "fpl.transform.facts:mart_fact_team_form"
    )


def _referenced_source_tables(source_owner: str) -> set[str]:
    return {
        token.strip(" ()+")
        for token in source_owner.replace(":", " ").split()
        if token.strip(" ()+").startswith(("mart_", "ledger_", "stg_"))
    }


def test_every_sourced_table_names_a_database_table_or_an_artifact_module() -> None:
    """A source owner is either production tables or a typed artifact, never hand-waving."""
    for table in CONTRACT.tables:
        if table.name in NOT_YET_SOURCED:
            continue
        owner = table.source_owner
        assert _referenced_source_tables(owner) or owner.startswith("fpl.artifacts."), (
            f"{table.name} names neither a source table nor an artifact module in {owner!r}"
        )
    # The optimizer plan is the one artifact-sourced table; it has no production table behind it.
    assert CONTRACT.table("fact_optimizer_plan").source_owner == "fpl.artifacts.optimizer_plan"


@pytest.mark.archive
def test_declared_source_tables_exist_in_the_database(db: duckdb.DuckDBPyConnection) -> None:
    """Every source exists, except the documented all-absent fresh ledger state.

    ``build_db`` intentionally does not create a ledger until the first forecast is recorded. P1.4
    treats that complete zero-vintage state as publishable; a partially present ledger remains
    source drift and must fail this check (and the exporter) closed.
    """
    existing = {
        row[0]
        for row in db.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
    }

    checked = 0
    for table in CONTRACT.tables:
        if table.name in NOT_YET_SOURCED:
            continue
        referenced = _referenced_source_tables(table.source_owner)
        missing = referenced - existing
        if missing:
            if referenced <= OUTCOME_LEDGER_SOURCE_TABLES:
                # A database created before the additive v3 outcome store is a valid empty
                # outcome fact; the exporter validates the complete shape whenever it exists.
                continue
            assert referenced <= FORECAST_LEDGER_SOURCE_TABLES and not (
                existing & FORECAST_LEDGER_SOURCE_TABLES
            ), f"{table.name} references missing source table(s) {sorted(missing)}"
            continue
        checked += len(referenced)
    assert checked > 0, "no production source tables were checked"
