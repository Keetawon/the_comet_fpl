"""Premier League SDP client -- the V2 football data source.

`sdp-prem-prod.premier-league-prod.pulselive.com` is the JSON backend behind
premierleague.com. It is undocumented private infrastructure, not a published API, so this
module is written for a provider that may change shape without notice:

  * **Raw bytes are the record.** Every fetch returns the exact response text alongside its
    sha256 and byte count. The parse is a convenience; the payload is the archive.
  * **Additive drift is tolerated, incompatible drift is loud.** Envelope shapes are probed
    against an ordered list of known container keys and a failure names what was actually
    received. Unknown *fields* are never dropped -- they flow to the tall metric store.
  * **Nothing is inferred silently.** A season label with no mapped provider id raises rather
    than guessing an id; an ambiguous stats envelope raises rather than picking a side.

No test in this repository reaches the network. `base_url` is injectable and
`tests/fixtures/pl_sdp/` holds vendored payload shapes.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Self

import httpx

from fpl.config import PlSdpSource, load_sources
from fpl.ingest.fpl_api import ApiResponseError, EgressBlockedError

__all__ = [
    "MATCH_LIST_CONTAINER_KEYS",
    "PlSdpClient",
    "RawPayload",
    "SdpMatchSummary",
    "SdpSchemaError",
    "SdpTeamStats",
    "extract_items",
    "is_completed_scored_match",
    "parse_match_summary",
    "parse_team_stats",
]

# Proxy/gateway statuses meaning "policy refused this host", not "the server erred".
_EGRESS_BLOCKED_STATUSES: Final[frozenset[int]] = frozenset({403, 407})

# Envelope container keys tried, in order, when a payload is an object rather than a list.
# Ordered most-specific first so a payload carrying both `matches` and a generic `content`
# resolves to the specific one.
MATCH_LIST_CONTAINER_KEYS: Final[tuple[str, ...]] = (
    "matches",
    "content",
    "data",
    "items",
    "results",
    "elements",
)

# Keys that have carried the total-result count on Pulselive-family envelopes.
_TOTAL_KEYS: Final[tuple[str, ...]] = ("totalElements", "totalResults", "total", "count")
_PAGE_INFO_KEYS: Final[tuple[str, ...]] = ("pageInfo", "page", "paging", "pagination")

# Side labels the stats endpoint is documented (by observation of the website) to use.
_HOME_LABELS: Final[frozenset[str]] = frozenset({"home", "h", "hometeam", "home_team"})
_AWAY_LABELS: Final[frozenset[str]] = frozenset({"away", "a", "awayteam", "away_team"})

# Result labels observed or historically used by the provider for a completed match. A
# recognised label is still insufficient without both scores: scheduled 0-0 placeholders must
# never be treated as results.
_COMPLETED_RESULT_LABELS: Final[frozenset[str]] = frozenset(
    {"c", "complete", "completed", "finished", "fulltime", "ft", "normalresult", "played"}
)


class SdpSchemaError(RuntimeError):
    """A payload did not have a shape this client can interpret.

    Deliberately distinct from `ApiResponseError`: the request succeeded and the provider
    answered, but its contract changed in a way that cannot be tolerated additively. Callers
    must surface it rather than retry.
    """


@dataclass(frozen=True, slots=True)
class RawPayload:
    """One fetched response, as it arrived.

    `text` is the response body decoded explicitly as UTF-8. `payload` is its parse, retained
    only so a caller does not parse twice; `sha256` and `byte_count` describe the source bytes.
    """

    endpoint: str
    path: str
    params: Mapping[str, object]
    fetched_at: datetime
    status_code: int
    text: str
    sha256: str
    byte_count: int
    payload: Any

    def params_json(self) -> str:
        """Canonical request identity: sorted keys, no whitespace drift."""
        return json.dumps(
            {str(key): value for key, value in sorted(self.params.items())},
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class SdpMatchSummary:
    """The identity of one match, reduced to what the crosswalk and marts need.

    Every field except `match_id` is optional because a provider that omits one must not
    abort a backfill -- the identity audit reports the gap instead. `match_id` is not
    optional: a payload row without one cannot be stored, keyed, or reconciled.
    """

    match_id: int
    season_id: int | None
    matchweek: int | None
    kickoff: datetime | None
    home_team_name: str | None
    away_team_name: str | None
    home_team_id: int | None
    away_team_id: int | None
    home_score: int | None
    away_score: int | None
    status: str | None


@dataclass(frozen=True, slots=True)
class SdpTeamStats:
    """One side of one match: its provider team identity and its raw metric mapping.

    `stats` is deliberately an untyped mapping of the provider's own field names to their raw
    values. Interpretation happens at the staging boundary against the metric dictionary, so
    a field this client has never heard of still lands in the tall store.
    """

    match_id: int
    side: str
    team_id: int | None
    team_name: str | None
    stats: Mapping[str, Any]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def extract_items(
    payload: Any, *, container_keys: Sequence[str] = MATCH_LIST_CONTAINER_KEYS
) -> list[Any]:
    """Pull the list of records out of a payload whose envelope shape is unknown.

    Accepts a bare list, or an object carrying the list under one of `container_keys`. Raises
    `SdpSchemaError` naming the keys actually present rather than returning an empty list --
    "no matches this season" and "the envelope changed" must not look the same, because the
    first is a fact worth recording and the second is a bug worth failing on.
    """
    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, dict):
        for key in container_keys:
            value = payload.get(key)
            if isinstance(value, list):
                return list(value)
        raise SdpSchemaError(
            "payload object carries no recognised list container. Tried "
            f"{list(container_keys)}; payload keys are {sorted(payload)}"
        )
    raise SdpSchemaError(f"payload is neither a list nor an object: {type(payload).__name__}")


def _reported_total(payload: Any) -> int | None:
    """The provider's own count of available records, if it declares one."""
    if not isinstance(payload, dict):
        return None
    for key in _TOTAL_KEYS:
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    for key in _PAGE_INFO_KEYS:
        info = payload.get(key)
        if isinstance(info, dict):
            for inner in _TOTAL_KEYS:
                value = info.get(inner)
                if isinstance(value, int) and not isinstance(value, bool):
                    return value
    return None


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _as_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 string or an epoch-millisecond integer to an aware UTC instant.

    A naive result is stamped UTC rather than left naive: this repository's point-in-time
    boundary refuses naive datetimes, so a naive kickoff would be a latent leakage error.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int) and not isinstance(value, bool):
        # Milliseconds since epoch is the Pulselive-family convention. Seconds would place
        # every Premier League match in 1970, so the discriminator is unambiguous.
        seconds = value / 1000.0 if abs(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=UTC)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    if isinstance(value, dict):
        return _as_datetime(_first(value, "millis", "utcDate", "date", "label"))
    return None


