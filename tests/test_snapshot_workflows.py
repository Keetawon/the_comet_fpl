"""Static contracts for the shell-only durable snapshot workflows.

The workflows intentionally do not import the Python package.  These tests therefore pin the
load-bearing schedule, completion gate, append-only path, and hosted-package inventory without
turning the irreplaceable capture into a Python-dependent job.
"""

from __future__ import annotations

import re
from pathlib import Path

from fpl.publish.public_dashboard import _ARCHIVE_FILENAMES

ROOT = Path(__file__).resolve().parents[1]
PINNED_CHECKOUT = (
    "uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2"
)


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_provisional_history_runs_in_bangkok_morning_under_shared_lock() -> None:
    workflow = _workflow("provisional-player-history.yml")
    assert set(re.findall(r'cron: "([^"]+)"', workflow)) == {
        "0 1 * * *",
        "0 5 * * *",
    }
    assert "group: api-snapshot" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "workflow_dispatch:" in workflow
    assert PINNED_CHECKOUT in workflow
    assert not re.search(r"uses:\s+[^\s]+@v\d+", workflow)


def test_all_durable_snapshot_checkouts_are_pinned_to_one_reviewed_commit() -> None:
    for filename in (
        "snapshot.yml",
        "player-history.yml",
        "provisional-player-history.yml",
    ):
        workflow = _workflow(filename)
        assert PINNED_CHECKOUT in workflow
        assert not re.search(r"uses:\s+actions/checkout@v\d+", workflow)


def test_provisional_history_admits_only_completed_scored_fixture_legs() -> None:
    workflow = _workflow("provisional-player-history.yml")
    assert ".finished_provisional == true or .finished == true" in workflow
    assert ".team_h_score != null and .team_a_score != null" in workflow
    assert "] | max // empty" in workflow
    assert 'get "${API}/event/${LATEST_GW}/live/"' in workflow
    assert 'get "${API}/element-summary/${element_id}/"' in workflow
    assert ".element_type == 1 or .element_type == 2" in workflow
    assert ".element_type == 3 or .element_type == 4" in workflow


def test_provisional_history_bounds_responses_and_rejects_rollover_skew() -> None:
    workflow = _workflow("provisional-player-history.yml")
    assert "MAX_BOOTSTRAP_BYTES=8388608" in workflow
    assert "MAX_FIXTURES_BYTES=4194304" in workflow
    assert "MAX_EVENT_LIVE_BYTES=8388608" in workflow
    assert "MAX_ELEMENT_SUMMARY_BYTES=2097152" in workflow
    assert '--max-time 120 --max-filesize "${max_bytes}"' in workflow
    assert 'bytes="$(wc -c < "${out}")"' in workflow
    assert 'if [ "${bytes}" -gt "${max_bytes}" ]; then' in workflow
    assert 'FIRST_KICKOFF="$(jq -r' in workflow
    assert 'if [[ "${FIRST_KICKOFF}" < "${FIRST_DEADLINE}" ]]; then' in workflow
    assert "fixtures still belong to the previous season" in workflow
    assert workflow.index('FIRST_KICKOFF="$(jq -r') < workflow.index('LATEST_GW="$(jq -r')
    assert workflow.index('FIRST_KICKOFF="$(jq -r') < workflow.index(
        'get "${API}/element-summary/${element_id}/"'
    )


def test_provisional_signal_covers_every_scored_fixture_and_latest_live_payload() -> None:
    workflow = _workflow("provisional-player-history.yml")
    assert "mapfile -t SIGNAL_GWS" in workflow
    assert "] | unique | sort | .[]" in workflow
    assert 'for signal_gw in "${SIGNAL_GWS[@]}"; do' in workflow
    assert 'get "${API}/event/${LATEST_GW}/live/"' in workflow
    assert '"${WORK}/event-live-signal/${signal_gw}.json"' not in workflow
    assert '] | sort_by(.event, .id)\' "${fixtures_path}"' in workflow
    assert "provisional-signal-v2" in workflow
    assert 'signal_schema_version:"2"' in workflow
    assert "] | sort_by(.id))}" in workflow
    assert "map(. | .explain |= sort_by(.fixture)) | sort_by(.id)" in workflow
    assert "mapfile -t AFTER_SIGNAL_GWS" in workflow
    assert 'get "${API}/bootstrap-static/" "${WORK}/bootstrap-after.json"' in workflow
    assert 'signal_sha256 "${WORK}/bootstrap-after.json"' in workflow
    assert 'if [ "${AFTER_SIGNAL_GW_LIST}" != "${SIGNAL_GW_LIST}" ]; then' in workflow
    assert "eligible fixture gameweeks changed during element-summary capture" in workflow


