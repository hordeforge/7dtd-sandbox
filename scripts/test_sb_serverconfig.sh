#!/usr/bin/env bash
# The declarative, deterministic instance contract, at the sb level.
#
# An instance is described by instance.env (identity, ports, admins) plus
# instance.props (declared serverconfig properties). Its serverconfig is
# rebuilt from the pristine base template every time, so what the server reads
# depends only on what is declared now, never on what a previous run left
# behind. Part of `make test`; needs no game, no Proton, no steamcmd.
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

# Value of the first active (not commented out) property in a serverconfig.
active_value() { # active_value <cfg> <key>
  python3 "$SBCONFIG" get "$1" "$2" 2>/dev/null || echo "(absent)"
}

INST="$TMP/instances/srv-demo"
mkdir -p "$INST/game" "$INST/userdata/Saves" "$INST/logs"

# The stock template shapes that matter: tab padding, a trailing comment, and a
# commented-out UserDataFolder.
cat > "$INST/game/serverconfig.xml" <<'EOF'
<?xml version="1.0"?>
<ServerSettings>
	<property name="ServerPort"						value="26900"/>				<!-- Port -->
	<property name="TelnetPort"					value="8081"/>
	<property name="ServerName"					value="My Game Host"/>
	<property name="EACEnabled"						value="true"/>
	<property name="MaxSpawnedZombies"			value="64"/>
	<!-- <property name="UserDataFolder"			value="absolute_path"/> -->
	<!-- <property name="GameWorld"				value="RANDOM WORLD GENERATION"/> -->
	<!-- <property name="EnemySpawnMode"			value="true"/> -->
</ServerSettings>
EOF

cat > "$INST/instance.env" <<EOF
SANDBOX_NAME=srv-demo
INSTANCE_DIR=$INST
SERVER_GAME=$INST/game
SERVER_USERDATA=$INST/userdata
SERVER_PORT=27105
SERVER_TELNET_PORT=27106
SERVER_CONFIG=$INST/serverconfig.xml
SERVER_PROPS=$INST/instance.props
SERVER_LOG=$INST/logs/server.log
SERVER_ADMINS=client-demo
SERVER_KIND=server
EOF

sb() { env SANDBOX_HOME="$TMP" SANDBOX_INSTANCES="$TMP/instances" "$SB" "$@"; }
cfg="$INST/serverconfig.xml"

# --- a declaration reaches the config, and the instance keeps its own ports --

sb render-config srv-demo GameWorld=Navezgane MaxSpawnedZombies=0 >/dev/null
expect_eq "declared GameWorld"      "$(active_value "$cfg" GameWorld)"         "Navezgane"
expect_eq "declared spawn cap"      "$(active_value "$cfg" MaxSpawnedZombies)" "0"
expect_eq "instance keeps its port" "$(active_value "$cfg" ServerPort)"        "27105"
expect_eq "instance keeps telnet"   "$(active_value "$cfg" TelnetPort)"        "27106"
expect_eq "EAC forced off"          "$(active_value "$cfg" EACEnabled)"        "false"
expect_eq "userdata activated"      "$(active_value "$cfg" UserDataFolder)"    "$INST/userdata"

# The stock commented line must survive: rewriting inside the comment is how a
# server ends up saving under its default userdata while a harness wipes an
# empty tree.
if ! grep -q '^	<!-- <property name="UserDataFolder"' "$cfg"; then
  echo "FAIL: stock commented UserDataFolder was mangled" >&2
  fail=1
fi
expect_eq "single active ServerPort" "$(grep -c 'name="ServerPort"' "$cfg")" "1"

# --- a second declaration adds to the first; it does not replace the world ---

sb render-config srv-demo EnemySpawnMode=false >/dev/null
expect_eq "earlier declaration held"  "$(active_value "$cfg" GameWorld)"      "Navezgane"
expect_eq "new declaration applied"   "$(active_value "$cfg" EnemySpawnMode)" "false"

# --- last write wins per key, and the config is rebuilt, never accumulated ---

sb render-config srv-demo GameWorld=Pregen06k01 >/dev/null
expect_eq "last write wins"     "$(active_value "$cfg" GameWorld)"        "Pregen06k01"
expect_eq "one active GameWorld" \
  "$(grep -c '^[[:space:]]*<property name="GameWorld"' "$cfg")" "1"

