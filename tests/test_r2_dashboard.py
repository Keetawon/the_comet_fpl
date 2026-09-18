from __future__ import annotations

import gzip
import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fpl.jobs import refresh_dashboard
from fpl.jobs.capture_sdp_workload import COMPETITIONS
from fpl.publish import r2_dashboard as r2
from fpl.publish import sdp_stats
from fpl.publish.export import _canonical_json_bytes
from fpl.publish.public_dashboard import PublicDashboardPackageError, _assert_public_safe
from fpl.publish.team_form import refresh_team_forms

from .test_public_dashboard import _documents, _write_generation

STAMP = datetime(2026, 8, 21, 12, tzinfo=UTC)


class S3Error(Exception):
    def __init__(self, code: str) -> None:
        super().__init__("credential-secret-must-not-appear")
        self.response = {"Error": {"Code": code}}


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.puts: list[str] = []
        self.failure: str | None = None

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        key = kwargs["Key"]
        if key not in self.objects:
            raise S3Error("NoSuchKey")
        record = self.objects[key]
        body = record["Body"]
        if self.failure == "verify" and key != "current.json":
            body = body[:-1] + bytes([body[-1] ^ 1])
        return {**record, "Body": io.BytesIO(body)}

    def put_object(self, **kwargs: Any) -> None:
        key = kwargs["Key"]
        if self.failure == "upload" and key != "current.json":
            raise S3Error("ServiceUnavailable")
        if self.failure == "pointer" and key == "current.json":
            raise TimeoutError("credential-secret-must-not-appear")
        if self.failure == "race" and key == "current.json":
            raise S3Error("PreconditionFailed")
        if kwargs.get("IfNoneMatch") == "*" and key in self.objects:
            raise S3Error("PreconditionFailed")
        if "IfMatch" in kwargs and kwargs["IfMatch"] != self.objects[key]["ETag"]:
            raise S3Error("PreconditionFailed")
        self.objects[key] = {**kwargs, "ETag": hashlib.sha256(kwargs["Body"]).hexdigest()}
        self.puts.append(key)

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "Contents": [{"Key": key} for key in self.objects if key.startswith(kwargs["Prefix"])]
        }


def seal_receipt(root: Path) -> None:
    receipt: dict[str, Any] = {
        "schema": "fpl.sdp-dashboard-generation/v1",
        "completed_at": STAMP.isoformat(),
        "public_package": {
            "manifest_content_sha256": json.loads(
                (root / "public/data/manifest.json").read_bytes()
            )["content_sha256"]
        },
    }
    for name, key, size_key in (
        ("sdp_stats", "sdp_sidecar", "byte_count"),
        ("competitive_schedule", "competitive_schedule", "bytes"),
    ):
        body = (root / f"public/sdp/{name}.json").read_bytes()
        receipt[key] = {"sha256": hashlib.sha256(body).hexdigest(), size_key: len(body)}
    (root / "receipt.json").write_bytes(_canonical_json_bytes(receipt))


@pytest.fixture
def generation(tmp_path: Path) -> Path:
    root = tmp_path / "generation"
    (root / "public/sdp").mkdir(parents=True)
    documents = _documents()
    documents["fixture_matrix.json"]["teams"] = list(
        refresh_team_forms(
            documents["fixture_matrix.json"]["teams"], documents["team_actuals.json"]["teams"], []
        )
    )
    _write_generation(root / "public/data", documents)
    (root / "receipt.json").write_text(
        json.dumps(
            {
                "schema": "fpl.sdp-dashboard-generation/v1",
                "completed_at": STAMP.isoformat(),
            }
        )
    )
    stats = {
        "schema": sdp_stats.SCHEMA,
        "json_schema_version": 8,
        "as_of": STAMP.isoformat(),
        "source_status": {
            field: (
                "UNAVAILABLE"
                if field in {"team_stats", "player_stats", "player_lineups", "fpl_enrichment"}
                else []
                if field == "notes"
                else None
            )
            for field in sdp_stats.STATUS_FIELDS
        },
        "coverage": {field: [] if field == "seasons" else 0 for field in sdp_stats.COVERAGE_FIELDS},
        "metrics": sdp_stats.metric_catalog(),
        "team_matches": [],
        "player_matches": [],
        "gameweeks": [],
    }
    schedule = {
        "schema_version": 1,
        "semantics": "current_schedule_not_prediction",
        "season": "2026-27",
        "as_of": STAMP.isoformat(),
        "verified_team_codes": [],
        "identity_sources": [],
        "competitions": [
            {
                "competition_id": number,
                "name": name,
                "status": "UNAVAILABLE",
                "issues": [],
                "sources": [],
                "matches": [],
            }
            for number, name in COMPETITIONS.items()
            if number != 8
        ],
    }
    for name, value in (("sdp_stats", stats), ("competitive_schedule", schedule)):
        (root / f"public/sdp/{name}.json").write_bytes(_canonical_json_bytes(value))
    (root / "public/sdp/publication_status.json").write_text('{"stale":"ignored"}')
    seal_receipt(root)
    return root


