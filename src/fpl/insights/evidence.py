"""Resolve insight selectors against one verified static dashboard generation.

The browser supplies identity and display selectors only.  This module owns every word and
number sent to an optional language provider, after revalidating the published generation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from fpl.insights.contracts import (
    InsightDisplayScope,
    InsightFact,
    InsightFactKind,
    InsightPage,
    InsightPastMetric,
    InsightReadModel,
    InsightSummaryRequest,
    ResolvedInsightEvidence,
)
from fpl.publish.dashboard_json import (
    DASHBOARD_JSON_SCHEMA_VERSION,
    DashboardJsonError,
    validate_dashboard_json,
)


class InsightEvidenceError(ValueError):
    """The selector cannot be resolved to one verified public generation."""


_PAGE_FILES: Final[dict[InsightPage, tuple[InsightReadModel, ...]]] = {
    InsightPage.SUMMARY: (InsightReadModel.SUMMARY,),
    InsightPage.FIXTURE_MATRIX: (InsightReadModel.FIXTURE_MATRIX,),
    InsightPage.PLAYERS: (InsightReadModel.PLAYERS, InsightReadModel.PLAYER_HORIZONS),
    InsightPage.PLAYER_ANALYTICS: (
        InsightReadModel.PLAYERS,
        InsightReadModel.PLAYER_HORIZONS,
    ),
    InsightPage.TEAM_ANALYTICS: (InsightReadModel.FIXTURE_MATRIX,),
    InsightPage.PLAYER_FORECAST_VS_ACTUAL: (InsightReadModel.PLAYER_FORECAST_VS_ACTUAL,),
    InsightPage.TEAM_FORECAST_VS_ACTUAL: (InsightReadModel.TEAM_FORECAST_VS_ACTUAL,),
}

_PAGE_SCOPE_FIELDS: Final[dict[InsightPage, frozenset[str]]] = {
    InsightPage.SUMMARY: frozenset({"gw_from", "gw_to"}),
    InsightPage.FIXTURE_MATRIX: frozenset(
        {"gw_from", "gw_to", "team_code", "view", "venue", "form_window"}
    ),
    InsightPage.PLAYERS: frozenset(
        {
            "gw_from",
            "gw_to",
            "actual_gw_from",
            "actual_gw_to",
            "position",
            "team_code",
            "view",
            "venue",
            "form_window",
            "min_price_tenths",
            "max_price_tenths",
            "min_avg_minutes_l5",
            "availability",
        }
    ),
    InsightPage.PLAYER_ANALYTICS: frozenset(
        {
            "gw_from",
            "gw_to",
            "position",
            "team_code",
            "view",
            "form_window",
            "threshold",
            "min_price_tenths",
            "max_price_tenths",
            "min_avg_minutes_l5",
            "availability",
            "past_metric",
        }
    ),
    InsightPage.TEAM_ANALYTICS: frozenset(
        {"gw_from", "gw_to", "team_code", "view", "venue", "form_window", "past_metric"}
    ),
    InsightPage.PLAYER_FORECAST_VS_ACTUAL: frozenset(
        {"gw_from", "gw_to", "position", "team_code", "view"}
    ),
    InsightPage.TEAM_FORECAST_VS_ACTUAL: frozenset(
        {"gw_from", "gw_to", "team_code", "view", "venue"}
    ),
}

_CAVEATS: Final[dict[InsightPage, tuple[str, ...]]] = {
    InsightPage.SUMMARY: (
        "Expected points may be summed; published probabilities are not combined here.",
        "This development forecast is exploratory and does not establish a model verdict.",
    ),
    InsightPage.FIXTURE_MATRIX: (
        "Future forecast values and backward-looking form remain separate.",
        "Missing published values remain missing rather than zero.",
    ),
    InsightPage.PLAYERS: (
        "Availability is a reported next-round overlay and is not applied to raw expected points.",
        "Actual-GW totals use only complete finalized current-season fixtures and are not a "
        "future player forecast.",
    ),
    InsightPage.PLAYER_ANALYTICS: (
        "Frontier membership is display geometry, not a model quantity or model verdict.",
        "Published cumulative probabilities are selected at one exact horizon, never summed.",
    ),
    InsightPage.TEAM_ANALYTICS: (
        "Expected clean sheets is a sum of published fixture probabilities, not a new probability.",
        "Future club environment and backward-looking form remain separate.",
    ),
    InsightPage.PLAYER_FORECAST_VS_ACTUAL: (
        "Only complete officially final player gameweeks are scored; "
        "partial gameweeks stay absent.",
        "Historical residuals are diagnostic and are not future utility.",
    ),
    InsightPage.TEAM_FORECAST_VS_ACTUAL: (
        "Only official final fixtures with reciprocal outcome sides are scored.",
        "Positive defence residual means more conceded than forecast and is worse.",
    ),
}


@dataclass(frozen=True)
class _Generation:
    manifest: Mapping[str, Any]
    documents: Mapping[InsightReadModel, Mapping[str, Any]]
    run: Mapping[str, Any]


def _strict_document(payload: bytes) -> Mapping[str, Any]:
    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON constant {value}")

    value = json.loads(payload.decode("utf-8"), parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise InsightEvidenceError("dashboard read model is not an object")
    return value


def _load_generation(directory: Path, request: InsightSummaryRequest) -> _Generation:
    root = Path(directory)
    manifest_path = root / InsightReadModel.MANIFEST.value
    try:
        before = manifest_path.read_bytes()
        manifest = validate_dashboard_json(root)
        if manifest.get("json_schema_version") != DASHBOARD_JSON_SCHEMA_VERSION:
            raise InsightEvidenceError("dashboard generation schema is unsupported")
        if manifest.get("content_sha256") != request.manifest_sha256:
            raise InsightEvidenceError("dashboard generation identity does not match the request")

        matching_runs = [
            item
            for item in manifest.get("runs", [])
            if isinstance(item, dict)
            and item.get("run_id") == request.run_id
            and item.get("season") == request.season
        ]
        if len(matching_runs) != 1:
            raise InsightEvidenceError("forecast run identity is absent or ambiguous")
        run = matching_runs[0]
        run_as_of = datetime.fromisoformat(str(run.get("as_of")))
        if run_as_of.tzinfo is None or run_as_of != request.as_of:
            raise InsightEvidenceError("forecast run timestamp does not match the request")

        documents: dict[InsightReadModel, Mapping[str, Any]] = {}
        for source in _PAGE_FILES[request.page]:
            payload = (root / source.value).read_bytes()
            entry = manifest["files"][source.value]
            if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                raise InsightEvidenceError("dashboard read model changed after validation")
            document = _strict_document(payload)
            if document.get("json_schema_version") != DASHBOARD_JSON_SCHEMA_VERSION:
                raise InsightEvidenceError("dashboard read model schema is unsupported")
            documents[source] = document
        after = manifest_path.read_bytes()
    except InsightEvidenceError:
        raise
    except (DashboardJsonError, OSError, KeyError, TypeError, ValueError) as exc:
        raise InsightEvidenceError("dashboard generation could not be verified") from exc
    if before != after:
        raise InsightEvidenceError("dashboard generation changed while resolving evidence")
    return _Generation(manifest=manifest, documents=documents, run=run)


def _fact(
    identifier: str,
    kind: InsightFactKind,
    statement: str,
    *sources: InsightReadModel,
) -> InsightFact:
    return InsightFact(
        id=identifier,
        kind=kind,
        statement=statement,
        source_read_models=sources,
    )


def _number(value: object, places: int = 2) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "unavailable"
    return f"{float(value):.{places}f}"


def _label(value: object, fallback: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    cleaned = " ".join(value.split())
    return cleaned[:48]


def _scope_values(scope: InsightDisplayScope) -> dict[str, object]:
    return {
        key: value for key, value in scope.model_dump(mode="python").items() if value is not None
    }


def _validate_scope(request: InsightSummaryRequest, run: Mapping[str, Any]) -> None:
    values = _scope_values(request.scope)
    unexpected = set(values) - _PAGE_SCOPE_FIELDS[request.page]
    if unexpected:
        raise InsightEvidenceError("scope contains selectors unavailable to this page")
    view = request.scope.view.value if request.scope.view is not None else None
    allowed_views: dict[InsightPage, frozenset[str | None]] = {
        InsightPage.SUMMARY: frozenset({None}),
        InsightPage.FIXTURE_MATRIX: frozenset({None, "overall", "attack", "defence"}),
        InsightPage.PLAYERS: frozenset({None, "overall", "attack", "defence"}),
        InsightPage.PLAYER_ANALYTICS: frozenset(
            {"value", "upside_downside", "differential", "past_future"}
        ),
        InsightPage.TEAM_ANALYTICS: frozenset({"environment", "attack-floor", "past-future"}),
        InsightPage.PLAYER_FORECAST_VS_ACTUAL: frozenset({None, "overall"}),
        InsightPage.TEAM_FORECAST_VS_ACTUAL: frozenset({None, "attack", "defence", "clean_sheet"}),
    }
    if view not in allowed_views[request.page]:
        raise InsightEvidenceError("scope view is unavailable to this page")
    if request.scope.threshold is not None and view != "upside_downside":
        raise InsightEvidenceError("scope threshold is unavailable to this view")
    if request.scope.past_metric is not None:
        if request.page is InsightPage.PLAYER_ANALYTICS:
            allowed_metrics = {
                InsightPastMetric.POINTS,
                InsightPastMetric.XG_PER_90,
                InsightPastMetric.XA_PER_90,
            }
            expected_view = "past_future"
        elif request.page is InsightPage.TEAM_ANALYTICS:
            allowed_metrics = {
                InsightPastMetric.TEAM_XG,
                InsightPastMetric.TEAM_GOALS,
                InsightPastMetric.TEAM_XGC,
                InsightPastMetric.TEAM_GOALS_AGAINST,
            }
            expected_view = "past-future"
        else:
            allowed_metrics = set()
            expected_view = ""
        if request.scope.past_metric not in allowed_metrics or view != expected_view:
            raise InsightEvidenceError("scope past metric is unavailable to this view")
    gw_from = request.scope.gw_from
    gw_to = request.scope.gw_to
    run_from = run.get("gw_from")
    run_to = run.get("gw_to")
    if not isinstance(run_from, int) or not isinstance(run_to, int):
        raise InsightEvidenceError("forecast run horizon is malformed")
    if gw_from is not None and not run_from <= gw_from <= run_to:
        raise InsightEvidenceError("scope starts outside the forecast horizon")
    if gw_to is not None and not run_from <= gw_to <= run_to:
        raise InsightEvidenceError("scope ends outside the forecast horizon")
    if request.page is InsightPage.PLAYER_ANALYTICS and gw_from is not None and gw_from != run_from:
        raise InsightEvidenceError("cumulative player horizons must start at the run boundary")


def _gw_bounds(scope: InsightDisplayScope, run: Mapping[str, Any]) -> tuple[int, int]:
    return int(scope.gw_from or run["gw_from"]), int(scope.gw_to or run["gw_to"])


def _venue_matches(was_home: object, scope: InsightDisplayScope) -> bool:
    if scope.venue is None or scope.venue.value == "all":
        return True
    if not isinstance(was_home, bool):
        return False
    return was_home if scope.venue.value == "home" else not was_home


def _position_matches(value: object, scope: InsightDisplayScope) -> bool:
    return scope.position is None or scope.position.value == "all" or value == scope.position.value


def _player_matches(player: Mapping[str, Any], scope: InsightDisplayScope) -> bool:
    if not _position_matches(player.get("position"), scope):
        return False
    if scope.team_code is not None and player.get("team_code") != scope.team_code:
        return False
    cost = player.get("now_cost")
    if scope.min_price_tenths is not None and (
        not isinstance(cost, int) or cost < scope.min_price_tenths
    ):
        return False
    if scope.max_price_tenths is not None and (
        not isinstance(cost, int) or cost > scope.max_price_tenths
    ):
        return False
    minutes = player.get("avg_minutes_last_5")
    if scope.min_avg_minutes_l5 is not None and (
        not isinstance(minutes, (int, float)) or minutes < scope.min_avg_minutes_l5
    ):
        return False
    status = player.get("availability_status")
    if scope.availability is not None and scope.availability.value == "available" and status != "a":
        return False
    return not (
        scope.availability is not None
        and scope.availability.value == "flagged"
        and (status is None or status == "a")
    )


def _coverage(page: str, count: int, noun: str, *sources: InsightReadModel) -> InsightFact:
    return _fact(
        f"{page}.coverage",
        InsightFactKind.COVERAGE,
        f"The selected scope contains {count} published {noun}.",
        *sources,
    )


def _pareto(
    rows: Sequence[tuple[Mapping[str, Any], float, float]],
    *,
    maximize_x: bool,
    maximize_y: bool,
) -> list[Mapping[str, Any]]:
    frontier: list[Mapping[str, Any]] = []
    for row, x, y in rows:
        dominated = False
        for other, ox, oy in rows:
            if other is row:
                continue
            x_good = ox >= x if maximize_x else ox <= x
            y_good = oy >= y if maximize_y else oy <= y
            x_better = ox > x if maximize_x else ox < x
            y_better = oy > y if maximize_y else oy < y
            if x_good and y_good and (x_better or y_better):
                dominated = True
                break
        if not dominated:
            frontier.append(row)
    return frontier


def _summary(generation: _Generation, request: InsightSummaryRequest) -> list[InsightFact]:
    document = generation.documents[InsightReadModel.SUMMARY]
    latest = document.get("latest_run")
    if not isinstance(latest, dict) or latest.get("run_id") != request.run_id:
        raise InsightEvidenceError("summary read model does not describe the requested run")
    facts = [
        _fact(
            "summary.coverage",
            InsightFactKind.COVERAGE,
            f"The published roster contains {document['roster']['players']} players "
            f"across {document['roster']['teams']} clubs.",
            InsightReadModel.SUMMARY,
        )
    ]
    top = document.get("horizon_top_xp") or document.get("top_xp") or []
    if top:
        leader = top[0]
        facts.append(
            _fact(
                "summary.xp.leader",
                InsightFactKind.RANK,
                f"{_label(leader.get('web_name'), 'The leading player')} leads the "
                f"published horizon with {_number(leader.get('expected_points'))} "
                "expected points.",
                InsightReadModel.SUMMARY,
            )
        )
    fixtures = document.get("easiest_fixtures") or []
    if fixtures:
        fixture = fixtures[0]
        facts.append(
            _fact(
                "summary.fixture.leader",
                InsightFactKind.RANK,
                f"{_label(fixture.get('team_short_name'), 'The leading club')} has the "
                "highest published overall fixture-ease row at "
                f"{_number(fixture.get('overall_ease_index'), 1)}.",
                InsightReadModel.SUMMARY,
            )
        )
    return facts


def _fixture_rows(
    generation: _Generation, request: InsightSummaryRequest
) -> tuple[list[tuple[Mapping[str, Any], Mapping[str, Any]]], Mapping[str, Any]]:
    document = generation.documents[InsightReadModel.FIXTURE_MATRIX]
    gw_from, gw_to = _gw_bounds(request.scope, generation.run)
    teams = [
        team
        for team in document.get("teams", [])
        if team.get("run_id") == request.run_id and team.get("season") == request.season
    ]
    if request.scope.team_code is not None and not any(
        team.get("team_code") == request.scope.team_code for team in teams
    ):
        raise InsightEvidenceError("selected club is absent from the requested run")
    rows = [
        (team, fixture)
        for team in teams
        if request.scope.team_code is None or team.get("team_code") == request.scope.team_code
        for fixture in team.get("fixtures", [])
        if isinstance(fixture.get("gw"), int)
        and gw_from <= fixture["gw"] <= gw_to
        and _venue_matches(fixture.get("was_home"), request.scope)
    ]
    return rows, document


def _fixture_matrix(generation: _Generation, request: InsightSummaryRequest) -> list[InsightFact]:
    rows, _ = _fixture_rows(generation, request)
    facts = [
        _coverage("fixture", len(rows), "forecast fixture sides", InsightReadModel.FIXTURE_MATRIX)
    ]
    view = request.scope.view.value if request.scope.view is not None else "overall"
    key = {
        "attack": "attack_ease_index",
        "defence": "probability_clean_sheet",
        "overall": "overall_ease_index",
    }.get(view, "overall_ease_index")
    measured = [
        (team, fixture) for team, fixture in rows if isinstance(fixture.get(key), (int, float))
    ]
    measured.sort(key=lambda item: (-float(item[1][key]), int(item[1]["fixture"])))
    for index, (team, fixture) in enumerate(measured[:2], 1):
        facts.append(
            _fact(
                f"fixture.rank.{index}",
                InsightFactKind.RANK,
                f"{_label(team.get('short_name'), 'Club')} ranks {index} on the selected "
                f"published value at {_number(fixture.get(key), 1)} against "
                f"{_label(fixture.get('opponent_short_name'), 'opponent')}.",
                InsightReadModel.FIXTURE_MATRIX,
            )
        )
    fallback = sum(bool(fixture.get("stage_a_league_average_team")) for _, fixture in rows)
    facts.append(
        _fact(
            "fixture.fallback.coverage",
            InsightFactKind.COVERAGE,
            f"{fallback} selected fixture sides use the published Stage A "
            "league-average fallback flag.",
            InsightReadModel.FIXTURE_MATRIX,
        )
    )
    return facts


def _selected_players(
    generation: _Generation, request: InsightSummaryRequest
) -> tuple[list[Mapping[str, Any]], Mapping[str, Any], Mapping[str, Any]]:
    players_doc = generation.documents[InsightReadModel.PLAYERS]
    horizons_doc = generation.documents[InsightReadModel.PLAYER_HORIZONS]
    candidates = [
        player
        for player in players_doc.get("players", [])
        if player.get("run_id") == request.run_id
        and player.get("season") == request.season
        and _player_matches(player, request.scope)
    ]
    all_run_players = [
        player
        for player in players_doc.get("players", [])
        if player.get("run_id") == request.run_id and player.get("season") == request.season
    ]
    if request.scope.team_code is not None and not any(
        player.get("team_code") == request.scope.team_code for player in all_run_players
    ):
        raise InsightEvidenceError("selected club is absent from the requested run")
    return candidates, players_doc, horizons_doc


def _player_fixture_xp(
    player: Mapping[str, Any], request: InsightSummaryRequest, run: Mapping[str, Any]
) -> float:
    gw_from, gw_to = _gw_bounds(request.scope, run)
    return sum(
        float(fixture["expected_points"])
        for fixture in player.get("fixtures", [])
        if isinstance(fixture.get("gw"), int)
        and gw_from <= fixture["gw"] <= gw_to
        and _venue_matches(fixture.get("was_home"), request.scope)
        and isinstance(fixture.get("expected_points"), (int, float))
    )


def _has_player_fixture_xp(
    player: Mapping[str, Any], request: InsightSummaryRequest, run: Mapping[str, Any]
) -> bool:
    gw_from, gw_to = _gw_bounds(request.scope, run)
    return any(
        isinstance(fixture.get("gw"), int)
        and gw_from <= fixture["gw"] <= gw_to
        and _venue_matches(fixture.get("was_home"), request.scope)
        and isinstance(fixture.get("expected_points"), (int, float))
        for fixture in player.get("fixtures", [])
    )


def _players(generation: _Generation, request: InsightSummaryRequest) -> list[InsightFact]:
    players, _, _ = _selected_players(generation, request)
    scored = [
        (player, _player_fixture_xp(player, request, generation.run))
        for player in players
        if _has_player_fixture_xp(player, request, generation.run)
    ]
    scored.sort(key=lambda item: (-item[1], int(item[0]["code"])))
    facts = [
        _coverage(
            "players",
            len(players),
            "players after all selected filters",
            InsightReadModel.PLAYERS,
            InsightReadModel.PLAYER_HORIZONS,
        )
    ]
    facts.append(
        _fact(
            "players.xp.coverage",
            InsightFactKind.COVERAGE,
            f"{len(scored)} selected players have at least one measured expected-points "
            f"fixture; {len(players) - len(scored)} do not.",
            InsightReadModel.PLAYERS,
        )
    )
    for index, (player, xp) in enumerate(scored[:3], 1):
        facts.append(
            _fact(
                f"players.xp.rank.{index}",
                InsightFactKind.RANK,
                f"{_label(player.get('web_name'), 'Player')} ranks {index} with {xp:.2f} "
                "summed published expected points in the selected fixtures.",
                InsightReadModel.PLAYERS,
            )
        )
    actual_from = request.scope.actual_gw_from
    actual_to = request.scope.actual_gw_to
    if actual_from is not None and actual_to is not None:
        run_players = [
            player
            for player in generation.documents[InsightReadModel.PLAYERS].get("players", [])
            if player.get("run_id") == request.run_id
            and player.get("season") == request.season
        ]
        available_gws = sorted(
            {
                int(actual["gw"])
                for player in run_players
                for actual in player.get("actuals", [])
                if isinstance(actual.get("gw"), int)
            }
        )
        if not available_gws:
            raise InsightEvidenceError(
                "actual-gameweek scope was requested but no finalized current-season actuals exist"
            )
        if actual_from < available_gws[0] or actual_to > available_gws[-1]:
            raise InsightEvidenceError("actual-gameweek scope exceeds finalized current-season data")

        actual_scored: list[tuple[Mapping[str, Any], int]] = []
        for player in players:
            selected_actuals = [
                actual
                for actual in player.get("actuals", [])
                if isinstance(actual.get("gw"), int)
                and actual_from <= int(actual["gw"]) <= actual_to
            ]
            appeared = [
                actual
                for actual in selected_actuals
                if isinstance(actual.get("minutes"), int) and int(actual["minutes"]) >= 1
            ]
            if not appeared or any(
                isinstance(actual.get("points_under_rules_2026_27"), bool)
                or not isinstance(actual.get("points_under_rules_2026_27"), int)
                for actual in appeared
            ):
                continue
            actual_scored.append(
                (
                    player,
                    sum(int(actual["points_under_rules_2026_27"]) for actual in appeared),
                )
            )
        actual_scored.sort(key=lambda item: (-item[1], int(item[0]["code"])))
        facts.append(
            _fact(
                "players.actual.coverage",
                InsightFactKind.COVERAGE,
                f"{len(actual_scored)} selected players have complete replayed actual points "
                f"from finalized current-season GW{actual_from} through GW{actual_to}; "
                f"{len(players) - len(actual_scored)} do not.",
                InsightReadModel.PLAYERS,
            )
        )
        for index, (player, points) in enumerate(actual_scored[:3], 1):
            facts.append(
                _fact(
                    f"players.actual.rank.{index}",
                    InsightFactKind.RANK,
                    f"{_label(player.get('web_name'), 'Player')} ranks {index} with {points} "
                    f"replayed actual points from finalized GW{actual_from} through "
                    f"GW{actual_to}.",
                    InsightReadModel.PLAYERS,
                )
            )
    return facts


def _horizon_map(
    document: Mapping[str, Any],
) -> tuple[dict[tuple[str, str, int], dict[int, dict[str, float]]], list[str]]:
    fields = [str(field) for field in document.get("horizon_fields", [])]
    result: dict[tuple[str, str, int], dict[int, dict[str, float]]] = {}
    for player in document.get("players", []):
        endpoints: dict[int, dict[str, float]] = {}
        for row in player.get("horizons", []):
            values = dict(zip(fields, row, strict=True))
            endpoints[int(values["gw_to"])] = {
                key: float(value) for key, value in values.items() if key != "gw_to"
            }
        result[(player["run_id"], player["season"], int(player["code"]))] = endpoints
    return result, fields


def _form_window_key(scope: InsightDisplayScope) -> str:
    value = scope.form_window if scope.form_window is not None else 5
    return value if value == "season_to_date" else f"last_{value}"


def _past_value(player: Mapping[str, Any], scope: InsightDisplayScope) -> float | None:
    form = player.get("form")
    if not isinstance(form, dict):
        return None
    window = form.get("windows", {}).get(_form_window_key(scope))
    if not isinstance(window, dict):
        return None
    metric = scope.past_metric or InsightPastMetric.POINTS
    key = {
        InsightPastMetric.POINTS: "points_under_rules_2026_27",
        InsightPastMetric.XG_PER_90: "expected_goals_per_90",
        InsightPastMetric.XA_PER_90: "expected_assists_per_90",
    }.get(metric)
    value = window.get(key) if key is not None else None
    return float(value) if isinstance(value, (int, float)) else None


def _player_analytics(generation: _Generation, request: InsightSummaryRequest) -> list[InsightFact]:
    players, _, horizons_doc = _selected_players(generation, request)
    endpoint_map, _ = _horizon_map(horizons_doc)
    gw_to = request.scope.gw_to or int(generation.run["gw_to"])
    enriched: list[tuple[Mapping[str, Any], Mapping[str, float]]] = []
    for player in players:
        endpoint = endpoint_map.get((request.run_id, request.season, int(player["code"])), {}).get(
            gw_to
        )
        if endpoint is not None:
            enriched.append((player, endpoint))
    facts = [
        _coverage(
            "player.analytics",
            len(enriched),
            "players with an exact cumulative endpoint",
            InsightReadModel.PLAYERS,
            InsightReadModel.PLAYER_HORIZONS,
        )
    ]
    view = request.scope.view.value if request.scope.view is not None else "value"
    points: list[tuple[Mapping[str, Any], float, float]] = []
    if view == "value":
        points = [
            (player, endpoint["xp"], float(player["now_cost"]))
            for player, endpoint in enriched
            if isinstance(player.get("now_cost"), int)
        ]
        maximize = (True, False)
        axis = "expected points and lower published price"
    elif view == "upside_downside":
        threshold = request.scope.threshold or 6
        points = [
            (player, endpoint[f"p_ge_{threshold}"], endpoint["p_le_2"])
            for player, endpoint in enriched
        ]
        maximize = (True, False)
        axis = f"published P(points at least {threshold}) and lower P(points at most 2)"
    elif view == "differential":
        points = [
            (player, endpoint["xp"], float(player["selected_by_percent"]))
            for player, endpoint in enriched
            if isinstance(player.get("selected_by_percent"), (int, float))
        ]
        maximize = (True, False)
        axis = "expected points and lower published ownership"
    else:
        points = [
            (player, past, endpoint["xp"])
            for player, endpoint in enriched
            if (past := _past_value(player, request.scope)) is not None
        ]
        maximize = (True, True)
        axis = "backward-looking form and future expected points"
    if view != "past_future":
        frontier = _pareto(points, maximize_x=maximize[0], maximize_y=maximize[1])
        names = ", ".join(_label(player.get("web_name"), "Player") for player in frontier[:6])
        facts.append(
            _fact(
                "player.analytics.frontier",
                InsightFactKind.FRONTIER,
                f"{len(frontier)} selected players are non-dominated on {axis}; the "
                f"first displayed names are {names or 'none'}.",
                InsightReadModel.PLAYERS,
                InsightReadModel.PLAYER_HORIZONS,
            )
        )
    else:
        facts.append(
            _fact(
                "player.analytics.axis.coverage",
                InsightFactKind.COVERAGE,
                f"{len(points)} selected players have both measured past-form and future "
                "expected-points axes; no frontier is assigned to this explanatory view.",
                InsightReadModel.PLAYERS,
                InsightReadModel.PLAYER_HORIZONS,
            )
        )
    plotted_codes = {int(player["code"]) for player, _, _ in points}
    ranked = sorted(
        (
            (player, endpoint)
            for player, endpoint in enriched
            if int(player["code"]) in plotted_codes
        ),
        key=lambda item: (-item[1]["xp"], int(item[0]["code"])),
    )
    if ranked:
        leader_player, leader_endpoint = ranked[0]
        facts.append(
            _fact(
                "player.analytics.xp.leader",
                InsightFactKind.RANK,
                f"{_label(leader_player.get('web_name'), 'Player')} has the highest selected "
                f"exact cumulative expected points at {leader_endpoint['xp']:.2f}.",
                InsightReadModel.PLAYER_HORIZONS,
            )
        )
    return facts


def _complete_sum(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    """Match the frontend's complete-scope sum: one missing/non-finite leg makes it null."""
    if not rows:
        return None
    total = 0.0
    for row in rows:
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        numeric = float(value)
        if not isfinite(numeric):
            return None
        total += numeric
    return total


