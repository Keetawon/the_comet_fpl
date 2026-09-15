"""Additive SDP prospective-evidence pair registry, over the append-only prediction ledger.

The SDP-backed V2 architecture is the primary football environment by owner direction
(2026-09-07); frozen historical experimental verdicts remain unchanged. Each prospective
default run publishes a primary artifact (SDP football environment active) and an
incumbent shadow artifact with the environment disabled. This module binds those two
vintages as ONE pre-deadline comparison pair and, when the ledger does not yet hold them,
inserts both vintages atomically in the same transaction as the pair.

Strictly additive; every failure is a refusal, never a repair:

* ``ledger_sdp_evidence_pair`` -- one row per pair; ``prediction_id`` is a deterministic
  hash of the pair identity, so identical repeats are recognised, never duplicated.
* ``created_at`` is the ACTUAL record entry instant (``datetime.now(UTC)``; there is no
  caller-supplied recording stamp). It must precede the official deadline of every
  included gameweek, and every predicted kickoff must be strictly future.
* Deadlines are witnessed from the exact cutoff-known bootstrap the runs consumed, with
  the retained raw bytes re-hashed, never inferred from kickoffs.
* The two artifacts must agree on everything except the football-environment modes and
  the forecast role: live inputs (including registry hash and schedule captures), season,
  horizon, cutoff, commit, database hash, contracts, seed, draws, support, and the exact
  player/team row membership including blanks and double-gameweek legs.
* The primary MUST carry SDP provenance (primary + fallback configuration, frozen model,
  and consumed source versions validated against the retained raw payloads); the shadow
  MUST be the incumbent role with no SDP provenance; the primary's bound shadow hash MUST
  equal the shadow's canonical artifact hash.

All timestamps are read back through ``epoch_us(...)`` and compared as exact integers,
matching the repository's no-``pytz`` rule.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from fpl.artifacts.prospective_points import (
    ProspectivePointsArtifact,
    artifact_bytes,
)
from fpl.storage import ledger
from fpl.storage.db import table_exists
from fpl.storage.ledger import ensure_ledger_schema

if TYPE_CHECKING:
    import duckdb

PAIR_SCHEMA: Final[str] = "fpl.sdp-evidence-pair/v1"

_PRIMARY_ROLE: Final[str] = "primary"
_SHADOW_ROLE: Final[str] = "shadow_incumbent"
_SDP_PRIMARY_ENVIRONMENT: Final[str] = "sdp_v2"
_SDP_FALLBACK_ENVIRONMENT: Final[str] = "trailing_goals_attack_defence"

# The only component_modes entries that may differ between the two sides of a pair.
_ENV_MODE_KEYS: Final[frozenset[str]] = frozenset(
    {"football_environment.provenance", "football_environment.primary", "forecast_role"}
)

# The adopted TEAM ENVIRONMENT component legitimately differs between the sides: the
# primary runs the SDP environment with incumbent fallback, the shadow the incumbent
# alone. This is the adopted architecture, not a player challenger; the exact pair is
# validated and every player component must still be identical.
_TEAM_CLEAN_SHEET_MODE_KEY: Final[str] = "component.team_clean_sheet"
_SDP_PRIMARY_CS_MODE: Final[str] = "sdp_v2_with_incumbent_fallback"
_INCUMBENT_CS_MODE: Final[str] = "trailing_goals_attack_defence"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_sdp_evidence_pair (
    prediction_id              VARCHAR PRIMARY KEY,
    season                     VARCHAR NOT NULL,
    gw_from                    INTEGER NOT NULL,
    gw_to                      INTEGER NOT NULL,
    as_of                      TIMESTAMPTZ NOT NULL,
    primary_run_id             VARCHAR NOT NULL,
    primary_artifact_sha256    VARCHAR NOT NULL,
    shadow_run_id              VARCHAR NOT NULL,
    shadow_artifact_sha256     VARCHAR NOT NULL,
    created_at                 TIMESTAMPTZ NOT NULL,
    deadline_evidence          VARCHAR NOT NULL,
    source_provenance          VARCHAR NOT NULL,
    verification               VARCHAR NOT NULL
);
"""


class SdpEvidenceError(Exception):
    """The evidence registry was asked to record something it cannot honestly bind."""


class ArtifactNotCanonicalError(SdpEvidenceError):
    """The presented artifact file bytes are not the canonical serialisation."""


class UnknownPairRunError(SdpEvidenceError):
    """A required run is absent from the prediction ledger (a one-sided record)."""


class PairVerificationError(SdpEvidenceError):
    """A fail-closed pair verification failed; nothing was recorded."""


class DeadlineEvidenceError(PairVerificationError):
    """Pre-deadline existence could not be witnessed against official FPL deadlines."""


class PairConflictError(SdpEvidenceError):
    """This prediction_id already exists with different bound values."""


def _now() -> datetime:
    """The actual record entry instant. Production always uses real wall-clock time."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _RunRow:
    """The ledger's immutable forecast-run projection needed for pair verification."""

    run_id: str
    created_at_us: int
    as_of_us: int
    season: str
    gw_from: int
    gw_to: int
    artifact_schema: str
    schema_version: int
    status: str
    commit_sha: str
    artifact_sha256: str
    base_seed: int
    monte_carlo_draws: int
    row_count: int
    roster_size: int
    fixture_count: int
    worktree_clean: bool


@dataclass(frozen=True, slots=True)
class _PairRow:
    """Exactly the persisted ``ledger_sdp_evidence_pair`` columns."""

    prediction_id: str
    season: str
    gw_from: int
    gw_to: int
    as_of: datetime
    primary_run_id: str
    primary_artifact_sha256: str
    shadow_run_id: str
    shadow_artifact_sha256: str
    created_at: datetime
    deadline_evidence: str
    source_provenance: str
    verification: str


def ensure_sdp_evidence_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the additive pair table if absent, alongside the ledger tables it joins."""
    ensure_ledger_schema(con)
    con.execute(_SCHEMA)


def _epoch_us(value: datetime) -> int:
    """An aware instant as exact epoch microseconds, matching DuckDB's ``epoch_us()``."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return round(value.timestamp() * 1_000_000)


def _instant_from_us(value: int) -> datetime:
    """Rebuild an aware UTC instant from ``epoch_us`` microseconds (no IANA lookup)."""
    return datetime.fromtimestamp(value / 1_000_000, tz=UTC)


def _iso(value: int) -> str:
    return _instant_from_us(value).isoformat()


def _canonical_sha256(artifact: ProspectivePointsArtifact, presented: str) -> str:
    """The canonical artifact hash; the presented file hash must be exactly it."""
    canonical = hashlib.sha256(artifact_bytes(artifact)).hexdigest()
    if presented != canonical:
        raise ArtifactNotCanonicalError(
            "artifact file bytes are not the canonical serialisation: "
            f"presented sha256 {presented} against canonical {canonical}"
        )
    return canonical


def _load_run(con: duckdb.DuckDBPyConnection, run_id: str) -> _RunRow:
    row = con.execute(
        """
        SELECT run_id, epoch_us(created_at), epoch_us(as_of), season, gw_from, gw_to,
               artifact_schema, schema_version, status, commit_sha, artifact_sha256,
               base_seed, monte_carlo_draws, row_count, roster_size, fixture_count,
               worktree_clean
        FROM ledger_forecast_run WHERE run_id = ?
        """,
        [run_id],
    ).fetchone()
    if row is None:
        raise UnknownPairRunError(f"run {run_id} is not recorded in ledger_forecast_run")
    return _RunRow(
        run_id=str(row[0]),
        created_at_us=int(row[1]),
        as_of_us=int(row[2]),
        season=str(row[3]),
        gw_from=int(row[4]),
        gw_to=int(row[5]),
        artifact_schema=str(row[6]),
        schema_version=int(row[7]),
        status=str(row[8]),
        commit_sha=str(row[9]),
        artifact_sha256=str(row[10]),
        base_seed=int(row[11]),
        monte_carlo_draws=int(row[12]),
        row_count=int(row[13]),
        roster_size=int(row[14]),
        fixture_count=int(row[15]),
        worktree_clean=bool(row[16]),
    )


