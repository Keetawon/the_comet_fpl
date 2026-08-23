"""Stable artifact contract for prospective player-gameweek points distributions.

The forecaster operates at player-fixture grain because double gameweeks are real. Squad
planning operates at player-gameweek grain, so this module is the explicit boundary between the
two: fixture distributions are convolved in sorted fixture order and a zero-fixture gameweek is
represented by the exact point mass ``(1.0,)``. Availability remains metadata beside the raw
distribution; it is never folded into the stored probabilities.

The JSON Lines format has one manifest followed by exactly one forecast row per
``(season, gw, code)``. JSONL is intentionally preferred to Parquet here: nested probability
vectors and nullable live fields are native JSON values, canonical serialisation is
bit-reproducible and diffable, and the standard library is sufficient. The single-file scale is
small enough that columnar compression would not justify a more opaque contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ARTIFACT_SCHEMA = "fpl.prospective-points"
ARTIFACT_SCHEMA_VERSION = 1
ARTIFACT_STATUS = "development_only_not_a_validated_production_forecast"


def _validate_sha256(value: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
    return value


class ArtifactError(ValueError):
    """The artifact is malformed, internally inconsistent, or unsafe to consume."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class ContractIdentity(_Frozen):
    """One configuration contract consumed by the forecast."""

    name: str
    version: str
    sha256: str

    @field_validator("sha256")
    @classmethod
    def _valid_sha256(cls, value: str) -> str:
        return _validate_sha256(value)


class LiveInputProvenance(_Frozen):
    """The versioned live captures visible at the forecast cutoff."""

    bootstrap_capture_id: str
    bootstrap_known_at: datetime
    bootstrap_payload_sha256: str
    schedule_capture_ids: tuple[str, ...]
    selectable_player_registry_sha256: str | None = None

    @field_validator("bootstrap_payload_sha256", "selectable_player_registry_sha256")
    @classmethod
    def _valid_sha256(cls, value: str | None) -> str | None:
        return None if value is None else _validate_sha256(value)

    @field_validator("schedule_capture_ids")
    @classmethod
    def _sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("schedule_capture_ids must be sorted and unique")
        return value


class ForecastArtifactManifest(_Frozen):
    """The global contract and provenance record at line one."""

    record_type: Literal["manifest"] = "manifest"
    artifact_schema: Literal["fpl.prospective-points"] = Field(
        default="fpl.prospective-points", alias="schema"
    )
    # The manifest declares what the file actually contains, so the default is the version that
    # carries no fixture-grain rows. A producer emitting fixture rows opts into version 2 and must
    # state both counts; supplying rows under version 1 fails closed in _validate_fixture_grain.
    schema_version: Literal[1, 2] = 1
    status: Literal["development_only_not_a_validated_production_forecast"] = (
        "development_only_not_a_validated_production_forecast"
    )
    as_of: datetime
    season: str
    gw_from: int = Field(ge=1)
    gw_to: int = Field(ge=1)
    row_count: int = Field(ge=0)
    #: Fixture-grain row counts. ``None`` on a schema-version-1 artifact, which carried no
    #: fixture rows at all; required from version 2 so a truncated file cannot read as complete.
    player_fixture_row_count: int | None = Field(default=None, ge=0)
    team_fixture_row_count: int | None = Field(default=None, ge=0)
    roster_size: int = Field(ge=0)
    fixture_count: int = Field(ge=0)
    monte_carlo_draws: int = Field(gt=0)
    base_seed: int
    fixture_points_support_max: int = Field(ge=0)
    freshness_cold_start: bool
    worktree_clean: Literal[True] = True
    commit_sha: str
    database_sha256: str
    contracts: dict[str, ContractIdentity]
    component_modes: dict[str, str]
    live_inputs: LiveInputProvenance

    @model_validator(mode="after")
    def _consistent_horizon(self) -> Self:
        if self.gw_to < self.gw_from:
            raise ValueError("gw_to must be >= gw_from")
        expected = self.roster_size * (self.gw_to - self.gw_from + 1)
        if self.row_count != expected:
            raise ValueError(f"row_count {self.row_count} does not equal roster*horizon {expected}")
        if not self.commit_sha:
            raise ValueError("commit_sha is required")
        _validate_sha256(self.database_sha256)
        fixture_counts = (self.player_fixture_row_count, self.team_fixture_row_count)
        if self.schema_version == 1:
            if any(count is not None for count in fixture_counts):
                raise ValueError("schema version 1 carries no fixture-grain rows")
        elif any(count is None for count in fixture_counts):
            raise ValueError(
                "schema version 2 must declare player_fixture_row_count and team_fixture_row_count"
            )
        return self


