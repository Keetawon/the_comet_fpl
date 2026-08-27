"""Offline contract tests for the local interactive plan server.

The server is a trigger, not a new solver: these tests pin the request contract, the
same-machine origin rule, the single-flight serialization, the fail-closed pre-checks
(dirty worktree, missing forecast), and the HTTP surface on a real loopback socket with
the pipeline monkeypatched -- never solving a real squad and never touching the network
beyond the loopback interface the server itself listens on.
"""

from __future__ import annotations

import json
import math
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from fpl.artifacts.prospective_points import (
    ContractIdentity,
    ForecastArtifactManifest,
    ForecastArtifactRow,
    LiveInputProvenance,
    ProspectivePointsArtifact,
    write_artifact_atomic,
)
from fpl.ingest.manager_team import (
    ManagerCaptureCompleteness,
    ManagerCaptureProvenance,
    ManagerSquadPlayer,
    ManagerTeamCapture,
    ManagerTransferReplayRules,
    derive_manager_capture_id,
    write_manager_capture_atomic,
)
from fpl.insights.contracts import (
    INSIGHT_REQUEST_SCHEMA,
    INSIGHT_SCHEMA_VERSION,
    PROMPT_VERSION,
    InsightSummaryRequest,
    ProviderSummaryPayload,
    ResolvedInsightEvidence,
)
from fpl.insights.service import InsightService
from fpl.jobs import plan_server
from fpl.jobs.plan_server import (
    RequestError,
    ServerState,
    _allowed_origin,
    _load_manager_capture,
    _manager_capture_path,
    _manager_team_preview,
    _publish_dashboard_generations,
    _run_optimizer_cli,
    fetch_and_store_manager_team,
    make_handler,
    run_manager_plan,
    run_plan,
    summarize_artifact,
    validate_manager_plan_request,
    validate_request,
)

