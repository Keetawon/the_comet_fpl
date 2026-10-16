"""Restate ONLY the provisional preview of an already-published dashboard generation.

The full refresh rebuilds everything from the operational database, so a completed match
reaches the public site only when that machine runs. This path exists for the hours in
between: it takes the generation the public is already being served, rebuilds the two
provisional preview documents from a committed completed-match capture, and republishes
the result with every other file carried forward byte for byte.

What that boundary buys is that nothing a forecast depends on can move here. No model, no
xP, no PMF, no ledger vintage, no optimizer plan, no finalized outcome and no monitoring
score is recomputed, because none of them is an input: the provisional facts are forbidden
from reaching any of them, and this job cannot write where they live. It is the same
preview the full refresh publishes, arriving earlier.

Three files may change, and the third is not a choice: `fixture_matrix.json` carries the
team-form summaries the published provisional rows own, and `check_observed_freshness`
already refuses a package whose forms disagree with its own ended fixtures, so the forms
are recomputed from the restated rows by the same shared function the full export uses.

The finalized anti-join comes from the published `player_actuals.json` and
`team_actuals.json` rather than the ledger this job cannot see. That substitution is
conservative in the only direction that matters: a fixture the public already carries as
finalized is removed from the preview, and no fixture is ever added to it.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import polars as pl

from fpl.ingest.snapshot_files import load_directory
from fpl.publish.contract import SEMANTIC_CONTRACT_V6
from fpl.publish.dashboard_json import (
    PLAYER_PROVISIONAL_ACTUALS_FILENAME,
    PLAYER_PROVISIONAL_ACTUALS_SCHEMA,
    PROVISIONAL_ACTUALS_JSON_SCHEMA_VERSION,
    TEAM_PROVISIONAL_ACTUALS_FILENAME,
    TEAM_PROVISIONAL_ACTUALS_SCHEMA,
    _build_player_provisional_actuals,
    _build_team_provisional_actuals,
    _file_row_count,
    _manifest_content_sha256,
    validate_dashboard_json,
)
from fpl.publish.dashboard_refresh import check_observed_freshness
from fpl.publish.export import (
    _canonical_json_bytes,
    _contract_query,
    _sha256_bytes,
    _strict_json_loads,
)
from fpl.publish.provisional_sql import (
    capture_identity_queries,
    finalized_fixture_union,
    provisional_observation_queries,
)
from fpl.publish.r2_dashboard import PUBLIC_FILES, validate_pointer
from fpl.publish.team_form import refresh_team_forms
from fpl.storage.db import initialise

GENERATION_SCHEMA: Final = "fpl.sdp-dashboard-generation/v1"
RESTATEMENT_SCHEMA: Final = "fpl.dashboard-provisional-restatement/v1"
# Exactly the files this path may rewrite. Anything else is carried forward byte for byte,
# and the restated generation is rejected if that is not what happened.
RESTATED_FILES: Final[frozenset[str]] = frozenset(
    {
        PLAYER_PROVISIONAL_ACTUALS_FILENAME,
        TEAM_PROVISIONAL_ACTUALS_FILENAME,
        "fixture_matrix.json",
        "manifest.json",
    }
)
# Bounds that stop a wrong base URL from streaming without end. The published
# all-vintage `players.json` is the largest file and grows with every recorded forecast
# run, so the per-file bound is generous and the whole-generation bound is the real guard.
_POINTER_LIMIT: Final = 65_536
_FILE_LIMIT: Final = 512 * 1024 * 1024
_GENERATION_LIMIT: Final = 1024 * 1024 * 1024

Reader = Callable[[str], bytes]


class ProvisionalRepublishError(RuntimeError):
    """A restatement that cannot be proved correct is refused, never published."""


@dataclass(frozen=True)
class PublishedGeneration:
    """The exact bytes the public is being served, verified against its own pointer."""

    pointer: dict[str, Any]
    files: dict[str, bytes]

    @property
    def generation_sha256(self) -> str:
        return str(self.pointer["generation_sha256"])

    def data(self, filename: str) -> bytes:
        return self.files[f"data/{filename}"]

    def document(self, filename: str) -> Any:
        return _strict_json_loads(self.data(filename).decode("utf-8"))


@dataclass(frozen=True)
class Restatement:
    """One restated preview, with the evidence behind every number it changed."""

    documents: dict[str, bytes]
    captured_at: str | None
    player_rows: int
    team_rows: int
    player_fixtures: int
    team_fixtures: int
    finalized_fixtures: int
    capture_id: str
    season: str


def fetch_published_generation(base_url: str, *, read: Reader) -> PublishedGeneration:
    """Read the live pointer and its generation, verifying every file against it."""
    base = base_url.rstrip("/")
    if not base.startswith("https://"):
        raise ProvisionalRepublishError("the published dashboard base URL must be HTTPS")
    body = _decode(read(f"{base}/current.json"))
    if len(body) > _POINTER_LIMIT:
        raise ProvisionalRepublishError("published pointer exceeds its declared bound")
    pointer = _strict_json_loads(body.decode("utf-8"))
    validate_pointer(pointer)
    if frozenset(pointer["files"]) != PUBLIC_FILES:
        raise ProvisionalRepublishError(
            "a provisional restatement requires the current complete public file set"
        )
    declared = sum(int(entry["size_bytes"]) for entry in pointer["files"].values())
    if declared > _GENERATION_LIMIT:
        raise ProvisionalRepublishError("the published generation exceeds its declared bound")
    files: dict[str, bytes] = {}
    for relative, entry in sorted(pointer["files"].items()):
        if entry["size_bytes"] > _FILE_LIMIT:
            raise ProvisionalRepublishError(f"published file {relative} exceeds its bound")
        content = _decode(read(f"{base}/{pointer['base_path']}/{relative}"))
        if (
            hashlib.sha256(content).hexdigest() != entry["sha256"]
            or len(content) != entry["size_bytes"]
        ):
            raise ProvisionalRepublishError(
                f"published file {relative} does not match the pointer inventory"
            )
        files[relative] = content
    return PublishedGeneration(pointer=pointer, files=files)


def https_reader(timeout: float = 30.0) -> Reader:
    """Read published objects over HTTPS. No credential is needed or sent: the bucket's
    read side is public, and a restatement proves the bytes by hash, not by trust."""
    import httpx

    def read(url: str) -> bytes:
        response = httpx.get(url, timeout=timeout, follow_redirects=False)
        response.raise_for_status()
        return bytes(response.content)

    return read


def _decode(body: bytes) -> bytes:
    """The objects are stored gzip-encoded. A client that negotiated the encoding away has
    already decompressed; one that did not hands us the stored bytes."""
    return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body


def _finalized_fixtures(generation: PublishedGeneration) -> set[tuple[str, int]]:
    """Fixtures the public already carries as finalized, from both published ledgers."""
    found: set[tuple[str, int]] = set()
    for filename, plural in (("player_actuals.json", "players"), ("team_actuals.json", "teams")):
        document = generation.document(filename)
        for row in document[plural]:
            for actual in row["actuals"]:
                found.add((str(row["season"]), int(actual["fixture"])))
    return found


def _eligible(generation: PublishedGeneration) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The published forecast populations, which bound what a preview may report."""
    players = generation.document("players.json")["players"]
    teams = generation.document("fixture_matrix.json")["teams"]
    return (
        pl.DataFrame(
            {
                "season": [str(r["season"]) for r in players],
                "code": [int(r["code"]) for r in players],
            },
            schema={"season": pl.Utf8, "code": pl.Int64},
        ),
        pl.DataFrame(
            {
                "season": [str(r["season"]) for r in teams],
                "team_code": [int(r["team_code"]) for r in teams],
            },
            schema={"season": pl.Utf8, "team_code": pl.Int64},
        ),
    )


