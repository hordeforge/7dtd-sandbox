#!/usr/bin/env bash
# The release contract, checked without a tag: the version this repository
# ships must be a version the changelog documents. release.yml rejects a bad
# tag, but only once someone has pushed it; this rejects the same mistake on
# every push, and the two checks are the same rules so neither can drift.
# Pure file checks, no network and no game. Part of `make test`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SB="$ROOT/scripts/sb"
CHANGELOG="$ROOT/CHANGELOG.md"

fail=0
note() { echo "FAIL: $1" >&2; fail=1; }

# --- the version is a version -----------------------------------------------

SHIPPED="$(sed -n 's/^SB_VERSION="\([^"]*\)".*/\1/p' "$SB" | head -1)"
[[ -n "$SHIPPED" ]] || { echo "FAIL: no SB_VERSION=\"...\" in scripts/sb" >&2; exit 1; }

# release.yml compares the tag against this string verbatim, so anything that
# is not a plain MAJOR.MINOR.PATCH is a tag shape a consumer cannot order.
if [[ ! "$SHIPPED" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  note "SB_VERSION '$SHIPPED' is not MAJOR.MINOR.PATCH"
fi

# There is exactly one version home. A second literal in the tree is a value
# that can disagree with the tag gate without the gate seeing it. The file
# types are the ones that can carry a sandbox version: the docs and CI, the
# shell, the Python gates, the config, and the Dockerfile (whose version comes
# from the build arg, so its ARG default is filtered rather than its file).
# The Makefile is not in the list: it carries the analyzer pins, which are
# version literals by their own right and are held by check-analyzer-versions
# and scripts/test_sb_cli.sh.
dupes="$(grep -rn --exclude-dir=.git -E '\b[0-9]+\.[0-9]+\.[0-9]+\b' "$ROOT" \
  --include='*.md' --include='*.yml' --include='*.sh' --include='*.py' \
  --include='*.toml' --include='Dockerfile*' --include='sb' \
  | grep -v 'CHANGELOG.md' | grep -E 'version|VERSION' | grep -v 'SB_VERSION=' || true)"
[[ -z "$dupes" ]] || note "a second version declaration can drift from SB_VERSION:
$dupes"

# --- the changelog documents the shipped version -----------------------------

# A bump lands with its notes in the same commit, which is how every release
# here was made (0.1.0 through 0.3.0 each touched CHANGELOG.md and scripts/sb
# together). A version with no section is a tag whose release notes are empty.
if ! grep -qE "^## \[$SHIPPED\] - [0-9]{4}-[0-9]{2}-[0-9]{2}$" "$CHANGELOG"; then
  note "CHANGELOG.md has no '## [$SHIPPED] - YYYY-MM-DD' section for the shipped version"
fi

# That a release section is not left empty, with its notes still under
# [Unreleased], is checked where it can be proven and still refused: the tag
# gate, at push time. Enforcing it here would forbid the very habit this file
# is for, which is writing a change down before it is released.

# Every released heading needs its link definition, or the rendered page shows
# the raw [0.2.0] instead of a diff.
while read -r ver; do
  grep -qF "[$ver]:" "$CHANGELOG" || note "no link definition for [$ver]"
done < <(sed -n 's/^## \[\([0-9][^]]*\)\] - .*/\1/p' "$CHANGELOG")

# A compare link is only a diff if it names the previous release. The first
# release has no previous one, so it links its tag instead.
prev=""
while read -r ver; do
  if [[ -n "$prev" ]]; then
    link="$(sed -n "s/^\[$ver\]: \(.*\)$/\1/p" "$CHANGELOG" | head -1)"
    [[ "$link" == *"compare/v$prev...v$ver" ]] \
      || note "[$ver] link '$link' does not compare v$prev...v$ver"
  fi
  prev="$ver"
done < <(sed -n 's/^## \[\([0-9][^]]*\)\] - .*/\1/p' "$CHANGELOG" | tac)

# The Unreleased compare link points at the newest released tag. When it lags,
# the diff a reader opens is not the diff since the last release.
newest="$(sed -n 's/^## \[\([0-9][^]]*\)\] - .*/\1/p' "$CHANGELOG" | head -1)"
unreleased="$(sed -n 's/^\[Unreleased\]: \(.*\)$/\1/p' "$CHANGELOG" | head -1)"
[[ "$unreleased" == *"compare/v$newest...HEAD" ]] \
  || note "[Unreleased] link '$unreleased' does not compare v$newest...HEAD"

# --- the changelog is well formed -------------------------------------------

# Releases are newest first, and each carries a date.
mapfile -t releases < <(sed -n 's/^## \(\[[0-9][^]]*\] - [0-9-]*\)$/\1/p' "$CHANGELOG")
[[ "${releases[0]:-}" == "[$newest] -"* ]] || note "releases are not newest first"

# One heading per group per release. Two "### Fixed" blocks under one version
# is a formatting slip that reads as two separate fixes, and Keep a Changelog
# groups them into one.
while read -r dup; do
  note "'$dup' repeats a group heading inside one release"
done < <(awk '
  function report(  g) { for (g in seen) if (seen[g] > 1) print section " " g }
  /^## \[/ { report(); section = $0; delete seen; next }
  /^### /  { gsub(/^### /, "", $0); sub(/ .*/, "", $0); seen[$0]++ }
  END      { report() }
' "$CHANGELOG" | sort -u)

# The Unreleased section exists even when empty: its absence is how a shipped
# change reaches a tag with nowhere to have been written down.
grep -q '^## \[Unreleased\]' "$CHANGELOG" || note "no [Unreleased] section"

if [[ "$fail" -ne 0 ]]; then
  echo "sb_release: FAILED" >&2
  exit 1
fi
echo "sb_release: ok"
