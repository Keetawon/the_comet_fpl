"""Synthetic runner orchestration only: no real population or scientific claim is used."""

from __future__ import annotations

import json
import platform
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from fpl.features.attacking_role_premium_v1 import UsageObservation, UsageTarget
from fpl.jobs import evaluate_attacking_role_premium_v1 as job
from fpl.jobs.competitive_participation_pilot import file_sha256, publish_json
from fpl.validate.attacking_role_premium_v1 import StudyFold, StudyPopulation, UsageOutcome

AS_OF = datetime(2023, 8, 20, tzinfo=UTC)


def population() -> StudyPopulation:
    history = tuple(
        UsageObservation(
            "2023-24",
            1,
            code,
            AS_OF - timedelta(days=7),
            code,
            position,
            90,
            1,
            code / 10,
            code / 20,
            AS_OF - timedelta(days=6),
            AS_OF - timedelta(days=6),
            "ARCHIVED_AS_OF",
            "a" * 40,
            "b" * 64,
        )
        for code, position in enumerate(("DEF", "MID", "FWD"), 1)
    )
    folds = tuple(
        StudyFold(
            "2023-24",
            gw,
            AS_OF + timedelta(days=(gw - 2) * 7),
            "a" * 40,
            tuple(
                UsageTarget(
                    "2023-24",
                    gw,
                    gw * 10 + code,
                    AS_OF + timedelta(days=(gw - 2) * 7 + 1),
                    code,
                    position,
                    100,
                    200,
                    "HOME",
                )
                for code, position in enumerate(("DEF", "MID", "FWD"), 1)
            ),
        )
        for gw in (2, 3)
    )
    outcomes = {
        (t.season, t.fixture_id, t.player_code): UsageOutcome(
            t.season, t.gameweek, t.fixture_id, t.player_code, 0.2, 0.1, 90, 1
        )
        for fold in folds
        for t in fold.targets
    }
    receipt = {
        "target_gameweeks": 2,
        "target_rows": 6,
        "unique_players": 3,
        "population_sha256": "c" * 64,
        "paired_minutes_ge_45": 6,
    }
    return StudyPopulation(folds, history, outcomes, receipt)


@pytest.fixture
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    real = Path(__file__).resolve().parents[1] / job.CONFIG
    contract = yaml.safe_load(real.read_bytes())
    contract["evaluation"]["bootstrap_draws"] = 20
    contract["population"] = {
        "target_gws": 2,
        "target_rows": 6,
        "players": 3,
        "positions": {"DEF": 2, "MID": 2, "FWD": 2},
        "target_identity_sha256": "c" * 64,
        "primary_minute_slice_rows": 6,
    }
    pinned = {
        "study_id": job.STUDY_ID,
        "preregistration_git_head": "a" * 40,
        "implementation_sha256": {"runner": "b" * 64},
    }
    pop = population()
    monkeypatch.setattr(job, "load_contract", lambda *_: contract)
    monkeypatch.setattr(job, "provenance", lambda *_: pinned)
    monkeypatch.setattr(job, "load_population", lambda *_: pop)
    monkeypatch.setattr(job, "_git", lambda *_: "")
    monkeypatch.setattr(job, "_named_cases", lambda *_: {})
    claims: list[Path] = []

    def claim(root: Path, candidate: str, provenance: dict[str, Any]) -> Path:
        assert root == tmp_path
        path = tmp_path / "claim-in-shared-git.json"
        publish_json(
            path,
            {
                "candidate": candidate,
                "provenance": provenance,
                "claimed_at_utc": "2026-09-08T00:00:00+00:00",
            },
        )
        claims.append(path)
        return path

    monkeypatch.setattr(job, "reserve_program_claim", claim)
    return {
        "root": tmp_path,
        "config": real,
        "contract": contract,
        "pinned": pinned,
        "population": pop,
        "claims": claims,
    }


def execute(env: dict[str, Any], name: str = "formal", **options: Any) -> dict[str, Any]:
    return job.run(env["root"], env["config"], env["root"] / name, **options)


