"""Development-only runner for Stage B Candidate V2. This is NOT a promotion evaluation.

    python -m fpl.validate.dev_minutes_candidate_v2            # full archive, development only
    python -m fpl.validate.dev_minutes_candidate_v2 --season 2025-26

Candidate V2 (``recency_weighted_trailing_player_minutes_v2``) is V1 with a geometric recency
weight on the same trailing-5 window; it reduces exactly to V1 at ``decay = 1.0``. This runner
reuses the Stage B harness, the four frozen baselines, the shared best-per-metric guardrail +
starter-ranking gate diagnostics, and the provenance machinery from the V1 runner unchanged -- it
only supplies the V2 candidate factory, source path, banner, and reconciliation schema.

Pre-registered before any V2 evaluation. The same provenance fence closes every time-of-check /
time-of-use gap: it refuses a dirty worktree, fingerprints the exact parsed config bytes, the V2
candidate-source bytes, and the archive, re-checks them after the database is closed, and suppresses
the result as INVALID/UNPUBLISHABLE if anything moved. The frozen gate is reported as structured
DEVELOPMENT diagnostics only and is never combined into a promotion verdict.

NOTE: a V2 historical evaluation must run against a PRISTINE historical archive (rebuild via
``build_db``), because the working DB now carries Step-2 live rows and its fingerprint no longer
matches the V1-era archive. That one-shot run is the owner's authorized action and is NOT invoked
here.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fpl.config import Phase2EvaluationConfig, config_dir, repo_root
from fpl.storage.db import default_db_path
from fpl.validate.dev_minutes_candidate_v1 import (
    ProvenanceError,
    build_reconciliation_record,
    capture_preflight,
    compute_development_diagnostics,
    file_sha256,
    finalize_provenance,
    format_development_report,
    format_reconciliation_record,
    load_contract_from_bytes,
    open_database,
    require_clean_worktree,
    verify_snapshot,
)
from fpl.validate.minutes_baselines import HistoryRow, TargetRow
from fpl.validate.minutes_harness import (
    MinutesCandidateFactory,
    format_minutes_report,
    run_minutes_harness,
)
from fpl.validate.minutes_metrics import MinutesDistribution

if TYPE_CHECKING:
    from fpl.models.minutes_v2 import RecencyWeightedTrailingPlayerMinutesV2

logger = logging.getLogger("fpl.validate.dev_minutes_candidate_v2")

_DEVELOPMENT_BANNER = (
    "\n"
    "============================================================================\n"
    " DEVELOPMENT ONLY -- NOT A PROMOTION RESULT\n"
    " Candidate V2 (recency_weighted_trailing_player_minutes_v2). V2 is V1 with a geometric\n"
    " recency weight on the same trailing-5 window (reduces to V1 at decay=1.0). The historical\n"
    " archive is development evidence (an unversioned target-roster / first-kickoff proxy), not\n"
    " a fresh holdout. Prospective 2026/27 is the untouched confirmation set, not consumed.\n"
    " No number below is a promotion verdict; V2 is judged by no promotion gate.\n"
    "============================================================================\n"
)

_V2_SCHEMA = "stage_b_candidate_v2_development/v1"

# The Candidate V2 model source this runner scores. Fingerprinted so a mid-run edit is detected.
_CANDIDATE_SOURCE_REL = Path("src") / "fpl" / "models" / "minutes_v2.py"


def _utc_now() -> str:
    """A timezone-aware UTC timestamp as a fixed ``YYYY-MM-DDTHH:MM:SSZ`` string."""
    from datetime import UTC

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def candidate_source_path(repo: Path) -> Path:
    """The Candidate V2 model source path whose fingerprint the runner records."""
    return repo / _CANDIDATE_SOURCE_REL


# --------------------------------------------------------------------------------------
# Candidate V2 adapter: a fold-local factory conforming to the harness protocol
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class _FittedCandidate:
    """Adapts Candidate V2's predict surface to the harness's uniform candidate shape."""

    name: str
    _model: RecencyWeightedTrailingPlayerMinutesV2

    def predict(self, target: TargetRow) -> MinutesDistribution:
        return self._model.predict(target)

    def parameters(self) -> dict[str, float | int | bool | str]:
        return self._model.parameters()


def candidate_factory(config: Phase2EvaluationConfig) -> MinutesCandidateFactory:
    """Build the fold-local Candidate V2 factory (mirrors the V1 factory; imports V2 lazily)."""
    from fpl.models.minutes_v2 import RecencyWeightedTrailingPlayerMinutesV2

    def factory(history: tuple[HistoryRow, ...], as_of: datetime) -> _FittedCandidate:
        model = RecencyWeightedTrailingPlayerMinutesV2(config=config).fit(history, as_of=as_of)
        return _FittedCandidate(model.name, model)

    return factory


# --------------------------------------------------------------------------------------
# Orchestration (mirrors dev_minutes_candidate_v1.main; reuses every shared helper)
# --------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Stage B Candidate V2 as a DEVELOPMENT-ONLY evaluation. Not a promotion evaluation."
        )
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--season", action="append", dest="seasons", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    repo = repo_root()
    config_path = config_dir() / "phase2_evaluation.yaml"
    contract, config_fp = load_contract_from_bytes(config_path)
    candidate_name = contract.stage_b_candidate_v2.name
    # Refuse to score a dirty worktree so the provenance is truthful.
    require_clean_worktree(repo, candidate="Candidate V2")

    db_path = args.db or default_db_path()
    cand_source = candidate_source_path(repo)
    snapshot = capture_preflight(
        db_path,
        contract,
        repo=repo,
        config_path=config_path,
        config_fp=config_fp,
        candidate_source_path=cand_source,
        candidate_source_fp=file_sha256(cand_source),
        candidate_name=candidate_name,
    )

    factory = candidate_factory(contract)
    con = open_database(db_path)
    try:
        result = run_minutes_harness(
            con, config=contract, seasons=args.seasons, candidate_factory=factory
        )
    finally:
        con.close()

    diagnostics = compute_development_diagnostics(result, snapshot.candidate, contract)
    ended_at = _utc_now()

    try:
        verify_snapshot(
            snapshot,
            db_path=db_path,
            repo=repo,
            config_path=config_path,
            candidate_source_path=cand_source,
        )
    except ProvenanceError as exc:
        sys.stderr.write(
            f"Candidate V2 result is INVALID / UNPUBLISHABLE and will not be printed: {exc}\n"
        )
        return 1

    provenance = finalize_provenance(snapshot, ended_at=ended_at)
    reconciliation = build_reconciliation_record(
        result, contract, provenance=provenance, diagnostics=diagnostics, schema=_V2_SCHEMA
    )
    standard_report = format_minutes_report(result, config=contract)
    development_report = format_development_report(
        result,
        snapshot.candidate,
        contract,
        provenance=provenance,
        diagnostics=diagnostics,
        banner=_DEVELOPMENT_BANNER,
    )
    print(standard_report)
    print(development_report)
    print("BEGIN_STAGE_B_CANDIDATE_V2_RECONCILIATION_JSON")
    print(format_reconciliation_record(reconciliation))
    print("END_STAGE_B_CANDIDATE_V2_RECONCILIATION_JSON")
    return 0


if __name__ == "__main__":
    sys.exit(main())
