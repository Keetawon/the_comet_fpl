# SDP primary remote runtime (design and status)

**Status: BLOCKED ONLY ON RUNTIME AUTHORIZATION / CREDENTIALS. This package is prepared
and offline-tested; it is not deployed, and no host is authorized.** No always-on remote
host is currently authorized for this repository, the only known hosting is the static
GitHub Pages site described in `docs/dashboard-deployment.md` (no mutable backend exists
or is authorized), and this package therefore provisions no credential of any kind.
`deploy/sdp-primary/` is complete, reviewed, offline-tested code that may be installed
the day an owner authorizes a machine. Nothing in this document changes a frozen result,
gate, model default, or the scientific record, and nothing here authorizes a main-branch
merge, PR, or default-branch change.

This is an additive companion to `docs/sdp-primary-operations.md` (the existing runbook,
which stays authoritative for the Windows task and the pre-deadline flow). It closes one
specific gap: that runbook's scheduler is a signed-in Windows interactive task and the
Actions capture path is manual-only, so an overnight host outage before a deadline has no
durable always-on refresh path.

## Scope and authorization boundary

- V2 branch only, development/operations-only. No promotion, no default change, no
  research evaluation, no capture or forecast is authorized by this package.
- The runtime runs exactly one command per day:
  `python -m fpl.jobs.daily_pl_sdp --db <explicit persistent db> --runs <persistent runs>
  --lookback-days 5 --workload`, reusing the existing locked, backed-up
  capture/normalize wrapper. It adds no retries inside the capture, no new network
  client, and no new repository dependency.
- Secrets: none exist and none may be introduced. The SDP backend is a public provider
  backend; the environment file carries paths and a commit pin only, and no credential
  may enter env files, unit files, receipts, logs, or Git.

## Pinned-code rule

The service runs code from one immutable V2-branch commit (`SDP_CODE_PIN` in
`/etc/default/comet-fpl-sdp`). The guard script is installed by `install.sh` at
`/usr/local/sbin/comet-fpl-verify-pin` (nothing inside the checkout is chmod'd or
mutated) and runs as `ExecStartPre` on both services via `/bin/sh`. It fails closed
when: the pin is unset or not a 40-hex SHA; `git` cannot read the checkout; the checkout
`HEAD` differs from the pin; **or the worktree is dirty** - any tracked modification or
untracked (non-ignored) file is code drift under an unchanged HEAD and refuses the
start. A root-owned checkout makes `git` refuse with "dubious ownership"; the guard
handles that narrowly by scoping `safe.directory` to exactly this one checkout path
through git's protected-config environment (`GIT_CONFIG_KEY_0`/`GIT_CONFIG_VALUE_0`),
never a wildcard. The capture unit also supplies this exact protected-config scope to its
Python process and children, because the daily job invokes Git again for provenance;
the guard's process-local export alone would not cover that separate invocation.
Pulling a mutable branch while the
runtime runs is forbidden: to change code, stop the services, move the checkout
consciously, update the pin, and start again. The project environment is built from the
repository's `uv.lock` with `uv sync --frozen` (frozen resolution, explicit environment
`/opt/comet-fpl/venv`, Python 3.12, project installed editable, lockfile never
rewritten), so `fpl.config.repo_root()` and the per-run source hashes keep resolving to
that checkout.

## Unit design

