"""Synthetic comparator-cache checks; no historical model scoring."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest
import yaml

from fpl.jobs.competitive_participation_pilot import ParticipationError
from fpl.models.price_starter_prior import apply_price_starter_prior
from fpl.storage.db import initialise
from fpl.types import Position
from fpl.validate import current_minutes_control_cache as cache
from fpl.validate.current_minutes_control_cache import build_fold, run, target_roster

CUTOFF = datetime(2025, 9, 5, 19, tzinfo=UTC)
DIGEST = "a" * 64


@pytest.fixture
def source() -> Iterator[duckdb.DuckDBPyConnection]:
    con = initialise(":memory:")
    con.execute(
        "INSERT INTO mart_dim_team (season,team_id,team_code,team_name,short_name) "
        "VALUES ('2025-26',1,3,'Club','CLB')"
    )
    for index in range(3):
        _row(con, index + 1, index + 1, 1, CUTOFF - timedelta(days=21 - 7 * index), 90, 60)
    _row(con, 4, 4, 1, CUTOFF, 0, 60)
    _row(con, 4, 4, 2, CUTOFF, 90, 55)
    try:
        yield con
    finally:
        con.close()


def _row(
    con: duckdb.DuckDBPyConnection,
    fixture: int,
    gw: int,
    code: int,
    kickoff: datetime,
    minutes: int,
    value: int | None,
) -> None:
    con.execute(
        """INSERT INTO mart_fact_player_fixture
        (season,gw,fixture,kickoff_time,code,position,team_id,opponent_team_id,was_home,minutes,value)
        VALUES ('2025-26',?,?,?,?, 'MID',1,2,true,?,?)""",
        [gw, fixture, kickoff, code, minutes, value],
    )


def _fold(con: duckdb.DuckDBPyConnection) -> dict[str, object]:
    return build_fold(con, season="2025-26", gw=4, as_of=CUTOFF, database_hash=DIGEST)


def test_hand_computable_established_and_cold_routes(source: duckdb.DuckDBPyConnection) -> None:
    result = _fold(source)
    established, cold = result["rows"]
    assert established["minutes_distribution"] == pytest.approx([0.875 / 6.5] * 3 + [3.875 / 6.5])
    assert not established["price_proxy_dependent"]
    assert established["selector_provenance"]["archive_price_lineage"] == []
    expected = apply_price_starter_prior(
        tuple(cold["raw_v3_distribution"]), price=55, position=Position.MID
    )
    assert cold["minutes_distribution"] == list(expected)
    assert cold["price_proxy_dependent"]
    assert (
        cold["selector_provenance"]["archive_price_lineage"][0]["rows"][0]["source_known_at"]
        is None
    )


def test_target_outcomes_never_change_control(source: duckdb.DuckDBPyConnection) -> None:
    before = _fold(source)
    source.execute(
        "UPDATE mart_fact_player_fixture SET minutes=37, starts=1, goals_scored=9 WHERE gw=4"
    )
    assert _fold(source) == before


def test_future_truncation_equivalence(source: duckdb.DuckDBPyConnection) -> None:
    before = _fold(source)
    _row(source, 5, 5, 1, CUTOFF + timedelta(days=7), 0, 120)
    _row(source, 5, 5, 2, CUTOFF + timedelta(days=7), 90, 120)
    assert _fold(source) == before


def test_established_price_not_consulted_without_required_witness(
    source: duckdb.DuckDBPyConnection,
) -> None:
    before = _fold(source)
    source.execute("UPDATE mart_fact_player_fixture SET value=NULL WHERE gw=4 AND code=1")
    assert _fold(source) == before


def test_missing_cold_price_fails_not_imputed(source: duckdb.DuckDBPyConnection) -> None:
    source.execute("UPDATE mart_fact_player_fixture SET value=NULL WHERE gw=4 AND code=2")
    with pytest.raises(ValueError, match="archive_price_unmeasured"):
        _fold(source)


def test_all_double_gameweek_legs_share_precutoff_history(
    source: duckdb.DuckDBPyConnection,
) -> None:
    _row(source, 40, 4, 1, CUTOFF + timedelta(days=4), 0, 60)
    _row(source, 40, 4, 2, CUTOFF + timedelta(days=4), 0, 55)
    result = _fold(source)
    a, b, c, d = result["rows"]
    assert a["minutes_distribution"] == c["minutes_distribution"]
    assert b["minutes_distribution"] == d["minutes_distribution"]
    assert result["training_rows"] == 3
    assert len(b["selector_provenance"]["archive_price_lineage"][0]["rows"]) == 2


def test_double_gameweek_cold_price_disagreement_fails(source: duckdb.DuckDBPyConnection) -> None:
    _row(source, 40, 4, 2, CUTOFF + timedelta(days=4), 0, 56)
    with pytest.raises(ValueError, match="same_gw_revision_ambiguity"):
        _fold(source)


def test_same_gw_club_ambiguity_fails(source: duckdb.DuckDBPyConnection) -> None:
    source.execute(
        "INSERT INTO mart_dim_team (season,team_id,team_code,team_name,short_name) "
        "VALUES ('2025-26',2,7,'Other','OTH')"
    )
    _row(source, 40, 4, 1, CUTOFF + timedelta(days=4), 0, 60)
    source.execute("UPDATE mart_fact_player_fixture SET team_id=2 WHERE fixture=40")
    with pytest.raises(ValueError, match="club/position ambiguity"):
        target_roster(source, "2025-26", 4)


def test_cutoff_not_silently_shifted(source: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(ValueError, match="first-kickoff"):
        build_fold(
            source,
            season="2025-26",
            gw=4,
            as_of=CUTOFF + timedelta(seconds=1),
            database_hash=DIGEST,
        )


def test_cache_refuses_dirty_before_database_or_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def refuse(_: Path) -> str:
        raise ParticipationError("dirty")

    monkeypatch.setattr("fpl.validate.current_minutes_control_cache.git_clean_head", refuse)
    with pytest.raises(ParticipationError, match="dirty"):
        run(db=tmp_path / "absent.duckdb", output=tmp_path / "output", root=tmp_path)
    assert not (tmp_path / "output").exists()


@pytest.fixture
def cache_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    """Zero folds and a stub connection: provenance checks never fit a model."""
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "results").mkdir()
    db = tmp_path / "reference.duckdb"
    db.write_bytes(b"synthetic database identity; never opened")
    source_path = root / "unchanged.py"
    source_path.write_text("# unchanged prospective source\n", encoding="utf-8")
    frozen = root / "results" / "frozen.json"
    frozen.write_text('{"frozen":true}\n', encoding="utf-8")
    config_path = root / cache.CONFIG
    config_path.write_text(
        yaml.safe_dump(
            {
                "identity": "synthetic_reference",
                "comparator": cache.NAME,
                "evidence_class": cache.EVIDENCE_CLASS,
                "database_sha256": cache.file_sha256(db),
                "seasons": ["2025-26"],
                "expected_folds": 0,
                "expected_rows": 0,
                "expected_direct_proxy_rows": 0,
            }
        ),
        encoding="utf-8",
    )
    proxy_name = "config/retrospective_current_minutes_proxy_v1.yaml"
    (root / proxy_name).write_text(
        yaml.safe_dump(
            {"unchanged_source_sha256": {"unchanged.py": cache.file_sha256(source_path)}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cache, "CONFIG_SHA256", cache.file_sha256(config_path))
    monkeypatch.setattr(cache, "SOURCES", (cache.CONFIG, proxy_name, "unchanged.py"))
    monkeypatch.setattr(cache, "git_clean_head", lambda _: "a" * 40)
    monkeypatch.setattr(
        cache.subprocess,
        "check_output",
        lambda *args, **kwargs: "claude/comet-fpl-v2-architecture-mqrj8f\n",
    )

    def readonly_connection(path: Path, *, read_only: bool) -> duckdb.DuckDBPyConnection:
        assert path == db and read_only is True
        return duckdb.connect(":memory:")

    def no_fit(*args: object, **kwargs: object) -> None:
        pytest.fail("a provenance-only test must not fit a model")

    monkeypatch.setattr(cache, "connect", readonly_connection)
    monkeypatch.setattr(cache, "generate_minutes_folds", lambda _: [])
    monkeypatch.setattr(cache, "build_fold", no_fit)
    return {
        "root": root,
        "db": db,
        "output": tmp_path / "new_reference",
        "source": source_path,
        "config": config_path,
        "frozen": frozen,
    }


def _run_cache(files: dict[str, Path]) -> dict[str, object]:
    return run(db=files["db"], output=files["output"], root=files["root"])


def test_cache_contract_byte_pin_matches_committed_policy() -> None:
    root = Path(__file__).resolve().parents[1]
    assert hashlib.sha256((root / cache.CONFIG).read_bytes()).hexdigest() == cache.CONFIG_SHA256


def test_cache_refuses_wrong_branch_before_output(
    monkeypatch: pytest.MonkeyPatch, cache_files: dict[str, Path]
) -> None:
    monkeypatch.setattr(cache.subprocess, "check_output", lambda *args, **kwargs: "main\n")
    with pytest.raises(ValueError, match="V2 branch"):
        _run_cache(cache_files)
    assert not cache_files["output"].exists()


@pytest.mark.parametrize(
    ("changed", "message"),
    [
        ("config", "contract differs"),
        ("source", "unchanged prospective source differs"),
        ("db", "database differs"),
    ],
)
def test_cache_refuses_changed_pinned_input_before_output(
    cache_files: dict[str, Path], changed: str, message: str
) -> None:
    path = cache_files[changed]
    path.write_bytes(path.read_bytes() + b"\n# drift\n")
    with pytest.raises(ValueError, match=message):
        _run_cache(cache_files)
    assert not cache_files["output"].exists()


def test_cache_refuses_unresolved_wal_before_output(cache_files: dict[str, Path]) -> None:
    Path(str(cache_files["db"]) + ".wal").write_bytes(b"unresolved writer")
    with pytest.raises(ValueError, match="unresolved WAL"):
        _run_cache(cache_files)
    assert not cache_files["output"].exists()


def test_cache_unchanged_readonly_zero_fold_run_and_write_once(
    cache_files: dict[str, Path],
) -> None:
    before = cache.file_sha256(cache_files["db"])
    result = _run_cache(cache_files)
    assert result["completed"] is True
    assert cache.file_sha256(cache_files["db"]) == before
    assert (cache_files["output"] / "manifest.json").is_file()
    with pytest.raises(ValueError, match="NEW external persistent directory"):
        _run_cache(cache_files)


@pytest.mark.parametrize("changed", ["head", "dirty", "source", "db", "wal", "frozen"])
def test_cache_postflight_drift_retains_failure_not_manifest(
    monkeypatch: pytest.MonkeyPatch, cache_files: dict[str, Path], changed: str
) -> None:
    def after_open(_: duckdb.DuckDBPyConnection) -> list[object]:
        if changed == "head":
            monkeypatch.setattr(cache, "git_clean_head", lambda _: "b" * 40)
        elif changed == "dirty":

            def dirty(_: Path) -> str:
                raise ParticipationError("dirty worktree")

            monkeypatch.setattr(cache, "git_clean_head", dirty)
        elif changed == "wal":
            Path(str(cache_files["db"]) + ".wal").write_bytes(b"late writer")
        else:
            path = cache_files[changed]
            path.write_bytes(path.read_bytes() + b"\n# changed during cache\n")
        return []

    monkeypatch.setattr(cache, "generate_minutes_folds", after_open)
    with pytest.raises((ValueError, ParticipationError), match=r"changed|dirty"):
        _run_cache(cache_files)
    output = cache_files["output"]
    assert not (output / "manifest.json").exists()
    failure = json.loads((output / "failure.json").read_text(encoding="utf-8"))
    assert failure["completed"] is False
    assert failure["retained_folds"] == []
    assert (output / "provenance.json").is_file()
