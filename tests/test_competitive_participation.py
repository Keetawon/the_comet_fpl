"""Hand-computable participation cases; no provider calls or real database writes."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from fpl.config import load_sources, repo_root
from fpl.ingest.pl_sdp import PlSdpClient
from fpl.jobs import competitive_participation_pilot as pilot
from fpl.transform.competitive_participation import (
    ParticipationError,
    exact_crosswalk,
    parse_participation,
)

KICKOFF = datetime(2025, 9, 14, 15, tzinfo=UTC)
CAPTURE = datetime(2026, 9, 7, tzinfo=UTC)


def sample() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    match = {
        "matchId": "1",
        "season": "2025",
        "competitionId": "8",
        "kickoff": KICKOFF.isoformat(),
        "period": "FullTime",
        "resultType": "NormalResult",
        "clock": "96",
        "homeTeam": {"id": "3", "score": 1},
        "awayTeam": {"id": "31", "score": 0},
    }
    lineups = {}
    events = {}
    for side, node, team, shift in (("home", "homeTeam", 3, 0), ("away", "awayTeam", 31, 100)):
        lineups[f"{side}_team"] = {
            "teamId": str(team),
            "formation": {},
            "players": [
                {
                    "id": str(i + shift),
                    "firstName": "P",
                    "lastName": str(i),
                    "position": "Midfielder" if i <= 11 else "Substitute",
                }
                for i in range(1, 14)
            ],
        }
        events[node] = {"id": str(team), "subs": [], "cards": [], "goals": []}
    return match, lineups, events


def event(minute: int, *, period: str = "SecondHalf", **fields: Any) -> dict[str, Any]:
    stamp = KICKOFF + timedelta(minutes=minute + (15 if period != "FirstHalf" else 0))
    return {
        "period": period,
        "time": str(minute),
        "timestamp": stamp.strftime("%Y%m%dT%H%M%S%z"),
        **fields,
    }


def parsed_rows(
    data: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    result = parse_participation(*data, known_at=CAPTURE)
    return {row["provider_player_id"]: row for row in result["sides"][0]["rows"]}


def test_normal_complete_match_and_missing_formation_are_explicit() -> None:
    result = parse_participation(*sample(), known_at=CAPTURE)
    rows = result["sides"][0]["rows"]
    assert len(rows) == 13
    assert sum(row["nominal_minutes"] for row in rows) == 990
    assert sum(row["started"] for row in rows) == 11
    assert rows[-1]["nominal_minutes"] == 0
    assert not rows[-1]["appeared"]
    assert result["sides"][0]["formation"] == {}
    assert result["known_at"] == CAPTURE.isoformat()
    assert result["evidence_class"] == "retrospective_backfill_development"
    assert result["exact_rest_hours"] is None


@pytest.mark.parametrize(
    ("minute", "period", "off", "on"),
    [
        (68, "SecondHalf", 68, 22),
        (45, "SecondHalf", 45, 45),
        (48, "FirstHalf", 45, 45),
        (91, "SecondHalf", 90, 0),
    ],
)
def test_substitution_nominal_clock_not_fpl_rounding(
    minute: int, period: str, off: int, on: int
) -> None:
    data = sample()
    data[2]["homeTeam"]["subs"] = [event(minute, period=period, playerOffId="1", playerOnId="12")]
    before = deepcopy(data)
    rows = parsed_rows(data)
    assert rows[1]["nominal_minutes"] == off
    assert rows[12]["nominal_minutes"] == on
    assert rows[12]["appeared"]
    assert not rows[12]["started"]
    assert data == before


def test_substitute_can_later_be_substituted_off() -> None:
    data = sample()
    data[2]["homeTeam"]["subs"] = [
        event(61, playerOffId="1", playerOnId="12"),
        event(81, playerOffId="12", playerOnId="13"),
    ]
    rows = parsed_rows(data)
    assert rows[12]["nominal_intervals"] == [[61, 81]]
    assert rows[12]["nominal_minutes"] == 20
    assert rows[13]["nominal_minutes"] == 9


@pytest.mark.parametrize("card_type", ["Red", "SecondYellow"])
def test_active_dismissal_ends_only_that_players_field_interval(card_type: str) -> None:
    data = sample()
    data[2]["homeTeam"]["cards"] = [
        event(74, type="Yellow", playerId="1"),
        event(76, type=card_type, playerId="1"),
    ]
    rows = parsed_rows(data)
    assert rows[1]["nominal_minutes"] == 76
    assert rows[2]["nominal_minutes"] == 90
    assert sum(row["nominal_minutes"] for row in rows.values()) == 976


@pytest.mark.parametrize("card_type", ["Yellow", "Red", "SecondYellow"])
def test_bench_card_never_creates_appearance(card_type: str) -> None:
    data = sample()
    data[2]["homeTeam"]["cards"] = [event(76, type=card_type, playerId="12")]
    result = parse_participation(*data, known_at=CAPTURE)
    assert result["sides"][0]["discipline"][0]["context"] == "bench"
    row = next(r for r in result["sides"][0]["rows"] if r["provider_player_id"] == 12)
    assert not row["appeared"]
    assert row["nominal_minutes"] == 0


def test_already_substituted_players_red_card_does_not_change_minutes() -> None:
    data = sample()
    data[2]["homeTeam"]["subs"] = [event(61, playerOffId="1", playerOnId="12")]
    data[2]["homeTeam"]["cards"] = [event(76, type="Red", playerId="1")]
    assert parsed_rows(data)[1]["nominal_minutes"] == 61


@pytest.mark.parametrize("actor", [None, "999"])
def test_unattributed_dismissal_makes_side_minutes_null(actor: str | None) -> None:
    data = sample()
    data[2]["homeTeam"]["cards"] = [event(76, type="Red", playerId=actor)]
    result = parse_participation(*data, known_at=CAPTURE)
    assert result["sides"][0]["errors"]
    assert all(row["nominal_minutes"] is None for row in result["sides"][0]["rows"])
    assert result["sides"][1]["rows"][0]["nominal_minutes"] == 90


def test_null_yellow_actor_is_unattributed_not_a_field_dismissal() -> None:
    data = sample()
    data[2]["homeTeam"]["cards"] = [event(76, type="Yellow", playerId=None)]
    result = parse_participation(*data, known_at=CAPTURE)
    assert result["sides"][0]["discipline"][0]["context"] == "unattributed"
    assert not result["sides"][0]["errors"]


def test_extra_time_and_shootouts_have_distinct_duration_evidence() -> None:
    data = sample()
    data[0]["resultType"] = "PenaltyShootout"
    data[0]["clock"] = "99"
    assert parsed_rows(data)[1]["nominal_minutes"] == 90
    data[0]["clock"] = "122"
    assert parsed_rows(data)[1]["nominal_minutes"] is None
    data[2]["homeTeam"]["cards"] = [
        event(115, period="ExtraSecondHalf", type="Yellow", playerId="1")
    ]
    assert parsed_rows(data)[1]["nominal_minutes"] == 120
    data[2]["homeTeam"]["subs"] = [
        event(121, period="ExtraSecondHalf", playerOnId="12", playerOffId="1")
    ]
    assert parsed_rows(data)[12]["nominal_minutes"] == 0
    assert parsed_rows(data)[12]["appeared"]


@pytest.mark.parametrize("clock", [None, "unknown", "89"])
def test_unmeasured_completion_clock_never_fills_minutes(clock: str | None) -> None:
    data = sample()
    data[0]["clock"] = clock
    assert parsed_rows(data)[1]["nominal_minutes"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"time": "45+2"},
        {"time": "44"},
        {"period": "Unknown"},
        {"timestamp": "2025-09-14T16:00:00"},
        {"playerOnId": "999"},
        {"playerOnId": "1"},
        {"playerOffId": "12"},
        {"timestamp": "2027-09-14T16:00:00Z"},
        {"timestamp": "2025-09-13T16:00:00Z"},
    ],
)
def test_unknown_or_impossible_required_event_fails_closed(change: dict[str, Any]) -> None:
    data = sample()
    data[2]["homeTeam"]["subs"] = [event(61, playerOnId="12", playerOffId="1") | change]
    with pytest.raises(ParticipationError):
        parsed_rows(data)


def test_duplicate_and_simultaneous_actor_changes_are_not_silently_ordered() -> None:
    data = sample()
    first = event(61, playerOnId="12", playerOffId="1")
    data[2]["homeTeam"]["subs"] = [first, deepcopy(first)]
    with pytest.raises(ParticipationError, match="duplicate"):
        parsed_rows(data)
    data[2]["homeTeam"]["subs"][1] = event(61, playerOnId="13", playerOffId="12")
    with pytest.raises(ParticipationError, match="simultaneous"):
        parsed_rows(data)


def test_no_reentry_or_entry_after_bench_dismissal() -> None:
    data = sample()
    data[2]["homeTeam"]["cards"] = [event(55, type="Red", playerId="12")]
    data[2]["homeTeam"]["subs"] = [event(61, playerOnId="12", playerOffId="1")]
    with pytest.raises(ParticipationError, match="impossible"):
        parsed_rows(data)


@pytest.mark.parametrize("field", ["period", "resultType", "kickoff"])
def test_unknown_match_status_or_kickoff_not_accepted(field: str) -> None:
    data = sample()
    data[0][field] = None
    with pytest.raises(ParticipationError):
        parsed_rows(data)


def test_reciprocal_identity_and_duplicate_rosters_fail_closed() -> None:
    data = sample()
    data[2]["homeTeam"]["id"] = "31"
    with pytest.raises(ParticipationError, match="contradiction"):
        parsed_rows(data)
    data = sample()
    data[1]["home_team"]["players"].append(deepcopy(data[1]["home_team"]["players"][0]))
    with pytest.raises(ParticipationError, match="duplicate lineup"):
        parsed_rows(data)


def test_exact_opta_anchor_has_no_name_or_code_fallback_and_is_season_scoped() -> None:
    roster = [
        {"season": "2025-26", "opta_code": "p1", "code": 100},
        {"season": "2024-25", "opta_code": "p1", "code": 200},
        {"season": "2025-26", "opta_code": None, "code": 2, "name": "same"},
    ]
    mapped, errors = exact_crosswalk([1, 2], roster, season="2025-26")
    assert mapped == {1: 100, 2: None}
    assert len(errors) == 1
    roster.append({"season": "2025-26", "opta_code": "p1", "code": 999})
    assert exact_crosswalk([1], roster, season="2025-26")[0] == {1: None}


def test_deterministic_output_and_naive_capture_refusal() -> None:
    assert parse_participation(*sample(), known_at=CAPTURE) == parse_participation(
        *sample(), known_at=CAPTURE
    )
    with pytest.raises(ParticipationError, match="timezone-aware"):
        parse_participation(*sample(), known_at=CAPTURE.replace(tzinfo=None))


def test_event_actual_capture_not_later_bundle_time_bounds_event() -> None:
    data = sample()
    data[2]["homeTeam"]["subs"] = [event(61, playerOnId="12", playerOffId="1")]
    with pytest.raises(ParticipationError, match="actual capture"):
        parse_participation(*data, known_at=CAPTURE, event_known_at=KICKOFF + timedelta(minutes=60))


def test_simultaneous_independent_substitutions_are_order_invariant() -> None:
    data = sample()
    data[2]["homeTeam"]["subs"] = [
        event(61, playerOnId="12", playerOffId="1"),
        event(61, playerOnId="13", playerOffId="2"),
    ]
    before = parsed_rows(data)
    data[2]["homeTeam"]["subs"].reverse()
    assert parsed_rows(data) == before


def synthetic_reference() -> dict[str, Any]:
    registry = []
    facts = []
    for team, shift in ((3, 0), (31, 100)):
        for i in range(1, 14):
            registry.append({"season": "2025-26", "code": shift + i, "opta_code": f"p{shift + i}"})
            facts.append(
                {
                    "fixture": 1,
                    "code": shift + i,
                    "team_code": team,
                    "minutes": 90 if i <= 11 else 0,
                    "starts": int(i <= 11),
                    "kickoff_utc": KICKOFF.isoformat(),
                }
            )
    return {
        "registry": registry,
        "facts": facts,
        "identity_observed_at_utc": CAPTURE.isoformat(),
        "crosswalk": {
            "1": {
                "fixture": 1,
                "method": "identity_fallback",
                "kickoff_utc": KICKOFF.isoformat(),
                "home_team_code": 3,
                "away_team_code": 31,
                "home_score": 1,
                "away_score": 0,
            }
        },
    }


def synthetic_contract() -> dict[str, Any]:
    contract = pilot.load_contract(repo_root())
    return contract | {
        "expected_pl_match_ids": [1],
        "minimum_pl_matches": 1,
        "competitions": [{"provider_competition_id": 8}],
    }


def test_validation_denominator_includes_missing_provider_participant() -> None:
    parsed = parse_participation(*sample(), known_at=CAPTURE)
    reference = synthetic_reference()
    result = pilot.validate_results([deepcopy(parsed)], reference, synthetic_contract())
    assert result["passed"]
    assert result["duration_rows"] == 22
    reference["facts"].append(
        {
            "fixture": 1,
            "code": 999,
            "team_code": 3,
            "minutes": 10,
            "starts": 0,
            "kickoff_utc": KICKOFF.isoformat(),
        }
    )
    result = pilot.validate_results([parsed], reference, synthetic_contract())
    assert not result["passed"]
    assert result["duration_rows"] == 23
    assert result["duration_measured_coverage"] == 22 / 23
    assert any(row["code"] == 999 and row["difference_minutes"] is None for row in result["pairs"])


def test_validation_missing_fpl_or_sdp_minutes_is_not_zero_filled() -> None:
    parsed = parse_participation(*sample(), known_at=CAPTURE)
    reference = synthetic_reference()
    reference["facts"][0]["minutes"] = None
    parsed["sides"][1]["rows"][0]["nominal_minutes"] = None
    result = pilot.validate_results([parsed], reference, synthetic_contract())
    assert not result["passed"]
    assert result["duration_measured_coverage"] == 20 / 22


def test_validation_prior_membership_uses_event_cutoff_not_endseason_club() -> None:
    parsed = parse_participation(*sample(), known_at=CAPTURE)
    reference = synthetic_reference()
    reference["registry"][0]["team_code"] = 43
    reference["facts"].insert(
        0,
        {
            "fixture": 0,
            "code": 1,
            "team_code": 3,
            "minutes": 90,
            "starts": 1,
            "kickoff_utc": (KICKOFF - timedelta(days=7)).isoformat(),
        },
    )
    reference["facts"].append(
        {
            "fixture": 2,
            "code": 1,
            "team_code": 43,
            "minutes": 90,
            "starts": 1,
            "kickoff_utc": (KICKOFF + timedelta(days=7)).isoformat(),
        }
    )
    assert pilot.validate_results([parsed], reference, synthetic_contract())["passed"]
    assert parsed["sides"][0]["rows"][0]["prior_fpl_team_code"] == 3


def test_validation_rejects_real_prior_club_conflict() -> None:
    parsed = parse_participation(*sample(), known_at=CAPTURE)
    reference = synthetic_reference()
    reference["facts"].insert(
        0,
        {
            "fixture": 0,
            "code": 1,
            "team_code": 43,
            "minutes": 90,
            "starts": 1,
            "kickoff_utc": (KICKOFF - timedelta(days=7)).isoformat(),
        },
    )
    assert not pilot.validate_results([parsed], reference, synthetic_contract())["passed"]


def test_contract_hash_is_fixed() -> None:
    assert pilot.file_sha256(repo_root() / pilot.CONFIG) == pilot.CONFIG_SHA256
    assert (
        pilot.load_contract(repo_root())["validation"]["minimum_pl_duration_within_tolerance"]
        == 0.95
    )


def test_write_once_atomic_publication_and_failed_publication_preserve_old_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "raw.json"
    pilot.publish_bytes(path, b"original")
    with pytest.raises(FileExistsError):
        pilot.publish_bytes(path, b"replacement")
    assert path.read_bytes() == b"original"
    assert not list(tmp_path.glob("*.tmp"))


def test_recorder_retains_error_and_revised_raw_bytes_and_request_bound(tmp_path: Path) -> None:
    recorder = pilot.ResponseRecorder(tmp_path, 1)
    bodies = [b'{"error": "unavailable"}', b'{"value": 1}', b'{"value": 2}']

    def handle(request: httpx.Request) -> httpx.Response:
        body = bodies.pop(0)
        return httpx.Response(503 if b"error" in body else 200, content=body)

    with httpx.Client(
        transport=httpx.MockTransport(handle),
        event_hooks={"request": [recorder.request], "response": [recorder.response]},
    ) as http:
        for _ in range(3):
            http.get("https://provider.invalid/one")
        with pytest.raises(ParticipationError, match="bound"):
            http.get("https://provider.invalid/two")
    assert len(recorder.attempts) == len(recorder.responses) == 3
    assert [r["status"] for r in recorder.responses] == [503, 200, 200]
    assert len({r["sha256"] for r in recorder.responses}) == 3
    assert all(
        pilot.file_sha256(tmp_path / r["raw_file"]) == r["sha256"] for r in recorder.responses
    )


@pytest.mark.parametrize(
    "problem", ["duplicate", "missing_cursor", "wrong_competition", "wrong_season"]
)
def test_discovery_fails_closed_on_incomplete_or_conflicting_pages(problem: str) -> None:
    source = load_sources().pl_sdp
    assert source is not None
    match = sample()[0]
    if problem == "wrong_competition":
        match["competitionId"] = "5"
    if problem == "wrong_season":
        match["season"] = "2024"
    payload = {"data": [match], "pagination": {"_next": "more"}}
    if problem == "missing_cursor":
        payload.pop("pagination")
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        with PlSdpClient(
            config=source.model_copy(
                update={"min_request_interval_seconds": 0, "maximum_pages": 2}
            ),
            client=http,
        ) as client:
            with pytest.raises(ParticipationError):
                pilot.discover(client, synthetic_contract())


def test_mock_collection_retains_full_fixture_population_and_no_stats_requests(
    tmp_path: Path,
) -> None:
    source = load_sources().pl_sdp
    assert source is not None
    data = sample()
    requested = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if request.url.path.endswith("/lineups"):
            payload = data[1]
        elif request.url.path.endswith("/events"):
            payload = data[2]
        else:
            payload = {"data": [data[0]], "pagination": {"_next": None}}
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        report = pilot.collect(
            http,
            source.model_copy(update={"min_request_interval_seconds": 0}),
            synthetic_contract(),
            synthetic_reference(),
            tmp_path,
        )
    assert report["passed"]
    assert report["parsed_matches"] == report["selected_matches"] == 1
    assert len(requested) == 3
    assert all(not path.endswith("/stats") for path in requested)
    assert report["matches"][0]["source_versions"]["events"]["sha256"]


def test_dirty_worktree_guard_runs_before_any_database_or_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(pilot, "load_contract", lambda _: {})

    def dirty(_: Path) -> str:
        raise ParticipationError("dirty worktree")

    monkeypatch.setattr(pilot, "git_clean_head", dirty)
    with pytest.raises(ParticipationError, match="dirty"):
        pilot.run(root=tmp_path, db=tmp_path / "absent.duckdb", results=tmp_path / "absent-output")
    assert list(tmp_path.iterdir()) == []


def test_global_attempt_spacing_does_not_reset_between_clients(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    elapsed = [10.0]
    sleeps = []
    monkeypatch.setattr(pilot.time, "monotonic", lambda: elapsed[0])

    def advance(seconds: float) -> None:
        sleeps.append(seconds)
        elapsed[0] += seconds

    monkeypatch.setattr(pilot.time, "sleep", advance)
    recorder = pilot.ResponseRecorder(tmp_path, 2, 1.5)
    for url in ("https://provider.invalid/competition1", "https://provider.invalid/competition2"):
        recorder.request(httpx.Request("GET", url))
    assert sleeps == [1.5]
    assert elapsed[0] == 11.5


@pytest.mark.parametrize("mode", ["success", "capture_failure", "postflight_change"])
def test_runner_retains_final_result_and_provenance_without_real_io(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    db = tmp_path / "synthetic-not-a-real-db.bin"
    db.write_bytes(b"read-only reference sentinel")
    output = tmp_path / "pilot-20260907T120000Z"
    contract = {"maximum_distinct_provider_requests": 1, "season": "2025-26"}
    monkeypatch.setattr(pilot, "load_contract", lambda _: contract)
    monkeypatch.setattr(pilot, "git_clean_head", lambda _: "a" * 40)
    monkeypatch.setattr(pilot, "SOURCE_FILES", ())
    monkeypatch.setattr(pilot, "reference_data", lambda *_: synthetic_reference())

    def collect_no_network(*args: Any) -> dict[str, Any]:
        if mode == "capture_failure":
            raise ParticipationError("synthetic unavailable provider")
        if mode == "postflight_change":
            db.write_bytes(b"external writer changed synthetic sentinel")
        return {"passed": True, "capture_complete": True}

    monkeypatch.setattr(pilot, "collect", collect_no_network)
    report = pilot.run(root=root, db=db, results=output)
    assert (output / "result.json").is_file()
    assert (output / "provenance.json").is_file()
    assert not report["http_attempts"]
    assert report["passed"] == (mode == "success")
    if mode == "capture_failure":
        assert report["execution_failure"]["class"] == "ParticipationError"
        assert report["postflight"]["database_sha256"] == report["provenance"]["database_sha256"]
    if mode == "postflight_change":
        assert report["postflight_failure"]
        assert not report["completed"]
    with pytest.raises(ParticipationError, match="already exists"):
        pilot.run(root=root, db=db, results=output)


def test_midwrite_failure_does_not_publish_partial_raw(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "capture.raw"

    def fail(_: int) -> None:
        raise OSError("synthetic flush failure")

    monkeypatch.setattr(pilot.os, "fsync", fail)
    with pytest.raises(OSError, match="flush failure"):
        pilot.publish_bytes(path, b"not published")
    assert not path.exists()
    assert not list(tmp_path.iterdir())


def test_pre_kickoff_bench_discipline_not_field_participation() -> None:
    data = sample()
    data[2]["homeTeam"]["cards"] = [
        event(0, period="FirstHalf", type="Yellow", playerId="12")
        | {"timestamp": (KICKOFF - timedelta(minutes=1)).isoformat()}
    ]
    result = parse_participation(*data, known_at=CAPTURE)
    assert result["sides"][0]["discipline"][0]["context"] == "bench"
    assert not result["sides"][0]["rows"][-2]["appeared"]