def derive_prediction_id(
    *,
    primary_run_id: str,
    shadow_run_id: str,
    season: str,
    gw_from: int,
    gw_to: int,
    as_of_us: int,
) -> str:
    """A deterministic id for one primary/shadow comparison pair."""
    identity = {
        "schema": PAIR_SCHEMA,
        "primary_run_id": primary_run_id,
        "shadow_run_id": shadow_run_id,
        "season": season,
        "gw_from": gw_from,
        "gw_to": gw_to,
        "as_of_us": as_of_us,
    }
    blob = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _component_modes(run_id: str, manifest: Any) -> dict[str, Any]:
    modes = dict(manifest.component_modes)
    if not isinstance(modes, dict):  # pragma: no cover - pydantic guarantees a mapping
        raise PairVerificationError(f"run {run_id} component_modes is not an object")
    return modes


def _verify_manifest_parity(
    primary: ProspectivePointsArtifact, shadow: ProspectivePointsArtifact
) -> dict[str, Any]:
    """Everything except the football-environment modes must be identical across sides."""
    pm, sm = primary.manifest, shadow.manifest
    compared = {
        "artifact_schema": (pm.artifact_schema, sm.artifact_schema),
        "schema_version": (pm.schema_version, sm.schema_version),
        "status": (pm.status, sm.status),
        "as_of": (pm.as_of, sm.as_of),
        "season": (pm.season, sm.season),
        "gw_from": (pm.gw_from, sm.gw_from),
        "gw_to": (pm.gw_to, sm.gw_to),
        "commit_sha": (pm.commit_sha, sm.commit_sha),
        "database_sha256": (pm.database_sha256, sm.database_sha256),
        "base_seed": (pm.base_seed, sm.base_seed),
        "monte_carlo_draws": (pm.monte_carlo_draws, sm.monte_carlo_draws),
        "fixture_points_support_max": (
            pm.fixture_points_support_max,
            sm.fixture_points_support_max,
        ),
        "roster_size": (pm.roster_size, sm.roster_size),
        "fixture_count": (pm.fixture_count, sm.fixture_count),
    }
    for name, (left, right) in compared.items():
        if left != right:
            raise PairVerificationError(
                f"primary and shadow manifests differ on {name}: {left!r} against {right!r}"
            )
    if pm.contracts != sm.contracts:
        raise PairVerificationError(
            "primary and shadow contract identities differ; a pair compares models, not rulesets"
        )
    if pm.live_inputs != sm.live_inputs:
        raise PairVerificationError(
            "primary and shadow live inputs differ; both sides must consume the identical "
            "FPL bootstrap, registry hash, and schedule captures"
        )
    return {
        "season": pm.season,
        "gw_from": pm.gw_from,
        "gw_to": pm.gw_to,
        "commit_sha": pm.commit_sha,
        "database_sha256": pm.database_sha256,
        "base_seed": pm.base_seed,
        "monte_carlo_draws": pm.monte_carlo_draws,
        "fixture_points_support_max": pm.fixture_points_support_max,
        "contracts": sorted(pm.contracts),
        "live_inputs_equal": True,
    }


def _verify_membership(
    primary: ProspectivePointsArtifact, shadow: ProspectivePointsArtifact
) -> dict[str, int]:
    """Exact row membership must match, including blanks and double-gameweek legs."""
    gw_primary = {
        (row.season, row.gw, row.code): (
            row.position,
            row.team_id,
            row.team_code,
            row.fixture_ids,
        )
        for row in primary.rows
    }
    gw_shadow = {
        (row.season, row.gw, row.code): (
            row.position,
            row.team_id,
            row.team_code,
            row.fixture_ids,
        )
        for row in shadow.rows
    }
    if gw_primary != gw_shadow:
        key_set_differs = sorted(set(gw_primary) ^ set(gw_shadow))
        key = (
            key_set_differs[0]
            if key_set_differs
            else next(key for key in gw_primary if gw_primary[key] != gw_shadow[key])
        )
        raise PairVerificationError(
            f"primary and shadow player-gameweek membership differs at {key}: "
            f"{gw_primary.get(key)} against {gw_shadow.get(key)}"
        )
    player_fixture = {
        (row.season, row.fixture, row.code): (
            row.gw,
            _epoch_us(row.kickoff_time),
            row.position,
            row.team_id,
            row.team_code,
            row.opponent_team_id,
            row.was_home,
        )
        for row in primary.player_fixture_rows
    }
    player_fixture_shadow = {
        (row.season, row.fixture, row.code): (
            row.gw,
            _epoch_us(row.kickoff_time),
            row.position,
            row.team_id,
            row.team_code,
            row.opponent_team_id,
            row.was_home,
        )
        for row in shadow.player_fixture_rows
    }
    if player_fixture != player_fixture_shadow:
        raise PairVerificationError(
            "primary and shadow player-fixture membership differs (fixture legs, kickoff, "
            "venue, position, or club/opponent identity)"
        )
    team_fixture = {
        (row.season, row.fixture, row.team_id): (
            row.gw,
            _epoch_us(row.kickoff_time),
            row.team_code,
            row.opponent_team_id,
            row.was_home,
        )
        for row in primary.team_fixture_rows
    }
    team_fixture_shadow = {
        (row.season, row.fixture, row.team_id): (
            row.gw,
            _epoch_us(row.kickoff_time),
            row.team_code,
            row.opponent_team_id,
            row.was_home,
        )
        for row in shadow.team_fixture_rows
    }
    if team_fixture != team_fixture_shadow:
        raise PairVerificationError(
            "primary and shadow team-fixture membership differs (fixture legs, kickoff, "
            "venue, or club/opponent identity)"
        )
    return {
        "player_gameweek_rows": len(gw_primary),
        "player_fixture_rows": len(player_fixture),
        "team_fixture_rows": len(team_fixture),
        "blank_gameweek_rows": sum(1 for value in gw_primary.values() if not value[3]),
    }


def _verify_component_modes(primary_modes: dict[str, Any], shadow_modes: dict[str, Any]) -> None:
    """Only the football-environment modes, forecast role, and adopted CS pair may differ."""
    primary_cs = primary_modes.get(_TEAM_CLEAN_SHEET_MODE_KEY)
    shadow_cs = shadow_modes.get(_TEAM_CLEAN_SHEET_MODE_KEY)
    if (primary_cs is not None or shadow_cs is not None) and (
        primary_cs != _SDP_PRIMARY_CS_MODE or shadow_cs != _INCUMBENT_CS_MODE
    ):
        raise PairVerificationError(
            f"{_TEAM_CLEAN_SHEET_MODE_KEY} is {primary_cs!r}/{shadow_cs!r} across the pair; "
            f"only the exact adopted pair (primary {_SDP_PRIMARY_CS_MODE!r}, shadow "
            f"{_INCUMBENT_CS_MODE!r}) may appear, and only as a difference"
        )
    primary_shared = {
        k: v
        for k, v in primary_modes.items()
        if k not in _ENV_MODE_KEYS and k != _TEAM_CLEAN_SHEET_MODE_KEY
    }
    shadow_shared = {
        k: v
        for k, v in shadow_modes.items()
        if k not in _ENV_MODE_KEYS and k != _TEAM_CLEAN_SHEET_MODE_KEY
    }
    if primary_shared != shadow_shared:
        differing = sorted(
            key
            for key in set(primary_shared) | set(shadow_shared)
            if primary_shared.get(key) != shadow_shared.get(key)
        )
        raise PairVerificationError(
            f"primary and shadow player-component modes differ: {differing}; only the "
            "football environment, forecast role, and the adopted clean-sheet pair may "
            "differ between pair sides"
        )
    shadow_role = shadow_modes.get("forecast_role")
    if shadow_role != _SHADOW_ROLE:
        raise PairVerificationError(
            f"the shadow side must declare forecast_role={_SHADOW_ROLE!r}, found {shadow_role!r}"
        )
    if "football_environment.provenance" in shadow_modes:
        raise PairVerificationError("the incumbent shadow must not carry SDP primary provenance")
    if "football_environment.primary" in shadow_modes:
        raise PairVerificationError(
            "the incumbent shadow must not claim a football environment primary"
        )
    primary_role = primary_modes.get("forecast_role")
    if primary_role != _PRIMARY_ROLE:
        raise PairVerificationError(
            f"the primary side must declare forecast_role={_PRIMARY_ROLE!r}, found {primary_role!r}"
        )