| Concern | Choice |
| --- | --- |
| Schedule | `OnCalendar=*-*-* 07:00:00` host-local time + `RandomizedDelaySec=15min`, `Persistent=true` so a missed run fires at next boot |
| Runtime bound | `TimeoutStartSec=7200` on the capture service (the start phase of a `Type=oneshot` unit is bounded by `TimeoutStartSec`, not `RuntimeMaxSec`), `TimeoutStopSec=120`; health service `TimeoutStartSec=300`, `TimeoutStopSec=60`. See the [systemd.service manpage](https://manpages.debian.org/trixie/systemd/systemd.service.5.en.html) for exact timeout semantics |
| Stop path | `KillSignal=SIGINT` asks the interpreter to raise KeyboardInterrupt so the daily wrapper can record a failed receipt and release its lock **when cleanup is possible** - best-effort, never a guarantee. After `TimeoutStopSec` the process is SIGKILLed, which leaves the sidecar lock and any unresolved WAL for explicit manual recovery. Nothing is ever deleted automatically |
| Retries | `Restart=on-failure`, `RestartSec=30min`, `StartLimitIntervalSec=4h`, `StartLimitBurst=3` in `[Unit]` - one initial attempt plus two bounded retries; then the unit stays failed until the next timer fire |
| Concurrency | `Type=oneshot` refuses overlapping starts of the same unit; the daily job additionally holds its own sidecar/DuckDB writer lock and backs up first |
| Privilege | Dedicated unprivileged `comet-fpl` system user (`nologin`), `NoNewPrivileges`, `ProtectSystem=strict` with `ReadWritePaths=/var/lib/comet-fpl`, `ProtectHome`, `PrivateTmp`, empty `CapabilityBoundingSet` |
| Network | Capture service allows `AF_UNIX AF_INET AF_INET6`; the health service allows `AF_UNIX` only (it is read-only and offline) |
| Database | One explicit persistent operational database under `/var/lib/comet-fpl/db`; never the repository default/research database (the daily job itself refuses it). `install.sh` imports an operator-provided **checkpointed** database with source/history; a schema-only database is explicitly NOT forecast-ready and requires the `--init-empty-schema` opt-in |
| Receipts | One directory per run under `/var/lib/comet-fpl/runs` with `report.json`, inventories, logs, staging audits, and a `before.duckdb` backup; never pruned by the runtime, failed receipts preserved |

## Deployment prerequisites

Root on the authorized host, systemd, git, an operator-installed **system** Python 3.12
(`install.sh` fails before mutating if it is missing, and pins uv to system
interpreters: `UV_PYTHON_PREFERENCE=only-system`, `UV_PYTHON_DOWNLOADS=never` - no
root-private interpreter the unprivileged service user and `ProtectHome=true` could not
execute), `uv` (for the frozen `uv.lock`-based environment), and an operator-provided
checkpointed operational database.
`install.sh` validates the pin (40-hex), the health bound (finite, positive), and both
paths (resolved under `/var/lib/comet-fpl`, conservative character set) before any
mutation, never interpolates paths into Python source (argv only), and verifies the
service user can actually read the checkout and execute the venv.

## Health CLI contract (`fpl.jobs.sdp_capture_health`)

Read-only: it scans receipt directories and writes nothing, reads no database, and never
deletes or rewrites a receipt (failed and malformed receipts are evidence).

```sh
python -m fpl.jobs.sdp_capture_health --runs <runs> --db <db> \
  [--max-success-age-hours H] [--fail-on-production-failure] [--now ISO-8601]
```

- Emits one JSON record (`schema: fpl.sdp-capture-health`, version 2) on stdout.
- Receipts may sit directly under the runs root (scheduled cycles) or nested below
  grouping directories (pre-deadline receipts); ordering uses each receipt's validated
  `finished_at` instant, never the directory name. Descendants of an identified receipt
  directory (its `staging/` outputs, logs, backups) are never receipts; the runs root
  itself is never a receipt; and only a true run directory - a daily-job timestamp run
  id or a directory holding a `run.log`/`before.json` witness - can be a pending run,
  never an arbitrary empty grouping or staging folder.
- A timestamp that is missing, unparseable, naive, or in the future is unknown: such a
  receipt is **undated**, cannot prove freshness, and appears under `undated_receipts`.
- `latest_completed`: newest completed receipt with a trustworthy `report.json`, with
  its `healthy`/`consumer_ready`/`exit_code`/`mode` and timestamps.
- `latest_success` and `success_age_hours`: newest receipt whose `healthy` is true and
  whose `finished_at` is a validated aware UTC instant.
- No healthy verdict over a suspect: while a malformed or undated receipt is newer than
  the proven success - or is of unknown recency, as unreadable JSON is - the report
  keeps `healthy: null` and `verdict: unknown`, and `newer_suspects` names the blocker.
  With `--db`, an unattributed (`database`-less) receipt never proves success for the
  requested database either: only an exactly attributed success proves freshness, and
  an unattributed receipt blocks like any other suspect. Unknown is never promoted to
  healthy. A real failure (`healthy: false` on the newest completed receipt) still
  reports as unhealthy.
- `production_health`: the stricter core-field block from the newest receipt that
  carries one, reported separately from receipt success - a transport-healthy run may
  still be in `SDP_SOURCE_FALLBACK`; the two verdicts are never merged.
- `running_receipts` (a true run directory without its `report.json` - in progress or
  crashed), `failed_receipts` (completed with `healthy: false`), `malformed_receipts`
  (unreadable or untrustworthy `report.json`), and `undated_receipts` are all reported.
  With `--db`, receipts whose database cannot be read are **unattributed**: they are
  never silently dropped - `unattributed_receipts` counts them and they block healthy
  claims because they may belong to this database. Provably other-database receipts
  appear under `other_database_receipts` and block nothing.
- Unknown is null: missing runs root, missing fields, unparseable timestamps, and
  malformed receipts surface as nulls with a `problem` note, never as zero, never as
  healthy, never as a guess.
- Exit status is nonzero for real conditions: the newest completed receipt says
  `healthy: false`; or proven staleness - `--max-success-age-hours` supplied (finite
  and positive; rejected otherwise) and no dated success exists or the success age
  exceeds that explicit bound; or, only with `--fail-on-production-failure`, the newest
  production health reports a global failure; **or an explicit bound whose required
  freshness cannot be proven** because suspects block the evidence - a monitor must not
  exit success when freshness is unproven, so the exit is nonzero with `verdict:
  unknown` and `freshness_unproven: true`, while every unknown field stays null (no
  invented time, no zero). Without an explicit bound, blocked evidence exits zero as
  plain unknown. The bound is an explicit operational argument; this module invents no
  scientific or statistical threshold.
- `--now` exists for deterministic checks.

## Pre-deadline use

The capture service is independently callable at any time:
`sudo systemctl start comet-fpl-sdp-capture.service`. The forecast itself remains the
separate `fpl.jobs.pre_deadline_forecast` flow documented in the parent runbook, pointed
at the same operational database; the runtime never runs or schedules a forecast,
prediction, or evaluation. Pre-deadline receipts land under the same runs root (the
health CLI reads them wherever they are nested).

## Storage

The source operational database is on the order of **1.4 GB**, and each capture cycle
writes a full `before.duckdb` backup into its receipt directory, so receipts grow by
roughly that size per day. The runtime never prunes anything; retention is an explicit
operator decision. Retire a backup only after verifying complete retention of its immutable
raw and ledger records elsewhere. Keep every published forecast's `forecast-source.duckdb`,
`report.json`, inventories, and logs long enough to reconstruct every published
prospective vintage per the parent runbook, and never edit or delete a failed receipt to
make a dashboard look healthy. Recovery must preserve newer source versions and ledger rows;
replacing the operational database with an older backup alone is insufficient.

## Blocked items and unblocking

Blocked solely on owner authorization of a capture host (and any credential the owner
would provision for that host, which today is none). When unblocked: follow
`deploy/sdp-primary/README.md` exactly (prerequisites, place the checkpointed
operational database, `install.sh --pin <sha>`), confirm the timer, run the health
check, and record the host and pin in this document before the first scheduled cycle.
Until then this package must not be described as deployed, running, or production.
