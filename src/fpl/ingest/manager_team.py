"""Auditable public-manager team capture for the current FPL season.

The public picks endpoint exposes the selected element ids and bank, but (as live-verified
for 2026/27) it exposes neither purchase nor selling prices. This module therefore rebuilds
the permanent ownership ledger from a committed deadline bootstrap plus the entry's public
transfer history. It never guesses a missing price or identity.

All live endpoints are fetched before a capture can be serialized. The returned capture is
canonical, immutable, provenance-bearing, and suitable as the input boundary for a manager
transfer plan. It contains no authenticated/private FPL data.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from fpl.config import load_sources, repo_root
from fpl.ingest.fpl_api import (
    BootstrapElement,
    BootstrapEvent,
    BootstrapStatic,
    FplApiClient,
    ManagerChip,
    ManagerEntry,
    ManagerEventPicks,
    ManagerHistory,
    ManagerHistoryRow,
    ManagerTransfer,
)
from fpl.ingest.player_registry import (
    PlayerRegistryError,
    selectable_player_registry_sha256,
)

MANAGER_CAPTURE_SCHEMA: Final[str] = "fpl.manager-team-capture"
MANAGER_CAPTURE_SCHEMA_VERSION: Final[int] = 2
MANAGER_CAPTURE_STATUS: Final[str] = "development_only_public_manager_import"
FREE_TRANSFER_SOURCE: Final[str] = (
    "public_history_replay_official_2026_27_one_grant_cap_five_wildcard_freehit_preserve_prior_bank"
)
_POSITION: Final[dict[int, Literal["GK", "DEF", "MID", "FWD"]]] = {
    1: "GK",
    2: "DEF",
    3: "MID",
    4: "FWD",
}
_POSITION_QUOTA: Final[dict[str, int]] = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
_CHIP_WILDCARD: Final[frozenset[str]] = frozenset({"wildcard"})
_CHIP_FREE_HIT: Final[frozenset[str]] = frozenset({"freehit"})
_CHIPS_PRESERVING_PRIOR_BANK: Final[frozenset[str]] = _CHIP_WILDCARD | _CHIP_FREE_HIT


class ManagerCaptureErrorCode(StrEnum):
    """Machine-readable fail-closed diagnoses for the supported import boundary."""

    INVALID_MANAGER = "invalid_manager"
    NO_NEXT_EVENT = "no_next_event"
    NO_REVEALED_PICKS = "no_revealed_picks"
    EVENT_TIMELINE_MISMATCH = "event_timeline_mismatch"
    DEADLINE_SNAPSHOT_MISSING = "deadline_snapshot_missing"
    DEADLINE_SNAPSHOT_INVALID = "deadline_snapshot_invalid"
    ELEMENT_MAPPING_MISSING = "element_mapping_missing"
    PRICE_MISSING = "price_missing"
    PUBLIC_PRICE_PROVENANCE_UNAVAILABLE = "public_price_provenance_unavailable"
    TRANSFER_REPLAY_MISMATCH = "transfer_replay_mismatch"
    FREE_TRANSFER_REPLAY_MISMATCH = "free_transfer_replay_mismatch"
    ACTIVE_PLANNING_CHIP = "active_planning_chip"
    ILLEGAL_SQUAD = "illegal_squad"
    CAPTURE_INVALID = "capture_invalid"


class ManagerCaptureError(ValueError):
    """A manager capture is incomplete or cannot be reconstructed without guessing."""

    def __init__(self, code: ManagerCaptureErrorCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")


class ManagerCaptureExistsError(ManagerCaptureError):
    """Refused to overwrite an existing immutable manager capture."""

    def __init__(self, path: Path) -> None:
        super().__init__(
            ManagerCaptureErrorCode.CAPTURE_INVALID,
            f"refusing to overwrite existing immutable manager capture at {path}",
        )


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class ManagerTransferReplayRules(_Frozen):
    """The exact 2026/27 free-transfer rules used by the public-history replay."""

    free_transfer_per_event: Literal[1] = 1
    free_transfer_bank_cap: Literal[5] = 5
    hit_cost_points: Literal[4] = 4


class ManagerCaptureCompleteness(_Frozen):
    status: Literal["complete"] = "complete"
    supported_scope: Literal[
        "current_season_with_committed_start_deadline_snapshot_and_public_transfer_history"
    ] = "current_season_with_committed_start_deadline_snapshot_and_public_transfer_history"
    latest_free_hit_picks_comparable_to_permanent_squad: bool


class ManagerChipRecord(_Frozen):
    name: str
    event: int = Field(gt=0)
    played_at: datetime


class ManagerSquadPlayer(_Frozen):
    """One normalized current holding keyed by stable FPL player code."""

    element: int = Field(gt=0)
    code: int = Field(gt=0)
    web_name: str
    position: Literal["GK", "DEF", "MID", "FWD"]
    team_id: int = Field(gt=0)
    now_cost: int = Field(gt=0)
    purchase_price: int = Field(gt=0)
    selling_price: int = Field(gt=0)


class ManagerCaptureProvenance(_Frozen):
    current_bootstrap_sha256: str
    selectable_player_registry_sha256: str
    entry_sha256: str
    latest_picks_sha256: str
    start_picks_sha256: str
    transfers_sha256: str
    history_sha256: str
    deadline_snapshot_capture_id: str
    deadline_snapshot_captured_at: datetime
    deadline_snapshot_relative_path: str
    deadline_snapshot_manifest_sha256: str
    deadline_snapshot_bootstrap_archive_sha256: str
    deadline_snapshot_bootstrap_payload_sha256: str

    @field_validator(
        "current_bootstrap_sha256",
        "selectable_player_registry_sha256",
        "entry_sha256",
        "latest_picks_sha256",
        "start_picks_sha256",
        "transfers_sha256",
        "history_sha256",
        "deadline_snapshot_manifest_sha256",
        "deadline_snapshot_bootstrap_archive_sha256",
        "deadline_snapshot_bootstrap_payload_sha256",
    )
    @classmethod
    def _sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        return value


class ManagerTeamCapture(_Frozen):
    """Complete current manager state consumed by transfer optimization."""

    artifact_schema: Literal["fpl.manager-team-capture"] = Field(
        default="fpl.manager-team-capture", alias="schema"
    )
    schema_version: Literal[2] = 2
    status: Literal["development_only_public_manager_import"] = (
        "development_only_public_manager_import"
    )
    capture_id: str
    captured_at: datetime
    season: str
    manager_id: int = Field(gt=0)
    manager_name: str
    player_first_name: str
    player_last_name: str
    started_event: int = Field(gt=0)
    picks_event: int = Field(gt=0)
    planning_event: int = Field(gt=0)
    squad: tuple[ManagerSquadPlayer, ...]
    bank_tenths: int = Field(ge=0)
    squad_selling_value_tenths: int = Field(gt=0)
    available_budget_tenths: int = Field(gt=0)
    free_transfers_available: int = Field(ge=0, le=5)
    free_transfers_source: Literal[
        "public_history_replay_official_2026_27_one_grant_cap_five_"
        "wildcard_freehit_preserve_prior_bank"
    ] = (
        "public_history_replay_official_2026_27_one_grant_cap_five_"
        "wildcard_freehit_preserve_prior_bank"
    )
    existing_hit_points: int = Field(ge=0)
    historical_hit_points: int = Field(ge=0)
    post_picks_transfer_count: int = Field(ge=0)
    chips: tuple[ManagerChipRecord, ...]
    transfer_rules: ManagerTransferReplayRules
    completeness: ManagerCaptureCompleteness
    provenance: ManagerCaptureProvenance

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.planning_event != self.picks_event + 1:
            raise ValueError("planning_event must immediately follow picks_event")
        if len(self.squad) != 15:
            raise ValueError("manager capture must contain exactly 15 players")
        codes = tuple(player.code for player in self.squad)
        if codes != tuple(sorted(set(codes))):
            raise ValueError("manager capture squad must be sorted by unique stable code")
        expected_value = sum(player.selling_price for player in self.squad)
        if self.squad_selling_value_tenths != expected_value:
            raise ValueError("squad selling value does not reconcile to player selling prices")
        if self.available_budget_tenths != expected_value + self.bank_tenths:
            raise ValueError("available budget must equal squad selling value plus bank")
        return self


@dataclass(frozen=True, slots=True)
class ManagerApiInputs:
    """All public endpoint payloads fetched before reconstruction or publication."""

    raw_bootstrap: Any
    bootstrap: BootstrapStatic
    raw_entry: Any
    entry: ManagerEntry
    raw_latest_picks: Any
    latest_picks: ManagerEventPicks
    raw_start_picks: Any
    start_picks: ManagerEventPicks
    raw_transfers: Any
    transfers: tuple[ManagerTransfer, ...]
    raw_history: Any
    history: ManagerHistory
    planning_event: BootstrapEvent


@dataclass(frozen=True, slots=True)
class _DeadlineSnapshot:
    directory: Path
    captured_at: datetime
    capture_id: str
    manifest_sha256: str
    bootstrap_archive_sha256: str
    bootstrap_payload_sha256: str
    bootstrap: BootstrapStatic


@dataclass(frozen=True, slots=True)
class _FreeTransferState:
    available: int
    existing_hit_points: int
    historical_hit_points: int


def _aware_utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.CAPTURE_INVALID, f"{label} must be timezone-aware"
        )
    return value.astimezone(UTC)


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _normalise_chip(name: str | None) -> str | None:
    if name is None:
        return None
    return "".join(character for character in name.lower() if character.isalnum())


def _event_by_id(bootstrap: BootstrapStatic, event: int) -> BootstrapEvent:
    matches = [item for item in bootstrap.events if item.id == event]
    if len(matches) != 1:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.EVENT_TIMELINE_MISMATCH,
            f"bootstrap contains {len(matches)} rows for event {event}",
        )
    return matches[0]


def fetch_manager_team_inputs(
    client: FplApiClient,
    manager_id: int,
    *,
    captured_at: datetime,
) -> ManagerApiInputs:
    """Fetch and type every required public endpoint, without writing anything."""
    if manager_id <= 0:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.INVALID_MANAGER, "manager_id must be positive"
        )
    known_at = _aware_utc(captured_at, label="captured_at")
    raw_bootstrap = client.raw_bootstrap_static()
    try:
        bootstrap = BootstrapStatic.model_validate(raw_bootstrap)
    except ValidationError as exc:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.CAPTURE_INVALID,
            f"current bootstrap payload is malformed: {exc}",
        ) from exc
    raw_entry = client.raw_manager_entry(manager_id)
    try:
        entry = ManagerEntry.model_validate(raw_entry)
    except ValidationError as exc:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.INVALID_MANAGER,
            f"manager entry payload is malformed: {exc}",
        ) from exc
    if entry.id != manager_id:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.INVALID_MANAGER,
            f"requested manager {manager_id}, endpoint returned {entry.id}",
        )

    planning_event = bootstrap.next_event()
    if planning_event is None or planning_event.deadline_time is None:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.NO_NEXT_EVENT,
            "bootstrap does not identify a next event with a deadline",
        )
    picks_event = _event_by_id(bootstrap, entry.current_event)
    if (
        picks_event.deadline_time is None
        or _aware_utc(picks_event.deadline_time, label="picks deadline") > known_at
    ):
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.NO_REVEALED_PICKS,
            f"event {entry.current_event} picks were not revealed by capture time",
        )
    if planning_event.id != entry.current_event + 1:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.EVENT_TIMELINE_MISMATCH,
            f"next event {planning_event.id} does not follow revealed picks event "
            f"{entry.current_event}",
        )
    if not 1 <= entry.started_event <= entry.current_event:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.EVENT_TIMELINE_MISMATCH,
            f"started_event {entry.started_event} is outside the revealed season",
        )
    _event_by_id(bootstrap, entry.started_event)
    if entry.started_event != 1:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.PUBLIC_PRICE_PROVENANCE_UNAVAILABLE,
            "public manager endpoints do not expose acquisition prices; using the "
            f"GW{entry.started_event} deadline price would be unsafe after earlier price changes",
        )

    raw_latest_picks = client.raw_manager_event_picks(manager_id, entry.current_event)
    if entry.started_event == entry.current_event:
        raw_start_picks = raw_latest_picks
    else:
        raw_start_picks = client.raw_manager_event_picks(manager_id, entry.started_event)
    raw_transfers = client.raw_manager_transfers(manager_id)
    raw_history = client.raw_manager_history(manager_id)

    if not isinstance(raw_transfers, list):
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.TRANSFER_REPLAY_MISMATCH,
            "manager transfers endpoint did not return a list",
        )
    try:
        latest_picks = ManagerEventPicks.model_validate(raw_latest_picks)
        start_picks = ManagerEventPicks.model_validate(raw_start_picks)
        transfers = tuple(ManagerTransfer.model_validate(row) for row in raw_transfers)
        history = ManagerHistory.model_validate(raw_history)
    except ValidationError as exc:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.CAPTURE_INVALID,
            f"a public manager payload is malformed: {exc}",
        ) from exc
    if not latest_picks.picks or not start_picks.picks:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.NO_REVEALED_PICKS, "a required picks payload is empty"
        )
    if latest_picks.entry_history.event != entry.current_event:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.EVENT_TIMELINE_MISMATCH,
            "latest picks entry_history event does not match the entry current_event",
        )
    if start_picks.entry_history.event != entry.started_event:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.EVENT_TIMELINE_MISMATCH,
            "start picks entry_history event does not match the entry started_event",
        )
    return ManagerApiInputs(
        raw_bootstrap=raw_bootstrap,
        bootstrap=bootstrap,
        raw_entry=raw_entry,
        entry=entry,
        raw_latest_picks=raw_latest_picks,
        latest_picks=latest_picks,
        raw_start_picks=raw_start_picks,
        start_picks=start_picks,
        raw_transfers=raw_transfers,
        transfers=transfers,
        raw_history=raw_history,
        history=history,
        planning_event=planning_event,
    )


def _snapshot_timestamp(manifest_path: Path) -> datetime:
    try:
        payload = json.loads(manifest_path.read_bytes())
        if str(payload.get("schema_version", "1")) != "1":
            raise ValueError("unsupported schema_version")
        value = datetime.fromisoformat(str(payload["captured_at"]).replace("Z", "+00:00"))
        return _aware_utc(value, label=f"{manifest_path} captured_at")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.DEADLINE_SNAPSHOT_INVALID,
            f"invalid daily snapshot manifest {manifest_path}: {exc}",
        ) from exc


def _verify_deadline_snapshot(directory: Path, *, snapshots_root: Path) -> _DeadlineSnapshot:
    manifest_path = directory / "manifest.json"
    checksum_path = directory / "SHA256SUMS"
    try:
        relative = directory.relative_to(snapshots_root)
        relative_posix = PurePosixPath(relative.as_posix())
        manifest_raw = manifest_path.read_bytes()
        checksum_raw = checksum_path.read_bytes()
        captured_at = _snapshot_timestamp(manifest_path)
        seen: set[str] = set()
        declared_hashes: dict[str, str] = {}
        for line in checksum_raw.decode("utf-8").splitlines():
            expected, separator, declared = line.partition("  ")
            declared_path = PurePosixPath(declared)
            filename = declared_path.name
            allowed_declarations = {
                filename,
                (relative_posix / filename).as_posix(),
                (PurePosixPath(snapshots_root.name) / relative_posix / filename).as_posix(),
            }
            if (
                not separator
                or len(expected) != 64
                or any(character not in "0123456789abcdef" for character in expected)
                or not filename
                or declared not in allowed_declarations
                or filename in seen
            ):
                raise ValueError(f"invalid checksum inventory line {line!r}")
            path = directory / filename
            if not path.is_file():
                raise ValueError(f"declared payload is missing: {filename}")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"checksum mismatch for {filename}")
            seen.add(filename)
            declared_hashes[filename] = expected
        archives = {path.name for path in directory.glob("*.gz")}
        if not seen or seen != archives:
            raise ValueError(
                f"checksum inventory differs from archives: checked={sorted(seen)}, "
                f"archives={sorted(archives)}"
            )
        if "fixtures.json.gz" not in declared_hashes:
            raise ValueError("fixtures.json.gz is absent from the daily snapshot")
        bootstrap_path = directory / "bootstrap-static.json.gz"
        if bootstrap_path.name not in declared_hashes:
            raise ValueError("bootstrap-static.json.gz is absent from checksum inventory")
        with gzip.open(bootstrap_path, "rt", encoding="utf-8") as stream:
            raw_bootstrap = json.load(stream)
        bootstrap = BootstrapStatic.model_validate(raw_bootstrap)
    except ManagerCaptureError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.DEADLINE_SNAPSHOT_INVALID,
            f"invalid committed daily snapshot {directory}: {exc}",
        ) from exc
    return _DeadlineSnapshot(
        directory=Path(relative),
        captured_at=captured_at,
        capture_id="file-" + hashlib.sha256(manifest_raw + checksum_raw).hexdigest(),
        manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
        bootstrap_archive_sha256=declared_hashes["bootstrap-static.json.gz"],
        bootstrap_payload_sha256=_payload_sha256(raw_bootstrap),
        bootstrap=bootstrap,
    )


def _latest_deadline_snapshot(
    snapshots_root: Path,
    *,
    deadline: datetime,
) -> _DeadlineSnapshot:
    cutoff = _aware_utc(deadline, label="start-event deadline")
    daily_root = snapshots_root / "daily"
    candidates: list[tuple[datetime, Path]] = []
    if daily_root.is_dir():
        for manifest in daily_root.glob("*/*/manifest.json"):
            captured_at = _snapshot_timestamp(manifest)
            if captured_at <= cutoff:
                candidates.append((captured_at, manifest.parent))
    if not candidates:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.DEADLINE_SNAPSHOT_MISSING,
            f"no committed daily snapshot exists at or before {cutoff.isoformat()}",
        )
    _, directory = max(candidates, key=lambda item: (item[0], item[1].as_posix()))
    return _verify_deadline_snapshot(directory, snapshots_root=snapshots_root)


def _element_indexes(
    bootstrap: BootstrapStatic,
) -> tuple[dict[int, BootstrapElement], dict[int, BootstrapElement]]:
    by_element: dict[int, BootstrapElement] = {}
    by_code: dict[int, BootstrapElement] = {}
    for player in bootstrap.elements:
        if player.element_type not in _POSITION:
            continue
        if player.id in by_element or player.code in by_code:
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.ELEMENT_MAPPING_MISSING,
                "bootstrap player element ids and stable codes must be unique",
            )
        by_element[player.id] = player
        by_code[player.code] = player
    return by_element, by_code


def _pick_codes(
    picks: ManagerEventPicks,
    *,
    by_element: Mapping[int, BootstrapElement],
    label: str,
) -> tuple[int, ...]:
    if len(picks.picks) != 15:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.ILLEGAL_SQUAD,
            f"{label} contains {len(picks.picks)} picks instead of 15",
        )
    positions = tuple(sorted(pick.position for pick in picks.picks))
    if positions != tuple(range(1, 16)):
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.ILLEGAL_SQUAD,
            f"{label} pick positions must be exactly 1..15",
        )
    element_ids = tuple(pick.element for pick in picks.picks)
    if len(set(element_ids)) != 15:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.ILLEGAL_SQUAD, f"{label} contains duplicate players"
        )
    codes: list[int] = []
    for element in element_ids:
        player = by_element.get(element)
        if player is None:
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.ELEMENT_MAPPING_MISSING,
                f"{label} element {element} is absent from its bootstrap",
            )
        codes.append(player.code)
    return tuple(codes)


def _chips_by_event(history: ManagerHistory, *, captured_at: datetime) -> dict[int, ManagerChip]:
    chips: dict[int, ManagerChip] = {}
    for chip in history.chips:
        if _aware_utc(chip.time, label="chip time") > captured_at:
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.EVENT_TIMELINE_MISMATCH,
                f"chip {chip.name!r} is timestamped after the capture",
            )
        if chip.event in chips:
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.EVENT_TIMELINE_MISMATCH,
                f"multiple chips are recorded for event {chip.event}",
            )
        chips[chip.event] = chip
    return chips


def _history_by_event(
    history: ManagerHistory,
    *,
    start_event: int,
    picks_event: int,
) -> dict[int, ManagerHistoryRow]:
    rows: dict[int, ManagerHistoryRow] = {}
    for row in history.current:
        if row.event in rows:
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.FREE_TRANSFER_REPLAY_MISMATCH,
                f"duplicate history row for event {row.event}",
            )
        rows[row.event] = row
    required = set(range(start_event, picks_event + 1))
    missing = sorted(required - rows.keys())
    if missing:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.FREE_TRANSFER_REPLAY_MISMATCH,
            f"history is missing revealed event rows {missing}",
        )
    return rows


def _transfer_records_by_event(
    transfers: tuple[ManagerTransfer, ...],
    *,
    manager_id: int,
    start_event: int,
    planning_event: int,
    captured_at: datetime,
) -> dict[int, tuple[ManagerTransfer, ...]]:
    grouped: dict[int, list[ManagerTransfer]] = {}
    seen: set[tuple[int, int, int, datetime]] = set()
    for transfer in transfers:
        transfer_time = _aware_utc(transfer.time, label="transfer time")
        if transfer.entry != manager_id:
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.TRANSFER_REPLAY_MISMATCH,
                f"transfer belongs to entry {transfer.entry}, expected {manager_id}",
            )
        if transfer_time > captured_at:
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.EVENT_TIMELINE_MISMATCH,
                "transfer history contains a transfer timestamped after the capture",
            )
        if transfer.event < start_event or transfer.event > planning_event:
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.EVENT_TIMELINE_MISMATCH,
                f"transfer event {transfer.event} is outside supported replay "
                f"{start_event}..{planning_event}",
            )
        key = (transfer.event, transfer.element_out, transfer.element_in, transfer_time)
        if key in seen:
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.TRANSFER_REPLAY_MISMATCH,
                f"duplicate transfer record in event {transfer.event}",
            )
        seen.add(key)
        grouped.setdefault(transfer.event, []).append(transfer)
    return {
        event: tuple(
            sorted(
                rows,
                key=lambda row: (
                    _aware_utc(row.time, label="transfer time"),
                    row.element_out,
                    row.element_in,
                ),
            )
        )
        for event, rows in grouped.items()
    }


def _apply_transfer(
    ownership: dict[int, int],
    transfer: ManagerTransfer,
    *,
    current_by_element: Mapping[int, BootstrapElement],
) -> None:
    outgoing = current_by_element.get(transfer.element_out)
    incoming = current_by_element.get(transfer.element_in)
    if outgoing is None or incoming is None:
        missing = transfer.element_out if outgoing is None else transfer.element_in
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.ELEMENT_MAPPING_MISSING,
            f"transfer element {missing} is absent from current bootstrap",
        )
    if outgoing.code not in ownership:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.TRANSFER_REPLAY_MISMATCH,
            f"cannot transfer out unowned player code {outgoing.code}",
        )
    if incoming.code in ownership:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.TRANSFER_REPLAY_MISMATCH,
            f"cannot transfer in already-owned player code {incoming.code}",
        )
    if transfer.element_in_cost <= 0:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.PRICE_MISSING,
            f"transfer-in price is missing for player code {incoming.code}",
        )
    del ownership[outgoing.code]
    ownership[incoming.code] = transfer.element_in_cost


def _replay_ownership(
    inputs: ManagerApiInputs,
    snapshot: _DeadlineSnapshot,
    *,
    captured_at: datetime,
) -> tuple[dict[int, int], tuple[ManagerTransfer, ...], bool]:
    deadline_by_element, _ = _element_indexes(snapshot.bootstrap)
    current_by_element, current_by_code = _element_indexes(inputs.bootstrap)
    start_codes = _pick_codes(
        inputs.start_picks, by_element=deadline_by_element, label="start-event picks"
    )
    ownership: dict[int, int] = {}
    for code in start_codes:
        deadline_player = next(
            player for player in deadline_by_element.values() if player.code == code
        )
        if deadline_player.now_cost is None or deadline_player.now_cost <= 0:
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.PRICE_MISSING,
                f"deadline price is missing for player code {code}",
            )
        if code not in current_by_code:
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.ELEMENT_MAPPING_MISSING,
                f"start-event player code {code} is absent from current bootstrap",
            )
        ownership[code] = deadline_player.now_cost

    chips = _chips_by_event(inputs.history, captured_at=captured_at)
    grouped = _transfer_records_by_event(
        inputs.transfers,
        manager_id=inputs.entry.id,
        start_event=inputs.entry.started_event,
        planning_event=inputs.planning_event.id,
        captured_at=captured_at,
    )
    for event in range(inputs.entry.started_event + 1, inputs.entry.current_event + 1):
        chip = _normalise_chip(chips[event].name) if event in chips else None
        if chip in _CHIP_FREE_HIT:
            continue
        for transfer in grouped.get(event, ()):
            _apply_transfer(ownership, transfer, current_by_element=current_by_element)

    latest_chip = _normalise_chip(inputs.latest_picks.active_chip)
    recorded_latest_chip = (
        _normalise_chip(chips[inputs.entry.current_event].name)
        if inputs.entry.current_event in chips
        else None
    )
    if latest_chip != recorded_latest_chip and (
        latest_chip in _CHIPS_PRESERVING_PRIOR_BANK
        or recorded_latest_chip in _CHIPS_PRESERVING_PRIOR_BANK
    ):
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.TRANSFER_REPLAY_MISMATCH,
            "latest picks active chip disagrees with public chip history",
        )
    latest_is_free_hit = latest_chip in _CHIP_FREE_HIT
    if not latest_is_free_hit:
        latest_codes = set(
            _pick_codes(
                inputs.latest_picks,
                by_element=current_by_element,
                label="latest revealed picks",
            )
        )
        if latest_codes != set(ownership):
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.TRANSFER_REPLAY_MISMATCH,
                "permanent transfer replay does not match the latest revealed picks",
            )

    post_picks = grouped.get(inputs.planning_event.id, ())
    for transfer in post_picks:
        _apply_transfer(ownership, transfer, current_by_element=current_by_element)
    return ownership, post_picks, not latest_is_free_hit


def _replay_free_transfers(
    inputs: ManagerApiInputs,
    *,
    post_picks_transfer_count: int,
    captured_at: datetime,
    rules: ManagerTransferReplayRules,
) -> _FreeTransferState:
    rows = _history_by_event(
        inputs.history,
        start_event=inputs.entry.started_event,
        picks_event=inputs.entry.current_event,
    )
    latest = rows[inputs.entry.current_event]
    picks_history = inputs.latest_picks.entry_history
    compared = (
        "bank",
        "value",
        "event_transfers",
        "event_transfers_cost",
    )
    if any(getattr(latest, field) != getattr(picks_history, field) for field in compared):
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.FREE_TRANSFER_REPLAY_MISMATCH,
            "latest picks entry_history disagrees with the history endpoint",
        )

    chips = _chips_by_event(inputs.history, captured_at=captured_at)
    grouped = _transfer_records_by_event(
        inputs.transfers,
        manager_id=inputs.entry.id,
        start_event=inputs.entry.started_event,
        planning_event=inputs.planning_event.id,
        captured_at=captured_at,
    )
    if rows[inputs.entry.started_event].event_transfers_cost != 0:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.FREE_TRANSFER_REPLAY_MISMATCH,
            "the entry's unlimited start event cannot carry a transfer hit",
        )

    carried = 0
    historical_hits = 0
    for event in range(inputs.entry.started_event + 1, inputs.entry.current_event + 1):
        row = rows[event]
        chip = _normalise_chip(chips[event].name) if event in chips else None
        records = grouped.get(event, ())
        if chip in _CHIPS_PRESERVING_PRIOR_BANK:
            if row.event_transfers_cost != 0:
                raise ManagerCaptureError(
                    ManagerCaptureErrorCode.FREE_TRANSFER_REPLAY_MISMATCH,
                    f"{chip} event {event} unexpectedly carries a transfer hit",
                )
            # In 2026/27 WC/FH consumes this event's new grant, while transfers banked
            # before the chip survive.
            continue

        if len(records) != row.event_transfers:
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.FREE_TRANSFER_REPLAY_MISMATCH,
                f"event {event} reports {row.event_transfers} transfers but the public "
                f"transfer log contains {len(records)}",
            )
        before = min(
            rules.free_transfer_bank_cap,
            carried + rules.free_transfer_per_event,
        )
        expected_hit = max(0, row.event_transfers - before) * rules.hit_cost_points
        if row.event_transfers_cost != expected_hit:
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.FREE_TRANSFER_REPLAY_MISMATCH,
                f"event {event} transfer cost {row.event_transfers_cost} does not match "
                f"the official replay value {expected_hit}",
            )
        carried = max(0, before - row.event_transfers)
        historical_hits += expected_hit

    planning_chip = (
        _normalise_chip(chips[inputs.planning_event.id].name)
        if inputs.planning_event.id in chips
        else None
    )
    if planning_chip in _CHIPS_PRESERVING_PRIOR_BANK:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.ACTIVE_PLANNING_CHIP,
            f"{planning_chip} is active for planning event {inputs.planning_event.id}; "
            "normal transfer suggestions are not valid",
        )
    before_planning_moves = min(
        rules.free_transfer_bank_cap,
        carried + rules.free_transfer_per_event,
    )
    existing_hit = max(0, post_picks_transfer_count - before_planning_moves) * rules.hit_cost_points
    remaining = max(0, before_planning_moves - post_picks_transfer_count)
    return _FreeTransferState(
        available=remaining,
        existing_hit_points=existing_hit,
        historical_hit_points=historical_hits,
    )


def official_selling_price(*, purchase_price: int, current_price: int) -> int:
    """FPL selling value: losses are immediate; profit is shared and rounded down."""
    if purchase_price <= 0 or current_price <= 0:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.PRICE_MISSING,
            "purchase and current prices must both be positive",
        )
    if current_price <= purchase_price:
        return current_price
    return purchase_price + (current_price - purchase_price) // 2


def _normalized_squad(
    ownership: Mapping[int, int],
    *,
    bootstrap: BootstrapStatic,
) -> tuple[ManagerSquadPlayer, ...]:
    _, by_code = _element_indexes(bootstrap)
    if len(ownership) != 15:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.ILLEGAL_SQUAD,
            f"reconstructed current squad has {len(ownership)} players instead of 15",
        )
    players: list[ManagerSquadPlayer] = []
    position_counts: dict[str, int] = dict.fromkeys(_POSITION_QUOTA, 0)
    team_counts: dict[int, int] = {}
    for code, purchase_price in sorted(ownership.items()):
        player = by_code.get(code)
        if player is None:
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.ELEMENT_MAPPING_MISSING,
                f"current squad code {code} is absent from current bootstrap",
            )
        position = _POSITION.get(player.element_type)
        if position is None:
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.ILLEGAL_SQUAD,
                f"current squad code {code} is not a playing-position element",
            )
        if player.now_cost is None or player.now_cost <= 0:
            raise ManagerCaptureError(
                ManagerCaptureErrorCode.PRICE_MISSING,
                f"current price is missing for player code {code}",
            )
        position_counts[position] += 1
        team_counts[player.team] = team_counts.get(player.team, 0) + 1
        players.append(
            ManagerSquadPlayer(
                element=player.id,
                code=code,
                web_name=player.web_name,
                position=position,
                team_id=player.team,
                now_cost=player.now_cost,
                purchase_price=purchase_price,
                selling_price=official_selling_price(
                    purchase_price=purchase_price, current_price=player.now_cost
                ),
            )
        )
    if position_counts != _POSITION_QUOTA:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.ILLEGAL_SQUAD,
            f"position counts {position_counts} do not match {_POSITION_QUOTA}",
        )
    over_cap = sorted(team for team, count in team_counts.items() if count > 3)
    if over_cap:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.ILLEGAL_SQUAD,
            f"current squad exceeds the three-per-club cap for team ids {over_cap}",
        )
    return tuple(players)


def _assert_snapshot_matches_start_event(
    snapshot: _DeadlineSnapshot,
    *,
    current_bootstrap: BootstrapStatic,
    start_event: int,
) -> None:
    current = _event_by_id(current_bootstrap, start_event)
    deadline = _event_by_id(snapshot.bootstrap, start_event)
    if current.deadline_time is None or deadline.deadline_time is None:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.DEADLINE_SNAPSHOT_INVALID,
            f"event {start_event} has no deadline in one of the bootstrap payloads",
        )
    if _aware_utc(current.deadline_time, label="current deadline") != _aware_utc(
        deadline.deadline_time, label="snapshot deadline"
    ):
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.DEADLINE_SNAPSHOT_INVALID,
            f"deadline snapshot event {start_event} belongs to a different season/calendar",
        )


def _relative_snapshot_path(snapshot: _DeadlineSnapshot) -> str:
    return (Path("snapshots") / snapshot.directory).as_posix()


def derive_manager_capture_id(capture: ManagerTeamCapture) -> str:
    """Derive the stable capture id from every field except the id itself."""
    payload = capture.model_dump(mode="json", by_alias=True, exclude={"capture_id"})
    return "manager-" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def capture_manager_team(
    manager_id: int,
    *,
    client: FplApiClient,
    snapshots_root: Path | None = None,
    captured_at: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    transfer_rules: ManagerTransferReplayRules | None = None,
) -> ManagerTeamCapture:
    """Fetch, validate, and reconstruct one complete manager state entirely in memory.

    The capture time (or clock) is injectable for deterministic tests. No destination is
    accepted here by design, so endpoint or validation failure cannot publish a partial
    manager capture.
    """
    if captured_at is not None and clock is not None:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.CAPTURE_INVALID,
            "provide captured_at or clock, not both",
        )
    observed_at = captured_at or (clock or (lambda: datetime.now(UTC)))()
    known_at = _aware_utc(observed_at, label="captured_at")
    rules = transfer_rules or ManagerTransferReplayRules()
    inputs = fetch_manager_team_inputs(client, manager_id, captured_at=known_at)
    start = _event_by_id(inputs.bootstrap, inputs.entry.started_event)
    if start.deadline_time is None:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.EVENT_TIMELINE_MISMATCH,
            f"start event {start.id} has no deadline",
        )
    source_config = load_sources()
    root = (
        snapshots_root
        if snapshots_root is not None
        else repo_root() / source_config.paths.snapshots
    )
    snapshot = _latest_deadline_snapshot(root, deadline=start.deadline_time)
    _assert_snapshot_matches_start_event(
        snapshot,
        current_bootstrap=inputs.bootstrap,
        start_event=inputs.entry.started_event,
    )
    ownership, post_picks, comparable = _replay_ownership(inputs, snapshot, captured_at=known_at)
    free_state = _replay_free_transfers(
        inputs,
        post_picks_transfer_count=len(post_picks),
        captured_at=known_at,
        rules=rules,
    )
    squad = _normalized_squad(ownership, bootstrap=inputs.bootstrap)
    bank = inputs.latest_picks.entry_history.bank + sum(
        transfer.element_out_cost - transfer.element_in_cost for transfer in post_picks
    )
    if bank < 0:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.TRANSFER_REPLAY_MISMATCH,
            f"post-picks transfer replay produces a negative bank ({bank})",
        )
    chips = tuple(
        ManagerChipRecord(
            name=chip.name,
            event=chip.event,
            played_at=_aware_utc(chip.time, label="chip time"),
        )
        for chip in sorted(inputs.history.chips, key=lambda item: (item.event, item.name))
    )
    try:
        registry_sha256 = selectable_player_registry_sha256(
            inputs.raw_bootstrap,
            season=source_config.current_season.season,
        )
    except PlayerRegistryError as exc:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.CAPTURE_INVALID,
            f"current selectable-player registry is malformed: {exc}",
        ) from exc
    provenance = ManagerCaptureProvenance(
        current_bootstrap_sha256=_payload_sha256(inputs.raw_bootstrap),
        selectable_player_registry_sha256=registry_sha256,
        entry_sha256=_payload_sha256(inputs.raw_entry),
        latest_picks_sha256=_payload_sha256(inputs.raw_latest_picks),
        start_picks_sha256=_payload_sha256(inputs.raw_start_picks),
        transfers_sha256=_payload_sha256(inputs.raw_transfers),
        history_sha256=_payload_sha256(inputs.raw_history),
        deadline_snapshot_capture_id=snapshot.capture_id,
        deadline_snapshot_captured_at=snapshot.captured_at,
        deadline_snapshot_relative_path=_relative_snapshot_path(snapshot),
        deadline_snapshot_manifest_sha256=snapshot.manifest_sha256,
        deadline_snapshot_bootstrap_archive_sha256=snapshot.bootstrap_archive_sha256,
        deadline_snapshot_bootstrap_payload_sha256=snapshot.bootstrap_payload_sha256,
    )
    selling_value = sum(player.selling_price for player in squad)
    pending = ManagerTeamCapture(
        capture_id="pending",
        captured_at=known_at,
        season=source_config.current_season.season,
        manager_id=inputs.entry.id,
        manager_name=inputs.entry.name,
        player_first_name=inputs.entry.player_first_name,
        player_last_name=inputs.entry.player_last_name,
        started_event=inputs.entry.started_event,
        picks_event=inputs.entry.current_event,
        planning_event=inputs.planning_event.id,
        squad=squad,
        bank_tenths=bank,
        squad_selling_value_tenths=selling_value,
        available_budget_tenths=selling_value + bank,
        free_transfers_available=free_state.available,
        existing_hit_points=free_state.existing_hit_points,
        historical_hit_points=free_state.historical_hit_points,
        post_picks_transfer_count=len(post_picks),
        chips=chips,
        transfer_rules=rules,
        completeness=ManagerCaptureCompleteness(
            latest_free_hit_picks_comparable_to_permanent_squad=comparable
        ),
        provenance=provenance,
    )
    payload = pending.model_dump(mode="json", by_alias=True)
    payload["capture_id"] = derive_manager_capture_id(pending)
    return ManagerTeamCapture.model_validate(payload)


def manager_capture_bytes(capture: ManagerTeamCapture) -> bytes:
    """Canonical UTF-8 bytes after re-deriving the capture identity."""
    expected = derive_manager_capture_id(capture)
    if capture.capture_id != expected:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.CAPTURE_INVALID,
            f"capture_id {capture.capture_id!r} does not match derived id {expected!r}",
        )
    payload = capture.model_dump(mode="json", by_alias=True)
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
    return (text + "\n").encode("utf-8")


def manager_capture_sha256(capture: ManagerTeamCapture) -> str:
    """SHA-256 of the exact canonical capture bytes."""
    return hashlib.sha256(manager_capture_bytes(capture)).hexdigest()


def read_manager_capture_bytes(payload: bytes) -> ManagerTeamCapture:
    try:
        capture = ManagerTeamCapture.model_validate_json(payload)
    except ValueError as exc:
        raise ManagerCaptureError(
            ManagerCaptureErrorCode.CAPTURE_INVALID,
            f"invalid manager capture: {exc}",
        ) from exc
    manager_capture_bytes(capture)
    return capture


def read_manager_capture(path: Path) -> ManagerTeamCapture:
    return read_manager_capture_bytes(path.read_bytes())


def write_manager_capture_atomic(
    path: Path,
    capture: ManagerTeamCapture,
    *,
    pre_publish: Callable[[], None] | None = None,
) -> str:
    """Flush then atomically create path; an existing path is never overwritten."""
    payload = manager_capture_bytes(capture)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if pre_publish is not None:
            pre_publish()
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise ManagerCaptureExistsError(path) from exc
        temporary.unlink()
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "FREE_TRANSFER_SOURCE",
    "MANAGER_CAPTURE_SCHEMA",
    "MANAGER_CAPTURE_SCHEMA_VERSION",
    "ManagerCaptureCompleteness",
    "ManagerCaptureError",
    "ManagerCaptureErrorCode",
    "ManagerCaptureExistsError",
    "ManagerCaptureProvenance",
    "ManagerChipRecord",
    "ManagerSquadPlayer",
    "ManagerTeamCapture",
    "ManagerTransferReplayRules",
    "capture_manager_team",
    "derive_manager_capture_id",
    "fetch_manager_team_inputs",
    "manager_capture_bytes",
    "manager_capture_sha256",
    "official_selling_price",
    "read_manager_capture",
    "read_manager_capture_bytes",
    "write_manager_capture_atomic",
]
