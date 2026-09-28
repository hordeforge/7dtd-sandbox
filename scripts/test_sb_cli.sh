#!/usr/bin/env bash
# sb CLI surface tests: pure-arg cases that need no game, no Proton, no
# steamcmd. Runs against a temp SANDBOX_HOME so instances/ and bases are
# fakes. Part of `make test` (sibling-repo gate pattern).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SB="$ROOT/scripts/sb"

fail=0
expect_eq() { # expect_eq <desc> <got> <want>
  if [[ "$2" != "$3" ]]; then
    echo "FAIL: $1 (got '$2' want '$3')" >&2
    fail=1
  fi
}
check() { # check <desc> <expected-rc> <cmd...>
  local desc="$1" want="$2"; shift 2
  local rc=0 out=""
  # Subshell: a sourced sb helper calls `exit` on refusal, which would take
  # this script down instead of reporting the exit code under test. The output
  # is captured rather than dropped, so a failure says what the command said.
  out="$( ("$@") 2>&1 )" || rc=$?
  if [[ "$rc" != "$want" ]]; then
    echo "FAIL: $desc (rc=$rc want=$want)" >&2
    [[ -n "$out" ]] && printf '  said: %s\n' "$out" >&2
    fail=1
  fi
}

# Several gates below drive `sb`'s own helpers by extracting them with sed
# rather than running the CLI, so they can reach a branch the CLI refuses to
# enter. A rename on the sb side leaves the sed matching nothing: the helper
# is then simply undefined, and either the gate dies mid-run on a name error or
# a case that depended on it stops asserting anything at all. Naming the
# missing helper is the difference between a red gate and a silent hole.
require_fn() { # require_fn <fn>...
  local fn
  for fn in "$@"; do
    declare -F "$fn" >/dev/null || {
      echo "FAIL: $fn is not defined; the extraction out of scripts/sb has drifted" >&2
      exit 1
    }
  done
}

# --- help / usage ----------------------------------------------------------

check "help exits 0"            0 "$SB" help
check "no args = help"          0 "$SB"
check "-h is help"              0 "$SB" -h
# A wrong command line is exit 2 on every path, not only on the verbs that
# happen to route through usage_err: a script that told itself "0 ok, 2 my
# fault, 1 the run failed" could not rely on it while `sb stpo` and a bare
# `sb create` still reported the same code as a server that never bound.
check "unknown command is usage" 2 "$SB" definitely-not-a-command
check "bare run is usage"       2 "$SB" run
check "run missing name usage"  2 "$SB" run client
check "run bad mode dies"       2 "$SB" run bogus xyz
# A near miss is answered with the command meant, so the refusal says what to
# type rather than only what was wrong.
near="$("$SB" stpo 2>&1 || true)"
case "$near" in
  *"sb stop"*) ;;
  *) echo "FAIL: 'sb stpo' does not suggest 'sb stop': $near" >&2; fail=1 ;;
esac
help_out="$("$SB" help)"
for needle in "run client" "run server" "run both" "fetch-base" "create-server"; do
  if ! grep -qF "$needle" <<<"$help_out"; then
    echo "FAIL: help does not mention '$needle'" >&2
    fail=1
  fi
done

# --- per-command help ------------------------------------------------------

# Every verb carries a page, reachable both ways, and each names its own flags
# rather than only restating the verb: a caller reading `sb up --help` has to
# learn that --timeout exists without running the command.
for c in run create create-server up stage render-config launch launch-server \
         wipe destroy stop list status logs env fetch-base fetch-server-base \
         doctor init version help; do
  for page in "$("$SB" "$c" --help 2>/dev/null)" "$("$SB" help "$c" 2>/dev/null)"; do
    if [[ "$page" != Usage:* ]]; then
      echo "FAIL: no usage page for 'sb $c --help'" >&2
      fail=1
    fi
  done
done
for pair in "up:--timeout" "create:--res" "create-server:--admin" "logs:--follow"; do
  c="${pair%%:*}"; flag="${pair#*:}"
  if ! grep -qF -- "$flag" <<<"$("$SB" "$c" --help)"; then
    echo "FAIL: 'sb $c --help' does not document $flag" >&2
    fail=1
  fi
done
# The page is on stdout, and the run it documents was not started.
check "up --help starts nothing" 0 "$SB" up --help
# Help wins over a bad flag, so a caller who lost the syntax does not have to
# know which verbs parse options at all.
check "create --help over bad flag" 0 "$SB" create --help
# Asking for help about a verb that does not exist is still a wrong command
# line: a help request must not launder it into exit 0.
check "help for unknown verb"    2 "$SB" help frobnicate
check "--help for unknown verb"  2 "$SB" frobnicate --help
# Every verb that takes arguments says so with 2 rather than 1, so "you called
# me wrong" and "the run failed" never share an exit code.
for c in run create create-server up stage render-config destroy wipe stop \
         status launch launch-server logs env; do
  check "bare '$c' is a usage error" 2 "$SB" "$c"
done

# --- name validation -------------------------------------------------------

check "name with slash refused"  2 "$SB" create "../escape"
check "leading dash refused"     2 "$SB" create -danger
check "empty name refused"       2 "$SB" create ""
check "dotfile name refused"     2 "$SB" status ".hidden"
check "plain name passes val"    2 "$SB" status "plain-name" # dies on missing instance, not name

# --- temp sandbox: create/list/status/env/stop -----------------------------

