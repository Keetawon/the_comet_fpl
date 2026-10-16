"""Compatibility between existing public generations and Claude's additive pipelines."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from fpl.jobs import republish_provisional as job
from fpl.publish import provisional_republish as rp
from fpl.publish import r2_dashboard as r2
from fpl.publish.dashboard_scope import PUBLIC_PAYLOAD_LIMITS
from fpl.publish.rest_summary import PlayerObservation, validate_rest_summary

from .test_provisional_republish import BASE, capture_package, published, serve  # noqa: F401
from .test_r2_dashboard import STAMP, FakeS3, configured, generation  # noqa: F401
from .test_rest_summary import GAKPO, LIVERPOOL, cup, summarise


def legacy_rest() -> dict[str, Any]:
    value = summarise(
        [cup(LIVERPOOL, observations=(PlayerObservation(GAKPO, True, True, 90),))]
    ).model_dump(mode="json")
    for row in value["players"]:
        row.pop("midweek_load")
        row.pop("midweek_fixtures")
    return value


def test_legacy_rest_sidecar_retains_original_evidence_without_inventing_load() -> None:
    value = legacy_rest()
    before = json.dumps(value, sort_keys=True)
    validated = validate_rest_summary(value)
    assert validated.counts["midweek_played"] == 1
    assert all("midweek_load" not in row.model_fields_set for row in validated.players)
    assert json.dumps(value, sort_keys=True) == before


@pytest.mark.parametrize(("field", "value"), [("midweek_load", "heavy"), ("midweek_fixtures", 1)])
def test_partial_additive_load_fields_fail_closed(field: str, value: Any) -> None:
    document = legacy_rest()
    document["players"][0][field] = value
    with pytest.raises(ValueError, match="supplied together"):
        validate_rest_summary(document)


def test_mobile_budget_rejects_base_before_any_payload_download(published: Path) -> None:  # noqa: F811
    read = serve(published)
    pointer = json.loads(read(f"{BASE}/current.json"))
    pointer["files"]["data/players.json"]["size_bytes"] = PUBLIC_PAYLOAD_LIMITS["players.json"] + 1
    digest = r2.inventory_hash(pointer["files"])
    pointer.update(generation_sha256=digest, base_path=f"generations/{digest}")
    requests: list[str] = []

    def oversized(url: str) -> bytes:
        requests.append(url)
        assert url == f"{BASE}/current.json", "must reject before downloading any payload"
        return json.dumps(pointer).encode()

    with pytest.raises(rp.ProvisionalRepublishError, match=r"players\.json exceeds its bound"):
        rp.fetch_published_generation(BASE, read=oversized)
    assert requests == [f"{BASE}/current.json"]


def test_publisher_preserves_restated_compact_bytes_and_repeat_is_noop(
    published: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    captured = capture_package(tmp_path / "capture")
    base = rp.fetch_published_generation(BASE, read=serve(published))
    restatement = rp.build_restatement(captured, base, scratch=tmp_path / "first-capture")
    first = tmp_path / "first"
    rp.restate_generation(base, restatement, first)
    encoded, _ = r2.prepare_generation(first, tmp_path / "prepared")
    for relative, body in encoded.items():
        if relative.startswith("data/"):
            assert gzip.decompress(body) == (first / "public" / relative).read_bytes(), relative
    next_base = rp.fetch_published_generation(BASE, read=serve(first))
    repeated = rp.build_restatement(captured, next_base, scratch=tmp_path / "next-capture")
    receipt = rp.restate_generation(next_base, repeated, tmp_path / "next")
    assert receipt["restated_files"] == []


@pytest.mark.parametrize("exists", [True, False])
def test_changed_or_missing_base_blocks_publication_before_remote_writes(
    generation: Path,  # noqa: F811
    configured: Path,  # noqa: F811
    tmp_path: Path,
    exists: bool,
) -> None:
    client = FakeS3()
    if exists:
        assert (
            r2.publish_r2_dashboard(
                generation, configured, tmp_path / "initial", client=client, published_at=STAMP
            )["status"]
            == "COMPLETE"
        )
    before, puts = dict(client.objects), list(client.puts)
    report = r2.publish_r2_dashboard(
        generation,
        configured,
        tmp_path / "rejected",
        client=client,
        published_at=STAMP,
        expected_base_generation="0" * 64,
    )
    assert report["status"] == "FAILED" and report["pointer_update_attempted"] is False
    assert client.objects == before and client.puts == puts


def test_republish_job_binds_publication_to_the_generation_it_restated(
    published: Path,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = rp.fetch_published_generation(BASE, read=serve(published))
    capture = capture_package(tmp_path / "capture")
    monkeypatch.setattr(job, "fetch_published_generation", lambda *a, **kw: base)
    calls: list[dict[str, Any]] = []

    def publish(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"status": "COMPLETE"}

    monkeypatch.setattr(job, "publish_r2_dashboard", publish)
    assert (
        job.main(
            [
                "--out",
                str(tmp_path / "job"),
                "--capture",
                str(capture),
                "--r2-config",
                str(tmp_path / "unused-config.json"),
            ]
        )
        == 0
    )
    assert len(calls) == 1 and calls[0]["expected_base_generation"] == base.generation_sha256
