"""Synthetic review regressions for receipts and saved-projection source drift."""

from types import SimpleNamespace

import pytest

from fpl.validate import dev_player_points_synthesis as runner
from tests.test_dev_player_points_synthesis import setup as setup


@pytest.mark.parametrize("phase", ["preclaim", "postflight"])
def test_saved_projection_source_drift_refuses_success(setup, monkeypatch, tmp_path, phase):
    args, calls, old = setup
    args["root"] = tmp_path / "repo"
    source = tmp_path / "saved-h-provenance.json"
    source.write_text("original saved source", encoding="utf-8")
    source_files = {str(source.resolve()): runner.file_sha256(source)}
    projection = SimpleNamespace(
        source_files=source_files,
        provenance={"models_refitted": False},
        reproduction={"maximum_absolute_pmf_difference": 0.0},
        project=lambda *a: {r.code: (1.0,) + (0.0,) * 10 for r in old},
    )
    monkeypatch.setattr(runner, "load_saves_projection", lambda *a: projection)
    original = runner.compose_synthesis_fixture

    def compose(*args, saves_replacements=None):
        values = original(*args, saves_replacements=saves_replacements)
        if (phase == "preclaim" and not saves_replacements) or (
            phase == "postflight" and saves_replacements
        ):
            source.write_text("changed saved source", encoding="utf-8")
        return values

    monkeypatch.setattr(runner, "compose_synthesis_fixture", compose)
    with pytest.raises(ValueError, match=r"projection|source|drift|changed|hash"):
        runner.run(**args)
    assert not (args["output"] / "result.json").exists()
    assert ("claim" in calls) is (phase == "postflight")


def test_comparator_receipt_drift_refuses_success(setup, monkeypatch, tmp_path):
    args, _, _ = setup
    args["root"] = tmp_path / "repo"
    original = runner.summarize_points

    def score(rows, **kwargs):
        result = original(rows, **kwargs)
        (args["output"] / "comparator_reproduction.json").write_text(
            "changed reproduction receipt", encoding="utf-8"
        )
        return result

    monkeypatch.setattr(runner, "summarize_points", score)
    with pytest.raises(ValueError, match=r"output|receipt|changed|hash"):
        runner.run(**args)
    assert not (args["output"] / "result.json").exists()