def _team_identity(node: Any) -> tuple[int | None, str | None]:
    """Team id and name out of a side node, tolerating several nesting conventions."""
    if not isinstance(node, dict):
        return None, None
    inner = node
    for key in ("team", "club", "info"):
        candidate = node.get(key)
        if isinstance(candidate, dict):
            inner = candidate
            break
    team_id = _as_int(_first(inner, "id", "teamId", "clubId", "optaId"))
    name = _first(inner, "name", "shortName", "displayName", "clubName", "abbreviation")
    return team_id, str(name) if isinstance(name, str) else None


def parse_match_summary(record: Any) -> SdpMatchSummary:
    """Reduce one match record to its identity. Raises if it carries no usable id."""
    if not isinstance(record, dict):
        raise SdpSchemaError(f"match record is not an object: {type(record).__name__}")
    match_id = _as_int(_first(record, "id", "matchId", "match_id", "optaId"))
    if match_id is None:
        raise SdpSchemaError(f"match record carries no integer id; keys are {sorted(record)}")

    teams = record.get("teams")
    home_node: Any = _first(record, "homeTeam", "home_team", "home")
    away_node: Any = _first(record, "awayTeam", "away_team", "away")
    if isinstance(teams, list) and len(teams) == 2:
        home_node = home_node if home_node is not None else teams[0]
        away_node = away_node if away_node is not None else teams[1]
    home_id, home_name = _team_identity(home_node)
    away_id, away_name = _team_identity(away_node)

    score_node = record.get("score")
    scores: Mapping[str, Any] = score_node if isinstance(score_node, dict) else record
    home_score = _as_int(_first(scores, "homeScore", "home_score", "homeGoals", "home"))
    away_score = _as_int(_first(scores, "awayScore", "away_score", "awayGoals", "away"))
    if home_score is None and isinstance(home_node, dict):
        home_score = _as_int(_first(home_node, "score", "goals", "teamScore"))
    if away_score is None and isinstance(away_node, dict):
        away_score = _as_int(_first(away_node, "score", "goals", "teamScore"))

    season_node = record.get("season")
    season_id = (
        _as_int(_first(season_node, "id", "seasonId"))
        if isinstance(season_node, dict)
        else _as_int(_first(record, "season", "seasonId"))
    )
    # The live payload's `phase` is a numeric competition phase (observed as the string
    # "1" for completed and scheduled matches), not match completion. `resultType` is the
    # completion discriminator: completed matches carry `NormalResult`, future matches null.
    status = _first(record, "status", "state", "matchStatus", "resultType", "result_type")
    if not isinstance(status, str):
        status = _first(record, "phase")
    return SdpMatchSummary(
        match_id=match_id,
        season_id=season_id,
        matchweek=_as_int(_first(record, "matchweek", "matchWeek", "gameweek", "round")),
        kickoff=_as_datetime(
            _first(record, "kickoff", "kickoffTime", "kickoff_time", "utcDate", "date")
        ),
        home_team_name=home_name,
        away_team_name=away_name,
        home_team_id=home_id,
        away_team_id=away_id,
        home_score=home_score,
        away_score=away_score,
        status=str(status) if isinstance(status, str) else None,
    )