# Undeclaring is what a previous run's leftover would defeat: drop the spawn
# cap from the declaration and the base template's own value must come back,
# not the 0 an earlier suite set.
grep -v '^MaxSpawnedZombies=' "$INST/instance.props" > "$INST/props.new"
mv "$INST/props.new" "$INST/instance.props"
sb render-config srv-demo GameWorld=Pregen06k01 >/dev/null
expect_eq "undeclared property returns to the base template" \
  "$(active_value "$cfg" MaxSpawnedZombies)" "64"

# --- a declared key is a literal, not a pattern ---------------------------

# The upsert filtered with `grep -v "^$key="`, so the key was a basic regular
# expression: `.` in one key matched a neighbour's name and deleted a
# declaration it had nothing to do with, and a key holding an unmatched `[`
# made grep fail, which left instance.props holding only the key just
# declared. Two defenses now: a key outside [A-Za-z_][A-Za-z0-9_]* never
# reaches the upsert (asserted below), so no key that does reach it can mean
# anything but itself, and the upsert matches a literal `KEY=` prefix, which is
# what spares the neighbour here.
sb render-config srv-demo Game_World=underscore >/dev/null
sb render-config srv-demo Game_World2=applied >/dev/null
expect_eq "underscore key is applied"   "$(active_value "$cfg" Game_World2)" "applied"
expect_eq "upsert spares its neighbour" "$(active_value "$cfg" Game_World)" "underscore"
grep -v '^Game_World' "$INST/instance.props" > "$INST/props.new"
mv "$INST/props.new" "$INST/instance.props"
sb render-config srv-demo GameWorld=dotted >/dev/null

# A serverconfig names its properties [A-Za-z_][A-Za-z0-9_]*, so a
# pattern-shaped key is refused where it is written rather than recorded, and
# the declarations beside it survive.
for bad in 'Game.World=dot' 'MaxSpawned[Zombies=0'; do
  rc=0
  sb render-config srv-demo "$bad" >/dev/null 2>&1 || rc=$?
  expect_eq "pattern-shaped key '$bad' refused"       "$rc" "2"
  expect_eq "refused key spared its neighbour" "$(active_value "$cfg" GameWorld)" "dotted"
done
expect_eq "refused key was not recorded" \
  "$(grep -c '^Game\.World=' "$INST/instance.props" || true)" "0"

# instance.props is one KEY=VALUE per line, so a value carrying a newline is
# two declarations, the second of which is not one. Refused at the point the
# caller can still see which key it was.
rc=0
sb render-config srv-demo "$(printf 'GameWorld=two\nlines')" >/dev/null 2>&1 || rc=$?
expect_eq "value spanning lines is refused"    "$rc" "2"
expect_eq "refused value left the declaration" "$(active_value "$cfg" GameWorld)" "dotted"

# --- the instance owns its ports and userdata; a caller may not declare them -

for owned in ServerPort TelnetPort UserDataFolder; do
  rc=0
  sb render-config srv-demo "$owned=1" >/dev/null 2>&1 || rc=$?
  expect_eq "$owned refused as a declaration" "$rc" "2"
done

# --- a glob-shaped property name is refused, and costs nothing --------------

# `.*` looks like a legal property name to a caller. A key is the line prefix
# in instance.props, and matching it (and dropping it) used to drop every other
# declaration with it, so one render-config call erased the instance's whole
# declared state. The name charset now refuses it outright, before the
# declaration file is touched.
cp "$INST/instance.props" "$INST/props.before-glob"
rc=0
sb render-config srv-demo '.*=oops' >/dev/null 2>&1 || rc=$?
expect_eq "a glob-shaped key is refused" "$rc" "2"
expect_eq "a refused key changes no declaration" \
  "$(grep -c '^[A-Za-z]' "$INST/instance.props")" \
  "$(grep -c '^[A-Za-z]' "$INST/props.before-glob")"
expect_eq "a refused key is not declared" \
  "$(grep -c '^\.\*=' "$INST/instance.props")" "0"
expect_eq "the config is untouched by the refusal" \
  "$(active_value "$cfg" GameWorld)" "dotted"

# --- the contract is exported, not merely assigned --------------------------

