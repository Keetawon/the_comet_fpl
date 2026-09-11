"""No code path may fetch a TIMESTAMPTZ in a way that requires `pytz`.

This project pins `tzdata` for `zoneinfo` and deliberately does NOT depend on `pytz`. DuckDB,
however, converts a `TIMESTAMPTZ` returned through `fetchall()`/`fetchone()` into a Python
datetime via `pytz`, so any such projection raises on a clean install while passing on a
developer machine that happens to have it.

That defect has now been found three times in this repository: in the BI exporter's provenance
reads, in the outcome/ledger attachment path, and in the V2 SDP transform. The sanctioned fix
is to project `epoch_us(...)` and rebuild the instant in Python, which also avoids resolving
the IANA database at all. The Arrow path (`.to_arrow_table()` into Polars) is unaffected.

These tests are BEHAVIOURAL rather than a source scan. A regex over SQL text was tried first
and rejected: it cannot tell a docstring from a projection, cannot see through `SELECT *`, and
flags the safe Arrow reads. Blocking the import and running the real code path tests the actual
property, and it keeps working when someone writes the next query.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest

from fpl.storage.db import initialise
from fpl.storage.ledger import TeamLedgerOutcome, attach_team_outcomes, ensure_ledger_schema
from fpl.storage.outcomes import select_finalized_team_outcomes
from fpl.transform import pl_sdp as sdp

KICKOFF = datetime(2025, 11, 25, 15, 0, tzinfo=UTC)


@pytest.fixture
def without_pytz(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `import pytz` fail, reproducing a clean install of this project's declared deps."""
    monkeypatch.setitem(__import__("sys").modules, "pytz", None)


def test_the_guard_actually_reproduces_the_failure(without_pytz: None) -> None:
    """Pin the upstream behaviour, so the tests below cannot pass vacuously.

    If DuckDB ever stops needing `pytz`, this fails and the whole file can be retired rather
    than carried forever for a reason nobody remembers.
    """
    # DuckDB caches timezone conversion state in its extension. Earlier tests can warm
    # that cache, making sys.modules blocking alone a vacuous negative control. A fresh
    # interpreter must still reproduce the missing-dependency failure before conversion.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
sys.modules['pytz'] = None
import duckdb
connection = duckdb.connect(':memory:')
try:
    connection.execute("SET TimeZone='UTC'")
    try:
        connection.execute('SELECT now()::TIMESTAMPTZ').fetchall()
    except duckdb.InvalidInputException as error:
        assert 'pytz' in str(error), str(error)
    else:
        raise AssertionError('TIMESTAMPTZ unexpectedly no longer requires pytz')
finally:
    connection.close()