def _team_past_value(team: Mapping[str, Any], scope: InsightDisplayScope) -> float | None:
    form = team.get("form")
    if not isinstance(form, dict):
        return None
    window = form.get("windows", {}).get(_form_window_key(scope))
    if not isinstance(window, dict):
        return None
    metric = scope.past_metric or InsightPastMetric.TEAM_XG
    key = {
        InsightPastMetric.TEAM_XG: "team_xg_per_match",
        InsightPastMetric.TEAM_GOALS: "goals_for_per_match",
        InsightPastMetric.TEAM_XGC: "team_xgc_per_match",
        InsightPastMetric.TEAM_GOALS_AGAINST: "goals_against_per_match",
    }.get(metric)
    value = window.get(key) if key is not None else None
    return float(value) if isinstance(value, (int, float)) else None


def _team_analytics(generation: _Generation, request: InsightSummaryRequest) -> list[InsightFact]:
    rows, _ = _fixture_rows(generation, request)
    grouped: dict[int, tuple[Mapping[str, Any], list[Mapping[str, Any]]]] = {}
    for team, fixture in rows:
        grouped.setdefault(int(team["team_code"]), (team, []))[1].append(fixture)
    facts = [_coverage("team.analytics", len(grouped), "clubs", InsightReadModel.FIXTURE_MATRIX)]
    values: list[tuple[Mapping[str, Any], float, float]] = []
    view = request.scope.view.value if request.scope.view is not None else "environment"
    for team, fixtures in grouped.values():
        lambda_for = _complete_sum(fixtures, "lambda_for")
        lambda_against = _complete_sum(fixtures, "lambda_against")
        if view == "attack-floor":
            clean_sheets = _complete_sum(fixtures, "probability_clean_sheet")
            if clean_sheets is not None and lambda_for is not None:
                values.append((team, clean_sheets, lambda_for))
        elif view == "past-future":
            past = _team_past_value(team, request.scope)
            if past is not None:
                metric = request.scope.past_metric or InsightPastMetric.TEAM_XG
                future = (
                    lambda_against
                    if metric
                    in {
                        InsightPastMetric.TEAM_XGC,
                        InsightPastMetric.TEAM_GOALS_AGAINST,
                    }
                    else lambda_for
                )
                if future is not None:
                    values.append((team, past, future))
        elif lambda_against is not None and lambda_for is not None:
            values.append((team, lambda_against, lambda_for))
    if view != "past-future":
        frontier = _pareto(
            values,
            maximize_x=view == "attack-floor",
            maximize_y=True,
        )
        names = ", ".join(_label(team.get("short_name"), "Club") for team in frontier[:6])
        facts.append(
            _fact(
                "team.analytics.frontier",
                InsightFactKind.FRONTIER,
                f"{len(frontier)} clubs are non-dominated in the selected display "
                f"geometry; the first displayed names are {names or 'none'}.",
                InsightReadModel.FIXTURE_MATRIX,
            )
        )
    else:
        facts.append(
            _fact(
                "team.analytics.axis.coverage",
                InsightFactKind.COVERAGE,
                f"{len(values)} clubs have both measured past-form and future axes; "
                "no frontier is assigned to this explanatory view.",
                InsightReadModel.FIXTURE_MATRIX,
            )
        )
    ranked = sorted(values, key=lambda item: (-item[2], int(item[0]["team_code"])))
    if ranked:
        team, first, second = ranked[0]
        facts.append(
            _fact(
                "team.analytics.leader",
                InsightFactKind.RANK,
                f"{_label(team.get('short_name'), 'Club')} has the highest selected "
                f"vertical-axis value at {second:.2f}; its horizontal-axis value is {first:.2f}.",
                InsightReadModel.FIXTURE_MATRIX,
            )
        )
    return facts