def _is_knowledge_time_key(key: str) -> bool:
    return (
        key in {"known_at", "cutoff", "fetched_at"}
        or key.endswith("_known_at")
        or key.endswith("_fetched_at")
    )


def _scan_provenance_times_and_hashes(
    node: Any,
    *,
    as_of: datetime,
    path: str,
    times: list[str],
    hashes: list[str],
    exclude: frozenset[str] = frozenset(),
) -> None:
    """Fail closed: every consumed knowledge time within the cutoff, every hash well-formed.

    Subtrees named in ``exclude`` (the operational ``refresh`` receipt) are skipped: a
    source revision fetched after the cutoff may appear in a receipt, but never in
    consumed source_versions, which are validated separately and strictly.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            name = str(key)
            if name in exclude:
                continue
            child = f"{path}.{key}"
            if isinstance(value, str):
                if _is_knowledge_time_key(name):
                    try:
                        stamp = datetime.fromisoformat(value)
                    except ValueError as error:
                        raise PairVerificationError(
                            f"SDP provenance {child} is not an ISO timestamp: {value!r}"
                        ) from error
                    if stamp.tzinfo is None or stamp.utcoffset() is None:
                        raise PairVerificationError(f"SDP provenance {child} is timezone-naive")
                    if stamp > as_of:
                        raise PairVerificationError(
                            f"SDP provenance {child} {value} is later than the run cutoff "
                            f"{as_of.isoformat()}"
                        )
                    times.append(child)
                elif name.endswith("sha256"):
                    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                        raise PairVerificationError(
                            f"SDP provenance {child} is not a 64-hex sha256: {value!r}"
                        )
                    hashes.append(child)
            elif isinstance(value, (dict, list)):
                _scan_provenance_times_and_hashes(
                    value,
                    as_of=as_of,
                    path=child,
                    times=times,
                    hashes=hashes,
                    exclude=exclude,
                )
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _scan_provenance_times_and_hashes(
                value,
                as_of=as_of,
                path=f"{path}[{index}]",
                times=times,
                hashes=hashes,
                exclude=exclude,
            )


def _aware_instant(value: Any, *, label: str, cutoff: datetime) -> datetime:
    if not isinstance(value, str):
        raise PairVerificationError(f"{label} must be an ISO timestamp string, got {value!r}")
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise PairVerificationError(f"{label} is not an ISO timestamp: {value!r}") from error
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise PairVerificationError(f"{label} is timezone-naive")
    if stamp > cutoff:
        raise PairVerificationError(
            f"{label} {value} is later than the consumed cutoff {cutoff.isoformat()}"
        )
    return stamp


def _validate_consumed_sources(
    con: duckdb.DuckDBPyConnection,
    provenance: dict[str, Any],
    *,
    season: str,
    cutoff: datetime,
) -> dict[str, int]:
    """Every declared consumed source MUST be witnessed by the normative strict reader.

    There is NO empty-reader exception: ``sdp_runtime.load_sdp_state`` is the normative
    reader that revalidates raw bytes, statuses, identity, metadata, and core fields for
    every cutoff-eligible match, and emits the canonical normalized provenance (the
    knowledge time it reports is already the maximum of the stats fetch time, the FPL
    metadata known time, and the selected SDP match-metadata receipt time). Each declared
    entry must equal ONE full canonical ``SdpStateRow.provenance`` exactly -- the same
    field set with the same values, timestamps compared as instants. A reader that yields
    no rows cannot witness anything, so declared sources with an empty reader are a
    refusal, not a skip: a source the database can no longer evidence was not demonstrably
    consumed at this cutoff. Declaring no sources (an all-fallback forecast) requires no
    witnessing. The reader is cutoff-selected by construction, so an exact match also
    proves every consumed time preceded the cutoff.
    """
    versions = provenance.get("source_versions")
    if not isinstance(versions, list):
        raise PairVerificationError("SDP provenance source_versions must be a list")
    if not versions:
        return {"stats_payloads_validated": 0, "metadata_receipts_validated": 0}

    from fpl.storage.sdp_runtime import load_sdp_state

    state = load_sdp_state(con, cutoff=cutoff, season=season)
    actual: dict[tuple[str, str], dict[str, Any]] = {}
    for row in state.rows:
        if isinstance(row.provenance, dict):
            canonical = dict(row.provenance)
            key = (
                str(canonical.get("payload_id")),
                str(canonical.get("payload_sha256")),
            )
            actual[key] = canonical
    if not actual:
        raise PairVerificationError(
            "declared consumed SDP sources exist but the strict SDP reader yields no "
            "cutoff-eligible rows; the database cannot evidence the consumption"
        )

    stats = 0
    metadata = 0
    for index, entry in enumerate(versions):
        if not isinstance(entry, dict):
            raise PairVerificationError(f"SDP source_version[{index}] is not an object")
        payload_id = entry.get("payload_id")
        payload_sha = entry.get("payload_sha256")
        if not isinstance(payload_id, str) or not isinstance(payload_sha, str):
            raise PairVerificationError(f"SDP source_version[{index}] payload identity missing")
        witnessed = actual.get((payload_id, payload_sha))
        if witnessed is None:
            raise PairVerificationError(
                f"declared consumed source {payload_id!r} is not a cutoff-eligible match "
                "according to the strict SDP reader; it was not consumed at this cutoff"
            )
        if set(entry) != set(witnessed):
            differing = sorted(set(entry) ^ set(witnessed))
            raise PairVerificationError(
                f"declared consumed source {payload_id!r} provenance is not the full canonical "
                f"reader shape; fields differ: {differing}"
            )
        for field, declared in sorted(entry.items()):
            seen = witnessed[field]
            if field in {"fetched_at", "known_at", "fpl_metadata_known_at"}:
                same = (
                    isinstance(declared, str)
                    and isinstance(seen, str)
                    and datetime.fromisoformat(declared) == datetime.fromisoformat(seen)
                )
            else:
                same = declared == seen
            if not same:
                raise PairVerificationError(
                    f"declared consumed source {payload_id!r} field {field!r} disagrees with "
                    "the strict SDP reader's cutoff-eligible provenance"
                )
        if isinstance(entry.get("match_metadata_payload_id"), str):
            metadata += 1
        stats += 1
    return {"stats_payloads_validated": stats, "metadata_receipts_validated": metadata}


def _validate_decision_coverage(decisions: list[Any], artifact: ProspectivePointsArtifact) -> int:
    """Exactly one selector decision per fixture, with its exact club/venue/gameweek identity."""
    per_fixture: dict[int, dict[str, Any]] = {}
    for row in artifact.team_fixture_rows:
        entry = per_fixture.setdefault(
            row.fixture, {"season": row.season, "gw": row.gw, "home": None, "away": None}
        )
        if row.was_home:
            entry["home"] = row.team_code
        else:
            entry["away"] = row.team_code
    seen: set[int] = set()
    for decision in decisions:
        if not isinstance(decision, dict):
            raise PairVerificationError("an SDP selector decision is not an object")
        fixture_value = decision.get("fixture")
        if isinstance(fixture_value, bool) or not isinstance(fixture_value, int):
            raise PairVerificationError(
                f"selector decision fixture is not an integer: {fixture_value!r}"
            )
        if fixture_value in seen:
            raise PairVerificationError(f"duplicate selector decision for fixture {fixture_value}")
        seen.add(fixture_value)
        expected = per_fixture.get(fixture_value)
        if expected is None:
            raise PairVerificationError(
                f"selector decision names fixture {fixture_value}, which the primary "
                "artifact does not contain"
            )
        identity = (
            decision.get("season"),
            decision.get("gw"),
            decision.get("home_team_code"),
            decision.get("away_team_code"),
        )
        wanted = (expected["season"], expected["gw"], expected["home"], expected["away"])
        if identity != wanted:
            raise PairVerificationError(
                f"selector decision for fixture {fixture_value} disagrees with the fixture "
                f"identity: {identity} against {wanted}"
            )
        selector = decision.get("selector")
        if not isinstance(selector, str) or not selector:
            raise PairVerificationError(
                f"selector decision for fixture {fixture_value} has no explicit selector reason"
            )
    missing = sorted(set(per_fixture) - seen)
    if missing:
        raise PairVerificationError(
            f"missing selector decision for fixture(s) {missing}; every predicted fixture "
            "needs exactly one environment decision"
        )
    return len(per_fixture)


def _verify_primary_environment(
    con: duckdb.DuckDBPyConnection,
    primary_modes: dict[str, Any],
    *,
    as_of: datetime,
    shadow_sha256: str,
    artifact: ProspectivePointsArtifact,
) -> dict[str, Any]:
    """The primary MUST carry complete SDP provenance binding this exact shadow."""
    raw = primary_modes.get("football_environment.provenance")
    if raw is None:
        raise PairVerificationError(
            "the primary side must carry football_environment.provenance; the owner-directed "
            "adoption records SDP primary evidence, not an environmentless run"
        )
    if not isinstance(raw, str):
        raise PairVerificationError(
            "football_environment.provenance must be a canonical JSON string"
        )
    try:
        provenance = json.loads(raw)
    except ValueError as error:
        raise PairVerificationError("football_environment.provenance is not valid JSON") from error
    if not isinstance(provenance, dict):
        raise PairVerificationError("football_environment.provenance is not a JSON object")
    if provenance.get("primary") != _SDP_PRIMARY_ENVIRONMENT:
        raise PairVerificationError("SDP provenance must declare the sdp_v2 primary configuration")
    if provenance.get("fallback") != _SDP_FALLBACK_ENVIRONMENT:
        raise PairVerificationError(
            "SDP provenance must declare the incumbent fallback configuration "
            f"{_SDP_FALLBACK_ENVIRONMENT!r}"
        )
    # Frozen model provenance: required whenever the SDP environment was actually used;
    # absent (null preserved) is acceptable only for an all-fallback forecast.
    decisions = provenance.get("decisions")
    if not isinstance(decisions, list):
        raise PairVerificationError("SDP provenance decisions must be a list")
    fixture_count = _validate_decision_coverage(decisions, artifact)
    selectors = {
        str(decision.get("selector")) for decision in decisions if isinstance(decision, dict)
    }
    sdp_primary_used = "SDP_PRIMARY" in selectors
    model_sha = provenance.get("model_sha256")
    model_known_at = provenance.get("model_known_at")
    if model_sha is None or model_known_at is None:
        if sdp_primary_used:
            raise PairVerificationError(
                "SDP_PRIMARY selectors require valid frozen model provenance; an absent "
                "model is tolerable only when every fixture selector is an explicit fallback"
            )
        if model_sha is not None or model_known_at is not None:
            raise PairVerificationError(
                "SDP provenance model_sha256 and model_known_at must be present or absent together"
            )
    else:
        if (
            not isinstance(model_sha, str)
            or len(model_sha) != 64
            or any(c not in "0123456789abcdef" for c in model_sha)
        ):
            raise PairVerificationError(
                "SDP provenance must carry a well-formed frozen model sha256"
            )
        _aware_instant(model_known_at, label="SDP provenance model_known_at", cutoff=as_of)
    bound = provenance.get("shadow_incumbent_artifact_sha256")
    if not isinstance(bound, str):
        raise PairVerificationError("SDP provenance must bind the shadow incumbent artifact sha256")
    if bound != shadow_sha256:
        raise PairVerificationError(
            f"SDP provenance binds shadow artifact hash {bound!r} but the shadow's canonical "
            f"artifact hash is {shadow_sha256!r}"
        )
    sources = _validate_consumed_sources(
        con, provenance, cutoff=as_of, season=artifact.manifest.season
    )
    if sdp_primary_used and sources["stats_payloads_validated"] == 0:
        raise PairVerificationError(
            "SDP_PRIMARY selectors require consumed SDP source versions; none were declared"
        )
    times: list[str] = []
    hashes: list[str] = []
    _scan_provenance_times_and_hashes(
        provenance,
        as_of=as_of,
        path="provenance",
        times=times,
        hashes=hashes,
        exclude=frozenset({"refresh"}),
    )
    health = provenance.get("health")
    health_dict = health if isinstance(health, dict) else {}
    return {
        "present": True,
        "primary": _SDP_PRIMARY_ENVIRONMENT,
        "fallback": _SDP_FALLBACK_ENVIRONMENT,
        "model_sha256": model_sha,
        "model_known_at": model_known_at,
        "model_version": provenance.get("model_version"),
        "latest_sdp_known_at": health_dict.get("latest_sdp_known_at"),
        "selector_counts_team_predictions": provenance.get("selector_counts_team_predictions"),
        "decision_coverage": {
            "fixtures": fixture_count,
            "all_fallback": not sdp_primary_used,
        },
        "consumed_sources": sources,
        "knowledge_times_within_cutoff": len(times),
        "source_hashes_validated": len(hashes),
        "refresh_receipt_times_exempt": True,
    }


def _verify_populations(con: duckdb.DuckDBPyConnection, run: _RunRow) -> dict[str, dict[str, int]]:
    """The inserted vintage must hold its complete declared population, at both grains."""
    horizon = run.gw_to - run.gw_from + 1
    expected_rows = run.roster_size * horizon
    gw_rows = con.execute(
        "SELECT count(*) FROM ledger_prediction_player_gameweek WHERE run_id = ?", [run.run_id]
    ).fetchone()
    team_rows = con.execute(
        "SELECT count(*) FROM ledger_prediction_team_fixture WHERE run_id = ?", [run.run_id]
    ).fetchone()
    player_fixture_rows = con.execute(
        "SELECT count(*) FROM ledger_prediction_player_fixture WHERE run_id = ?", [run.run_id]
    ).fetchone()
    total_legs = con.execute(
        """
        SELECT coalesce(sum(json_array_length(fixture_ids)), 0)
        FROM ledger_prediction_player_gameweek WHERE run_id = ?
        """,
        [run.run_id],
    ).fetchone()
    assert gw_rows is not None
    assert team_rows is not None
    assert player_fixture_rows is not None
    assert total_legs is not None
    counts = {
        "player_gameweek_rows": int(gw_rows[0]),
        "team_fixture_rows": int(team_rows[0]),
        "player_fixture_rows": int(player_fixture_rows[0]),
        "player_fixture_legs": int(total_legs[0]),
    }
    expected = {
        "player_gameweek_rows": expected_rows,
        "player_fixture_rows": int(total_legs[0]),
    }
    if run.row_count != expected_rows or counts["player_gameweek_rows"] != expected_rows:
        raise PairVerificationError(
            f"run {run.run_id} population incomplete: {counts['player_gameweek_rows']} "
            f"player-gameweek rows against an expected {expected_rows}"
        )
    if run.schema_version >= 2:
        expected["team_fixture_rows"] = 2 * run.fixture_count
        if counts["team_fixture_rows"] != expected["team_fixture_rows"]:
            raise PairVerificationError(
                f"run {run.run_id} fixture population incomplete: {counts['team_fixture_rows']} "
                f"team-fixture rows against an expected {expected['team_fixture_rows']}"
            )
        if counts["player_fixture_rows"] != counts["player_fixture_legs"]:
            raise PairVerificationError(
                f"run {run.run_id} fixture-grain transport incomplete: "
                f"{counts['player_fixture_rows']} player-fixture rows against "
                f"{counts['player_fixture_legs']} declared fixture legs"
            )
    elif counts["team_fixture_rows"] != 0 or counts["player_fixture_rows"] != 0:
        raise PairVerificationError(
            f"run {run.run_id} declares schema version {run.schema_version} but carries "
            "fixture-grain rows"
        )
    return {"stored": counts, "expected": expected}


def _deadline_witness(
    con: duckdb.DuckDBPyConnection,
    *,
    bootstrap_capture_id: str,
    bootstrap_payload_sha256: str,
    bootstrap_known_at: datetime,
    cutoff: datetime,
    season: str,
    gw_from: int,
    gw_to: int,
    recorded_at: datetime,
) -> dict[str, Any]:
    """Witness official deadlines from the exact cutoff-known bootstrap the runs consumed.

    The retained raw payload bytes are re-hashed against both the snapshot store and the
    runs' declared bootstrap hash; the capture time must equal the manifest's declared
    bootstrap knowledge time and that knowledge time must precede the forecast cutoff;
    event identities must be unique; every included gameweek needs a deadline at or after
    the record entry instant.
    """
    if bootstrap_known_at > cutoff:
        raise DeadlineEvidenceError(
            f"the manifest's bootstrap knowledge time {bootstrap_known_at.isoformat()} is "
            f"after the forecast cutoff {cutoff.isoformat()}; the runs did not consume a "
            "cutoff-known FPL snapshot"
        )
    if not table_exists(con, "snapshot_payload") or not table_exists(con, "snapshot_capture"):
        raise DeadlineEvidenceError(
            "FPL snapshot tables are absent; official deadline evidence cannot be witnessed"
        )
    rows = con.execute(
        """
        SELECT epoch_us(c.captured_at), c.season, p.sha256, CAST(p.payload AS VARCHAR)
        FROM snapshot_payload AS p JOIN snapshot_capture AS c USING (capture_id)
        WHERE p.capture_id = ? AND p.endpoint = 'bootstrap-static' AND p.parameter = ''
        """,
        [bootstrap_capture_id],
    ).fetchall()
    if len(rows) != 1:
        raise DeadlineEvidenceError(
            f"bootstrap capture {bootstrap_capture_id} does not resolve to exactly one "
            "bootstrap-static payload row"
        )
    captured_us, capture_season, stored_sha, payload_text = rows[0]
    payload_bytes = str(payload_text).encode("utf-8")
    if hashlib.sha256(payload_bytes).hexdigest() != str(stored_sha):
        raise DeadlineEvidenceError(
            "retained deadline witness bytes do not hash to the stored payload sha256"
        )
    if str(stored_sha) != bootstrap_payload_sha256:
        raise DeadlineEvidenceError(
            "deadline witness payload hash does not match the runs' bootstrap payload hash"
        )
    if int(captured_us) != _epoch_us(bootstrap_known_at):
        raise DeadlineEvidenceError(
            "the retained capture time does not equal the manifest's declared bootstrap "
            "knowledge time"
        )
    if str(capture_season) != season:
        raise DeadlineEvidenceError(
            f"deadline witness capture season {capture_season!r} does not match run season "
            f"{season!r}"
        )
    if int(captured_us) > _epoch_us(recorded_at):
        raise DeadlineEvidenceError(
            "deadline witness bootstrap was captured after the record entry instant; a future "
            "capture cannot witness a prior commitment"
        )
    try:
        data = json.loads(str(payload_text))
        events = data["events"]
        if not isinstance(events, list) or not events:
            raise ValueError("events must be a non-empty list")
        deadlines: dict[int, datetime] = {}
        for event in events:
            event_id = int(event["id"])
            if event_id in deadlines:
                raise ValueError(f"duplicate event identity {event_id}")
            raw = event.get("deadline_time")
            if not isinstance(raw, str):
                raise ValueError(f"event {event_id} has no deadline_time")
            stamp = datetime.fromisoformat(raw)
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError(f"event {event_id} deadline_time is timezone-naive")
            deadlines[event_id] = stamp
    except (ValueError, KeyError, TypeError) as error:
        raise DeadlineEvidenceError(
            f"deadline witness bootstrap payload is unusable: {error}"
        ) from error
    horizon = range(gw_from, gw_to + 1)
    missing = [gw for gw in horizon if gw not in deadlines]
    if missing:
        raise DeadlineEvidenceError(
            f"included gameweeks {missing} have no official deadline in the cutoff-known "
            "bootstrap; pre-deadline existence cannot be witnessed"
        )
    late = sorted(gw for gw in horizon if recorded_at > deadlines[gw])
    if late:
        raise DeadlineEvidenceError(
            f"the record entry instant {recorded_at.isoformat()} is after the official deadline "
            f"of included gameweek(s) {late}; an expired deadline cannot witness a prior "
            "commitment"
        )
    return {
        "rule": (
            "created_at (actual record entry instant) <= the official deadline of every "
            "included gameweek, and every predicted kickoff strictly future; deadlines "
            "witnessed from the cutoff-known bootstrap-static payload the runs consumed, "
            "with the retained raw bytes re-hashed"
        ),
        "source": "snapshot_payload/snapshot_capture bootstrap-static",
        "capture_id": bootstrap_capture_id,
        "captured_at": _iso(int(captured_us)),
        "payload_sha256": bootstrap_payload_sha256,
        "deadlines": {str(gw): deadlines[gw].isoformat() for gw in sorted(horizon)},
    }


def _verify_future_kickoffs(
    primary: ProspectivePointsArtifact, shadow: ProspectivePointsArtifact, recorded_us: int
) -> dict[str, int]:
    """Every predicted kickoff must still be future at the record entry instant."""
    kickoffs: set[int] = set()
    for artifact in (primary, shadow):
        if artifact.player_fixture_rows:
            kickoffs.update(_epoch_us(row.kickoff_time) for row in artifact.player_fixture_rows)
        else:
            for gameweek in artifact.rows:
                kickoffs.update(_epoch_us(kickoff) for kickoff in gameweek.kickoff_times)
    if not kickoffs:
        raise PairVerificationError("the paired artifacts carry no predicted kickoffs")
    past = sorted(us for us in kickoffs if us <= recorded_us)
    if past:
        raise DeadlineEvidenceError(
            "the pair predicts kickoff(s) at or before the record entry instant: "
            f"{[_iso(us) for us in past]}"
        )
    return {"distinct_future_kickoffs": len(kickoffs)}


def _run_provenance(
    run_id: str, artifact: ProspectivePointsArtifact, artifact_sha256: str, modes: dict[str, Any]
) -> dict[str, Any]:
    manifest = artifact.manifest
    return {
        "run_id": run_id,
        "artifact_sha256": artifact_sha256,
        "as_of": manifest.as_of.isoformat(),
        "commit_sha": manifest.commit_sha,
        "worktree_clean": manifest.worktree_clean,
        "bootstrap_capture_id": manifest.live_inputs.bootstrap_capture_id,
        "bootstrap_known_at": manifest.live_inputs.bootstrap_known_at.isoformat(),
        "bootstrap_payload_sha256": manifest.live_inputs.bootstrap_payload_sha256,
        "schedule_capture_ids": list(manifest.live_inputs.schedule_capture_ids),
        "selectable_player_registry_sha256": (
            manifest.live_inputs.selectable_player_registry_sha256
        ),
        "contract_identities": {
            name: {"name": c.name, "version": c.version, "sha256": c.sha256}
            for name, c in sorted(manifest.contracts.items())
        },
        "component_modes": modes,
    }


def _ensure_vintage(
    con: duckdb.DuckDBPyConnection,
    artifact: ProspectivePointsArtifact,
    artifact_sha256: str,
    run_id: str,
    stamp: datetime,
) -> _RunRow:
    """Insert the immutable vintage if absent; an existing one must match exactly.

    Reuses the ledger's private insert helpers inside the pair transaction so both
    vintages and the pair row commit or roll back together.
    """
    if ledger.run_exists(con, run_id):
        row = _load_run(con, run_id)
        if row.artifact_sha256 != artifact_sha256:
            raise PairConflictError(
                f"run {run_id} is already recorded with a different artifact hash"
            )
        if row.created_at_us > _epoch_us(stamp):
            raise PairVerificationError(
                f"run {run_id} claims a recording instant after the pair record entry; every "
                "forecast run must already exist at the pair record entry time"
            )
        return row
    ledger._insert_run(con, run_id, artifact.manifest, artifact_sha256, stamp)
    ledger._insert_predictions(con, run_id, artifact)
    return _load_run(con, run_id)


def _fetch_pair_row(con: duckdb.DuckDBPyConnection, prediction_id: str) -> tuple[Any, ...] | None:
    return con.execute(
        """
        SELECT prediction_id, season, gw_from, gw_to, epoch_us(as_of),
               primary_run_id, primary_artifact_sha256, shadow_run_id, shadow_artifact_sha256,
               epoch_us(created_at), deadline_evidence, source_provenance, verification
        FROM ledger_sdp_evidence_pair WHERE prediction_id = ?
        """,
        [prediction_id],
    ).fetchone()


# Stored columns compared on a repeat, positionally into _fetch_pair_row's projection:
# the full pair binding (prediction_id, season, horizon, as_of, both run ids and both
# artifact hashes). created_at (index 9) is excluded so an identical repeat is an
# idempotent no-op that keeps the original stamp -- including a repeat issued after the
# deadline has passed. The three JSON payload columns (indices 10-12) are deterministic
# functions of the immutable artifacts and snapshot captures and were verified at the
# initial recording.
_BINDING_COLUMNS: Final[tuple[int, ...]] = (0, 1, 2, 3, 4, 5, 6, 7, 8)


def record_pair(
    con: duckdb.DuckDBPyConnection,
    *,
    primary: ProspectivePointsArtifact,
    primary_sha256: str,
    shadow: ProspectivePointsArtifact,
    shadow_sha256: str,
) -> str:
    """Bind a primary/incumbent-shadow pair; insert missing ledger vintages atomically.

    Both artifacts are validated as canonical, both ledger vintages are inserted (or
    recognised as already present and exactly equal), the pair is verified, and the pair
    row is written -- all inside ONE transaction. Any failure rolls back to zero partial
    new predictions. The record entry instant is always the actual ``datetime.now(UTC)``;
    it stamps new ledger rows and the pair's ``created_at``. An identical repeat of an
    already-recorded pair is an idempotent no-op returning the existing id and stamp.
    """
    ensure_sdp_evidence_schema(con)
    primary_sha = _canonical_sha256(primary, primary_sha256)
    shadow_sha = _canonical_sha256(shadow, shadow_sha256)
    primary_run_id = ledger.derive_run_id(primary.manifest, primary_sha)
    shadow_run_id = ledger.derive_run_id(shadow.manifest, shadow_sha)
    if primary_run_id == shadow_run_id:
        raise PairVerificationError("the primary and shadow sides of a pair are the same artifact")
    stamp = _now()
    if stamp.tzinfo is None or stamp.utcoffset() is None:  # pragma: no cover - clock contract
        raise PairVerificationError("the record entry clock returned a naive instant")
    prediction_id = derive_prediction_id(
        primary_run_id=primary_run_id,
        shadow_run_id=shadow_run_id,
        season=primary.manifest.season,
        gw_from=primary.manifest.gw_from,
        gw_to=primary.manifest.gw_to,
        as_of_us=_epoch_us(primary.manifest.as_of),
    )
    existing = _fetch_pair_row(con, prediction_id)
    if existing is not None:
        stored = tuple(existing[index] for index in _BINDING_COLUMNS)
        replay = (
            prediction_id,
            primary.manifest.season,
            primary.manifest.gw_from,
            primary.manifest.gw_to,
            _epoch_us(primary.manifest.as_of),
            primary_run_id,
            primary_sha,
            shadow_run_id,
            shadow_sha,
        )
        if stored == replay:
            return prediction_id
        raise PairConflictError(
            f"pair {prediction_id} is already recorded with different bound values: "
            f"stored {stored}, replay {replay}"
        )

    con.execute("BEGIN TRANSACTION")
    try:
        primary_row = _ensure_vintage(con, primary, primary_sha, primary_run_id, stamp)
        shadow_row = _ensure_vintage(con, shadow, shadow_sha, shadow_run_id, stamp)
        verification, source_provenance, deadline_evidence = _verify_pair(
            con,
            primary=primary,
            shadow=shadow,
            primary_sha=primary_sha,
            shadow_sha=shadow_sha,
            primary_run_id=primary_run_id,
            shadow_run_id=shadow_run_id,
            primary_row=primary_row,
            shadow_row=shadow_row,
            stamp=stamp,
        )
        _insert_pair(
            con,
            _PairRow(
                prediction_id=prediction_id,
                season=primary.manifest.season,
                gw_from=primary.manifest.gw_from,
                gw_to=primary.manifest.gw_to,
                as_of=primary.manifest.as_of,
                primary_run_id=primary_run_id,
                primary_artifact_sha256=primary_sha,
                shadow_run_id=shadow_run_id,
                shadow_artifact_sha256=shadow_sha,
                created_at=stamp,
                deadline_evidence=deadline_evidence,
                source_provenance=source_provenance,
                verification=verification,
            ),
        )
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return prediction_id


def _verify_pair(
    con: duckdb.DuckDBPyConnection,
    *,
    primary: ProspectivePointsArtifact,
    shadow: ProspectivePointsArtifact,
    primary_sha: str,
    shadow_sha: str,
    primary_run_id: str,
    shadow_run_id: str,
    primary_row: _RunRow,
    shadow_row: _RunRow,
    stamp: datetime,
) -> tuple[str, str, str]:
    """Run every fail-closed check; return the three persisted JSON columns."""
    for name, row in (("primary", primary_row), ("shadow", shadow_row)):
        if not row.worktree_clean:
            raise PairVerificationError(
                f"{name} run {row.run_id} was produced from a dirty worktree"
            )
        if row.created_at_us > _epoch_us(stamp):
            raise PairVerificationError(
                f"{name} run {row.run_id} must already exist at the pair record entry instant"
            )
        if row.as_of_us > _epoch_us(stamp):
            raise PairVerificationError(
                f"{name} run {row.run_id} claims knowledge time {_iso(row.as_of_us)} after the "
                "record entry instant; a future cutoff is refused"
            )

    parity = _verify_manifest_parity(primary, shadow)
    membership = _verify_membership(primary, shadow)
    populations = {
        "primary": _verify_populations(con, primary_row),
        "shadow": _verify_populations(con, shadow_row),
    }
    kickoff_check = _verify_future_kickoffs(primary, shadow, _epoch_us(stamp))

    primary_modes = _component_modes(primary_run_id, primary.manifest)
    shadow_modes = _component_modes(shadow_run_id, shadow.manifest)
    _verify_component_modes(primary_modes, shadow_modes)
    as_of = primary.manifest.as_of
    environment = _verify_primary_environment(
        con,
        primary_modes,
        as_of=as_of,
        shadow_sha256=shadow_sha,
        artifact=primary,
    )

    deadline_evidence = _deadline_witness(
        con,
        bootstrap_capture_id=primary.manifest.live_inputs.bootstrap_capture_id,
        bootstrap_payload_sha256=primary.manifest.live_inputs.bootstrap_payload_sha256,
        bootstrap_known_at=primary.manifest.live_inputs.bootstrap_known_at,
        cutoff=as_of,
        season=primary.manifest.season,
        gw_from=primary.manifest.gw_from,
        gw_to=primary.manifest.gw_to,
        recorded_at=stamp,
    )

    verification = {
        "schema_version": 2,
        "manifest_parity": parity,
        "membership": membership,
        "populations": populations,
        "kickoffs": kickoff_check,
        "worktree_clean": True,
        "roles": {
            "primary_forecast_role": primary_modes.get("forecast_role"),
            "shadow_forecast_role": shadow_modes.get("forecast_role"),
            "shadow_environment_disabled": True,
        },
        "primary_shadow_hash_binding": {
            "required": True,
            "shadow_incumbent_artifact_sha256": shadow_sha,
        },
        "sdp_provenance": environment,
        "deadline_rule_witnessed": True,
    }
    source_provenance = {
        "primary": _run_provenance(primary_run_id, primary, primary_sha, primary_modes),
        "shadow": _run_provenance(shadow_run_id, shadow, shadow_sha, shadow_modes),
    }
    return (
        json.dumps(verification, sort_keys=True, separators=(",", ":"), allow_nan=False),
        json.dumps(source_provenance, sort_keys=True, separators=(",", ":"), allow_nan=False),
        json.dumps(deadline_evidence, sort_keys=True, separators=(",", ":"), allow_nan=False),
    )


def _insert_pair(con: duckdb.DuckDBPyConnection, row: _PairRow) -> None:
    con.execute(
        """
        INSERT INTO ledger_sdp_evidence_pair (
            prediction_id, season, gw_from, gw_to, as_of,
            primary_run_id, primary_artifact_sha256, shadow_run_id, shadow_artifact_sha256,
            created_at, deadline_evidence, source_provenance, verification
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            row.prediction_id,
            row.season,
            row.gw_from,
            row.gw_to,
            row.as_of,
            row.primary_run_id,
            row.primary_artifact_sha256,
            row.shadow_run_id,
            row.shadow_artifact_sha256,
            row.created_at,
            row.deadline_evidence,
            row.source_provenance,
            row.verification,
        ],
    )