@pytest.fixture
def configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = r2.R2Config(
        "public-dashboard",
        "https://account.r2.cloudflarestorage.com",
        "https://data.example.com",
        tmp_path / "external-credentials",
    )
    monkeypatch.setattr(r2, "load_config", lambda _: config)
    return tmp_path / "non-secret-config.json"


def test_sanitized_generation_is_deterministic_and_hash_binds_every_companion(
    generation: Path,
    tmp_path: Path,
) -> None:
    outputs = [tmp_path / name for name in ("one", "two", "three")]
    for output in outputs:
        output.mkdir()
    encoded, inventory = r2.prepare_generation(generation, outputs[0])
    assert r2.prepare_generation(generation, outputs[1]) == (encoded, inventory)
    assert set(inventory) == r2.PUBLIC_FILES
    assert all(gzip.decompress(encoded[k]) for k in inventory)
    manifest = json.loads(gzip.decompress(encoded["data/manifest.json"]))
    status = json.loads(gzip.decompress(encoded["sdp/publication_status.json"]))
    assert status["data_manifest_sha256"] == manifest["content_sha256"]
    plans = json.loads(gzip.decompress(encoded["data/next_gw.json"]))["plans"]
    assert {p["plan_kind"] for p in plans} == {"platform_default", "platform_diagnostic"}
    assert not any(b"user_custom" in gzip.decompress(body) for body in encoded.values())
    schedule_path = generation / "public/sdp/competitive_schedule.json"
    schedule = json.loads(schedule_path.read_bytes())
    schedule["competitions"][0]["issues"].append("new_source_revision")
    schedule_path.write_bytes(_canonical_json_bytes(schedule))
    seal_receipt(generation)
    _, changed = r2.prepare_generation(generation, outputs[2])
    assert inventory["data/manifest.json"] == changed["data/manifest.json"]
    assert r2.inventory_hash(inventory) != r2.inventory_hash(changed)


@pytest.mark.parametrize("fail", [False, True])
def test_sanitization_copies_are_temporary_and_original_generation_is_untouched(
    generation: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail: bool,
) -> None:
    original = {
        p.relative_to(generation): p.read_bytes() for p in generation.rglob("*") if p.is_file()
    }
    output = tmp_path / "publication"
    output.mkdir()
    (output / "receipt.json").write_bytes(b"retained receipt")
    stages: list[Path] = []
    temporary_directory = r2.TemporaryDirectory

    def temporary(*args: Any, **kwargs: Any) -> Any:
        assert kwargs.get("dir") is None  # Use the system temporary disk, not the data disk.
        result = temporary_directory(*args, **kwargs)
        stages.append(Path(result.name))
        return result

    monkeypatch.setattr(r2, "TemporaryDirectory", temporary)
    package = r2.package_public_dashboard

    def packaged(*args: Any, **kwargs: Any) -> Any:
        result = package(*args, **kwargs)
        assert args[1].is_dir() and args[2].is_file()
        if fail:
            raise OSError("injected preparation failure after creating copies")
        return result

    monkeypatch.setattr(r2, "package_public_dashboard", packaged)
    if fail:
        with pytest.raises(OSError, match="injected preparation failure"):
            r2.prepare_generation(generation, output)
    else:
        compressed, inventory = r2.prepare_generation(generation, output)
        assert set(compressed) == set(inventory) == r2.PUBLIC_FILES
    assert len(stages) == 1 and not stages[0].exists()
    assert {
        p.relative_to(generation): p.read_bytes() for p in generation.rglob("*") if p.is_file()
    } == original
    assert {p.name: p.read_bytes() for p in output.iterdir()} == {
        "receipt.json": b"retained receipt"
    }