TMP="$(mktemp -d)"
# A stub Proton, so the client-side surface (env, launch refusals) is testable
# on a machine that has no Steam runtime at all. detect_proton takes PROTON
# when it is executable, and nothing here actually runs the game.
PROTON="$TMP/proton-stub"
printf '#!/usr/bin/env bash\nexit 0\n' > "$PROTON"
chmod +x "$PROTON"
export PROTON
trap 'rm -rf "$TMP"' EXIT
check "list empty ok"           0 env SANDBOX_HOME="$TMP" "$SB" list
check "status missing dies"     2 env SANDBOX_HOME="$TMP" "$SB" status nope
check "stop missing ok"         0 env SANDBOX_HOME="$TMP" "$SB" stop nope
check "create w/o base dies"    1 env SANDBOX_HOME="$TMP" "$SB" create t1
check "create-server w/o base"  1 env SANDBOX_HOME="$TMP" "$SB" create-server t1

# A Steam password on steamcmd's argv is readable by every local user, so sb
# refuses the variable rather than passing it or dropping it quietly. Checked
# before steamcmd is even required, hence rc 2 rather than the rc 1 that a
# machine with no steamcmd gives.
check "STEAMCMD_PASS refused" 2 env SANDBOX_HOME="$TMP" STEAMCMD_USER=u \
  STEAMCMD_PASS=hunter2 "$SB" fetch-base

# An app id is handed straight to steamcmd's app_update, so a typo must be
# refused rather than fetched.
mkdir -p "$TMP/tools/steamcmd" && printf '#!/usr/bin/env bash\nexit 0\n' \
  > "$TMP/tools/steamcmd/steamcmd.sh" && chmod +x "$TMP/tools/steamcmd/steamcmd.sh"
check "non-numeric STEAM_APPID refused" 1 env SANDBOX_HOME="$TMP" \
  STEAM_APPID=not-an-app "$SB" fetch-base
check "non-numeric SERVER_APPID refused" 1 env SANDBOX_HOME="$TMP" \
  SERVER_APPID=0 "$SB" fetch-server-base

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

# --- teardown is by instance, on the client's marker too --------------------

# A client is bound to its instance by STEAM_COMPAT_DATA_PATH, a server by
# SB_INSTANCE (AGENTS.md rule 6), and `sb stop` matching only the server one
# left every Proton and wine process of a client running while reporting the
# instance as stopped. The marker is what a blanket `pkill` of wine/proton or
# of 7DaysToDie would sweep up, so a stop that touches one instance's process
# and not its neighbour's is the whole property.
#
# The processes are plain sleeps carrying the marker in their environment: the
# scan reads /proc/<pid>/environ, so what is under test is the marker match,
# not the game binary. A neighbour is spawned alongside so a stop that killed
# by anything but the exact marker would be caught.

mkdir -p "$TMP/instances/t6/game" "$TMP/instances/t6/logs"
printf 'SANDBOX_NAME=t6\nGAME=%s/instances/t6/game\n' "$TMP" \
  > "$TMP/instances/t6/instance.env"

marker_sleep() { # marker_sleep <compatdata-path>; sets MARKER_PID
  # Detached from this script's streams: a backgrounded child that inherits
  # them holds the pipe open, so anything reading this script's output (make,
  # a CI log) blocks until the child exits 300s later. Not run in a command
  # substitution either, for the same reason one level in.
  env "STEAM_COMPAT_DATA_PATH=$1" sleep 300 >/dev/null 2>&1 &
  MARKER_PID=$!
  # Give the child a moment to be visible in /proc with its environment set,
  # or the scan below reads the tree before the process exists.
  local waited=0
  while (( waited < 100 )) && ! grep -aqzF "STEAM_COMPAT_DATA_PATH=$1" \
    "/proc/$MARKER_PID/environ" 2>/dev/null; do
    sleep 0.1
    # `(( waited++ ))` returns the value before the increment, so the first
    # pass is a failing arithmetic command and `set -e` ends the gate right
    # there, before any of the cases below it.
    waited=$((waited + 1))
  done
  grep -aqzF "STEAM_COMPAT_DATA_PATH=$1" "/proc/$MARKER_PID/environ" 2>/dev/null || {
    echo "FAIL: the marked process $MARKER_PID never published its marker" >&2
    exit 1
  }
}

stopped_pid=""
neighbour_pid=""
cleanup_markers() {
  local p
  for p in "$stopped_pid" "$neighbour_pid"; do
    [[ -n "$p" ]] && kill -KILL "$p" 2>/dev/null || true
  done
}
trap 'cleanup_markers; rm -rf "$TMP"' EXIT

marker_sleep "$TMP/instances/t1/compatdata"
stopped_pid="$MARKER_PID"
marker_sleep "$TMP/instances/t6/compatdata"
neighbour_pid="$MARKER_PID"
# Out of the job table, so bash does not print a "Killed" line for a pid this
# gate stopped on purpose. The pids are kept for cleanup_markers either way.
disown "$stopped_pid" "$neighbour_pid" 2>/dev/null || true

running_t1="$(env SANDBOX_HOME="$TMP" "$SB" status t1)"
grep -qE '^running: +yes \(1 procs\)$' <<<"$running_t1" \
  || { echo "FAIL: a client carrying its marker was reported stopped: $running_t1" >&2; fail=1; }

running_t6="$(env SANDBOX_HOME="$TMP" "$SB" status t6)"
grep -qE '^running: +yes \(1 procs\)$' <<<"$running_t6" \
  || { echo "FAIL: the neighbour's marked process was not seen: $running_t6" >&2; fail=1; }

check "stop the client by marker"  0 env SANDBOX_HOME="$TMP" "$SB" stop t1
# SIGTERM reaches a sleep, so the process is gone as soon as the wait returns.
kill -0 "$stopped_pid" 2>/dev/null \
  && { echo "FAIL: sb stop left the client's marked process running (pid $stopped_pid)" >&2; fail=1; }