def _find_run(document: Mapping[str, Any], request: InsightSummaryRequest) -> Mapping[str, Any]:
    matches: list[Mapping[str, Any]] = []
    for candidate in document.get("runs", []):
        if (
            isinstance(candidate, dict)
            and candidate.get("run_id") == request.run_id
            and candidate.get("season") == request.season
        ):
            matches.append(candidate)
    if len(matches) != 1 or datetime.fromisoformat(str(matches[0].get("as_of"))) != request.as_of:
        raise InsightEvidenceError("monitoring read model does not match the requested run")
    return matches[0]


def _player_fva(generation: _Generation, request: InsightSummaryRequest) -> list[InsightFact]:
    document = generation.documents[InsightReadModel.PLAYER_FORECAST_VS_ACTUAL]
    run = _find_run(document, request)
    gw_from, gw_to = _gw_bounds(request.scope, generation.run)
    rows = [
        row
        for row in run.get("observations", [])
        if gw_from <= row.get("gw", 0) <= gw_to
        and _position_matches(row.get("position"), request.scope)
        and (request.scope.team_code is None or row.get("team_code") == request.scope.team_code)
    ]
    forecast = sum(float(row["forecast_xp"]) for row in rows)
    actual = sum(float(row["actual_points"]) for row in rows)
    facts = [
        _coverage(
            "player.monitoring",
            len(rows),
            "fully finalized player-gameweeks",
            InsightReadModel.PLAYER_FORECAST_VS_ACTUAL,
        ),
        _fact(
            "player.monitoring.totals",
            InsightFactKind.ALLOWED_SUM,
            f"Selected published expected points sum to {forecast:.2f}; finalized "
            f"actual points sum to {actual:.2f}.",
            InsightReadModel.PLAYER_FORECAST_VS_ACTUAL,
        ),
    ]
    if rows:
        extreme = max(rows, key=lambda row: (abs(float(row["residual"])), -int(row["code"])))
        facts.append(
            _fact(
                "player.monitoring.extreme",
                InsightFactKind.COMPARISON,
                f"{_label(extreme.get('web_name'), 'Player')} in gameweek {extreme['gw']} "
                "has the largest absolute displayed residual at "
                f"{_number(abs(float(extreme['residual'])))} points.",
                InsightReadModel.PLAYER_FORECAST_VS_ACTUAL,
            )
        )
    return facts


