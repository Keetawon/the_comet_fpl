# Private news API credentials

The news capture CLI now accepts a private UTF-8 `.env` file. This is local
credential loading only; it does not enable providers, change budgets, update a
scheduler, publish news, or change any forecast/model/UI.

Owner-host location: `D:/Personal/fpl-operations/news/.env`. Put the real value
after `OPENAI_API_KEY=` locally. `X_BEARER_TOKEN=` may remain empty for FPL-only
news translation. Never paste keys into chat or commit/upload them. This is a
plaintext local file: restrict its folder to the account running the job. The
owner-host file is created empty with owner-only permissions; no key is requested
or read during setup. A safe empty template is `config/public_news.env.example`.

The capture job defaults to `.env` in the same directory as its `--store`.
It never searches the working directory or parents. An explicit `--env-file`
must exist; a missing default file retains the old process-environment behavior.
Only `OPENAI_API_KEY` and `X_BEARER_TOKEN` are accepted. Existing process variables
win, including explicit empty values. The loader does not modify `os.environ`.

Use one `KEY=value` per line, with optional matching single/double quotes. Empty
lines and full-line `#` comments work. No `export`, interpolation, inline comments,
multiline values, duplicate keys or unknown variables. The input is bounded to
16 KiB. Invalid files fail before opening the news store, with redacted errors.
Credential files under `dashboard`, `public` or `dist` are rejected, including
resolved symlink paths. `.gitignore` already excludes `.env`/`.env.*`.

Example from the `codex/match-preview` worktree, using the existing Python runtime:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
& D:/Personal/fpl-operations/.venv/Scripts/python.exe -m fpl.jobs.capture_public_news `
  --config config/public_news.yaml `
  --env-file D:/Personal/fpl-operations/news/.env `
  --store D:/Personal/fpl-operations/news/news.sqlite3 `
  --output D:/Personal/fpl-operations/news/capture-unique-id.json
```

Keep a fresh output filename per run. With the committed `enabled: false`, even
valid keys do not cause provider requests. Adding the key alone does not connect
the scheduled refresh or update the website. No paid request is part of this
change. The earlier process-only credential instruction is extended only for
this CLI; frontend secrets remain forbidden.

Verification: 75 offline dotenv/capture/publish tests pass with synthetic keys;
scoped Ruff, formatting and strict mypy pass. Tests cover file/process precedence,
no parent search, malformed/unknown/duplicate assignments, size and UTF-8 bounds,
publication-path rejection, redacted receipts and disabled capture making no
network request despite keys being present. The first test invocation lacked its
temporary parent folder; after creating it, the suite passed. An existing Windows
pytest-cache permission warning remains and does not affect these test results.
Owner-host creation uses exclusive file creation and verifies an owner-only ACL.
No actual key was read, no provider request made, and no scheduler/site changed.
