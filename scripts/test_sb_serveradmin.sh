#!/usr/bin/env bash
# seed_sandbox_admins unit tests: Local sandbox clients (PltfmId Local_<name>)
# must land as permission_level=0 in serveradmin.xml on every create/launch/wipe.
# Part of `make test`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SB="$ROOT/scripts/sb"
# The sourced helpers shell out to scripts/sbconfig.py via SB_CONFIG.
export SANDBOX_HOME="$ROOT"
export SB_CONFIG="$ROOT/scripts/sbconfig.py"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail=0
expect_eq() { # expect_eq <desc> <got> <want>
  if [[ "$2" != "$3" ]]; then
    echo "FAIL: $1 (got '$2' want '$3')" >&2
    fail=1
  fi
}

expect_grep() { # expect_grep <desc> <pattern> <file>
  if ! grep -qE "$2" "$3"; then
    echo "FAIL: $1 (pattern /$2/ not in $3)" >&2
    fail=1
  fi
}

# The admins a server admits are declared by the instance (SERVER_ADMINS in
# instance.env), never discovered by scanning whatever other instances happen
# to exist: the same declaration must produce the same file on any host, and
# an unrelated instance appearing on the machine must not change it.
INSTANCES_DIR="$TMP/instances"
export INSTANCES_DIR
INST="$INSTANCES_DIR/srv-sg"
UD="$INST/userdata"
mkdir -p "$UD/Saves"
cat > "$INST/instance.env" <<'EOF'
SANDBOX_NAME=srv-sg
SERVER_ADMINS=client-sg,other-client
SERVER_KIND=server
EOF

# shellcheck disable=SC1090,SC1091 # extract the helpers from sb without running main
# The interpreter check travels with them: seeding shells out to sbconfig.py.
source /dev/stdin <<<"$(sed -n '/^SB_PY=/p;/^SB_PY_MIN=/p;/^die()/,/^}/p;/^require_python()/,/^}/p;/^unquote_value()/,/^}/p;/^env_value()/,/^}/p' "$SB")
$(sed -n '/^default_server_admins()/,/^}/p' "$SB")
$(sed -n '/^warn()/,/^}/p' "$SB")
$(sed -n '/^restrict_instance_env()/,/^}/p' "$SB")
$(sed -n '/^restrict_instance_dir()/,/^}/p' "$SB")
$(sed -n '/^seed_sandbox_admins()/,/^}/p' "$SB")"
# A rename on the sb side leaves the sed matching nothing, and the helper is
# then simply undefined: the first case dies on a name error at best, and at
# worst the cases after it stop asserting anything. Name the missing helper.
for helper in die require_python unquote_value env_value default_server_admins \
  restrict_instance_env seed_sandbox_admins
do
  declare -F "$helper" >/dev/null \
    || { echo "FAIL: $helper is not defined; the extraction out of scripts/sb has drifted" >&2; exit 1; }
done

seed_sandbox_admins "$INST"
admin="$UD/Saves/serveradmin.xml"
[[ -f "$admin" ]] || { echo "FAIL: serveradmin.xml not created" >&2; exit 1; }

expect_grep "client-sg Local admin" \
  'platform="Local" userid="client-sg"[^>]*permission_level="0"' "$admin"
expect_grep "other-client Local admin" \
  'platform="Local" userid="other-client"[^>]*permission_level="0"' "$admin"
expect_grep "default Player Local admin" \
  'platform="Local" userid="Player"[^>]*permission_level="0"' "$admin"

# The file that hands permission_level=0 to a player name is user-only, on
# creation and after every rewrite, rather than whatever the umask said.
expect_eq "serveradmin.xml is 0600" "$(stat -c '%a' "$admin")" "600"

# instance.env carries the same names in SERVER_ADMINS, so it is restricted on
# the same path: an instance.env left 0644 by a 022 umask publishes every Local
# player name the server admits to every account on the host.
chmod 0644 "$INST/instance.env"
seed_sandbox_admins "$INST"
expect_eq "instance.env is 0600 after a seed" "$(stat -c '%a' "$INST/instance.env")" "600"

# The game writes the rest of what a run knows about its players itself: the
# server log naming who connected, the saves, the userdata logs. Those files
# carry the game process's umask, so the directory is what has to keep another
# account on a shared host out of them. A 0755 instance dir left by a 022 umask
# published every one of those names under a file the restrictions above never
# touch.
chmod 0755 "$INST"
seed_sandbox_admins "$INST"
expect_eq "instance dir is 0700 after a seed" "$(stat -c '%a' "$INST")" "700"

# An unrelated instance on the machine must not leak into this server's file.
mkdir -p "$INSTANCES_DIR/client-unrelated"
echo 'SANDBOX_NAME=client-unrelated' > "$INSTANCES_DIR/client-unrelated/instance.env"
seed_sandbox_admins "$INST"
if grep -q 'userid="client-unrelated"' "$admin"; then
  echo "FAIL: an undeclared instance was seeded as a Local admin" >&2
  fail=1
fi

# A server instance created before SERVER_ADMINS existed still admits its pair.
LEGACY="$INSTANCES_DIR/srv-legacy"
mkdir -p "$LEGACY/userdata/Saves"
echo 'SERVER_KIND=server' > "$LEGACY/instance.env"
seed_sandbox_admins "$LEGACY"
expect_grep "legacy instance admits its pair" \
  'platform="Local" userid="client-legacy"[^>]*permission_level="0"' \
  "$LEGACY/userdata/Saves/serveradmin.xml"


