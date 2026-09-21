"""Bounded public news read model; never a forecast or private-note transport."""

from __future__ import annotations

import ipaddress
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import parse_qsl, urlsplit

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from fpl.publish.public_dashboard import PublicDashboardPackageError, _assert_public_safe
from fpl.storage.public_news import NewsStore

NewsKind = Literal["fpl", "x"]
Category = Literal["injury", "suspension", "transfer", "squad", "press_conference", "other"]
Status = Literal["ok", "disabled", "pending_key", "error", "budget_exhausted", "not_configured"]


class NewsRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NewsText(NewsRecord):
    en: str = Field(min_length=1, max_length=800)
    th: str | None = Field(max_length=800)


class NewsSource(NewsRecord):
    source_id: str = Field(min_length=1, max_length=100)
    source_name: str = Field(min_length=1, max_length=120)
    source_kind: NewsKind
    status: Status
    last_checked_at: AwareDatetime | None
    last_success_at: AwareDatetime | None
    message: str = Field(max_length=300)


class NewsStory(NewsRecord):
    id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_id: str = Field(min_length=1, max_length=100)
    source_name: str = Field(min_length=1, max_length=120)
    source_kind: NewsKind
    source_url: str = Field(max_length=2000)
    source_record_id: str = Field(min_length=1, max_length=150)
    published_at: AwareDatetime | None
    known_at: AwareDatetime
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    season: str | None = Field(pattern=r"^\d{4}-\d{2}$")
    team_code: StrictInt | None = Field(gt=0)
    team_name: str | None = Field(max_length=120)
    player_code: StrictInt | None = Field(gt=0)
    player_name: str | None = Field(max_length=120)
    category: Category
    title: NewsText
    summary: NewsText
    rendering: Literal["source_text", "ai_summary"]
    ai_model: str | None = Field(max_length=100)
    summarized_at: AwareDatetime | None

    @field_validator("source_url")
    @classmethod
    def public_link(cls, value: str) -> str:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (
            parsed.scheme != "https"
            or not host
            or "." not in host
            or host.endswith((".local", ".internal", ".localhost", ".test", ".invalid", ".example"))
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or any(ord(c) < 33 for c in value)
            or "\\" in value
            or parsed.fragment
            or any(
                re.search(
                    r"token|secret|password|manager|entry|squad|api.?key|signature|auth", key, re.I
                )
                for key, _ in parse_qsl(parsed.query)
            )
        ):
            raise ValueError("news source must be a public credential-free HTTPS link")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return value
        raise ValueError("news source must use a public hostname")

    @model_validator(mode="after")
    def provenance(self) -> Self:
        if self.published_at is not None and self.published_at > self.known_at:
            raise ValueError("news publication cannot postdate its observation")
        if (self.player_code is None) != (self.player_name is None):
            raise ValueError("player name requires a measured stable code")
        if (self.team_code is None) != (self.team_name is None):
            raise ValueError("club name requires a measured stable code")
        if self.source_kind == "x":
            parsed = urlsplit(self.source_url)
            if parsed.hostname not in {
                "x.com",
                "twitter.com",
                "www.x.com",
                "www.twitter.com",
            } or not re.fullmatch(r"/[A-Za-z0-9_]{1,15}/status/[0-9]+", parsed.path):
                raise ValueError("X news requires its exact source post URL")
            if self.player_code is not None:
                raise ValueError("X player mentions have no automatic identity resolution")
        if self.rendering == "source_text":
            if self.ai_model is not None or self.summarized_at is not None:
                raise ValueError("original source text cannot claim AI provenance")
        elif (
            self.ai_model is None
            or self.summarized_at is None
            or self.title.th is None
            or self.summary.th is None
        ):
            raise ValueError("AI summary requires both languages and actual provenance")
        return self


class NewsFeed(NewsRecord):
    schema_name: Literal["fpl.public-news"] = Field(alias="schema")
    schema_version: Literal[1]
    semantics: Literal["reported_news_not_forecast"]
    generated_at: AwareDatetime
    demo: StrictBool
    sources: list[NewsSource] = Field(max_length=50)
    stories: list[NewsStory] = Field(max_length=100)

    @model_validator(mode="after")
    def chronology(self) -> Self:
        sources = {source.source_id: source for source in self.sources}
        if len(sources) != len(self.sources):
            raise ValueError("duplicate news source")
        ids: set[str] = set()
        records: set[tuple[str, str]] = set()
        for source in self.sources:
            for stamp in (source.last_checked_at, source.last_success_at):
                if stamp is not None and stamp > self.generated_at:
                    raise ValueError("news source check postdates export")
            if (
                source.last_success_at is not None
                and source.last_checked_at is not None
                and source.last_success_at > source.last_checked_at
            ):
                raise ValueError("last success postdates last check")
        for story in self.stories:
            story_source = sources.get(story.source_id)
            if story_source is None or (story.source_name, story.source_kind) != (
                story_source.source_name,
                story_source.source_kind,
            ):
                raise ValueError("news source identity mismatch")
            record = (story.source_id, story.source_record_id)
            if story.id in ids or record in records:
                raise ValueError("duplicate news story/version")
            ids.add(story.id)
            records.add(record)
            if story.known_at > self.generated_at or (
                story.summarized_at is not None and story.summarized_at > self.generated_at
            ):
                raise ValueError("news evidence postdates export")
        return self