kill -0 "$neighbour_pid" 2>/dev/null \
  || { echo "FAIL: sb stop t1 killed the neighbour's process (pid $neighbour_pid)" >&2; fail=1; }

stopped_t1="$(env SANDBOX_HOME="$TMP" "$SB" status t1)"
grep -qE '^running: +no$' <<<"$stopped_t1" \
  || { echo "FAIL: the stopped client still reports running: $stopped_t1" >&2; fail=1; }

cleanup_markers
stopped_pid=""
neighbour_pid=""
trap 'rm -rf "$TMP"' EXIT

# --- steam-ownership guard -------------------------------------------------

mkdir -p "$TMP/steamlib/steamapps/common"
check "create in steamapps dies" 1 env SANDBOX_HOME="$TMP/steamlib" "$SB" create s1
# With a base present, the refusal must come from the steamapps guard itself
# and name the library, not from require_base further up.
mkdir -p "$TMP/steamlib/base/game"
touch "$TMP/steamlib/base/game/7DaysToDie.exe"
guard_out="$(env SANDBOX_HOME="$TMP/steamlib" "$SB" create s2 2>&1 || true)"
grep -q "Steam library" <<<"$guard_out" \
  || { echo "FAIL: steamapps refusal did not name the Steam library: $guard_out" >&2; fail=1; }

# steamcmd writes its own steamapps/ (appmanifest, downloading, temp) into
# whatever +force_install_dir it is given, so every fetched base carries one.
# That is not a Steam library and must not be refused: a library is
# steamapps/common. This false positive refused our own pristine base, so the
# guard is exercised directly rather than through a create that would also
# build a Proton prefix.
# shellcheck disable=SC1090,SC1091 # extract the guard from sb without running main
source /dev/stdin <<<"$(sed -n '/^die()/,/^}/p' "$SB")
$(sed -n '/^assert_not_steam_owned()/,/^}/p' "$SB")"
require_fn die assert_not_steam_owned

mkdir -p "$TMP/fetched/game/steamapps/downloading"
touch "$TMP/fetched/game/steamapps/appmanifest_251570.acf"
if ! ( assert_not_steam_owned "$TMP/fetched/game" "base game" ) 2>/dev/null; then
  echo "FAIL: a steamcmd manifest dir was mistaken for a Steam library" >&2
  fail=1
fi

mkdir -p "$TMP/reallib/steamapps/common/7 Days To Die" "$TMP/reallib/base/game"
if ( assert_not_steam_owned "$TMP/reallib/steamapps/common/7 Days To Die" "base game" ) 2>/dev/null; then
  echo "FAIL: a path inside a real Steam library was accepted" >&2
  fail=1
fi
if ( assert_not_steam_owned "$TMP/reallib/base/game" "base game" ) 2>/dev/null; then
  echo "FAIL: a library root ancestor was accepted" >&2
  fail=1
fi
check "doctor flags steam lib"  1 env SANDBOX_HOME="$TMP/steamlib" "$SB" doctor

# --- server instance env contract ------------------------------------------

mkdir -p "$TMP/base/server-game" "$TMP/instances/srv-t"
printf 'SANDBOX_NAME=srv-t\nSERVER_KIND=server\nSERVER_PORT=27100\nSERVER_TELNET_PORT=27101\nSERVER_GAME=%s/instances/srv-t/game\nSERVER_USERDATA=%s/instances/srv-t/userdata\nSERVER_CONFIG=%s/instances/srv-t/serverconfig.xml\nSERVER_LOG=%s/instances/srv-t/logs/server.log\n' \
  "$TMP" "$TMP" "$TMP" "$TMP" > "$TMP/instances/srv-t/instance.env"
check "status server ok"        0 env SANDBOX_HOME="$TMP" "$SB" status srv-t
status_out="$(env SANDBOX_HOME="$TMP" "$SB" status srv-t)"
grep -q "srv-t (server)" <<<"$status_out" || { echo "FAIL: status not server-kind" >&2; fail=1; }
check "launch on server dies"   1 env SANDBOX_HOME="$TMP" "$SB" launch srv-t

# The documented consumer of `sb env` is `eval "$(sb env <name>)"`, so what it
# prints must be data, never shell. A declared value carrying a quote would
# otherwise close the assignment and run the rest of the line.
mkdir -p "$TMP/instances/srv-evil"
EVIL_ADMINS="a'; touch $TMP/PWNED; #"
cat > "$TMP/instances/srv-evil/instance.env" <<EOF
SANDBOX_NAME=srv-evil
SERVER_KIND=server
SERVER_ADMINS=$EVIL_ADMINS
EOF
evil_env="$(env SANDBOX_HOME="$TMP" "$SB" env srv-evil)"
eval "$evil_env"
[[ -e "$TMP/PWNED" ]] && { echo "FAIL: sb env emitted a value the caller's shell executes" >&2; fail=1; }
expect_eq "quoted value round-trips through eval" "${SERVER_ADMINS:-}" "$EVIL_ADMINS"

# A Local admin name lands in instance.env and in serveradmin.xml; one shaped
# like a shell fragment is refused at the boundary.
touch "$TMP/base/server-game/7DaysToDieServer.x86_64"
check "admin name with quote refused"  2 env SANDBOX_HOME="$TMP" "$SB" create-server srv-bad --admin "a'; touch $TMP/PWNED; #"
check "admin name with slash refused"  2 env SANDBOX_HOME="$TMP" "$SB" create-server srv-bad --admin "a/b"
[[ -d "$TMP/instances/srv-bad" ]] && { echo "FAIL: a refused admin name still created the instance" >&2; fail=1; }