def load_pair(con: duckdb.DuckDBPyConnection, prediction_id: str) -> dict[str, Any] | None:
    """The full pair row as a JSON-ready dict, or ``None`` when absent."""
    row = _fetch_pair_row(con, prediction_id)
    if row is None:
        return None
    return {
        "prediction_id": str(row[0]),
        "season": str(row[1]),
        "gw_from": int(row[2]),
        "gw_to": int(row[3]),
        "as_of": _iso(int(row[4])),
        "primary_run_id": str(row[5]),
        "primary_artifact_sha256": str(row[6]),
        "shadow_run_id": str(row[7]),
        "shadow_artifact_sha256": str(row[8]),
        "created_at": _iso(int(row[9])),
        "deadline_evidence": json.loads(str(row[10])),
        "source_provenance": json.loads(str(row[11])),
        "verification": json.loads(str(row[12])),
    }


def list_pairs(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Every recorded pair, newest recording first."""
    rows = con.execute(
        """
        SELECT prediction_id, epoch_us(created_at), season, gw_from, gw_to, epoch_us(as_of),
               primary_run_id, shadow_run_id
        FROM ledger_sdp_evidence_pair ORDER BY created_at DESC, prediction_id
        """,
    ).fetchall()
    return [
        {
            "prediction_id": str(row[0]),
            "created_at": _iso(int(row[1])),
            "season": str(row[2]),
            "gw_from": int(row[3]),
            "gw_to": int(row[4]),
            "as_of": _iso(int(row[5])),
            "primary_run_id": str(row[6]),
            "shadow_run_id": str(row[7]),
        }
        for row in rows
    ]


def _outcome_team(
    con: duckdb.DuckDBPyConnection, season: str, fixture: int, team_id: int
) -> dict[str, Any] | None:
    row = con.execute(
        """
        SELECT epoch_us(attached_at), goals_for, goals_against
        FROM ledger_outcome_team_fixture
        WHERE season = ? AND fixture = ? AND team_id = ?
        """,
        [season, fixture, team_id],
    ).fetchone()
    if row is None:
        return None
    return {
        "attached": True,
        "attached_at": _iso(int(row[0])),
        "goals_for": int(row[1]),
        "goals_against": int(row[2]),
    }


def _outcome_player(
    con: duckdb.DuckDBPyConnection, season: str, fixture: int, code: int
) -> dict[str, Any] | None:
    row = con.execute(
        """
        SELECT epoch_us(attached_at), total_points_as_recorded, points_under_rules_2026_27
        FROM ledger_outcome_player_fixture
        WHERE season = ? AND code = ? AND fixture = ?
        """,
        [season, code, fixture],
    ).fetchone()
    if row is None:
        return None
    return {
        "attached": True,
        "attached_at": _iso(int(row[0])),
        "total_points_as_recorded": row[1],
        "points_under_rules_2026_27": row[2],
    }


def _official_gameweek_final(con: duckdb.DuckDBPyConnection, season: str, gw: int) -> bool | None:
    """The established official-gameweek finality rule, evaluated on the source of truth.

    Mirrors the BI exporter's ``dim_gameweek``: a gameweek is officially final when EVERY
    fixture of that (season, gw) is ``finished IS TRUE`` -- over ``stg_fixture`` for
    archived seasons, or over each fixture's latest live fixture version otherwise. A
    gameweek with no witness rows in the database at all is ``None``: no finality witness
    exists, so downstream consumers must treat the gameweek as unavailable, never final.
    """
    historical_rows = None
    if table_exists(con, "stg_fixture"):
        historical_rows = con.execute(
            """
            SELECT count(*), count(*) FILTER (WHERE finished IS TRUE)
            FROM stg_fixture WHERE season = ? AND gw = ?
            """,
            [season, gw],
        ).fetchone()
    archived_season = None
    if table_exists(con, "stg_fixture"):
        row = con.execute(
            "SELECT EXISTS (SELECT 1 FROM stg_fixture WHERE season = ?)", [season]
        ).fetchone()
        archived_season = bool(row[0]) if row is not None else False
    if archived_season and historical_rows is not None:
        total, finished = int(historical_rows[0]), int(historical_rows[1])
    elif table_exists(con, "stg_live_fixture_version"):
        live = con.execute(
            """
            SELECT count(*), count(*) FILTER (WHERE finished IS TRUE)
            FROM (
                SELECT finished, gw FROM stg_live_fixture_version
                WHERE season = ?
                QUALIFY row_number() OVER (
                    PARTITION BY fixture ORDER BY known_at DESC, capture_id DESC
                ) = 1
            ) WHERE gw = ?
            """,
            [season, gw],
        ).fetchone()
        total, finished = (int(live[0]), int(live[1])) if live is not None else (0, 0)
    else:
        total, finished = 0, 0
    if total == 0:
        return None
    return finished == total


def _outcome_player_gameweek(
    con: duckdb.DuckDBPyConnection, season: str, gw: int, code: int, fixture_ids: tuple[int, ...]
) -> dict[str, Any]:
    """Outcome status for one player-gameweek, honoring complete OFFICIAL GW finality.

    The gameweek must be officially final per the established finality authority (every
    fixture of the gameweek finished), and every predicted fixture leg must have an
    attached finalized player outcome with non-NULL points. A partial double gameweek or
    an unwitnessed gameweek is never scored; NULL is never zero.
    """
    if not fixture_ids:
        return {"attached": False, "reason": "blank gameweek: no fixture legs"}
    final = _official_gameweek_final(con, season, gw)
    if final is not True:
        return {
            "attached": False,
            "reason": (
                "official gameweek finality not witnessed: no finished-fixture witness "
                "exists for this gameweek, or the gameweek is not fully finished"
            ),
        }
    legs: list[dict[str, Any]] = []
    recorded_total = 0
    replayed_total = 0
    for fixture in fixture_ids:
        row = con.execute(
            """
            SELECT epoch_us(attached_at), total_points_as_recorded, points_under_rules_2026_27
            FROM ledger_outcome_player_fixture
            WHERE season = ? AND code = ? AND fixture = ?
            """,
            [season, code, fixture],
        ).fetchone()
        if row is None or row[1] is None or row[2] is None:
            return {
                "attached": False,
                "reason": "finalized outcome missing or incomplete for at least one fixture leg",
            }
        legs.append(
            {
                "fixture": fixture,
                "attached_at": _iso(int(row[0])),
                "total_points_as_recorded": int(row[1]),
                "points_under_rules_2026_27": int(row[2]),
            }
        )
        recorded_total += int(row[1])
        replayed_total += int(row[2])
    return {
        "attached": True,
        "legs": legs,
        "total_points_as_recorded": recorded_total,
        "points_under_rules_2026_27": replayed_total,
    }


def _fixture_selectors(modes: dict[str, Any]) -> dict[int, str]:
    """Per-fixture selector reasons from the primary's SDP environment provenance."""
    env = modes.get("football_environment.provenance")
    if not isinstance(env, str):
        return {}
    try:
        provenance = json.loads(env)
        decisions = provenance["decisions"]
    except (ValueError, KeyError, TypeError):
        return {}
    selectors: dict[int, str] = {}
    if isinstance(decisions, list):
        for decision in decisions:
            if isinstance(decision, dict) and "fixture" in decision and "selector" in decision:
                try:
                    selectors[int(decision["fixture"])] = str(decision["selector"])
                except (TypeError, ValueError):
                    continue
    return selectors


_ROLES: Final[tuple[tuple[str, str, str], ...]] = (
    ("primary", "primary_run_id", "primary_artifact_sha256"),
    ("shadow", "shadow_run_id", "shadow_artifact_sha256"),
)


def pair_team_fixture_rows(
    con: duckdb.DuckDBPyConnection, pair: dict[str, Any]
) -> list[dict[str, Any]]:
    """One row per run side x club side x fixture, joined to its separately attached outcome.

    These are exactly the retained rows a Goal NLL / CS-Brier / CRPS / calibration metric
    consumes: the stored goals-for PMF beside the official signed score, only when the
    outcome has been attached by the authoritative finalization path.
    """
    rows: list[dict[str, Any]] = []
    for role, run_id_key, hash_key in _ROLES:
        run_id = str(pair[run_id_key])
        stored_modes = con.execute(
            "SELECT component_modes FROM ledger_forecast_run WHERE run_id = ?", [run_id]
        ).fetchone()
        modes = json.loads(str(stored_modes[0])) if stored_modes is not None else {}
        selectors = _fixture_selectors(modes) if role == "primary" else {}
        for row in con.execute(
            """
            SELECT season, gw, fixture, epoch_us(kickoff_time), team_id, team_code,
                   opponent_team_id, was_home, lambda_for, lambda_against,
                   probability_clean_sheet, goals_for_distribution, stage_a_league_average_team
            FROM ledger_prediction_team_fixture WHERE run_id = ?
            ORDER BY season, fixture, team_id
            """,
            [run_id],
        ).fetchall():
            season, gw, fixture = str(row[0]), int(row[1]), int(row[2])
            rows.append(
                {
                    "role": role,
                    "run_id": run_id,
                    "artifact_sha256": str(pair[hash_key]),
                    "season": season,
                    "gw": gw,
                    "fixture": fixture,
                    "kickoff_time": _iso(int(row[3])),
                    "team_id": int(row[4]),
                    "team_code": row[5],
                    "opponent_team_id": int(row[6]),
                    "was_home": bool(row[7]),
                    "lambda_for": row[8],
                    "lambda_against": row[9],
                    "probability_clean_sheet": row[10],
                    "goals_for_distribution": list(row[11]),
                    "stage_a_league_average_team": bool(row[12]),
                    "selector": selectors.get(fixture),
                    "outcome": _outcome_team(con, season, fixture, int(row[4])),
                }
            )
    return rows


def pair_player_fixture_rows(
    con: duckdb.DuckDBPyConnection, pair: dict[str, Any]
) -> list[dict[str, Any]]:
    """One row per run x player-fixture, joined to its separately attached outcome."""
    rows: list[dict[str, Any]] = []
    for role, run_id_key, hash_key in _ROLES:
        run_id = str(pair[run_id_key])
        for row in con.execute(
            """
            SELECT season, gw, fixture, code, epoch_us(kickoff_time), position, team_id,
                   team_code, opponent_team_id, was_home, expected_points, expected_bonus,
                   distribution, stage_a_league_average_team
            FROM ledger_prediction_player_fixture WHERE run_id = ?
            ORDER BY season, fixture, code
            """,
            [run_id],
        ).fetchall():
            season, fixture, code = str(row[0]), int(row[2]), int(row[3])
            rows.append(
                {
                    "role": role,
                    "run_id": run_id,
                    "artifact_sha256": str(pair[hash_key]),
                    "season": season,
                    "gw": int(row[1]),
                    "fixture": fixture,
                    "code": code,
                    "kickoff_time": _iso(int(row[4])),
                    "position": str(row[5]),
                    "team_id": int(row[6]),
                    "team_code": row[7],
                    "opponent_team_id": int(row[8]),
                    "was_home": bool(row[9]),
                    "expected_points": row[10],
                    "expected_bonus": row[11],
                    "distribution": list(row[12]),
                    "stage_a_league_average_team": bool(row[13]),
                    "outcome": _outcome_player(con, season, fixture, code),
                }
            )
    return rows


def pair_player_gameweek_rows(
    con: duckdb.DuckDBPyConnection, pair: dict[str, Any]
) -> list[dict[str, Any]]:
    """One row per run x player-gameweek, scorable only when every fixture leg is final.

    The stored gameweek distribution is already the exact convolution of its fixture legs,
    so this grain serves within-gameweek ranking (Spearman) and signed error metrics
    directly; the gameweek actual is the sum of its separately attached finalized leg
    outcomes. Absent or partial evidence stays unattached (never zero-filled).
    """
    rows: list[dict[str, Any]] = []
    for role, run_id_key, hash_key in _ROLES:
        run_id = str(pair[run_id_key])
        for row in con.execute(
            """
            SELECT season, gw, code, fixture_ids, position, team_id, team_code,
                   expected_points, availability_adjusted_expected_points, distribution
            FROM ledger_prediction_player_gameweek WHERE run_id = ?
            ORDER BY season, gw, code
            """,
            [run_id],
        ).fetchall():
            season, code = str(row[0]), int(row[2])
            fixture_ids = tuple(int(f) for f in json.loads(str(row[3])))
            rows.append(
                {
                    "role": role,
                    "run_id": run_id,
                    "artifact_sha256": str(pair[hash_key]),
                    "season": season,
                    "gw": int(row[1]),
                    "code": code,
                    "position": str(row[4]),
                    "team_id": int(row[5]),
                    "team_code": row[6],
                    "fixture_ids": list(fixture_ids),
                    "expected_points": row[7],
                    "availability_adjusted_expected_points": row[8],
                    "distribution": list(row[9]),
                    "outcome": _outcome_player_gameweek(
                        con, season, int(row[1]), code, fixture_ids
                    ),
                }
            )
    return rows


__all__ = [
    "PAIR_SCHEMA",
    "ArtifactNotCanonicalError",
    "DeadlineEvidenceError",
    "PairConflictError",
    "PairVerificationError",
    "SdpEvidenceError",
    "UnknownPairRunError",
    "derive_prediction_id",
    "ensure_sdp_evidence_schema",
    "list_pairs",
    "load_pair",
    "pair_player_fixture_rows",
    "pair_player_gameweek_rows",
    "pair_team_fixture_rows",
    "record_pair",
]
