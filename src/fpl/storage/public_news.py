"""Small private append-only public-source news store; never a model input."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class ExactModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SourceObservation(ExactModel):
    source_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    source_name: str = Field(min_length=1, max_length=100)
    source_record_id: str = Field(min_length=1, max_length=100)
    source_url: str = Field(max_length=2048)
    source_published_at: AwareDatetime | None
    captured_at: AwareDatetime
    known_at: AwareDatetime
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str = Field(max_length=20000)
    team_code: int | None = Field(default=None, gt=0)
    player_code: int | None = Field(default=None, gt=0)
    season: str | None = Field(default=None, pattern=r"^20\d{2}-\d{2}$")
    source_kind: Literal["x", "fpl"]
    team_name: str | None = Field(default=None, max_length=100)
    player_name: str | None = Field(default=None, max_length=150)
    active: bool = True
    source_snapshot_id: str | None = None
    source_payload_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("source_url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("news source must have an HTTPS public source URL")
        return value

    @model_validator(mode="after")
    def honest_times(self) -> Self:
        if self.known_at > self.captured_at:
            raise ValueError("news knowledge time postdates capture")
        if self.source_published_at and self.source_published_at > self.captured_at:
            raise ValueError("news publication postdates capture")
        if self.source_kind == "x" and self.player_code is not None:
            raise ValueError("X text cannot resolve a player identity")
        if self.active != bool(self.text.strip()):
            raise ValueError("empty news must be an inactive tombstone")
        return self

    @property
    def version_id(self) -> str:
        return hashlib.sha256(canonical(self.model_dump(mode="json"))).hexdigest()


Category = Literal["injury", "suspension", "squad", "press_conference", "transfer", "other"]


class BilingualSummary(ExactModel):
    title_en: str = Field(min_length=1, max_length=160)
    title_th: str = Field(min_length=1, max_length=200)
    summary_en: str = Field(min_length=1, max_length=600)
    summary_th: str = Field(min_length=1, max_length=800)
    category: Category
    # Old summaries had no substantive-content check and are not publishable X news.
    has_substantive_update: bool = False


class SummaryRecord(ExactModel):
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: str
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    summarized_at: AwareDatetime
    summary: BilingualSummary


class CaptureStatus(ExactModel):
    source_id: str
    source_name: str
    source_kind: Literal["fpl", "x"]
    checked_at: AwareDatetime
    source_checked_at: AwareDatetime | None = None
    status: Literal["disabled", "missing_key", "unapproved", "ok", "budget_exhausted", "error"]
    reason: str
    observations: int = Field(default=0, ge=0)
    summarized: int = Field(default=0, ge=0)
    summary_status: Literal["disabled", "missing_key", "ok", "budget_exhausted", "error"]
    truncated: bool = False

    @model_validator(mode="after")
    def truthful_check_time(self) -> Self:
        if self.source_checked_at is not None and self.source_checked_at > self.checked_at:
            raise ValueError("source check postdates status receipt")
        return self


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


class NewsStore:
    """SQLite append-only receipts. Raw source text stays local, not in public assets."""

    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self.path = path
        self.read_only = read_only
        if read_only:
            if not path.is_file():
                raise ValueError("news store unavailable")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS observations (
                    version INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL, record_id TEXT NOT NULL,
                    content_sha TEXT NOT NULL, body TEXT NOT NULL, raw BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS news_source_record
                    ON observations(source_id, record_id, version);
                CREATE TABLE IF NOT EXISTS summaries (
                    content_sha TEXT NOT NULL, model TEXT NOT NULL, prompt_sha TEXT NOT NULL,
                    body TEXT NOT NULL, PRIMARY KEY(content_sha, model, prompt_sha)
                );
                CREATE TABLE IF NOT EXISTS reservations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, month TEXT NOT NULL,
                    provider TEXT NOT NULL, microusd INTEGER NOT NULL CHECK(microusd > 0),
                    reserved_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS statuses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL, body TEXT NOT NULL
                );
            """)
            for table in ("observations", "summaries", "reservations", "statuses"):
                for action in ("UPDATE", "DELETE"):
                    db.execute(f"""CREATE TRIGGER IF NOT EXISTS no_{action.lower()}_{table}
                        BEFORE {action} ON {table}
                        BEGIN SELECT RAISE(ABORT, 'news records are append-only'); END""")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self.read_only:
            db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        else:
            db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def append(self, observation: SourceObservation, raw: bytes) -> SourceObservation:
        return self.append_batch([(observation, raw)])[0]

    def append_batch(
        self, pending: list[tuple[SourceObservation, bytes]]
    ) -> list[SourceObservation]:
        """One provider page/snapshot is atomic, including chronology validation."""
        saved: list[SourceObservation] = []
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for observation, raw in pending:
                if hashlib.sha256(raw).hexdigest() != observation.content_sha256:
                    raise ValueError("news raw content hash mismatch")
                row = db.execute(
                    "SELECT body FROM observations WHERE source_id=? AND record_id=? "
                    "ORDER BY version DESC LIMIT 1",
                    (observation.source_id, observation.source_record_id),
                ).fetchone()
                if row:
                    previous = SourceObservation.model_validate_json(row[0])
                    if observation.captured_at < previous.captured_at:
                        raise ValueError("news capture cannot move backwards")
                    if previous.content_sha256 == observation.content_sha256:
                        unversioned = {
                            "captured_at",
                            "known_at",
                            "source_snapshot_id",
                            "source_payload_sha256",
                        }
                        if previous.model_dump(exclude=unversioned) != observation.model_dump(
                            exclude=unversioned
                        ):
                            raise ValueError("identical raw content has conflicting news metadata")
                        saved.append(previous)
                        continue
                if observation.known_at != observation.captured_at:
                    raise ValueError("new version must use its actual capture knowledge time")
                db.execute(
                    "INSERT INTO observations(source_id,record_id,content_sha,body,raw) "
                    "VALUES(?,?,?,?,?)",
                    (
                        observation.source_id,
                        observation.source_record_id,
                        observation.content_sha256,
                        observation.model_dump_json(),
                        raw,
                    ),
                )
                saved.append(observation)
        return saved

    def recent_observations(
        self, *, limit: int = 200, as_of: datetime | None = None, source_id: str | None = None
    ) -> list[SourceObservation]:
        if not 1 <= limit <= 2000:
            raise ValueError("news read limit must be bounded")
        with self._connect() as db:
            rows = db.execute(
                "SELECT body FROM observations WHERE (? IS NULL OR source_id=?) "
                "ORDER BY version DESC",
                (source_id, source_id),
            ).fetchall()
        latest: dict[tuple[str, str], SourceObservation] = {}
        for row in rows:
            observation = SourceObservation.model_validate_json(row[0])
            if as_of is None or observation.known_at <= as_of:
                latest.setdefault(
                    (observation.source_id, observation.source_record_id), observation
                )
        return sorted(latest.values(), key=lambda o: (o.known_at, o.version_id), reverse=True)[
            :limit
        ]

    def since_id(self, source_id: str) -> str | None:
        with self._connect() as db:
            rows = db.execute(
                "SELECT record_id FROM observations WHERE source_id=?", (source_id,)
            ).fetchall()
        ids = [str(row[0]) for row in rows if str(row[0]).isascii() and str(row[0]).isdigit()]
        return max(ids, key=int) if ids else None

    def summary_for(
        self, content_sha256: str, model: str, prompt_sha256: str
    ) -> SummaryRecord | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT body FROM summaries WHERE content_sha=? AND model=? AND prompt_sha=?",
                (content_sha256, model, prompt_sha256),
            ).fetchone()
        return SummaryRecord.model_validate_json(row[0]) if row else None

    def save_summary(self, record: SummaryRecord) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO summaries VALUES(?,?,?,?)",
                (
                    record.content_sha256,
                    record.model,
                    record.prompt_sha256,
                    record.model_dump_json(),
                ),
            )

    def latest_summary(self, content_sha256: str, *, as_of: datetime) -> SummaryRecord | None:
        with self._connect() as db:
            rows = db.execute(
                "SELECT body FROM summaries WHERE content_sha=?", (content_sha256,)
            ).fetchall()
        records = [SummaryRecord.model_validate_json(row[0]) for row in rows]
        eligible = [record for record in records if record.summarized_at <= as_of]
        return (
            max(eligible, key=lambda r: (r.summarized_at, r.model, r.prompt_sha256))
            if eligible
            else None
        )

    def reserve(
        self, provider: Literal["x", "openai"], microusd: int, *, cap_microusd: int, now: datetime
    ) -> bool:
        """Reserve worst-case cost before every attempt; ambiguous failures never refund."""
        if now.tzinfo is None or microusd <= 0 or cap_microusd < 0:
            raise ValueError("invalid news budget reservation")
        month = now.astimezone(UTC).strftime("%Y-%m")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            used = int(
                db.execute(
                    "SELECT COALESCE(SUM(microusd),0) FROM reservations "
                    "WHERE month=? AND provider=?",
                    (month, provider),
                ).fetchone()[0]
            )
            if used + microusd > cap_microusd:
                return False
            db.execute(
                "INSERT INTO reservations(month,provider,microusd,reserved_at) VALUES(?,?,?,?)",
                (month, provider, microusd, now.astimezone(UTC).isoformat()),
            )
        return True

    def reserved_microusd(self, provider: str, month: str) -> int:
        with self._connect() as db:
            return int(
                db.execute(
                    "SELECT COALESCE(SUM(microusd),0) FROM reservations "
                    "WHERE provider=? AND month=?",
                    (provider, month),
                ).fetchone()[0]
            )

    def record_status(self, status: CaptureStatus) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO statuses(source_id,body) VALUES(?,?)",
                (status.source_id, status.model_dump_json()),
            )

    def latest_statuses(self, *, as_of: datetime | None = None) -> list[CaptureStatus]:
        with self._connect() as db:
            rows = db.execute("SELECT body FROM statuses ORDER BY id DESC").fetchall()
        latest: dict[str, CaptureStatus] = {}
        for row in rows:
            status = CaptureStatus.model_validate_json(row[0])
            if as_of is None or status.checked_at <= as_of:
                latest.setdefault(status.source_id, status)
        return [latest[key] for key in sorted(latest)]

    def last_successes(self, *, as_of: datetime) -> dict[str, datetime]:
        with self._connect() as db:
            rows = db.execute("SELECT body FROM statuses ORDER BY id DESC").fetchall()
        latest: dict[str, datetime] = {}
        for row in rows:
            status = CaptureStatus.model_validate_json(row[0])
            if status.status == "ok" and status.checked_at <= as_of:
                latest.setdefault(status.source_id, status.source_checked_at or status.checked_at)
        return latest
