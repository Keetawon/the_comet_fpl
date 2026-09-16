"""Synthetic capture -> normalization -> cutoff-safe production state, without network."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from fpl.ingest.pl_sdp import parse_match_summary
from fpl.jobs.capture_pl_sdp import capture, required_core_rechecks
from fpl.storage.db import initialise
from fpl.storage.sdp_runtime import load_sdp_state

from .test_pl_sdp_revision_pit import CAPTURED, SEASON, _raw, _rebuild
from .test_sdp_primary import CUTOFF, METRICS, seed


@pytest.mark.parametrize("response", ["repaired", "incomplete", "network_failure"])
def test_required_history_refresh_outside_lookback_preserves_versions(tmp_path, response):
    database = tmp_path / "operational.duckdb"
    with initialise(database) as con:
        seed(con, change=lambda payload: payload[0]["stats"].pop("ontargetScoringAtt"))
        old = load_sdp_state(con, cutoff=CUTOFF, season=SEASON)
        assert (SEASON, 103) in old.failures
        metadata = json.loads(
            con.execute(
                "SELECT CAST(payload AS VARCHAR) FROM raw_pl_sdp_payload WHERE endpoint='matches' "
                "ORDER BY fetched_at DESC LIMIT 1"
            ).fetchone()[0]
        )
        original = con.execute(
            "SELECT payload_id,sha256,epoch_us(fetched_at) FROM raw_pl_sdp_payload "
            "WHERE endpoint='match_stats' ORDER BY payload_id"
        ).fetchall()

    known = CUTOFF + timedelta(hours=1)  # Synthetic receipt clock; never used by a live run.

    class Client:
        request_count = 0

        def iter_matches(self, *, season_id):
            self.request_count += 1
            yield (
                _raw("matches", metadata, CAPTURED + timedelta(seconds=1)),
                [parse_match_summary(row) for row in metadata["content"]],
            )

        def fetch_match_stats(self, match_id):
            self.request_count += 1
            assert match_id == 300103
            if response == "network_failure":
                raise OSError("synthetic SDP outage")
            payload = [
                {"side": side, "team": {"id": team}, "stats": dict(METRICS)}
                for side, team in (("Home", 8), ("Away", 3))
            ]
            if response == "incomplete":
                payload[0]["stats"].pop("ontargetScoringAtt")
            return _raw("match_stats", payload, known, match_id)

    def run():
        return capture(
            season=SEASON,
            db_path=database,
            lookback_days=5,
            client=Client(),
            now=known,
            recheck_required_history=True,
        )

    report = run()
    assert report.required_history_rechecks == (300103,)
    assert report.stats_requested == 1
    assert bool(report.failures) == (response == "network_failure")
    if response != "network_failure":
        receipt = report.source_versions[0]
        assert receipt.request_fetched_at == known
        assert receipt.known_at == (known if response == "repaired" else CAPTURED)
        assert receipt.new_version == (response == "repaired")
    with initialise(database) as con:
        _rebuild(con)
        assert load_sdp_state(con, cutoff=CUTOFF, season=SEASON) == old
        current = load_sdp_state(con, cutoff=known, season=SEASON)
        assert ((SEASON, 103) not in current.failures) == (response == "repaired")
        retained = con.execute(
            "SELECT payload_id,sha256,epoch_us(fetched_at) FROM raw_pl_sdp_payload "
            "WHERE endpoint='match_stats' ORDER BY payload_id"
        ).fetchall()
        assert set(original) <= set(retained)
        normalized_count = con.execute(
            "SELECT count(*) FROM mart_fact_team_match_stats_v2_version"
        ).fetchone()[0]
    repeated = run()
    assert repeated.payloads_new == 0
    with initialise(database) as con:
        _rebuild(con)
        assert (
            con.execute("SELECT count(*) FROM mart_fact_team_match_stats_v2_version").fetchone()[0]
            == normalized_count
        )


def test_rechecks_are_bounded_to_last_five_club_matches(tmp_path):
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con, change=lambda p: p[0]["stats"].pop("ontargetScoringAtt"))
        matches = [
            parse_match_summary(
                {
                    "matchId": 300103 + i,
                    "kickoff": (CUTOFF - timedelta(days=8 - i)).isoformat(),
                    "homeTeam": {"id": 3},
                    "awayTeam": {"id": 8},
                }
            )
            for i in range(6)
        ]
        # The retained incomplete fixture has aged out of BOTH clubs' recent-five window.
        assert required_core_rechecks(con, season=SEASON, completed=matches) == set()