def test_public_sdp_correction_timestamp_is_scanned_without_changing_provenance(
    tmp_path: Path,
) -> None:
    from .test_player_attacking_usage_export import _write
    from .test_sdp_stats import _load

    db = tmp_path / "correction.duckdb"
    _write(db)
    document = _load(db)
    row = document["team_matches"][0]
    correction = {
        "correction_id": "synthetic-xgot-zero",
        "value": 0,
        "evidence_class": "owner_confirmed_display_correction",
        "provider_field": "expectedGoalsOnTarget",
        "provider_field_state": "omitted",
        "corroboration": "owner_confirmed_xgot_with_corroborated_zero_sot",
        "raw_payload_sha256": "a" * 64,
        "provider_match_id": 123,
        "subject_team_code": row["team_code"],
        "relation": "direct",
        "source_known_at": row["known_at"],
        "owner_confirmation_recorded_at": document["as_of"],
    }
    row["display_corrections"]["expected_goals_on_target"] = correction
    original = _canonical_json_bytes(document)
    with pytest.raises(PublicDashboardPackageError, match="owner_confirmation_recorded_at"):
        _assert_public_safe(document)
    r2._validate_sdp_public_safe(document)
    assert _canonical_json_bytes(document) == original
    correction["owner_email"] = "private@example.com"
    with pytest.raises(ValueError, match="correction provenance"):
        r2._validate_sdp_public_safe(document)
    correction.pop("owner_email")
    correction["correction_id"] = "manager-123456"
    with pytest.raises(PublicDashboardPackageError, match="private-looking"):
        r2._validate_sdp_public_safe(document)


def test_upload_verified_before_pointer_last_and_repeat_never_mutates_immutable_keys(
    generation: Path,
    configured: Path,
    tmp_path: Path,
) -> None:
    client = FakeS3()
    first = r2.publish_r2_dashboard(
        generation, configured, tmp_path / "first", client=client, published_at=STAMP
    )
    assert first["status"] == "COMPLETE"
    assert client.puts[-1] == "current.json"
    pointer = json.loads(client.objects["current.json"]["Body"])
    r2.validate_pointer(pointer)
    assert client.objects["current.json"]["CacheControl"] == "no-store"
    assert set(client.objects) == {
        "current.json",
        *(pointer["base_path"] + "/" + name for name in pointer["files"]),
    }
    first_objects = dict(client.objects)
    puts = list(client.puts)
    second = r2.publish_r2_dashboard(
        generation, configured, tmp_path / "second", client=client, published_at=STAMP
    )
    assert second["status"] == "COMPLETE" and second["already_current"]
    assert client.objects == first_objects and client.puts == puts
    assert (tmp_path / "second/previous-current.json").read_bytes() == client.objects[
        "current.json"
    ]["Body"]


@pytest.mark.parametrize("failure", ["upload", "verify", "pointer", "race"])
def test_failed_publication_preserves_previous_pointer_and_never_leaks_sdk_errors(
    generation: Path,
    configured: Path,
    tmp_path: Path,
    failure: str,
) -> None:
    client = FakeS3()
    assert (
        r2.publish_r2_dashboard(
            generation, configured, tmp_path / "first", client=client, published_at=STAMP
        )["status"]
        == "COMPLETE"
    )
    previous = client.objects["current.json"]["Body"]
    schedule_path = generation / "public/sdp/competitive_schedule.json"
    schedule = json.loads(schedule_path.read_bytes())
    schedule["competitions"][0]["issues"].append("changed")
    schedule_path.write_bytes(_canonical_json_bytes(schedule))
    seal_receipt(generation)
    client.failure = failure
    report = r2.publish_r2_dashboard(
        generation, configured, tmp_path / "failed", client=client, published_at=STAMP
    )
    assert report["status"] == ("UNKNOWN" if failure == "pointer" else "FAILED")
    assert client.objects["current.json"]["Body"] == previous
    assert (tmp_path / "failed/previous-current.json").read_bytes() == previous
    assert "credential-secret" not in (tmp_path / "failed/receipt.json").read_text()


