from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fpl.jobs import build_sdp_dashboard as job
from fpl.jobs.build_sdp_dashboard import install_preview, retain_validated_generation
from fpl.publish.public_dashboard import PublicDashboardPackageError
from fpl.publish.rest_summary import RosterPlayer, build_rest_summary, validate_rest_summary


def test_windows_copy_requires_the_validated_publication_hook(tmp_path: Path) -> None:
    endpoint, retained = tmp_path / "endpoint", tmp_path / "retained"

    def publisher(source: Path, target: Path, **kwargs: Any) -> None:
        stage = target.parent / f".{target.name}.test.tmp"
        stage.mkdir()
        (stage / "manifest.json").write_text('{"validated":true}')
        kwargs["before_publish"]()
        error = OSError("symlink privilege unavailable")
        error.winerror = 1314  # type: ignore[attr-defined]
        raise error

    assert retain_validated_generation(publisher, tmp_path, endpoint, retained) is False
    assert (retained / "manifest.json").read_text() == '{"validated":true}'


@pytest.mark.parametrize("winerror", [5, 1314])
def test_export_failure_is_not_silently_converted_to_a_preview(
    tmp_path: Path, winerror: int
) -> None:
    def publisher(source: Path, target: Path, **kwargs: Any) -> None:
        error = OSError("failed before validation")
        error.winerror = winerror  # type: ignore[attr-defined]
        raise error

    with pytest.raises(OSError, match="before validation"):
        retain_validated_generation(
            publisher, tmp_path, tmp_path / "endpoint", tmp_path / "retained"
        )


def test_preview_copies_only_intended_public_exports(tmp_path: Path) -> None:
    generation = tmp_path / "generation"
    (generation / "public" / "data").mkdir(parents=True)
    (generation / "public" / "sdp").mkdir()
    (generation / "before.duckdb").write_bytes(b"private database")
    (generation / "receipt.json").write_text('{"private_path":"retained"}')
    (generation / "public" / "data" / "manifest.json").write_text('{"public":true}')
    (generation / "public" / "sdp" / "sdp_stats.json").write_text('{"observed":true}')
    (generation / "public" / "sdp" / "competitive_schedule.json").write_text('{"schedule":true}')
    (generation / "public" / "sdp" / "rest_summary.json").write_text('{"rest":true}')
    (generation / "public" / "sdp" / "news_feed.json").write_text('{"news":true}')
    destination = tmp_path / "dashboard" / "public"
    install_preview(generation, destination)
    install_preview(generation, destination)
    assert sorted(
        p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()
    ) == [
        "data/manifest.json",
        "sdp/competitive_schedule.json",
        "sdp/news_feed.json",
        "sdp/rest_summary.json",
        "sdp/sdp_stats.json",
    ]
    assert (generation / "before.duckdb").read_bytes() == b"private database"
    (generation / "public" / "sdp" / "news_feed.json").unlink()
    install_preview(generation, destination)
    assert not (destination / "sdp" / "news_feed.json").exists()


