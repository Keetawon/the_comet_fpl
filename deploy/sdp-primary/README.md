# SDP primary remote runtime (Linux systemd package)

Operational files for running the daily SDP-primary capture cycle
(`python -m fpl.jobs.daily_pl_sdp`) on an always-on Linux host under systemd.
Design, authorization status, and the health-CLI contract live in
`docs/sdp-primary-remote-runtime.md`; read it before installing anything.

**Status: BLOCKED ONLY ON RUNTIME AUTHORIZATION / CREDENTIALS.** This package is
prepared, reviewed code - it is not deployed, and no host is authorized yet. Nothing here
must be run until the owner authorizes a machine; there are no credentials to provision
(the SDP backend is public and this runtime uses no secret).

## Files

| File | Purpose |
| --- | --- |
| `comet-fpl-sdp-capture.service` | Oneshot daily capture cycle, unprivileged, hardened, `TimeoutStartSec=7200` / `TimeoutStopSec=120`, bounded retries |
| `comet-fpl-sdp-capture.timer` | Daily 07:00 host-local schedule, `Persistent=true` |
| `comet-fpl-sdp-health.service` | Read-only receipt health check; nonzero exit on unhealthy/stale |
| `comet-fpl-sdp-capture.env.sample` | Sample for `/etc/default/comet-fpl-sdp` (paths and pin only; no secrets) |
| `install.sh` | Validated bootstrap: user, state dirs, env file, frozen-lock venv, DB import check, guard install, units, timer |
| `verify-pin.sh` | Installed to `/usr/local/sbin/comet-fpl-verify-pin`; refuses dirty worktrees, HEAD drift, and unset pins |

## Prerequisites (operator-installed, nothing is auto-downloaded)

Root on the authorized host; systemd; git; an operator-installed **system** Python 3.12
(`install.sh` fails before mutating if missing; uv is pinned to system interpreters via
`UV_PYTHON_PREFERENCE=only-system` and `UV_PYTHON_DOWNLOADS=never`, so no root-private
interpreter that the unprivileged service user and `ProtectHome=true` could not execute);
`uv` (the project environment is built with `uv sync --frozen` from the repository
`uv.lock` - no unpinned pip resolution, lockfile never rewritten); and an
operator-provided **checkpointed** operational database with source/history. A
schema-only database is NOT forecast-ready and requires the explicit
`--init-empty-schema` opt-in with a loud warning.

## Exact commands

```sh
# 0. On the authorized host, as root: place a checkout of the V2 branch at the pinned
#    commit. Never clone, pull, or move a branch while the runtime runs.
sudo install -d -m 0755 /opt/comet-fpl
sudo git clone --branch claude/comet-fpl-v2-architecture-mqrj8f --single-branch \
  <authorized-repository-url> /opt/comet-fpl/checkout
sudo git -C /opt/comet-fpl/checkout checkout --detach <pinned-v2-commit-sha>

# 1. Place the operator-provided CHECKPOINTED operational database (with source and
#    history) where --db will point. Create its service identity before copying the DB:
if ! id comet-fpl >/dev/null 2>&1; then
  sudo useradd --system --home-dir /var/lib/comet-fpl --shell /usr/sbin/nologin \
    --no-create-home comet-fpl
fi
sudo install -d -m 0750 -o comet-fpl -g comet-fpl /var/lib/comet-fpl/db /var/lib/comet-fpl/runs
sudo install -m 0640 -o comet-fpl -g comet-fpl <provided-operational.duckdb> \
  /var/lib/comet-fpl/db/operational.duckdb

# 2. Bootstrap everything (validation happens before any mutation):
sudo sh /opt/comet-fpl/checkout/deploy/sdp-primary/install.sh --pin <pinned-v2-commit-sha>

# 3. Start / stop / status:
systemctl list-timers comet-fpl-sdp-capture.timer
sudo systemctl start comet-fpl-sdp-capture.service      # one cycle now (pre-deadline too)
sudo systemctl stop comet-fpl-sdp-capture.timer         # halt the schedule
sudo systemctl stop comet-fpl-sdp-capture.service       # SIGINT: best-effort receipt + lock
                                                        # cleanup; SIGKILL/WAL recovery is manual
systemctl status comet-fpl-sdp-capture.timer
journalctl -u comet-fpl-sdp-capture.service -n 200

# 4. Health (read-only; nonzero also covers unproven freshness under the explicit bound):
sudo systemctl start comet-fpl-sdp-health.service
sudo systemctl status comet-fpl-sdp-health.service
sudo -u comet-fpl /opt/comet-fpl/venv/bin/python -m fpl.jobs.sdp_capture_health \
  --runs /var/lib/comet-fpl/runs --db /var/lib/comet-fpl/db/operational.duckdb \
  --max-success-age-hours 30
```

The runtime captures and normalizes only. The pre-deadline forecast stays independently
callable from the same pinned checkout (see `docs/sdp-primary-operations.md`); point it at
the operational database with `--db /var/lib/comet-fpl/db/operational.duckdb`.

## Storage, retention, restore

- State root `/var/lib/comet-fpl`: `db/operational.duckdb`, `runs/<run_id>/` receipts,
  `backups/` for operator-made copies. Service umask 0027, directories 0750, unprivileged
  `comet-fpl` user only. Both `--db` and `--runs` must resolve under
  `/var/lib/comet-fpl`; `install.sh` rejects anything else before mutating.
- The source operational database is roughly **1.4 GB**, and every cycle writes a full
  `before.duckdb` backup into its receipt directory, so receipts grow by about that much
  per day. The runtime never prunes anything - failed and malformed receipts are
  preserved as evidence. Retention is an explicit operator decision: retire a redundant
  `before.duckdb` only after verifying that another retained copy contains every immutable
  raw, prediction and outcome record. Preserve each published forecast's exact
  `forecast-source.duckdb`; receipts alone do not reproduce its database hash. Keep
  `report.json`, inventories, and logs long enough to reconstruct every published
  prospective vintage (per `docs/sdp-primary-operations.md`). Never edit or delete a
  failed receipt to make a dashboard look healthy.
- Recovery: stop the timer and service and preserve the current database, WAL and receipts
  before attempting recovery. Work on a separate recovery copy. An older backup lacks newer
  source versions and ledger records: reconcile and retain those records with their original
  times before resuming production. Never overwrite the sole surviving copy or revive an old
  provider version by discarding a later correction. After the recovered database is complete
  and checkpointed, verify one capture cycle and its health report before re-enabling the timer.