# AGENTS.md documents `eval "$(sb env <name>)"` as a resolution path. A bare
# KEY=value line defines a shell variable and stops there, so a sibling
# harness that spawns a client or a load generator saw nothing.
exported="$(bash -c 'eval "$1"; env' _ "$(sb env srv-demo)")"
for var in SERVER_PORT SERVER_TELNET_PORT SERVER_ADMINS SERVER_CONFIG; do
  if ! grep -q "^$var=" <<<"$exported"; then
    echo "FAIL: sb env did not export $var to a child process" >&2
    fail=1
  fi
done

# --- a malformed declaration is refused where it is written, not later -----
#
# Persisting it would leave the instance permanently broken: every launch
# re-reads instance.props, so the failure would resurface with no record of
# the command that caused it.

for bad in '=Navezgane' 'Game World=Navezgane' 'Game.World=1' 'MaxSpawned.Zombies=0'; do
  rc=0
  sb render-config srv-demo "$bad" >/dev/null 2>&1 || rc=$?
  expect_eq "malformed declaration '$bad' refused" "$rc" "2"
done
if grep -q '=Navezgane$' "$INST/instance.props"; then
  echo "FAIL: a refused declaration was still written to instance.props" >&2
  fail=1
fi

# A hand-edited instance.props is validated where it is read, naming the file
# and the line, so the refusal is actionable.
cp "$INST/instance.props" "$INST/props.good"
printf 'Game.World=1\n' >> "$INST/instance.props"
rc=0
sb render-config srv-demo GameWorld=Navezgane >/dev/null 2>&1 || rc=$?
expect_eq "hand-edited malformed line refused" "$rc" "2"
msg="$(sb render-config srv-demo GameWorld=Navezgane 2>&1 >/dev/null || true)"
if [[ "$msg" != *"instance.props:"* ]]; then
  echo "FAIL: refusal does not name instance.props: $msg" >&2
  fail=1
fi
mv "$INST/props.good" "$INST/instance.props"

# A key the base template never names is inserted, but warned about: the game
# ignores it, and a suite that believed it declared one would be wrong.
warn="$(sb render-config srv-demo MaxSpawnedZombiez=0 2>&1 >/dev/null || true)"
if [[ "$warn" != *"MaxSpawnedZombiez"* ]]; then
  echo "FAIL: an unknown property was not warned about (got '$warn')" >&2
  fail=1
fi
grep -v '^MaxSpawnedZombiez=' "$INST/instance.props" > "$INST/props.new"
mv "$INST/props.new" "$INST/instance.props"

# --- a port block the instance cannot use is refused before the server runs -

cp "$INST/instance.env" "$INST/env.good"
grep -v '^SERVER_TELNET_PORT=' "$INST/instance.env" > "$INST/env.new"
mv "$INST/env.new" "$INST/instance.env"
rc=0
sb render-config srv-demo GameWorld=Navezgane >/dev/null 2>&1 || rc=$?
expect_eq "missing SERVER_TELNET_PORT refused" "$rc" "1"
cp "$INST/env.good" "$INST/instance.env"
sed -i 's/^SERVER_PORT=27105/SERVER_PORT=not-a-port/' "$INST/instance.env"
rc=0
sb render-config srv-demo GameWorld=Navezgane >/dev/null 2>&1 || rc=$?
expect_eq "non-numeric SERVER_PORT refused" "$rc" "1"
cp "$INST/env.good" "$INST/instance.env"

# --- ports are derived from the name, not from creation order ---------------

first="$(python3 "$SBCONFIG" port-block srv-lab)"
expect_eq "same name, same block" "$(python3 "$SBCONFIG" port-block srv-lab)" "$first"
if [[ "$first" == "$(python3 "$SBCONFIG" port-block srv-other)" ]]; then
  echo "FAIL: two different names collided with no instances recorded" >&2
  fail=1
fi
# A block another instance already recorded is skipped, deterministically.
taken="$(python3 "$SBCONFIG" port-block srv-lab --taken "$first")"
if [[ "$taken" == "$first" ]]; then
  echo "FAIL: port-block handed out a block already taken" >&2
  fail=1
fi
expect_eq "probe is deterministic too" \
  "$(python3 "$SBCONFIG" port-block srv-lab --taken "$first")" "$taken"

if [[ "$fail" -ne 0 ]]; then
  echo "sb_serverconfig: FAILED" >&2
  exit 1
fi
echo "sb_serverconfig: ok"