# --- an instance's mods are stock plus what was declared --------------------

# A base seeded from a Steam install carries whatever that install had. This
# repo's own client base carried RealEarth, so every client instance inherited
# a terrain mod the server instance did not: the pair registered different
# blocks, the client failed to deserialize the first world package, and the
# server kicked it minutes into a run with nothing naming the cause.
# shellcheck disable=SC1090,SC1091 # extract the pruner from sb without running main
source /dev/stdin <<<"$(sed -n '/^STOCK_MOD=/p' "$SB")
$(sed -n '/^is_stock_mod()/,/^}/p' "$SB")
$(sed -n '/^prune_instance_mods()/,/^}/p' "$SB")"
require_fn is_stock_mod prune_instance_mods
[[ -n "${STOCK_MOD:-}" ]] || { echo "FAIL: STOCK_MOD is not defined" >&2; exit 1; }

MODS="$TMP/instances/pruneme/game/Mods"
mkdir -p "$MODS/0_TFP_Harmony" "$MODS/TFP_CommandExtensions" "$MODS/Xample_MarkersMod" \
         "$MODS/RealEarth" "$MODS/SomeRandomMod"
prune_out="$(prune_instance_mods "$TMP/instances/pruneme")"
[[ -d "$MODS/0_TFP_Harmony" ]] \
  || { echo "FAIL: pruning removed the Harmony loader every code mod needs" >&2; fail=1; }
# TFP's samples go too: the client and dedicated depots ship different ones, so
# keeping them makes every pair asymmetric and the server registers content the
# client never loaded.
for undeclared in TFP_CommandExtensions Xample_MarkersMod RealEarth SomeRandomMod; do
  [[ -e "$MODS/$undeclared" ]] \
    && { echo "FAIL: undeclared mod $undeclared survived pruning" >&2; fail=1; }
done
grep -q "RealEarth" <<<"$prune_out" \
  || { echo "FAIL: pruning did not name what it removed: $prune_out" >&2; fail=1; }

# Pruning is idempotent and silent once an instance is already clean.
quiet_out="$(prune_instance_mods "$TMP/instances/pruneme")"
[[ -z "$quiet_out" ]] \
  || { echo "FAIL: a clean instance still reported a prune: $quiet_out" >&2; fail=1; }

# --- create-server declares its pair, not itself ---------------------------

# cmd_create_server read "$@" for --admin extras without shifting the name off
# it, so every server declared its own instance name as a Local admin.
# shellcheck disable=SC1090,SC1091 # extract the helper from sb without running main
source /dev/stdin <<<"$(sed -n '/^default_server_admins()/,/^}/p' "$SB")"
require_fn default_server_admins
expect_eq "pair name only" "$(default_server_admins srv-demo)" "client-demo"
expect_eq "no pair for a bare name" "$(default_server_admins standalone)" ""

# --- a Local admin name is shell code once it is in instance.env -----------

# instance.env is source-able and `sb env` prints it for eval, so a --admin
# value carrying shell metacharacters would run in the next harness's shell.
# The helper calls sb's usage_err, so stub the exit it uses. `die` is already
# in scope, sourced from sb above.
usage_err() { echo "test: $*" >&2; exit 2; }
# shellcheck disable=SC1090,SC1091 # extract the helper from sb without running main
source /dev/stdin <<<"$(sed -n '/^validate_admin_name()/,/^}/p' "$SB")"
require_fn validate_admin_name
for good in client-demo "srv_1" "a.b-c"; do
  check "admin name '$good' accepted" 0 validate_admin_name "$good"
done
# shellcheck disable=SC2016 # the single quotes are the payload, not an oversight
for bad in 'x;rm -rf /' '$(id)' 'a b' '../x' '-x' '' 'a"b'; do
  check "admin name '$bad' refused" 2 validate_admin_name "$bad"
done

# End to end: the refusal happens at the CLI, before anything is written, and a
# well-formed name still reaches the declaration.
mkdir -p "$TMP/base/server-game"
touch "$TMP/base/server-game/7DaysToDieServer.x86_64"
check "create-server refuses a metacharacter admin" 2 \
  env SANDBOX_HOME="$TMP" "$SB" create-server srv-bad --admin 'x;id'
[[ -e "$TMP/instances/srv-bad" ]] \
  && { echo "FAIL: a refused --admin still created the instance" >&2; fail=1; }
check "create-server accepts a plain admin" 0 \
  env SANDBOX_HOME="$TMP" "$SB" create-server srvplain --admin 'client-ok'
grep -qx "SERVER_ADMINS='client-ok'" "$TMP/instances/srvplain/instance.env" \
  || { echo "FAIL: a valid --admin did not reach SERVER_ADMINS" >&2; fail=1; }
# The instance directory is what keeps another account on a shared host out of
# the game-written files under it: the server log, the saves, the userdata
# logs, all created by the game at its own umask. 0755 published every one of
# them under a file the 0600 restrictions never touch.
expect_eq "instance dir is 0700 after create-server" \
  "$(stat -c '%a' "$TMP/instances/srvplain")" "700"

# --- the window contract every launcher must honour -------------------------

# A sandbox client is a test fixture: never fullscreen, and several must be
# visible at once. `sb env` exports the arguments so a launcher that is not
# `sb launch` (fastconnect's launch_client.sh, used by playtest) applies the
# same window instead of whatever the prefix last saved.
env_out="$(env SANDBOX_HOME="$TMP" "$SB" env t1)"
for needle in \
  "SB_RES='1280x720'" \
  "SB_FULLSCREEN='0'" \
  "SB_SCREEN_ARGS='-screen-fullscreen 0 -screen-width 1280 -screen-height 720'"