HASH = "a" * 64
CAPTURED_AT = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def _insight_request_bytes(**overrides: object) -> bytes:
    payload: dict[str, object] = {
        "schema": INSIGHT_REQUEST_SCHEMA,
        "schema_version": INSIGHT_SCHEMA_VERSION,
        "page": "summary",
        "manifest_sha256": HASH,
        "run_id": "forecast-vintage-1",
        "season": "2026-27",
        "as_of": "2026-08-26T08:00:00Z",
        "scope": {"gw_from": 2, "gw_to": 5},
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


class _HttpInsightProvider:
    provider_id = "fake"
    model = "fake-model-v1"

    def generate(
        self,
        evidence: ResolvedInsightEvidence,
        *,
        deadline_monotonic: float,
    ) -> ProviderSummaryPayload:
        del evidence, deadline_monotonic
        return ProviderSummaryPayload.model_validate(
            {
                "headline": "coverage",
                "items": [
                    {
                        "relation": "highlight",
                        "fact_ids": ["summary.coverage"],
                    }
                ],
            }
        )


def _fake_insight_evidence(
    directory: Path, request: InsightSummaryRequest
) -> ResolvedInsightEvidence:
    del directory
    return ResolvedInsightEvidence.model_validate(
        {
            "request": request,
            "facts": [
                {
                    "id": "summary.coverage",
                    "kind": "coverage",
                    "statement": "The displayed export reports complete horizon coverage.",
                    "source_read_models": ["summary.json"],
                }
            ],
            "caveats": [],
        }
    )


def _distribution(mean: float) -> tuple[float, ...]:
    lower = math.floor(mean)
    fraction = mean - lower
    if fraction == 0.0:
        return (*((0.0,) * lower), 1.0)
    return (*((0.0,) * lower), 1.0 - fraction, fraction)


def _manager_players(*, price_delta_code: int | None = None) -> tuple[ManagerSquadPlayer, ...]:
    positions = ("GK", "GK", *("DEF",) * 5, *("MID",) * 5, *("FWD",) * 3)
    players: list[ManagerSquadPlayer] = []
    for offset, position in enumerate(positions, start=1):
        now_cost = 51 if offset == price_delta_code else 50
        players.append(
            ManagerSquadPlayer(
                element=100 + offset,
                code=offset,
                web_name=f"P{offset}",
                position=position,
                team_id=(offset - 1) // 3 + 1,
                now_cost=now_cost,
                purchase_price=50,
                selling_price=50,
            )
        )
    return tuple(players)


def _manager_capture(
    *,
    planning_event: int = 2,
    bootstrap_sha256: str = HASH,
    registry_sha256: str = HASH,
) -> ManagerTeamCapture:
    players = _manager_players()
    selling_value = sum(player.selling_price for player in players)
    pending = ManagerTeamCapture(
        capture_id="pending",
        captured_at=CAPTURED_AT,
        season="2026-27",
        manager_id=42,
        manager_name="Fixture XI",
        player_first_name="Test",
        player_last_name="Manager",
        started_event=1,
        picks_event=planning_event - 1,
        planning_event=planning_event,
        squad=players,
        bank_tenths=25,
        squad_selling_value_tenths=selling_value,
        available_budget_tenths=selling_value + 25,
        free_transfers_available=1,
        existing_hit_points=4,
        historical_hit_points=0,
        post_picks_transfer_count=2,
        chips=(),
        transfer_rules=ManagerTransferReplayRules(),
        completeness=ManagerCaptureCompleteness(
            latest_free_hit_picks_comparable_to_permanent_squad=True
        ),
        provenance=ManagerCaptureProvenance(
            current_bootstrap_sha256=bootstrap_sha256,
            selectable_player_registry_sha256=registry_sha256,
            entry_sha256="b" * 64,
            latest_picks_sha256="c" * 64,
            start_picks_sha256="d" * 64,
            transfers_sha256="e" * 64,
            history_sha256="f" * 64,
            deadline_snapshot_capture_id="file-synthetic",
            deadline_snapshot_captured_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
            deadline_snapshot_relative_path="snapshots/daily/2026-08-21/synthetic",
            deadline_snapshot_manifest_sha256="1" * 64,
            deadline_snapshot_bootstrap_archive_sha256="2" * 64,
            deadline_snapshot_bootstrap_payload_sha256="3" * 64,
        ),
    )
    payload = pending.model_dump(mode="json", by_alias=True)
    payload["capture_id"] = derive_manager_capture_id(pending)
    return ManagerTeamCapture.model_validate(payload)


def _write_forecast(
    path: Path,
    *,
    gw_from: int = 2,
    bootstrap_sha256: str = HASH,
    registry_sha256: str | None = HASH,
    price_delta_code: int | None = None,
) -> ProspectivePointsArtifact:
    players = _manager_players(price_delta_code=price_delta_code)
    rows = tuple(
        ForecastArtifactRow(
            season="2026-27",
            gw=gw_from,
            code=player.code,
            web_name=player.web_name,
            position=player.position,
            team_id=player.team_id,
            team_code=player.team_id,
            now_cost=player.now_cost,
            selected_by_percent=None,
            availability_status="a",
            chance_of_playing=None,
            availability_multiplier=1.0,
            fixture_ids=(2000 + player.code,),
            kickoff_times=(datetime(2026, 8, 29, 14, 0, tzinfo=UTC),),
            expected_points=2.0,
            availability_adjusted_expected_points=2.0,
            expected_bonus=0.0,
            distribution=_distribution(2.0),
            cold_start_player=False,
            stage_a_league_average_team=False,
            attacking_signal_cold_start=False,
            assist_signal_cold_start=False,
            transferred_no_rescale=False,
        )
        for player in players
    )
    artifact = ProspectivePointsArtifact(
        manifest=ForecastArtifactManifest(
            as_of=CAPTURED_AT,
            season="2026-27",
            gw_from=gw_from,
            gw_to=gw_from,
            row_count=len(rows),
            roster_size=len(rows),
            fixture_count=len(rows),
            monte_carlo_draws=100,
            base_seed=1,
            fixture_points_support_max=40,
            freshness_cold_start=True,
            commit_sha="forecastcommit",
            database_sha256="9" * 64,
            contracts={
                "synthetic": ContractIdentity(name="synthetic", version="1", sha256="8" * 64)
            },
            component_modes={"test": "synthetic"},
            live_inputs=LiveInputProvenance(
                bootstrap_capture_id="synthetic",
                bootstrap_known_at=CAPTURED_AT,
                bootstrap_payload_sha256=bootstrap_sha256,
                schedule_capture_ids=("synthetic",),
                selectable_player_registry_sha256=registry_sha256,
            ),
        ),
        rows=rows,
    )
    write_artifact_atomic(path, artifact)
    return artifact


def _write_standing_plans(base: Path) -> None:
    for name in plan_server.STANDING_PLANS:
        (base / name).write_text("{}", encoding="utf-8")


class TestValidateRequest:
    def test_parses_sorts_and_dedupes_locks_and_defaults_the_gate(self) -> None:
        assert validate_request({"locks": [5, 1, 5]}) == ([1, 5], [], 0.0)

    def test_accepts_a_bench_gate_fraction(self) -> None:
        assert validate_request({"locks": [], "min_bench_appearance": 0.5}) == ([], [], 0.5)

    def test_parses_sorts_and_dedupes_exclusions(self) -> None:
        assert validate_request({"excludes": [9, 3, 9]}) == ([], [3, 9], 0.0)

    def test_rejects_too_many_or_overlapping_exclusions(self) -> None:
        with pytest.raises(RequestError, match="at most 15"):
            validate_request({"excludes": list(range(16))})
        with pytest.raises(RequestError, match="both locked and excluded"):
            validate_request({"locks": [7], "excludes": [7]})

    def test_rejects_more_than_five_locks(self) -> None:
        with pytest.raises(RequestError, match="at most 5"):
            validate_request({"locks": [1, 2, 3, 4, 5, 6]})

    def test_rejects_non_integer_locks(self) -> None:
        with pytest.raises(RequestError, match="list of player codes"):
            validate_request({"locks": ["1"]})

    @pytest.mark.parametrize("field", ["locks", "excludes"])
    def test_rejects_boolean_player_codes(self, field: str) -> None:
        with pytest.raises(RequestError, match="list of player codes"):
            validate_request({field: [True]})

    def test_rejects_out_of_range_bench_gate(self) -> None:
        for bad in (0, 1, -0.5, "0.5"):
            with pytest.raises(RequestError, match="min_bench_appearance"):
                validate_request({"locks": [], "min_bench_appearance": bad})


class TestValidateManagerPlanRequest:
    def test_parses_capture_rules_and_free_transfer_override(self) -> None:
        capture_id = "manager-" + "1" * 64
        assert validate_manager_plan_request(
            {
                "capture_id": capture_id,
                "locks": [7, 3, 7],
                "excludes": [11, 9],
                "min_bench_appearance": 0.25,
                "free_transfers_override": 0,
            }
        ) == (capture_id, [3, 7], [9, 11], 0.25, 0)

    def test_accepts_no_override_and_rejects_invalid_overrides(self) -> None:
        capture_id = "manager-" + "1" * 64
        assert validate_manager_plan_request({"capture_id": capture_id})[-1] is None
        for bad in (True, -1, 6, 1.5, "1"):
            with pytest.raises(RequestError, match="free_transfers_override"):
                validate_manager_plan_request(
                    {"capture_id": capture_id, "free_transfers_override": bad}
                )

    @pytest.mark.parametrize(
        "capture_id",
        ["", "1" * 64, "manager-" + "G" * 64, "../manager-" + "1" * 64],
    )
    def test_rejects_noncanonical_capture_ids(self, capture_id: str) -> None:
        with pytest.raises(RequestError, match="immutable manager capture"):
            validate_manager_plan_request({"capture_id": capture_id})


class TestAllowedOrigin:
    def test_non_browser_requests_pass(self) -> None:
        assert _allowed_origin(None) is True

    def test_loopback_origins_pass(self) -> None:
        assert _allowed_origin("http://localhost:5173") is True
        assert _allowed_origin("http://127.0.0.1:4173") is True

    def test_only_this_hosts_lan_origin_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            plan_server.socket,
            "getaddrinfo",
            lambda *args, **kwargs: [(plan_server.socket.AF_INET, 0, 0, "", ("192.168.1.37", 0))],
        )
        assert _allowed_origin("http://192.168.1.37:4173") is True
        assert _allowed_origin("http://192.168.1.88:4173") is False

    def test_other_sites_are_refused(self) -> None:
        assert _allowed_origin("https://evil.example") is False

    def test_non_loopback_peers_require_the_exact_launch_token(self) -> None:
        assert plan_server._peer_authenticated("127.0.0.1", None, "secret") is True
        assert plan_server._peer_authenticated("192.168.1.88", None, "secret") is False
        assert plan_server._peer_authenticated("192.168.1.88", "wrong", "secret") is False
        assert plan_server._peer_authenticated("192.168.1.88", "secret", "secret") is True