def _team_fva(generation: _Generation, request: InsightSummaryRequest) -> list[InsightFact]:
    document = generation.documents[InsightReadModel.TEAM_FORECAST_VS_ACTUAL]
    run = _find_run(document, request)
    gw_from, gw_to = _gw_bounds(request.scope, generation.run)
    rows = [
        row
        for row in run.get("observations", [])
        if gw_from <= row.get("gw", 0) <= gw_to
        and (request.scope.team_code is None or row.get("team_code") == request.scope.team_code)
        and _venue_matches(row.get("was_home"), request.scope)
    ]
    facts = [
        _coverage(
            "team.monitoring",
            len(rows),
            "finalized reciprocal team-fixture sides",
            InsightReadModel.TEAM_FORECAST_VS_ACTUAL,
        )
    ]
    view = request.scope.view.value if request.scope.view is not None else "attack"
    if view == "clean_sheet":
        forecast = sum(float(row["probability_clean_sheet"]) for row in rows)
        actual = sum(bool(row["actual_clean_sheet"]) for row in rows)
        statement = (
            f"Expected clean sheets sum to {forecast:.2f}; finalized clean sheets total {actual}."
        )
    elif view == "defence":
        forecast = sum(float(row["lambda_against"]) for row in rows)
        actual = sum(int(row["actual_goals_against"]) for row in rows)
        statement = (
            f"Published goals-against expectations sum to {forecast:.2f}; "
            f"finalized goals conceded total {actual}."
        )
    else:
        forecast = sum(float(row["lambda_for"]) for row in rows)
        actual = sum(int(row["actual_goals_for"]) for row in rows)
        statement = (
            f"Published goals-for expectations sum to {forecast:.2f}; "
            f"finalized goals scored total {actual}."
        )
    facts.append(
        _fact(
            "team.monitoring.totals",
            InsightFactKind.ALLOWED_SUM,
            statement,
            InsightReadModel.TEAM_FORECAST_VS_ACTUAL,
        )
    )
    return facts


