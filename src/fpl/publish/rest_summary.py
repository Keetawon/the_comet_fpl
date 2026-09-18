"""Descriptive pre-deadline rest reporting over already-captured competitive participation.

This is reporting, not a model. It reads witnessed appearances in completed fixtures and
states how long a player has between his last observed match and his club's next scheduled
Premier League fixture. It never estimates fatigue, never changes minutes, xP, a PMF, an
optimizer input or a monitoring score, and never converts an absence of evidence into rest.

Three rules decide everything here:

* **A red flag is cheap; a green flag must be earned.** A witnessed appearance proves
  congestion. Proving the opposite needs a complete, error-free interpretation of that
  club's side in every midweek fixture in the window -- an absent endpoint or an
  unresolved identity cannot prove that a player did not play, so the verdict is UNKNOWN.
* **Unknown is a verdict, not a zero.** Every downgrade carries its reason and the exact
  fixture that caused it.
* **National-team call-ups are not captured anywhere in this repository.** A published
  international window overlapping the gap qualifies a rest claim; it never establishes
  that a particular player travelled.

Durations are the provider's nominal period-clock intervals
(``nominal_period_clock_intervals_v1_not_fpl_minutes``), which is not FPL's recorded
``minutes``. For a Premier League leg FPL's own figure remains the authority.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from fpl.config import config_dir

EVIDENCE_CLASS: Final = "descriptive_observed_rest_development"
DURATION_DEFINITION: Final = "nominal_period_clock_intervals_v1_not_fpl_minutes"
MIDWEEK_DEFINITION: Final = "Monday_through_Thursday_UTC"
# Matches `config/competitive_workload_staging.yaml`; a week is the default review window.
DEFAULT_WINDOW_HOURS: Final = 168
# Presentation calendar. The all-competition calendar already counts listed gaps in UK dates.
DISPLAY_ZONE: Final = ZoneInfo("Europe/London")
COMPETITION_NAMES: Final[Mapping[int, str]] = {
    8: "Premier League",
    1: "FA Cup",
    2: "League Cup",
    5: "Champions League",
    6: "Europa League",
    1125: "Conference League",
}

Verdict = Literal["midweek_played", "full_rest", "unknown"]


@dataclass(frozen=True, slots=True)
class PlayerObservation:
    """One player's witnessed participation inside one completed fixture."""

    code: int
    appeared: bool | None
    started: bool | None
    nominal_minutes: float | None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CompletedFixture:
    """One scoped club's side of one completed fixture, with its proof state attached."""

    competition_id: int
    provider_match_id: int
    kickoff: datetime
    team_code: int
    opponent_name: str | None
    # True only when this club's whole side interpreted without error, so that a player's
    # absence from `observations` is a proved non-selection rather than missing evidence.
    roster_proven: bool
    observations: tuple[PlayerObservation, ...] = ()

    @property
    def midweek(self) -> bool:
        return self.kickoff.astimezone(UTC).weekday() <= 3


@dataclass(frozen=True, slots=True)
class RosterPlayer:
    code: int
    web_name: str
    team_code: int
    team_name: str


@dataclass(frozen=True, slots=True)
class NextFixture:
    team_code: int
    gw: int
    kickoff: datetime | None
    opponent_name: str | None
    was_home: bool | None


@dataclass(frozen=True, slots=True)
class InternationalWindow:
    season: str
    starts_on: date
    ends_on: date
    label: str


class RestRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BreakSource(RestRecord):
    name: str
    url: str
    published_on: date
    verified_at: AwareDatetime


class Appearance(RestRecord):
    competition_id: int
    competition_name: str
    provider_match_id: int = Field(gt=0)
    kickoff: AwareDatetime
    opponent_name: str | None
    started: bool | None
    nominal_minutes: float | None = Field(default=None, ge=0.0)
    midweek: bool


class UpcomingFixture(RestRecord):
    gw: int = Field(ge=1, le=38)
    kickoff: AwareDatetime | None
    opponent_name: str | None
    was_home: bool | None


class PlayerRest(RestRecord):
    code: int = Field(gt=0)
    web_name: str
    team_code: int = Field(gt=0)
    team_name: str
    verdict: Verdict
    last_appearance: Appearance | None
    next_fixture: UpcomingFixture | None
    rest_hours: float | None
    # Whole UK calendar days between the two kickoff dates: 13 Sep -> 20 Sep reads 7.
    rest_days: int | None
    midweek_appearances: int
    midweek_nominal_minutes: float | None
    window_appearances: int
    international_window_overlap: bool
    unknown_reasons: list[str]


