#!/bin/sh
# Bootstrap and install for the SDP primary remote runtime (Linux, systemd, root).
# The pinned checkout must already exist at /opt/comet-fpl/checkout; this script never
# clones, pulls, moves a branch, or mutates anything inside the checkout.
#
# Deployment prerequisites (installed by the operator, not by this script):
#   - systemd (timer/service management), git
#   - an operator-installed SYSTEM Python 3.12 (uv is pinned to system interpreters
#     only: it never downloads a private interpreter the unprivileged service user and
#     ProtectHome=true could not execute)
#   - uv (https://docs.astral.sh/uv/), used with the repository's uv.lock via
#     `uv sync --frozen`; the lockfile is never rewritten and resolution is never
#     re-done from unpinned ranges
#   - an operator-provided CHECKPOINTED operational database with source/history
#     (a schema-only database is NOT forecast-ready)
#
# Usage:
#   sudo sh ./install.sh --pin <40-hex-commit-sha> [--db PATH] [--runs PATH]
#                     [--health-max-age-hours N] [--init-empty-schema]
set -eu

CHECKOUT=/opt/comet-fpl/checkout
VENV=/opt/comet-fpl/venv
STATE_DIR=/var/lib/comet-fpl
SERVICE_USER=comet-fpl
ENV_FILE=/etc/default/comet-fpl-sdp
UNIT_DIR=/etc/systemd/system
DEPLOY_DIR="$CHECKOUT/deploy/sdp-primary"
VERIFY_PIN_BIN=/usr/local/sbin/comet-fpl-verify-pin

PIN=""
DB="$STATE_DIR/db/operational.duckdb"
RUNS="$STATE_DIR/runs"
HEALTH_MAX_AGE_HOURS=30
INIT_EMPTY_SCHEMA=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --pin) [ "$#" -ge 2 ] || { echo "--pin needs a value" >&2; exit 1; }; PIN="$2"; shift 2 ;;
        --db) [ "$#" -ge 2 ] || { echo "--db needs a value" >&2; exit 1; }; DB="$2"; shift 2 ;;
        --runs) [ "$#" -ge 2 ] || { echo "--runs needs a value" >&2; exit 1; }; RUNS="$2"; shift 2 ;;
        --health-max-age-hours)
            [ "$#" -ge 2 ] || { echo "--health-max-age-hours needs a value" >&2; exit 1; }
            HEALTH_MAX_AGE_HOURS="$2"; shift 2
            ;;
        --init-empty-schema) INIT_EMPTY_SCHEMA=1; shift ;;
        *) echo "unknown argument: $1" >&2; exit 1 ;;
    esac
done

fail() {
    echo "refusing to install: $1" >&2
    exit 1
}

# ---- validation, strictly before any mutation ---------------------------------------
[ "$(id -u)" -eq 0 ] || fail "run as root"
case "$PIN" in
    ''|*[!0-9a-f]*) fail "--pin must be a 40-hex-character commit SHA" ;;
esac
[ "$(printf %s "$PIN" | wc -c)" -eq 40 ] || fail "--pin must be a 40-hex-character commit SHA"

# The bound must be finite and positive: digits with at most one decimal point.
case "$HEALTH_MAX_AGE_HOURS" in
    ''|*[!0-9.]*) fail "--health-max-age-hours must be a finite positive number of hours" ;;
    .*|.*.|*.|*.*.*) fail "--health-max-age-hours must be a finite positive number of hours" ;;
esac
awk -v v="$HEALTH_MAX_AGE_HOURS" 'BEGIN { exit !(v > 0) }' \
    || fail "--health-max-age-hours must be a finite positive number of hours"

# Persist-only paths: must resolve inside /var/lib/comet-fpl with a conservative
# character set (no whitespace or shell metacharacters). Paths are later passed to
# Python as argv, never interpolated into code.
for path in "$DB" "$RUNS"; do
    case "$path" in
        ''|*[!A-Za-z0-9/._-]*) fail "unsafe path (whitespace or special characters): $path" ;;
    esac
done
resolved_db="$(realpath -m "$DB")"
resolved_runs="$(realpath -m "$RUNS")"
case "$resolved_db" in "$STATE_DIR"/?*) ;; *) fail "--db must live under $STATE_DIR" ;; esac
case "$resolved_runs" in "$STATE_DIR"/?*) ;; *) fail "--runs must live under $STATE_DIR" ;; esac
[ "$resolved_runs" != "$STATE_DIR" ] || fail "--runs must be a directory under $STATE_DIR"

[ -d "$CHECKOUT/.git" ] || fail "missing pinned checkout: $CHECKOUT"
[ -f "$CHECKOUT/uv.lock" ] || fail "missing uv.lock in $CHECKOUT"
[ -d "$DEPLOY_DIR" ] || fail "missing deploy package: $DEPLOY_DIR"
HEAD="$(git -C "$CHECKOUT" rev-parse HEAD)"
[ "$HEAD" = "$PIN" ] || fail "checkout HEAD $HEAD does not equal --pin $PIN"
command -v uv >/dev/null 2>&1 || fail "uv is a deployment prerequisite; install it first"
command -v sudo >/dev/null 2>&1 || fail "sudo is required to run steps as the service user"
command -v python3.12 >/dev/null 2>&1 \
    || fail "operator-installed system python3.12 is a prerequisite; uv is pinned to system interpreters only and never downloads one"

