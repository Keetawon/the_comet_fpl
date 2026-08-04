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

    @field_validator("bootstrap_payload_sha256")
    @classmethod
    def _valid_sha256(cls, value: str) -> str:
        return _validate_sha256(value)

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
    schema_version: Literal[1] = 1
    status: Literal["development_only_not_a_validated_production_forecast"] = (
        "development_only_not_a_validated_production_forecast"
    )
    as_of: datetime
    season: str
    gw_from: int = Field(ge=1)
    gw_to: int = Field(ge=1)
    row_count: int = Field(ge=0)
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
    manifest: ForecastArtifactManifest
    rows: tuple[ForecastArtifactRow, ...]


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
    return json.dumps(
        model.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def artifact_bytes(artifact: ProspectivePointsArtifact) -> bytes:
    """Canonical UTF-8 representation, suitable for bit-for-bit reproducibility checks."""
    _validate_artifact(artifact)
    lines = [_json_line(artifact.manifest), *(_json_line(row) for row in artifact.rows)]
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


def read_artifact(path: Path) -> ProspectivePointsArtifact:
    """Parse and fully validate a JSONL artifact without any database access."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ArtifactError("artifact is empty")
    try:
        manifest = ForecastArtifactManifest.model_validate_json(lines[0])
        rows = tuple(ForecastArtifactRow.model_validate_json(line) for line in lines[1:])
    except ValueError as exc:
        raise ArtifactError(f"invalid prospective points artifact: {exc}") from exc
    artifact = ProspectivePointsArtifact(manifest=manifest, rows=rows)
    _validate_artifact(artifact)
    return artifact


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