@pytest.mark.parametrize(
    "corruption", ["existing_content", "extra_object", "audit_archive", "private_companion"]
)
def test_source_privacy_or_immutable_prefix_mutation_blocks_pointer_write(
    generation: Path,
    configured: Path,
    tmp_path: Path,
    corruption: str,
) -> None:
    client = FakeS3()
    first = r2.publish_r2_dashboard(
        generation, configured, tmp_path / "first", client=client, published_at=STAMP
    )
    assert first["status"] == "COMPLETE"
    pointer_body = client.objects["current.json"]["Body"]
    prefix = json.loads(pointer_body)["base_path"] + "/"
    if corruption == "existing_content":
        client.objects[prefix + "data/players.json"]["Body"] = b"altered"
    elif corruption in ("extra_object", "audit_archive"):
        name = "private.duckdb.gz" if corruption == "audit_archive" else "private.duckdb"
        client.objects[prefix + name] = {"Body": b"not public"}
    else:
        path = generation / "public/sdp/competitive_schedule.json"
        schedule = json.loads(path.read_bytes())
        schedule["competitions"][0]["issues"].append("manager-123456")
        path.write_bytes(_canonical_json_bytes(schedule))
        seal_receipt(generation)
    report = r2.publish_r2_dashboard(generation, configured, tmp_path / "rejected", client=client)
    assert report["status"] == "FAILED"
    assert client.objects["current.json"]["Body"] == pointer_body
    assert report["pointer_update_attempted"] is False


def test_config_rejects_secrets_and_unsafe_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(r2, "repo_root", lambda: tmp_path / "checkout")
    monkeypatch.setattr(r2, "_inside_git", lambda _: False)
    credentials = tmp_path / "credentials"
    credentials.write_text("[comet-r2]\n")
    config = {
        "bucket": "public-dashboard",
        "endpoint_url": "https://account.r2.cloudflarestorage.com",
        "public_base_url": "https://data.example.com",
        "credentials_file": str(credentials),
        "profile": "comet-r2",
    }
    path = tmp_path / "r2.json"
    path.write_text(json.dumps(config))
    assert r2.load_config(path).credentials_file == credentials
    for extra in (
        {"secret": "never"},
        {"endpoint_url": "https://evil.example"},
        {"public_base_url": "http://data.example.com"},
        {"endpoint_url": "https://user:password@account.r2.cloudflarestorage.com"},
        {"public_base_url": "https://data.example.com/path"},
        {"profile": "default"},
    ):
        path.write_text(json.dumps({**config, **extra}))
        with pytest.raises(ValueError, match=r"R2|invalid"):
            r2.load_config(path)


def test_sdk_is_optional_and_uses_only_the_explicit_profile_with_bounded_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    def provider(**kwargs: Any) -> Any:
        calls["provider"] = kwargs
        return SimpleNamespace(
            load=lambda: SimpleNamespace(access_key="key", secret_key="secret", token=None)
        )

    def sdk_config(**kwargs: Any) -> dict[str, Any]:
        calls["config"] = kwargs
        return kwargs

    def session(**kwargs: Any) -> Any:
        calls["session"] = kwargs
        return SimpleNamespace(client=lambda *a, **kw: calls.setdefault("client", kw))

    modules = {
        "boto3": SimpleNamespace(Session=session),
        "botocore.config": SimpleNamespace(Config=sdk_config),
        "botocore.credentials": SimpleNamespace(SharedCredentialProvider=provider),
    }
    monkeypatch.setattr(r2, "import_module", lambda name: modules[name])
    config = r2.R2Config(
        "bucket",
        "https://account.r2.cloudflarestorage.com",
        "https://data.example.com",
        tmp_path / "credentials",
    )
    r2.s3_client(config)
    assert calls["provider"] == {
        "creds_filename": str(config.credentials_file),
        "profile_name": "comet-r2",
    }
    assert calls["config"]["connect_timeout"] == 10
    assert calls["config"]["read_timeout"] == 60
    assert calls["config"]["retries"] == {"mode": "standard", "total_max_attempts": 3}
    assert calls["client"]["endpoint_url"] == config.endpoint_url