def is_completed_scored_match(summary: SdpMatchSummary, *, now: datetime) -> bool:
    """Whether a match has a genuine completed result and both scores.

    The live provider exposes ``resultType=NormalResult`` rather than a status/phase. When no
    result label is available, a scored match is accepted only after the conservative
    three-hour post-kickoff boundary used by the current-season capture.
    """
    if summary.home_score is None or summary.away_score is None:
        return False
    if summary.status is not None:
        label = summary.status.strip().casefold().replace(" ", "").replace("_", "").replace("-", "")
        return label in _COMPLETED_RESULT_LABELS
    return summary.kickoff is not None and summary.kickoff + timedelta(hours=3) <= now


def _normalise_side(label: Any) -> str:
    text = str(label).strip().lower().replace(" ", "").replace("-", "")
    if text in _HOME_LABELS:
        return "home"
    if text in _AWAY_LABELS:
        return "away"
    raise SdpSchemaError(f"unrecognised side label {label!r}; expected a home/away marker")


def _stats_mapping(node: Mapping[str, Any]) -> Mapping[str, Any]:
    """The metric mapping out of a side node.

    Two shapes are accepted: a `stats` object keyed by field name, and a `stats` LIST of
    `{name, value}` records, which is the older Pulselive rendering. A duplicated name inside
    a list with conflicting values fails closed rather than letting the last one win.
    """
    stats = node.get("stats", node.get("statistics"))
    if isinstance(stats, dict):
        return dict(stats)
    if isinstance(stats, list):
        collected: dict[str, Any] = {}
        for item in stats:
            if not isinstance(item, dict):
                continue
            name = _first(item, "name", "key", "type", "metric")
            if not isinstance(name, str):
                continue
            value = _first(item, "value", "amount", "total")
            if name in collected and collected[name] != value:
                raise SdpSchemaError(
                    f"stat {name!r} appears twice with different values "
                    f"({collected[name]!r} then {value!r}); refusing to pick one"
                )
            collected[name] = value
        return collected
    raise SdpSchemaError(f"side node carries no stats mapping; keys are {sorted(node)}")


def parse_team_stats(payload: Any, *, match_id: int) -> list[SdpTeamStats]:
    """Both sides of one match's stats payload.

    The documented shape is `[{"side": "Home", "stats": {...}}, {"side": "Away", ...}]`, and
    an object envelope carrying that list is also accepted. Exactly two sides, one home and
    one away, are required: a stats payload with one side is a partial capture, and storing it
    would produce a team-match fact whose opponent mirror is silently absent.
    """
    items = extract_items(payload, container_keys=("stats", *MATCH_LIST_CONTAINER_KEYS))
    sides: list[SdpTeamStats] = []
    for item in items:
        if not isinstance(item, dict):
            raise SdpSchemaError(f"stats entry is not an object: {type(item).__name__}")
        label = _first(item, "side", "teamSide", "homeOrAway", "type")
        if label is None:
            raise SdpSchemaError(f"stats entry carries no side label; keys are {sorted(item)}")
        team_id, team_name = _team_identity(item)
        sides.append(
            SdpTeamStats(
                match_id=match_id,
                side=_normalise_side(label),
                team_id=team_id,
                team_name=team_name,
                stats=_stats_mapping(item),
            )
        )
    labels = sorted(side.side for side in sides)
    if labels != ["away", "home"]:
        raise SdpSchemaError(
            f"match {match_id} stats payload has sides {labels}, expected exactly "
            "['away', 'home']; a one-sided capture cannot produce opponent mirrors"
        )
    return sides


