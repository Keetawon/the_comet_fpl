"""Private dotenv integration without real credentials or provider requests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from fpl.jobs import capture_public_news as job


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)


def test_literal_credentials_and_process_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# private\nOPENAI_API_KEY=\"dummy-file-key\"\nX_BEARER_TOKEN='dummy=x%2B'\n",
        encoding="utf-8-sig",
    )
    assert job._news_environment(env_file, required=True) == {
        "OPENAI_API_KEY": "dummy-file-key",
        "X_BEARER_TOKEN": "dummy=x%2B",
    }
    assert "OPENAI_API_KEY" not in os.environ
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-process-key")
    monkeypatch.setenv("X_BEARER_TOKEN", "")
    monkeypatch.setenv("UNRELATED_SECRET", "unrelated")
    assert job._news_environment(env_file, required=True) == {
        "OPENAI_API_KEY": "dummy-process-key",
        "X_BEARER_TOKEN": "",
    }


def test_optional_missing_file_has_no_parent_search(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=dummy-parent\n")
    assert job._news_environment(tmp_path / "private" / ".env", required=False) == {}
    with pytest.raises(ValueError, match="explicit news credential file is missing"):
        job._news_environment(tmp_path / "missing.env", required=True)


@pytest.mark.parametrize(
    "text",
    [
        "OPENAI_API_KEY=dummy-secret\nOPENAI_API_KEY=duplicate",
        "VITE_OPENAI_API_KEY=dummy-secret",
        "OPENAI_API_KEY",
        'OPENAI_API_KEY="dummy-secret',
        "OPENAI_API_KEY=dummy-secret # comment",
        "OPENAI_API_KEY=${dummy-secret}",
        "OPENAI_API_KEY=$(dummy-secret)",
        "OPENAI_API_KEY=dummy-secret\x00",
        "OPENAI_API_KEY='dummy-secret with spaces'",
        "OPENAI_API_KEY=" + "dummy-secret" * 2000,
    ],
)
def test_invalid_file_fails_closed_without_echoing_secrets(tmp_path: Path, text: str) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="news credential") as error:
        job._news_environment(env_file, required=True)
    assert "dummy-secret" not in str(error.value)


@pytest.mark.parametrize("folder", ["dashboard", "PUBLIC", "dist"])
def test_publication_path_rejected(tmp_path: Path, folder: str) -> None:
    with pytest.raises(ValueError, match="outside dashboard/publication"):
        job._news_environment(tmp_path / folder / ".env", required=False)


def test_unreadable_encoding_is_redacted(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_bytes(b"OPENAI_API_KEY=dummy-secret\xff")
    with pytest.raises(ValueError, match="cannot be read as UTF-8") as error:
        job._news_environment(env_file, required=True)
    assert "dummy-secret" not in str(error.value)


def test_blank_template_and_file_keys_do_not_enable_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=\nX_BEARER_TOKEN=\n")
    assert job._news_environment(env_file, required=True) == {
        "OPENAI_API_KEY": "",
        "X_BEARER_TOKEN": "",
    }
    env_file.write_text("OPENAI_API_KEY=dummy-secret\nX_BEARER_TOKEN=dummy-secret\n")
    config = tmp_path / "news.yaml"
    config.write_text(
        "enabled: false\nx_sources:\n  - source_id: club\n    name: Club\n"
        "    handle: ClubOfficial\n    reuse_approved: true\n"
    )

    def blocked(*args: Any, **kwargs: Any) -> None:
        pytest.fail("credential loading must not enable provider requests")

    monkeypatch.setattr(job.httpx.Client, "send", blocked)
    output, store = tmp_path / "receipt.json", tmp_path / "news.sqlite3"
    assert job.main(["--config", str(config), "--store", str(store), "--output", str(output)]) == 0
    assert json.loads(output.read_text())["sources"][0]["status"] == "disabled"
    captured = capsys.readouterr()
    assert "dummy-secret" not in captured.out + captured.err + output.read_text()
    assert b"dummy-secret" not in store.read_bytes()


@pytest.mark.parametrize("explicit", [False, True])
def test_cli_passes_only_private_credentials_without_leaks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    explicit: bool,
) -> None:
    config = tmp_path / "news.yaml"
    config.write_text("enabled: false\nx_sources: []\n")
    env_file = tmp_path / ("custom.env" if explicit else ".env")
    env_file.write_text("OPENAI_API_KEY=dummy-private-key\nX_BEARER_TOKEN=\n")
    seen: list[dict[str, str]] = []

    def capture(*args: Any, env: dict[str, str], **kwargs: Any) -> list[Any]:
        seen.append(env)
        return []

    monkeypatch.setattr(job, "run_capture", capture)
    output = tmp_path / "receipt.json"
    args = [
        "--config",
        str(config),
        "--store",
        str(tmp_path / "news.sqlite3"),
        "--output",
        str(output),
    ]
    if explicit:
        args += ["--env-file", str(env_file)]
    assert job.main(args) == 0
    assert seen == [{"OPENAI_API_KEY": "dummy-private-key", "X_BEARER_TOKEN": ""}]
    assert json.loads(output.read_text()) == {"schema_version": 1, "sources": []}
    captured = capsys.readouterr()
    assert "dummy-private-key" not in captured.out + captured.err + output.read_text()
    assert "OPENAI_API_KEY" not in os.environ


def test_bad_env_cli_fails_before_store_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "news.yaml"
    config.write_text("enabled: false\n")
    (tmp_path / ".env").write_text("BAD_KEY=dummy-secret\n")
    store = tmp_path / "news.sqlite3"
    monkeypatch.setattr(job, "run_capture", lambda *a, **kw: pytest.fail("must not capture"))
    with pytest.raises(SystemExit):
        job.main(
            [
                "--config",
                str(config),
                "--store",
                str(store),
                "--output",
                str(tmp_path / "receipt.json"),
            ]
        )
    assert not store.exists()
    assert "dummy-secret" not in capsys.readouterr().err