def _frame(con: duckdb.DuckDBPyConnection, query: str) -> pl.DataFrame:
    # Arrow, never fetchall: a bare TIMESTAMPTZ through fetchall converts through pytz,
    # which this project does not depend on. An empty result keeps its declared schema.
    table = con.execute(query).to_arrow_table().replace_schema_metadata(None)
    return pl.from_arrow(table)  # type: ignore[return-value]


def build_restatement(
    capture: Path, generation: PublishedGeneration, *, scratch: Path
) -> Restatement:
    """Rebuild both preview documents from one committed capture and the published base."""
    scratch.mkdir(parents=True, exist_ok=False)
    database = scratch / "capture.duckdb"
    # A disposable database holding one capture and nothing else: no archive, no ledger,
    # no forecast. The provisional queries read only capture staging, so this is the
    # whole of their input besides the published finalized anti-join below.
    con = initialise(database)
    try:
        result = load_directory(con, capture)
        if result is None:
            raise ProvisionalRepublishError("the capture package was already loaded or is empty")
        # Read the stored identity back rather than restating it: the loader decides the
        # mode and season, and the provisional query selects on exactly these columns.
        stored = con.execute(
            "SELECT mode, season FROM snapshot_capture WHERE capture_id = ?",
            [result.capture_id],
        ).fetchone()
        if stored is None:
            raise ProvisionalRepublishError("the loaded capture is absent from snapshot_capture")
        mode, season = str(stored[0]), str(stored[1])
        if mode != "player-history":
            raise ProvisionalRepublishError(
                f"a provisional restatement requires a player-history capture, not {mode!r}"
            )
        finalized = _finalized_fixtures(generation)
        con.execute("CREATE TABLE published_finalized_fixture (season VARCHAR, fixture BIGINT)")
        con.executemany("INSERT INTO published_finalized_fixture VALUES (?, ?)", sorted(finalized))
        player_source, team_source = provisional_observation_queries(
            finalized_fixture_union(
                ["SELECT season, fixture FROM published_finalized_fixture"],
            )
        )
        # Project through the semantic contract exactly as the BI export does, so the
        # frames the shared builders receive carry the declared types rather than whatever
        # DuckDB inferred -- a provider DECIMAL is a float in the contract, for instance.
        frames = {
            name: _frame(con, _contract_query(SEMANTIC_CONTRACT_V6.table(name), source))
            for name, source in (
                ("fact_provisional_player_fixture_observation", player_source),
                ("fact_provisional_team_fixture_observation", team_source),
            )
        }
        team_season_sql, dim_fixture_sql = capture_identity_queries()
        team_season = _frame(
            con, _contract_query(SEMANTIC_CONTRACT_V6.table("dim_team_season"), team_season_sql)
        )
        dim_fixture = _frame(
            con, _contract_query(SEMANTIC_CONTRACT_V6.table("dim_fixture"), dim_fixture_sql)
        )
        player_provisional = frames["fact_provisional_player_fixture_observation"]
        team_provisional = frames["fact_provisional_team_fixture_observation"]
    finally:
        con.close()

    player_population, team_population = _eligible(generation)
    player_rows, player_captured = _build_player_provisional_actuals(
        player_provisional, team_season, dim_fixture, player_population
    )
    team_rows, team_captured = _build_team_provisional_actuals(
        team_provisional, team_season, dim_fixture, team_population
    )
    if (
        player_captured is not None
        and team_captured is not None
        and player_captured != team_captured
    ):
        raise ProvisionalRepublishError("the two preview documents disagree on their capture time")
    # Both documents describe one capture, and the published envelope requires them to say
    # so with one timestamp -- which must be null when a document has no rows. So the pair
    # is publishable only when both have rows or neither does, and a lopsided pair is
    # refused rather than published half-stated. It means the published forecast population
    # covers no player in any captured fixture, which no ordinary new registration causes:
    # a newcomer is simply absent from the player preview while his team mates remain.
    if bool(player_rows) != bool(team_rows):
        raise ProvisionalRepublishError(
            "the captured fixtures yield a preview on only one side: "
            f"{len(player_rows)} player and {len(team_rows)} club identities, so the "
            "published forecast population does not cover this capture"
        )
    captured_at = player_captured or team_captured
    documents = {
        PLAYER_PROVISIONAL_ACTUALS_FILENAME: _canonical_json_bytes(
            {
                "schema": PLAYER_PROVISIONAL_ACTUALS_SCHEMA,
                "json_schema_version": PROVISIONAL_ACTUALS_JSON_SCHEMA_VERSION,
                "captured_at": captured_at,
                "players": list(player_rows),
            },
            indent=2,
        ),
        TEAM_PROVISIONAL_ACTUALS_FILENAME: _canonical_json_bytes(
            {
                "schema": TEAM_PROVISIONAL_ACTUALS_SCHEMA,
                "json_schema_version": PROVISIONAL_ACTUALS_JSON_SCHEMA_VERSION,
                "captured_at": captured_at,
                "teams": list(team_rows),
            },
            indent=2,
        ),
    }
    return Restatement(
        documents=documents,
        captured_at=captured_at,
        player_rows=len(player_rows),
        team_rows=len(team_rows),
        player_fixtures=sum(len(row["actuals"]) for row in player_rows),
        team_fixtures=sum(len(row["actuals"]) for row in team_rows),
        finalized_fixtures=len(finalized),
        capture_id=result.capture_id,
        season=season,
    )