do
  grep -qF "$needle" <<<"$env_out" \
    || { echo "FAIL: sb env lost the window contract ($needle)" >&2; fail=1; }
done

# The window is the instance's declaration, not the caller's environment: the
# same instance must open the same window on any machine, so an ambient SB_RES
# at launch time changes nothing.
amb_out="$(env SANDBOX_HOME="$TMP" SB_RES=1920x1080 "$SB" env t1)"
grep -qF "SB_SCREEN_ARGS='-screen-fullscreen 0 -screen-width 1280 -screen-height 720'" \
  <<<"$amb_out" \
  || { echo "FAIL: an ambient SB_RES overrode the instance's declared window" >&2; fail=1; }

# It is declared at create time and recorded in instance.env.
mkdir -p "$TMP/instances/t2"
printf 'SANDBOX_NAME=t2\nSB_RES=1920x1080\nSB_FULLSCREEN=1\n' \
  > "$TMP/instances/t2/instance.env"
decl_out="$(env SANDBOX_HOME="$TMP" "$SB" env t2)"
grep -qF "SB_SCREEN_ARGS='-screen-fullscreen 1 -screen-width 1920 -screen-height 1080'" \
  <<<"$decl_out" \
  || { echo "FAIL: the declared window was not honoured: $decl_out" >&2; fail=1; }

# A malformed declaration is a refusal, never a client with no window args.
mkdir -p "$TMP/instances/t3"
printf 'SANDBOX_NAME=t3\nSB_RES=huge\nSB_FULLSCREEN=0\n' > "$TMP/instances/t3/instance.env"
check "malformed declared SB_RES refused" 1 env SANDBOX_HOME="$TMP" "$SB" env t3
mkdir -p "$TMP/instances/t4"
printf 'SANDBOX_NAME=t4\nSB_RES=1280x720\nSB_FULLSCREEN=yes\n' > "$TMP/instances/t4/instance.env"
check "malformed declared SB_FULLSCREEN refused" 1 env SANDBOX_HOME="$TMP" "$SB" env t4

# The launch path refuses the same declaration rather than starting the game
# with no -screen-* arguments at all, which is what a refusal inside the
# command substitution used to produce.
mkdir -p "$TMP/instances/t5/game"
printf 'SANDBOX_NAME=t5\nSB_RES=huge\nSB_FULLSCREEN=0\n' > "$TMP/instances/t5/instance.env"
bad_launch="$(env SANDBOX_HOME="$TMP" "$SB" launch t5 2>&1 || true)"
grep -qF "SB_RES must look like" <<<"$bad_launch" \
  || { echo "FAIL: sb launch started on a malformed declared window: $bad_launch" >&2; fail=1; }

# --- instance.env is source-able, whatever the paths hold -------------------

# Both documented consumers parse this file with a shell: `eval "$(sb env
# <name>)"` and `source instances/<name>/instance.env`. A path written bare
# is a path re-split by that shell: every stock Proton install lives under
# "Proton - Experimental", which assigned the prefix and then ran `-` as a
# command, and a value carrying a newline wrote a second line that shell ran.
# The values below are what a create writes when the caller's environment is
# shaped that way; both consumers have to hand back exactly the input.
HOSTILE_STEAM_ROOT="$TMP/Steam Root/\$(id); touch $TMP/PWNED2"
mkdir -p "$TMP/base/game" && touch "$TMP/base/game/7DaysToDie.exe"
check "create with a shaped STEAM_ROOT" 0 env \
  SANDBOX_HOME="$TMP" STEAM_ROOT="$HOSTILE_STEAM_ROOT" "$SB" create src-safe
[[ -e "$TMP/PWNED2" ]] \
  && { echo "FAIL: writing instance.env executed part of a path" >&2; fail=1; }
# shellcheck disable=SC2016 # the single-quoted script is run by the child bash
sourced="$(env SANDBOX_HOME="$TMP" STEAM_ROOT="$HOSTILE_STEAM_ROOT" \
  bash -c 'source "$1/instances/src-safe/instance.env"; printf %s "$STEAM_ROOT"' _ "$TMP")"
expect_eq "a sourced instance.env keeps a shaped path whole" "$sourced" "$HOSTILE_STEAM_ROOT"
# shellcheck disable=SC2016 # the single-quoted script is run by the child bash
evaled="$(env SANDBOX_HOME="$TMP" STEAM_ROOT="$HOSTILE_STEAM_ROOT" \
  bash -c 'eval "$("$1" env src-safe)"; printf %s "$STEAM_ROOT"' _ "$SB" 2>/dev/null | tail -1)"
expect_eq "sb env keeps a shaped path whole" "$evaled" "$HOSTILE_STEAM_ROOT"
[[ -e "$TMP/PWNED2" ]] \
  && { echo "FAIL: sb env emitted a path the caller's shell executes" >&2; fail=1; }

# --- up / stage / render-config surface ------------------------------------

