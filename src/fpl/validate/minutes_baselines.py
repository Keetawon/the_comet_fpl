"""The four Stage B (player minutes) baselines frozen by `config/phase2_evaluation.yaml`.

This is the implementation slice for the four pre-registered Stage B baselines. No model is
fitted here and no walk-forward backtest is run: the slice takes a fold-local training window
(``history``) and a set of ``targets`` and produces, for each target, the same four-bin minutes
distribution each frozen baseline definition specifies. Every baseline uses the estimator
``raw_empirical_bin_frequency_count_divided_by_n`` -- raw ``count / n`` with NO additive
smoothing -- so a one-hot zero probability REMAINS zero and is salvaged only by the contract's
registered log-probability floor (applied at scoring time, not here).

Data-correctness invariants inherited from the contract (see AGENTS.md):

* Player identity is the stable ``code`` (1:1 with permanent identity). ``element_id`` /
  archive ``element`` are season-scoped and reassigned yearly, so the player baselines track
  ``code`` and never carry ``element_id``.
* Team identity is season-scoped: a bare ``team_id`` is never joined across seasons. The team
  baseline resolves the target row's season-qualified ``(season, team_id)`` to the stable
  ``team_code`` through a separate :class:`TeamCodeMap`, never from ``mart_dim_player.team_id``.
* The target record carries EXACTLY the nine safe proxy columns and no outcome -- ``minutes``
  is the label and lives only on history rows.

The four bins (keys, numeric ranges, and the 60-minute boundary) are read from
:class:`~fpl.config.Phase2EvaluationConfig` via :class:`MinuteBins`; nothing about the bin shape
is hardcoded here.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

from fpl.config import Phase2EvaluationConfig, Phase2OutputPolicy
from fpl.types import Position

# A four-bin minutes distribution over the contract's ordered bin keys. Probabilities are raw
# ``count / n`` (no smoothing); entries are non-negative and sum to 1.0 wherever one is returned.
type MinutesDistribution = tuple[float, float, float, float]

# The frozen ordered names of the four Stage B baselines, matching the contract's
# ``baselines.definitions`` order exactly. ``stage_b`` in the config is a (unordered) frozenset;
# the definitions tuple and this constant carry the order the report requires.
STAGE_B_BASELINE_ORDER: tuple[str, ...] = (
    "position_minutes_frequency",
    "last_observed_player_minutes",
    "trailing_5_player_minutes",
    "trailing_5_team_position_minutes",
)


# --------------------------------------------------------------------------------------
# Bin shape (read from the contract, never hardcoded)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MinuteBins:
    """The four ordered minute bins, read from the contract's ``output`` block.

    The bin keys and numeric ranges are config data; this object only holds them so the
    baselines never repeat a literal ``60`` or ``"60_89"``. The 60-minute boundary lives here as
    ``ranges[2]`` and is cross-checked against the downstream ruleset at config load time.
    """

    keys: tuple[str, ...]
    ranges: tuple[tuple[int, int | None], ...]

    @classmethod
    def from_output(cls, output: Phase2OutputPolicy) -> MinuteBins:
        return cls(
            keys=tuple(bin_.key for bin_ in output.bins),
            ranges=tuple((bin_.minutes_min, bin_.minutes_max) for bin_ in output.bins),
        )

    @classmethod
    def from_config(cls, config: Phase2EvaluationConfig) -> MinuteBins:
        return cls.from_output(config.output)

    def n_bins(self) -> int:
        return len(self.keys)

    def index_of(self, minutes: int) -> int:
        """Bin index for a minutes value. ``minutes_max is None`` means unbounded above.

        Raises if the value falls outside every configured bin (a negative value, against this
        contract); a value at or above the open-ended ``"90"`` tail folds into the last bin.
        """
        for index, (low, high) in enumerate(self.ranges):
            upper = math.inf if high is None else high
            if low <= minutes <= upper:
                return index
        raise ValueError(f"minutes {minutes} falls outside every configured minute bin")

    def one_hot(self, index: int) -> MinutesDistribution:
        """A one-bin distribution: all mass on ``index``. ``last_observed`` is this, at n=1."""
        masses = [0.0] * self.n_bins()
        masses[index] = 1.0
        # Cast rather than rebuild: the validated contract fixes four bins while this method
        # remains generic over n_bins(); the fixed-tuple alias records that contract invariant.
        return cast(MinutesDistribution, tuple(masses))


def _counts_to_distribution(counts: Sequence[int]) -> MinutesDistribution:
    """Raw ``count / n`` over the bins with NO smoothing. ``sum(counts)`` must be > 0."""
    total = sum(counts)
    if total <= 0:
        raise ValueError("cannot form a distribution from zero counts")
    return cast(MinutesDistribution, tuple(count / total for count in counts))


# --------------------------------------------------------------------------------------
# Stable team identity: season-qualified team_id -> stable team_code
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TeamCodeMap:
    """Resolves a row's season-qualified ``(season, team_id)`` to the stable ``team_code``.

    ``team_id`` is reassigned every summer and recurs (id 10 is Leeds, Leicester, Fulham,
    Ipswich, then Fulham again), so it must NEVER be joined across seasons. The map is the only
    path from a target/history row's season-scoped ``team_id`` to the cross-season ``team_code``
    the team baseline needs. Carrying it as a separate object keeps ``team_code`` out of the
    target record's frozen proxy column set.
    """

    _entries: dict[tuple[str, int], int] = field(default_factory=dict)

    @classmethod
    def from_pairs(cls, pairs: Iterable[tuple[str, int, int]]) -> TeamCodeMap:
        """Build from ``(season, team_id, team_code)`` triples, rejecting a duplicated key."""
        entries: dict[tuple[str, int], int] = {}
        for season, team_id, team_code in pairs:
            key = (season, team_id)
            if key in entries:
                raise ValueError(
                    f"duplicate team_code mapping for ({season!r}, {team_id}): "
                    f"{entries[key]} and {team_code}"
                )
            entries[key] = team_code
        return cls(entries)

    def code(self, season: str, team_id: int) -> int:
        try:
            return self._entries[(season, team_id)]
        except KeyError:
            raise ValueError(
                f"no team_code mapping for season-qualified team_id ({season!r}, {team_id}); "
                "every target and history row must resolve"
            ) from None

    def __len__(self) -> int:
        return len(self._entries)


# --------------------------------------------------------------------------------------
# Immutable typed records
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TargetRow:
    """One player-fixture the minutes model predicts. Carries EXACTLY the nine safe proxy
    columns and NO outcome.

    ``code`` is the stable cross-season player key; ``team_id`` is season-qualified and resolves
    to ``team_code`` only through :class:`TeamCodeMap`. ``minutes`` (the label) is deliberately
    absent -- it lives outside the model-facing projection. The exact column set is asserted
    against the contract in the tests.
    """

    season: str
    gw: int
    fixture: int
    kickoff_time: datetime
    code: int
    position: Position
    team_id: int
    opponent_team_id: int
    was_home: bool


@dataclass(frozen=True, slots=True)
class HistoryRow(TargetRow):
    """A prior eligible player-fixture row: a :class:`TargetRow` plus the ``minutes`` label.

    ``minutes`` is non-NULL and in range (validated), and is the only outcome column any Stage B
    baseline reads. It is present here and absent on :class:`TargetRow` by construction.
    """

    minutes: int


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------


def _require_aware_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be a timezone-aware datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware (UTC-compatible), got a naive datetime")
    return value.astimezone(UTC)


def _require_position(value: object, row: TargetRow) -> None:
    """Positions are validated, not just annotated.

    ``TargetRow.position`` is typed :class:`Position`, but a plain dataclass does not enforce its
    annotation at construction, so a raw label (``"AM"`` the manager element, ``"GKP"``, or a typo)
    would otherwise pass through unvalidated. Manager elements are excluded from the player
    population, so a non-:class:`Position` value is rejected here rather than fed into a rate.
    """
    if not isinstance(value, Position):
        raise TypeError(
            f"position must be a Position, got {value!r} for "
            f"(season, code, fixture)=({row.season!r}, {row.code}, {row.fixture})"
        )


def _check_unique_key(rows: Sequence[TargetRow], label: str) -> None:
    seen: set[tuple[str, int, int]] = set()
    for row in rows:
        key = (row.season, row.code, row.fixture)
        if key in seen:
            raise ValueError(
                f"duplicate {label} grain (season, code, fixture) {key}; "
                "player-fixture grain must be unique"
            )
        seen.add(key)


def validate_minutes_inputs(
    history: Sequence[HistoryRow],
    targets: Sequence[TargetRow],
    *,
    as_of: datetime,
    team_codes: TeamCodeMap,
    bins: MinuteBins,
) -> tuple[tuple[HistoryRow, ...], tuple[TargetRow, ...]]:
    """Validate the fold-local inputs before any baseline is fitted; fail closed on every
    contract invariant.

    Checks: timezone-aware UTC-compatible ``kickoff_time`` / ``as_of``; the cutoff
    (``kickoff_time < as_of`` for every history row -- observed results only); unique
    ``(season, code, fixture)`` grain in history and targets; non-null, integer, in-bin-range
    ``minutes`` on history; valid :class:`Position`; and that every row's season-qualified
    ``team_id`` resolves to a ``team_code``.

    Returns the inputs as tuples so downstream code handles immutable sequences.
    """
    as_of_utc = _require_aware_utc(as_of, "as_of")
    history_tuple = tuple(history)
    targets_tuple = tuple(targets)
    _check_unique_key(history_tuple, "history")
    _check_unique_key(targets_tuple, "target")

    for history_row in history_tuple:
        _require_position(history_row.position, history_row)
        kickoff_utc = _require_aware_utc(history_row.kickoff_time, "history kickoff_time")
        if kickoff_utc >= as_of_utc:
            raise ValueError(
                f"history row (season, code, fixture)=({history_row.season!r}, {history_row.code}, "
                f"{history_row.fixture}) is not observed before cutoff as_of: kickoff_time "
                f"{history_row.kickoff_time!r} >= as_of {as_of!r}"
            )
        if isinstance(history_row.minutes, bool) or not isinstance(history_row.minutes, int):
            raise TypeError(
                f"history minutes must be a non-null int, got {history_row.minutes!r} for "
                f"({history_row.season!r}, {history_row.code}, {history_row.fixture})"
            )
        bins.index_of(history_row.minutes)  # raises if outside every bin (e.g. negative)
        team_codes.code(history_row.season, history_row.team_id)  # mapping must resolve

    for target_row in targets_tuple:
        _require_position(target_row.position, target_row)
        kickoff_utc = _require_aware_utc(target_row.kickoff_time, "target kickoff_time")
        # A target at or after the cutoff is the prediction case; equality is valid (a fixture
        # kicking off exactly at as_of is the first target). A target already in the past would be
        # an observed result misrouted as a prediction.
        if kickoff_utc < as_of_utc:
            raise ValueError(
                f"target row (season, code, fixture)=({target_row.season!r}, {target_row.code}, "
                f"{target_row.fixture}) is already observed before cutoff as_of: kickoff_time "
                f"{target_row.kickoff_time!r} < as_of {as_of!r}"
            )
        team_codes.code(target_row.season, target_row.team_id)  # mapping must resolve

    return history_tuple, targets_tuple


# --------------------------------------------------------------------------------------
# Recency ordering and the shared positional prior (the fallback engine)
# --------------------------------------------------------------------------------------


def _recent_first(rows: Iterable[HistoryRow]) -> list[HistoryRow]:
    """Most-recent-first: ``kickoff_time`` DESC, then ``season`` DESC, then ``fixture`` DESC.

    The contract fixes this order wherever an order applies. The grain ``(season, code,
    fixture)`` is unique within a player's history (validated), so the sort is total and input
    order cannot change the result.
    """
    return sorted(rows, key=lambda r: (r.kickoff_time, r.season, r.fixture), reverse=True)


@dataclass(frozen=True, slots=True)
class PositionPrior:
    """The ``position_minutes_frequency`` baseline and every other baseline's fallback.

    Holds raw per-bin counts (not distributions) at each position and across all positions, so
    the fallback chain is exact: position rows, else all-position rows, else fail closed. Raw
    ``count / n`` with no smoothing is applied only when a distribution is requested.
    """

    by_position: dict[Position, tuple[int, ...]]
    all_positions: tuple[int, ...]

    @classmethod
    def from_history(cls, history: Sequence[HistoryRow], bins: MinuteBins) -> PositionPrior:
        n = bins.n_bins()
        all_counts = [0] * n
        per_position: dict[Position, list[int]] = {}
        for row in history:
            index = bins.index_of(row.minutes)
            all_counts[index] += 1
            per_position.setdefault(row.position, [0] * n)[index] += 1
        return cls(
            by_position={position: tuple(counts) for position, counts in per_position.items()},
            all_positions=tuple(all_counts),
        )

    def distribution_for(self, position: Position) -> MinutesDistribution:
        """Position rows -> raw frequency; else all-position rows; else fail closed.

        An empty all-position prior means there is no training data at all, which is a
        configuration error in a fold, not a prediction -- so it raises rather than inventing a
        uniform distribution.
        """
        counts = self.by_position.get(position)
        if counts is not None and sum(counts) > 0:
            return _counts_to_distribution(counts)
        if sum(self.all_positions) > 0:
            return _counts_to_distribution(self.all_positions)
        raise ValueError(
            "empty all-position prior: no eligible history rows to estimate a minutes "
            "distribution from"
        )


def _empirical_counts(rows: Sequence[HistoryRow], bins: MinuteBins) -> tuple[int, ...]:
    counts = [0] * bins.n_bins()
    for row in rows:
        counts[bins.index_of(row.minutes)] += 1
    return tuple(counts)


# --------------------------------------------------------------------------------------
# Fitted state shared by the four baselines
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Fitted:
    """Fold-local precomputed structures shared by every baseline.

    Groupings are recent-first (``kickoff_time`` then ``season`` then ``fixture``), so the
    ``last_observed`` / ``trailing_5`` lookups take a prefix and the team baseline dedupes
    fixtures in recency order. Building it once keeps the four baselines from recomputing the
    same group_by, and sorting here (not an unordered group_by) is what makes a pre-registered
    evaluation reproducible.
    """

    prior: PositionPrior
    by_code: dict[int, tuple[HistoryRow, ...]]
    by_team_code: dict[int, tuple[HistoryRow, ...]]
    bins: MinuteBins
    as_of: datetime
    team_codes: TeamCodeMap

    @classmethod
    def fit(
        cls,
        history: Sequence[HistoryRow],
        *,
        as_of: datetime,
        team_codes: TeamCodeMap,
        bins: MinuteBins,
    ) -> _Fitted:
        ordered = _recent_first(history)
        by_code: dict[int, list[HistoryRow]] = {}
        by_team_code: dict[int, list[HistoryRow]] = {}
        for row in ordered:
            by_code.setdefault(row.code, []).append(row)
            club = team_codes.code(row.season, row.team_id)
            by_team_code.setdefault(club, []).append(row)
        return cls(
            prior=PositionPrior.from_history(history, bins),
            by_code={code: tuple(rows) for code, rows in by_code.items()},
            by_team_code={code: tuple(rows) for code, rows in by_team_code.items()},
            bins=bins,
            as_of=as_of,
            team_codes=team_codes,
        )


# --------------------------------------------------------------------------------------
# The four baselines
# --------------------------------------------------------------------------------------


class MinutesBaseline(ABC):
    """One frozen Stage B baseline: fit on a validated history, predict one target."""

    name: str

    @abstractmethod
    def predict(self, target: TargetRow) -> MinutesDistribution: ...


class PositionMinutesFrequency(MinutesBaseline):
    """All prior eligible rows at the target position -> raw ``count / n``.

    Fallback: if that position has no rows, the unsmoothed all-position prior. An empty
    all-position prior fails closed (see :meth:`PositionPrior.distribution_for`). This is the
    transparent positional floor and the cold-start fallback for the other three.
    """

    name = "position_minutes_frequency"

    def __init__(self, fitted: _Fitted) -> None:
        self._fitted = fitted

    def predict(self, target: TargetRow) -> MinutesDistribution:
        return self._fitted.prior.distribution_for(target.position)


class _CodeFallbackBaseline(MinutesBaseline):
    """Shared by the two player-history baselines: identity is stable ``code``, fallback is
    :class:`PositionMinutesFrequency` when the player has no usable prior rows."""

    def __init__(self, fitted: _Fitted) -> None:
        self._fitted = fitted

    def _position_fallback(self, target: TargetRow) -> MinutesDistribution:
        return self._fitted.prior.distribution_for(target.position)


class LastObservedPlayerMinutes(_CodeFallbackBaseline):
    """One-hot distribution at the most recent prior player-fixture bin (identity = ``code``).

    Population is the single most recent prior row; the estimator at n=1 is a one-hot. Fallback
    if no prior row = :class:`PositionMinutesFrequency`.
    """

    name = "last_observed_player_minutes"

    def predict(self, target: TargetRow) -> MinutesDistribution:
        rows = self._fitted.by_code.get(target.code)
        if rows:
            return self._fitted.bins.one_hot(self._fitted.bins.index_of(rows[0].minutes))
        return self._position_fallback(target)


class Trailing5PlayerMinutes(_CodeFallbackBaseline):
    """Up to five most recent prior player-fixture rows INCLUDING zero-minute rows (identity =
    ``code``) -> raw ``count / n``. Fallback if none = :class:`PositionMinutesFrequency`."""

    name = "trailing_5_player_minutes"

    def predict(self, target: TargetRow) -> MinutesDistribution:
        rows = self._fitted.by_code.get(target.code)
        if rows:
            window = rows[:5]
            return _counts_to_distribution(_empirical_counts(window, self._fitted.bins))
        return self._position_fallback(target)


class Trailing5TeamPositionMinutes(MinutesBaseline):
    """Target club's five most recent COMPLETED fixtures before cutoff, then all prior eligible
    rows at the TARGET position in those fixtures -> raw ``count / n``.

    The club is resolved from the target row's season-qualified ``team_id`` to the stable
    ``team_code`` (never a bare ``team_id`` join, never ``mart_dim_player.team_id``). Fallback
    if none = :class:`PositionMinutesFrequency`.
    """

    name = "trailing_5_team_position_minutes"

    def __init__(self, fitted: _Fitted) -> None:
        self._fitted = fitted

    def _recent_distinct_fixture_keys(
        self, club_rows: Sequence[HistoryRow], *, window: int
    ) -> set[tuple[str, int]]:
        """The ``(season, fixture)`` keys of the club's ``window`` most recent completed
        fixtures (``kickoff_time < as_of``), distinct."""
        selected: set[tuple[str, int]] = set()
        for row in club_rows:  # already recent-first
            if row.kickoff_time.astimezone(UTC) >= self._fitted.as_of:
                continue  # not completed before cutoff (defence-in-depth; history is pre-cutoff)
            key = (row.season, row.fixture)
            if key in selected:
                continue
            selected.add(key)
            if len(selected) >= window:
                break
        return selected

    def predict(self, target: TargetRow) -> MinutesDistribution:
        team_code = self._fitted.team_codes.code(target.season, target.team_id)
        club_rows = self._fitted.by_team_code.get(team_code, ())
        fixture_keys = self._recent_distinct_fixture_keys(club_rows, window=5)
        if fixture_keys:
            selected = [
                row
                for row in club_rows
                if (row.season, row.fixture) in fixture_keys and row.position == target.position
            ]
            if selected:
                return _counts_to_distribution(_empirical_counts(selected, self._fitted.bins))
        return self._fitted.prior.distribution_for(target.position)


def build_minutes_baselines(
    history: Sequence[HistoryRow],
    *,
    as_of: datetime,
    team_codes: TeamCodeMap,
    bins: MinuteBins,
) -> list[MinutesBaseline]:
    """Fit and return the four Stage B baselines in the contract's frozen order.

    Assumes the inputs have been validated by :func:`validate_minutes_inputs` (or are trusted);
    it does not re-validate.
    """
    fitted = _Fitted.fit(history, as_of=as_of, team_codes=team_codes, bins=bins)
    return [
        PositionMinutesFrequency(fitted),
        LastObservedPlayerMinutes(fitted),
        Trailing5PlayerMinutes(fitted),
        Trailing5TeamPositionMinutes(fitted),
    ]


def baseline_names() -> tuple[str, ...]:
    """The ordered names of the four baselines this slice builds, for the contract-set test."""
    return STAGE_B_BASELINE_ORDER