def test_substituting_a_valid_companion_fails_before_any_remote_write(
    generation: Path,
    configured: Path,
    tmp_path: Path,
) -> None:
    path = generation / "public/sdp/competitive_schedule.json"
    schedule = json.loads(path.read_bytes())
    schedule["competitions"][0]["issues"].append("different_valid_generation")
    path.write_bytes(_canonical_json_bytes(schedule))
    client = FakeS3()
    report = r2.publish_r2_dashboard(generation, configured, tmp_path / "failed", client=client)
    assert report["status"] == "FAILED"
    assert client.puts == []


@pytest.mark.parametrize("worktree", [False, True])
def test_git_ancestor_detection_includes_other_checkouts(tmp_path: Path, worktree: bool) -> None:
    checkout = tmp_path / "sibling-checkout"
    checkout.mkdir()
    if worktree:
        (checkout / ".git").write_text("gitdir: elsewhere")
    else:
        (checkout / ".git").mkdir()
    assert r2._inside_git(checkout / "nested/credentials")


@pytest.mark.parametrize("target", ["config", "credentials"])
def test_config_rejects_reparse_ancestors_before_reading_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    config_path = tmp_path / "r2.json"
    credentials = tmp_path / "credentials"
    credentials.write_text("unread-secret")
    config_path.write_text(
        json.dumps(
            {
                "bucket": "public-dashboard",
                "endpoint_url": "https://account.r2.cloudflarestorage.com",
                "public_base_url": "https://data.example.com",
                "profile": "comet-r2",
                "credentials_file": str(credentials),
            }
        )
    )
    monkeypatch.setattr(r2, "_inside_git", lambda _: False)
    monkeypatch.setattr(r2, "repo_root", lambda: tmp_path / "checkout")
    flagged = config_path if target == "config" else credentials
    monkeypatch.setattr(r2, "_has_reparse_ancestor", lambda path: path == flagged)
    with pytest.raises(ValueError, match="reparse"):
        r2.load_config(config_path)


def test_reparse_check_inspects_unresolved_ancestors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    junction = tmp_path / "junction"
    original = Path.lstat

    def attributes(path: Path) -> Any:
        if path == junction:
            return SimpleNamespace(st_file_attributes=r2.stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return original(path)

    monkeypatch.setattr(Path, "lstat", attributes)
    assert r2._has_reparse_ancestor(junction / "credentials")


@pytest.mark.parametrize("raises", [False, True])
def test_refresh_keeps_local_success_and_lock_until_optional_publication_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raises: bool,
) -> None:
    db = tmp_path / "operational.duckdb"
    import duckdb

    with duckdb.connect(str(db)) as con:
        con.execute("CREATE TABLE raw_test(id INTEGER)")
    original = db.read_bytes()
    runs = tmp_path / "runs"
    monkeypatch.setattr(refresh_dashboard, "complete", lambda *a, **kw: {"preview_updated": True})

    def publish(*args: Any, **kwargs: Any) -> dict[str, str]:
        assert (runs / ".dashboard-refresh.lock").is_file()
        if raises:
            raise RuntimeError("credential-secret-must-not-appear")
        return {"status": "FAILED"}

    monkeypatch.setattr(r2, "publish_r2_dashboard", publish)
    result = refresh_dashboard.main(
        [
            "--db",
            str(db),
            "--runs",
            str(runs),
            "--forecast-dir",
            str(tmp_path),
            "--preview-public",
            str(tmp_path),
            "--plan-store",
            str(tmp_path),
            "--skip-capture",
            "--r2-config",
            str(tmp_path / "config.json"),
        ]
    )
    assert result == 1
    receipt = next(runs.glob("dashboard-*/receipt.json")).read_text()
    assert "credential-secret" not in receipt
    report = json.loads(receipt)
    assert report["status"] == "COMPLETE" and report["preview_updated"]
    assert report["public_publication"]["status"] == "FAILED"
    assert not (runs / ".dashboard-refresh.lock").exists()
    assert db.read_bytes() == original