class RestSummary(RestRecord):
    schema_version: Literal[1] = 1
    semantics: Literal["descriptive_observed_rest_not_forecast"] = (
        "descriptive_observed_rest_not_forecast"
    )
    season: str
    as_of: AwareDatetime
    window_hours: int = Field(gt=0)
    midweek_definition: str = MIDWEEK_DEFINITION
    duration_definition: str = DURATION_DEFINITION
    evidence_class: str = EVIDENCE_CLASS
    promotion_permitted: Literal[False] = False
    international_break_source: BreakSource | None = None
    counts: dict[str, int]
    players: list[PlayerRest]


def load_international_breaks(
    path: Path | None = None,
) -> tuple[BreakSource, tuple[InternationalWindow, ...]]:
    """Read the published window annotations. The browser calendar carries the same source."""
    target = path or config_dir() / "international_breaks.yaml"
    with target.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("international break config did not parse to a mapping")
    source = BreakSource.model_validate(loaded["source"])
    windows = tuple(
        InternationalWindow(
            season=str(row["season"]),
            starts_on=row["from"],
            ends_on=row["to"],
            label=str(row["label"]),
        )
        for row in loaded["windows"]
    )
    for window in windows:
        if not isinstance(window.starts_on, date) or not isinstance(window.ends_on, date):
            raise ValueError("international window bounds must be calendar dates")
        if window.starts_on > window.ends_on:
            raise ValueError("international window ends before it starts")
    return source, windows


def _aware(value: datetime, label: str) -> datetime:
    if value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone aware")
    return value


def _overlaps(windows: Iterable[InternationalWindow], season: str, first: date, last: date) -> bool:
    if first > last:
        first, last = last, first
    return any(w.season == season and w.starts_on <= last and w.ends_on >= first for w in windows)