class PlSdpClient:
    """Polite, retrying, raw-preserving client.

    Pacing defaults are slower than the FPL client's because this is a website backend rather
    than a public API. 429 is honoured via `Retry-After` where the provider sends one.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        config: PlSdpSource | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        resolved = config or (load_sources().pl_sdp)
        if resolved is None:
            raise RuntimeError(
                "config/sources.yaml carries no `pl_sdp` block; the V2 football source is "
                "unconfigured"
            )
        self._config = resolved
        self._base_url = (base_url or resolved.base_url).rstrip("/")
        self._client = client or httpx.Client(
            timeout=resolved.timeout_seconds, follow_redirects=True
        )
        self._owns_client = client is None
        self._last_request_at: float | None = None
        self.request_count = 0

    @property
    def config(self) -> PlSdpSource:
        return self._config

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _throttle(self) -> None:
        interval = self._config.min_request_interval_seconds
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < interval:
                time.sleep(interval - elapsed)
        self._last_request_at = time.monotonic()

    @staticmethod
    def _retry_after_seconds(response: httpx.Response, fallback: float) -> float:
        """Honour `Retry-After` when the provider sends a usable one."""
        header = response.headers.get("retry-after")
        if header:
            try:
                seconds = float(header.strip())
            except ValueError:
                return fallback
            # Cap it: a hostile or buggy header must not stall a backfill indefinitely.
            return min(max(seconds, 0.0), 120.0)
        return fallback

    def fetch(
        self, endpoint: str, *, path: str, params: Mapping[str, object] | None = None
    ) -> RawPayload:
        """GET with throttling, backoff and 429 handling, returning the raw response.

        `endpoint` is the logical name recorded in provenance; `path` is what is requested.
        Keeping them separate means a config path change does not orphan already-captured raw
        rows from their endpoint identity.
        """
        # httpx types query values narrowly; every value this client sends is a scalar the
        # provider expects verbatim, so it is rendered to text here rather than loosened.
        query: dict[str, str] = {
            str(key): str(value) for key, value in (params or {}).items() if value is not None
        }
        url = f"{self._base_url}/{path.lstrip('/')}"
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            self._throttle()
            self.request_count += 1
            try:
                response = self._client.get(url, params=query)
            except httpx.ProxyError as error:
                raise EgressBlockedError(
                    f"egress blocked reaching {url}: {error}. The host is not permitted by "
                    "this environment's network policy. Capture must run where it is."
                ) from error
            except httpx.HTTPError as error:
                last_error = error
            else:
                if response.status_code == 200:
                    content = response.content
                    if len(content) < self._config.minimum_payload_bytes:
                        raise ApiResponseError(
                            f"{url} returned {len(content)} bytes, below the "
                            f"{self._config.minimum_payload_bytes}-byte floor; treating an "
                            "implausibly small body as a failure rather than as empty data"
                        )
                    try:
                        text = content.decode("utf-8")
                    except UnicodeDecodeError as error:
                        raise ApiResponseError(
                            f"{url} returned a body that is not valid UTF-8: {error}"
                        ) from error
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError as error:
                        raise ApiResponseError(f"{url} returned invalid JSON: {error}") from error
                    return RawPayload(
                        endpoint=endpoint,
                        path=path,
                        params=query,
                        fetched_at=datetime.now(UTC),
                        status_code=response.status_code,
                        text=text,
                        sha256=_sha256(content),
                        byte_count=len(content),
                        payload=parsed,
                    )
                if response.status_code in _EGRESS_BLOCKED_STATUSES:
                    raise EgressBlockedError(
                        f"egress blocked reaching {url}: HTTP {response.status_code} from the "
                        "proxy or gateway. This is a policy denial, not a server error."
                    )
                if response.status_code == 429:
                    last_error = ApiResponseError(f"{url} rate-limited (429)")
                    if attempt < self._config.max_retries:
                        time.sleep(
                            self._retry_after_seconds(
                                response,
                                self._config.retry_backoff_base_seconds * (2**attempt),
                            )
                        )
                        continue
                elif response.status_code < 500:
                    raise ApiResponseError(f"{url} returned HTTP {response.status_code}")
                else:
                    last_error = ApiResponseError(f"{url} returned HTTP {response.status_code}")

            if attempt < self._config.max_retries:
                time.sleep(self._config.retry_backoff_base_seconds * (2**attempt))
        raise ApiResponseError(
            f"{url} failed after {self._config.max_retries} retries: {last_error}"
        ) from last_error

    # -- endpoint wrappers ---------------------------------------------------------------

    def _endpoint(self, name: str) -> str:
        try:
            return self._config.endpoints[name]
        except KeyError:
            raise KeyError(
                f"no pl_sdp endpoint configured for {name!r}; available: "
                f"{sorted(self._config.endpoints)}"
            ) from None

    def fetch_seasons(self) -> RawPayload:
        path = self._endpoint("seasons").format(competition=self._config.competition)
        return self.fetch("seasons", path=path)

    def fetch_matches_page(
        self,
        *,
        season_id: int,
        matchweek: int | None = None,
        page: int = 0,
        cursor: str | None = None,
    ) -> RawPayload:
        params: dict[str, object] = {
            "competition": self._config.competition,
            "season": season_id,
            "_limit": self._config.page_size,
        }
        if cursor is not None:
            params["_next"] = cursor
        elif page > 0:
            # Compatibility fallback for the older page-number envelope. The live endpoint
            # uses the opaque `_next` cursor instead and ignores page/pageSize.
            params["page"] = page
            params["pageSize"] = self._config.page_size
        if matchweek is not None:
            params["matchweek"] = matchweek
        return self.fetch("matches", path=self._endpoint("matches"), params=params)

    def iter_matches(
        self, *, season_id: int, matchweek: int | None = None
    ) -> Iterator[tuple[RawPayload, list[SdpMatchSummary]]]:
        """Page through a season's matches, yielding each raw page with its parse.

        Termination is defensive because the provider's paging contract is unknown: it stops
        on an empty page, on a page that adds no unseen match id (which is what an endpoint
        that ignores `page` looks like), on reaching a declared total, and on the configured
        page cap. Yielding the raw page alongside the parse lets the caller archive every
        response even when it later proves to be a duplicate.
        """
        seen: set[int] = set()
        seen_cursors: set[str] = set()
        cursor: str | None = None
        for page in range(self._config.maximum_pages):
            raw = self.fetch_matches_page(
                season_id=season_id, matchweek=matchweek, page=page, cursor=cursor
            )
            records = extract_items(raw.payload)
            summaries = [parse_match_summary(record) for record in records]
            fresh = {summary.match_id for summary in summaries} - seen
            yield raw, summaries
            if not summaries or not fresh:
                return
            seen |= fresh
            total = _reported_total(raw.payload)
            if total is not None and len(seen) >= total:
                return
            pagination = raw.payload.get("pagination") if isinstance(raw.payload, dict) else None
            if isinstance(pagination, dict) and "_next" in pagination:
                value = pagination["_next"]
                if value is None or value == "":
                    return
                if isinstance(value, bool) or not isinstance(value, (str, int)):
                    raise SdpSchemaError(
                        "pagination._next must be a string, integer, or null; got "
                        f"{type(value).__name__}"
                    )
                next_cursor = str(value)
                if next_cursor in seen_cursors:
                    raise ApiResponseError(
                        f"season {season_id} repeated pagination cursor {next_cursor!r}; "
                        "refusing an incomplete or looping capture"
                    )
                seen_cursors.add(next_cursor)
                cursor = next_cursor
                continue
            if len(records) < self._config.page_size:
                return
        raise ApiResponseError(
            f"season {season_id} did not terminate within {self._config.maximum_pages} pages; "
            "the provider is ignoring the paging parameters or the cap is too low"
        )

    def fetch_match(self, match_id: int) -> RawPayload:
        path = self._endpoint("match").format(match_id=match_id)
        return self.fetch("match", path=path, params={"match_id": match_id})

    def fetch_match_stats(self, match_id: int) -> RawPayload:
        path = self._endpoint("match_stats").format(match_id=match_id)
        return self.fetch("match_stats", path=path, params={"match_id": match_id})

    def fetch_match_lineups(self, match_id: int) -> RawPayload:
        path = self._endpoint("match_lineups").format(match_id=match_id)
        return self.fetch("match_lineups", path=path, params={"match_id": match_id})

    def fetch_match_events(self, match_id: int) -> RawPayload:
        path = self._endpoint("match_events").format(match_id=match_id)
        return self.fetch("match_events", path=path, params={"match_id": match_id})
