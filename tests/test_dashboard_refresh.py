from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from fpl.publish import dashboard_refresh as refresh


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.mark.parametrize("provisional", [False, True])
def test_current_observations_cannot_be_replaced_by_a_freshly_dated_old_base(
    tmp_path: Path, provisional: bool
) -> None:
    sidecar: dict[str, Any] = {"gameweeks": [{"season": "2026-27"}]}
    for scope, plural, identity in (("team", "teams", "team_code"), ("player", "players", "code")):
        sidecar[f"{scope}_matches"] = [
            {"season": "2026-27", "fixture": 30, identity: 3, "fpl": {"goals": 0}}
        ]
        for suffix in ("actuals", "provisional_actuals"):
            selected = suffix == ("provisional_actuals" if provisional else "actuals")
            rows = [{"season": "2026-27", identity: 3, "actuals": [{"fixture": 30}]}]
            write(tmp_path / f"{scope}_{suffix}.json", {plural: rows if selected else []})
    assert (
        refresh.check_observed_freshness(tmp_path, sidecar)["player"]["matched_current_rows"] == 1
    )
    # A new manifest timestamp is not a freshness witness for missing GW3 data.
    for suffix in ("actuals", "provisional_actuals"):
        write(tmp_path / f"player_{suffix}.json", {"players": []})
    with pytest.raises(ValueError, match="stale player actuals"):
        refresh.check_observed_freshness(tmp_path, sidecar)


def test_only_existing_plan_blocks_are_carried_into_the_fresh_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fresh, old, output = (tmp_path / name for name in ("fresh", "old", "output"))
    files = {"player_actuals.json": {}, "team_actuals.json": {}}
    for name, key in (
        ("next_gw.json", "plans"),
        ("optimizer_audit.json", "plans"),
        ("summary.json", "optimizer_plans"),
    ):
        files[name] = {}
        write(old / name, {key: [{"forecast_run_id": "frozen", "as_of": "original"}]})
        write(
            fresh / name,
            {
                key: [],
                "fresh_context": "GW3",
                "component_modes": {
                    "football_environment.provenance": '{"pmf":[0.1,0.9]}',
                    "player_history.provenance": '{"live_captures":["private-source"]}',
                    "player_history.contract": "prospective_archive_live_player_history/v1",
                },
            },
        )
    for name in ("player_actuals.json", "team_actuals.json"):
        write(fresh / name, {"gw": 3})
        write(old / name, {"gw": 2})
    manifest = {
        "runs": [{"run_id": "frozen", "as_of": "original"}],
        "files": files,
        "content_sha256": "h",
        "generated_at": "now",
    }
    monkeypatch.setattr(
        refresh, "validate_dashboard_json", lambda _: json.loads(json.dumps(manifest))
    )
    monkeypatch.setattr(refresh, "_manifest_content_sha256", lambda _: "hash")
    monkeypatch.setattr(refresh, "_file_row_count", lambda *a: 1)
    before = {p.name: p.read_bytes() for p in old.iterdir()}
    report = refresh.retain_existing_plans(fresh, old, output)
    assert report["forecasts_regenerated"] is False
    for name in ("player_actuals.json", "team_actuals.json"):
        assert (output / name).read_bytes() == (fresh / name).read_bytes()
    assert json.loads((output / "summary.json").read_bytes())["fresh_context"] == "GW3"
    modes = json.loads((output / "summary.json").read_bytes())["component_modes"]
    assert modes == {
        "football_environment.provenance_sha256": hashlib.sha256(b'{"pmf":[0.1,0.9]}').hexdigest(),
        "player_history.provenance_sha256": hashlib.sha256(
            b'{"live_captures":["private-source"]}'
        ).hexdigest(),
        "player_history.contract": "prospective_archive_live_player_history/v1",
    }
    assert (
        '"pmf"'
        in json.loads((fresh / "summary.json").read_bytes())["component_modes"][
            "football_environment.provenance"
        ]
    )
    assert {p.name: p.read_bytes() for p in old.iterdir()} == before
    assert "private-source" not in (output / "summary.json").read_text()
    assert "private-source" in (fresh / "summary.json").read_text()
    write(old / "next_gw.json", {"plans": [{"forecast_run_id": "different"}]})
    with pytest.raises(ValueError, match="exact forecast vintage"):
        refresh.retain_existing_plans(fresh, old, tmp_path / "refused")
