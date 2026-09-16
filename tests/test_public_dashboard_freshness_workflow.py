"""Execute the hosted freshness adapter against synthetic, pinned inputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from fpl.publish import dashboard_refresh


@pytest.mark.parametrize("has_companion", [False, True])
def test_hosted_freshness_uses_existing_publisher_and_pinned_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, has_companion: bool
) -> None:
    workflow = yaml.safe_load(
        (Path(__file__).parents[1] / ".github/workflows/deploy-dashboard.yml").read_bytes()
    )
    step = next(
        s
        for s in workflow["jobs"]["build"]["steps"]
        if s.get("name") == "Bind public freshness to the pinned generation"
    )
    script = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "dashboard/public/sdp"
    folder.mkdir(parents=True)
    source = folder / "sdp_stats.json"
    if has_companion:
        source.write_text('{"gameweeks": []}', encoding="utf-8")
    calls: list[tuple[Path, dict[str, Any]]] = []

    def status(generation: Path, sidecar: dict[str, Any]) -> dict[str, Any]:
        calls.append((generation, sidecar))
        return {"data_manifest_sha256": "public-hash", "latest_forecast": None}

    monkeypatch.setattr(dashboard_refresh, "publication_status", status)
    exec(compile(script, "deploy-dashboard.yml", "exec"), {})
    target = folder / "publication_status.json"
    if has_companion:
        assert calls == [(Path("dashboard/public/data"), {"gameweeks": []})]
        assert json.loads(target.read_bytes())["data_manifest_sha256"] == "public-hash"
        before = target.read_bytes()
        exec(compile(script, "deploy-dashboard.yml", "exec"), {})
        assert target.read_bytes() == before
        assert source.read_text(encoding="utf-8") == '{"gameweeks": []}'
    else:
        assert calls == []
        assert not target.exists()
