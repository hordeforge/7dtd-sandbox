#!/usr/bin/env bash
# set_server_config_value unit tests: the XML rewriter at the heart of
# `launch-server`/`run both`. Uses the real stock-template shapes (tabs,
# trailing comments, commented-out UserDataFolder) so a regex regression
# fails here instead of at first launch. Part of `make test`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SB="$ROOT/scripts/sb"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail=0
active_value() { # active_value <cfg> <key> -> first active value or empty
  python3 - "$1" "$2" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
key = sys.argv[2]
pat = re.compile(r'<property\s+name="%s"\s+value="([^"]*)"' % re.escape(key))
for m in pat.finditer(text):
    op = text.rfind("<!--", 0, m.start())
    cl = text.rfind("-->", 0, m.start())
    if not (op != -1 and op > cl):
        print(m.group(1))
        break
PY
}

# Stock-template shapes: tab padding, trailing comment, commented property.
cfg="$TMP/serverconfig.xml"
cat > "$cfg" <<'EOF'
<?xml version="1.0"?>
<ServerSettings>
	<!-- GENERAL SERVER SETTINGS -->
	<property name="ServerPort"						value="26900"/>				<!-- Port you want the server to listen on. -->
	<property name="TelnetPort"					value="8081"/>				<!-- Port of the telnet server -->
	<property name="ServerName"					value="My Game Host"/>		<!-- Whatever you want the name of the server to be. -->
	<property name="EACEnabled"						value="true"/>				<!-- Enables/Disables EasyAntiCheat -->
	<!-- <property name="UserDataFolder"			value="absolute_path"/> -->	<!-- Use this to override where the server stores all user data. -->
</ServerSettings>
EOF

# shellcheck disable=SC1090 # extract the function from sb without running main
source /dev/stdin <<<"$(sed -n '/^set_server_config_value()/,/^}/p' "$SB")"

set_server_config_value "$cfg" ServerPort 27105
set_server_config_value "$cfg" TelnetPort 27106
set_server_config_value "$cfg" ServerName "sandbox-demo"
set_server_config_value "$cfg" EACEnabled false
set_server_config_value "$cfg" UserDataFolder /srv/userdata

expect_eq() { # expect_eq <desc> <got> <want>
  if [[ "$2" != "$3" ]]; then
    echo "FAIL: $1 (got '$2' want '$3')" >&2
    fail=1
  fi
}

expect_eq "ServerPort rewritten"     "$(active_value "$cfg" ServerPort)"     "27105"
expect_eq "TelnetPort rewritten"     "$(active_value "$cfg" TelnetPort)"     "27106"
expect_eq "ServerName with space"    "$(active_value "$cfg" ServerName)"     "sandbox-demo"
expect_eq "EACEnabled to false"      "$(active_value "$cfg" EACEnabled)"     "false"
expect_eq "UserDataFolder inserted"  "$(active_value "$cfg" UserDataFolder)" "/srv/userdata"

# Exactly one active ServerPort after rewrite (no duplicates appended).
n_port="$(grep -c 'name="ServerPort"' "$cfg")"
expect_eq "single ServerPort total"  "$n_port" "1"

# Commented UserDataFolder template line must remain commented; the active
# one is the inserted copy, not an uncommented stock line.
if grep -q '^	<!-- <property name="UserDataFolder"' "$cfg"; then
  : # stock commented line preserved verbatim
else
  echo "FAIL: stock commented UserDataFolder was mangled" >&2
  fail=1
fi

# Valid XML after the rewrites (the game parses it).
python3 -c "import xml.etree.ElementTree, sys; xml.etree.ElementTree.parse(sys.argv[1])" "$cfg" \
  || { echo "FAIL: serverconfig no longer valid XML" >&2; fail=1; }

if [[ "$fail" -ne 0 ]]; then
  echo "sb_serverconfig: FAILED" >&2
  exit 1
fi
echo "sb_serverconfig: ok"
