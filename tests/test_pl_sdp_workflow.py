"""Static contracts for the durable Premier League SDP capture workflow.

The workflow deliberately does not import this package -- it is curl, gzip and jq only, so a
refactor or a broken lockfile cannot stop a capture. That is exactly why its load-bearing
properties have to be pinned here rather than trusted to review.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINNED_CHECKOUT = "uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2"


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_the_capture_workflow_exists_and_pins_its_checkout() -> None:
    workflow = _workflow("pl-sdp-capture.yml")
    assert PINNED_CHECKOUT in workflow, "an unpinned action can change under the capture"


def test_capture_shares_the_snapshot_concurrency_group() -> None:
    """Two capture jobs must never race on the same commit."""
    workflow = _workflow("pl-sdp-capture.yml")
    assert "group: api-snapshot" in workflow
    assert "cancel-in-progress: false" in workflow


def test_capture_uses_no_python() -> None:
    """The one job that cannot afford to break has no build step.

    Checked against the executable parts only: the comments legitimately point an operator at
    `python -m fpl.jobs.audit_pl_sdp --probe`, which runs on their machine, not in this job.
    """
    workflow = _workflow("pl-sdp-capture.yml")
    executable = "\n".join(
        line for line in workflow.splitlines() if not line.lstrip().startswith("#")
    )
    for forbidden in ("setup-python", "pip install", "python -m fpl", "uv run"):
        assert forbidden not in executable, f"{forbidden!r} would couple capture to the package"


def test_capture_is_manual_until_a_season_id_is_recorded() -> None:
    """`pl_sdp.season_ids` starts empty and this repository refuses to guess one."""
    workflow = _workflow("pl-sdp-capture.yml")
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow


def test_untrusted_inputs_are_validated_and_never_interpolated_into_the_script() -> None:
    """`${{ }}` is substituted before the shell parses, so an input could close a quote."""
    workflow = _workflow("pl-sdp-capture.yml")
    body = workflow.split("run: |", 1)[1]
    assert "${{ inputs." not in body, "inputs must reach the shell through `env`, not `${{ }}`"
    assert 'case "${SEASON_ID}" in' in workflow
    assert 'case "${SEASON_LABEL}" in' in workflow
    assert 'case "${MAX_MATCHES}" in' in workflow


def test_the_commit_path_is_asserted_before_anything_is_written() -> None:
    workflow = _workflow("pl-sdp-capture.yml")
    assert "refusing to commit unexpected path" in workflow
    assert "snapshots/pl-sdp/" in workflow


def test_capture_refuses_a_non_200_empty_or_non_json_body() -> None:
    """Committing an error page would look like data forever."""
    workflow = _workflow("pl-sdp-capture.yml")
    assert "--fail" in workflow
    assert 'jq -e . "${out}"' in workflow
    assert "implausibly small" in workflow


def test_capture_paces_its_requests() -> None:
    """This is a website backend, not a public API."""
    workflow = _workflow("pl-sdp-capture.yml")
    assert "sleep 1.5" in workflow


def test_capture_probes_the_envelope_rather_than_assuming_it() -> None:
    """The response shape is undocumented; the jq must accept a list or a container."""
    workflow = _workflow("pl-sdp-capture.yml")
    assert 'if type == "array"' in workflow
    assert ".matches // .content // .data // .items" in workflow


def test_capture_records_a_manifest_and_checksums() -> None:
    workflow = _workflow("pl-sdp-capture.yml")
    assert "SHA256SUMS" in workflow
    assert "manifest.json" in workflow
    assert "schema_version" in workflow


def test_a_missing_stats_payload_is_a_recorded_gap_not_a_failed_run() -> None:
    """One unavailable match must not abandon a capture; coverage is where a gap shows."""
    workflow = _workflow("pl-sdp-capture.yml")
    assert "a gap is recorded, not fatal" in workflow
