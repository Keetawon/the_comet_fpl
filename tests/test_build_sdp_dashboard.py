from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest

from fpl.jobs import build_sdp_dashboard as job
from fpl.jobs.build_sdp_dashboard import install_preview, retain_validated_generation


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
    destination = tmp_path / "dashboard" / "public"
    install_preview(generation, destination)
    install_preview(generation, destination)
    assert sorted(
        p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()
    ) == [
        "data/manifest.json",
        "sdp/sdp_stats.json",
    ]
    assert (generation / "before.duckdb").read_bytes() == b"private database"


@pytest.mark.parametrize("retained", [False, True])
def test_existing_base_is_explicit_and_never_relabels_forecast_vintage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retained: bool
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
    monkeypatch.setattr(job, "check_observed_freshness", lambda *a: {})
    monkeypatch.setattr(job, "retain_existing_plans", lambda *a: {"observations_refreshed": True})
    report = job.build(db, output, base_dashboard=old_base if retained else None)
    assert calls == [
        (
            "package",
            output / "dashboard-with-retained-plans" if retained else output / "dashboard-retained",
        ),
        ("sidecar", db),
    ]
    assert report["base_dashboard"]["generated_at"] == "new"
    assert report["base_dashboard"]["mode"] == (
        "refreshed_observations_with_retained_plans"
        if retained
        else "refreshed_operational_generation"
    )
    assert report["forecast_regenerated"] is False
    assert old_evidence.read_bytes() == b"original forecast"
    assert db.read_bytes() == b"unchanged database"
