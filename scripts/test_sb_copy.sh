#!/usr/bin/env bash
# A failed copy must cost the caller nothing.
#
# Every path that replaces a tree used to delete the old one first and copy
# second. A copy that failed part-way (an unreadable file under the base, a
# full disk, an interrupt) therefore destroyed the tree and then failed to
# rebuild it: `sb wipe` left the instance with no game at all, and the Mods a
# harness had staged into it gone with it. The reflink retry made it worse,
# because the failed first attempt left a partially populated destination and
# `cp` then copied the source *into* that debris, so the retry could report
# success having produced game/server-game/7DaysToDieServer.x86_64.
#
# Part of `make test`; needs no game, no Proton, no steamcmd. The failure is
# provoked with an unreadable file, which only works for a non-root caller, so
# the gate skips itself as root rather than reporting a false pass.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SB="$ROOT/scripts/sb"

TMP="$(mktemp -d)"
trap 'chmod -R u+rwX "$TMP" 2>/dev/null || true; rm -rf "$TMP"' EXIT

fail=0
expect_eq() { # expect_eq <desc> <got> <want>
  if [[ "$2" != "$3" ]]; then
    echo "FAIL: $1 (got '$2' want '$3')" >&2
    fail=1
  fi
}
check() { # check <desc> <condition-as-command...>
  if ! "${@:2}"; then
    echo "FAIL: $1" >&2
    fail=1
  fi
}

if [[ "$(id -u)" -eq 0 ]]; then
  echo "test_sb_copy: skipped (root can read a 0000 file, so the copy cannot be made to fail)"
  exit 0
fi

# A base with one file the caller cannot read, so cp fails part-way through.
# Only the file is made unreadable: an unreadable base *directory* fails the
# copy at the directory entry instead, which is a different error and would
# not exercise the partial-copy path this gate is about.

sb() { env SANDBOX_HOME="$TMP" SANDBOX_INSTANCES="$TMP/instances" "$SB" "$@"; }

# --- a failed wipe leaves the instance as it was ----------------------------

INST="$TMP/instances/srv-demo"
mkdir -p "$INST/game/Mods/StagedMod" "$INST/userdata/Saves" "$INST/logs"
printf '<?xml version="1.0"?>\n<ServerSettings>\n</ServerSettings>\n' > "$INST/game/serverconfig.xml"
cat > "$INST/instance.env" <<EOF
SANDBOX_NAME=srv-demo
SERVER_PORT=27105
SERVER_TELNET_PORT=27106
SERVER_ADMINS=client-demo
SERVER_KIND=server
EOF
: > "$INST/instance.props"
mkdir -p "$TMP/base/server-game"
touch "$TMP/base/server-game/7DaysToDieServer.x86_64"
# Work a harness staged into the instance, which the wipe would destroy.
echo "staged work" > "$INST/game/Mods/StagedMod/ModInfo.xml"
echo "the file that cannot be read" > "$TMP/base/server-game/unreadable.dat"
chmod 000 "$TMP/base/server-game/unreadable.dat"

rc=0
out="$(sb wipe srv-demo 2>&1)" || rc=$?
expect_eq "wipe over an unreadable base fails" "$rc" "1"
check "the failure names the file cp could not read" \
  grep -q "unreadable.dat" <<<"$out"
check "the failure reports cp's own reason, not just 'copy failed'" \
  grep -qi "permission denied" <<<"$out"

check "the instance's game tree survived the failed wipe" test -f "$INST/game/serverconfig.xml"
check "the staged mod survived the failed wipe"      test -f "$INST/game/Mods/StagedMod/ModInfo.xml"
check "no staging debris was left behind"            test -z "$(find "$INST" -maxdepth 1 -name 'game.*' -print -quit)"
check "no replaced-tree debris was left behind"      test -z "$(find "$INST" -maxdepth 1 -name 'game.replaced.*' -print -quit)"

# --- the same copy succeeds once the base is readable ----------------------

chmod 644 "$TMP/base/server-game/unreadable.dat"
rc=0
sb wipe srv-demo >/dev/null 2>&1 || rc=$?
expect_eq "wipe succeeds once the base is readable" "$rc" "0"
check "the wiped game came from the base"  test -f "$INST/game/7DaysToDieServer.x86_64"
check "the staged mod was pruned by the wipe" test ! -e "$INST/game/Mods/StagedMod"
check "no debris after a successful wipe"   test -z "$(find "$INST" -maxdepth 1 -name 'game.*' -print -quit)"

# --- a failed re-stage leaves the staged modlet in place -------------------

CLI="$TMP/instances/cl"
mkdir -p "$CLI/game"
printf 'SANDBOX_NAME=cl\n' > "$CLI/instance.env"
mkdir -p "$TMP/src/GoodMod"
echo '<ModInfo/>' > "$TMP/src/GoodMod/ModInfo.xml"
echo good > "$TMP/src/GoodMod/data.txt"

sb stage cl "$TMP/src/GoodMod" >/dev/null
check "the modlet staged" test -f "$CLI/game/Mods/GoodMod/data.txt"

echo "the file that cannot be read" > "$TMP/src/GoodMod/broken.dat"
chmod 000 "$TMP/src/GoodMod/broken.dat"
rc=0
sb stage cl "$TMP/src/GoodMod" >/dev/null 2>&1 || rc=$?
expect_eq "re-staging a broken build fails" "$rc" "1"
check "the previously staged modlet survived" test -f "$CLI/game/Mods/GoodMod/data.txt"
check "the broken file did not land in the instance" test ! -e "$CLI/game/Mods/GoodMod/broken.dat"
check "no staging debris in Mods" \
  test -z "$(find "$CLI/game/Mods" -maxdepth 1 -mindepth 1 ! -name GoodMod -print -quit)"

chmod 644 "$TMP/src/GoodMod/broken.dat"

if [[ "$fail" -ne 0 ]]; then
  echo "test_sb_copy: FAILED" >&2
  exit 1
fi
echo "test_sb_copy: ok"