check "up without name usage"   2 env SANDBOX_HOME="$TMP" "$SB" up
check "up bad flag usage"       2 env SANDBOX_HOME="$TMP" "$SB" up srv-t --nope
check "up bad timeout usage"    2 env SANDBOX_HOME="$TMP" "$SB" up srv-t --timeout soon
check "up on client instance"   1 env SANDBOX_HOME="$TMP" "$SB" up t1
check "stage without dirs"      2 env SANDBOX_HOME="$TMP" "$SB" stage t1
check "stage missing instance"  2 env SANDBOX_HOME="$TMP" "$SB" stage nosuch "$TMP"
check "stage non-modlet dies"   1 env SANDBOX_HOME="$TMP" "$SB" stage t1 "$TMP"
mkdir -p "$TMP/instances/srv-t/game"
printf '<ServerSettings>\n</ServerSettings>\n' > "$TMP/instances/srv-t/game/serverconfig.xml"
check "render-config no props"  2 env SANDBOX_HOME="$TMP" "$SB" render-config srv-t
check "render-config bad prop"  2 env SANDBOX_HOME="$TMP" "$SB" render-config srv-t NoEquals
# A key is a regex in the upsert and a line prefix in instance.props; a value
# is one line of that file. Anything else is a refusal, not a rewrite.
check "render-config regex key refused"  2 env SANDBOX_HOME="$TMP" "$SB" render-config srv-t '.*=x'
check "render-config key with space"     2 env SANDBOX_HOME="$TMP" "$SB" render-config srv-t 'Max Spawn=1'
check "render-config newline value"      2 env SANDBOX_HOME="$TMP" "$SB" render-config srv-t $'ServerName=a\nGameWorld=Navezgane'

mkdir -p "$TMP/modsrc/DemoMod"
touch "$TMP/modsrc/DemoMod/ModInfo.xml"
check "stage modlet ok"         0 env SANDBOX_HOME="$TMP" "$SB" stage t1 "$TMP/modsrc/DemoMod"
[[ -f "$TMP/instances/t1/game/Mods/DemoMod/ModInfo.xml" ]] \
  || { echo "FAIL: staged modlet missing from instance Mods" >&2; fail=1; }
[[ -L "$TMP/instances/t1/game/Mods/DemoMod" ]] \
  && { echo "FAIL: staged modlet is a symlink, not a real copy" >&2; fail=1; }

check "render-config sets prop" 0 env SANDBOX_HOME="$TMP" "$SB" render-config srv-t GameWorld=Navezgane
grep -q 'name="GameWorld" value="Navezgane"' "$TMP/instances/srv-t/serverconfig.xml" \
  || { echo "FAIL: render-config did not set GameWorld" >&2; fail=1; }
check "env server kind ok"      0 env SANDBOX_HOME="$TMP" "$SB" env srv-t

# --- a create either completes or leaves nothing behind --------------------

# A real base and server base, so both create paths run end to end.
touch "$TMP/base/game/7DaysToDie.exe"
mkdir -p "$TMP/base/server-game/Mods/0_TFP_Harmony" "$TMP/base/server-game/Mods/SampleMod"
touch "$TMP/base/server-game/7DaysToDieServer.x86_64"
printf '<ServerSettings>\n</ServerSettings>\n' > "$TMP/base/server-game/serverconfig.xml"

check "create client ok"        0 env SANDBOX_HOME="$TMP" "$SB" create cli-ok
[[ -f "$TMP/instances/cli-ok/game/7DaysToDie.exe" ]] \
  || { echo "FAIL: create did not copy the base into the instance" >&2; fail=1; }
[[ -d "$TMP/instances/cli-ok/game/Mods/SampleMod" ]] \
  && { echo "FAIL: a sample mod survived into a fresh client instance" >&2; fail=1; }
check "create server ok"        0 env SANDBOX_HOME="$TMP" "$SB" create-server srv-ok
grep -q '^SERVER_PORT=' "$TMP/instances/srv-ok/instance.env" \
  || { echo "FAIL: create-server recorded no port block" >&2; fail=1; }
# A client prefix and a client log are the same personal data a server's are:
# the player name, the saves, the log lines naming who played. Both kinds are
# restricted by the same rule, so both are asserted here.
for created in cli-ok srv-ok; do
  expect_eq "$created instance dir is 0700" \
    "$(stat -c '%a' "$TMP/instances/$created")" "700"
done

# The instance dir is allocated before the work that fills it. A failure
# anywhere in that work used to leave a tree behind that refuses every retry
# with "already exists" and has to be removed by hand; the create rolls it back
# instead. Two deterministic ways to fail after the allocation: a config helper
# that cannot run (server), and a base the copy cannot read (client).
printf 'this is not python\n' > "$TMP/broken-sbconfig.py"
out="$(env SANDBOX_HOME="$TMP" SB_CONFIG="$TMP/broken-sbconfig.py" \
  "$SB" create-server halfmade-server 2>&1 || true)"
grep -q "was not created" <<<"$out" \
  || { echo "FAIL: a failed create-server did not report the rollback: $out" >&2; fail=1; }
[[ -e "$TMP/instances/halfmade-server" ]] \
  && { echo "FAIL: a failed create-server left an instance dir behind" >&2; fail=1; }

# root reads an unreadable directory, so this case only means anything as a
# normal user; CI runs as one, and a root run skips rather than asserts nothing.
if [[ "$(id -u)" -ne 0 ]]; then
  mkdir -p "$TMP/unreadable/game/blocked"
  touch "$TMP/unreadable/game/7DaysToDie.exe" "$TMP/unreadable/game/blocked/data"
  chmod 000 "$TMP/unreadable/game/blocked"
  out="$(env SANDBOX_HOME="$TMP" SANDBOX_BASE_GAME="$TMP/unreadable/game" \
    "$SB" create halfmade-client 2>&1 || true)"
  chmod 755 "$TMP/unreadable/game/blocked"
  grep -q "was not created" <<<"$out" \
    || { echo "FAIL: a failed create did not report the rollback: $out" >&2; fail=1; }
  [[ -e "$TMP/instances/halfmade-client" ]] \
    && { echo "FAIL: a failed create left an instance dir behind" >&2; fail=1; }
