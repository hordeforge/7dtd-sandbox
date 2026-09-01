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
source /dev/stdin <<<"$(sed -n '/^default_server_admins()/,/^}/p' "$SB")
$(sed -n '/^seed_sandbox_admins()/,/^}/p' "$SB")"

seed_sandbox_admins "$INST"
admin="$UD/Saves/serveradmin.xml"
[[ -f "$admin" ]] || { echo "FAIL: serveradmin.xml not created" >&2; exit 1; }

expect_grep "client-sg Local admin" \
  'platform="Local" userid="client-sg"[^>]*permission_level="0"' "$admin"
expect_grep "other-client Local admin" \
  'platform="Local" userid="other-client"[^>]*permission_level="0"' "$admin"
expect_grep "default Player Local admin" \
  'platform="Local" userid="Player"[^>]*permission_level="0"' "$admin"

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

# definition + 4 call sites (create-server / launch-server / wipe / detached start)
n="$(grep -c 'seed_sandbox_admins' "$SB" || true)"
if [[ "$n" -lt 5 ]]; then
  echo "FAIL: expected seed_sandbox_admins definition + 4 call sites, found $n" >&2
  fail=1
fi

python3 - "$SB" <<'PY' || fail=1
import re, sys
text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
checks = [
    ("cmd_create_server", "seed_sandbox_admins"),
    ("cmd_launch_server", "seed_sandbox_admins"),
    ("cmd_wipe", "seed_sandbox_admins"),
    # `sb up` and `sb run both` both seed through start_server_detached.
    ("start_server_detached", "seed_sandbox_admins"),
]
fail = 0
for fn, needle in checks:
    m = re.search(rf'^{fn}\(\) \{{', text, re.M)
    if not m:
        print(f"FAIL: {fn} not found", file=sys.stderr)
        fail = 1
        continue
    rest = text[m.end():]
    n = re.search(r'\n[a-zA-Z_][a-zA-Z0-9_]*\(\) \{', rest)
    body = rest[: n.start()] if n else rest
    if needle not in body:
        print(f"FAIL: {fn} does not call {needle}", file=sys.stderr)
        fail = 1
sys.exit(fail)
PY

if [[ "$fail" -ne 0 ]]; then
  echo "test_sb_serveradmin: FAILED" >&2
  exit 1
fi
echo "test_sb_serveradmin: OK"
