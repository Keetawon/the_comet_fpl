"""Executable contract for the provisional-only republish.

The full refresh rebuilds every read model from the operational database. This path may
move exactly three published files and must carry the rest forward byte for byte, so the
tests are mostly about what it refuses: a fixture the public already calls finalized, a
player outside the published forecast population, a tampered object, a capture that is not
a completed-match capture, and any attempt to rewrite a forecast read model.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fpl.publish import provisional_republish as rp
from fpl.publish import r2_dashboard as r2
from fpl.publish.dashboard_json import (
    _file_row_count,
    _manifest_content_sha256,
    validate_dashboard_json,
)
from fpl.publish.export import _canonical_json_bytes, _sha256_bytes
from fpl.publish.team_form import refresh_team_forms

from .test_r2_dashboard import add_rest_summary, generation, seal_receipt  # noqa: F401

BASE = "https://data.example.com"
SEASON = "2026-27"
KICKOFF = "2026-10-04T14:00:00Z"
FIXTURE = 501
CODE = 1
ELEMENT = 10


def _bootstrap(*, code: int = CODE) -> dict[str, Any]:
    return {
        "events": [{"id": 6, "name": "Gameweek 6", "deadline_time": KICKOFF, "finished": False}],
        "teams": [
            {"id": 1, "code": 1, "name": "Alpha", "short_name": "ALP"},
            {"id": 2, "code": 2, "name": "Beta", "short_name": "BET"},
        ],
        "elements": [
            {
                "id": ELEMENT,
                "code": code,
                "web_name": "Preserved Player",
                "element_type": 3,
                "team": 1,
                "now_cost": 75,
                "status": "a",
            }
        ],
    }


def _fixtures(*, finished: bool = False) -> list[dict[str, Any]]:
    return [
        {
            "id": FIXTURE,
            "code": 9501,
            "event": 6,
            "finished": finished,
            "finished_provisional": True,
            "kickoff_time": KICKOFF,
            "team_h": 1,
            "team_a": 2,
            "team_h_score": 2,
            "team_a_score": 1,
            "team_h_difficulty": 2,
            "team_a_difficulty": 4,
            "pulse_id": 7501,
        }
    ]


def _summary(*, element: int = ELEMENT) -> dict[str, Any]:
    return {
        "fixtures": [],
        "history": [
            {
                "element": element,
                "fixture": FIXTURE,
                "opponent_team": 2,
                "total_points": 8,
                "was_home": True,
                "kickoff_time": KICKOFF,
                "round": 6,
                "minutes": 90,
                "starts": 1,
                "goals_scored": 1,
                "assists": 0,
                "clean_sheets": 0,
                "goals_conceded": 1,
                "saves": 0,
                "penalties_saved": 0,
                "penalties_missed": 0,
                "own_goals": 0,
                "yellow_cards": 0,
                "red_cards": 0,
                "bonus": 2,
                "bps": 31,
                "expected_goals": 0.55,
                "expected_assists": 0.12,
                "expected_goals_conceded": 1.1,
                "defensive_contribution": 4,
                "threat": 42.0,
                "creativity": 9.5,
                "influence": 38.0,
                "value": 75,
                "selected": 1000,
                "transfers_in": 5,
                "transfers_out": 1,
            }
        ],
        "history_past": [],
    }


def capture_package(
    directory: Path,
    *,
    summary: dict[str, Any] | None = None,
    player_history: bool = True,
    code: int = CODE,
) -> Path:
    """One committed capture package, checksummed exactly as the workflow commits it."""
    directory.mkdir(parents=True)
    paths = []
    for name, payload in (
        ("bootstrap-static.json.gz", _bootstrap(code=code)),
        ("fixtures.json.gz", _fixtures()),
        ("event-live-6.json.gz", {"elements": []}),
    ):
        target = directory / name
        with gzip.open(target, "wt", encoding="utf-8") as stream:
            json.dump(payload, stream)
        paths.append(target)
    if player_history:
        body = json.dumps(summary or _summary()).encode()
        archive_path = directory / "element-summary.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            member = tarfile.TarInfo(f"{ELEMENT}.json")
            member.size = len(body)
            archive.addfile(member, io.BytesIO(body))
        paths.append(archive_path)
    (directory / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in paths
        ),
        encoding="utf-8",
    )
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "captured_at": "2026-10-05T01:00:00Z",
                "season": SEASON,
                "history_through_gw": 6,
                "element_payloads": 1 if player_history else 0,
                "player_fixture_rows": 1 if player_history else 0,
            }
        ),
        encoding="utf-8",
    )
    return directory


def rewrite(data: Path, filename: str, document: dict[str, Any]) -> None:
    """Replace one published document and keep its manifest entry honest."""
    body = _canonical_json_bytes(document, indent=2)
    (data / filename).write_bytes(body)
    manifest = json.loads((data / "manifest.json").read_bytes())
    manifest["files"][filename] = {
        "row_count": _file_row_count(document, filename),
        "sha256": _sha256_bytes(body),
    }
    manifest["content_sha256"] = _manifest_content_sha256(manifest)
    (data / "manifest.json").write_bytes(_canonical_json_bytes(manifest, indent=2))


def read_document(data: Path, filename: str) -> Any:
    return json.loads((data / filename).read_bytes())


@pytest.fixture
def published(generation: Path) -> Path:  # noqa: F811
    """A published generation whose forecast population covers both clubs in the capture."""
    data = generation / "public/data"
    matrix = read_document(data, "fixture_matrix.json")
    matrix["teams"] = list(
        refresh_team_forms(
            [
                {"season": SEASON, "team_code": 1, "preserved": "fixture"},
                {"season": SEASON, "team_code": 2, "preserved": "fixture"},
            ],
            read_document(data, "team_actuals.json")["teams"],
            read_document(data, "team_provisional_actuals.json")["teams"],
        )
    )
    rewrite(data, "fixture_matrix.json", matrix)
    validate_dashboard_json(data)
    seal_receipt(generation)
    add_rest_summary(generation)
    return generation


def serve(root: Path, *, corrupt: str | None = None) -> rp.Reader:
    """Serve a generation the way R2 serves it: gzip bodies under an immutable prefix."""
    compressed, inventory = r2.prepare_generation(root, root)
    digest = r2.inventory_hash(inventory)
    pointer = {
        "schema": "fpl.public-dashboard-current",
        "schema_version": 1,
        "generation_sha256": digest,
        "base_path": f"generations/{digest}",
        "published_at": datetime(2026, 10, 5, 2, tzinfo=UTC).isoformat(),
        "files": inventory,
    }
    r2.validate_pointer(pointer)
    objects = {f"{BASE}/current.json": _canonical_json_bytes(pointer, indent=2)}
    for relative, body in compressed.items():
        if relative == corrupt:
            body = gzip.compress(b'{"schema": "tampered"}')
        objects[f"{BASE}/{pointer['base_path']}/{relative}"] = body

    def read(url: str) -> bytes:
        return objects[url]

    return read


def restate(published: Path, capture: Path, tmp_path: Path, name: str = "run") -> dict[str, Any]:
    fetched = rp.fetch_published_generation(BASE, read=serve(published))
    restatement = rp.build_restatement(capture, fetched, scratch=tmp_path / f"{name}-capture")
    return rp.restate_generation(fetched, restatement, tmp_path / f"{name}-out")


def test_a_completed_fixture_the_public_lacks_reaches_the_preview(
    published: Path, tmp_path: Path
) -> None:
    capture = capture_package(tmp_path / "capture")
    receipt = restate(published, capture, tmp_path)
    # The two previews, plus the team-form summaries those rows own.
    assert receipt["restated_files"] == [
        "fixture_matrix.json",
        "player_provisional_actuals.json",
        "team_provisional_actuals.json",
    ]
    data = tmp_path / "run-out/public/data"
    players = read_document(data, "player_provisional_actuals.json")
    assert players["captured_at"] == "2026-10-05T01:00:00+00:00"
    assert [(r["season"], r["code"]) for r in players["players"]] == [(SEASON, CODE)]
    row = players["players"][0]["actuals"][0]
    assert (row["gw"], row["fixture"], row["minutes"], row["goals_scored"]) == (6, FIXTURE, 90, 1)
    # Identity comes from the capture's own club dimension, never the player's current club.
    assert (row["team_code"], row["team_short_name"]) == (1, "ALP")
    assert (row["opponent_team_code"], row["opponent_short_name"]) == (2, "BET")
    # The provisional points measure stays separately named from the finalized one.
    assert row["total_points_as_recorded"] == 8
    assert "points_under_rules_2026_27" not in row
    teams = read_document(data, "team_provisional_actuals.json")
    assert [(r["season"], r["team_code"]) for r in teams["teams"]] == [(SEASON, 1), (SEASON, 2)]
    assert [t["actuals"][0]["goals_for"] for t in teams["teams"]] == [2, 1]
    # One published finalized fixture, named by both ledgers, excluded once.
    assert receipt["capture"]["published_finalized_fixtures_excluded"] == 1
    assert receipt["forecast_regenerated"] is False
    # The form the published preview owns moved with it, through the shared function the
    # full export uses, so the freshness gate reconciles instead of refusing the package.
    base = read_document(published / "public/data", "fixture_matrix.json")["teams"]
    assert read_document(data, "fixture_matrix.json")["teams"] != base
    assert receipt["observed_freshness_reconciliation"]["team_form"] == {
        "reconciled_rows": 2,
        "source": "published_team_actuals",
    }


def test_a_fixture_the_public_already_calls_finalized_is_never_re_previewed(
    published: Path, tmp_path: Path
) -> None:
    """The handoff is fixture-atomic: one published finalized side retires the preview."""
    data = published / "public/data"
    teams = read_document(data, "team_actuals.json")
    teams["teams"].append(
        {
            "season": SEASON,
            "team_code": 1,
            "actuals": [
                {
                    "gw": 6,
                    "fixture": FIXTURE,
                    "kickoff_time": "2026-10-04T14:00:00+00:00",
                    "opponent_team_code": 2,
                    "opponent_short_name": "BET",
                    "was_home": True,
                    "goals_for": 2,
                    "goals_against": 1,
                    "team_xg": 1.4,
                    "team_xgc": 1.1,
                    "team_bps": 60,
                    "defensive_contribution": 41,
                }
            ],
        }
    )
    rewrite(data, "team_actuals.json", teams)
    # A finalized row the public carries owns its club's form, exactly as a provisional one
    # would, so the base stays self-consistent before it is restated.
    matrix = read_document(data, "fixture_matrix.json")
    matrix["teams"] = list(
        refresh_team_forms(
            matrix["teams"],
            teams["teams"],
            read_document(data, "team_provisional_actuals.json")["teams"],
        )
    )
    rewrite(data, "fixture_matrix.json", matrix)
    seal_receipt(published)
    receipt = restate(published, capture_package(tmp_path / "capture"), tmp_path)
    assert receipt["restated_files"] == []
    assert read_document(tmp_path / "run-out/public/data", "player_provisional_actuals.json") == {
        "schema": "fpl.dashboard-player-provisional-actuals",
        "json_schema_version": 1,
        "captured_at": None,
        "players": [],
    }


def test_a_preview_on_only_one_side_is_refused_rather_than_half_published(
    published: Path, tmp_path: Path
) -> None:
    """The envelope pins one capture time across both documents and requires it to be null
    when a document is empty, so a lopsided pair cannot be published at all. Only a base
    whose forecast population covers no captured player reaches that state."""
    capture = capture_package(tmp_path / "capture", code=4242)
    fetched = rp.fetch_published_generation(BASE, read=serve(published))
    with pytest.raises(rp.ProvisionalRepublishError, match="preview on only one side"):
        rp.build_restatement(capture, fetched, scratch=tmp_path / "capture-db")


def test_a_tampered_published_object_is_refused_before_any_restatement(
    published: Path, tmp_path: Path
) -> None:
    read = serve(published, corrupt="data/players.json")
    with pytest.raises(rp.ProvisionalRepublishError, match="does not match the pointer inventory"):
        rp.fetch_published_generation(BASE, read=read)


def test_an_incomplete_public_file_set_is_refused(generation: Path) -> None:  # noqa: F811
    """A generation published before the rest sidecar is not a base this path may restate."""
    with pytest.raises(rp.ProvisionalRepublishError, match="complete public file set"):
        rp.fetch_published_generation(BASE, read=serve(generation))


def test_a_plain_http_base_is_refused(published: Path) -> None:
    with pytest.raises(rp.ProvisionalRepublishError, match="must be HTTPS"):
        rp.fetch_published_generation("http://data.example.com", read=serve(published))


def test_a_daily_capture_is_not_a_completed_match_capture(published: Path, tmp_path: Path) -> None:
    capture = capture_package(tmp_path / "capture", player_history=False)
    fetched = rp.fetch_published_generation(BASE, read=serve(published))
    with pytest.raises(rp.ProvisionalRepublishError, match="requires a player-history capture"):
        rp.build_restatement(capture, fetched, scratch=tmp_path / "capture-db")


def test_the_restatement_may_not_rewrite_a_forecast_read_model(
    published: Path, tmp_path: Path
) -> None:
    fetched = rp.fetch_published_generation(BASE, read=serve(published))
    restatement = rp.build_restatement(
        capture_package(tmp_path / "capture"), fetched, scratch=tmp_path / "capture-db"
    )
    doctored = replace(
        restatement,
        documents={**restatement.documents, "players.json": b'{"schema": "forged"}'},
    )
    with pytest.raises(rp.ProvisionalRepublishError, match=r"may not rewrite players\.json"):
        rp.restate_generation(fetched, doctored, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_every_other_published_file_is_carried_forward_byte_for_byte(
    published: Path, tmp_path: Path
) -> None:
    fetched = rp.fetch_published_generation(BASE, read=serve(published))
    receipt = restate(published, capture_package(tmp_path / "capture"), tmp_path)
    data = tmp_path / "run-out/public/data"
    moved = set(receipt["restated_files"]) | {"manifest.json"}
    for relative, body in fetched.files.items():
        name = relative.removeprefix("data/")
        target = (
            (data / name)
            if relative.startswith("data/")
            else (tmp_path / "run-out/public" / relative)
        )
        if name in moved:
            continue
        assert target.read_bytes() == body, name
    # The restated generation is a complete, independently valid published generation.
    assert (
        validate_dashboard_json(data)["content_sha256"]
        == receipt["public_package"]["manifest_content_sha256"]
    )
