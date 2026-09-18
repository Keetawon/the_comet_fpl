"""Executable contract for the descriptive pre-deadline rest summary.

A red flag needs one witnessed appearance; a green flag needs proof of absence in every
midweek fixture the club played. Everything else is UNKNOWN with a stated reason.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from fpl.config import repo_root
from fpl.publish.rest_summary import (
    CompletedFixture,
    InternationalWindow,
    NextFixture,
    PlayerObservation,
    RosterPlayer,
    build_rest_summary,
    load_international_breaks,
    render_rest_summary_text,
    validate_rest_summary,
)

SEASON = "2026-27"
AS_OF = datetime(2026, 9, 18, 10, 0, tzinfo=UTC)
LIVERPOOL, CITY = 14, 43
GAKPO, HAALAND = 111111, 222222

ROSTER = (
    RosterPlayer(code=GAKPO, web_name="Gakpo", team_code=LIVERPOOL, team_name="Liverpool"),
    RosterPlayer(code=HAALAND, web_name="Haaland", team_code=CITY, team_name="Man City"),
)
NEXT = {
    LIVERPOOL: NextFixture(
        team_code=LIVERPOOL,
        gw=5,
        kickoff=datetime(2026, 9, 20, 15, 30, tzinfo=UTC),
        opponent_name="Bournemouth",
        was_home=True,
    ),
    CITY: NextFixture(
        team_code=CITY,
        gw=5,
        kickoff=datetime(2026, 9, 20, 13, 0, tzinfo=UTC),
        opponent_name="Sunderland",
        was_home=False,
    ),
}


def league(team: int, *, code: int, day: int, minutes: float | None = 90.0, **kwargs: object):
    """A Saturday/Sunday Premier League leg the player started."""
    return CompletedFixture(
        competition_id=8,
        provider_match_id=9000 + day,
        kickoff=datetime(2026, 9, day, 14, 0, tzinfo=UTC),
        team_code=team,
        opponent_name="Man Utd",
        roster_proven=bool(kwargs.get("roster_proven", True)),
        observations=(
            PlayerObservation(code=code, appeared=True, started=True, nominal_minutes=minutes),
        ),
    )


def cup(
    team: int,
    *,
    observations: tuple[PlayerObservation, ...],
    roster_proven: bool = True,
    day: int = 15,
) -> CompletedFixture:
    """A Monday-to-Thursday League Cup tie -- the midweek leg the summary is about."""
    return CompletedFixture(
        competition_id=2,
        provider_match_id=7000 + day,
        kickoff=datetime(2026, 9, day, 19, 0, tzinfo=UTC),
        team_code=team,
        opponent_name="Tottenham",
        roster_proven=roster_proven,
        observations=observations,
    )


def summarise(fixtures, **kwargs):
    return build_rest_summary(
        season=SEASON,
        as_of=AS_OF,
        roster=ROSTER,
        fixtures=fixtures,
        next_fixtures=kwargs.pop("next_fixtures", NEXT),
        **kwargs,
    )


def player(document, code: int):
    return next(p for p in document.players if p.code == code)


def test_a_witnessed_midweek_appearance_is_red_and_dates_the_rest_from_that_leg() -> None:
    document = summarise(
        [
            league(LIVERPOOL, code=GAKPO, day=13),
            cup(
                LIVERPOOL,
                observations=(
                    PlayerObservation(
                        code=GAKPO, appeared=True, started=True, nominal_minutes=90.0
                    ),
                ),
            ),
        ]
    )
    row = player(document, GAKPO)
    assert row.verdict == "midweek_played"
    assert row.midweek_appearances == 1
    assert row.midweek_nominal_minutes == 90.0
    assert row.window_appearances == 2
    # The gap is measured from the cup tie, not from the earlier league game.
    assert row.last_appearance is not None
    assert row.last_appearance.competition_name == "League Cup"
    assert row.rest_hours == pytest.approx(116.5)
    assert row.rest_days == 5
    assert row.unknown_reasons == []


def test_absence_from_a_complete_roster_is_a_proved_rest() -> None:
    document = summarise(
        [
            league(CITY, code=HAALAND, day=13),
            # City played midweek; the interpretation is complete and Haaland is not in it.
            cup(
                CITY,
                observations=(
                    PlayerObservation(
                        code=999999, appeared=True, started=True, nominal_minutes=90.0
                    ),
                ),
            ),
        ]
    )
    row = player(document, HAALAND)
    assert row.verdict == "full_rest"
    assert row.midweek_appearances == 0
    assert row.last_appearance is not None
    assert row.last_appearance.competition_id == 8
    assert row.rest_days == 7
    assert row.unknown_reasons == []


def test_an_unproven_roster_can_never_produce_a_green_flag() -> None:
    document = summarise(
        [
            league(CITY, code=HAALAND, day=13),
            cup(CITY, observations=(), roster_proven=False),
        ]
    )
    row = player(document, HAALAND)
    assert row.verdict == "unknown"
    assert row.unknown_reasons == ["roster_not_proven:7015"]
    # The proved league leg still dates the gap.
    assert row.rest_days == 7


def test_an_unproven_roster_also_never_produces_a_red_flag() -> None:
    """A contradictory interpretation is unusable in both directions, not 'probably played'."""
    document = summarise(
        [
            cup(
                LIVERPOOL,
                observations=(
                    PlayerObservation(
                        code=GAKPO, appeared=True, started=True, nominal_minutes=90.0
                    ),
                ),
                roster_proven=False,
            )
        ]
    )
    row = player(document, GAKPO)
    assert row.verdict == "unknown"
    assert row.midweek_appearances == 0
    assert row.last_appearance is None
    assert "no_witnessed_appearance_in_window" in row.unknown_reasons


@pytest.mark.parametrize(
    "observation",
    [
        PlayerObservation(code=GAKPO, appeared=None, started=None, nominal_minutes=None),
        PlayerObservation(
            code=GAKPO,
            appeared=True,
            started=True,
            nominal_minutes=90.0,
            errors=("two goalkeepers in the starting roster",),
        ),
    ],
)
def test_unknown_participation_downgrades_the_verdict(observation: PlayerObservation) -> None:
    document = summarise([cup(LIVERPOOL, observations=(observation,))])
    row = player(document, GAKPO)
    assert row.verdict == "unknown"
    assert "participation_unknown:7015" in row.unknown_reasons


def test_an_appearance_without_a_duration_stays_an_appearance_with_a_stated_gap() -> None:
    document = summarise(
        [
            cup(
                LIVERPOOL,
                observations=(
                    PlayerObservation(
                        code=GAKPO, appeared=True, started=False, nominal_minutes=None
                    ),
                ),
            )
        ]
    )
    row = player(document, GAKPO)
    assert row.verdict == "midweek_played"
    assert row.midweek_nominal_minutes is None
    assert row.unknown_reasons == ["duration_unknown:7015"]


def test_rest_days_count_uk_calendar_dates_between_the_two_kickoffs() -> None:
    document = summarise([league(CITY, code=HAALAND, day=13)])
    # 13 September to 20 September reads seven days, as a matchday-to-matchday count.
    assert player(document, HAALAND).rest_days == 7
    assert player(document, HAALAND).rest_hours == pytest.approx(167.0)


def test_a_club_with_no_fixture_in_the_window_is_rested_but_says_it_witnessed_nothing() -> None:
    row = player(summarise([]), HAALAND)
    assert row.verdict == "full_rest"
    assert row.last_appearance is None
    assert row.rest_hours is None and row.rest_days is None
    assert row.unknown_reasons == ["no_witnessed_appearance_in_window"]


def test_a_published_international_window_qualifies_the_gap() -> None:
    document = summarise(
        [league(CITY, code=HAALAND, day=13)],
        international_windows=[
            InternationalWindow(
                season=SEASON,
                starts_on=date(2026, 9, 19),
                ends_on=date(2026, 10, 6),
                label="19 Sep-6 Oct",
            )
        ],
    )
    row = player(document, HAALAND)
    assert row.international_window_overlap is True
    assert "international_window_overlap_call_ups_not_captured" in row.unknown_reasons
    # The overlap qualifies the claim; it does not invent a call-up, so the verdict stands.
    assert row.verdict == "full_rest"


def test_a_window_in_another_season_never_qualifies_this_one() -> None:
    document = summarise(
        [league(CITY, code=HAALAND, day=13)],
        international_windows=[
            InternationalWindow(
                season="2025-26",
                starts_on=date(2026, 9, 19),
                ends_on=date(2026, 10, 6),
                label="stale",
            )
        ],
    )
    assert player(document, HAALAND).international_window_overlap is False


def test_a_missing_next_fixture_suppresses_the_gap_rather_than_guessing_one() -> None:
    document = summarise([league(CITY, code=HAALAND, day=13)], next_fixtures={})
    row = player(document, HAALAND)
    assert row.next_fixture is None
    assert row.rest_hours is None and row.rest_days is None
    assert "no_next_fixture_listed" in row.unknown_reasons


def test_an_unlisted_next_kickoff_suppresses_the_gap_but_keeps_the_fixture() -> None:
    document = summarise(
        [league(CITY, code=HAALAND, day=13)],
        next_fixtures={
            CITY: NextFixture(
                team_code=CITY, gw=5, kickoff=None, opponent_name="Sunderland", was_home=False
            )
        },
    )
    row = player(document, HAALAND)
    assert row.next_fixture is not None and row.next_fixture.kickoff is None
    assert row.rest_days is None
    assert "next_fixture_kickoff_unavailable" in row.unknown_reasons


def test_a_fixture_that_has_not_kicked_off_witnesses_nothing() -> None:
    upcoming = CompletedFixture(
        competition_id=2,
        provider_match_id=7777,
        kickoff=AS_OF + timedelta(hours=2),
        team_code=LIVERPOOL,
        opponent_name="Tottenham",
        roster_proven=True,
        observations=(
            PlayerObservation(code=GAKPO, appeared=True, started=True, nominal_minutes=90.0),
        ),
    )
    assert player(summarise([upcoming]), GAKPO).verdict == "full_rest"


def test_a_fixture_older_than_the_window_is_out_of_scope() -> None:
    document = summarise([league(LIVERPOOL, code=GAKPO, day=8)], window_hours=168)
    assert player(document, GAKPO).window_appearances == 0


def test_both_legs_of_a_congested_week_are_counted_and_the_latest_dates_the_gap() -> None:
    document = summarise(
        [
            cup(
                LIVERPOOL,
                day=15,
                observations=(
                    PlayerObservation(
                        code=GAKPO, appeared=True, started=True, nominal_minutes=90.0
                    ),
                ),
            ),
            cup(
                LIVERPOOL,
                day=17,
                observations=(
                    PlayerObservation(
                        code=GAKPO, appeared=True, started=False, nominal_minutes=25.0
                    ),
                ),
            ),
        ]
    )
    row = player(document, GAKPO)
    assert row.midweek_appearances == 2
    assert row.midweek_nominal_minutes == 115.0
    assert row.last_appearance is not None
    assert row.last_appearance.provider_match_id == 7017
    assert row.rest_days == 3


@pytest.mark.parametrize(
    ("fixtures", "message"),
    [
        (
            [league(CITY, code=HAALAND, day=13), league(CITY, code=HAALAND, day=13)],
            "duplicate club fixture side",
        ),
        (
            [
                CompletedFixture(
                    competition_id=99,
                    provider_match_id=1,
                    kickoff=datetime(2026, 9, 13, 14, 0, tzinfo=UTC),
                    team_code=CITY,
                    opponent_name=None,
                    roster_proven=True,
                )
            ],
            "unverified competition",
        ),
        (
            [
                CompletedFixture(
                    competition_id=8,
                    provider_match_id=1,
                    kickoff=datetime(2026, 9, 13, 14, 0, tzinfo=UTC),
                    team_code=CITY,
                    opponent_name=None,
                    roster_proven=True,
                    observations=(
                        PlayerObservation(
                            code=HAALAND, appeared=True, started=True, nominal_minutes=90.0
                        ),
                        PlayerObservation(
                            code=HAALAND, appeared=False, started=False, nominal_minutes=None
                        ),
                    ),
                )
            ],
            "duplicate player observation",
        ),
    ],
)
def test_contradictory_evidence_fails_closed(fixtures, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        summarise(fixtures)


def test_a_naive_cutoff_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone aware"):
        build_rest_summary(
            season=SEASON,
            as_of=datetime(2026, 9, 18, 10, 0),
            roster=ROSTER,
            fixtures=[],
            next_fixtures=NEXT,
        )


def test_a_duplicated_roster_code_is_refused() -> None:
    with pytest.raises(ValueError, match="unique"):
        build_rest_summary(
            season=SEASON,
            as_of=AS_OF,
            roster=[*ROSTER, ROSTER[0]],
            fixtures=[],
            next_fixtures=NEXT,
        )


def test_the_document_round_trips_through_json_and_revalidates() -> None:
    document = summarise(
        [
            league(LIVERPOOL, code=GAKPO, day=13),
            cup(
                LIVERPOOL,
                observations=(
                    PlayerObservation(
                        code=GAKPO, appeared=True, started=True, nominal_minutes=90.0
                    ),
                ),
            ),
            league(CITY, code=HAALAND, day=13),
        ]
    )
    reloaded = validate_rest_summary(json.loads(json.dumps(document.model_dump(mode="json"))))
    assert reloaded.counts == {"players": 2, "midweek_played": 1, "full_rest": 1, "unknown": 0}
    assert reloaded.promotion_permitted is False
    assert reloaded.semantics == "descriptive_observed_rest_not_forecast"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda v: v["counts"].update(full_rest=99), "counts do not reconcile"),
        (lambda v: v["players"][0].update(verdict="full_rest"), "verdict contradicts"),
        (lambda v: v["players"][0].update(midweek_appearances=0), "verdict contradicts"),
        (
            lambda v: v["players"][0].update(rest_hours=-1.0),
            "negative rest",
        ),
        (
            lambda v: v["players"][0].update(international_window_overlap=True),
            "must be stated as a qualification",
        ),
        (
            lambda v: v["players"][0].update(next_fixture=None),
            "rest reported without both of its endpoints",
        ),
        (
            lambda v: v["players"][0].update(window_appearances=0),
            "exceed window appearances",
        ),
    ],
)
def test_validation_rejects_a_document_that_contradicts_itself(mutate, message: str) -> None:
    document = summarise(
        [
            cup(
                LIVERPOOL,
                observations=(
                    PlayerObservation(
                        code=GAKPO, appeared=True, started=True, nominal_minutes=90.0
                    ),
                ),
            )
        ]
    )
    value = document.model_dump(mode="json")
    value["players"] = [p for p in value["players"] if p["code"] == GAKPO]
    value["counts"] = {"players": 1, "midweek_played": 1, "full_rest": 0, "unknown": 0}
    mutate(value)
    with pytest.raises(ValueError, match=message):
        validate_rest_summary(value)


def test_the_rendered_block_carries_every_marker_and_its_caveat() -> None:
    document = summarise(
        [
            league(LIVERPOOL, code=GAKPO, day=13),
            cup(
                LIVERPOOL,
                observations=(
                    PlayerObservation(
                        code=GAKPO, appeared=True, started=True, nominal_minutes=90.0
                    ),
                ),
            ),
            league(CITY, code=HAALAND, day=13),
        ]
    )
    text = render_rest_summary_text(document)
    assert "Rest check before Premier League GW5" in text
    assert "\N{LARGE RED CIRCLE} Gakpo | Liverpool" in text
    assert "\N{LARGE GREEN CIRCLE} Haaland | Man City" in text
    assert "vs Tottenham (League Cup, 15 Sep) - 90 nominal min, started" in text
    assert "GW5, 20 Sep) - 5d rest (116.5h)" in text
    assert "National-team call-ups are not captured" in text
    # Most congested first.
    assert text.index("Gakpo") < text.index("Haaland")


def test_the_published_international_windows_match_the_browser_calendar() -> None:
    """The Python config and the dashboard copy cite one published source; pin them together."""
    source, windows = load_international_breaks()
    body = (repo_root() / "dashboard/src/data/internationalBreaks.ts").read_text(encoding="utf-8")
    assert source.url in body
    parsed = {
        (season, date.fromisoformat(start), date.fromisoformat(end))
        for season, start, end in re.findall(
            r'season:\s*"([^"]+)",\s*from:\s*"([^"]+)",\s*to:\s*"([^"]+)"', body
        )
    }
    assert parsed == {(w.season, w.starts_on, w.ends_on) for w in windows}
    assert parsed, "the calendar must publish at least one verified window"


def test_the_summary_module_never_reaches_a_database() -> None:
    body = (repo_root() / "src/fpl/publish/rest_summary.py").read_text(encoding="utf-8")
    assert "duckdb" not in body
    assert "httpx" not in body


def test_the_config_is_loadable_and_ordered() -> None:
    source, windows = load_international_breaks()
    assert source.published_on <= source.verified_at.date()
    assert all(w.starts_on <= w.ends_on for w in windows)
    assert len({(w.season, w.starts_on) for w in windows}) == len(windows)


def test_an_explicit_config_path_is_honoured(tmp_path: Path) -> None:
    target = tmp_path / "breaks.yaml"
    target.write_text(
        "source:\n"
        "  name: n\n  url: https://example.invalid/x\n  published_on: 2026-09-05\n"
        "  verified_at: 2026-09-15T08:35:18Z\n"
        'windows:\n  - season: "2026-27"\n    from: 2026-10-06\n    to: 2026-09-21\n'
        "    label: reversed\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ends before it starts"):
        load_international_breaks(target)