class TestSummarizeArtifact:
    def test_maps_the_fields_the_ui_greets_with(self, tmp_path: Path) -> None:
        artifact = {
            "run_id": "r" * 64,
            "decision_sha256": "d" * 64,
            "plan": {
                "expected_points_after_hits": 317.2,
                "hit_points": 0,
                "weeks": [
                    {
                        "gw": 1,
                        "expected_points": 60.7,
                        "squad_cost_tenths": 995,
                        "captain": {"web_name": "Gibbs-White"},
                        "vice_captain": {"web_name": "O'Reilly"},
                    }
                ],
            },
        }
        path = tmp_path / "plan-x.json"
        path.write_text(json.dumps(artifact), encoding="utf-8")
        summary = summarize_artifact(path)
        assert summary["optimizer_run_id"] == "r" * 64
        assert summary["gw_expected_points"] == 60.7
        assert summary["captain"] == "Gibbs-White"

    def test_schema_v2_separates_new_hits_from_sunk_hits_and_reports_cash(
        self, tmp_path: Path
    ) -> None:
        capture_id = "manager-" + "1" * 64
        artifact = {
            "schema_version": 2,
            "run_id": "r" * 64,
            "decision_sha256": "d" * 64,
            "manager_context": {
                "capture_id": capture_id,
                "existing_hit_points": 4,
                "initial_free_transfers": 0,
                "bank_tenths": 25,
            },
            "plan": {
                "expected_points_after_hits": 111.5,
                "hit_points": 8,
                "weeks": [
                    {
                        "gw": 2,
                        "expected_points": 61.5,
                        "squad_cost_tenths": 1015,
                        "captain": {"web_name": "Captain"},
                        "vice_captain": {"web_name": "Vice"},
                        "transfers_in": [{"code": 16, "web_name": "New"}],
                        "transfers_out": [{"code": 1, "web_name": "Old"}],
                        "free_transfers_before": 0,
                        "free_transfers_after": 0,
                        "hit_points": 4,
                        "bank_before_tenths": 25,
                        "bank_after_tenths": 20,
                    },
                    {
                        "gw": 3,
                        "expected_points": 58.0,
                        "squad_cost_tenths": 1015,
                        "captain": {"web_name": "Captain"},
                        "vice_captain": {"web_name": "Vice"},
                        "transfers_in": [{"code": 17, "web_name": "Second new"}],
                        "transfers_out": [{"code": 2, "web_name": "Second old"}],
                        "free_transfers_before": 1,
                        "free_transfers_after": 0,
                        "hit_points": 4,
                        "bank_before_tenths": 20,
                        "bank_after_tenths": 13,
                    },
                ],
            },
        }
        path = tmp_path / "manager-plan.json"
        path.write_text(json.dumps(artifact), encoding="utf-8")

        summary = summarize_artifact(path)

        assert summary["hit_points"] == 8
        assert summary["manager_existing_hit_points"] == 4
        assert summary["manager_capture_id"] == capture_id
        assert summary["manager_initial_free_transfers"] == 0
        assert summary["manager_bank_tenths"] == 25
        assert summary["manager_weeks"][0] == {
            "gw": 2,
            "transfers_in": [{"code": 16, "web_name": "New"}],
            "transfers_out": [{"code": 1, "web_name": "Old"}],
            "free_transfers_before": 0,
            "free_transfers_after": 0,
            "hit_points": 4,
            "bank_before_tenths": 25,
            "bank_after_tenths": 20,
        }