""",
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_epoch_us_needs_no_timezone_database(without_pytz: None) -> None:
    """The sanctioned fix returns an integer, so no conversion is attempted."""
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET TimeZone='UTC'")
        row = connection.execute("SELECT epoch_us(TIMESTAMPTZ '2026-08-21 17:30:00+00')").fetchone()
        assert row is not None and isinstance(row[0], int)
        assert datetime.fromtimestamp(row[0] / 1_000_000, tz=UTC) == datetime(
            2026, 8, 21, 17, 30, tzinfo=UTC
        )
    finally:
        connection.close()


def _seed_fixture(connection: Any) -> None:
    connection.execute(
        """
        INSERT INTO stg_fixture (season, fixture, pulse_id, gw, kickoff_time, team_h, team_a,
                                 team_h_score, team_a_score, finished)
        VALUES ('2025-26', 7, 116001, 12, ?, 1, 4, 2, 1, TRUE)
        """,
        [KICKOFF],
    )
    for team_id, team_code, name in ((1, 3, "Arsenal"), (4, 8, "Chelsea")):
        connection.execute(
            "INSERT INTO stg_team (season, team_id, team_name, short_name, team_code) "
            "VALUES ('2025-26', ?, ?, ?, ?)",
            [team_id, name, name[:3].upper(), team_code],
        )
        connection.execute(
            "INSERT INTO mart_dim_team (season, team_id, team_code, team_name, short_name) "
            "VALUES ('2025-26', ?, ?, ?, ?)",
            [team_id, team_code, name, name[:3].upper()],
        )


def test_finalized_team_outcome_selection_works_without_pytz(
    tmp_path: Path, without_pytz: None
) -> None:
    """The outcome path reads fixture kickoffs; it must not need a timezone database."""
    connection = initialise(tmp_path / "outcomes.duckdb")
    try:
        _seed_fixture(connection)
        outcomes = select_finalized_team_outcomes(
            connection, as_of=datetime(2026, 1, 1, tzinfo=UTC)
        )
        assert len(outcomes) == 2, "one reciprocal pair per finalized fixture"
        assert {outcome.kickoff_time for outcome in outcomes} == {KICKOFF}
        assert all(outcome.kickoff_time.tzinfo is not None for outcome in outcomes)
    finally:
        connection.close()


def test_team_outcome_reattachment_works_without_pytz(tmp_path: Path, without_pytz: None) -> None:
    """Idempotent re-attachment compares stored kickoffs, which is where it broke before."""
    connection = initialise(tmp_path / "ledger.duckdb")
    try:
        ensure_ledger_schema(connection)
        pair = [
            TeamLedgerOutcome(
                season="2025-26",
                fixture=7,
                team_id=team_id,
                team_code=team_code,
                opponent_team_id=opponent,
                gw=12,
                kickoff_time=KICKOFF,
                was_home=was_home,
                goals_for=goals_for,
                goals_against=goals_against,
            )
            for team_id, team_code, opponent, was_home, goals_for, goals_against in (
                (1, 3, 4, True, 2, 1),
                (4, 8, 1, False, 1, 2),
            )
        ]
        assert attach_team_outcomes(connection, pair) == 2
        # The second call re-reads the stored kickoff to prove the values are unchanged.
        assert attach_team_outcomes(connection, pair) == 0
    finally:
        connection.close()


def test_sdp_staging_and_crosswalk_work_without_pytz(tmp_path: Path, without_pytz: None) -> None:
    """The V2 SDP path reads capture times and kickoffs on every staging pass."""
    from fpl.ingest.pl_sdp import RawPayload

    payload = {
        "content": [
            {
                "id": 116001,
                "season": {"id": 719},
                "matchweek": 12,
                "kickoff": {"millis": int(KICKOFF.timestamp() * 1000)},
                "teams": [
                    {"team": {"id": 3, "name": "Arsenal"}},
                    {"team": {"id": 8, "name": "Chelsea"}},
                ],
                "score": {"homeScore": 2, "awayScore": 1},
            }
        ]
    }
    text = json.dumps(payload)
    raw = RawPayload(
        endpoint="matches",
        path="/api/v2/matches",
        params={"season": 719},
        fetched_at=datetime(2025, 11, 26, 8, 0, tzinfo=UTC),
        status_code=200,
        text=text,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        byte_count=len(text.encode()),
        payload=payload,
    )
    connection = initialise(tmp_path / "sdp.duckdb")
    try:
        _seed_fixture(connection)
        sdp.land_payload(connection, raw, season="2025-26")
        report = sdp.stage_matches(connection, season_labels={719: "2025-26"})
        assert report.matches_staged == 1, report.schema_failures
        audit = sdp.resolve_crosswalk(
            connection, team_name_codes=sdp.team_name_code_map(connection)
        )
        assert audit.matched_by_pulse_id == 1
        assert audit.kickoff_corroborated == 1
    finally:
        connection.close()


def test_complete_sdp_audit_cli_in_cold_process_needs_no_pytz(tmp_path: Path) -> None:
    """A fresh supported install must write every real audit report, not only stage rows."""
    from fpl.ingest.pl_sdp import RawPayload

    from .test_daily_pl_sdp import _land, _official

    database = tmp_path / "operational.duckdb"
    reports = tmp_path / "audit"
    _official(database)
    _land(database)
    # Exercise the formerly unsafe unmatched-provider timestamp path as well as coverage.
    payload = {
        "data": [
            {
                "matchId": 7999,
                "season": 2026,
                "kickoff": "2026-09-03T14:00:00.123456Z",
                "homeTeam": {"id": 3, "name": "Arsenal"},
                "awayTeam": {"id": 9, "name": "Coventry"},
            }
        ]
    }
    body = json.dumps(payload)
    raw = RawPayload(
        endpoint="matches",
        path="/api/v2/matches",
        params={"season": 2026},
        fetched_at=datetime(2026, 9, 6, 18, tzinfo=UTC),
        status_code=200,
        text=body,
        sha256=hashlib.sha256(body.encode()).hexdigest(),
        byte_count=len(body.encode()),
        payload=payload,
    )
    with initialise(database) as connection:
        sdp.land_payload(connection, raw, season="2026-27")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys,runpy; sys.modules['pytz']=None; "
            "sys.argv=['audit_pl_sdp',*sys.argv[1:]]; "
            "runpy.run_module('fpl.jobs.audit_pl_sdp',run_name='__main__')",
            "--db",
            str(database),
            "--stage",
            "--results",
            str(reports),
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert {path.name for path in reports.glob("*.json")} == {
        "pl_sdp_identity_audit.json",
        "pl_sdp_coverage.json",
        "pl_sdp_reconciliation.json",
        "pl_sdp_metric_inventory.json",
    }
    coverage = json.loads((reports / "pl_sdp_coverage.json").read_text())
    season = coverage["providers"]["pl_sdp"]["2026-27"]
    assert season["first_kickoff"] == "2026-08-22 14:00:00+00:00"
    assert season["last_kickoff"] == "2026-09-05 14:00:00+00:00"
    assert season["metrics"]["shots_on_target"]["first_measured_kickoff"] == season["first_kickoff"]
    assert season["metrics"]["shots_on_target"]["last_measured_kickoff"] == season["last_kickoff"]
    assert season["metrics"]["expected_goals"]["first_measured_kickoff"] is None
    identity = json.loads((reports / "pl_sdp_identity_audit.json").read_text())
    assert identity["details"]["unmatched_sdp"][0]["kickoff"] == "2026-09-03 14:00:00.123456+00:00"
