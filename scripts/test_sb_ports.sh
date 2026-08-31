#!/usr/bin/env bash
# Port-block allocation tests: unique non-overlapping 5-port blocks per
# server instance, recorded in instance.env, starting at 27100. Pure logic
# against a temp instances dir; no server binary needed. Part of `make test`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SB="$ROOT/scripts/sb"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
INST="$TMP/instances"
mkdir -p "$INST"

fail=0
expect_eq() {
  if [[ "$2" != "$3" ]]; then
    echo "FAIL: $1 (got '$2' want '$3')" >&2
    fail=1
  fi
}

# shellcheck disable=SC1090 # extract alloc_server_ports without running main
source /dev/stdin <<<"$(sed -n '/^alloc_server_ports()/,/^}/p' "$SB")"

# Empty instances dir: first block is 27100.
expect_eq "first block 27100" "$(alloc_server_ports)" "27100"

# One existing server at 27100: next block skips to 27105.
mkdir -p "$INST/srv-a"
printf 'SERVER_KIND=server\nSERVER_PORT=27100\n' > "$INST/srv-a/instance.env"
expect_eq "second block 27105" "$(alloc_server_ports)" "27105"

# A server at 27105 forces the third to 27110.
mkdir -p "$INST/srv-b"
printf 'SERVER_KIND=server\nSERVER_PORT=27105\n' > "$INST/srv-b/instance.env"
expect_eq "third block 27110" "$(alloc_server_ports)" "27110"

# A hole at 27105 is filled before climbing: remove srv-b's claim.
rm "$INST/srv-b/instance.env"
expect_eq "hole reused" "$(alloc_server_ports)" "27105"

# Client instances (no SERVER_PORT) never block allocation.
mkdir -p "$INST/client-x"
printf 'SANDBOX_NAME=client-x\n' > "$INST/client-x/instance.env"
expect_eq "client ignored" "$(alloc_server_ports)" "27105"

# Non-numeric garbage in SERVER_PORT must not crash the allocator.
mkdir -p "$INST/srv-bad"
printf 'SERVER_PORT=not-a-number\n' > "$INST/srv-bad/instance.env"
next="$(alloc_server_ports)" || { echo "FAIL: allocator crashed on garbage" >&2; fail=1; }
if [[ "$next" != "27105" ]]; then
  echo "FAIL: garbage claim changed allocation (got '$next' want 27105)" >&2
  fail=1
fi

if [[ "$fail" -ne 0 ]]; then
  echo "sb_ports: FAILED" >&2
  exit 1
fi
echo "sb_ports: ok"