def validate_news_feed(payload: object) -> None:
    feed = NewsFeed.model_validate(payload)
    _assert_public_safe(feed.model_dump(mode="json", by_alias=True))


def empty_news_feed(*, as_of: datetime, status: Status = "not_configured") -> dict[str, Any]:
    """No source evidence is an explicit state, not a synthetic article."""
    document: dict[str, Any] = {
        "schema": "fpl.public-news",
        "schema_version": 1,
        "semantics": "reported_news_not_forecast",
        "generated_at": as_of.isoformat(),
        "demo": False,
        "sources": [
            {
                "source_id": "news",
                "source_name": "News collection",
                "source_kind": "fpl",
                "status": status,
                "last_checked_at": None,
                "last_success_at": None,
                "message": "News collection is not configured."
                if status == "not_configured"
                else "Retained news is unavailable; core dashboard data is unaffected.",
            }
        ],
        "stories": [],
    }
    validate_news_feed(document)
    return document


def export_news_feed(store: Path, *, as_of: datetime) -> dict[str, Any]:
    """Read a retained store only. Provider capture is a separate, optional job."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("news export cutoff must be timezone-aware")
    if not store.is_file():
        return empty_news_feed(as_of=as_of)
    try:
        return _retained_feed(NewsStore(store, read_only=True), as_of=as_of)
    except (OSError, sqlite3.DatabaseError, ValueError, PublicDashboardPackageError):
        # Optional source failure must not block the core football-data publication.
        # Do not echo database paths, provider bodies, or private record content.
        return empty_news_feed(as_of=as_of, status="error")


def _retained_feed(store: NewsStore, *, as_of: datetime) -> dict[str, Any]:
    observations = store.recent_observations(limit=2000, as_of=as_of)
    states = store.latest_statuses(as_of=as_of)
    successes = store.last_successes(as_of=as_of)
    withdrawn = {state.source_id for state in states if state.status == "unapproved"}
    receipted = {state.source_id for state in states}
    sources: dict[str, dict[str, Any]] = {}
    statuses: dict[str, Status] = {"missing_key": "pending_key", "unapproved": "disabled"}
    for state in states:
        status = statuses.get(state.status, state.status)
        summary_note = {
            "missing_key": " AI translation is not connected.",
            "budget_exhausted": " AI translation monthly limit reached.",
            "error": " AI translation is unavailable.",
            "disabled": " AI translation is disabled.",
            "ok": "",
        }[state.summary_status]
        success = successes.get(state.source_id)
        sources[state.source_id] = {
            "source_id": state.source_id,
            "source_name": state.source_name,
            "source_kind": state.source_kind,
            "status": status,
            "last_checked_at": state.checked_at.isoformat(),
            "last_success_at": success.isoformat() if success else None,
            "message": (state.reason + summary_note)[:300],
        }
    stories: list[dict[str, Any]] = []
    for observation in observations:
        if observation.source_id not in sources:
            sources[observation.source_id] = {
                "source_id": observation.source_id,
                "source_name": observation.source_name,
                "source_kind": observation.source_kind,
                "status": "error",
                "last_checked_at": None,
                "last_success_at": None,
                "message": "Retained observation available; collection receipt unavailable.",
            }
        if (
            not observation.active
            or len(stories) == 100
            or observation.source_id in withdrawn
            or (observation.source_kind == "x" and observation.source_id not in receipted)
        ):
            continue
        summary = store.latest_summary(observation.content_sha256, as_of=as_of)
        if observation.source_kind == "x" and (
            summary is None or not summary.summary.has_substantive_update
        ):
            # A teaser is not a team update. Legacy unchecked summaries also stay private.
            continue
        if summary is None and (observation.source_kind == "x" or len(observation.text) > 800):
            # X raw posts remain private. Await a validated digest instead of publishing a
            # copied post without its required native display/attribution contract.
            continue
        stories.append(
            {
                "id": observation.version_id,
                "source_id": observation.source_id,
                "source_name": observation.source_name,
                "source_kind": observation.source_kind,
                "source_url": observation.source_url,
                "source_record_id": observation.source_record_id,
                "published_at": observation.source_published_at.isoformat()
                if observation.source_published_at
                else None,
                "known_at": observation.known_at.isoformat(),
                "source_sha256": observation.content_sha256,
                "season": observation.season,
                "team_code": observation.team_code,
                "team_name": observation.team_name,
                "player_code": observation.player_code,
                "player_name": observation.player_name,
                "category": summary.summary.category if summary else "other",
                "title": {
                    "en": summary.summary.title_en
                    if summary
                    else f"{observation.player_name or 'Player'} · FPL update",
                    "th": summary.summary.title_th if summary else None,
                },
                "summary": {
                    "en": summary.summary.summary_en if summary else observation.text,
                    "th": summary.summary.summary_th if summary else None,
                },
                "rendering": "ai_summary" if summary else "source_text",
                "ai_model": summary.model if summary else None,
                "summarized_at": summary.summarized_at.isoformat() if summary else None,
            }
        )
    document: dict[str, Any] = {
        "schema": "fpl.public-news",
        "schema_version": 1,
        "semantics": "reported_news_not_forecast",
        "generated_at": as_of.isoformat(),
        "demo": False,
        "sources": [sources[key] for key in sorted(sources)],
        "stories": stories,
    }
    validate_news_feed(document)
    return document
