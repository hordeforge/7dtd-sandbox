#!/usr/bin/env bash
# Port-block allocation: an instance's 5-port block is derived from its name,
# not from creation order, so the same name yields the same ports on any
# machine and a recorded run can be reproduced elsewhere. A block another
# instance already recorded is skipped by a deterministic forward probe.
# Pure logic against a temp instances dir; no server binary. Part of `make test`.
# shellcheck disable=SC2154 # the functions under test are sourced out of sb, so
# the names they set (SERVER_PORT, PORT_MAX, ...) are not assignments here
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
# The interpreter check travels with it: allocating a block shells out to
# sbconfig.py, so the helper under test now needs its interpreter too.
source /dev/stdin <<<"$(sed -n '/^SB_PY=/p;/^SB_PY_MIN=/p;/^PORT_BLOCK_SIZE=/p;/^PORT_BLOCK_LAST_OFFSET=/p;/^PORT_MAX=/p;/^die()/,/^}/p;/^require_python()/,/^}/p;/^alloc_server_ports()/,/^}/p' "$SB")"

# --- the block a declaration has to fit in ----------------------------------

# instance_server_ports is the gate a hand-edited instance.env passes through,
# so the range it accepts is the range a server is ever started on.
# shellcheck disable=SC1090,SC1091 # sourced out of sb, as the allocator below
source /dev/stdin <<<"$(sed -n '/^instance_server_ports()/,/^}/p' "$SB")"

# expect_refused <label> <SERVER_PORT> <SERVER_TELNET_PORT>
expect_refused() {
  local inst="$TMP/env-$2-$3"
  mkdir -p "$inst"
  printf 'SERVER_PORT=%s\nSERVER_TELNET_PORT=%s\n' "$2" "$3" > "$inst/instance.env"
  if ( instance_server_ports "$inst" ) >/dev/null 2>&1; then
    echo "FAIL: $1: SERVER_PORT=$2 was accepted" >&2
    fail=1
  fi
}

expect_refused "telnet off the end of the port space" 65535 65536
expect_refused "spare ports off the end of the port space" 65532 65533
expect_refused "a port wider than the shell's integer" 9223372036854775808 9223372036854775809
expect_refused "not a port" 0 1

# The last block that does fit, and one past it: 65531..65535 is legal,
# 65532..65536 is not.
accept_dir="$TMP/env-accepted"
mkdir -p "$accept_dir"
printf 'SERVER_PORT=65531\nSERVER_TELNET_PORT=65532\n' > "$accept_dir/instance.env"
instance_server_ports "$accept_dir" \
  || { echo "FAIL: a block ending exactly at $PORT_MAX was refused" >&2; fail=1; }
expect_eq "the last legal block's port" "$SERVER_PORT" 65531
expect_eq "the last legal block's telnet" "$SERVER_TELNET_PORT" 65532

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
