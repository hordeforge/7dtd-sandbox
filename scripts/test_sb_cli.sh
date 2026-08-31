#!/usr/bin/env bash
# sb CLI surface tests: pure-arg cases that need no game, no Proton, no
# steamcmd. Runs against a temp SANDBOX_HOME so instances/ and bases are
# fakes. Part of `make test` (sibling-repo gate pattern).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SB="$ROOT/scripts/sb"

fail=0
check() { # check <desc> <expected-rc> <cmd...>
  local desc="$1" want="$2"; shift 2
  local rc=0
  "$@" >/dev/null 2>&1 || rc=$?
  if [[ "$rc" != "$want" ]]; then
    echo "FAIL: $desc (rc=$rc want=$want)" >&2
    fail=1
  fi
}

# --- help / usage ----------------------------------------------------------

check "help exits 0"            0 "$SB" help
check "no args = help"          0 "$SB"
check "-h is help"              0 "$SB" -h
check "unknown command dies"    1 "$SB" definitely-not-a-command
check "bare run dies"           1 "$SB" run
check "run missing name dies"   1 "$SB" run client
check "run bad mode dies"       2 "$SB" run bogus xyz
help_out="$("$SB" help)"
for needle in "run client" "run server" "run both" "fetch-base" "create-server"; do
  if ! grep -qF "$needle" <<<"$help_out"; then
    echo "FAIL: help does not mention '$needle'" >&2
    fail=1
  fi
done

# --- name validation -------------------------------------------------------

check "name with slash refused"  1 "$SB" create "../escape"
check "leading dash refused"     1 "$SB" create -danger
check "empty name refused"       1 "$SB" create ""
check "dotfile name refused"     1 "$SB" status ".hidden"
check "plain name passes val"    2 "$SB" status "plain-name" # dies on missing instance, not name

# --- temp sandbox: create/list/status/env/stop -----------------------------

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
check "list empty ok"           0 env SANDBOX_HOME="$TMP" "$SB" list
check "status missing dies"     2 env SANDBOX_HOME="$TMP" "$SB" status nope
check "stop missing ok"         0 env SANDBOX_HOME="$TMP" "$SB" stop nope
check "create w/o base dies"    1 env SANDBOX_HOME="$TMP" "$SB" create t1
check "create-server w/o base"  1 env SANDBOX_HOME="$TMP" "$SB" create-server t1

# Fake client base + instance so list/status/env/logs/stop have state.
mkdir -p "$TMP/base/game" "$TMP/instances/t1/game" "$TMP/instances/t1/logs"
printf 'platform=Local\ncrossplatform=None\nserverplatforms=Steam,LAN,Local,\n' \
  > "$TMP/instances/t1/game/platform.cfg"
cat > "$TMP/instances/t1/instance.env" <<EOF
SANDBOX_NAME=t1
INSTANCE_DIR=$TMP/instances/t1
GAME=$TMP/instances/t1/game
COMPAT=$TMP/instances/t1/compatdata
LOGFILE=$TMP/instances/t1/logs/output_log_client.txt
EOF
check "list shows t1"           0 env SANDBOX_HOME="$TMP" "$SB" list
list_out="$(env SANDBOX_HOME="$TMP" "$SB" list)"
grep -qE "^t1 " <<<"$list_out" || { echo "FAIL: list missing t1 row" >&2; fail=1; }
check "status t1 ok"            0 env SANDBOX_HOME="$TMP" "$SB" status t1
check "env t1 ok"               0 env SANDBOX_HOME="$TMP" "$SB" env t1
env_out="$(env SANDBOX_HOME="$TMP" "$SB" env t1)"
grep -q "^export GAME=" <<<"$env_out" || { echo "FAIL: env missing GAME export" >&2; fail=1; }
grep -q "^export LOGFILE=" <<<"$env_out" || { echo "FAIL: env missing LOGFILE export" >&2; fail=1; }
check "logs without file dies"  1 env SANDBOX_HOME="$TMP" "$SB" logs t1
echo "log-line" > "$TMP/instances/t1/logs/output_log_client.txt"
check "logs with file ok"       0 env SANDBOX_HOME="$TMP" "$SB" logs t1

# --- steam-ownership guard -------------------------------------------------

mkdir -p "$TMP/steamlib/steamapps/common"
check "create in steamapps dies" 1 env SANDBOX_HOME="$TMP/steamlib" "$SB" create s1
guard_out="$(env SANDBOX_INSTANCES="$TMP/steamlib/steamapps" "$SB" list 2>&1 || true)"
check "doctor flags steam lib"  1 env SANDBOX_HOME="$TMP/steamlib" "$SB" doctor

# --- server instance env contract ------------------------------------------

mkdir -p "$TMP/base/server-game" "$TMP/instances/srv-t"
printf 'SANDBOX_NAME=srv-t\nSERVER_KIND=server\nSERVER_PORT=27100\nSERVER_TELNET_PORT=27101\nSERVER_GAME=%s/instances/srv-t/game\nSERVER_USERDATA=%s/instances/srv-t/userdata\nSERVER_CONFIG=%s/instances/srv-t/serverconfig.xml\nSERVER_LOG=%s/instances/srv-t/logs/server.log\n' \
  "$TMP" "$TMP" "$TMP" "$TMP" > "$TMP/instances/srv-t/instance.env"
check "status server ok"        0 env SANDBOX_HOME="$TMP" "$SB" status srv-t
status_out="$(env SANDBOX_HOME="$TMP" "$SB" status srv-t)"
grep -q "srv-t (server)" <<<"$status_out" || { echo "FAIL: status not server-kind" >&2; fail=1; }
check "launch on server dies"   1 env SANDBOX_HOME="$TMP" "$SB" launch srv-t
check "env server kind ok"      0 env SANDBOX_HOME="$TMP" "$SB" env srv-t

# --- fetch arg validation ----------------------------------------------------

check "fetch bad flag dies"     2 "$SB" fetch-base --nonsense
check "fetch-server bad flag"   2 "$SB" fetch-server-base --nonsense

if [[ "$fail" -ne 0 ]]; then
  echo "sb_cli: FAILED" >&2
  exit 1
fi
echo "sb_cli: ok"
