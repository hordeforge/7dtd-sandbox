#!/usr/bin/env bash
# Concurrent `sb` invocations against one instances tree.
#
# Two harnesses can drive the same instance at the same time, and every
# create / up / render-config is a check-then-act over shared state: the
# existence test, the recorded port block, the running-proc scan. Without a
# lock those sections interleave, and the loser is a half-built instance, a
# double-bound port, or a lost declaration. Part of `make test`; needs no
# game, no Proton, no steamcmd.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SB="$ROOT/scripts/sb"
SBCONFIG="$ROOT/scripts/sbconfig.py"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail=0
expect_eq() { # expect_eq <desc> <got> <want>
  if [[ "$2" != "$3" ]]; then
    echo "FAIL: $1 (got '$2' want '$3')" >&2
    fail=1
  fi
}

# A minimal server base: create-server needs the binary and a template to
# render, nothing else. The copy is the slow part, which is what widens the
# window between the existence test and the copy far enough to lose.
BASE="$TMP/base/server-game"
mkdir -p "$BASE/Mods/0_TFP_Harmony" "$BASE/Mods/RealEarth"
touch "$BASE/7DaysToDieServer.x86_64"
cat > "$BASE/serverconfig.xml" <<'EOF'
<?xml version="1.0"?>
<ServerSettings>
	<property name="ServerPort"						value="26900"/>
	<property name="TelnetPort"					value="8081"/>
	<property name="ServerName"					value="My Game Host"/>
	<property name="GameWorld"					value="RWG"/>
	<property name="EACEnabled"						value="true"/>
	<property name="MaxSpawnedZombies"			value="64"/>
</ServerSettings>
EOF

sb() { env SANDBOX_HOME="$TMP" SANDBOX_INSTANCES="$TMP/instances" "$SB" "$@"; }

# Run each argument as its own `sb` invocation, all started before any is
# waited on. Prints "<rc> <index>" for every invocation, in start order.
run_parallel() {
  local pids=() out="$TMP/parallel"
  : > "$out"
  local i=0
  for cmdline in "$@"; do
    # shellcheck disable=SC2086 # each argument is a command line, split on spaces
    sb $cmdline >/dev/null 2>&1 &
    pids+=("$!:$i")
    i=$(( i + 1 ))
  done
  local entry rc
  for entry in "${pids[@]}"; do
    rc=0
    wait "${entry%%:*}" || rc=$?
    echo "$rc ${entry#*:}" >> "$out"
  done
  cat "$out"
}

succeeded() { # succeeded <results>
  grep -c '^0 ' <<<"$1" || true
}

failed() { # failed <results>
  grep -vc '^0 ' <<<"$1" || true
}

# --- one create wins, the rest are refused, the instance is whole -----------

results="$(run_parallel \
  "create-server srv-race" "create-server srv-race" "create-server srv-race")"
expect_eq "exactly one create-server of a name wins" "$(succeeded "$results")" "1"

INST="$TMP/instances/srv-race"
[[ -f "$INST/instance.env" ]] \
  || { echo "FAIL: the winning create-server left no instance.env" >&2; fail=1; }
[[ -f "$INST/game/7DaysToDieServer.x86_64" ]] \
  || { echo "FAIL: the winning create-server left no game copy" >&2; fail=1; }
[[ -f "$INST/game/platform.cfg" ]] \
  || { echo "FAIL: the winning create-server never finished its writes" >&2; fail=1; }
grep -qx "SERVER_KIND='server'" "$INST/instance.env" \
  || { echo "FAIL: instance.env is not a complete server declaration" >&2; fail=1; }
# A loser that reached its own copy_tree would have deleted the winner's tree
# (copy_tree rm -rf's its destination) and left an unpruned base mod.
[[ -d "$INST/game/Mods/0_TFP_Harmony" && ! -e "$INST/game/Mods/RealEarth" ]] \
  || { echo "FAIL: a losing create raced the winner's tree" >&2; fail=1; }
# A torn instance.props (truncated by an interrupted writer) is what the next
# render reads: absent or empty, never half a declaration.
[[ ! -s "$INST/instance.props" ]] \
  || { echo "FAIL: instance.props was written by a losing create" >&2; fail=1; }