class TestManagerTeamPreview:
    @staticmethod
    def _state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ServerState:
        monkeypatch.setattr(plan_server, "_pulp_package_version", lambda: "3.3.2")
        monkeypatch.setattr(plan_server, "_cbc_binary_version", lambda: "2.10.3")
        state = ServerState(tmp_path)
        _write_forecast(state.forecast_path)
        return state

    def test_returns_exact_fifteen_player_private_dto(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state = self._state(tmp_path, monkeypatch)
        capture = _manager_capture()

        preview = _manager_team_preview(state, capture, require_full_registry=True)

        assert set(preview) == {
            "capture_id",
            "captured_at",
            "manager_id",
            "entry_name",
            "picks_event",
            "planning_gw",
            "bank_tenths",
            "squad_selling_value_tenths",
            "free_transfers_available",
            "free_transfers_source",
            "existing_hit_points",
            "players",
        }
        assert preview["capture_id"] == capture.capture_id
        assert preview["manager_id"] == 42
        assert preview["entry_name"] == "Fixture XI"
        assert preview["planning_gw"] == 2
        assert len(preview["players"]) == 15
        assert preview["players"][0] == {
            "element_id": 101,
            "code": 1,
            "web_name": "P1",
            "position": "GK",
            "team_id": 1,
            "team_code": 1,
            "now_cost": 50,
            "purchase_price": 50,
            "selling_price": 50,
        }

    @pytest.mark.parametrize(
        ("case", "message"),
        [
            ("gameweek", "active forecast starts"),
            ("registry", "different selectable-player registries"),
            ("price", "disagrees with active forecast metadata"),
        ],
    )
    def test_fails_closed_on_forecast_capture_disagreement(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        case: str,
        message: str,
    ) -> None:
        monkeypatch.setattr(plan_server, "_pulp_package_version", lambda: "3.3.2")
        monkeypatch.setattr(plan_server, "_cbc_binary_version", lambda: "2.10.3")
        state = ServerState(tmp_path)
        if case == "gameweek":
            _write_forecast(state.forecast_path, gw_from=3)
            capture = _manager_capture()
        elif case == "registry":
            _write_forecast(state.forecast_path, registry_sha256="7" * 64)
            capture = _manager_capture()
        else:
            _write_forecast(state.forecast_path, price_delta_code=1)
            capture = _manager_capture()

        with pytest.raises(RequestError, match=message):
            _manager_team_preview(state, capture, require_full_registry=True)

    def test_preview_tolerates_volatile_bootstrap_payload_changes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_pulp_package_version", lambda: "3.3.2")
        monkeypatch.setattr(plan_server, "_cbc_binary_version", lambda: "2.10.3")
        state = ServerState(tmp_path)
        _write_forecast(state.forecast_path, bootstrap_sha256="7" * 64)
        preview = _manager_team_preview(
            state,
            _manager_capture(bootstrap_sha256="8" * 64),
            require_full_registry=True,
        )
        assert len(preview["players"]) == 15

    def test_preview_requires_forecast_registry_binding(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_pulp_package_version", lambda: "3.3.2")
        monkeypatch.setattr(plan_server, "_cbc_binary_version", lambda: "2.10.3")
        state = ServerState(tmp_path)
        _write_forecast(state.forecast_path, registry_sha256=None)
        with pytest.raises(RequestError, match="no selectable-player registry binding"):
            _manager_team_preview(state, _manager_capture(), require_full_registry=True)

    def test_member_only_preview_tolerates_unrelated_registry_drift(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_pulp_package_version", lambda: "3.3.2")
        monkeypatch.setattr(plan_server, "_cbc_binary_version", lambda: "2.10.3")
        state = ServerState(tmp_path)
        _write_forecast(state.forecast_path, registry_sha256="7" * 64)

        preview = _manager_team_preview(
            state,
            _manager_capture(registry_sha256="8" * 64),
            require_full_registry=False,
        )

        assert len(preview["players"]) == 15

    def test_member_only_preview_still_rejects_owned_player_metadata_drift(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_pulp_package_version", lambda: "3.3.2")
        monkeypatch.setattr(plan_server, "_cbc_binary_version", lambda: "2.10.3")
        state = ServerState(tmp_path)
        _write_forecast(
            state.forecast_path,
            registry_sha256="7" * 64,
            price_delta_code=1,
        )

        with pytest.raises(RequestError, match="disagrees with active forecast metadata"):
            _manager_team_preview(
                state,
                _manager_capture(registry_sha256="8" * 64),
                require_full_registry=False,
            )

    def test_manager_plan_rejects_more_owned_exclusions_than_first_week_depth(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_git_worktree_clean", lambda repo: True)
        monkeypatch.setattr(plan_server, "_pulp_package_version", lambda: "3.3.2")
        monkeypatch.setattr(plan_server, "_cbc_binary_version", lambda: "2.10.3")
        state = ServerState(tmp_path)
        _write_forecast(state.forecast_path)
        capture = _manager_capture()
        write_manager_capture_atomic(
            _manager_capture_path(state, capture.capture_id),
            capture,
        )
        forced = [player.code for player in capture.squad[:3]]
        with pytest.raises(RequestError, match="force 3 first-week transfers"):
            run_manager_plan(
                state,
                capture.capture_id,
                [],
                forced,
                0.0,
                None,
            )

    def test_fetch_validates_previews_and_stores_without_network(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state = self._state(tmp_path, monkeypatch)
        capture = _manager_capture()
        client_instance = object()
        writes: list[tuple[Path, ManagerTeamCapture]] = []

        class FakeClient:
            def __enter__(self) -> object:
                return client_instance

            def __exit__(self, *args: object) -> None:
                return None

        def fake_capture(manager_id: int, *, client: object) -> ManagerTeamCapture:
            assert manager_id == 42
            assert client is client_instance
            return capture

        def fake_write(path: Path, value: ManagerTeamCapture) -> str:
            writes.append((path, value))
            return "0" * 64

        monkeypatch.setattr(plan_server, "FplApiClient", FakeClient)
        monkeypatch.setattr(plan_server, "capture_manager_team", fake_capture)
        monkeypatch.setattr(plan_server, "write_manager_capture_atomic", fake_write)

        preview = fetch_and_store_manager_team(state, 42, require_full_registry=True)

        assert preview["capture_id"] == capture.capture_id
        assert writes == [
            (
                tmp_path / plan_server.MANAGER_CAPTURES_DIRNAME / f"{capture.capture_id}.json",
                capture,
            )
        ]

    def test_capture_reload_rejects_path_traversal_and_invalid_or_corrupt_ids(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_pulp_package_version", lambda: "3.3.2")
        monkeypatch.setattr(plan_server, "_cbc_binary_version", lambda: "2.10.3")
        state = ServerState(tmp_path)
        for invalid in (
            "../manager-" + "1" * 64,
            "manager-" + "1" * 63,
            "manager-" + "Z" * 64,
        ):
            with pytest.raises(RequestError, match="capture id is invalid"):
                _manager_capture_path(state, invalid)

        capture = _manager_capture()
        valid_path = _manager_capture_path(state, capture.capture_id)
        write_manager_capture_atomic(valid_path, capture)
        assert _load_manager_capture(state, capture.capture_id) == capture

        missing = "manager-" + "1" * 64
        with pytest.raises(RequestError, match="capture is unavailable"):
            _load_manager_capture(state, missing)

        corrupt_path = _manager_capture_path(state, missing)
        corrupt_path.parent.mkdir(exist_ok=True)
        corrupt_path.write_text("{}", encoding="utf-8")
        with pytest.raises(RequestError, match="immutable validation"):
            _load_manager_capture(state, missing)


class TestRunPlanPreChecks:
    def test_optimizer_cli_failure_surfaces_the_stderr_tail(self) -> None:
        """The solve runs in a child interpreter; its refusal text must reach the UI."""
        with pytest.raises(RequestError, match="optimizer run failed"):
            _run_optimizer_cli(["--not-a-real-flag"])

    def test_busy_server_refuses_a_second_run(self) -> None:
        state = ServerState(Path("unused"))
        assert state.run_lock.acquire(blocking=False)
        try:
            with pytest.raises(RequestError, match="already in progress"):
                run_plan(state, [], [], 0.0)
        finally:
            state.run_lock.release()

    def test_missing_forecast_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_git_worktree_clean", lambda repo: True)
        state = ServerState(tmp_path)
        with pytest.raises(RequestError, match="forecast artifact missing"):
            run_plan(state, [], [], 0.0)

    def test_unverified_solver_runtime_is_refused_before_solving(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_pulp_package_version", lambda: "3.3.2")
        monkeypatch.setattr(plan_server, "_cbc_binary_version", lambda: None)
        state = ServerState(tmp_path)
        monkeypatch.setattr(plan_server, "_run_optimizer_cli", lambda _argv: pytest.fail("solved"))
        with pytest.raises(RequestError, match="CBC binary version is unavailable"):
            run_plan(state, [], [], 0.0)
        assert state.solver_package_version == "3.3.2"
        assert state.solver_binary_version is None
        assert state.solver_discovery_attempts == 2

    def test_transient_startup_probe_is_retried_by_status(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock = [0.0]
        binary_versions = iter([None, "2.10.3"])
        monkeypatch.setattr(plan_server, "_monotonic", lambda: clock[0])
        monkeypatch.setattr(plan_server, "_pulp_package_version", lambda: "3.3.2")
        monkeypatch.setattr(plan_server, "_cbc_binary_version", lambda: next(binary_versions))

        state = ServerState(tmp_path)
        assert state.solver_binary_version is None

        clock[0] = plan_server.SOLVER_PROBE_COOLDOWN_SECONDS
        runtime = state.snapshot()["runtime"]
        assert runtime["solver_ready"] is True
        assert runtime["pulp_package_version"] == "3.3.2"
        assert runtime["cbc_binary_version"] == "2.10.3"
        assert runtime["solver_discovery_attempts"] == 2
        assert runtime["solver_discovery_error"] is None

    def test_solver_probe_exception_is_reported_without_accepting_partial_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_pulp_package_version", lambda: "3.3.2")

        def fail_cbc_probe() -> str:
            raise OSError("endpoint scanner denied launch")

        monkeypatch.setattr(plan_server, "_cbc_binary_version", fail_cbc_probe)
        state = ServerState(tmp_path)

        assert state.solver_package_version == "3.3.2"
        assert state.solver_binary_version is None
        assert state.solver_discovery_error == ("CBC binary probe failed (OSError)")

    def test_pre_solve_forces_recheck_of_previously_ready_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package_versions = iter(["3.3.2", None])
        monkeypatch.setattr(plan_server, "_pulp_package_version", lambda: next(package_versions))
        monkeypatch.setattr(plan_server, "_cbc_binary_version", lambda: "2.10.3")
        state = ServerState(tmp_path)
        assert state.solver_package_version == "3.3.2"
        assert state.solver_binary_version == "2.10.3"
        monkeypatch.setattr(plan_server, "_run_optimizer_cli", lambda _argv: pytest.fail("solved"))

        with pytest.raises(RequestError, match="PuLP package version is unavailable"):
            run_plan(state, [], [], 0.0)

        assert state.solver_package_version is None
        assert state.solver_binary_version == "2.10.3"
        assert state.solver_discovery_attempts == 2

    def test_status_probe_cooldown_collapses_concurrent_requests(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock = [0.0]
        probe_entered = threading.Event()
        release_probe = threading.Event()
        binary_probe_count = 0

        def binary_probe() -> None:
            nonlocal binary_probe_count
            binary_probe_count += 1
            if binary_probe_count == 2:
                probe_entered.set()
                assert release_probe.wait(timeout=5)
            return None

        monkeypatch.setattr(plan_server, "_monotonic", lambda: clock[0])
        monkeypatch.setattr(plan_server, "_pulp_package_version", lambda: "3.3.2")
        monkeypatch.setattr(plan_server, "_cbc_binary_version", binary_probe)
        state = ServerState(tmp_path)
        clock[0] = plan_server.SOLVER_PROBE_COOLDOWN_SECONDS

        first = threading.Thread(target=state.snapshot)
        first.start()
        assert probe_entered.wait(timeout=5)
        followers = [threading.Thread(target=state.snapshot) for _ in range(4)]
        for follower in followers:
            follower.start()
        for follower in followers:
            follower.join(timeout=1)
            assert not follower.is_alive()
        release_probe.set()
        first.join(timeout=5)
        assert not first.is_alive()

        assert binary_probe_count == 2
        state.snapshot()
        assert binary_probe_count == 2

    def test_status_diagnostic_does_not_expose_raw_exception_or_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_pulp_package_version", lambda: "3.3.2")

        def fail_cbc_probe() -> str:
            raise OSError(r"C:\\Users\\owner\\secret-cbc.exe access denied")

        monkeypatch.setattr(plan_server, "_cbc_binary_version", fail_cbc_probe)
        runtime = ServerState(tmp_path).snapshot()["runtime"]

        assert runtime["solver_discovery_error"] == "CBC binary probe failed (OSError)"
        rendered = json.dumps(runtime)
        assert "owner" not in rendered
        assert "secret-cbc" not in rendered

    def test_dirty_worktree_is_refused_before_solving(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_git_worktree_clean", lambda repo: False)
        (tmp_path / plan_server.FORECAST_NAME).write_text("{}", encoding="utf-8")
        state = ServerState(tmp_path)
        with pytest.raises(RequestError, match="worktree is dirty"):
            run_plan(state, [], [], 0.0)

    def test_user_plan_threads_exclusions_and_origin_to_cli(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_git_worktree_clean", lambda repo: True)
        (tmp_path / plan_server.FORECAST_NAME).write_text("{}", encoding="utf-8")
        _write_standing_plans(tmp_path)
        seen: list[str] = []

        def capture(argv: list[str]) -> None:
            seen.extend(argv)
            raise RequestError("stop after capture")

        monkeypatch.setattr(plan_server, "_run_optimizer_cli", capture)
        with pytest.raises(RequestError, match="stop after capture"):
            run_plan(ServerState(tmp_path), [7], [9, 11], 0.25)
        assert seen.count("--exclude") == 2
        assert seen[seen.index("--plan-origin") + 1] == "user_custom"
        assert "9" in seen and "11" in seen

    def test_manager_plan_threads_capture_rules_override_and_shared_publish(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_git_worktree_clean", lambda repo: True)
        monkeypatch.setattr(plan_server, "_pulp_package_version", lambda: "3.3.2")
        monkeypatch.setattr(plan_server, "_cbc_binary_version", lambda: "2.10.3")
        state = ServerState(tmp_path)
        _write_forecast(state.forecast_path)
        _write_standing_plans(tmp_path)
        capture = _manager_capture()
        seen_argv: list[str] = []
        published: list[tuple[Path, list[Path], dict[str, Any]]] = []

        monkeypatch.setattr(plan_server, "_load_manager_capture", lambda _state, _id: capture)

        def fake_optimizer(argv: list[str]) -> None:
            seen_argv.extend(argv)
            Path(argv[argv.index("--output") + 1]).write_text("{}", encoding="utf-8")

        summary = {
            "optimizer_run_id": "r" * 64,
            "decision_sha256": "d" * 64,
            "manager_capture_id": capture.capture_id,
        }
        monkeypatch.setattr(plan_server, "_run_optimizer_cli", fake_optimizer)
        monkeypatch.setattr(plan_server, "summarize_artifact", lambda _path: dict(summary))

        def fake_publish(
            _state: ServerState,
            output: Path,
            standing_paths: list[Path],
            published_summary: dict[str, Any],
        ) -> None:
            published.append((output, standing_paths, published_summary))

        monkeypatch.setattr(plan_server, "_publish_custom_artifact", fake_publish)

        result = run_manager_plan(
            state,
            capture.capture_id,
            [1],
            [9, 11],
            0.25,
            0,
        )

        assert seen_argv[0] == str(state.forecast_path)
        assert seen_argv[seen_argv.index("--manager-capture") + 1] == str(
            _manager_capture_path(state, capture.capture_id)
        )
        assert seen_argv[seen_argv.index("--plan-origin") + 1] == "user_custom"
        assert seen_argv[seen_argv.index("--lock") + 1] == "1"
        assert seen_argv.count("--exclude") == 2
        assert seen_argv[seen_argv.index("--min-bench-appearance") + 1] == "0.25"
        assert seen_argv[seen_argv.index("--free-transfers-override") + 1] == "0"
        output = Path(seen_argv[seen_argv.index("--output") + 1])
        assert output.name.startswith("manager-plan-")
        assert published == [
            (
                output,
                [tmp_path / name for name in plan_server.STANDING_PLANS],
                result,
            )
        ]
        assert result["manager_entry_name"] == "Fixture XI"
        assert result["manager_planning_gw"] == 2
        assert len(result["manager_current_team"]) == 15

    def test_publishes_the_exact_output_not_the_newest_sibling(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_git_worktree_clean", lambda repo: True)
        monkeypatch.setattr(plan_server, "repo_root", lambda: tmp_path)
        base = tmp_path / "dev-latest"
        base.mkdir()
        (base / plan_server.FORECAST_NAME).write_text("{}", encoding="utf-8")
        _write_standing_plans(base)
        run_id = "r" * 64
        written: Path | None = None

        def fake_optimizer(argv: list[str]) -> None:
            nonlocal written
            written = Path(argv[argv.index("--output") + 1])
            artifact = {
                "run_id": run_id,
                "decision_sha256": "d" * 64,
                "plan": {
                    "expected_points_after_hits": 60.0,
                    "hit_points": 0,
                    "weeks": [
                        {
                            "gw": 1,
                            "expected_points": 60.0,
                            "squad_cost_tenths": 1000,
                            "captain": {"web_name": "Captain"},
                            "vice_captain": {"web_name": "Vice"},
                        }
                    ],
                },
            }
            written.write_text(json.dumps(artifact), encoding="utf-8")
            stale = written.parent / "plan-stale.json"
            stale.write_text(json.dumps({**artifact, "run_id": "s" * 64}), encoding="utf-8")

        def fake_bi(
            db_path: Path,
            output_dir: Path,
            *,
            optimizer_plan_paths: list[Path],
            before_publish: object,
        ) -> None:
            assert written is not None
            assert optimizer_plan_paths[-1] == written
            (base / "bi-export-copy").mkdir()

        def fake_dashboard(
            export_dir: Path,
            output_dir: Path,
            *,
            before_publish: object,
        ) -> None:
            staged = output_dir.parent / f".{output_dir.name}.fake.tmp"
            staged.mkdir(parents=True)
            (staged / plan_server.NEXT_GW_FILENAME).write_text(
                json.dumps(
                    {
                        "plans": [
                            {
                                "optimizer_run_id": run_id,
                                "plan_kind": "user_custom",
                            },
                            {
                                "optimizer_run_id": "d" * 64,
                                "plan_kind": "platform_default",
                            },
                            {
                                "optimizer_run_id": "c" * 64,
                                "plan_kind": "platform_diagnostic",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            assert callable(before_publish)
            before_publish()

        monkeypatch.setattr(plan_server, "_run_optimizer_cli", fake_optimizer)
        monkeypatch.setattr(plan_server, "export_bi", fake_bi)
        monkeypatch.setattr(plan_server, "export_dashboard_json", fake_dashboard)

        result = run_plan(ServerState(base), [7], [9], 0.25)
        assert result["optimizer_run_id"] == run_id
        assert written is not None
        assert result["output"] == str(written)
        assert written.name != "plan-stale.json"
        public = tmp_path / "dashboard" / "public" / "data"
        assert run_id in (public / plan_server.NEXT_GW_FILENAME).read_text(encoding="utf-8")

    def test_publish_io_error_fails_instead_of_reporting_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_git_worktree_clean", lambda repo: True)
        monkeypatch.setattr(plan_server, "repo_root", lambda: tmp_path)
        base = tmp_path / "dev-latest"
        base.mkdir()
        (base / plan_server.FORECAST_NAME).write_text("{}", encoding="utf-8")
        _write_standing_plans(base)

        def fake_optimizer(argv: list[str]) -> None:
            output = Path(argv[argv.index("--output") + 1])
            output.write_text(
                json.dumps(
                    {
                        "run_id": "r" * 64,
                        "decision_sha256": "d" * 64,
                        "plan": {
                            "expected_points_after_hits": 60.0,
                            "hit_points": 0,
                            "weeks": [
                                {
                                    "gw": 1,
                                    "expected_points": 60.0,
                                    "squad_cost_tenths": 1000,
                                    "captain": {"web_name": "Captain"},
                                    "vice_captain": {"web_name": "Vice"},
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

        monkeypatch.setattr(plan_server, "_run_optimizer_cli", fake_optimizer)
        monkeypatch.setattr(
            plan_server,
            "export_bi",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
        )
        with pytest.raises(OSError, match="disk full"):
            run_plan(ServerState(base), [], [], 0.0)

    def test_missing_standing_plan_fails_before_solving(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_git_worktree_clean", lambda repo: True)
        (tmp_path / plan_server.FORECAST_NAME).write_text("{}", encoding="utf-8")
        with pytest.raises(RequestError, match="required platform plan artifacts are missing"):
            run_plan(ServerState(tmp_path), [], [], 0.0)

    def test_missing_exact_run_in_dashboard_fails_closed(self, tmp_path: Path) -> None:
        (tmp_path / plan_server.NEXT_GW_FILENAME).write_text(
            json.dumps(
                {
                    "plans": [
                        {"optimizer_run_id": "default", "plan_kind": "platform_default"},
                        {
                            "optimizer_run_id": "diagnostic",
                            "plan_kind": "platform_diagnostic",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="exact solved optimizer run"):
            plan_server._verify_dashboard_plans_published(tmp_path, "wanted")

    def test_missing_formal_plan_in_dashboard_fails_closed(self, tmp_path: Path) -> None:
        (tmp_path / plan_server.NEXT_GW_FILENAME).write_text(
            json.dumps(
                {
                    "plans": [
                        {"optimizer_run_id": "wanted", "plan_kind": "user_custom"},
                        {"optimizer_run_id": "default", "plan_kind": "platform_default"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="platform_diagnostic"):
            plan_server._verify_dashboard_plans_published(tmp_path, "wanted")

    def test_dashboard_generation_reaches_public_and_static_preview_atomically(
        self, tmp_path: Path
    ) -> None:
        run_id = "wanted"
        source = tmp_path / "source"
        source.mkdir()
        payload = {
            "plans": [
                {"optimizer_run_id": run_id, "plan_kind": "user_custom"},
                {"optimizer_run_id": "default", "plan_kind": "platform_default"},
                {"optimizer_run_id": "diagnostic", "plan_kind": "platform_diagnostic"},
            ]
        }
        (source / plan_server.NEXT_GW_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
        (source / "players.json").write_text('{"generation":"new"}', encoding="utf-8")
        public = tmp_path / "public" / "data"
        preview = tmp_path / "dist" / "data"
        for target in (public, preview):
            target.mkdir(parents=True)
            (target / plan_server.NEXT_GW_FILENAME).write_text("old", encoding="utf-8")
            (target / "stale.json").write_text("old-only", encoding="utf-8")

        _publish_dashboard_generations(source, [public, preview], run_id)

        for target in (public, preview):
            assert (
                json.loads((target / plan_server.NEXT_GW_FILENAME).read_text())["plans"]
                == payload["plans"]
            )
            assert (target / "players.json").read_text(encoding="utf-8") == '{"generation":"new"}'
            assert not (target / "stale.json").exists()
        assert not list(tmp_path.rglob(".*.tmp"))
        assert not list(tmp_path.rglob(".*.previous"))

    def test_invalid_generation_leaves_every_served_target_unchanged(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        (source / plan_server.NEXT_GW_FILENAME).write_text(
            json.dumps(
                {
                    "plans": [
                        {"optimizer_run_id": "other", "plan_kind": "user_custom"},
                        {"optimizer_run_id": "default", "plan_kind": "platform_default"},
                        {"optimizer_run_id": "diagnostic", "plan_kind": "platform_diagnostic"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        targets = [tmp_path / "public" / "data", tmp_path / "dist" / "data"]
        for target in targets:
            target.mkdir(parents=True)
            (target / "sentinel").write_text("unchanged", encoding="utf-8")

        with pytest.raises(RuntimeError, match="exact solved optimizer run"):
            _publish_dashboard_generations(source, targets, "wanted")

        for target in targets:
            assert (target / "sentinel").read_text(encoding="utf-8") == "unchanged"

    def test_generation_promotion_failure_restores_previous_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run_id = "wanted"
        source = tmp_path / "source"
        source.mkdir()
        (source / plan_server.NEXT_GW_FILENAME).write_text(
            json.dumps(
                {
                    "plans": [
                        {"optimizer_run_id": run_id, "plan_kind": "user_custom"},
                        {"optimizer_run_id": "default", "plan_kind": "platform_default"},
                        {"optimizer_run_id": "diagnostic", "plan_kind": "platform_diagnostic"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        target = tmp_path / "public" / "data"
        target.mkdir(parents=True)
        (target / "sentinel").write_text("previous", encoding="utf-8")
        real_replace = Path.replace

        def fail_generation_promotion(path: Path, destination: Path) -> Path:
            if path.name.endswith(".tmp") and destination == target:
                raise OSError("injected promotion failure")
            return real_replace(path, destination)

        monkeypatch.setattr(Path, "replace", fail_generation_promotion)

        with pytest.raises(OSError, match="injected promotion failure"):
            _publish_dashboard_generations(source, [target], run_id)

        assert (target / "sentinel").read_text(encoding="utf-8") == "previous"
        assert not list(tmp_path.rglob(".*.tmp"))
        assert not list(tmp_path.rglob(".*.previous"))

    def test_second_target_promotion_failure_rolls_both_targets_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run_id = "wanted"
        source = self._valid_dashboard_source(tmp_path, run_id)
        public = tmp_path / "public" / "data"
        preview = tmp_path / "dist" / "data"
        for target, marker in ((public, "old-public"), (preview, "old-preview")):
            target.mkdir(parents=True)
            (target / "sentinel").write_text(marker, encoding="utf-8")
        real_replace = Path.replace

        def fail_preview_promotion(path: Path, destination: Path) -> Path:
            if path.name.endswith(".tmp") and destination == preview:
                raise OSError("injected second promotion failure")
            return real_replace(path, destination)

        monkeypatch.setattr(Path, "replace", fail_preview_promotion)

        with pytest.raises(OSError, match="injected second promotion failure"):
            _publish_dashboard_generations(source, [public, preview], run_id)

        assert (public / "sentinel").read_text(encoding="utf-8") == "old-public"
        assert (preview / "sentinel").read_text(encoding="utf-8") == "old-preview"
        assert not list(tmp_path.rglob(".*.tmp"))
        assert not list(tmp_path.rglob(".*.previous"))

    def test_partial_copy_failure_cleans_staged_generation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run_id = "wanted"
        source = self._valid_dashboard_source(tmp_path, run_id)
        target = tmp_path / "public" / "data"
        target.mkdir(parents=True)
        (target / "sentinel").write_text("previous", encoding="utf-8")

        def partial_copy(_source: Path, destination: Path) -> None:
            destination.mkdir()
            (destination / "partial.json").write_text("partial", encoding="utf-8")
            raise OSError("injected partial copy failure")

        monkeypatch.setattr(plan_server.shutil, "copytree", partial_copy)

        with pytest.raises(OSError, match="injected partial copy failure"):
            _publish_dashboard_generations(source, [target], run_id)

        assert (target / "sentinel").read_text(encoding="utf-8") == "previous"
        assert not list(tmp_path.rglob(".*.tmp"))
        assert not list(tmp_path.rglob(".*.previous"))

    def test_double_failure_preserves_backup_and_restores_earlier_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run_id = "wanted"
        source = self._valid_dashboard_source(tmp_path, run_id)
        public = tmp_path / "public" / "data"
        preview = tmp_path / "dist" / "data"
        for target, marker in ((public, "old-public"), (preview, "old-preview")):
            target.mkdir(parents=True)
            (target / "sentinel").write_text(marker, encoding="utf-8")
        real_replace = Path.replace

        def fail_preview_promotion_and_restore(path: Path, destination: Path) -> Path:
            if destination == preview and (
                path.name.endswith(".tmp") or path.name.endswith(".previous")
            ):
                raise OSError("injected preview promotion/restore failure")
            return real_replace(path, destination)

        monkeypatch.setattr(Path, "replace", fail_preview_promotion_and_restore)

        with pytest.raises(RuntimeError, match="preserved for manual recovery") as excinfo:
            _publish_dashboard_generations(source, [public, preview], run_id)

        assert (public / "sentinel").read_text(encoding="utf-8") == "old-public"
        assert not preview.exists()
        backups = list((tmp_path / "dist").glob(".data.*.previous"))
        assert len(backups) == 1
        assert (backups[0] / "sentinel").read_text(encoding="utf-8") == "old-preview"
        assert str(backups[0]) in str(excinfo.value)
        assert str(preview) in str(excinfo.value)
        assert not list(tmp_path.rglob(".*.tmp"))

    @staticmethod
    def _valid_dashboard_source(tmp_path: Path, run_id: str) -> Path:
        source = tmp_path / f"source-{run_id}"
        source.mkdir()
        (source / plan_server.NEXT_GW_FILENAME).write_text(
            json.dumps(
                {
                    "plans": [
                        {"optimizer_run_id": run_id, "plan_kind": "user_custom"},
                        {"optimizer_run_id": "default", "plan_kind": "platform_default"},
                        {"optimizer_run_id": "diagnostic", "plan_kind": "platform_diagnostic"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        return source


@pytest.fixture
def loopback_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ThreadingHTTPServer:
    """A real server on an ephemeral loopback port with the pipeline monkeypatched out."""
    monkeypatch.setattr(plan_server, "_git_worktree_clean", lambda repo: True)
    monkeypatch.setattr(
        plan_server,
        "run_plan",
        lambda state, locks, excludes, bench: {
            "optimizer_run_id": "r" * 64,
            "decision_sha256": "d" * 64,
            "captain": "Stub",
            "locks_seen": locks,
            "excludes_seen": excludes,
            "bench_seen": bench,
        },
    )
    monkeypatch.setattr(
        plan_server,
        "fetch_and_store_manager_team",
        lambda state, manager_id, *, require_full_registry: {
            "manager_id_seen": manager_id,
            "full_registry_seen": require_full_registry,
        },
    )
    monkeypatch.setattr(
        plan_server,
        "_load_manager_capture",
        lambda state, capture_id: {"capture_id": capture_id},
    )
    monkeypatch.setattr(
        plan_server,
        "_manager_team_preview",
        lambda state, capture, *, require_full_registry: {
            "capture_seen": capture["capture_id"],
            "full_registry_seen": require_full_registry,
        },
    )
    monkeypatch.setattr(
        plan_server,
        "run_manager_plan",
        lambda state, capture_id, locks, excludes, bench, override: {
            "capture_seen": capture_id,
            "locks_seen": locks,
            "excludes_seen": excludes,
            "bench_seen": bench,
            "override_seen": override,
        },
    )
    insight_service = InsightService(provider=None, cache_dir=tmp_path / "insight-cache")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        make_handler(ServerState(tmp_path, insight_service=insight_service)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


class TestHttpSurface:
    def _request(
        self,
        server: ThreadingHTTPServer,
        path: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
        origin: str | None = None,
    ) -> tuple[int, dict[str, str], str]:
        url = f"http://127.0.0.1:{server.server_address[1]}{path}"
        request = urllib.request.Request(url, data=body, method=method)
        if body is not None:
            request.add_header("Content-Type", "application/json")
        if origin is not None:
            request.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = response.read().decode("utf-8")
                return response.status, dict(response.headers), payload
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8")
            return exc.code, dict(exc.headers), payload

    def test_status_reports_the_server_state(self, loopback_server: ThreadingHTTPServer) -> None:
        status, _, payload = self._request(loopback_server, "/status")
        body = json.loads(payload)
        assert status == 200
        assert body["busy"] is False
        assert body["worktree_clean"] is True
        assert body["forecast_ready"] is False
        assert body["runtime"]["python_executable"]
        assert body["runtime"]["python_prefix"]
        assert body["runtime"]["pulp_package_version"]
        assert body["runtime"]["cbc_binary_version"]
        assert body["runtime"]["solver_ready"] is True
        assert body["runtime"]["solver_discovery_attempts"] >= 1
        assert body["runtime"]["solver_discovery_error"] is None

    def test_insight_status_is_exact_and_disabled_by_default(
        self, loopback_server: ThreadingHTTPServer
    ) -> None:
        status, _, payload = self._request(loopback_server, "/insights/status")
        assert status == 200
        assert json.loads(payload) == {
            "enabled": False,
            "provider": None,
            "model": None,
            "prompt_version": PROMPT_VERSION,
        }

    def test_disabled_and_invalid_insight_requests_return_stable_safe_errors(
        self, loopback_server: ThreadingHTTPServer
    ) -> None:
        status, _, payload = self._request(
            loopback_server,
            "/insights/summary",
            method="POST",
            body=_insight_request_bytes(),
        )
        assert status == 503
        assert json.loads(payload) == {
            "schema": "fpl.insight-summary-error",
            "schema_version": INSIGHT_SCHEMA_VERSION,
            "code": "insights_disabled",
            "message": "AI insight rendering is not configured on this server.",
        }

        status, _, payload = self._request(
            loopback_server,
            "/insights/summary",
            method="POST",
            body=_insight_request_bytes(prompt="arbitrary prompt"),
        )
        assert status == 422
        assert json.loads(payload)["code"] == "invalid_request"

    def test_insight_request_is_origin_protected(
        self, loopback_server: ThreadingHTTPServer
    ) -> None:
        status, _, payload = self._request(
            loopback_server,
            "/insights/summary",
            method="POST",
            body=_insight_request_bytes(),
            origin="https://evil.example",
        )
        assert status == 403
        assert "not allowed" in json.loads(payload)["error"]

    def test_insight_generation_does_not_take_or_wait_for_optimizer_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_git_worktree_clean", lambda repo: True)
        insight_service = InsightService(
            provider=_HttpInsightProvider(),
            cache_dir=tmp_path / "insight-cache",
            evidence_resolver=_fake_insight_evidence,
        )
        state = ServerState(tmp_path, insight_service=insight_service)
        assert state.run_lock.acquire(blocking=False)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            status, _, payload = self._request(
                server,
                "/insights/summary",
                method="POST",
                body=_insight_request_bytes(),
            )
            body = json.loads(payload)
            assert status == 200
            assert body["schema"] == "fpl.insight-summary-response"
            assert body["source"] == "provider"
            assert body["provider"] == "fake"
            assert body["model"] == "fake-model-v1"
            assert body["prompt_version"] == PROMPT_VERSION
            assert body["items"] == [
                {
                    "text": "The displayed export reports complete horizon coverage.",
                    "citations": ["summary.coverage"],
                }
            ]
            assert "insights" not in body
            assert state.run_lock.locked()
        finally:
            state.run_lock.release()
            server.shutdown()
            server.server_close()

    def test_plan_posts_through_to_the_pipeline(self, loopback_server: ThreadingHTTPServer) -> None:
        status, _, payload = self._request(
            loopback_server,
            "/plan",
            method="POST",
            body=json.dumps(
                {"locks": [7, 3], "excludes": [11, 9], "min_bench_appearance": 0.25}
            ).encode("utf-8"),
        )
        body = json.loads(payload)
        assert status == 200
        assert body["ok"] is True
        assert body["locks_seen"] == [3, 7]
        assert body["excludes_seen"] == [9, 11]
        assert body["bench_seen"] == 0.25

    def test_manager_routes_validate_and_dispatch(
        self, loopback_server: ThreadingHTTPServer
    ) -> None:
        capture_id = "manager-" + "1" * 64

        status, _, payload = self._request(
            loopback_server,
            "/manager-team",
            method="POST",
            body=json.dumps({"manager_id": 42}).encode("utf-8"),
        )
        assert status == 200
        assert json.loads(payload) == {
            "ok": True,
            "manager_id_seen": 42,
            "full_registry_seen": True,
        }

        status, _, payload = self._request(
            loopback_server,
            "/manager-team/capture",
            method="POST",
            body=json.dumps({"capture_id": capture_id}).encode("utf-8"),
        )
        assert status == 200
        assert json.loads(payload) == {
            "ok": True,
            "capture_seen": capture_id,
            "full_registry_seen": True,
        }

        status, _, payload = self._request(
            loopback_server,
            "/manager-team/members",
            method="POST",
            body=json.dumps({"manager_id": 42}).encode("utf-8"),
        )
        assert status == 200
        assert json.loads(payload) == {
            "ok": True,
            "manager_id_seen": 42,
            "full_registry_seen": False,
        }

        status, _, payload = self._request(
            loopback_server,
            "/manager-team/members/capture",
            method="POST",
            body=json.dumps({"capture_id": capture_id}).encode("utf-8"),
        )
        assert status == 200
        assert json.loads(payload) == {
            "ok": True,
            "capture_seen": capture_id,
            "full_registry_seen": False,
        }

        status, _, payload = self._request(
            loopback_server,
            "/manager-plan",
            method="POST",
            body=json.dumps(
                {
                    "capture_id": capture_id,
                    "locks": [7, 3],
                    "excludes": [11, 9],
                    "min_bench_appearance": 0.25,
                    "free_transfers_override": 0,
                }
            ).encode("utf-8"),
        )
        body = json.loads(payload)
        assert status == 200
        assert body["capture_seen"] == capture_id
        assert body["locks_seen"] == [3, 7]
        assert body["excludes_seen"] == [9, 11]
        assert body["bench_seen"] == 0.25
        assert body["override_seen"] == 0

    @pytest.mark.parametrize(
        ("route", "body"),
        [
            ("/manager-team", {"manager_id": 42}),
            ("/manager-team/capture", {"capture_id": "manager-" + "1" * 64}),
            ("/manager-team/members", {"manager_id": 42}),
            (
                "/manager-team/members/capture",
                {"capture_id": "manager-" + "1" * 64},
            ),
            ("/manager-plan", {"capture_id": "manager-" + "1" * 64}),
        ],
    )
    def test_manager_routes_require_same_machine_authorization(
        self,
        loopback_server: ThreadingHTTPServer,
        route: str,
        body: dict[str, object],
    ) -> None:
        status, _, payload = self._request(
            loopback_server,
            route,
            method="POST",
            body=json.dumps(body).encode("utf-8"),
            origin="https://evil.example",
        )
        assert status == 403
        assert "not allowed" in json.loads(payload)["error"]

    def test_bad_body_is_a_409_with_a_safe_message(
        self, loopback_server: ThreadingHTTPServer
    ) -> None:
        status, _, payload = self._request(
            loopback_server,
            "/plan",
            method="POST",
            body=json.dumps({"locks": "no"}).encode("utf-8"),
        )
        assert status == 409
        assert "list of player codes" in json.loads(payload)["error"]

    def test_a_crashing_pipeline_returns_a_reason_not_a_dead_socket(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reported ERR_EMPTY_RESPONSE: an uncaught solver exception must still answer."""
        monkeypatch.setattr(plan_server, "_git_worktree_clean", lambda repo: True)

        def boom(
            state: object, locks: list[int], excludes: list[int], bench: float
        ) -> dict[str, object]:
            raise RuntimeError(
                "initial squad lineup violates min_bench_appearance before transfer planning"
            )

        monkeypatch.setattr(plan_server, "run_plan", boom)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(ServerState(tmp_path)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            status, _, payload = self._request(
                server, "/plan", method="POST", body=json.dumps({"locks": []}).encode("utf-8")
            )
            body = json.loads(payload)
            assert status == 500
            assert "threshold is too high" in body["error"]
            assert "min_bench_appearance" in body["error"]
        finally:
            server.shutdown()
            server.server_close()

    def test_foreign_origin_is_refused(self, loopback_server: ThreadingHTTPServer) -> None:
        url = f"http://127.0.0.1:{loopback_server.server_address[1]}/status"
        request = urllib.request.Request(url, headers={"Origin": "https://evil.example"})
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(request, timeout=10)
        assert excinfo.value.code == 403

    def test_same_machine_origin_is_echoed_for_cors(
        self, loopback_server: ThreadingHTTPServer
    ) -> None:
        status, headers, _ = self._request(
            loopback_server,
            "/plan",
            method="POST",
            body=json.dumps({"locks": []}).encode("utf-8"),
            origin="http://localhost:5173",
        )
        assert status == 200
        assert headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"