fi

# --- teardown and auto-create converge on a second run ----------------------

# `sb destroy` is re-run: a harness whose last pass died, or a caller that
# tears down unconditionally, destroys what is already gone. That is done, not
# failed. The refusal (exit 2, "instance not found") also stopped `sb destroy
# a b` at the first name that was already gone, leaving the rest standing.
check "create server for teardown"  0 env SANDBOX_HOME="$TMP" "$SB" create-server srv-tear
check "destroy ok"                   0 env SANDBOX_HOME="$TMP" "$SB" destroy srv-tear
[[ -e "$TMP/instances/srv-tear" ]] \
  && { echo "FAIL: destroy left the instance dir behind" >&2; fail=1; }
check "destroy rerun ok"             0 env SANDBOX_HOME="$TMP" "$SB" destroy srv-tear

# One missing name must not stop the teardown of the ones after it.
check "create server for teardown 2" 0 env SANDBOX_HOME="$TMP" "$SB" create-server srv-tear2
check "destroy skips a gone name"     0 env SANDBOX_HOME="$TMP" "$SB" destroy gone-name srv-tear2
[[ -e "$TMP/instances/srv-tear2" ]] \
  && { echo "FAIL: a missing name stopped destroy before the instance after it" >&2; fail=1; }

# The auto-create path (`sb up` / `sb run` on a name with no instance) has to
# converge on a rerun after a create that was killed part-way: the create
# allocates the directory before the work that fills it, and its rollback only
# runs when the create failed on its own terms. A directory with no
# instance.env and nothing a create writes is that debris, and it is removed so
# the retry builds the instance. A directory holding anything else is somebody
# else's, and is refused by name rather than deleted.
mkdir -p "$TMP/instances/srv-debris/game"
out="$(env SANDBOX_HOME="$TMP" "$SB" up srv-debris --timeout 3 2>&1 || true)"
grep -q "did not finish" <<<"$out" \
  || { echo "FAIL: sb up did not name the unfinished create: $out" >&2; fail=1; }
# ... and then built it: the bring-up itself fails here, because the fixture
# 'server' is an empty file that binds nothing, which is a different failure
# than the one above.
[[ -f "$TMP/instances/srv-debris/instance.env" ]] \
  || { echo "FAIL: sb up did not rebuild the unfinished instance: $out" >&2; fail=1; }

mkdir -p "$TMP/instances/foreign"
: > "$TMP/instances/foreign/notes.txt"
out="$(env SANDBOX_HOME="$TMP" "$SB" up foreign --timeout 3 2>&1 || true)"
grep -q "notes.txt" <<<"$out" \
  || { echo "FAIL: sb up did not name the entry it refused: $out" >&2; fail=1; }
[[ -e "$TMP/instances/foreign/notes.txt" ]] \
  || { echo "FAIL: sb up removed a directory no create wrote" >&2; fail=1; }

# --- fetch arg validation ----------------------------------------------------

check "fetch bad flag dies"     2 "$SB" fetch-base --nonsense
check "fetch-server bad flag"   2 "$SB" fetch-server-base --nonsense

# --- interpreter contract ----------------------------------------------------

# One floor, declared twice (sb checks before it shells out, sbconfig checks
# its own process). A drift between them means sb either refuses a supported
# interpreter or hands an unsupported one work, so they are pinned equal.
sb_floor="$(sed -n 's/^SB_PY_MIN="\(.*\)"$/\1/p' "$SB" | head -1)"
py_floor="$(sed -n 's/^MIN_PYTHON = (\(.*\))$/\1/p' "$ROOT/scripts/sbconfig.py" | head -1)"
expected_floor="$(tr -d '() ' <<<"$py_floor" | tr ',' '.')"
expect_eq "sb and sbconfig.py declare one python floor" "$sb_floor" "$expected_floor"

# A missing interpreter is named, not surfaced as `command not found` from the
# middle of a create-server.
no_py="$(env SANDBOX_HOME="$TMP" SB_PY=sbconfig.py-no-such-interpreter "$SB" render-config srv-t GameWorld=Navezgane 2>&1 || true)"
grep -qF "not on PATH" <<<"$no_py" \
  || { echo "FAIL: a missing interpreter was not named: $no_py" >&2; fail=1; }

# --- analyzer contract ------------------------------------------------------

# The analyzers `make check` runs are pinned in the Makefile, and CI installs
# those pins rather than repeating the numbers. A CI that installs a different
# version than the Makefile names, or that falls back to the runner image's
# preinstalled one, is a gate whose verdict nobody chose, so the workflow is
# held to reading the pins here.
ci_yml="$ROOT/.github/workflows/ci.yml"
for pin in RUFF_VERSION SHELLCHECK_PY_VERSION SHELLCHECK_VERSION YAMLLINT_VERSION; do
  grep -qE "^$pin := [0-9]+\.[0-9]+" "$ROOT/Makefile" \
    || { echo "FAIL: the Makefile does not pin $pin" >&2; fail=1; }
  grep -q "s/^$pin := /" "$ci_yml" \
    || { echo "FAIL: ci.yml does not install the pinned $pin from the Makefile" >&2; fail=1; }
done
# No version literal of its own: a bump that edits only the workflow passes
# this gate and puts the two back out of step.
if grep -nE '(ruff|shellcheck-py|yamllint)==[0-9]' "$ci_yml"; then
  echo "FAIL: ci.yml carries a literal analyzer version rather than the Makefile pin" >&2
  fail=1