# --- concurrent creates of different names never share a port block --------

results="$(run_parallel \
  "create-server srv-p1" "create-server srv-p2" "create-server srv-p3" \
  "create-server srv-p4")"
expect_eq "every distinct-name create succeeded" "$(failed "$results")" "0"
ports="$(sed -n "s/^SERVER_PORT='\(.*\)'$/\1/p" "$TMP"/instances/srv-p?/instance.env | sort -u)"
expect_eq "each instance recorded its own port block" "$(wc -l <<<"$ports")" "4"
# Name-derived and independent of creation order: srv-p4 keeps the block it
# recorded, and a fresh allocation for it now skips whatever the others hold.
expect_eq "an instance keeps its own block" \
  "$(python3 "$SBCONFIG" port-block srv-p4 --instances "$TMP/instances")" \
  "$(sed -n "s/^SERVER_PORT='\(.*\)'$/\1/p" "$TMP/instances/srv-p4/instance.env")"

# --- concurrent declarations all survive -----------------------------------

sb render-config srv-race GameWorld=Navezgane >/dev/null
results="$(run_parallel \
  "render-config srv-race MaxSpawnedZombies=0" \
  "render-config srv-race MaxPlayers=8" \
  "render-config srv-race GameDifficulty=2" \
  "render-config srv-race GameMode=Survival" \
  "render-config srv-race MaxWorldSize=8192")"
expect_eq "every concurrent declaration succeeded" "$(failed "$results")" "0"
for kv in GameWorld=Navezgane MaxSpawnedZombies=0 MaxPlayers=8 \
          GameDifficulty=2 GameMode=Survival MaxWorldSize=8192
do
  grep -qxF "$kv" "$INST/instance.props" \
    || { echo "FAIL: declaration $kv was lost to a concurrent writer" >&2; fail=1; }
  key="${kv%%=*}"
  got="$(python3 "$SBCONFIG" get "$INST/serverconfig.xml" "$key" 2>/dev/null || echo absent)"
  expect_eq "declared $key reached the config" "$got" "${kv#*=}"
done
# instance.props is published by rename, so no writer leaves a temp fragment
# beside it for the next reader to pick up.
expect_eq "no temp fragments left beside instance.props" \
  "$(find "$INST" -maxdepth 1 -name 'instance.props.tmp*' | wc -l)" "0"

# --- concurrent staging of different modlets -------------------------------

for mod in one two; do
  mkdir -p "$TMP/src/m-$mod"
  printf '<ModInfo/>\n' > "$TMP/src/m-$mod/ModInfo.xml"
  printf '%s\n' "$mod" > "$TMP/src/m-$mod/payload.txt"
done
results="$(run_parallel "stage srv-race $TMP/src/m-one" "stage srv-race $TMP/src/m-two")"
expect_eq "every concurrent stage succeeded" "$(failed "$results")" "0"
for mod in one two; do
  [[ -f "$INST/game/Mods/m-$mod/payload.txt" ]] \
    || { echo "FAIL: staged modlet m-$mod is missing or half-copied" >&2; fail=1; }
  grep -qx "$mod" "$INST/game/Mods/m-$mod/payload.txt" 2>/dev/null \
    || { echo "FAIL: staged modlet m-$mod has the wrong content" >&2; fail=1; }
done
# Nothing half-staged is left where the game enumerates Mods: copy_tree
# stages into <dst>.incoming.<pid> and renames it into place.
expect_eq "no staging fragment left in Mods" \
  "$(find "$INST/game/Mods" -maxdepth 1 -name '*.incoming.*' | wc -l)" "0"

# --- a refusal still writes nothing ----------------------------------------

rc=0
sb render-config srv-race ServerPort=27000 >/dev/null 2>&1 || rc=$?
expect_eq "an instance-owned property is still refused" "$rc" "2"
if grep -qxF 'ServerPort=27000' "$INST/instance.props"; then
  echo "FAIL: a refused property was written anyway" >&2
  fail=1
fi

if [[ $fail -ne 0 ]]; then
  echo "sb_lock: FAILED" >&2
  exit 1
fi
echo "sb_lock: ok"
