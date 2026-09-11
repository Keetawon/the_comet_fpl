"""Descriptive scouting cannot change production forecasts or planning decisions."""

from __future__ import annotations

import ast
import json
from dataclasses import asdict, replace
from importlib.util import resolve_name
from pathlib import Path

import pytest

from fpl.artifacts.prospective_points import artifact_bytes
from fpl.config import repo_root
from fpl.features.player_attacking_usage import build_player_attacking_usage
from fpl.jobs.optimize_squad import _solve
from fpl.jobs.prospective_points_v1 import predict_prospective_points
from fpl.optimize.rules import load_squad_rules
from fpl.publish.player_attacking_usage import build_usage_export
from tests.test_player_attacking_usage_export import CUTOFF, _load, _write
from tests.test_prospective_points_v1 import AS_OF, _basic_db, _fixture, _player
from tests.test_squad_optimizer import _artifact, _base_players


def _bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False
    ).encode()


@pytest.mark.parametrize("environment", ["sdp_v2", "disabled"])
def test_descriptive_export_leaves_forecasts_and_optimizer_identical(
    tmp_path: Path, environment: str
) -> None:
    # Reuse the production regression's complete synthetic history/registry and the
    # optimizer's legal two-GW population. No operational DB or clean-Git CLI needed.
    con = _basic_db(  # type: ignore[no-untyped-call]  # Existing synthetic regression fixture.
        players=[_player(11, 1001, 3, 1), _player(12, 1002, 4, 2)],
        fixtures=[_fixture(501, 1, 2), _fixture(502, 2, 1, event=2)],
        history=[(1001, "MID", 1, 2, True), (1002, "FWD", 2, 1, False)],
    )
    # Keep a legal fixed squad and break synthetic equal-utility XI ties with
    # distinct binary fractions. No decision field or numerical tolerance is
    # excluded: the external full-registry replay also checks an actual transfer.
    players = tuple(
        player for player in _base_players(horizon=2) if player.code not in {3, 15, 25, 33}
    )
    optimizer_input = _artifact(
        tuple(
            replace(player, points=tuple(score + 2**rank / 100_000 for score in player.points))
            for rank, player in enumerate(players)
        )
    )
    optimizer_input_bytes = artifact_bytes(optimizer_input)
    rules = load_squad_rules()

    def production_outputs() -> tuple[bytes, bytes]:
        forecast = predict_prospective_points(
            con,
            as_of=AS_OF,
            season="2026-27",
            gw_from=1,
            gw_to=2,
            draws=500,
            football_environment_primary=environment,
        )
        assert len(forecast.records) == 4
        assert all(row.expected_points > 0 for row in forecast.records)
        assert all(len(row.distribution) > 1 for row in forecast.records)
        initial, _, plan, _ = _solve(optimizer_input, rules, 0.0)
        assert len(initial.members) == 15
        assert len(plan.weeks) == 2
        # Full dataclasses include every PMF, xP, bonus, team/CS environment,
        # shadow and component mode, plus every XI/captain/bench/transfer decision.
        return _bytes(asdict(forecast)), _bytes((asdict(initial), asdict(plan)))

    try:
        before = production_outputs()
        source = tmp_path / "scouting-source.duckdb"
        _write(source)
        original_source = source.read_bytes()
        captured = _load(source)
        source_input = _bytes([asdict(row) for row in captured.history])
        states = build_player_attacking_usage(captured.history, captured.players, CUTOFF)
        assert any(state.recent_usage_percentile is not None for state in states)
        destination = tmp_path / "scouting-export"
        build_usage_export(source, destination, as_of=CUTOFF, minimum_minutes=0)
        assert (destination / "player_attacking_usage.json").is_file()
        assert (destination / "player_attacking_usage.csv").is_file()
        assert source.read_bytes() == original_source
        assert _bytes([asdict(row) for row in captured.history]) == source_input
        assert artifact_bytes(optimizer_input) == optimizer_input_bytes
        assert production_outputs() == before
    finally:
        con.close()


def test_production_import_graph_cannot_reach_descriptive_usage() -> None:
    source = repo_root() / "src"
    modules = {}
    for path in (source / "fpl").rglob("*.py"):
        parts = path.relative_to(source).with_suffix("").parts
        modules[".".join(parts[:-1] if path.name == "__init__.py" else parts)] = path
    graph: dict[str, set[str]] = {}
    for module, path in modules.items():
        imports: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                parent = node.module or ""
                if node.level:
                    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
                    parent = resolve_name("." * node.level + parent, package)
                imports.add(parent)
                imports.update(f"{parent}.{alias.name}" for alias in node.names)
        # Importing a submodule also executes each parent package initializer.
        graph[module] = {
            ".".join(parts[:length])
            for imported in imports
            for parts in [imported.split(".")]
            for length in range(1, len(parts) + 1)
            if ".".join(parts[:length]) in modules
        }
    forbidden = {
        "fpl.features.player_attacking_usage",
        "fpl.publish.player_attacking_usage",
        "fpl.jobs.build_player_attacking_usage",
    }
    pending = {name for name in modules if name.startswith(("fpl.models.", "fpl.optimize."))} | {
        "fpl.jobs.prospective_points_v1",
        "fpl.jobs.pre_deadline_forecast",
    }
    visited: set[str] = set()
    while pending:
        module = pending.pop()
        assert module not in forbidden, f"production imports descriptive scouting: {module}"
        if module not in visited:
            visited.add(module)
            pending.update(graph.get(module, set()) - visited)
