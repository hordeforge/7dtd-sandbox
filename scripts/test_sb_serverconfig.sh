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
expect_eq "one GameWorld total" "$(grep -c 'name="GameWorld"' "$cfg")"    "1"

# Undeclaring is what a previous run's leftover would defeat: drop the spawn
# cap from the declaration and the base template's own value must come back,
# not the 0 an earlier suite set.
grep -v '^MaxSpawnedZombies=' "$INST/instance.props" > "$INST/props.new"
mv "$INST/props.new" "$INST/instance.props"
sb render-config srv-demo GameWorld=Pregen06k01 >/dev/null
expect_eq "undeclared property returns to the base template" \
  "$(active_value "$cfg" MaxSpawnedZombies)" "64"

# --- the instance owns its ports and userdata; a caller may not declare them -

for owned in ServerPort TelnetPort UserDataFolder; do
  rc=0
  sb render-config srv-demo "$owned=1" >/dev/null 2>&1 || rc=$?
  expect_eq "$owned refused as a declaration" "$rc" "2"
done

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
