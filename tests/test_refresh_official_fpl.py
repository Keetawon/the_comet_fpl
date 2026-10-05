"""Network-free coverage and failure atomicity for the independent reporting feed."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fpl.ingest.fpl_api import ApiResponseError
from fpl.jobs.refresh_official_fpl import CURRENT_KEY, build, encoded, publish

from .test_r2_dashboard import FakeS3

STAMP = datetime(2026, 10, 5, 10, tzinfo=UTC)


def official_payloads() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Synthetic complete-size calendar; no claimed real football values."""
    bootstrap = {
        "teams": [
            {"id": i, "code": i + 100, "name": f"Club {i}", "short_name": f"C{i}"}
            for i in range(1, 21)
        ],
        "events": [
            {"id": i, "name": f"GW{i}", "deadline_time": "2026-08-21T17:30:00Z", "is_next": i == 6}
            for i in range(1, 39)
        ],
        "elements": [
            {
                "id": i,
                "code": i + 1000,
                "web_name": f"Player {i}",
                "element_type": 3,
                "team": 1,
                "status": "a",
                "now_cost": 50,
            }
            for i in range(1, 401)
        ],
    }
    fixtures = [
        {
            "id": i + 1,
            "team_h": home,
            "team_a": away,
            "kickoff_time": "2026-08-21T19:00:00Z",
            "team_h_difficulty": 2,
            "team_a_difficulty": None,
        }
        for i, (home, away) in enumerate(
            (h, a) for h in range(1, 21) for a in range(1, 21) if h != a
        )
    ]
    return bootstrap, fixtures


def test_reporting_preserves_nulls_and_replay_inputs_and_advances_only_after_readback() -> None:
    bootstrap, fixtures = official_payloads()
    bootstrap["elements"][0].update(status="i", chance_of_playing_next_round=0, news="Knee injury")
    doc = build(bootstrap, fixtures, captured_at=STAMP)
    assert doc["season"] == "2026-27"
    assert len(doc["players"]) == 400 and len(doc["fixtures"]) == 760
    assert doc["fixtures"][1]["official_fdr"] is None
    assert doc["players"][0]["current_availability"]["chance_of_playing_next_round"] == 0
    client = FakeS3()
    raw = {"bootstrap-static": bootstrap, "fixtures": fixtures}
    publish(client, "bucket", doc, raw)
    assert client.puts[-1] == CURRENT_KEY
    original = client.objects[CURRENT_KEY]["Body"]
    assert json.loads(original) == doc
    later = build(bootstrap, fixtures, captured_at=STAMP + timedelta(hours=1))
    read = client.get_object

    def corrupt(**kwargs: Any) -> dict[str, Any]:
        client.failure = "verify" if kwargs["Key"] != CURRENT_KEY else None
        return read(**kwargs)

    client.get_object = corrupt  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="readback"):
        publish(client, "bucket", later, raw)
    assert client.objects[CURRENT_KEY]["Body"] == original
    client.get_object = read  # type: ignore[method-assign]
    client.failure = None
    with pytest.raises(ValueError, match="rollback"):
        publish(client, "bucket", doc, raw)
    assert client.objects[CURRENT_KEY]["Body"] == original


@pytest.mark.parametrize(
    "defect", ["season", "club", "player", "fixture", "fdr", "chance", "partial"]
)
def test_reporting_rejects_bad_identity_coverage_and_values(defect: str) -> None:
    bootstrap, fixtures = deepcopy(official_payloads())
    if defect == "season":
        fixtures[0]["kickoff_time"] = "2025-08-21T19:00:00Z"
    elif defect == "club":
        bootstrap["teams"][1]["code"] = bootstrap["teams"][0]["code"]
    elif defect == "player":
        bootstrap["elements"][1]["code"] = bootstrap["elements"][0]["code"]
    elif defect == "fixture":
        fixtures[1]["id"] = fixtures[0]["id"]
    elif defect == "fdr":
        fixtures[0]["team_h_difficulty"] = 6
    elif defect == "chance":
        bootstrap["elements"][0]["chance_of_playing_next_round"] = 101
    else:
        fixtures.pop()
    with pytest.raises((ValueError, ApiResponseError)):
        build(bootstrap, fixtures, captured_at=STAMP)


def test_concurrent_publication_cannot_overwrite_newer_capture() -> None:
    bootstrap, fixtures = official_payloads()
    raw = {"bootstrap-static": bootstrap, "fixtures": fixtures}
    client = FakeS3()
    publish(client, "bucket", build(bootstrap, fixtures, captured_at=STAMP), raw)
    put = client.put_object
    newer = encoded(build(bootstrap, fixtures, captured_at=STAMP + timedelta(hours=2)))

    def race(**kwargs: Any) -> None:
        if kwargs["Key"] == CURRENT_KEY:
            client.objects[CURRENT_KEY].update(Body=newer, ETag="another-writer")
        put(**kwargs)

    client.put_object = race  # type: ignore[method-assign]
    with pytest.raises(Exception, match="credential-secret"):
        publish(
            client,
            "bucket",
            build(bootstrap, fixtures, captured_at=STAMP + timedelta(hours=1)),
            raw,
        )
    assert client.objects[CURRENT_KEY]["Body"] == newer