def test_population_only_never_claims_or_predicts(
    environment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("population verification must not predict")

    monkeypatch.setattr(job, "predict_batch", forbidden)
    result = execute(environment, population_only=True)
    assert result["target_rows"] == 6
    assert environment["claims"] == []
    assert not (environment["root"] / "formal" / "formal-result.json").exists()


def test_claim_and_batch_publication_precede_every_outcome_access(
    environment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    output = environment["root"] / "formal"
    original = environment["population"]
    accesses: list[int] = []

    class GuardedOutcomes(dict[tuple[str, int, int], UsageOutcome]):
        def __getitem__(self, key: tuple[str, int, int]) -> UsageOutcome:
            outcome = super().__getitem__(key)
            assert environment["claims"]
            assert (output / f"predictions-gw{outcome.gameweek:02d}.jsonl").exists()
            accesses.append(outcome.gameweek)
            return outcome

    guarded = replace(original, outcomes=GuardedOutcomes(original.outcomes))
    monkeypatch.setattr(job, "load_population", lambda *_: guarded)
    result = execute(environment)
    assert accesses == [2, 2, 2, 3, 3, 3]
    assert result["primary"]["rows"] == 6
    prediction = json.loads((output / "predictions-gw02.jsonl").read_bytes().splitlines()[0])
    assert set(prediction["target"]) == {
        "season",
        "gameweek",
        "fixture_id",
        "kickoff_time",
        "player_code",
        "fpl_position",
        "team_code",
        "opponent_team_code",
        "venue",
    }
    assert "xg" not in prediction
    receipt = json.loads((output / "execution-receipt.json").read_bytes())
    assert [e["event"] for e in receipt["events"]] == [
        "prediction_frozen",
        "outcomes_attached",
        "prediction_frozen",
        "outcomes_attached",
    ]
    assert receipt["events"][0]["at"] <= receipt["events"][1]["at"]


def test_replay_is_byte_identical_and_reserves_no_second_claim(
    environment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = execute(environment)
    original = environment["root"] / "formal"
    new_head = {**environment["pinned"], "preregistration_git_head": "d" * 40}
    monkeypatch.setattr(job, "provenance", lambda *_: new_head)
    replay = execute(environment, "replay", replay=original)
    assert replay == first
    assert len(environment["claims"]) == 1
    for name in [*first["artifact_sha256"], "formal-result.json"]:
        assert (original / name).read_bytes() == (
            environment["root"] / "replay" / name
        ).read_bytes()


def test_second_formal_claim_fails_and_does_not_overwrite(environment: dict[str, Any]) -> None:
    execute(environment)
    claim = environment["claims"][0].read_bytes()
    with pytest.raises(FileExistsError):
        execute(environment, "second")
    assert environment["claims"][0].read_bytes() == claim
    assert (
        json.loads((environment["root"] / "second" / "failure.json").read_bytes())["status"]
        == "INVALID"
    )


def test_existing_output_is_never_overwritten(environment: dict[str, Any]) -> None:
    execute(environment)
    before = (environment["root"] / "formal" / "formal-result.json").read_bytes()
    with pytest.raises(FileExistsError):
        execute(environment)
    assert (environment["root"] / "formal" / "formal-result.json").read_bytes() == before


def test_predictor_failure_keeps_claim_and_invalid_record(
    environment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise ValueError("synthetic failure before scoring")

    monkeypatch.setattr(job, "predict_batch", fail)
    with pytest.raises(ValueError, match="synthetic failure"):
        execute(environment)
    assert len(environment["claims"]) == 1
    output = environment["root"] / "formal"
    assert not (output / "formal-result.json").exists()
    failure = json.loads((output / "failure.json").read_bytes())
    assert failure["status"] == "INVALID"
    assert failure["resume_permitted"] is False
    with pytest.raises(ValueError, match="invalid run"):
        job._original(output)


def test_changed_artifact_blocks_replay_and_diagnostics(environment: dict[str, Any]) -> None:
    execute(environment)
    original = environment["root"] / "formal"
    (original / "predictions.jsonl").write_bytes(b"tamper")
    with pytest.raises(ValueError, match="artifact hash"):
        execute(environment, "replay", replay=original)
    with pytest.raises(ValueError, match="artifact hash"):
        job.run_diagnostics(
            environment["root"],
            environment["config"],
            original,
            environment["root"] / "diagnostics",
        )


def test_changed_implementation_blocks_replay(
    environment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    execute(environment)
    changed = {**environment["pinned"], "implementation_sha256": {"runner": "c" * 64}}
    monkeypatch.setattr(job, "provenance", lambda *_: changed)
    with pytest.raises(ValueError, match="implementation identity"):
        execute(environment, "replay", replay=environment["root"] / "formal")


def test_diagnostics_use_frozen_rows_without_predicting(
    environment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    execute(environment)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("diagnostics cannot predict or reload target population")

    monkeypatch.setattr(job, "predict_batch", forbidden)
    monkeypatch.setattr(job, "load_population", forbidden)
    result = job.run_diagnostics(
        environment["root"],
        environment["config"],
        environment["root"] / "formal",
        environment["root"] / "diagnostics",
    )
    assert result["kind"] == "post_result_diagnostics_no_new_predictions"
    assert len(result["source_determined_def_cases"]["top_five"]) == 2
    assert len(environment["claims"]) == 1


@pytest.mark.parametrize(
    "field", ["target_identity_sha256", "primary_minute_slice_rows", "players"]
)
def test_frozen_population_mismatch_fails_before_claim(
    environment: dict[str, Any], field: str
) -> None:
    environment["contract"]["population"][field] = -1
    with pytest.raises(ValueError, match="population"):
        execute(environment)
    assert environment["claims"] == []


def test_postflight_mutation_invalidates_before_result_publication(
    environment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    called = 0

    def changed(*args: Any) -> dict[str, Any]:
        nonlocal called
        called += 1
        return environment["pinned"] if called == 1 else {"changed": True}

    monkeypatch.setattr(job, "provenance", changed)
    with pytest.raises(ValueError, match="inputs changed"):
        execute(environment)
    assert not (environment["root"] / "formal" / "formal-result.json").exists()
    assert (environment["root"] / "formal" / "failure.json").exists()


def test_preflight_rejects_dirty_worktree_before_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def dirty(*args: Any) -> str:
        raise ValueError("dirty worktree")

    monkeypatch.setattr(job, "git_clean_head", dirty)
    with pytest.raises(ValueError, match="dirty worktree"):
        job.provenance(tmp_path, tmp_path / "config", {})


def test_preflight_rejects_wrong_branch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "git_clean_head", lambda *_: "a" * 40)
    monkeypatch.setattr(job, "_git", lambda *_: "main")
    with pytest.raises(ValueError, match="authorized V2 branch"):
        job.provenance(tmp_path, tmp_path / "config", {"expected_branch": "v2"})


def test_preflight_rejects_frozen_input_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, frozen = tmp_path / "config", tmp_path / "frozen"
    config.write_bytes(b"config")
    frozen.write_bytes(b"changed")
    monkeypatch.setattr(job, "git_clean_head", lambda *_: "a" * 40)
    monkeypatch.setattr(job, "_git", lambda *_: "v2")
    monkeypatch.setattr(job, "CONFIG_SHA256", file_sha256(config))
    with pytest.raises(ValueError, match="frozen input changed"):
        job.provenance(
            tmp_path, config, {"expected_branch": "v2", "frozen_inputs": {"frozen": "a" * 64}}
        )


def test_missing_labels_remain_null_and_are_not_scored(
    environment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    pop = environment["population"]
    outcomes = dict(pop.outcomes)
    key = next(iter(outcomes))
    outcomes[key] = replace(outcomes[key], xg=None)
    monkeypatch.setattr(job, "load_population", lambda *_: replace(pop, outcomes=outcomes))
    result = execute(environment)
    assert result["unavailable_outcome_rows"] == 1
    assert result["primary"]["rows"] == 5
    row = json.loads((environment["root"] / "formal" / "scored.jsonl").read_bytes().splitlines()[0])
    assert row["xg"] is None


def test_canonical_content_rejects_nonfinite_and_preserves_null() -> None:
    assert job.canonical({"xg": None, "xa": 0.0}) == b'{"xa":0.0,"xg":null}\n'
    with pytest.raises(ValueError, match="Out of range"):
        job.canonical({"xg": float("nan")})


def test_clean_crlf_uses_git_normalized_identity_but_keeps_actual_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, observations = tmp_path / "config", tmp_path / "observations"
    config.write_bytes(b"config")
    observations.write_bytes(b"observations")
    name = "src/fpl/jobs/evaluate_attacking_role_premium_v1.py"
    source = tmp_path / name
    source.parent.mkdir(parents=True)
    source.write_bytes(b"# clean CRLF checkout\r\n")
    calls: list[tuple[str, ...]] = []

    def git(root: Path, *args: str) -> str:
        calls.append(args)
        return "v2" if args[0] == "branch" else "e" * 40

    monkeypatch.setattr(job, "git_clean_head", lambda *_: "a" * 40)
    monkeypatch.setattr(job, "_git", git)
    monkeypatch.setattr(job, "CONFIG_SHA256", file_sha256(config))
    monkeypatch.setattr(job, "_raw_identity", lambda *_: {})
    contract: dict[str, Any] = {
        "expected_branch": "v2",
        "frozen_inputs": {},
        "inputs": {
            "observations": str(observations),
            "observations_sha256": file_sha256(observations),
        },
        "implementation_files": [name],
        "runtime": {"python": platform.python_version(), "packages": {}},
    }
    result = job.provenance(tmp_path, config, contract)
    assert result["implementation_sha256"][name] == file_sha256(source)
    assert result["implementation_git_blobs"][name] == "e" * 40
    assert ("hash-object", f"--path={name}", name) in calls
    contract["runtime"]["python"] = "not-the-current-runtime"
    with pytest.raises(ValueError, match="runtime differs"):
        job.provenance(tmp_path, config, contract)


def test_unfrozen_config_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.write_bytes(b"unregistered")
    with pytest.raises(ValueError, match="frozen preregistration"):
        job.load_contract(tmp_path, config)


def test_claim_provenance_mismatch_is_rejected(environment: dict[str, Any]) -> None:
    execute(environment)
    original = environment["root"] / "formal"
    claim = json.loads((original / "claim.json").read_bytes())
    claim["provenance"] = {"tampered": True}
    payload = job.canonical(claim)
    (original / "claim.json").write_bytes(payload)
    result = json.loads((original / "formal-result.json").read_bytes())
    digest = file_sha256(original / "claim.json")
    result["claim_sha256"] = digest
    result["artifact_sha256"]["claim.json"] = digest
    (original / "formal-result.json").write_bytes(job.canonical(result))
    with pytest.raises(ValueError, match="scientific claim identity"):
        job._original(original)