_BUILDERS = {
    InsightPage.SUMMARY: _summary,
    InsightPage.FIXTURE_MATRIX: _fixture_matrix,
    InsightPage.PLAYERS: _players,
    InsightPage.PLAYER_ANALYTICS: _player_analytics,
    InsightPage.TEAM_ANALYTICS: _team_analytics,
    InsightPage.PLAYER_FORECAST_VS_ACTUAL: _player_fva,
    InsightPage.TEAM_FORECAST_VS_ACTUAL: _team_fva,
}


def resolve_insight_evidence(
    dashboard_data_dir: Path, request: InsightSummaryRequest
) -> ResolvedInsightEvidence:
    """Return canonical server-authored evidence for exactly one verified generation."""
    generation = _load_generation(dashboard_data_dir, request)
    _validate_scope(request, generation.run)
    try:
        facts = _BUILDERS[request.page](generation, request)
        if not facts:
            facts = [
                _coverage(
                    request.page.value,
                    0,
                    "rows with publishable evidence",
                    *_PAGE_FILES[request.page],
                )
            ]
        return ResolvedInsightEvidence(
            request=request,
            facts=tuple(facts[:24]),
            caveats=_CAVEATS[request.page],
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        if isinstance(exc, InsightEvidenceError):
            raise
        raise InsightEvidenceError("dashboard evidence could not be resolved") from exc


__all__ = ["InsightEvidenceError", "resolve_insight_evidence"]