class ForecastArtifactRow(_Frozen):
    """One full points distribution for a stable player identity in one gameweek."""

    record_type: Literal["forecast"] = "forecast"
    season: str
    gw: int = Field(ge=1)
    code: int = Field(gt=0)
    web_name: str | None
    position: Literal["GK", "DEF", "MID", "FWD"]
    team_id: int = Field(gt=0)
    team_code: int | None
    now_cost: int | None = Field(default=None, ge=0)
    selected_by_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    availability_status: str
    chance_of_playing: float | None = Field(default=None, ge=0.0, le=100.0)
    availability_multiplier: float = Field(ge=0.0, le=1.0)
    fixture_ids: tuple[int, ...]
    kickoff_times: tuple[datetime, ...]
    expected_points: float = Field(ge=0.0)
    availability_adjusted_expected_points: float = Field(ge=0.0)
    expected_bonus: float = Field(ge=0.0)
    distribution: tuple[float, ...]
    cold_start_player: bool
    stage_a_league_average_team: bool
    attacking_signal_cold_start: bool
    assist_signal_cold_start: bool
    transferred_no_rescale: bool

    @field_validator("fixture_ids")
    @classmethod
    def _fixture_order(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("fixture_ids must be sorted and unique")
        return value

    @field_validator("distribution")
    @classmethod
    def _valid_distribution(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if not value:
            raise ValueError("distribution must not be empty")
        if any(not math.isfinite(mass) or mass < 0.0 for mass in value):
            raise ValueError("distribution masses must be finite and non-negative")
        if not math.isclose(sum(value), 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(f"distribution sums to {sum(value)!r}, expected 1")
        return value

    @model_validator(mode="after")
    def _reconciles(self) -> Self:
        if len(self.fixture_ids) != len(self.kickoff_times):
            raise ValueError("fixture_ids and kickoff_times must have equal lengths")
        expected = sum(index * mass for index, mass in enumerate(self.distribution))
        if not math.isclose(self.expected_points, expected, rel_tol=0.0, abs_tol=1e-10):
            raise ValueError(
                f"expected_points {self.expected_points!r} does not match distribution {expected!r}"
            )
        adjusted = self.availability_multiplier * self.expected_points
        if not math.isclose(
            self.availability_adjusted_expected_points,
            adjusted,
            rel_tol=0.0,
            abs_tol=1e-10,
        ):
            raise ValueError("availability-adjusted expectation does not match overlay multiplier")
        return self


def _validated_distribution(value: tuple[float, ...]) -> tuple[float, ...]:
    if not value:
        raise ValueError("distribution must not be empty")
    if any(not math.isfinite(mass) or mass < 0.0 for mass in value):
        raise ValueError("distribution masses must be finite and non-negative")
    if not math.isclose(sum(value), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"distribution sums to {sum(value)!r}, expected 1")
    return value


class ForecastPlayerFixtureRow(_Frozen):
    """One full-points distribution for a player in ONE fixture.

    This is the grain the composer actually works at; the gameweek row is derived from these by
    convolution. Double gameweeks are real, so a player may have more than one of these per
    gameweek, and the convolution is not invertible -- which is why the fixture rows are
    transported rather than reconstructed.
    """

    record_type: Literal["player_fixture"] = "player_fixture"
    season: str
    gw: int = Field(ge=1)
    fixture: int = Field(gt=0)
    code: int = Field(gt=0)
    kickoff_time: datetime
    position: Literal["GK", "DEF", "MID", "FWD"]
    team_id: int = Field(gt=0)
    team_code: int | None
    opponent_team_id: int = Field(gt=0)
    was_home: bool
    expected_points: float = Field(ge=0.0)
    expected_bonus: float = Field(ge=0.0)
    distribution: tuple[float, ...]
    stage_a_league_average_team: bool

    @field_validator("distribution")
    @classmethod
    def _valid_distribution(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        return _validated_distribution(value)

    @model_validator(mode="after")
    def _reconciles(self) -> Self:
        expected = sum(index * mass for index, mass in enumerate(self.distribution))
        if not math.isclose(self.expected_points, expected, rel_tol=0.0, abs_tol=1e-10):
            raise ValueError(
                f"expected_points {self.expected_points!r} does not match its distribution "
                f"{expected!r}"
            )
        if self.team_id == self.opponent_team_id:
            raise ValueError("a fixture cannot have the same team on both sides")
        return self


class ForecastTeamFixtureRow(_Frozen):
    """One club's modelled scoring and conceding for one fixture.

    Two rows exist per fixture, one per club. These are the fixture-difficulty PRIMITIVES: any
    published ease index is derived from ``lambda_for`` and ``lambda_against`` and must be shown
    beside them with an explicit direction.
    """

    record_type: Literal["team_fixture"] = "team_fixture"
    season: str
    gw: int = Field(ge=1)
    fixture: int = Field(gt=0)
    kickoff_time: datetime
    team_id: int = Field(gt=0)
    team_code: int | None
    opponent_team_id: int = Field(gt=0)
    was_home: bool
    lambda_for: float = Field(ge=0.0)
    lambda_against: float = Field(ge=0.0)
    probability_clean_sheet: float = Field(ge=0.0, le=1.0)
    goals_for_distribution: tuple[float, ...]
    stage_a_league_average_team: bool

    @field_validator("goals_for_distribution")
    @classmethod
    def _valid_distribution(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        return _validated_distribution(value)

    @model_validator(mode="after")
    def _reconciles(self) -> Self:
        for name, value in (
            ("lambda_for", self.lambda_for),
            ("lambda_against", self.lambda_against),
            ("probability_clean_sheet", self.probability_clean_sheet),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        expected = sum(index * mass for index, mass in enumerate(self.goals_for_distribution))
        if not math.isclose(self.lambda_for, expected, rel_tol=0.0, abs_tol=1e-10):
            raise ValueError(
                f"lambda_for {self.lambda_for!r} does not match its goals distribution {expected!r}"
            )
        if self.team_id == self.opponent_team_id:
            raise ValueError("a fixture cannot have the same team on both sides")
        return self


@dataclass(frozen=True, slots=True)
class ArtifactPlayerInput:
    """Deadline-known registry metadata for one stable player ``code``."""

    code: int
    web_name: str | None
    position: Literal["GK", "DEF", "MID", "FWD"]
    team_id: int
    team_code: int | None
    now_cost: int | None
    selected_by_percent: float | None
    availability_status: str
    chance_of_playing: float | None
    availability_multiplier: float
    cold_start_player: bool
    attacking_signal_cold_start: bool
    assist_signal_cold_start: bool
    transferred_no_rescale: bool


@dataclass(frozen=True, slots=True)
class ArtifactFixtureInput:
    """One raw player-fixture distribution emitted by the composer."""

    season: str
    gw: int
    fixture: int
    kickoff_time: datetime
    code: int
    expected_bonus: float
    distribution: tuple[float, ...]
    stage_a_league_average_team: bool


@dataclass(frozen=True, slots=True)
class ProspectivePointsArtifact:
    """One forecast vintage at three grains.

    ``rows`` is the player-gameweek population every existing consumer reads and is unchanged.
    ``player_fixture_rows`` and ``team_fixture_rows`` are the schema-version-2 fixture-grain
    transport; both are empty on a version-1 artifact.
    """

    manifest: ForecastArtifactManifest
    rows: tuple[ForecastArtifactRow, ...]
    player_fixture_rows: tuple[ForecastPlayerFixtureRow, ...] = ()
    team_fixture_rows: tuple[ForecastTeamFixtureRow, ...] = ()


def _convolve(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    out = [0.0] * (len(left) + len(right) - 1)
    for left_index, left_mass in enumerate(left):
        for right_index, right_mass in enumerate(right):
            out[left_index + right_index] += left_mass * right_mass
    return tuple(out)


def build_artifact_rows(
    *,
    season: str,
    gw_from: int,
    gw_to: int,
    players: tuple[ArtifactPlayerInput, ...],
    fixtures: tuple[ArtifactFixtureInput, ...],
) -> tuple[ForecastArtifactRow, ...]:
    """Aggregate fixture predictions into a complete roster-by-gameweek artifact population."""
    if gw_to < gw_from:
        raise ArtifactError("gw_to must be >= gw_from")
    players_by_code = {player.code: player for player in players}
    if len(players_by_code) != len(players):
        raise ArtifactError("player metadata contains duplicate stable code values")

    grouped: dict[tuple[int, int], list[ArtifactFixtureInput]] = {}
    seen_fixture_keys: set[tuple[int, int]] = set()
    for fixture in fixtures:
        if fixture.season != season or not gw_from <= fixture.gw <= gw_to:
            raise ArtifactError("fixture input falls outside the artifact season/horizon")
        if fixture.code not in players_by_code:
            raise ArtifactError(f"fixture input code {fixture.code} is absent from the roster")
        fixture_key = (fixture.fixture, fixture.code)
        if fixture_key in seen_fixture_keys:
            raise ArtifactError(f"duplicate player-fixture input {fixture_key}")
        seen_fixture_keys.add(fixture_key)
        grouped.setdefault((fixture.gw, fixture.code), []).append(fixture)

    rows: list[ForecastArtifactRow] = []
    for gw in range(gw_from, gw_to + 1):
        for code in sorted(players_by_code):
            player = players_by_code[code]
            cells = sorted(grouped.get((gw, code), ()), key=lambda cell: cell.fixture)
            distribution: tuple[float, ...] = (1.0,)
            expected_bonus = 0.0
            for cell in cells:
                distribution = _convolve(distribution, cell.distribution)
                expected_bonus += cell.expected_bonus
            expected = sum(index * mass for index, mass in enumerate(distribution))
            rows.append(
                ForecastArtifactRow(
                    season=season,
                    gw=gw,
                    code=code,
                    web_name=player.web_name,
                    position=player.position,
                    team_id=player.team_id,
                    team_code=player.team_code,
                    now_cost=player.now_cost,
                    selected_by_percent=player.selected_by_percent,
                    availability_status=player.availability_status,
                    chance_of_playing=player.chance_of_playing,
                    availability_multiplier=player.availability_multiplier,
                    fixture_ids=tuple(cell.fixture for cell in cells),
                    kickoff_times=tuple(cell.kickoff_time for cell in cells),
                    expected_points=expected,
                    availability_adjusted_expected_points=player.availability_multiplier * expected,
                    expected_bonus=expected_bonus,
                    distribution=distribution,
                    cold_start_player=player.cold_start_player,
                    stage_a_league_average_team=any(
                        cell.stage_a_league_average_team for cell in cells
                    ),
                    attacking_signal_cold_start=player.attacking_signal_cold_start,
                    assist_signal_cold_start=player.assist_signal_cold_start,
                    transferred_no_rescale=player.transferred_no_rescale,
                )
            )
    return tuple(rows)


def _json_line(model: BaseModel) -> str:
    payload = model.model_dump(mode="json", by_alias=True)
    if (
        isinstance(model, ForecastArtifactManifest)
        and model.live_inputs.selectable_player_registry_sha256 is None
    ):
        # Preserve canonical bytes for artifacts written before the additive registry binding.
        payload["live_inputs"].pop("selectable_player_registry_sha256", None)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def artifact_bytes(artifact: ProspectivePointsArtifact) -> bytes:
    """Canonical UTF-8 representation, suitable for bit-for-bit reproducibility checks."""
    _validate_artifact(artifact)
    lines = [
        _json_line(artifact.manifest),
        *(_json_line(row) for row in artifact.rows),
        *(_json_line(row) for row in artifact.player_fixture_rows),
        *(_json_line(row) for row in artifact.team_fixture_rows),
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_artifact_atomic(path: Path, artifact: ProspectivePointsArtifact) -> str:
    """Atomically replace ``path`` and return the SHA-256 of the exact bytes written."""
    payload = artifact_bytes(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()


def read_artifact_bytes(payload: bytes) -> ProspectivePointsArtifact:
    """Parse and fully validate exact JSONL bytes without any database access.

    Keeping this byte-oriented entry point public lets provenance-sensitive consumers hash and
    parse one immutable in-memory snapshot instead of reading a path once for content and again for
    its identity.
    """
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArtifactError("artifact is not valid UTF-8") from exc
    lines = text.splitlines()
    if not lines:
        raise ArtifactError("artifact is empty")
    try:
        manifest = ForecastArtifactManifest.model_validate_json(lines[0])
        rows: list[ForecastArtifactRow] = []
        player_fixture_rows: list[ForecastPlayerFixtureRow] = []
        team_fixture_rows: list[ForecastTeamFixtureRow] = []
        for line in lines[1:]:
            # Dispatch on the row's own discriminator rather than on position, so a version-1
            # artifact (forecast rows only) and a version-2 one parse through the same path.
            record_type = json.loads(line).get("record_type")
            if record_type == "forecast":
                rows.append(ForecastArtifactRow.model_validate_json(line))
            elif record_type == "player_fixture":
                player_fixture_rows.append(ForecastPlayerFixtureRow.model_validate_json(line))
            elif record_type == "team_fixture":
                team_fixture_rows.append(ForecastTeamFixtureRow.model_validate_json(line))
            else:
                raise ArtifactError(f"unknown artifact record_type {record_type!r}")
    except ArtifactError:
        raise
    except ValueError as exc:
        raise ArtifactError(f"invalid prospective points artifact: {exc}") from exc
    artifact = ProspectivePointsArtifact(
        manifest=manifest,
        rows=tuple(rows),
        player_fixture_rows=tuple(player_fixture_rows),
        team_fixture_rows=tuple(team_fixture_rows),
    )
    _validate_artifact(artifact)
    return artifact


def read_artifact(path: Path) -> ProspectivePointsArtifact:
    """Parse and fully validate a JSONL artifact without any database access."""
    return read_artifact_bytes(path.read_bytes())


def _validate_artifact(artifact: ProspectivePointsArtifact) -> None:
    manifest = artifact.manifest
    if len(artifact.rows) != manifest.row_count:
        raise ArtifactError(
            f"manifest row_count={manifest.row_count}, actual rows={len(artifact.rows)}"
        )
    keys = tuple((row.season, row.gw, row.code) for row in artifact.rows)
    if keys != tuple(sorted(keys)):
        raise ArtifactError("forecast rows must use canonical (season, gw, code) order")
    if len(set(keys)) != len(keys):
        raise ArtifactError("forecast artifact has duplicate (season, gw, code) keys")
    for row in artifact.rows:
        if row.season != manifest.season or not manifest.gw_from <= row.gw <= manifest.gw_to:
            raise ArtifactError("forecast row is outside the manifest season/horizon")
    _validate_fixture_grain(artifact)


def _validate_fixture_grain(artifact: ProspectivePointsArtifact) -> None:
    """Check the fixture-grain transport and its exact mapping to the gameweek rows."""
    manifest = artifact.manifest
    if manifest.schema_version == 1:
        if artifact.player_fixture_rows or artifact.team_fixture_rows:
            raise ArtifactError("schema version 1 cannot carry fixture-grain rows")
        return

    if len(artifact.player_fixture_rows) != manifest.player_fixture_row_count:
        raise ArtifactError(
            f"manifest player_fixture_row_count={manifest.player_fixture_row_count}, actual "
            f"{len(artifact.player_fixture_rows)}"
        )
    if len(artifact.team_fixture_rows) != manifest.team_fixture_row_count:
        raise ArtifactError(
            f"manifest team_fixture_row_count={manifest.team_fixture_row_count}, actual "
            f"{len(artifact.team_fixture_rows)}"
        )

    player_keys = tuple((row.season, row.fixture, row.code) for row in artifact.player_fixture_rows)
    if player_keys != tuple(sorted(player_keys)):
        raise ArtifactError("player-fixture rows must use canonical (season, fixture, code) order")
    if len(set(player_keys)) != len(player_keys):
        raise ArtifactError("player-fixture rows have duplicate (season, fixture, code) keys")

    team_keys = tuple((row.season, row.fixture, row.team_id) for row in artifact.team_fixture_rows)
    if team_keys != tuple(sorted(team_keys)):
        raise ArtifactError("team-fixture rows must use canonical (season, fixture, team_id) order")
    if len(set(team_keys)) != len(team_keys):
        raise ArtifactError("team-fixture rows have duplicate (season, fixture, team_id) keys")

    for row in artifact.player_fixture_rows:
        if row.season != manifest.season or not manifest.gw_from <= row.gw <= manifest.gw_to:
            raise ArtifactError("player-fixture row is outside the manifest season/horizon")
    sides: dict[int, set[int]] = {}
    for team_row in artifact.team_fixture_rows:
        if team_row.season != manifest.season or not (
            manifest.gw_from <= team_row.gw <= manifest.gw_to
        ):
            raise ArtifactError("team-fixture row is outside the manifest season/horizon")
        sides.setdefault(team_row.fixture, set()).add(team_row.team_id)
    for fixture, team_ids in sides.items():
        if len(team_ids) != 2:
            raise ArtifactError(
                f"fixture {fixture} has {len(team_ids)} team-fixture row(s); a fixture has two "
                "sides and both must be published"
            )

    _validate_fixture_to_gameweek_mapping(artifact)


def _validate_fixture_to_gameweek_mapping(artifact: ProspectivePointsArtifact) -> None:
    """Prove each gameweek row IS the convolution of its own player-fixture rows.

    This is the invariant the fixture-grain transport exists to guarantee. Without it the two
    grains could drift silently and a consumer could not tell which one was wrong; with it, the
    gameweek row is demonstrably derived rather than separately asserted.
    """
    grouped: dict[tuple[int, int], list[ForecastPlayerFixtureRow]] = {}
    for row in artifact.player_fixture_rows:
        grouped.setdefault((row.gw, row.code), []).append(row)

    by_key = {(row.gw, row.code): row for row in artifact.rows}
    for (gw, code), cells in grouped.items():
        gameweek_row = by_key.get((gw, code))
        if gameweek_row is None:
            raise ArtifactError(
                f"player-fixture row (gw={gw}, code={code}) has no player-gameweek row"
            )
        cells.sort(key=lambda cell: cell.fixture)
        if gameweek_row.fixture_ids != tuple(cell.fixture for cell in cells):
            raise ArtifactError(
                f"player-gameweek row (gw={gw}, code={code}) names fixtures "
                f"{gameweek_row.fixture_ids} but carries {tuple(c.fixture for c in cells)}"
            )
        if gameweek_row.kickoff_times != tuple(cell.kickoff_time for cell in cells):
            raise ArtifactError(f"kickoff times disagree for (gw={gw}, code={code})")

        distribution: tuple[float, ...] = (1.0,)
        expected_bonus = 0.0
        for cell in cells:
            distribution = _convolve(distribution, cell.distribution)
            expected_bonus += cell.expected_bonus
        expected_points = sum(index * mass for index, mass in enumerate(distribution))
        if not math.isclose(
            gameweek_row.expected_points, expected_points, rel_tol=0.0, abs_tol=1e-9
        ):
            raise ArtifactError(
                f"player-gameweek row (gw={gw}, code={code}) expects "
                f"{gameweek_row.expected_points!r} but its fixture rows convolve to "
                f"{expected_points!r}"
            )
        if not math.isclose(gameweek_row.expected_bonus, expected_bonus, rel_tol=0.0, abs_tol=1e-9):
            raise ArtifactError(f"expected bonus disagrees for (gw={gw}, code={code})")
        if len(distribution) != len(gameweek_row.distribution) or any(
            not math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
            for left, right in zip(gameweek_row.distribution, distribution, strict=True)
        ):
            raise ArtifactError(
                f"player-gameweek distribution for (gw={gw}, code={code}) is not the convolution "
                "of its player-fixture distributions"
            )
        if gameweek_row.stage_a_league_average_team != any(
            cell.stage_a_league_average_team for cell in cells
        ):
            raise ArtifactError(f"stage_a fallback flag disagrees for (gw={gw}, code={code})")

    # A gameweek row with no fixture rows must be a genuine blank (the player has no fixture).
    for gameweek_row in artifact.rows:
        if (gameweek_row.gw, gameweek_row.code) in grouped:
            continue
        if gameweek_row.fixture_ids:
            raise ArtifactError(
                f"player-gameweek row (gw={gameweek_row.gw}, code={gameweek_row.code}) names "
                f"fixtures {gameweek_row.fixture_ids} but has no player-fixture rows"
            )
