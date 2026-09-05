"""Conservative SOT interpretation never replaces missing values without evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import duckdb
import pytest

from fpl.features.pit import AsOf, FeatureSource, PointInTimeView
from fpl.storage.db import initialise
from fpl.validate.retrospective_sdp import EVIDENCE_CLASS, RetrospectiveBackfillView
from fpl.validate.sot_zero_audit import (
    POLICY,
    CorroboratedSotBackfillView,
    IndependentZero,
    SotZeroPolicy,
    build_audit,
    interpret_omission,
)

from .test_retrospective_sdp import AS_OF, _archive_fixture


@pytest.mark.parametrize(
    ("stats", "proxy", "expected"),
    [
        ({"ontargetScoringAtt": 0}, 5, (0, "provider_explicit")),
        ({"ontargetScoringAtt": 4}, 0, (4, "provider_explicit")),
        ({"ontargetScoringAtt": None}, 0, (None, "unresolved_explicit_null")),
        ({}, 0, (None, "unresolved_omission")),
        (
            {"totalScoringAtt": 3, "shotOffTarget": 2, "blockedScoringAtt": 1},
            0,
            (0, "shot_accounting_and_fpl_proxy_zero"),
        ),
        ({"totalScoringAtt": 3, "shotOffTarget": 3}, 0, (0, "shot_accounting_and_fpl_proxy_zero")),
        (
            {"totalScoringAtt": 3, "blockedScoringAtt": 3},
            0,
            (0, "shot_accounting_and_fpl_proxy_zero"),
        ),
        ({"totalScoringAtt": 3, "shotOffTarget": 2}, 0, (None, "unresolved_omission")),
        ({"totalScoringAtt": 3, "shotOffTarget": 3}, 1, (None, "unresolved_omission")),
        ({"totalScoringAtt": 3, "shotOffTarget": 3}, None, (None, "unresolved_omission")),
        (
            {"totalScoringAtt": 6, "shotOffTarget": 6, "blockedScoringAtt": 1},
            0,
            (None, "unresolved_omission"),
        ),
        (
            {"totalScoringAtt": 3, "shotOffTarget": 3, "blockedScoringAtt": None},
            0,
            (None, "unresolved_omission"),
        ),
        (
            {"totalScoringAtt": 3, "shotOffTarget": 3, "expectedGoalsOnTarget": 0.2},
            0,
            (None, "unresolved_omission"),
        ),
        (
            {"totalScoringAtt": 3, "shotOffTarget": 3, "attIboxTarget": 1},
            0,
            (None, "unresolved_omission"),
        ),
        ({"totalScoringAtt": 3, "shotOffTarget": 3, "goals": 1}, 0, (None, "unresolved_omission")),
        (
            {"totalScoringAtt": 3, "shotOffTarget": 3, "expectedGoalsOnTarget": None},
            0,
            (None, "unresolved_omission"),
        ),
        (
            {"totalScoringAtt": 3, "shotOffTarget": 3, "expectedGoalsOnTarget": float("nan")},
            0,
            (None, "unresolved_omission"),
        ),
    ],
)
def test_interpretation_requires_concordant_evidence(stats, proxy, expected) -> None:
    assert interpret_omission(stats, proxy=proxy, independent=None) == expected


@pytest.mark.parametrize("value", [True, -1, 1.5, "0", float("nan"), float("inf")])
def test_invalid_explicit_sot_fails_closed(value) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        interpret_omission({"ontargetScoringAtt": value}, proxy=0, independent=None)


def test_independent_report_resolves_own_goal_but_not_explicit_null() -> None:
    report = IndependentZero(
        season="2024-25",
        fixture=124,
        team_code=4,
        sdp_match_id=2444593,
        source_url="https://www.premierleague.com/en/news/4177908",
        evidence="The match report corroborates Newcastle's zero SOT and own goal.",
    )
    assert interpret_omission({"goals": 1}, proxy=1, independent=report) == (
        0,
        "independent_report_zero",
    )
    assert interpret_omission({"ontargetScoringAtt": None}, proxy=0, independent=report) == (
        None,
        "unresolved_explicit_null",
    )


def _capture(con: duckdb.DuckDBPyConnection, identifier: str, *, later: bool = False) -> None:
    captured = datetime(2026, 9, 5, 2 if later else 1, tzinfo=UTC)
    home = {"totalScoringAtt": 3, "shotOffTarget": 2, "blockedScoringAtt": 1}
    away = {"ontargetScoringAtt": 4, "totalScoringAtt": 8}
    if later:
        home["ontargetScoringAtt"] = 99
    sides = [
        {"side": "Home", "teamId": 101, "stats": home},
        {"side": "Away", "teamId": 202, "stats": away},
    ]
    payload = json.dumps(sides)
    sha = hashlib.sha256(payload.encode()).hexdigest()
    con.execute(
        """
        INSERT INTO raw_pl_sdp_payload VALUES (
            ?, 'pl_sdp', 'match_stats', '/stats', '{}', '2024-25', 9001, ?, 200, ?, ?, ?
        )
    """,
        [identifier, captured, payload, sha, len(payload)],
    )
    for side in sides:
        stats = side["stats"]
        con.execute(
            """
            INSERT INTO stg_pl_sdp_team_match_stats (
                sdp_match_id, side, payload_id, known_at, sdp_team_id,
                stats_json, metric_count, mapped_count
            ) VALUES (9001, ?, ?, ?, ?, ?, ?, 1)
        """,
            [
                side["side"].lower(),
                identifier,
                captured,
                side["teamId"],
                json.dumps(stats),
                len(stats),
            ],
        )
        for key, value in stats.items():
            con.execute(
                """
                INSERT INTO stg_pl_sdp_team_match_metric VALUES (9001, ?, ?, ?, ?, ?, NULL)
            """,
                [
                    side["side"].lower(),
                    identifier,
                    key,
                    "shots_on_target" if key == "ontargetScoringAtt" else None,
                    value,
                ],
            )


@pytest.fixture
def con():
    connection = initialise(":memory:")
    _archive_fixture(connection)
    for team_id, code, name in ((1, 101, "One"), (2, 202, "Two")):
        connection.execute(
            "INSERT INTO mart_dim_team (season, team_id, team_code, team_name, short_name) "
            "VALUES ('2024-25', ?, ?, ?, ?)",
            [team_id, code, name, name],
        )
    connection.execute("UPDATE mart_fact_team_match_stats_v2 SET shots_on_target_allowed_proxy=0")
    _capture(connection, "first")
    yield connection
    connection.close()


def _policy() -> SotZeroPolicy:
    return SotZeroPolicy(
        policy=POLICY,
        evidence_class=EVIDENCE_CLASS,
        reviewed_at=datetime(2026, 9, 6, tzinfo=UTC),
        definition_source="https://www.statsperform.com/opta-event-definitions/",
        independent_zeros=(),
    )


def test_raw_verified_audit_and_separate_view_preserve_originals(con) -> None:
    before = RetrospectiveBackfillView(con, AS_OF).observed_real_sot()
    audit = build_audit(con, _policy())
    assert audit["seasons"]["2024-25"]["raw_sot_non_null"] == 1
    assert audit["seasons"]["2024-25"]["corroborated_zeros"] == 1
    assert audit["raw_payloads_verified"] == 1
    after = CorroboratedSotBackfillView(con, AS_OF, audit).observed_corroborated_sot()
    assert after["shots_on_target"].to_list() == [None, 4]
    assert after["shots_on_target_corroborated"].to_list() == [0, 4]
    assert after.select(before.columns).equals(before)
    assert after["source_known_at"].min() > AS_OF.ts
    assert build_audit(con, _policy()) == audit


def test_later_version_never_changes_earliest_interpretation(con) -> None:
    audit = build_audit(con, _policy())
    first = CorroboratedSotBackfillView(con, AS_OF, audit).observed_corroborated_sot()
    _capture(con, "later", later=True)
    assert build_audit(con, _policy()) == audit
    assert CorroboratedSotBackfillView(con, AS_OF, audit).observed_corroborated_sot().equals(first)


def test_crosswalk_and_capture_identity_fail_closed(con) -> None:
    audit = build_audit(con, _policy())
    audit["missing_sot_decisions"][0]["payload_sha256"] = "wrong"
    with pytest.raises(ValueError, match="canonical raw evidence"):
        CorroboratedSotBackfillView(con, AS_OF, audit).observed_corroborated_sot()


def test_explicit_null_and_unresolved_are_not_imputed(con) -> None:
    audit = build_audit(con, _policy())
    decision = audit["missing_sot_decisions"][0]
    decision["interpreted_sot"] = None
    decision["reason"] = "unresolved_omission"
    frame = CorroboratedSotBackfillView(con, AS_OF, audit).observed_corroborated_sot()
    assert frame["shots_on_target_corroborated"].to_list() == [None, 4]


def test_strict_prospective_cannot_consume_the_new_capability(con) -> None:
    view = CorroboratedSotBackfillView(con, AS_OF, build_audit(con, _policy()))
    assert not isinstance(view, PointInTimeView)
    with pytest.raises(AttributeError):
        PointInTimeView(view, AS_OF).observed_team_football()  # type: ignore[arg-type]
    strict = PointInTimeView(FeatureSource(con), AS_OF)
    assert strict.observed_team_football(providers=["pl_sdp"]).is_empty()


def test_corrupt_raw_payload_is_rejected(con) -> None:
    con.execute("UPDATE raw_pl_sdp_payload SET sha256='wrong'")
    with pytest.raises(ValueError, match="SHA mismatch"):
        build_audit(con, _policy())


def test_raw_team_identity_cannot_disagree_with_staged_crosswalk(con) -> None:
    raw = json.loads(con.execute("SELECT payload FROM raw_pl_sdp_payload").fetchone()[0])
    raw[0]["teamId"] = 999
    payload = json.dumps(raw)
    con.execute(
        "UPDATE raw_pl_sdp_payload SET payload=?, sha256=?",
        [payload, hashlib.sha256(payload.encode()).hexdigest()],
    )
    with pytest.raises(ValueError, match="raw payload team identity"):
        build_audit(con, _policy())


def test_event_cutoff_applies_before_zero_interpretation(con) -> None:
    audit = build_audit(con, _policy())
    kickoff = RetrospectiveBackfillView(con, AS_OF).observed_real_sot()["kickoff_time"][0]
    at_event = CorroboratedSotBackfillView(con, AsOf(kickoff), audit).observed_corroborated_sot()
    after = CorroboratedSotBackfillView(
        con, AsOf(kickoff + timedelta(seconds=1)), audit
    ).observed_corroborated_sot()
    assert at_event.is_empty()
    assert after["shots_on_target_corroborated"].to_list() == [0, 4]


@pytest.mark.parametrize("change", ["explicit_null", "team_average", "unlicensed_reason"])
def test_audit_cannot_license_explicit_null_or_average(con, change) -> None:
    audit = build_audit(con, _policy())
    row = audit["missing_sot_decisions"][0]
    if change == "explicit_null":
        row["raw_field_present"] = True
    elif change == "team_average":
        row["interpreted_sot"] = 3.5
    else:
        row["reason"] = "fill_null_with_zero"
    with pytest.raises(ValueError, match="unlicensed zero"):
        CorroboratedSotBackfillView(con, AS_OF, audit).observed_corroborated_sot()
