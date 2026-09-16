"""Development-only exposure-pooled FPL disciplinary outcomes, not physical cards.

The audited archive encodes mutually exclusive scored none/yellow/red outcomes.
This does NOT assert physical yellows and reds cannot occur in the same match.
No production job imports this module. Cutoffs/whole-GW exclusions are mandatory.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from fpl.config import ScoringRules
from fpl.types import Position

NAME: Final = "retrospective_exposure_pooled_disciplinary_v1"
EVIDENCE_CLASS: Final = "retrospective_archive_price_proxy_development"
type CardPmf = tuple[float, float, float]
NONE: CardPmf = (1.0, 0.0, 0.0)


def scored_card_state(yellow: int | None, red: int | None) -> int | None:
    """FPL-encoded label only; never silently erase a contradictory joint row."""
    if yellow is None or red is None:
        return None
    if type(yellow) is not int or type(red) is not int:
        raise ValueError("FPL card counts must be nullable integers, not coercible aliases")
    if (yellow, red) not in {(0, 0), (1, 0), (0, 1)}:
        raise ValueError("unsupported FPL scored card state; re-audit target encoding")
    return 2 if red else yellow


def scored_card_points(state: int, rules: ScoringRules) -> int:
    if type(state) is not int or state not in (0, 1, 2):
        raise ValueError("unsupported scored card state")
    return (0, rules.yellow_cards, rules.red_cards)[state]


def _pmf(pmf: Sequence[float]) -> None:
    if len(pmf) != 3 or any(not math.isfinite(p) or p < 0 for p in pmf):
        raise ValueError("invalid disciplinary PMF")
    if not math.isclose(sum(pmf), 1.0, rel_tol=0, abs_tol=1e-12):
        raise ValueError("disciplinary PMF mass differs from one")


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware cutoff/event required")


@dataclass(frozen=True, slots=True)
class DisciplinaryObservation:
    season: str
    gw: int
    fixture: int
    code: int
    position: Position
    kickoff: datetime
    minutes: int | None
    yellow: int | None
    red: int | None


@dataclass(frozen=True, slots=True)
class ConditionalDisciplinary:
    """One scored-card categorical PMF per minutes bin; bin zero is exact none.

    Owner-authorized on-pitch approximation. Bench cards stay in observed labels,
    but are not predicted. Never describe this as complete football discipline.
    """

    by_minutes_bin: tuple[CardPmf, CardPmf, CardPmf, CardPmf]

    def __post_init__(self) -> None:
        if len(self.by_minutes_bin) != 4 or self.by_minutes_bin[0] != NONE:
            raise ValueError("nonappearance must have exactly zero predicted card points")
        for row in self.by_minutes_bin:
            _pmf(row)

    def marginal(self, minutes: Sequence[float]) -> CardPmf:
        if (
            len(minutes) != 4
            or any(not math.isfinite(p) or p < 0 for p in minutes)
            or not math.isclose(sum(minutes), 1, rel_tol=0, abs_tol=1e-12)
        ):
            raise ValueError("invalid four-bin minutes distribution")
        masses = tuple(
            sum(minutes[b] * self.by_minutes_bin[b][s] for b in range(4)) for s in range(3)
        )
        return masses[0], masses[1], masses[2]


@dataclass(frozen=True, slots=True)
class DisciplinaryParameters:
    position_prior_minutes: float = 4500.0
    player_yellow_prior_minutes: float = 4500.0
    player_red_prior_minutes: float = 45000.0
    global_pseudocount: float = 0.5
    global_prior_minutes: float = 90.0

    def __post_init__(self) -> None:
        values = (
            self.position_prior_minutes,
            self.player_yellow_prior_minutes,
            self.player_red_prior_minutes,
            self.global_pseudocount,
            self.global_prior_minutes,
        )
        if any(not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("positive finite pooling parameters required")


class ExposurePooledDisciplinary:
    """Two pooled cause-specific rates form ONE finite competing-risk outcome.

    Long-run appearance exposure, no recent-card streak feature, no target minutes.
    Exposure per target minutes bin is fold-local mean observed exposure; empty
    training bins use existing contract representatives 0/59/89/90 explicitly.
    """

    def __init__(self, parameters: DisciplinaryParameters | None = None) -> None:
        self.parameters = parameters if parameters is not None else DisciplinaryParameters()
        self.as_of: datetime | None = None
        self.maximum_source_kickoff: datetime | None = None
        self.position_rates: dict[Position, tuple[float, float]] = {}
        self.player_totals: dict[tuple[int, Position], tuple[float, float, float]] = {}
        self.bin_exposure: tuple[float, float, float, float] = (0.0, 59.0, 89.0, 90.0)
        self.excluded_zero_minute_cards = 0

    def fit(
        self,
        history: Sequence[DisciplinaryObservation],
        *,
        as_of: datetime,
        excluded_target_gw: tuple[str, int],
    ) -> ExposurePooledDisciplinary:
        # A failed refit must not leave a previously fitted predictor usable.
        self.as_of = None
        self.position_rates = {}
        self.player_totals = {}
        _aware(as_of)
        totals: dict[Position, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
        players: dict[tuple[int, Position], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
        exposure: dict[int, list[int]] = defaultdict(list)
        seen: set[tuple[str, int, int]] = set()
        self.maximum_source_kickoff = None
        self.excluded_zero_minute_cards = 0
        for row in history:
            _aware(row.kickoff)
        for row in sorted(history, key=lambda r: (r.kickoff, r.season, r.fixture, r.code)):
            if (
                row.kickoff + timedelta(hours=6) >= as_of
                or (row.season, row.gw) == excluded_target_gw
            ):
                continue
            identity = row.season, row.fixture, row.code
            if identity in seen:
                raise ValueError("duplicate historical player-fixture")
            seen.add(identity)
            state = scored_card_state(row.yellow, row.red)
            if row.minutes is None or state is None:
                continue
            if type(row.minutes) is not int or row.minutes < 0 or row.minutes > 120:
                raise ValueError("invalid observed playing minutes")
            if row.minutes == 0:
                self.excluded_zero_minute_cards += int(state != 0)
                continue
            self.maximum_source_kickoff = row.kickoff
            for counts in (totals[row.position], players[row.code, row.position]):
                counts[0] += row.minutes
                counts[1] += int(state == 1)
                counts[2] += int(state == 2)
            bin_index = 1 if row.minutes < 60 else 2 if row.minutes < 90 else 3
            exposure[bin_index].append(row.minutes)
        params = self.parameters
        global_totals = [sum(values[k] for values in totals.values()) for k in range(3)]
        global_rates = tuple(
            (global_totals[k] + params.global_pseudocount)
            / (global_totals[0] + params.global_prior_minutes)
            for k in (1, 2)
        )
        self.position_rates = {}
        for position in Position:
            counts = totals[position]
            self.position_rates[position] = (
                (counts[1] + params.position_prior_minutes * global_rates[0])
                / (counts[0] + params.position_prior_minutes),
                (counts[2] + params.position_prior_minutes * global_rates[1])
                / (counts[0] + params.position_prior_minutes),
            )
        self.player_totals = {key: (v[0], v[1], v[2]) for key, v in players.items()}
        measured = [
            sum(exposure[b]) / len(exposure[b]) if exposure[b] else fallback
            for b, fallback in enumerate((0.0, 59.0, 89.0, 90.0))
        ]
        self.bin_exposure = measured[0], measured[1], measured[2], measured[3]
        self.as_of = as_of
        return self

    def predict(
        self, code: int, position: Position, *, position_only: bool = False
    ) -> ConditionalDisciplinary:
        if self.as_of is None:
            raise ValueError("fit prior history before predicting")
        yellow, red = self.position_rates[position]
        if not position_only:
            minutes, ys, rs = self.player_totals.get((code, position), (0.0, 0.0, 0.0))
            py = self.parameters.player_yellow_prior_minutes
            pr = self.parameters.player_red_prior_minutes
            yellow = (ys + py * yellow) / (minutes + py)
            red = (rs + pr * red) / (minutes + pr)
        total = yellow + red
        rows: list[CardPmf] = [NONE]
        for minutes in self.bin_exposure[1:]:
            any_card = -math.expm1(-total * minutes)
            rows.append((1 - any_card, any_card * yellow / total, any_card * red / total))
        return ConditionalDisciplinary((rows[0], rows[1], rows[2], rows[3]))
