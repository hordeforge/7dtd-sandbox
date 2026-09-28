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

# --- an interrupted copy leaves no debris ---------------------------------
#
# Every failure path above ends on its own and is cleaned up by the function
# that owns the temp. A Ctrl-C did not: the staging tree, and during a create
# the whole partial instance directory, stayed in instances/ with the pid of a
# run nobody has any record of, one per interrupted run. A lab that wipes and
# re-creates instances all day fills its own disk that way, and a partial
# instance refuses every retry with "already exists".
#
# The signal goes to a process group, not to `sb` alone, because that is what
# a terminal sends: `cp` has to die too, or it keeps writing into a tree the
# handler is deleting. It is TERM rather than INT because a shell started in
# the background inherits SIGINT ignored and cannot trap it, so an INT here
# would be swallowed and the case would prove nothing.
# interrupt_group <start> <path-that-appears-while-it-runs>
# Returns 0 when the run was caught mid-copy, 1 when it finished first.
interrupt_group() {
  local start="$1" appear="$2" pid pgid i
  setsid bash -c "$start" >/dev/null 2>&1 &
  pid=$!
  # The group id from /proc rather than `ps -o pgid=`: no fork, and the field
  # is the third one after the comm field.
  for ((i = 0; i < 200; i++)); do
    if [[ -r "/proc/$pid/stat" ]]; then
      pgid="$(sed 's/^.*) //' "/proc/$pid/stat" | awk '{print $3}')"
      [[ -n "$pgid" ]] && break
    fi
    sleep 0.01
  done
  for ((i = 0; i < 200; i++)); do
    if compgen -G "$appear" >/dev/null; then
      local own
      own="$(sed 's/^.*) //' "/proc/$$/stat" | awk '{print $3}')"
      # Never signal this gate's own group: if the child somehow shares it,
      # the case is reported as not reached rather than killing the run.
      if [[ -z "$pgid" || "$pgid" == "$own" ]]; then
        break
      fi
      kill -TERM -- "-$pgid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      return 0
    fi
    sleep 0.01
  done
  wait "$pid" 2>/dev/null || true
  return 1
}

# A base big enough that the copy is still running a few hundred milliseconds
# in, which is what makes the interrupt land inside it.
SLOW_BASE="$TMP/slow-base"
mkdir -p "$SLOW_BASE"
touch "$SLOW_BASE/7DaysToDieServer.x86_64"
for ((i = 0; i < 4000; i++)); do : > "$SLOW_BASE/f$i"; done
echo "the tree the wipe below has to survive" > "$INST/game/marker-old"

if interrupt_group "env SANDBOX_HOME='$TMP' SANDBOX_INSTANCES='$TMP/instances' \
    SANDBOX_SERVER_BASE_GAME='$SLOW_BASE' '$SB' wipe srv-demo" \
   "$INST/game.incoming.*"; then
  check "an interrupted wipe left no staging debris" \
    test -z "$(find "$INST" -maxdepth 1 -name 'game.incoming.*' -print -quit)"
  check "an interrupted wipe left no replaced-tree debris" \
    test -z "$(find "$INST" -maxdepth 1 -name 'game.replaced.*' -print -quit)"
  # The tree the wipe was replacing is still the instance's own: the one it
  # was copied from is the slow base, which carries no marker.
  check "an interrupted wipe kept the instance's own game tree" \
    test -f "$INST/game/marker-old"
else
  echo "NOTE: the copy finished before the interrupt landed; the wipe path is untested here"
fi

if interrupt_group "env SANDBOX_HOME='$TMP' SANDBOX_INSTANCES='$TMP/instances' \
    SANDBOX_SERVER_BASE_GAME='$SLOW_BASE' '$SB' create-server srv-slow" \
   "$TMP/instances/srv-slow"; then
  check "an interrupted create left no partial instance directory" \
    test ! -e "$TMP/instances/srv-slow"
  check "an interrupted create left no staging debris" \
    test -z "$(find "$TMP/instances" -maxdepth 1 -name 'game.incoming.*' -print -quit)"
else
  echo "NOTE: the copy finished before the interrupt landed; the create path is untested here"
fi
# The interrupted create may have left the instance behind if the run finished
# first, and a later case wants a clean name either way.
rm -rf "$TMP/instances/srv-slow"

# --- the tree moved aside comes back ---------------------------------------
#
# publish_tree's window between the two renames is microseconds wide, so the
# case is driven through the handler directly: that window is the one place
# where cleaning up an interrupted run wrongly would delete the only copy of an
# instance's game tree.
check "an interrupted publish puts the moved-aside tree back" \
  bash -c "set --; . '$SB' >/dev/null 2>&1
           mkdir -p '$TMP/rt/game'
           : > '$TMP/rt/game/keepme'
           sb_own_restore '$TMP/rt/game.replaced.9' '$TMP/rt/game'
           mv '$TMP/rt/game' '$TMP/rt/game.replaced.9'
           sb_own_pending '$TMP/rt/game.replaced.9'
           sb_settle_pending
           test -f '$TMP/rt/game/keepme' && test ! -e '$TMP/rt/game.replaced.9'"

if [[ "$fail" -ne 0 ]]; then
  echo "test_sb_copy: FAILED" >&2
  exit 1
fi
echo "test_sb_copy: ok"