# ---- mutations ----------------------------------------------------------------------
# 1. Unprivileged system user; no login shell, no home creation beyond the state dir.
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin --no-create-home \
        "$SERVICE_USER"
fi

# 2. Persistent state: database, receipts, logs, operator backups. Failed receipts are
#    never auto-pruned. Each cycle adds roughly one full database backup (~1.4 GB source
#    database), so retention is an explicit operator decision.
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$STATE_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$resolved_runs"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$(dirname "$resolved_db")"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$STATE_DIR/backups"

# 3. Environment file (no secret exists in this runtime). Never overwrite an existing one.
if [ -e "$ENV_FILE" ]; then
    echo "environment file already exists, leaving it untouched: $ENV_FILE" >&2
else
    {
        printf 'SDP_DB=%s\n' "$resolved_db"
        printf 'SDP_RUNS=%s\n' "$resolved_runs"
        printf 'SDP_CODE_PIN=%s\n' "$PIN"
        printf 'SDP_HEALTH_MAX_AGE_HOURS=%s\n' "$HEALTH_MAX_AGE_HOURS"
        printf 'PYTHONUNBUFFERED=1\n'
    } > "$ENV_FILE"
    chmod 0644 "$ENV_FILE"
fi

# 4. Project environment from the repository uv.lock: frozen resolution, explicit
#    environment, system Python 3.12 only (no interpreter downloads), project installed
#    editable, lockfile untouched.
UV_PROJECT_ENVIRONMENT="$VENV" UV_PYTHON_PREFERENCE=only-system UV_PYTHON_DOWNLOADS=never \
    uv sync --frozen --project "$CHECKOUT" --python 3.12
[ -x "$VENV/bin/python" ] || fail "uv did not produce $VENV/bin/python"

# 5. The verify-pin guard runs from /usr/local/sbin; the checkout is never mutated.
install -m 0755 "$DEPLOY_DIR/verify-pin.sh" "$VERIFY_PIN_BIN"

# 6. Operational database. Import an operator-provided checkpointed database with
#    source/history; a schema-only database is NOT forecast-ready. The path is passed
#    as argv, never interpolated into Python source.
if [ -f "$resolved_db" ]; then
    sudo -u "$SERVICE_USER" "$VENV/bin/python" -c \
        "import duckdb, sys; con = duckdb.connect(sys.argv[1], read_only=True); con.execute('SELECT 1'); con.close()" \
        "$resolved_db" || fail "provided database at $resolved_db is not readable by $SERVICE_USER"
else
    if [ "$INIT_EMPTY_SCHEMA" -eq 1 ]; then
        sudo -u "$SERVICE_USER" "$VENV/bin/python" -c \
            "from fpl.storage.db import initialise; import sys; initialise(sys.argv[1]).close()" \
            "$resolved_db"
        echo "WARNING: $resolved_db is schema-only: no archive history is loaded and it" >&2
        echo "WARNING: is NOT forecast-ready. Load/publish history separately before any" >&2
        echo "WARNING: forecast use; daily capture alone fills current-cycle data." >&2
    else
        fail "no database at $resolved_db; place an operator-provided CHECKPOINTED operational database there (cp as $SERVICE_USER, 0640/0750), or pass --init-empty-schema for an explicitly non-forecast-ready schema-only database"
    fi
fi

# 7. Root-owned checkouts must stay usable by the service user; verify-pin handles git's
#    dubious-ownership refusal narrowly. These checks catch filesystem-level mistakes.
sudo -u "$SERVICE_USER" test -r "$CHECKOUT/pyproject.toml" \
    || fail "$SERVICE_USER cannot read the checkout; fix permissions (keep it root-owned)"
sudo -u "$SERVICE_USER" test -x "$VENV/bin/python" \
    || fail "$SERVICE_USER cannot execute $VENV/bin/python"

# 8. Unit files, reload, enable the daily timer. The oneshot services are started by the
#    timer or manually, never enabled at boot.
install -m 0644 "$DEPLOY_DIR/comet-fpl-sdp-capture.service" "$UNIT_DIR/"
install -m 0644 "$DEPLOY_DIR/comet-fpl-sdp-capture.timer" "$UNIT_DIR/"
install -m 0644 "$DEPLOY_DIR/comet-fpl-sdp-health.service" "$UNIT_DIR/"
systemctl daemon-reload
systemctl enable --now comet-fpl-sdp-capture.timer

cat <<EOF

Installed. Common operations:

  systemctl list-timers comet-fpl-sdp-capture.timer      # next scheduled run
  sudo systemctl start comet-fpl-sdp-capture.service     # one capture cycle now
  sudo systemctl stop comet-fpl-sdp-capture.timer        # stop the daily schedule
  sudo systemctl stop comet-fpl-sdp-capture.service      # SIGINT: best-effort receipt + lock cleanup
  sudo systemctl start comet-fpl-sdp-health.service      # read-only health, nonzero on fail
  sudo systemctl status comet-fpl-sdp-health.service
  journalctl -u comet-fpl-sdp-capture.service -n 100

Receipts: $resolved_runs/<run_id>/report.json (never pruned by the runtime).
EOF
