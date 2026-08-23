"""Offline tests for the public manager-team capture and ownership replay."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from fpl.config import LiveApiSource
from fpl.ingest.fpl_api import FplApiClient, ManagerEventPicks
from fpl.ingest.manager_team import (
    FREE_TRANSFER_SOURCE,
    ManagerCaptureError,
    ManagerCaptureErrorCode,
    ManagerCaptureExistsError,
    ManagerTeamCapture,
    capture_manager_team,
    manager_capture_bytes,
    manager_capture_sha256,
    official_selling_price,
    read_manager_capture,
    write_manager_capture_atomic,
)
from fpl.ingest.player_registry import selectable_player_registry_sha256

FIXTURES = Path(__file__).parent / "fixtures"
CAPTURED_AT = datetime(2026, 8, 23, 12, tzinfo=UTC)
MANAGER_CONFIG = LiveApiSource(
    base_url="https://fpl.test/api",
    endpoints={
        "bootstrap_static": "bootstrap-static/",
        "fixtures": "fixtures/",
        "element_summary": "element-summary/{element_id}/",
        "event_live": "event/{gw}/live/",
        "entry": "entry/{manager_id}/",
        "entry_event_picks": "entry/{manager_id}/event/{event}/picks/",
        "entry_transfers": "entry/{manager_id}/transfers/",
        "entry_history": "entry/{manager_id}/history/",
    },
    min_request_interval_seconds=0.0,
    timeout_seconds=5.0,
    max_retries=0,
    retry_backoff_base_seconds=0.0,
)


def _json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text("utf-8"))


def _current_bootstrap() -> dict[str, Any]:
    payload: dict[str, Any] = copy.deepcopy(_json("manager_bootstrap_deadline.json"))
    current_prices = {1: 48, 3: 44, 15: 47}
    for player in payload["elements"]:
        if player["id"] in current_prices:
            player["now_cost"] = current_prices[player["id"]]
    return payload


def _base_payloads() -> dict[str, Any]:
    return {
        "/api/bootstrap-static/": _current_bootstrap(),
        "/api/entry/42/": _json("manager_entry.json"),
        "/api/entry/42/event/1/picks/": _json("manager_picks_start.json"),
        "/api/entry/42/transfers/": _json("manager_transfers.json"),
        "/api/entry/42/history/": _json("manager_history.json"),
    }


@contextmanager
def _client(
    payloads: dict[str, Any],
    *,
    calls: list[str] | None = None,
) -> Iterator[FplApiClient]:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request.url.path)
        if request.url.path not in payloads:
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json=payloads[request.url.path])

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with FplApiClient(config=MANAGER_CONFIG, client=http) as client:
            yield client


def _write_deadline_snapshot(
    root: Path,
    bootstrap: dict[str, Any],
    *,
    captured_at: datetime = datetime(2026, 8, 21, 17, tzinfo=UTC),
) -> Path:
    directory = (
        root / "daily" / captured_at.date().isoformat() / captured_at.strftime("%Y-%m-%dT%H%M%SZ")
    )
    directory.mkdir(parents=True)
    payloads = {
        "bootstrap-static.json.gz": bootstrap,
        "fixtures.json.gz": [],
    }
    checksums: list[str] = []
    for filename, payload in payloads.items():
        path = directory / filename
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
        declared = (Path(root.name) / directory.relative_to(root) / filename).as_posix()
        checksums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {declared}")
    (directory / "SHA256SUMS").write_text("\n".join(checksums) + "\n", "utf-8")
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "captured_at": captured_at.isoformat().replace("+00:00", "Z"),
                "season": "2026-27",
            },
            sort_keys=True,
        ),
        "utf-8",
    )
    return directory


def _capture(
    tmp_path: Path,
    *,
    payloads: dict[str, Any] | None = None,
    deadline_bootstrap: dict[str, Any] | None = None,
    captured_at: datetime = CAPTURED_AT,
    calls: list[str] | None = None,
) -> ManagerTeamCapture:
    snapshots = tmp_path / "snapshots"
    _write_deadline_snapshot(
        snapshots,
        deadline_bootstrap or _json("manager_bootstrap_deadline.json"),
    )
    with _client(payloads or _base_payloads(), calls=calls) as client:
        return capture_manager_team(
            42,
            client=client,
            snapshots_root=snapshots,
            captured_at=captured_at,
        )


def test_picks_model_ignores_non_contract_prices() -> None:
    picks = ManagerEventPicks.model_validate(_json("manager_picks_start.json"))
    assert len(picks.picks) == 15
    assert not hasattr(picks.picks[0], "purchase_price")
    assert not hasattr(picks.picks[0], "selling_price")


def test_client_exposes_typed_public_manager_endpoints() -> None:
    with _client(_base_payloads()) as client:
        assert client.manager_entry(42).name == "Fixture XI"
        assert len(client.manager_event_picks(42, 1).picks) == 15
        assert len(client.manager_transfers(42)) == 2
        history = client.manager_history(42)
    assert [row.event for row in history.current] == [1]
    assert history.past[0].season_name == "2025/26"


def test_manager_capture_reconstructs_prices_bank_hits_and_stable_codes(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    capture = _capture(tmp_path, calls=calls)
    assert calls == [
        "/api/bootstrap-static/",
        "/api/entry/42/",
        "/api/entry/42/event/1/picks/",
        "/api/entry/42/transfers/",
        "/api/entry/42/history/",
    ]
    assert capture.manager_id == 42
    assert capture.picks_event == 1
    assert capture.planning_event == 2
    assert capture.bank_tenths == 44
    assert capture.squad_selling_value_tenths == 807
    assert capture.available_budget_tenths == 851
    assert capture.free_transfers_available == 0
    assert capture.free_transfers_source == FREE_TRANSFER_SOURCE
    assert capture.existing_hit_points == 4
    assert capture.post_picks_transfer_count == 2
    by_code = {player.code: player for player in capture.squad}
    assert set(by_code) == {*range(1001, 1014), 1016, 1017}
    assert (by_code[1001].purchase_price, by_code[1001].now_cost) == (45, 48)
    assert by_code[1001].selling_price == 46
    assert by_code[1003].selling_price == 44
    assert by_code[1016].purchase_price == 50
    assert by_code[1017].purchase_price == 72
    assert capture.provenance.latest_picks_sha256 == capture.provenance.start_picks_sha256
    assert capture.schema_version == 2
    assert capture.provenance.selectable_player_registry_sha256 == (
        selectable_player_registry_sha256(
            _current_bootstrap(),
            season="2026-27",
        )
    )
    assert capture.provenance.deadline_snapshot_relative_path.startswith("snapshots/daily/")
    assert capture.capture_id.startswith("manager-") and len(capture.capture_id) == 72


def test_registry_binding_ignores_volatile_stats_but_detects_roster_drift() -> None:
    bootstrap = _current_bootstrap()
    expected = selectable_player_registry_sha256(bootstrap, season="2026-27")
    volatile = copy.deepcopy(bootstrap)
    volatile["elements"][0]["total_points"] = 99
    volatile["elements"][0]["selected_by_percent"] = "52.1"
    assert selectable_player_registry_sha256(volatile, season="2026-27") == expected
    drifted = copy.deepcopy(bootstrap)
    drifted["elements"][0]["now_cost"] += 1
    assert selectable_player_registry_sha256(drifted, season="2026-27") != expected


def test_later_start_has_no_safe_public_purchase_price_provenance(tmp_path: Path) -> None:
    payloads = _base_payloads()
    bootstrap = copy.deepcopy(payloads["/api/bootstrap-static/"])
    bootstrap["events"][0]["is_current"] = False
    bootstrap["events"][1]["is_current"] = True
    bootstrap["events"][1]["is_next"] = False
    bootstrap["events"].append(
        {
            "id": 3,
            "name": "Gameweek 3",
            "deadline_time": "2026-09-04T17:30:00Z",
            "finished": False,
            "is_next": True,
        }
    )
    entry = copy.deepcopy(payloads["/api/entry/42/"])
    entry["started_event"] = 2
    entry["current_event"] = 2
    payloads["/api/bootstrap-static/"] = bootstrap
    payloads["/api/entry/42/"] = entry
    with pytest.raises(ManagerCaptureError) as raised:
        _capture(
            tmp_path,
            payloads=payloads,
            captured_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
        )
    assert raised.value.code is ManagerCaptureErrorCode.PUBLIC_PRICE_PROVENANCE_UNAVAILABLE
    assert "do not expose acquisition prices" in raised.value.detail


@pytest.mark.parametrize(
    ("purchase", "current", "expected"),
    [(50, 48, 48), (50, 50, 50), (50, 51, 50), (50, 52, 51), (50, 55, 52)],
)
def test_official_selling_price_half_profit_rounds_down(
    purchase: int, current: int, expected: int
) -> None:
    assert official_selling_price(purchase_price=purchase, current_price=current) == expected


def test_duplicate_squad_fails_after_all_public_inputs_are_fetched(tmp_path: Path) -> None:
    payloads = _base_payloads()
    picks = copy.deepcopy(payloads["/api/entry/42/event/1/picks/"])
    picks["picks"][-1]["element"] = picks["picks"][0]["element"]
    payloads["/api/entry/42/event/1/picks/"] = picks
    calls: list[str] = []
    with pytest.raises(ManagerCaptureError) as raised:
        _capture(tmp_path, payloads=payloads, calls=calls)
    assert raised.value.code is ManagerCaptureErrorCode.ILLEGAL_SQUAD
    assert calls[-2:] == ["/api/entry/42/transfers/", "/api/entry/42/history/"]


def test_missing_deadline_price_fails_closed(tmp_path: Path) -> None:
    deadline = _json("manager_bootstrap_deadline.json")
    deadline["elements"][0]["now_cost"] = None
    with pytest.raises(ManagerCaptureError) as raised:
        _capture(tmp_path, deadline_bootstrap=deadline)
    assert raised.value.code is ManagerCaptureErrorCode.PRICE_MISSING


def test_missing_committed_start_deadline_snapshot_is_explicit(tmp_path: Path) -> None:
    with _client(_base_payloads()) as client:
        with pytest.raises(ManagerCaptureError) as raised:
            capture_manager_team(
                42,
                client=client,
                snapshots_root=tmp_path / "no-snapshots",
                captured_at=CAPTURED_AT,
            )
    assert raised.value.code is ManagerCaptureErrorCode.DEADLINE_SNAPSHOT_MISSING


def test_empty_picks_fail_with_no_revealed_picks(tmp_path: Path) -> None:
    payloads = _base_payloads()
    picks = copy.deepcopy(payloads["/api/entry/42/event/1/picks/"])
    picks["picks"] = []
    payloads["/api/entry/42/event/1/picks/"] = picks
    with pytest.raises(ManagerCaptureError) as raised:
        _capture(tmp_path, payloads=payloads)
    assert raised.value.code is ManagerCaptureErrorCode.NO_REVEALED_PICKS


def test_post_picks_transfer_of_unowned_player_fails_replay(tmp_path: Path) -> None:
    payloads = _base_payloads()
    transfers = copy.deepcopy(payloads["/api/entry/42/transfers/"])
    transfers[0]["element_out"] = 17
    payloads["/api/entry/42/transfers/"] = transfers
    with pytest.raises(ManagerCaptureError) as raised:
        _capture(tmp_path, payloads=payloads)
    assert raised.value.code is ManagerCaptureErrorCode.TRANSFER_REPLAY_MISMATCH


def test_active_free_hit_in_planning_event_is_refused(tmp_path: Path) -> None:
    payloads = _base_payloads()
    history = copy.deepcopy(payloads["/api/entry/42/history/"])
    history["chips"] = [{"name": "freehit", "event": 2, "time": "2026-08-23T07:00:00Z"}]
    payloads["/api/entry/42/history/"] = history
    with pytest.raises(ManagerCaptureError) as raised:
        _capture(tmp_path, payloads=payloads)
    assert raised.value.code is ManagerCaptureErrorCode.ACTIVE_PLANNING_CHIP


def test_no_next_event_is_an_explicit_completeness_error(tmp_path: Path) -> None:
    payloads = _base_payloads()
    bootstrap = copy.deepcopy(payloads["/api/bootstrap-static/"])
    bootstrap["events"][1]["is_next"] = False
    payloads["/api/bootstrap-static/"] = bootstrap
    with pytest.raises(ManagerCaptureError) as raised:
        _capture(tmp_path, payloads=payloads)
    assert raised.value.code is ManagerCaptureErrorCode.NO_NEXT_EVENT


def test_free_hit_and_wildcard_preserve_prior_banked_transfer(tmp_path: Path) -> None:
    payloads = _base_payloads()
    bootstrap = _current_bootstrap()
    first_deadline = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
    bootstrap["events"] = [
        {
            "id": event,
            "name": f"Gameweek {event}",
            "deadline_time": (first_deadline + timedelta(days=7 * (event - 1)))
            .isoformat()
            .replace("+00:00", "Z"),
            "finished": event < 4,
            "is_current": event == 4,
            "is_next": event == 5,
        }
        for event in range(1, 6)
    ]
    entry = copy.deepcopy(payloads["/api/entry/42/"])
    entry["current_event"] = 4
    latest = copy.deepcopy(payloads["/api/entry/42/event/1/picks/"])
    latest["active_chip"] = "wildcard"
    latest["entry_history"]["event"] = 4
    history_rows = []
    for event in range(1, 5):
        row = copy.deepcopy(latest["entry_history"])
        row["event"] = event
        row["event_transfers"] = 0
        row["event_transfers_cost"] = 0
        history_rows.append(row)
    history_rows[2]["event_transfers"] = 1
    history = {
        "current": history_rows,
        "past": [],
        "chips": [
            {"name": "freehit", "event": 3, "time": "2026-09-01T08:00:00Z"},
            {"name": "wildcard", "event": 4, "time": "2026-09-08T08:00:00Z"},
        ],
    }
    payloads = {
        "/api/bootstrap-static/": bootstrap,
        "/api/entry/42/": entry,
        "/api/entry/42/event/1/picks/": _json("manager_picks_start.json"),
        "/api/entry/42/event/4/picks/": latest,
        # This is the temporary free-hit move. Replaying it would make the final
        # permanent squad disagree with the unchanged event-4 picks, so success proves
        # the event-3 transfer is deliberately ignored.
        "/api/entry/42/transfers/": [
            {
                "element_in": 16,
                "element_in_cost": 50,
                "element_out": 15,
                "element_out_cost": 45,
                "entry": 42,
                "event": 3,
                "time": "2026-09-01T09:00:00Z",
            }
        ],
        "/api/entry/42/history/": history,
    }
    capture = _capture(
        tmp_path,
        payloads=payloads,
        captured_at=datetime(2026, 9, 12, 12, tzinfo=UTC),
    )
    assert capture.picks_event == 4
    assert capture.planning_event == 5
    assert capture.free_transfers_available == 2
    assert capture.existing_hit_points == 0


def test_capture_round_trip_no_clobber_and_prepublish_failure(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    output = tmp_path / "captures" / f"{capture.capture_id}.json"
    digest = write_manager_capture_atomic(output, capture)
    assert digest == manager_capture_sha256(capture)
    assert read_manager_capture(output) == capture
    assert manager_capture_bytes(capture) == output.read_bytes()
    original = output.read_bytes()
    with pytest.raises(ManagerCaptureExistsError):
        write_manager_capture_atomic(output, capture)
    assert output.read_bytes() == original

    failed = tmp_path / "captures" / "failed.json"

    def fail_before_publish() -> None:
        raise RuntimeError("simulated prepublish failure")

    with pytest.raises(RuntimeError, match="simulated prepublish"):
        write_manager_capture_atomic(failed, capture, pre_publish=fail_before_publish)
    assert not failed.exists()
    assert list(failed.parent.glob(".failed.json.*.tmp")) == []


def test_tampered_deadline_package_is_rejected_before_price_use(tmp_path: Path) -> None:
    snapshots = tmp_path / "snapshots"
    directory = _write_deadline_snapshot(snapshots, _json("manager_bootstrap_deadline.json"))
    with gzip.open(directory / "bootstrap-static.json.gz", "wt", encoding="utf-8") as stream:
        json.dump({"events": [], "elements": []}, stream)
    with _client(_base_payloads()) as client:
        with pytest.raises(ManagerCaptureError) as raised:
            capture_manager_team(
                42,
                client=client,
                snapshots_root=snapshots,
                captured_at=CAPTURED_AT,
            )
    assert raised.value.code is ManagerCaptureErrorCode.DEADLINE_SNAPSHOT_INVALID