def restate_generation(
    generation: PublishedGeneration,
    restatement: Restatement,
    output: Path,
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Lay out a complete generation for the existing R2 publisher, and prove it."""
    stamp = as_of or datetime.now(UTC)
    unexpected = sorted(set(restatement.documents) - RESTATED_FILES)
    if unexpected:
        raise ProvisionalRepublishError(
            f"a provisional restatement may not rewrite {', '.join(unexpected)}"
        )
    data = output / "public" / "data"
    sdp = output / "public" / "sdp"
    data.mkdir(parents=True, exist_ok=False)
    sdp.mkdir(parents=True, exist_ok=False)
    for relative, body in generation.files.items():
        target = (
            (data / relative.removeprefix("data/"))
            if relative.startswith("data/")
            else (output / "public" / relative)
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)

    manifest = _strict_json_loads((data / "manifest.json").read_text(encoding="utf-8"))
    changed: list[str] = []
    for filename, body in restatement.documents.items():
        if (data / filename).read_bytes() == body:
            continue
        (data / filename).write_bytes(body)
        changed.append(filename)
        manifest["files"][filename] = {
            "row_count": _file_row_count(_strict_json_loads(body.decode("utf-8")), filename),
            "sha256": _sha256_bytes(body),
        }
    # The forms the restated rows own, from the same shared function the full export uses.
    matrix = _strict_json_loads((data / "fixture_matrix.json").read_text(encoding="utf-8"))
    refreshed = list(
        refresh_team_forms(
            matrix["teams"],
            _strict_json_loads((data / "team_actuals.json").read_text(encoding="utf-8"))["teams"],
            _strict_json_loads(
                (data / "team_provisional_actuals.json").read_text(encoding="utf-8")
            )["teams"],
        )
    )
    if refreshed != matrix["teams"]:
        matrix["teams"] = refreshed
        body = _canonical_json_bytes(matrix, indent=2)
        (data / "fixture_matrix.json").write_bytes(body)
        changed.append("fixture_matrix.json")
        manifest["files"]["fixture_matrix.json"] = {
            "row_count": _file_row_count(matrix, "fixture_matrix.json"),
            "sha256": _sha256_bytes(body),
        }
    manifest["generated_at"] = stamp.isoformat()
    manifest["content_sha256"] = _manifest_content_sha256(manifest)
    manifest_body = _canonical_json_bytes(manifest, indent=2)
    (data / "manifest.json").write_bytes(manifest_body)
    published = validate_dashboard_json(data)

    # Nothing outside the declared set may have moved, in either direction. `manifest.json`
    # is in that set because it hashes the others and always carries a new `generated_at`.
    for relative, body in generation.files.items():
        filename = relative.removeprefix("data/")
        if not relative.startswith("data/") or filename in RESTATED_FILES:
            continue
        if (data / filename).read_bytes() != body:
            raise ProvisionalRepublishError(
                f"a provisional restatement changed {filename}, which it may not touch"
            )
    sidecar = _strict_json_loads((sdp / "sdp_stats.json").read_text(encoding="utf-8"))
    freshness = check_observed_freshness(data, sidecar)
    receipt = {
        "schema": GENERATION_SCHEMA,
        "restatement_schema": RESTATEMENT_SCHEMA,
        "started_at": stamp.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "mode": "provisional_preview_restated_from_published_generation",
        "forecast_regenerated": False,
        "models_recomputed": False,
        "base_generation_sha256": generation.generation_sha256,
        "base_manifest_content_sha256": _strict_json_loads(
            generation.data("manifest.json").decode("utf-8")
        )["content_sha256"],
        "restated_files": sorted(set(changed)),
        "carried_forward_files": sorted(
            relative
            for relative in generation.files
            if relative.removeprefix("data/") not in changed
        ),
        "capture": {
            "capture_id": restatement.capture_id,
            "season": restatement.season,
            "captured_at": restatement.captured_at,
            "player_identities": restatement.player_rows,
            "player_fixture_rows": restatement.player_fixtures,
            "team_identities": restatement.team_rows,
            "team_fixture_rows": restatement.team_fixtures,
            "published_finalized_fixtures_excluded": restatement.finalized_fixtures,
        },
        "public_package": {"manifest_content_sha256": published["content_sha256"]},
        "observed_freshness_reconciliation": freshness,
    }
    for name, key in (
        ("sdp_stats", "sdp_sidecar"),
        ("competitive_schedule", "competitive_schedule"),
        ("rest_summary", "rest_summary"),
    ):
        body = (sdp / f"{name}.json").read_bytes()
        size = "byte_count" if name == "sdp_stats" else "bytes"
        receipt[key] = {"sha256": _sha256_bytes(body), size: len(body)}
    (output / "receipt.json").write_text(
        json.dumps(receipt, allow_nan=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return receipt
