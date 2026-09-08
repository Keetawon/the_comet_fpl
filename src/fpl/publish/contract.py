"""The frozen BI semantic contract, version 6.

DEV-ROADMAP P1.1 requires each published table's grain, keys, null semantics, source owner, and
allowed joins to be settled **before** the exporter exists, so P1.2-P1.4 build against a fixed
target instead of discovering the schema by writing it. This module is that contract as a typed,
self-validating declaration; `docs/bi-semantic-contract.md` is its prose counterpart.

It is a declaration and nothing else: no DuckDB, no I/O, no export logic. Reading it tells you what
the export must contain; it does not produce anything.

The reason it is executable rather than prose is that this repository's most expensive defects have
all been join-shaped. ``element_id`` and ``team_id`` are **reassigned every season** -- id 308 is
five different players across five seasons, and club id 10 is Leeds, Leicester, Fulham, Ipswich,
then Fulham again, so a cross-season join on it silently yields a Fulham history with Ipswich in the
middle. That class of bug already cost 0.022 of mean log score inside the Stage A baselines before
anyone noticed. :meth:`SemanticContract.validate_contract` therefore mechanically rejects any join
that touches a season-scoped id without also binding ``season``, alongside the other meta-rules:
every forecast fact carries ``run_id`` and ``as_of``, no actual fact carries ``run_id``, grain
columns are non-nullable, and every nullable column states what its NULL means.

Three dimensions here are additions to the roadmap's original five, each forced by a measured
invariant rather than by taste:

* ``dim_player_season`` -- ``web_name``, ``position`` and ``element_id`` are all season-scoped
  (``Salah`` becomes ``M.Salah``), so a single ``code``-grain player dimension carrying them would
  either misreport them or fan a cross-season query out by season.
* ``dim_player_stint`` -- "which club is this player at" is a question with a time in it. Measured
  242 transfer stints, of which the season dimension matches only 120, and three clubs in one season
  occurs. Club must come from a fact row or from a stint, never from a player dimension.
* ``dim_team_season`` -- the season-scoped ``team_id`` needs somewhere to resolve to a cross-season
  ``team_code`` that is 1:1 with the club.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SEMANTIC_CONTRACT_VERSION = 6

#: Season-scoped identifiers. A join may use one only when ``season`` is bound in the same join.
SEASON_SCOPED_KEYS: frozenset[str] = frozenset({"element_id", "team_id", "opponent_team_id"})

#: The cross-season identities. These are the only keys allowed to join across seasons.
CROSS_SEASON_KEYS: frozenset[str] = frozenset({"code", "team_code"})

DataType = Literal["string", "int", "float", "bool", "timestamp"]
TableRole = Literal["dimension", "fact"]
Cardinality = Literal["many_to_one", "one_to_one"]

#: What a NULL is allowed to mean. There is deliberately no "zero" option: a NULL is never
#: zero-filled, because an unmeasured xG and a measured xG of 0.0 are different facts.
NullMeaning = Literal[
    "unmeasured",
    "not_applicable",
    "unknown_until_finalised",
    "optional_attribute",
]


class SemanticContractError(Exception):
    """The declared semantic contract is internally inconsistent or breaks a join invariant.

    Deliberately not a ``ValueError``: Pydantic converts ``ValueError`` raised inside a validator
    into a ``ValidationError``, which would bury the contract breach in a generic message. Keeping
    it off that hierarchy means the specific invariant -- and the reason it exists -- reaches the
    caller intact, whether the contract is constructed or validated explicitly.
    """


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Column(_Frozen):
    """One published column, its type, and -- if nullable -- what its NULL means."""

    name: str
    dtype: DataType
    nullable: bool = False
    null_means: NullMeaning | None = None
    description: str

    @model_validator(mode="after")
    def _null_semantics_declared(self) -> Self:
        if not self.name or not self.description:
            raise ValueError("a column needs a name and a description")
        if self.nullable and self.null_means is None:
            raise ValueError(f"nullable column {self.name!r} must declare what its NULL means")
        if not self.nullable and self.null_means is not None:
            raise ValueError(f"non-nullable column {self.name!r} must not declare a NULL meaning")
        return self


class Join(_Frozen):
    """One allowed join from this table to another, with the exact column pairs."""

    to_table: str
    on: tuple[tuple[str, str], ...] = Field(min_length=1)
    cardinality: Cardinality
    note: str | None = None

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        if not self.to_table:
            raise ValueError("a join needs a target table")
        locals_ = [pair[0] for pair in self.on]
        if len(set(locals_)) != len(locals_):
            raise ValueError(f"join to {self.to_table} repeats a local column")
        return self

    @property
    def local_columns(self) -> tuple[str, ...]:
        return tuple(pair[0] for pair in self.on)

    @property
    def remote_columns(self) -> tuple[str, ...]:
        return tuple(pair[1] for pair in self.on)


class Table(_Frozen):
    """One published dimension or fact: its grain, its columns, and where it comes from."""

    name: str
    role: TableRole
    subject: str
    grain: tuple[str, ...] = Field(min_length=1)
    grain_note: str
    source_owner: str
    columns: tuple[Column, ...] = Field(min_length=1)
    joins: tuple[Join, ...] = ()
    #: A forecast fact is bound to one prediction vintage and must carry ``run_id`` and ``as_of``.
    forecast_scoped: bool = False
    notes: tuple[str, ...] = ()

    @field_validator("columns")
    @classmethod
    def _unique_columns(cls, value: tuple[Column, ...]) -> tuple[Column, ...]:
        names = [column.name for column in value]
        if len(set(names)) != len(names):
            raise ValueError("column names must be unique within a table")
        return value

    @model_validator(mode="after")
    def _grain_is_a_real_non_null_key(self) -> Self:
        by_name = {column.name: column for column in self.columns}
        if len(set(self.grain)) != len(self.grain):
            raise ValueError(f"{self.name}: grain repeats a column")
        for key in self.grain:
            column = by_name.get(key)
            if column is None:
                raise ValueError(f"{self.name}: grain column {key!r} is not a published column")
            if column.nullable:
                raise ValueError(f"{self.name}: grain column {key!r} must be non-nullable")
        if self.forecast_scoped and self.role != "fact":
            raise ValueError(f"{self.name}: only a fact can be forecast-scoped")
        return self

    @property
    def column_names(self) -> frozenset[str]:
        return frozenset(column.name for column in self.columns)


def _key(name: str, dtype: DataType, description: str) -> Column:
    return Column(name=name, dtype=dtype, description=description)


def _nullable(name: str, dtype: DataType, null_means: NullMeaning, description: str) -> Column:
    return Column(
        name=name, dtype=dtype, nullable=True, null_means=null_means, description=description
    )


class SemanticContract(_Frozen):
    """The complete versioned set of published tables, validated as one closed schema."""

    version: int = Field(ge=1)
    tables: tuple[Table, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validated(self) -> Self:
        self.validate_contract()
        return self

    @property
    def by_name(self) -> dict[str, Table]:
        return {table.name: table for table in self.tables}

    def table(self, name: str) -> Table:
        try:
            return self.by_name[name]
        except KeyError as exc:
            raise SemanticContractError(f"no published table named {name!r}") from exc

    def validate_contract(self) -> None:
        """Enforce every meta-rule. Raises :class:`SemanticContractError` on the first breach."""
        tables = self.tables
        names = [table.name for table in tables]
        if len(set(names)) != len(names):
            raise SemanticContractError("published table names must be unique")
        by_name = {table.name: table for table in tables}

        for table in tables:
            self._check_forecast_scoping(table)
            for join in table.joins:
                self._check_join(table, join, by_name)

    @staticmethod
    def _check_forecast_scoping(table: Table) -> None:
        has_run_id = "run_id" in table.column_names
        has_as_of = "as_of" in table.column_names
        if table.forecast_scoped:
            if not (has_run_id and has_as_of):
                raise SemanticContractError(
                    f"{table.name}: a forecast fact must carry both run_id and as_of"
                )
            if "run_id" not in table.grain:
                raise SemanticContractError(
                    f"{table.name}: run_id must be part of a forecast fact's grain, otherwise a "
                    "later vintage would collide with an earlier one"
                )
        elif table.role == "fact" and has_run_id:
            raise SemanticContractError(
                f"{table.name}: a non-forecast fact must not carry run_id; outcomes are kept "
                "separate from predictions until finalisation"
            )

    @staticmethod
    def _check_join(table: Table, join: Join, by_name: dict[str, Table]) -> None:
        target = by_name.get(join.to_table)
        if target is None:
            raise SemanticContractError(
                f"{table.name}: join targets unknown table {join.to_table!r}"
            )
        for local, remote in join.on:
            if local not in table.column_names:
                raise SemanticContractError(
                    f"{table.name}: join to {target.name} uses unknown local column {local!r}"
                )
            if remote not in target.column_names:
                raise SemanticContractError(
                    f"{table.name}: join to {target.name} uses unknown remote column {remote!r}"
                )
        # The expensive invariant: a season-scoped id may only be joined with season bound too.
        local_columns = set(join.local_columns)
        scoped = local_columns & SEASON_SCOPED_KEYS
        if scoped and "season" not in local_columns:
            raise SemanticContractError(
                f"{table.name}: join to {target.name} uses season-scoped key(s) "
                f"{sorted(scoped)} without binding season. These ids are reassigned every "
                "season, so this join silently merges different players or clubs. Qualify it "
                "with season, or join on code / team_code instead."
            )
        # A many-to-one join must land on the target's full grain, or it is not many-to-one.
        if join.cardinality == "many_to_one":
            remote_columns = set(join.remote_columns)
            missing = set(target.grain) - remote_columns
            if missing:
                raise SemanticContractError(
                    f"{table.name}: many_to_one join to {target.name} does not bind its full "
                    f"grain; missing {sorted(missing)}. It would fan out."
                )


# ======================================================================================
# Dimensions
# ======================================================================================

DIM_FORECAST_RUN = Table(
    name="dim_forecast_run",
    role="dimension",
    subject="One immutable prediction vintage recorded in the append-only ledger.",
    grain=("run_id",),
    grain_note="One row per recorded forecast run. Never updated; a re-forecast is a new row.",
    source_owner="fpl.storage.ledger:ledger_forecast_run",
    columns=(
        _key("run_id", "string", "Deterministic ledger run identity."),
        _key("as_of", "timestamp", "Knowledge time. The most important column in the schema."),
        _key("created_at", "timestamp", "When the vintage was recorded."),
        _key("season", "string", "Season the forecast covers, e.g. 2026-27."),
        _key("gw_from", "int", "First forecast gameweek."),
        _key("gw_to", "int", "Last forecast gameweek."),
        _key("status", "string", "Development-only status string carried from the artifact."),
        _key("commit_sha", "string", "Repository commit that produced the forecast."),
        _key("database_sha256", "string", "Content hash of the database read."),
        _key("artifact_sha256", "string", "Canonical hash of the forecast artifact."),
        _key("base_seed", "int", "Monte-Carlo base seed."),
        _key("monte_carlo_draws", "int", "Draws per player-fixture simulation."),
        _key("row_count", "int", "Prediction rows in the vintage."),
        _key("roster_size", "int", "Players in the forecast roster."),
        _key("component_modes", "string", "JSON of the declared component architecture."),
        _key("contract_identities", "string", "JSON of the frozen contract versions and hashes."),
        _key("bootstrap_known_at", "timestamp", "Knowledge time of the live bootstrap capture."),
    ),
    notes=(
        "as_of is knowledge time, not event time. Every forecast fact must be filtered or "
        "sliced by this dimension; comparing two vintages without it compares different "
        "knowledge states.",
        "component_modes is what distinguishes a default vintage from a diagnostic one.",
    ),
)

DIM_PLAYER = Table(
    name="dim_player",
    role="dimension",
    subject="A player's permanent cross-season identity.",
    grain=("code",),
    grain_note=(
        "One row per player, ever. This is the only player dimension safe to join across "
        "seasons without fanning out."
    ),
    source_owner=(
        "fpl.transform.crosswalk:mart_dim_player + "
        "fpl.ingest.live_snapshot:stg_live_player_version (distinct on code, live season unioned)"
    ),
    columns=(
        _key("code", "int", "Permanent player identity, 1:1 with the person across all seasons."),
        _nullable(
            "opta_code",
            "string",
            "optional_attribute",
            "External Opta identifier where the source provides one.",
        ),
        _nullable(
            "latest_web_name",
            "string",
            "optional_attribute",
            "Display name from the most recent season. DISPLAY ONLY: web_name drifts between "
            "seasons (Salah -> M.Salah), so it is never a key and never a join column.",
        ),
    ),
    notes=(
        "Carries no club and no position. Both are season-scoped, and club is time-scoped even "
        "within a season; see dim_player_season and dim_player_stint.",
    ),
)

DIM_PLAYER_SEASON = Table(
    name="dim_player_season",
    role="dimension",
    subject="A player's season-scoped attributes.",
    grain=("season", "code"),
    grain_note="One row per player per season they appear in.",
    source_owner=(
        "fpl.transform.crosswalk:mart_dim_player + fpl.ingest.live_snapshot:stg_live_player_version"
    ),
    columns=(
        _key("season", "string", "Season, e.g. 2026-27."),
        _key("code", "int", "Permanent player identity."),
        _key("element_id", "int", "Season-scoped FPL element id. NEVER join this across seasons."),
        _key("web_name", "string", "Display name as used in this season."),
        _key("position", "string", "GK, DEF, MID or FWD in this season."),
        _nullable(
            "season_end_team_id",
            "int",
            "not_applicable",
            "Season-scoped id of the club the player FINISHED the season at. Reporting only: it "
            "matched the true club in 120 of 242 measured transfer stints, so it must never be "
            "used to resolve club membership. Use the fact row's team_id or dim_player_stint.",
        ),
    ),
    joins=(
        Join(
            to_table="dim_player",
            on=(("code", "code"),),
            cardinality="many_to_one",
            note="Safe: code is the cross-season identity.",
        ),
    ),
    notes=(
        "element_id is reassigned yearly. Measured: element_id 308 resolves to Almiron, Ake, "
        "Salah, Ward and Heath across five seasons.",
    ),
)

DIM_PLAYER_STINT = Table(
    name="dim_player_stint",
    role="dimension",
    subject="A continuous spell a player spent at one club inside one season.",
    grain=("season", "code", "stint_index"),
    grain_note=(
        "One row per player per club spell per season. A player may have more than two stints; "
        "three clubs in one season occurs."
    ),
    source_owner="fpl.transform.crosswalk:mart_dim_player_stint",
    columns=(
        _key("season", "string", "Season."),
        _key("code", "int", "Permanent player identity."),
        _key("stint_index", "int", "Ordinal of the spell within the season, starting at 1."),
        _key("team_id", "int", "Season-scoped club id for the spell."),
        _key("team_code", "int", "Cross-season club identity for the spell."),
        _nullable("first_gw", "int", "not_applicable", "First gameweek of the spell."),
        _nullable("last_gw", "int", "not_applicable", "Last gameweek of the spell."),
        _nullable("first_kickoff", "timestamp", "not_applicable", "First kickoff in the spell."),
        _nullable("last_kickoff", "timestamp", "not_applicable", "Last kickoff in the spell."),
        _key("appearances", "int", "Appearances made during the spell."),
        _key("minutes", "int", "Minutes played during the spell."),
    ),
    joins=(
        Join(to_table="dim_player", on=(("code", "code"),), cardinality="many_to_one"),
        Join(
            to_table="dim_team_season",
            on=(("season", "season"), ("team_id", "team_id")),
            cardinality="many_to_one",
            note="Season-qualified, as the invariant requires.",
        ),
        Join(to_table="dim_team", on=(("team_code", "team_code"),), cardinality="many_to_one"),
    ),
    notes=(
        "This is the answer to 'which club was this player at'. A player's attacking share "
        "travels with him on transfer but the team scale does not, and defensive contribution "
        "is a property of the team system, so a transferred player's expectations are not "
        "portable between stints.",
    ),
)

DIM_TEAM = Table(
    name="dim_team",
    role="dimension",
    subject="A club's permanent cross-season identity.",
    grain=("team_code",),
    grain_note=(
        "One row per club, ever. 27 codes over five seasons. The only club key safe to join "
        "across seasons."
    ),
    source_owner=(
        "fpl.transform.crosswalk:mart_dim_team + fpl.ingest.live_snapshot:stg_live_team_version "
        "(distinct on team_code, live season unioned)"
    ),
    columns=(
        _key("team_code", "int", "Permanent club identity, 1:1 with the club."),
        _key("team_name", "string", "Club name."),
        _key("short_name", "string", "Three-letter club abbreviation."),
    ),
)

DIM_TEAM_SEASON = Table(
    name="dim_team_season",
    role="dimension",
    subject="The season-scoped club id and its resolution to a permanent club.",
    grain=("season", "team_id"),
    grain_note="One row per club per season it played in.",
    source_owner=(
        "fpl.transform.crosswalk:mart_dim_team + fpl.ingest.live_snapshot:stg_live_team_version"
    ),
    columns=(
        _key("season", "string", "Season."),
        _key("team_id", "int", "Season-scoped club id. NEVER join this across seasons."),
        _key("team_code", "int", "Permanent club identity this id resolves to in this season."),
        _key("team_name", "string", "Club name in this season."),
        _key("short_name", "string", "Three-letter abbreviation in this season."),
        _nullable("pulse_id", "int", "optional_attribute", "External Pulse identifier."),
    ),
    joins=(Join(to_table="dim_team", on=(("team_code", "team_code"),), cardinality="many_to_one"),),
    notes=(
        "The failure mode is not merely that ids move but that they return: club id 10 is Leeds, "
        "Leicester, Fulham, Ipswich, then Fulham again, so a cross-season join on team_id looks "
        "like it works and yields a Fulham history with Ipswich in the middle. Compressing 26 "
        "clubs into 20 id slots already cost 0.022 of mean log score inside the Stage A "
        "baselines.",
    ),
)

DIM_FIXTURE = Table(
    name="dim_fixture",
    role="dimension",
    subject="One scheduled or played match.",
    grain=("season", "fixture"),
    grain_note="One row per fixture per season. Fixture ids are season-scoped.",
    source_owner=(
        "fpl.transform.facts:stg_fixture + fpl.transform.facts:mart_fact_team_match + "
        "fpl.ingest.live_snapshot:stg_live_fixture_version + "
        "fpl.ingest.live_snapshot:mart_team_fixture_live"
    ),
    columns=(
        _key("season", "string", "Season."),
        _key("fixture", "int", "Season-scoped fixture id."),
        _nullable("gw", "int", "not_applicable", "Gameweek, NULL while a fixture is unscheduled."),
        _nullable(
            "kickoff_time",
            "timestamp",
            "not_applicable",
            "Scheduled kickoff (UTC), NULL until the fixture is scheduled.",
        ),
        _key("home_team_id", "int", "Season-scoped home club id."),
        _key("away_team_id", "int", "Season-scoped away club id."),
        _key("home_team_code", "int", "Permanent home club identity."),
        _key("away_team_code", "int", "Permanent away club identity."),
        _nullable(
            "home_official_fdr",
            "int",
            "unmeasured",
            "Current official difficulty for the home club; NULL where unavailable.",
        ),
        _nullable(
            "away_official_fdr",
            "int",
            "unmeasured",
            "Current official difficulty for the away club; NULL where unavailable.",
        ),
        _nullable("pulse_id", "int", "optional_attribute", "External Pulse identifier."),
        _key("finished", "bool", "Whether the fixture has been played and finalised."),
    ),
    joins=(
        Join(
            to_table="dim_gameweek",
            on=(("season", "season"), ("gw", "gw")),
            cardinality="many_to_one",
            note="Only for scheduled fixtures; gw is nullable.",
        ),
    ),
    notes=(
        "kickoff_time is event time and governs which outcomes were observable; it is not "
        "knowledge time. Schedules are themselves versioned by known_at upstream.",
    ),
)

DIM_GAMEWEEK = Table(
    name="dim_gameweek",
    role="dimension",
    subject="One gameweek within one season.",
    grain=("season", "gw"),
    grain_note=(
        "One row per observed gameweek. Never assume 1..38: 2022-23 has no GW7, so iterate "
        "observed gameweeks rather than a range."
    ),
    source_owner=(
        "fpl.transform.facts:stg_fixture + "
        "fpl.ingest.live_snapshot:stg_live_fixture_version (observed gameweeks)"
    ),
    columns=(
        _key("season", "string", "Season."),
        _key("gw", "int", "Gameweek number as published."),
        _nullable("deadline_time", "timestamp", "not_applicable", "Official entry deadline (UTC)."),
        _nullable("first_kickoff", "timestamp", "not_applicable", "Earliest kickoff."),
        _nullable("last_kickoff", "timestamp", "not_applicable", "Latest kickoff."),
        _key("fixture_count", "int", "Fixtures scheduled in the gameweek."),
        _key("finished", "bool", "Whether every fixture in the gameweek is final."),
    ),
)

# ======================================================================================
# Facts
# ======================================================================================

_FORECAST_KEYS = (
    _key("run_id", "string", "Prediction vintage this row belongs to."),
    _key("as_of", "timestamp", "Knowledge time of the vintage, denormalised for slicing."),
)

FACT_FORECAST_PLAYER_GAMEWEEK = Table(
    name="fact_forecast_player_gameweek",
    role="fact",
    subject="A player's forecast full-points distribution for one gameweek.",
    grain=("run_id", "season", "gw", "code"),
    grain_note=(
        "One row per player per gameweek per vintage. Where a gameweek contains two fixtures for "
        "a club, this row is the convolution of that player's fixture distributions."
    ),
    source_owner="fpl.storage.ledger:ledger_prediction_player_gameweek",
    forecast_scoped=True,
    columns=(
        *_FORECAST_KEYS,
        _key("season", "string", "Season."),
        _key("gw", "int", "Gameweek."),
        _key("code", "int", "Permanent player identity."),
        _key("position", "string", "Position used for this forecast."),
        _key("team_id", "int", "Season-scoped club id at the forecast cutoff."),
        _nullable("team_code", "int", "unmeasured", "Permanent club identity at the cutoff."),
        _nullable("now_cost", "int", "unmeasured", "Deadline-known price in tenths of a million."),
        _nullable("selected_by_percent", "float", "unmeasured", "Ownership at the cutoff."),
        _nullable("availability_status", "string", "unmeasured", "Reported availability code."),
        _nullable("chance_of_playing", "int", "unmeasured", "Reported next-round chance, percent."),
        _key("availability_multiplier", "float", "Reported overlay applied to expected points."),
        _key("expected_points", "float", "Mean of the modelled full-points distribution."),
        _key(
            "availability_adjusted_expected_points",
            "float",
            "expected_points scaled by the availability overlay.",
        ),
        _nullable("expected_bonus", "float", "unmeasured", "Mean bonus points."),
        _key("distribution", "string", "JSON probability vector indexed by whole points."),
        _key("cold_start_player", "bool", "The player had no usable history at the cutoff."),
        _key(
            "stage_a_league_average_team",
            "bool",
            "Own or opponent club fell back to league average.",
        ),
        _key("attacking_signal_cold_start", "bool", "The attacking signal fell back."),
        _key("assist_signal_cold_start", "bool", "The assist signal fell back."),
        _key(
            "transferred_no_rescale", "bool", "A transfer was not rescaled to the destination club."
        ),
    ),
    joins=(
        Join(to_table="dim_forecast_run", on=(("run_id", "run_id"),), cardinality="many_to_one"),
        Join(to_table="dim_player", on=(("code", "code"),), cardinality="many_to_one"),
        Join(
            to_table="dim_player_season",
            on=(("season", "season"), ("code", "code")),
            cardinality="many_to_one",
        ),
        Join(
            to_table="dim_gameweek",
            on=(("season", "season"), ("gw", "gw")),
            cardinality="many_to_one",
        ),
        Join(
            to_table="dim_team_season",
            on=(("season", "season"), ("team_id", "team_id")),
            cardinality="many_to_one",
        ),
    ),
    notes=(
        "distribution is the reason this project models distributions at all. Quantiles, "
        "P(points >= threshold) and downside risk are all derived from it; a mean alone cannot "
        "answer a captaincy or differential question.",
        "availability is a REPORTED OVERLAY, never folded into the stored distribution. To apply "
        "it to a distribution, mix it: m * distribution + (1 - m) * point mass at zero. Never "
        "multiply a quantile by the multiplier.",
        "The overlay is valid for the FIRST forecast gameweek only. Its reuse across later "
        "gameweeks is an explicit scenario assumption, never a measured per-gameweek policy.",
    ),
)

FACT_FORECAST_PLAYER_FIXTURE = Table(
    name="fact_forecast_player_fixture",
    role="fact",
    subject="A player's forecast full-points distribution for one fixture.",
    grain=("run_id", "season", "fixture", "code"),
    grain_note=(
        "One row per player per fixture per vintage. This is the natural forecast grain: double "
        "gameweeks are real, and the gameweek row is derived from these by convolution."
    ),
    source_owner="fpl.storage.ledger:ledger_prediction_player_fixture",
    forecast_scoped=True,
    columns=(
        *_FORECAST_KEYS,
        _key("season", "string", "Season."),
        _key("fixture", "int", "Season-scoped fixture id."),
        _key("code", "int", "Permanent player identity."),
        _key("gw", "int", "Gameweek the fixture belongs to, for convenience."),
        _key("team_id", "int", "Season-scoped club id the player is forecast to play for."),
        _key("opponent_team_id", "int", "Season-scoped opponent club id."),
        _key("was_home", "bool", "Whether the player's club is at home."),
        _key("expected_points", "float", "Mean of the modelled fixture full-points distribution."),
        _key("distribution", "string", "JSON probability vector indexed by whole points."),
        _nullable("expected_minutes", "float", "unmeasured", "Mean modelled minutes."),
        _nullable("probability_appears", "float", "unmeasured", "P(minutes >= 1)."),
        _nullable("probability_sixty_minutes", "float", "unmeasured", "P(minutes >= 60)."),
        _nullable("expected_goals", "float", "unmeasured", "Mean modelled goals."),
        _nullable("expected_assists", "float", "unmeasured", "Mean modelled assists."),
        _nullable("probability_clean_sheet", "float", "unmeasured", "P(team clean sheet)."),
    ),
    joins=(
        Join(to_table="dim_forecast_run", on=(("run_id", "run_id"),), cardinality="many_to_one"),
        Join(to_table="dim_player", on=(("code", "code"),), cardinality="many_to_one"),
        Join(
            to_table="dim_fixture",
            on=(("season", "season"), ("fixture", "fixture")),
            cardinality="many_to_one",
        ),
        Join(
            to_table="dim_team_season",
            on=(("season", "season"), ("team_id", "team_id")),
            cardinality="many_to_one",
        ),
    ),
    notes=(
        "P1.2 must add this transport. Do NOT reverse-engineer fixture values out of a convolved "
        "gameweek distribution: the convolution is not invertible.",
        "Each row maps to exactly one fact_forecast_player_gameweek row via "
        "(run_id, season, gw, code); that mapping is part of the transport contract.",
    ),
)

FACT_FORECAST_TEAM_FIXTURE = Table(
    name="fact_forecast_team_fixture",
    role="fact",
    subject="A club's forecast scoring and conceding rates for one fixture.",
    grain=("run_id", "season", "fixture", "team_id"),
    grain_note="Two rows per fixture per vintage, one for each club.",
    source_owner="fpl.storage.ledger:ledger_prediction_team_fixture",
    forecast_scoped=True,
    columns=(
        *_FORECAST_KEYS,
        _key("season", "string", "Season."),
        _key("fixture", "int", "Season-scoped fixture id."),
        _key("team_id", "int", "Season-scoped club id this row is about."),
        _key("team_code", "int", "Permanent club identity."),
        _key("opponent_team_id", "int", "Season-scoped opponent club id."),
        _key("gw", "int", "Gameweek the fixture belongs to."),
        _key("was_home", "bool", "Whether this club is at home."),
        _key("lambda_for", "float", "Modelled expected goals scored by this club."),
        _key("lambda_against", "float", "Modelled expected goals conceded by this club."),
        _nullable(
            "league_average_team_lambda",
            "float",
            "unmeasured",
            "Mean lambda_for over all team-fixture rows in this (run_id, season), used as the "
            "common attack/defence ease denominator only when at least two rows support it and "
            "the mean is positive. NULL means the coverage/positivity gate rejected it.",
        ),
        _nullable(
            "attack_ease_index",
            "float",
            "unmeasured",
            "100 * lambda_for / league_average_team_lambda. 100 is league average and higher "
            "means an easier/better attacking fixture for the named team; NULL when the shared "
            "denominator is unavailable.",
        ),
        _nullable(
            "defence_ease_index",
            "float",
            "unmeasured",
            "100 * league_average_team_lambda / lambda_against. 100 is league average and "
            "higher means an easier/better defensive fixture for the named team; NULL when the "
            "shared denominator is unavailable or lambda_against is zero.",
        ),
        _nullable(
            "overall_ease_index",
            "float",
            "unmeasured",
            "Geometric mean sqrt(attack_ease_index * defence_ease_index). 100 is league average "
            "and higher means easier/better overall for the named team; NULL when either "
            "directed component is unavailable.",
        ),
        _key(
            "ease_index_formula_version",
            "string",
            "Non-null formula identity for the three re-derivable publish-layer ease indices.",
        ),
        _key("probability_clean_sheet", "float", "P(this club concedes zero)."),
        _nullable(
            "official_fdr",
            "int",
            "unmeasured",
            "Official FPL schedule difficulty rating for this season-qualified fixture/team. "
            "Kept separate from and never blended into the model-derived ease indices.",
        ),
        _key(
            "stage_a_league_average_team",
            "bool",
            "Own or opponent club fell back to league average.",
        ),
    ),
    joins=(
        Join(to_table="dim_forecast_run", on=(("run_id", "run_id"),), cardinality="many_to_one"),
        Join(
            to_table="dim_fixture",
            on=(("season", "season"), ("fixture", "fixture")),
            cardinality="many_to_one",
        ),
        Join(
            to_table="dim_team_season",
            on=(("season", "season"), ("team_id", "team_id")),
            cardinality="many_to_one",
        ),
        Join(to_table="dim_team", on=(("team_code", "team_code"),), cardinality="many_to_one"),
    ),
    notes=(
        "These are the fixture-difficulty PRIMITIVES. P1.5's ease indices are derived from "
        "lambda_for and lambda_against and must be published beside them, versioned and "
        "explicitly directed, never as an undirected 'difficulty' number.",
        "The same per-(run_id, season) mean serves both directions because each club's lambda_for "
        "for a fixture equals its opponent's lambda_against. Indices are per-team-fixture only; "
        "rolling 3/5-GW aggregation belongs downstream in P1.7.",
        "Do not blend official_fdr into a model-derived index; keep them separate measures.",
        "Stage A predicts about 2.86 goals per fixture regardless of the season's actual scoring "
        "level, which moved 2.645 to 3.147 across the archive. Treat lambda as a relative "
        "fixture-difficulty signal, not a calibrated absolute rate.",
    ),
)

# Version 3 transports the exact stored team-goals PMF.  Keep the version-2 declaration above
# unchanged so readers of historical manifests can still validate their original physical shape.
FACT_FORECAST_TEAM_FIXTURE_V3 = FACT_FORECAST_TEAM_FIXTURE.model_copy(
    update={
        "columns": tuple(
            column
            for existing in FACT_FORECAST_TEAM_FIXTURE.columns
            for column in (
                existing,
                *(
                    (
                        _key(
                            "goals_for_distribution",
                            "string",
                            "Exact JSON probability vector for goals scored, indexed by whole "
                            "goals and transported unchanged from the prediction ledger.",
                        ),
                    )
                    if existing.name == "probability_clean_sheet"
                    else ()
                ),
            )
        ),
        "notes": (
            *FACT_FORECAST_TEAM_FIXTURE.notes,
            "goals_for_distribution is the recorded model distribution. Never recreate it from "
            "lambda_for; distributional monitoring must score this exact vintage.",
        ),
    }
)

FACT_PLAYER_FIXTURE_ACTUAL = Table(
    name="fact_player_fixture_actual",
    role="fact",
    subject="What a player actually did in one finalised fixture.",
    grain=("season", "fixture", "code"),
    grain_note=(
        "One row per player per fixture. Exact duplicate source rows are not real; double "
        "gameweeks are."
    ),
    source_owner="fpl.transform.facts:mart_fact_player_fixture + mart_target_player_fixture",
    columns=(
        _key("season", "string", "Season."),
        _key("fixture", "int", "Season-scoped fixture id."),
        _key("code", "int", "Permanent player identity."),
        _key("gw", "int", "Gameweek."),
        _key("kickoff_time", "timestamp", "Kickoff (UTC). Event time, not knowledge time."),
        _key("position", "string", "Position in this fixture."),
        _key("team_id", "int", "Season-scoped club the player actually played for."),
        _key("team_code", "int", "Permanent club identity for this fixture."),
        _key("opponent_team_id", "int", "Season-scoped opponent club id."),
        _key("was_home", "bool", "Whether the player's club was at home."),
        _key("minutes", "int", "Minutes played."),
        _key("starts", "int", "Whether the player started."),
        _key("goals_scored", "int", "Goals scored."),
        _key("assists", "int", "Assists."),
        _key("clean_sheets", "int", "Clean sheet credited."),
        _key("goals_conceded", "int", "Goals conceded WHILE ON THE PITCH, not the full match."),
        _key("saves", "int", "Saves made."),
        _key("penalties_saved", "int", "Penalties saved."),
        _key("penalties_missed", "int", "Penalties missed."),
        _key("own_goals", "int", "Own goals."),
        _key("yellow_cards", "int", "Yellow cards."),
        _key("red_cards", "int", "Red cards."),
        _key("bonus", "int", "Bonus points awarded."),
        _key("bps", "int", "Bonus points system score."),
        _nullable("expected_goals", "float", "unmeasured", "xG. NULL before xG coverage begins."),
        _nullable("expected_assists", "float", "unmeasured", "xA. NULL before xA coverage begins."),
        _nullable("expected_goals_conceded", "float", "unmeasured", "xGC where measured."),
        _nullable("defensive_contribution", "int", "unmeasured", "DC count where measured."),
        _nullable("threat", "float", "unmeasured", "ICT threat."),
        _nullable("creativity", "float", "unmeasured", "ICT creativity."),
        _nullable("influence", "float", "unmeasured", "ICT influence."),
        _nullable(
            "total_points_as_recorded",
            "int",
            "unknown_until_finalised",
            "Points as the game recorded them, under that season's own rules.",
        ),
        _nullable(
            "points_under_rules_2026_27",
            "int",
            "unknown_until_finalised",
            "Points replayed under the 2026/27 ruleset. A DIFFERENT measure from the recorded "
            "total; the two are never conflated or summed together.",
        ),
    ),
    joins=(
        Join(to_table="dim_player", on=(("code", "code"),), cardinality="many_to_one"),
        Join(
            to_table="dim_fixture",
            on=(("season", "season"), ("fixture", "fixture")),
            cardinality="many_to_one",
        ),
        Join(
            to_table="dim_team_season",
            on=(("season", "season"), ("team_id", "team_id")),
            cardinality="many_to_one",
        ),
        Join(to_table="dim_team", on=(("team_code", "team_code"),), cardinality="many_to_one"),
    ),
    notes=(
        "Carries NO run_id. Outcomes are attached only after a fixture is final and are joined to "
        "forecasts at read time, never merged into a prediction row.",
        "NULL xG/xA means the signal was not measured that season, not zero. 2021-22 carries no "
        "xG at all and 2022-23 only 64% coverage. Zero-filling it destroys the distinction and "
        "produces a pooled figure that measures xG's absence.",
        "goals_conceded is already an on-pitch figure. A substitute sees about 35% more of his "
        "club's conceded goals than his share of the minutes implies, so never derive on-pitch "
        "exposure from minutes.",
        "Never use total_points_as_recorded as a model feature or a cross-season target.",
    ),
)

FACT_TEAM_FIXTURE_ACTUAL = Table(
    name="fact_team_fixture_actual",
    role="fact",
    subject="What a club actually did in one finalised fixture.",
    grain=("season", "fixture", "team_id"),
    grain_note="Two reciprocal rows per finalised fixture, one for each club side.",
    source_owner=(
        "fpl.publish.export:mart_fact_team_match + mart_fact_player_fixture + "
        "mart_fact_player_fixture_live + ledger_outcome_player_fixture + "
        "ledger_outcome_team_fixture"
    ),
    columns=(
        _key("season", "string", "Season."),
        _key("fixture", "int", "Season-scoped finalised fixture id."),
        _key("team_id", "int", "Season-scoped club id this actual is about."),
        _key("team_code", "int", "Permanent club identity for this fixture."),
        _key("opponent_team_id", "int", "Season-scoped opponent club id."),
        _key("gw", "int", "Gameweek."),
        _key("kickoff_time", "timestamp", "Kickoff (UTC). Event time, not knowledge time."),
        _key("was_home", "bool", "Whether this club was the home side."),
        _key("goals_for", "int", "Official finalised goals scored by this club."),
        _key("goals_against", "int", "Official finalised goals scored by its opponent."),
        _nullable(
            "team_xg",
            "float",
            "unmeasured",
            "Source-owned aggregate of measured player xG rows for the club in this fixture; "
            "NULL where the available component rows do not support a value.",
        ),
        _nullable(
            "team_xgc",
            "float",
            "unmeasured",
            "Source-owned club xGC aggregate (MAX of measured player xGC rows); NULL where the "
            "available component rows do not support a value.",
        ),
        _nullable(
            "team_bps",
            "int",
            "unmeasured",
            "Sum of measured player BPS rows available for this club and fixture.",
        ),
        _nullable(
            "defensive_contribution",
            "int",
            "unmeasured",
            "Sum of available appeared-outfield player rows' raw defensive-contribution actions. "
            "NULL when any present applicable row is unmeasured; this is not fantasy DC points.",
        ),
    ),
    joins=(
        Join(
            to_table="dim_fixture",
            on=(("season", "season"), ("fixture", "fixture")),
            cardinality="many_to_one",
        ),
        Join(
            to_table="dim_team_season",
            on=(
                ("season", "season"),
                ("team_id", "team_id"),
                ("team_code", "team_code"),
            ),
            cardinality="many_to_one",
        ),
        Join(
            to_table="dim_team_season",
            on=(("season", "season"), ("opponent_team_id", "team_id")),
            cardinality="many_to_one",
        ),
        Join(to_table="dim_team", on=(("team_code", "team_code"),), cardinality="many_to_one"),
    ),
    notes=(
        "Carries no run_id. Archive scores come directly from mart_fact_team_match and current "
        "scores come only from the append-only finalised team-outcome ledger; never reconstruct "
        "official goals from player events because own goals make that wrong.",
        "Current-season xG, xGC, BPS, and DC are aggregated only from the deterministic latest "
        "live player components for an exact finalised team-outcome grain. The checks prove "
        "measurement/finality for every player row present in that source, but do not provide "
        "an independent witness that the source roster itself contains every appeared player.",
        "Double-gameweek legs remain separate fixture rows. NULL means unmeasured or incomplete "
        "evidence and is never zero-filled.",
        "Possession and shot counts are not present in the official FPL/archive sources and are "
        "not approximated from xG, threat, or another metric.",
    ),
)


# Reporting-only mutable observations. These are deliberately separate from the finalised actual
# facts and the append-only outcome ledger: consumers may show them with an explicit provisional
# label, but prediction monitoring must never score them.
FACT_PROVISIONAL_PLAYER_FIXTURE_OBSERVATION = FACT_PLAYER_FIXTURE_ACTUAL.model_copy(
    update={
        "name": "fact_provisional_player_fixture_observation",
        "subject": "What the live API provisionally reports for a player in one completed fixture.",
        "source_owner": (
            "fpl.publish.export:latest complete player-history snapshot capture + "
            "stg_live_fixture_version + stg_live_player_fixture_version + "
            "stg_live_team_version"
        ),
        "columns": (
            *(
                column.model_copy(
                    update={
                        "description": (
                            "Raw points currently reported by the live FPL element-summary "
                            "payload. The value remains mutable reporting evidence until "
                            "immutable final attachment."
                        )
                    }
                )
                if column.name == "total_points_as_recorded"
                else column
                for column in FACT_PLAYER_FIXTURE_ACTUAL.columns
                if column.name != "points_under_rules_2026_27"
            ),
            _key(
                "observed_at",
                "timestamp",
                "Knowledge time of the single coherent player-history capture that supplied row.",
            ),
        ),
        "notes": (
            "Carries no run_id and never enters either finalized outcome ledger.",
            "Only scored fixtures whose same-capture schedule row says "
            "finished_provisional=true or finished=true are eligible for display.",
            "A fixture remains explicitly provisional until final attachment starts. Any row in "
            "an immutable player/team outcome ledger or finalized archive fact excludes that "
            "whole fixture from both provisional facts.",
            "Every published row comes from one latest complete player-history capture per season; "
            "fixture, player, club identity, score and components are never mixed across captures.",
            "The raw recorded points are mutable reporting context, not a final target or a replay "
            "under the 2026/27 rules.",
        ),
    }
)


FACT_PROVISIONAL_TEAM_FIXTURE_OBSERVATION = FACT_TEAM_FIXTURE_ACTUAL.model_copy(
    update={
        "name": "fact_provisional_team_fixture_observation",
        "subject": "What the live API provisionally reports for a club in one completed fixture.",
        "grain_note": "Two reciprocal provisional rows per completed fixture, one per club side.",
        "source_owner": (
            "fpl.publish.export:latest complete player-history snapshot capture + "
            "stg_live_fixture_version + stg_live_player_fixture_version + "
            "stg_live_team_version"
        ),
        "columns": (
            *FACT_TEAM_FIXTURE_ACTUAL.columns,
            _key(
                "observed_at",
                "timestamp",
                "Knowledge time of the single coherent player-history capture that supplied row.",
            ),
        ),
        "notes": (
            "Carries no run_id and never enters either finalized outcome ledger.",
            "Scores come directly from the same capture's fixtures payload and are reciprocal; "
            "they remain mutable reporting evidence until immutable final attachment.",
            "The fixture remains an explicitly provisional display row even after finished=true "
            "until any immutable finalized outcome or archive actual exists; that first evidence "
            "removes both club sides and every player row together.",
            "xG, xGC, BPS and defensive contribution are same-capture player aggregates. NULL "
            "continues to mean unavailable or incomplete measurement, never zero.",
        ),
    }
)

FACT_FINALIZED_PLAYER_FIXTURE_OUTCOME = Table(
    name="fact_finalized_player_fixture_outcome",
    role="fact",
    subject="An append-only finalized player-fixture outcome eligible for forecast monitoring.",
    grain=("season", "fixture", "code"),
    grain_note=(
        "One row per finalized player-fixture outcome. It is independent of prediction vintage "
        "and joins to forecasts only at read time."
    ),
    source_owner="fpl.storage.ledger:ledger_outcome_player_fixture",
    columns=(
        _key("season", "string", "Season."),
        _key("fixture", "int", "Season-scoped finalized fixture id."),
        _key("code", "int", "Permanent player identity."),
        _key("gw", "int", "Gameweek resolved from the season-qualified fixture schedule."),
        _key("attached_at", "timestamp", "UTC time the immutable outcome was attached."),
        _nullable(
            "total_points_as_recorded",
            "int",
            "unknown_until_finalised",
            "Points recorded by FPL under that season's rules, where supplied by the finalized "
            "source. Kept distinct from replayed points.",
        ),
        _nullable(
            "points_under_rules_2026_27",
            "int",
            "unknown_until_finalised",
            "Final points replayed under the repository's 2026/27 rules. This is the monitoring "
            "target for forecasts produced under those rules.",
        ),
    ),
    joins=(
        Join(to_table="dim_player", on=(("code", "code"),), cardinality="many_to_one"),
        Join(
            to_table="dim_fixture",
            on=(("season", "season"), ("fixture", "fixture")),
            cardinality="many_to_one",
        ),
    ),
    notes=(
        "Outcome values come only from ledger_outcome_player_fixture. The fixture schedule "
        "contributes gw only; the mutable historical actual mart is not a monitoring source.",
        "Carries no run_id. A player gameweek becomes scoreable only when the gameweek is final "
        "and every forecast fixture leg has a matching finalized outcome.",
    ),
)

FACT_FINALIZED_TEAM_FIXTURE_OUTCOME = Table(
    name="fact_finalized_team_fixture_outcome",
    role="fact",
    subject="An append-only finalized club-side outcome eligible for forecast monitoring.",
    grain=("season", "fixture", "team_id"),
    grain_note="Two reciprocal rows per finalized fixture, one for each club side.",
    source_owner="fpl.storage.ledger:ledger_outcome_team_fixture",
    columns=(
        _key("season", "string", "Season."),
        _key("fixture", "int", "Season-scoped finalized fixture id."),
        _key("team_id", "int", "Season-scoped club id this outcome is about."),
        _nullable(
            "team_code",
            "int",
            "optional_attribute",
            "Permanent club identity when the finalized registry could resolve it.",
        ),
        _key("opponent_team_id", "int", "Season-scoped opponent club id."),
        _key("gw", "int", "Finalized fixture gameweek."),
        _key("kickoff_time", "timestamp", "Fixture kickoff in UTC."),
        _key("was_home", "bool", "Whether this club was the home side."),
        _key("goals_for", "int", "Official finalized goals scored by this club."),
        _key("goals_against", "int", "Official finalized goals scored by its opponent."),
        _key("attached_at", "timestamp", "UTC time the immutable outcome was attached."),
    ),
    joins=(
        Join(
            to_table="dim_fixture",
            on=(("season", "season"), ("fixture", "fixture")),
            cardinality="many_to_one",
        ),
        Join(
            to_table="dim_team_season",
            on=(("season", "season"), ("team_id", "team_id")),
            cardinality="many_to_one",
        ),
        Join(to_table="dim_team", on=(("team_code", "team_code"),), cardinality="many_to_one"),
    ),
    notes=(
        "Official fixture scores are retained directly. Never reconstruct club goals from player "
        "events because own goals make that wrong.",
        "Carries no run_id. Defensive distributional scoring uses the opponent's exact stored "
        "goals_for_distribution for the same fixture, never a PMF regenerated from lambda_against.",
    ),
)

FACT_PLAYER_FORM = Table(
    name="fact_player_form",
    role="fact",
    subject="Rolling availability and productivity windows for a player, as at a gameweek.",
    grain=("season", "gw", "code", "window"),
    grain_note=(
        "One row per player per gameweek per window. Long format rather than wide, so a pivot "
        "can put window on an axis."
    ),
    source_owner="fpl.transform.facts:mart_fact_player_form",
    columns=(
        _key("season", "string", "Season."),
        _key("gw", "int", "Gameweek the window ends at, inclusive."),
        _key("code", "int", "Permanent player identity."),
        _key("window", "string", "One of last_3, last_5, last_10, season_to_date."),
        _key("rostered_fixtures", "int", "Fixtures in the window where the player was rostered."),
        _key("appearances", "int", "Fixtures with minutes >= 1."),
        _nullable(
            "starts",
            "int",
            "unmeasured",
            "Fixtures started. NULL when any rostered fixture in the window has an unmeasured "
            "starts value (all 2021-22 source rows are unmeasured).",
        ),
        _key("did_not_play", "int", "Rostered fixtures with zero minutes."),
        _key("minutes", "int", "Total minutes."),
        _nullable("goals_scored", "int", "not_applicable", "Goals over APPEARED fixtures."),
        _nullable("assists", "int", "not_applicable", "Assists over APPEARED fixtures."),
        _nullable("bonus", "int", "not_applicable", "Bonus over APPEARED fixtures."),
        _nullable("bps", "int", "not_applicable", "BPS over APPEARED fixtures."),
        _nullable("defensive_contribution", "int", "unmeasured", "DC over appeared fixtures."),
        _nullable("expected_goals", "float", "unmeasured", "xG summed over MEASURED-xG rows only."),
        _nullable(
            "expected_assists", "float", "unmeasured", "xA summed over MEASURED-xA rows only."
        ),
        _nullable(
            "expected_goals_per_90",
            "float",
            "unmeasured",
            "90 * sum(xG) / sum(minutes on those same measured-xG rows). NULL when that "
            "denominator is zero.",
        ),
        _nullable(
            "expected_assists_per_90",
            "float",
            "unmeasured",
            "90 * sum(xA) / sum(minutes on those same measured-xA rows). NULL when that "
            "denominator is zero.",
        ),
        _nullable(
            "points_under_rules_2026_27",
            "int",
            "unknown_until_finalised",
            "Replayed points over appeared fixtures in the window.",
        ),
        _nullable(
            "clean_sheets",
            "int",
            "not_applicable",
            "Clean sheets credited over appeared fixtures. NULL when the player did not appear.",
        ),
        _nullable(
            "goals_conceded",
            "int",
            "not_applicable",
            "Goals conceded while the player was on the pitch, summed over appeared fixtures. "
            "NULL when the player did not appear.",
        ),
        _nullable(
            "saves",
            "int",
            "not_applicable",
            "Saves over appeared fixtures. NULL when the player did not appear.",
        ),
        _nullable(
            "expected_goals_conceded",
            "float",
            "unmeasured",
            "xGC summed over appeared fixtures where xGC was measured. NULL when there was no "
            "measured appeared fixture; never zero-filled.",
        ),
    ),
    joins=(
        Join(to_table="dim_player", on=(("code", "code"),), cardinality="many_to_one"),
        Join(
            to_table="dim_player_season",
            on=(("season", "season"), ("code", "code")),
            cardinality="many_to_one",
        ),
        Join(
            to_table="dim_gameweek",
            on=(("season", "season"), ("gw", "gw")),
            cardinality="many_to_one",
        ),
    ),
    notes=(
        "Availability and productivity have DIFFERENT denominators and must not be mixed. "
        "Availability counts rostered fixtures; productivity counts appeared fixtures.",
        "starts is a measured availability field, not an inference from minutes. Preserve its "
        "NULL coverage rather than turning pre-2022-23 unknown starts into zero.",
        "A per-90 rate is a display measure. Never multiply it by expected minutes in the "
        "reporting layer to synthesise a forecast; that is the model's job.",
        "Never zero-fill an unmeasured xG or xA to make a window look complete.",
        "Basic defensive counts use appeared fixtures and stay NULL when there was no appearance; "
        "xGC additionally preserves source measurement coverage.",
    ),
)

FACT_TEAM_FORM = Table(
    name="fact_team_form",
    role="fact",
    subject="Rolling recent-form windows for a club, as at a gameweek.",
    grain=("season", "gw", "team_code", "window"),
    grain_note=(
        "One row per club per observed gameweek per window. Long format, like fact_player_form, "
        "so a pivot can put window on an axis."
    ),
    source_owner="fpl.transform.facts:mart_fact_team_form",
    columns=(
        _key("season", "string", "Season."),
        _key("gw", "int", "Gameweek the window ends at, inclusive."),
        _key("team_code", "int", "Permanent club identity, 1:1 with the club."),
        _key("window", "string", "One of last_3, last_5, last_10, season_to_date."),
        _key("matches_played", "int", "Matches in the window, including double-gameweek legs."),
        _nullable(
            "goals_for",
            "int",
            "not_applicable",
            "Goals scored over the window. NULL when any match in the window has an unmeasured "
            "score.",
        ),
        _nullable(
            "goals_against",
            "int",
            "not_applicable",
            "Goals conceded over the window. NULL when any match in the window has an unmeasured "
            "score.",
        ),
        _nullable(
            "clean_sheets",
            "int",
            "not_applicable",
            "Matches with goals_against = 0. NULL when coverage is incomplete.",
        ),
        _nullable("wins", "int", "not_applicable", "Wins. NULL when coverage is incomplete."),
        _nullable("draws", "int", "not_applicable", "Draws. NULL when coverage is incomplete."),
        _nullable("losses", "int", "not_applicable", "Losses. NULL when coverage is incomplete."),
        _nullable(
            "team_xg",
            "float",
            "unmeasured",
            "xG summed over MEASURED-xG matches only. NULL for the whole of 2021-22, never 0.0.",
        ),
        _nullable(
            "team_xgc",
            "float",
            "unmeasured",
            "xGC summed over MEASURED-xGC matches only. NULL where unmeasured, never 0.0.",
        ),
        _nullable(
            "goals_for_per_match",
            "float",
            "not_applicable",
            "goals_for / matches_played. NULL on a zero denominator or incomplete coverage.",
        ),
        _nullable(
            "goals_against_per_match",
            "float",
            "not_applicable",
            "goals_against / matches_played. NULL on a zero denominator or incomplete coverage.",
        ),
        _nullable(
            "team_xg_per_match",
            "float",
            "unmeasured",
            "team_xg / count of MEASURED-xG matches (not matches_played), so partial coverage "
            "does not understate the rate. NULL when no match in the window measured xG.",
        ),
        _nullable(
            "team_xgc_per_match",
            "float",
            "unmeasured",
            "team_xgc / count of MEASURED-xGC matches (not matches_played), so partial coverage "
            "does not understate the rate. NULL when no match in the window measured xGC.",
        ),
    ),
    joins=(
        Join(to_table="dim_team", on=(("team_code", "team_code"),), cardinality="many_to_one"),
        Join(
            to_table="dim_gameweek",
            on=(("season", "season"), ("gw", "gw")),
            cardinality="many_to_one",
        ),
    ),
    notes=(
        "Backward-looking observed form only, from the historical team-match mart; a live season "
        "with no finished matches contributes zero rows. It never carries run_id.",
        "Keyed on team_code, never team_id: club ids are reassigned every season.",
        "Anchor gameweeks are observed, never an assumed 1..38. A blank gameweek creates no row "
        "and no synthetic match.",
        "A per-match rate is a display measure. Never multiply it by a fixture count to synthesise "
        "a forecast; that is the model's job.",
    ),
)


FACT_OPTIMIZER_PLAN = Table(
    name="fact_optimizer_plan",
    role="fact",
    subject="One player's role in one gameweek of an optimizer decision.",
    grain=("optimizer_run_id", "gw", "code"),
    grain_note="One row per squad member per planned gameweek per optimizer run.",
    source_owner="fpl.artifacts.optimizer_plan",
    columns=(
        _key("optimizer_run_id", "string", "Deterministic optimizer run identity."),
        _key("decision_sha256", "string", "Hash binding the complete decision content."),
        _key("forecast_run_id", "string", "Ledger vintage the plan was optimised from."),
        _key("as_of", "timestamp", "Knowledge time inherited from that vintage."),
        _key("season", "string", "Season."),
        _key("gw", "int", "Planned gameweek."),
        _key("code", "int", "Permanent player identity."),
        _key("role", "string", "starting_xi, bench_goalkeeper or bench_outfield."),
        _nullable(
            "bench_order_index", "int", "not_applicable", "Bench order, outfield bench only."
        ),
        _key("is_captain", "bool", "Whether this player wears the armband."),
        _key("is_vice_captain", "bool", "Whether this player is vice-captain."),
        _key("now_cost", "int", "Deadline-known price in tenths of a million."),
        _key("transferred_in", "bool", "Whether the player entered the squad this gameweek."),
        _key("transferred_out", "bool", "Whether the player left the squad this gameweek."),
        _key("hit_points_this_gw", "int", "Points charged for excess transfers in this gameweek."),
    ),
    joins=(
        Join(to_table="dim_player", on=(("code", "code"),), cardinality="many_to_one"),
        Join(
            to_table="dim_forecast_run",
            on=(("forecast_run_id", "run_id"),),
            cardinality="many_to_one",
        ),
        Join(
            to_table="dim_gameweek",
            on=(("season", "season"), ("gw", "gw")),
            cardinality="many_to_one",
        ),
    ),
    notes=(
        "Carries forecast_run_id, not run_id: the plan is not itself a forecast vintage, it is a "
        "decision derived from one.",
        "Every gameweek after the first uses the deadline's static price. Later-gameweek "
        "affordability is a frozen-price scenario, not a price forecast.",
        "The initial squad is exact; the transfer path is optimal only within the configured "
        "bounded search and makes no global-optimality claim.",
    ),
)


DIM_OPTIMIZER_RUN = Table(
    name="dim_optimizer_run",
    role="dimension",
    subject="One immutable optimizer decision run and the complete provenance that produced it.",
    grain=("optimizer_run_id",),
    grain_note=(
        "One row per optimizer decision artifact explicitly included in the export. The run "
        "identity binds what produced the decision; decision_sha256 binds what was decided."
    ),
    source_owner="fpl.artifacts.optimizer_plan (explicit export inputs)",
    columns=(
        _key("optimizer_run_id", "string", "Deterministic optimizer run identity."),
        _key("decision_sha256", "string", "Hash binding the complete decision content."),
        _key("forecast_run_id", "string", "Ledger vintage the plan was optimised from."),
        _key("as_of", "timestamp", "Knowledge time inherited from that vintage."),
        _key("season", "string", "Season."),
        _key("gw_from", "int", "First planned gameweek."),
        _key("gw_to", "int", "Last planned gameweek."),
        _key("optimizer_commit_sha", "string", "Git HEAD that produced the plan."),
        _key("optimizer_worktree_clean", "bool", "The plan refused a dirty worktree; always true."),
        _key("forecast_artifact_sha256", "string", "SHA-256 of the input forecast JSONL artifact."),
        _key("forecast_commit_sha", "string", "Git HEAD that produced the input forecast."),
        _key("squad_rules_path", "string", "Squad-rule configuration file this plan obeyed."),
        _key("squad_rules_contract_version", "string", "Contract version of the squad rules."),
        _key("squad_rules_sha256", "string", "SHA-256 of the squad-rule configuration file."),
        _key("solver_name", "string", "Solver name."),
        _key("solver_package", "string", "Solver package (e.g. the modelling library)."),
        _key("solver_package_version", "string", "Solver package version."),
        _key("solver_binary_version", "string", "Solver binary version."),
        _key("solver_options", "string", "JSON array of the solver's deterministic options."),
        _key("solver_seed", "int", "Deterministic seed."),
        _key("solver_status", "string", "Solver termination status."),
        _key("search_method", "string", "Declared search method."),
        _key("optimality_scope", "string", "Declared optimality scope of the search."),
        _key("risk_lambda", "float", "Risk-aversion lambda; 0.0 is pure EV."),
        _key(
            "search_policy",
            "string",
            "JSON: the complete bounded-search policy (pool, depth, transitions, beam, free "
            "transfers, hit cost, transfer caps).",
        ),
        _key(
            "rules_snapshot",
            "string",
            "JSON: the verified squad-rule snapshot (squad size, budget, club cap, position "
            "rules, lineup size, captain multiplier, bench slots).",
        ),
        _key("assumptions", "string", "JSON array of the plan's explicit modelling assumptions."),
        _key(
            "status",
            "string",
            "Explicit development-only status; never a validated production recommendation.",
        ),
    ),
    joins=(
        Join(
            to_table="dim_forecast_run",
            on=(("forecast_run_id", "run_id"),),
            cardinality="many_to_one",
        ),
    ),
    notes=(
        "Sourced only from optimizer decision artifacts passed explicitly to the export; a "
        "database alone contributes no optimizer rows. No plans passed, no rows published.",
        "The three JSON columns are deterministic (sorted keys) so identical decisions emit "
        "byte-identical values.",
        "The join to dim_forecast_run is many_to_one on forecast_run_id: a vintage can back "
        "several plans (default and diagnostic architectures), never the reverse.",
    ),
)

SEMANTIC_CONTRACT_V2 = SemanticContract(
    version=2,
    tables=(
        DIM_FORECAST_RUN,
        DIM_PLAYER,
        DIM_PLAYER_SEASON,
        DIM_PLAYER_STINT,
        DIM_TEAM,
        DIM_TEAM_SEASON,
        DIM_FIXTURE,
        DIM_GAMEWEEK,
        FACT_FORECAST_PLAYER_GAMEWEEK,
        FACT_FORECAST_PLAYER_FIXTURE,
        FACT_FORECAST_TEAM_FIXTURE,
        FACT_PLAYER_FIXTURE_ACTUAL,
        FACT_PLAYER_FORM,
        FACT_TEAM_FORM,
        FACT_OPTIMIZER_PLAN,
        DIM_OPTIMIZER_RUN,
    ),
)

SEMANTIC_CONTRACT_V3 = SemanticContract(
    version=3,
    tables=(
        *(
            FACT_FORECAST_TEAM_FIXTURE_V3 if table.name == "fact_forecast_team_fixture" else table
            for table in SEMANTIC_CONTRACT_V2.tables
        ),
        FACT_FINALIZED_PLAYER_FIXTURE_OUTCOME,
        FACT_FINALIZED_TEAM_FIXTURE_OUTCOME,
    ),
)

# Version 4 keeps the v3 physical table shape and changes the ownership/completeness contract for
# the observed player-fixture fact. Historical rows still come from the immutable archive marts;
# current-season component rows may also come from the latest versioned live capture, but only when
# the append-only finalized outcome ledger carries the exact same season-qualified grain. The
# ledger owns both points measures for those live rows.
FACT_PLAYER_FIXTURE_ACTUAL_V4 = FACT_PLAYER_FIXTURE_ACTUAL.model_copy(
    update={
        "source_owner": (
            "fpl.publish.export:mart_fact_player_fixture + mart_target_player_fixture + "
            "mart_fact_player_fixture_live + ledger_outcome_player_fixture"
        ),
        "notes": (
            *FACT_PLAYER_FIXTURE_ACTUAL.notes,
            "Current-season live components are published only from the deterministic latest "
            "(known_at, capture_id) version at (season, fixture, code), and only when an exact "
            "append-only ledger_outcome_player_fixture row exists. For those rows the ledger "
            "owns recorded and replayed points; a live capture alone is not finality evidence.",
            "Archive and eligible live sources must never overlap at (season, fixture, code). "
            "The exporter fails closed instead of choosing one source or double counting.",
        ),
    }
)

SEMANTIC_CONTRACT_V4 = SemanticContract(
    version=4,
    tables=tuple(
        FACT_PLAYER_FIXTURE_ACTUAL_V4
        if table.name == "fact_player_fixture_actual"
        else table
        for table in SEMANTIC_CONTRACT_V3.tables
    ),
)

SEMANTIC_CONTRACT_V5 = SemanticContract(
    version=5,
    tables=(*SEMANTIC_CONTRACT_V4.tables, FACT_TEAM_FIXTURE_ACTUAL),
)


SEMANTIC_CONTRACT_V6 = SemanticContract(
    version=SEMANTIC_CONTRACT_VERSION,
    tables=(
        *SEMANTIC_CONTRACT_V5.tables,
        FACT_PROVISIONAL_PLAYER_FIXTURE_OBSERVATION,
        FACT_PROVISIONAL_TEAM_FIXTURE_OBSERVATION,
    ),
)

# The executable v1 declaration remains importable for readers of historical manifests. Its only
# structural difference from v2 is that dim_fixture predates current directed schedule FDR.
_DIM_FIXTURE_V1 = DIM_FIXTURE.model_copy(
    update={
        "source_owner": (
            "fpl.transform.facts:stg_fixture + fpl.ingest.live_snapshot:stg_live_fixture_version"
        ),
        "columns": tuple(
            column
            for column in DIM_FIXTURE.columns
            if column.name not in {"home_official_fdr", "away_official_fdr"}
        ),
    }
)
SEMANTIC_CONTRACT_V1 = SemanticContract(
    version=1,
    tables=tuple(
        _DIM_FIXTURE_V1 if table.name == "dim_fixture" else table
        for table in SEMANTIC_CONTRACT_V2.tables
    ),
)

#: Every table in the current semantic contract has a concrete source owner. The exporter can
#: therefore reject a genuinely partial contract rather than silently treating a table as optional.
NOT_YET_SOURCED: frozenset[str] = frozenset()


__all__ = [
    "CROSS_SEASON_KEYS",
    "NOT_YET_SOURCED",
    "SEASON_SCOPED_KEYS",
    "SEMANTIC_CONTRACT_V1",
    "SEMANTIC_CONTRACT_V2",
    "SEMANTIC_CONTRACT_V3",
    "SEMANTIC_CONTRACT_V4",
    "SEMANTIC_CONTRACT_V5",
    "SEMANTIC_CONTRACT_V6",
    "SEMANTIC_CONTRACT_VERSION",
    "Column",
    "Join",
    "NullMeaning",
    "SemanticContract",
    "SemanticContractError",
    "Table",
]