def test_recovery_and_manual_dispatch_force_a_content_identified_full_sweep() -> None:
    workflow = _workflow("provisional-player-history.yml")
    assert (
        "AUTHORITATIVE_SWEEP: ${{ github.event_name == 'workflow_dispatch' || "
        "github.event.schedule == '0 5 * * *' }}"
    ) in workflow
    assert (
        'if [ "${AUTHORITATIVE_SWEEP}" = "false" ] && [ -d "${BASE}" ]; then'
        in workflow
    )
    assert "authoritative recovery/manual pass: full element-summary sweep required" in workflow
    assert 'existing_content="$(jq -r \'.content_sha256 // empty\'' in workflow
    assert 'if [ "${existing_content}" = "${CONTENT_SHA256}" ]; then' in workflow
    assert workflow.index('get "${API}/element-summary/${element_id}/"') < workflow.index(
        'existing_content="$(jq -r'
    )


def test_provisional_sweep_requires_aggregate_rows_for_each_eligible_fixture() -> None:
    workflow = _workflow("provisional-player-history.yml")
    assert '.element == $element_id' in workflow
    assert '([.history[].fixture] | unique | length)' in workflow
    assert "foreign, invalid, or duplicate history rows" in workflow
    assert "MIN_HISTORY_ROWS_PER_FIXTURE=20" in workflow
    assert "COVERAGE_VIOLATION=" in workflow
    assert "[.[].history[]?] as $history" in workflow
    assert ".history_rows < $minimum or" in workflow
    assert ".home_appeared < 1 or .away_appeared < 1" in workflow
    assert ".opponent_team == $fixture.team_a" in workflow
    assert ".opponent_team == $fixture.team_h" in workflow
    assert "implausible per-fixture element-summary coverage" in workflow
    assert "minimum_history_rows_per_fixture:$minimum_history_rows_per_fixture" in workflow


def test_provisional_history_is_append_only_and_refuses_a_mixed_time_sweep() -> None:
    workflow = _workflow("provisional-player-history.yml")
    assert "snapshots/player-history-provisional/${SEASON}/gw-${LATEST_GW}" in workflow
    assert 'STAMP_DIR="$(date -u +%Y-%m-%dT%H%M%SZ)-${CONTENT_SHA256:0:16}"' in workflow
    assert 'if [ -e "${TARGET}" ]; then' in workflow
    assert "refusing to overwrite existing snapshot path" in workflow
    assert 'AFTER_SIGNAL_SHA256="$(signal_sha256' in workflow
    assert "fixture/live state changed during element-summary capture" in workflow
    assert 'mode:"player-history-provisional"' in workflow
    assert 'test -s "${TARGET}/event-live-${GW}.json.gz"' in workflow
    assert 'sha256sum --check --strict "${TARGET}/SHA256SUMS"' in workflow
    assert "attach_outcomes" not in workflow


def test_finalized_history_workflow_still_requires_official_event_finality() -> None:
    workflow = _workflow("player-history.yml")
    assert PINNED_CHECKOUT in workflow
    assert "[.events[] | select(.finished) | .id] | max // empty" in workflow
    assert "snapshots/player-history/${SEASON}/gw-${FINISHED_GW}" in workflow
    assert "finished_provisional" not in workflow


def test_pages_zip_allowlist_matches_the_public_packager_contract() -> None:
    workflow = _workflow("deploy-dashboard.yml")
    match = re.search(r"expected = \{(?P<body>.*?)\n\s*\}", workflow, re.DOTALL)
    assert match is not None
    declared = set(re.findall(r'"([a-z0-9_-]+\.json)"', match.group("body")))
    assert declared == set(_ARCHIVE_FILENAMES)