fi

# The launch path recognises a caller-supplied -screen-* argument with a bash
# scan, so no GNU-only null-input grep sits between sb and the game.
# shellcheck disable=SC1090,SC1091 # extract the helper from sb without running main
source /dev/stdin <<<"$(sed -n '/^has_screen_arg()/,/^}/p' "$SB")"
require_fn has_screen_arg
has_screen_arg -connect=1.2.3.4 -screen-width 800 && screen_seen=yes || screen_seen=no
expect_eq "-screen- arg detected" "$screen_seen" "yes"
has_screen_arg -connect=1.2.3.4 && screen_seen=yes || screen_seen=no
expect_eq "no -screen- arg detected" "$screen_seen" "no"

# --- the resolved configuration is readable ---------------------------------

# instance.env is a KEY=VALUE contract the harnesses are told to source, and
# the rest of the declaration (instance name, admin names, property keys) is
# charset-checked where it is written. An instances root outside that charset
# is refused at create, before the directory exists.
mkdir -p "$TMP/with space/instances" "$TMP/base/game" "$TMP/base/server-game"
touch "$TMP/base/game/7DaysToDie.exe" "$TMP/base/server-game/7DaysToDieServer.x86_64"
root_out="$(env SANDBOX_HOME="$TMP" SANDBOX_INSTANCES="$TMP/with space/instances" \
  "$SB" create sp 2>&1 || true)"
if [[ -e "$TMP/with space/instances/sp" ]]; then
  echo "FAIL: a refused instances root still created the instance" >&2
  fail=1
fi
grep -q "SANDBOX_INSTANCES" <<<"$root_out" \
  || { echo "FAIL: the refusal did not name the variable to move: $root_out" >&2; fail=1; }
check "create-server under the same root dies" 1 env SANDBOX_HOME="$TMP" \
  SANDBOX_INSTANCES="$TMP/with space/instances" "$SB" create-server sp
check "create under a safe root is accepted"   0 env SANDBOX_HOME="$TMP" \
  SANDBOX_INSTANCES="$TMP/instances" "$SB" create ok # the stub PROTON, the fake base

# The window defaults have one home (SB_DEFAULT_RES / SB_DEFAULT_FULLSCREEN),
# so an instance created before the window was declared opens the same window
# a fresh one is recorded with.
# shellcheck disable=SC1090,SC1091 # extract the defaults and the reader from sb
source /dev/stdin <<<"$(sed -n '/^SB_DEFAULT_RES=/p' "$SB")
$(sed -n '/^SB_DEFAULT_FULLSCREEN=/p' "$SB")
$(sed -n '/^unquote_value()/,/^}/p' "$SB")
$(sed -n '/^env_value()/,/^}/p' "$SB")
$(sed -n '/^declared_window()/,/^}/p' "$SB")"
require_fn unquote_value env_value declared_window
# shellcheck disable=SC2154 # the two defaults are sourced out of sb above
want_window="$SB_DEFAULT_RES $SB_DEFAULT_FULLSCREEN"
read -r win_res win_fs < <(declared_window "$TMP/instances/nodeclared")
expect_eq "undeclared window falls back to the one default" "$win_res $win_fs" \
  "$want_window"

# sb init is where an operator reads back what sb resolved, so it has to work
# on a host that has no Proton yet: detect_proton dies, and the report used to
# die with it before printing a line.
NO_PROTON_HOME="$TMP/nohome" && mkdir -p "$NO_PROTON_HOME"
init_rc=0
init_out="$(env -u PROTON HOME="$NO_PROTON_HOME" SANDBOX_HOME="$TMP/np" "$SB" init 2>&1)" || init_rc=$?
expect_eq "sb init runs with no Proton on the host" "$init_rc" "0"
for needle in "SERVER_BASE_GAME=" "SERVER_APPID=" "STEAM_APPID=" "SB_CONFIG=" \
  "SB_DEFAULT_RES=1280x720" "SB_UP_TIMEOUT="; do
  grep -qF "$needle" <<<"$init_out" \
    || { echo "FAIL: sb init does not report $needle" >&2; fail=1; }
done

# --- the contributor's edit-test loop ---------------------------------------

# `make test` is the whole verdict and is right before a push, not between two
# edits, so there has to be a way to run one gate, and the way has to be
# discoverable from `make help` rather than tribal memory about which
# interpreter a given scripts/test_* file wants.
make_help="$(make -C "$ROOT" help)"
grep -q "test-one" <<<"$make_help" \
  || { echo "FAIL: make help does not name test-one" >&2; fail=1; }
check "test-one with no GATE is a usage error" 2 env -u GATE \
  make -C "$ROOT" test-one
check "test-one on a file that is not a gate is a usage error" 2 \
  make -C "$ROOT" test-one GATE=scripts/sb
# A gate run through it, so the target is a loop and not a refusal: the release
# gate is pure file checks, costs nothing, and does not recurse into make test.
# GATE is passed explicitly on both make lines, because make exports a
# command-line variable into the recipe's environment: the `no GATE` case
# without env -u inherits the GATE this gate was itself run with and
# re-enters test-one on it.
check "test-one runs a real gate" 0 make -C "$ROOT" test-one \
  GATE=scripts/test_sb_release.sh
grep -q "make test-one" "$ROOT/README.md" \
  || { echo "FAIL: the README does not document make test-one" >&2; fail=1; }

if [[ "$fail" -ne 0 ]]; then
  echo "sb_cli: FAILED" >&2
  exit 1
fi
echo "sb_cli: ok"