def build_rest_summary(
    *,
    season: str,
    as_of: datetime,
    roster: Sequence[RosterPlayer],
    fixtures: Sequence[CompletedFixture],
    next_fixtures: Mapping[int, NextFixture],
    international_windows: Sequence[InternationalWindow] = (),
    break_source: BreakSource | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> RestSummary:
    """Summarise observed congestion for each rostered player. Pure; reads no source."""
    _aware(as_of, "rest summary cutoff")
    if window_hours <= 0:
        raise ValueError("positive rest review window required")
    if len({p.code for p in roster}) != len(roster):
        raise ValueError("roster player codes must be unique")
    window_start = as_of.timestamp() - window_hours * 3600
    scoped: dict[int, list[CompletedFixture]] = {}
    seen: set[tuple[int, int, int]] = set()
    for fixture in fixtures:
        _aware(fixture.kickoff, "fixture kickoff")
        if fixture.competition_id not in COMPETITION_NAMES:
            raise ValueError("unverified competition cannot supply rest evidence")
        if fixture.kickoff >= as_of:
            # A fixture that has not kicked off cannot witness participation.
            continue
        if fixture.kickoff.timestamp() < window_start:
            continue
        key = (fixture.team_code, fixture.competition_id, fixture.provider_match_id)
        if key in seen:
            raise ValueError("duplicate club fixture side in rest evidence")
        seen.add(key)
        if len({o.code for o in fixture.observations}) != len(fixture.observations):
            raise ValueError("duplicate player observation inside one fixture side")
        scoped.setdefault(fixture.team_code, []).append(fixture)

    players: list[PlayerRest] = []
    for player in sorted(roster, key=lambda p: (p.team_name, p.web_name, p.code)):
        players.append(
            _player_rest(
                player,
                season=season,
                club_fixtures=sorted(
                    scoped.get(player.team_code, ()), key=lambda f: (f.kickoff, f.provider_match_id)
                ),
                upcoming=next_fixtures.get(player.team_code),
                windows=international_windows,
            )
        )
    counts = {
        "players": len(players),
        "midweek_played": sum(p.verdict == "midweek_played" for p in players),
        "full_rest": sum(p.verdict == "full_rest" for p in players),
        "unknown": sum(p.verdict == "unknown" for p in players),
    }
    return RestSummary(
        season=season,
        as_of=as_of,
        window_hours=window_hours,
        international_break_source=break_source,
        counts=counts,
        players=players,
    )


def _player_rest(
    player: RosterPlayer,
    *,
    season: str,
    club_fixtures: Sequence[CompletedFixture],
    upcoming: NextFixture | None,
    windows: Sequence[InternationalWindow],
) -> PlayerRest:
    reasons: set[str] = set()
    appearances: list[tuple[CompletedFixture, PlayerObservation]] = []
    midweek_unusable = False
    for fixture in club_fixtures:
        if not fixture.roster_proven:
            # Nothing in an unproven side is usable in either direction: an absence does not
            # prove non-selection, and a row from a contradictory interpretation does not
            # prove an appearance. A midweek leg therefore leaves the verdict unknown.
            reasons.add(f"roster_not_proven:{fixture.provider_match_id}")
            midweek_unusable = midweek_unusable or fixture.midweek
            continue
        row = next((o for o in fixture.observations if o.code == player.code), None)
        if row is None:
            # A complete valid roster without this player is a proved non-selection.
            continue
        if row.errors or row.appeared is None:
            reasons.add(f"participation_unknown:{fixture.provider_match_id}")
            midweek_unusable = midweek_unusable or fixture.midweek
            continue
        if row.appeared is not True:
            continue
        appearances.append((fixture, row))
        if row.nominal_minutes is None:
            reasons.add(f"duration_unknown:{fixture.provider_match_id}")

    midweek = [(f, o) for f, o in appearances if f.midweek]
    measured = [o.nominal_minutes for _, o in midweek if o.nominal_minutes is not None]
    last = max(
        appearances,
        key=lambda pair: (pair[0].kickoff, pair[0].provider_match_id),
        default=None,
    )

    if midweek:
        verdict: Verdict = "midweek_played"
    elif midweek_unusable:
        verdict = "unknown"
    else:
        verdict = "full_rest"
    if not appearances:
        reasons.add("no_witnessed_appearance_in_window")

    rest_hours: float | None = None
    rest_days: int | None = None
    overlap = False
    if upcoming is None:
        reasons.add("no_next_fixture_listed")
    elif upcoming.kickoff is None:
        reasons.add("next_fixture_kickoff_unavailable")
    elif last is not None:
        rest_hours = (upcoming.kickoff - last[0].kickoff).total_seconds() / 3600
        rest_days = (
            upcoming.kickoff.astimezone(DISPLAY_ZONE).date()
            - last[0].kickoff.astimezone(DISPLAY_ZONE).date()
        ).days
        overlap = _overlaps(
            windows,
            season,
            last[0].kickoff.astimezone(DISPLAY_ZONE).date(),
            upcoming.kickoff.astimezone(DISPLAY_ZONE).date(),
        )
        if overlap:
            reasons.add("international_window_overlap_call_ups_not_captured")

    return PlayerRest(
        code=player.code,
        web_name=player.web_name,
        team_code=player.team_code,
        team_name=player.team_name,
        verdict=verdict,
        last_appearance=None if last is None else _appearance(*last),
        next_fixture=None
        if upcoming is None
        else UpcomingFixture(
            gw=upcoming.gw,
            kickoff=upcoming.kickoff,
            opponent_name=upcoming.opponent_name,
            was_home=upcoming.was_home,
        ),
        rest_hours=rest_hours,
        rest_days=rest_days,
        midweek_appearances=len(midweek),
        midweek_nominal_minutes=sum(measured) if measured else None,
        window_appearances=len(appearances),
        international_window_overlap=overlap,
        unknown_reasons=sorted(reasons),
    )


def _appearance(fixture: CompletedFixture, row: PlayerObservation) -> Appearance:
    return Appearance(
        competition_id=fixture.competition_id,
        competition_name=COMPETITION_NAMES[fixture.competition_id],
        provider_match_id=fixture.provider_match_id,
        kickoff=fixture.kickoff,
        opponent_name=fixture.opponent_name,
        started=row.started,
        nominal_minutes=row.nominal_minutes,
        midweek=fixture.midweek,
    )


def validate_rest_summary(value: Any) -> RestSummary:
    """Re-read a published summary and refuse a document that contradicts itself."""
    document = RestSummary.model_validate(value)
    codes = {p.code for p in document.players}
    if len(codes) != len(document.players):
        raise ValueError("duplicate player in rest summary")
    for player in document.players:
        last, upcoming = player.last_appearance, player.next_fixture
        if last is not None and last.kickoff >= document.as_of:
            raise ValueError("witnessed appearance postdates the summary cutoff")
        if (player.verdict == "midweek_played") != (player.midweek_appearances > 0):
            raise ValueError("verdict contradicts the witnessed midweek appearances")
        if player.verdict == "full_rest" and player.midweek_appearances:
            raise ValueError("a proved full rest cannot carry a midweek appearance")
        if player.verdict == "unknown" and not player.unknown_reasons:
            raise ValueError("an unknown verdict must state its reason")
        if player.window_appearances < player.midweek_appearances:
            raise ValueError("midweek appearances exceed window appearances")
        if (last is None or upcoming is None or upcoming.kickoff is None) and (
            player.rest_hours is not None or player.rest_days is not None
        ):
            raise ValueError("rest reported without both of its endpoints")
        if player.rest_hours is not None and player.rest_hours < 0:
            raise ValueError("negative rest between kickoffs")
        if player.international_window_overlap and (
            "international_window_overlap_call_ups_not_captured" not in player.unknown_reasons
        ):
            raise ValueError("international overlap must be stated as a qualification")
    expected = {
        "players": len(document.players),
        "midweek_played": sum(p.verdict == "midweek_played" for p in document.players),
        "full_rest": sum(p.verdict == "full_rest" for p in document.players),
        "unknown": sum(p.verdict == "unknown" for p in document.players),
    }
    if document.counts != expected:
        raise ValueError("rest summary counts do not reconcile to its rows")
    return document


_MARKS: Final[Mapping[Verdict, str]] = {
    "midweek_played": "\N{LARGE RED CIRCLE}",
    "full_rest": "\N{LARGE GREEN CIRCLE}",
    "unknown": "\N{MEDIUM WHITE CIRCLE}",
}


def _day(value: datetime) -> str:
    return value.astimezone(DISPLAY_ZONE).strftime("%d %b")


def _sort_key(player: PlayerRest) -> tuple[int, float, str]:
    # Most congested first: red before unknown before green, then by the shortest gap.
    order = {"midweek_played": 0, "unknown": 1, "full_rest": 2}[player.verdict]
    return (
        order,
        player.rest_hours if player.rest_hours is not None else float("inf"),
        player.web_name,
    )


def render_rest_summary_text(document: RestSummary) -> str:
    """A reviewable text block. Every marker is a claim the document already justifies."""
    gws = sorted({p.next_fixture.gw for p in document.players if p.next_fixture is not None})
    heading = (
        f"GW{gws[0]}" if len(gws) == 1 else ("GW" + "/".join(str(g) for g in gws) if gws else "")
    )
    lines = [
        f"Rest check before Premier League {heading}".rstrip(),
        f"as_of {document.as_of.isoformat()} | window {document.window_hours}h "
        f"| midweek {document.midweek_definition}",
        f"{_MARKS['full_rest']} proved no midweek match  "
        f"{_MARKS['midweek_played']} played midweek  "
        f"{_MARKS['unknown']} unknown, check manually",
        "Durations are provider nominal period-clock minutes, not FPL minutes.",
        "",
    ]
    for player in sorted(document.players, key=_sort_key):
        lines.append(f"{_MARKS[player.verdict]} {player.web_name} | {player.team_name}")
        last = player.last_appearance
        if last is None:
            lines.append("   last: no witnessed appearance in the window")
        else:
            minutes = (
                "duration unknown"
                if last.nominal_minutes is None
                else f"{last.nominal_minutes:g} nominal min"
            )
            role = "started" if last.started else ("off the bench" if last.started is False else "")
            opponent = last.opponent_name or "opponent unavailable"
            lines.append(
                f"   last: vs {opponent} ({last.competition_name}, {_day(last.kickoff)})"
                f" - {minutes}{', ' + role if role else ''}"
            )
        upcoming = player.next_fixture
        if upcoming is None or upcoming.kickoff is None:
            lines.append("   next: kickoff not listed")
        else:
            venue = "H" if upcoming.was_home else ("A" if upcoming.was_home is False else "?")
            rest = (
                "rest unavailable"
                if player.rest_days is None or player.rest_hours is None
                else f"{player.rest_days}d rest ({player.rest_hours:.1f}h)"
            )
            lines.append(
                f"   next: vs {upcoming.opponent_name or '?'} ({venue}, GW{upcoming.gw},"
                f" {_day(upcoming.kickoff)}) - {rest}"
            )
        if player.midweek_appearances:
            total = player.midweek_nominal_minutes
            load = "duration unknown" if total is None else f"{total:g} nominal min"
            lines.append(f"   midweek load: {player.midweek_appearances} appearance(s), {load}")
        for reason in player.unknown_reasons:
            lines.append(f"   ! {reason}")
        lines.append("")
    counts = document.counts
    lines.append(
        f"{counts['midweek_played']} played midweek, {counts['full_rest']} proved rested,"
        f" {counts['unknown']} unknown, of {counts['players']} players."
    )
    lines.append(
        "Observed participation only. National-team call-ups are not captured, and this"
        " changes no forecast, price or optimizer input."
    )
    return "\n".join(lines)