@pytest.mark.parametrize("retained", [False, True])
@pytest.mark.parametrize("with_news", [False, True])
def test_existing_base_is_explicit_and_never_relabels_forecast_vintage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retained: bool, with_news: bool
) -> None:
    db = tmp_path / "operational.duckdb"
    db.write_bytes(b"unchanged database")
    output = tmp_path / "generation"
    old_base = tmp_path / "existing-base"
    old_base.mkdir()
    old_evidence = old_base / "original.json"
    old_evidence.write_bytes(b"original forecast")
    calls: list[tuple[str, Path]] = []
    monkeypatch.setattr(job, "connect", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(job, "retain_validated_generation", lambda *a: False)
    monkeypatch.setattr(job, "validate_bi_export", lambda *a: None)
    monkeypatch.setattr(
        job,
        "validate_dashboard_json",
        lambda p: {"generated_at": "old" if p == old_base else "new", "content_sha256": "h"},
    )

    class Package:
        def metadata(self) -> dict[str, str]:
            return {"validated": "existing sanitizer"}

    def package(source: Path, *args: Any) -> Package:
        calls.append(("package", source))
        return Package()

    def sidecar(source: Path, *args: Any, **kwargs: Any) -> dict[str, str]:
        calls.append(("sidecar", source))
        target = args[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}")
        return {"source": "current operational observations"}

    monkeypatch.setattr(job, "package_public_dashboard", package)
    monkeypatch.setattr(job, "export_sdp_stats", sidecar)
    monkeypatch.setattr(job, "export_competitive_schedule", sidecar)
    monkeypatch.setattr(job, "export_rest_summary", sidecar)
    monkeypatch.setattr(job, "publish_news_feed", sidecar)
    monkeypatch.setattr(job, "check_observed_freshness", lambda *a: {})
    monkeypatch.setattr(job, "publication_status", lambda *a: {})
    monkeypatch.setattr(job, "retain_existing_plans", lambda *a: {"observations_refreshed": True})

    def availability(*args: Any, **kwargs: Any) -> dict[str, int]:
        calls.append(("availability", args[1]))
        return {"matched_player_rows": 1}

    monkeypatch.setattr(job, "refresh_current_availability", availability)
    news_store = tmp_path / "separate-news-store" if with_news else None
    report = job.build(
        db, output, base_dashboard=old_base if retained else None, news_store=news_store
    )
    assert calls == [
        (
            "availability",
            output / "dashboard-with-retained-plans" if retained else output / "dashboard-retained",
        ),
        ("package", output / "dashboard-with-current-availability"),
        ("sidecar", db),
        ("sidecar", db),
        ("sidecar", db),
    ] + ([("sidecar", news_store)] if with_news else [])
    assert report["base_dashboard"]["generated_at"] == "new"
    assert report["base_dashboard"]["mode"] == (
        "refreshed_observations_with_retained_plans"
        if retained
        else "refreshed_operational_generation"
    )
    assert report["forecast_regenerated"] is False
    assert report["current_availability"] == {"matched_player_rows": 1}
    assert report["rest_summary"] == {"source": "current operational observations"}
    assert ("news_feed" in report) is with_news
    assert old_evidence.read_bytes() == b"original forecast"
    assert db.read_bytes() == b"unchanged database"


def test_news_export_is_read_only_write_once_and_hash_bound(tmp_path: Path) -> None:
    stamp = datetime(2026, 9, 18, 10, tzinfo=UTC)
    missing_store = tmp_path / "not-configured"
    first, second = tmp_path / "first/news_feed.json", tmp_path / "second/news_feed.json"
    receipt = job.publish_news_feed(missing_store, first, as_of=stamp)
    assert job.publish_news_feed(missing_store, second, as_of=stamp) == receipt
    assert first.read_bytes() == second.read_bytes()
    job.validate_news_feed(json.loads(first.read_bytes()))
    assert receipt == {
        "sha256": hashlib.sha256(first.read_bytes()).hexdigest(),
        "bytes": len(first.read_bytes()),
    }
    assert not missing_store.exists()
    with pytest.raises(FileExistsError):
        job.publish_news_feed(missing_store, first, as_of=stamp)


def test_news_export_rejects_private_document_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(job, "export_news_feed", lambda *a, **kw: {"manager_id": 123})
    target = tmp_path / "public/sdp/news_feed.json"
    with pytest.raises((ValueError, PublicDashboardPackageError)):
        job.publish_news_feed(tmp_path / "store", target, as_of=datetime.now(UTC))
    assert not target.exists()


def test_public_rest_export_is_whole_roster_write_once_and_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stamp = datetime(2026, 9, 18, 10, tzinfo=UTC)
    document = build_rest_summary(
        season="2026-27",
        as_of=stamp,
        roster=[
            RosterPlayer(101, "Player One", 3, "Club One"),
            RosterPlayer(102, "Player Two", 4, "Club Two"),
        ],
        fixtures=[],
        next_fixtures={},
    )
    db = tmp_path / "operational.duckdb"
    db.write_bytes(b"immutable operational source")
    calls: list[dict[str, Any]] = []

    def build(source: Path, **kwargs: Any) -> Any:
        assert source == db
        calls.append(kwargs)
        return document

    monkeypatch.setattr(job, "build_rest_summary", build)
    first, replay = tmp_path / "first/rest_summary.json", tmp_path / "replay/rest_summary.json"
    receipt = job.export_rest_summary(db, first, as_of=stamp)
    assert job.export_rest_summary(db, replay, as_of=stamp) == receipt
    assert first.read_bytes() == replay.read_bytes()
    assert calls == [{"as_of": stamp}, {"as_of": stamp}]  # No private squad/code selector.
    value = json.loads(first.read_bytes())
    assert {row["code"] for row in value["players"]} == {101, 102}
    assert validate_rest_summary(value).counts["unknown"] == 2
    assert receipt["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    assert receipt["bytes"] == len(first.read_bytes())
    assert receipt["counts"] == value["counts"]
    with pytest.raises(FileExistsError):
        job.export_rest_summary(db, first, as_of=stamp)
    assert first.read_bytes() == replay.read_bytes()
    assert db.read_bytes() == b"immutable operational source"


@pytest.mark.parametrize("invalid", ["counts", "privacy"])
def test_public_rest_export_rejects_invalid_or_private_document_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    stamp = datetime(2026, 9, 18, 10, tzinfo=UTC)
    document = build_rest_summary(
        season="2026-27", as_of=stamp, roster=[], fixtures=[], next_fixtures={}
    )
    if invalid == "counts":
        document = document.model_copy(update={"counts": {**document.counts, "players": 1}})
    else:
        document = document.model_copy(update={"source_issues": ["manager-123456"]})
    monkeypatch.setattr(job, "build_rest_summary", lambda *args, **kwargs: document)
    target = tmp_path / "public/rest_summary.json"
    with pytest.raises((ValueError, PublicDashboardPackageError)):
        job.export_rest_summary(tmp_path / "source.duckdb", target, as_of=stamp)
    assert not target.exists()
