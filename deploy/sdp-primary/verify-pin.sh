#!/bin/sh
# Fail closed unless the checkout HEAD equals the pinned commit in the environment file
# AND the worktree is clean: any tracked modification or untracked (non-ignored) file is
# code drift under an unchanged HEAD and refuses the start.
#
# Read-only: this script never pulls, checks out, mutates, or chmods anything in the
# checkout. Pulling a mutable branch while the runtime runs is forbidden; a drifted
# checkout must be stopped and the pin consciously re-authorized and updated in
# /etc/default/comet-fpl-sdp instead.
set -eu

usage() {
    echo "usage: $0 <checkout-directory>" >&2
    exit 1
}

[ "$#" -eq 1 ] || usage
checkout="$1"
[ -d "$checkout" ] || { echo "refusing to run: checkout not found: $checkout" >&2; exit 1; }

pin="${SDP_CODE_PIN:-}"
if [ -z "$pin" ]; then
    echo "refusing to run: SDP_CODE_PIN is empty or unset in the environment file" >&2
    exit 1
fi
if [ "$(printf %s "$pin" | wc -c)" -ne 40 ]; then
    echo "refusing to run: SDP_CODE_PIN must be a 40-hex-character commit SHA" >&2
    exit 1
fi
case "$pin" in
    *[!0-9a-f]*)
        echo "refusing to run: SDP_CODE_PIN must be a 40-hex-character commit SHA" >&2
        exit 1
        ;;
esac

# A root-owned checkout makes git refuse with "dubious ownership". Handle it narrowly:
# safe.directory scoped through git's protected-config environment to exactly this one
# checkout path (never a wildcard), exported only for the git calls in this script.
GIT_CONFIG_COUNT=1
GIT_CONFIG_KEY_0="safe.directory"
GIT_CONFIG_VALUE_0="$checkout"
export GIT_CONFIG_COUNT GIT_CONFIG_KEY_0 GIT_CONFIG_VALUE_0

head="$(git -C "$checkout" rev-parse HEAD 2>/dev/null)" || {
    echo "refusing to run: cannot read HEAD of $checkout (is git installed?)" >&2
    exit 1
}
dirty="$(git -C "$checkout" status --porcelain 2>/dev/null)" || {
    echo "refusing to run: cannot read worktree status of $checkout" >&2
    exit 1
}
if [ -n "$dirty" ]; then
    echo "refusing to run: checkout worktree is dirty (tracked or untracked code drift)" >&2
    printf '%s\n' "$dirty" | head -n 10 >&2
    exit 1
fi
if [ "$head" != "$pin" ]; then
    echo "refusing to run: checkout HEAD $head does not equal pinned commit $pin" >&2
    exit 1
fi
echo "code pin verified: $head (worktree clean)"
