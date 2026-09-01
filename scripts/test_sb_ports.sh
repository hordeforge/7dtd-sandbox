#!/usr/bin/env bash
# Port-block allocation: an instance's 5-port block is derived from its name,
# not from creation order, so the same name yields the same ports on any
# machine and a recorded run can be reproduced elsewhere. A block another
# instance already recorded is skipped by a deterministic forward probe.
# Pure logic against a temp instances dir; no server binary. Part of `make test`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SB="$ROOT/scripts/sb"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
INST="$TMP/instances"
mkdir -p "$INST"
# alloc_server_ports reads INSTANCES_DIR and SB_CONFIG (both set at sb
# top-level); export them when sourcing the function alone so set -u holds.
export INSTANCES_DIR="$INST"
export SB_CONFIG="$ROOT/scripts/sbconfig.py"

fail=0
expect_eq() {
  if [[ "$2" != "$3" ]]; then
    echo "FAIL: $1 (got '$2' want '$3')" >&2
    fail=1
  fi
}

# shellcheck disable=SC1090,SC1091 # extract alloc_server_ports without running main
source /dev/stdin <<<"$(sed -n '/^alloc_server_ports()/,/^}/p' "$SB")"

# --- a name determines its block --------------------------------------------

lab="$(alloc_server_ports srv-lab)"
expect_eq "same name, same block" "$(alloc_server_ports srv-lab)" "$lab"
if (( lab < 27100 )) || (( (lab - 27100) % 5 != 0 )); then
  echo "FAIL: block $lab is not 5-aligned from 27100" >&2
  fail=1
fi

other="$(alloc_server_ports srv-other)"
if [[ "$other" == "$lab" ]]; then
  echo "FAIL: two names collided with nothing recorded" >&2
  fail=1
fi

# Creation order must not matter: an unrelated instance appearing first does
# not shift the block a name would have got.
mkdir -p "$INST/srv-unrelated"
printf 'SERVER_KIND=server\nSERVER_PORT=27500\n' > "$INST/srv-unrelated/instance.env"
expect_eq "unrelated instance does not shift the block" "$(alloc_server_ports srv-lab)" "$lab"

# --- a recorded block is skipped, deterministically -------------------------

mkdir -p "$INST/srv-squatter"
printf 'SERVER_KIND=server\nSERVER_PORT=%s\n' "$lab" > "$INST/srv-squatter/instance.env"
probed="$(alloc_server_ports srv-lab)"
if [[ "$probed" == "$lab" ]]; then
  echo "FAIL: allocator handed out a block another instance recorded" >&2
  fail=1
fi
expect_eq "probe is deterministic" "$(alloc_server_ports srv-lab)" "$probed"

# An instance does not block itself: re-deriving for a name that already holds
# its block must return that block, not probe past it.
mkdir -p "$INST/srv-self"
self="$(alloc_server_ports srv-self)"
printf 'SERVER_KIND=server\nSERVER_PORT=%s\n' "$self" > "$INST/srv-self/instance.env"
expect_eq "an instance keeps its own block" "$(alloc_server_ports srv-self)" "$self"

# --- claims that are not claims ---------------------------------------------

# Client instances carry no SERVER_PORT and never block allocation.
mkdir -p "$INST/client-x"
printf 'SANDBOX_NAME=client-x\n' > "$INST/client-x/instance.env"
expect_eq "client ignored" "$(alloc_server_ports srv-self)" "$self"

# Non-numeric garbage in SERVER_PORT must not crash the allocator.
mkdir -p "$INST/srv-bad"
printf 'SERVER_PORT=not-a-number\n' > "$INST/srv-bad/instance.env"
next="$(alloc_server_ports srv-self)" || { echo "FAIL: allocator crashed on garbage" >&2; fail=1; }
expect_eq "garbage claim ignored" "$next" "$self"

if [[ "$fail" -ne 0 ]]; then
  echo "sb_ports: FAILED" >&2
  exit 1
fi
echo "sb_ports: ok"