# Upsert: bump permission then reseed must restore 0.
python3 - "$admin" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
t = p.read_text(encoding="utf-8")
t = t.replace(
    'userid="client-sg" name="client-sg" permission_level="0"',
    'userid="client-sg" name="client-sg" permission_level="1000"',
    1,
)
p.write_text(t, encoding="utf-8")
PY
seed_sandbox_admins "$INST"
expect_grep "client-sg restored to 0" \
  'platform="Local" userid="client-sg"[^>]*permission_level="0"' "$admin"
expect_eq "serveradmin.xml still 0600 after a rewrite" "$(stat -c '%a' "$admin")" "600"
if grep -qE 'userid="client-sg"[^>]*permission_level="1000"' "$admin"; then
  echo "FAIL: client-sg still at permission_level=1000 after reseed" >&2
  fail=1
fi

# Idempotent: second call with correct file stays quiet and stable.
before="$(wc -c < "$admin")"
out="$(seed_sandbox_admins "$INST" 2>&1 || true)"
after="$(wc -c < "$admin")"
expect_eq "idempotent size" "$after" "$before"
if [[ -n "$out" ]]; then
  echo "FAIL: idempotent reseed printed: $out" >&2
  fail=1
fi

# A name dropped from the declaration loses its level-0 entry. Seeding was an
# upsert, so the file was a function of every declaration the instance had ever
# made and a player removed from SERVER_ADMINS kept dm/givetools forever.
sed -i 's/^SERVER_ADMINS=.*/SERVER_ADMINS=client-sg/' "$INST/instance.env"
seed_sandbox_admins "$INST"
if grep -q 'userid="other-client"' "$admin"; then
  echo "FAIL: an undeclared admin kept its level-0 entry" >&2
  fail=1
fi
expect_grep "the declared admin survives the revocation" \
  'platform="Local" userid="client-sg"[^>]*permission_level="0"' "$admin"
python3 -c 'import sys,xml.etree.ElementTree as ET; ET.parse(sys.argv[1])' "$admin" \
  || { echo "FAIL: revocation left broken XML in $admin" >&2; fail=1; }

# Which functions seed. The four call sites (create-server / launch-server /
# wipe / detached start) are checked by name below; counting occurrences of
# the identifier across the file would also count the definition and every
# comment, so it passed whether or not a call site was actually removed.

python3 - "$SB" <<'PY' || fail=1
import re, sys
text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
checks = [
    ("cmd_create_server", "seed_sandbox_admins"),
    # The name must be shifted off "$@" before --admin extras are read, or the
    # server declares its own instance name as a Local admin.
    ("cmd_create_server", 'local name="$1"; shift'),
    ("cmd_launch_server", "seed_sandbox_admins"),
    ("cmd_wipe", "seed_sandbox_admins"),
    # `sb up` and `sb run both` both seed through start_server_detached.
    ("start_server_detached", "seed_sandbox_admins"),
    # The declared names travel on stdin, never as arguments: argv is readable
    # through /proc/<pid>/cmdline by every account on the host, which would
    # publish the player names this server admits.
    ("seed_sandbox_admins", "restrict_instance_env"),
    # The instance directory carries the same names, in the files the game
    # writes rather than the ones sb writes, so every create and every bring-up
    # has to restrict it. A create that only restricted it after the copy would
    # have published the whole tree for the length of a 20 GB copy.
    ("cmd_create", "restrict_instance_dir"),
    ("cmd_create_server", "restrict_instance_dir"),
    ("cmd_launch", "restrict_instance_dir"),
    ("cmd_wipe", "restrict_instance_dir"),
    ("seed_sandbox_admins", "restrict_instance_dir"),
]

fail = 0


def body_of(fn):
    m = re.search(rf'^{fn}\(\) \{{', text, re.M)
    if not m:
        return None
    rest = text[m.end():]
    n = re.search(r'\n[a-zA-Z_][a-zA-Z0-9_]*\(\) \{', rest)
    return rest[: n.start()] if n else rest


for fn, needle in checks:
    body = body_of(fn)
    if body is None:
        print(f"FAIL: {fn} not found", file=sys.stderr)
        fail = 1
        continue
    if needle in body:
        continue
    # A create path may run its work in a `*_body` helper inside a subshell, so
    # a failure rolls the half-built instance dir back. Follow one level of that
    # delegation rather than reading it as a missing call.
    delegated = any(
        needle in (body_of(helper) or "")
        for helper in re.findall(r'\b([a-z_][a-z0-9_]*_body)\b', body)
    )
    if not delegated:
        print(f"FAIL: {fn} does not call {needle}", file=sys.stderr)
        fail = 1

# No `--name` in the seed helper: that spelling puts the player name in argv,
# which every account on the host can read while the process lives.
if "--name" in (body_of("seed_sandbox_admins") or ""):
    print("FAIL: seed_sandbox_admins passes an admin name in argv", file=sys.stderr)
    fail = 1
sys.exit(fail)
PY

if [[ "$fail" -ne 0 ]]; then
  echo "test_sb_serveradmin: FAILED" >&2
  exit 1
fi
echo "test_sb_serveradmin: OK"
