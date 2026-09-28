#!/usr/bin/env python3
"""Fuzz gate for the two untrusted-input parsers in scripts/sbconfig.py.

Both read text this repository does not control: the serverconfig template
shipped by the dedicated depot and a serveradmin.xml that a previous run, a
world, or the game itself left in an instance's userdata. Both are rewritten
with regexes (`set_property` / `active_value` / `_upsert_user`) and the admin
file is a persistence boundary, so a malformed input is not a stack trace, it
is a config the server then reads.

Structure-aware generation over a stock-shaped seed corpus, then byte-level
mutation of the result. Every iteration asserts the invariants a fuzzer alone
cannot see: the write/read round trip, XML well-formedness, 0600 mode, the
declared admins, and idempotence. Deterministic (seeded) so a failure
reproduces from the printed seed and iteration; `--iters`/`--seed` widen a run.

No third-party fuzzer: this repository's Python is stdlib only, so the harness
is a seeded generator rather than coverage-guided.
"""

from __future__ import annotations

import argparse
import random
import string
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sbconfig

# The gate's own budget. Small enough to run in `make test` on every push,
# large enough for the mutation chain to reach the insert, upsert and
# comment-shaped paths rather than only the happy path.
ITERATIONS = 400
SEED = 20260928

# Seeds that found a real defect, replayed at the same iteration count on every
# push alongside SEED. A generator is only as good as the seeds it is pinned
# to: SEED alone kept passing while a fixed SEED and four others each found a
# broken rewrite, so a defect fixed today could be reintroduced by any later
# change and no seed in the default run would notice. Each is here with the
# defect it reproduces, and a new finding's printed seed is added the same way.
#   119: a `>` inside an attribute value ended the tag the upsert rewrote.
#   7: an adopted entry carrying only `name` was granted but had no `userid`.
#   1234: the `>` case again, found independently at a wider iteration count.
REGRESSION_SEEDS = (7, 119, 1234)

# A call that takes this long is a finding: `_upsert_user`'s lookaheads scan
# to the next `>` from every start offset, so a crafted file with very long
# `>`-free attribute runs is quadratic in the file length.
CALL_BUDGET_S = 5.0

MAX_DOC_CHARS = 4000
MAX_FRAGMENTS = 24
MAX_RUN_CHARS = 400

# What a case carries besides the document: the property sets a serverconfig
# check writes, or the admin names a serveradmin check seeds. `run` is generic
# over it so the two cases keep their own payload type instead of sharing an
# `object` the checker cannot follow.
Payload = TypeVar("Payload")

# The generator's shape rolls and probabilities. Named so a document shape
# read off a finding is a constant in this file, not a literal in a branch.
P_MUTATE = 0.5
P_STOCK = 0.25
P_CLOSE_TAGS = 0.9
P_SELF_CLOSING = 0.5

CONFIG_COMMENTED = 2
ADMIN_WHITELIST = 2
ADMIN_NOISE = 3
ADMIN_TRUNCATED_USER = 4
MUTATE_INSERT = 2
MUTATE_DELETE = 3

SERVERCONFIG_KEYS = (
    "ServerPort",
    "TelnetPort",
    "ServerName",
    "ServerDescription",
    "EACEnabled",
    "UserDataFolder",
    "GameWorld",
    "TelnetPassword",
    "MaxSpawnedZombies",
    "MaxPlayers",
)

ADMIN_NAMES = ("client-sg", "Player", "admin", "srv-1.2_x")

# Values a caller can actually declare: XML metacharacters, a null byte, a
# newline, a lone surrogate escape, and the plain text around them.
NON_ASCII_VALUE_CHARS = ("\u00e9", "\u4e2d", "\U0001f600")
HOSTILE_VALUE_CHARS = (*tuple("\"'<>&;\n\t\x00\r"), *NON_ASCII_VALUE_CHARS)

# Seed corpus: the stock dedicated serverconfig shapes (`sb` renders from this
# file, so its comments and tab padding are what the renderer really meets).
STOCK_SERVERCONFIG = """<?xml version="1.0"?>
<ServerSettings>
\t<property name="ServerPort"\t\t\tvalue="26900"/>\t\t<!-- Port -->
\t<property name="ServerName"\t\t\tvalue="My Game Host"/>
\t<property name="EACEnabled"\t\t\tvalue="true"/>
\t<!-- <property name="UserDataFolder"\tvalue="absolute_path"/> -->
\t<!-- <property name="GameWorld" value="Navezgane"/> -->
</ServerSettings>
"""

# The stock serveradmin.xml, in the paired and self-closing <user> forms the
# upsert has to handle.
STOCK_SERVERADMIN = """<?xml version="1.0" encoding="UTF-8"?>
<adminTools>
  <users>
    <user platform="Local" userid="Player" name="Player" permission_level="0" />
    <user platform="Steam" userid="76561198000000000" name="steamer" permission_level="1000"></user>
  </users>
  <whitelist>
  </whitelist>
</adminTools>
"""


def _random_value(rng: random.Random) -> str:
    body = "".join(
        rng.choice(HOSTILE_VALUE_CHARS + tuple(string.printable[:40]))
        for _ in range(rng.randrange(0, 12))
    )
    return body or rng.choice(SERVERCONFIG_KEYS)


def _serverconfig_fragment(rng: random.Random) -> str:
    key = rng.choice(SERVERCONFIG_KEYS)
    value = _random_value(rng)
    shape = rng.randrange(4)
    if shape == 0:
        return f'\t<property name="{key}"\tvalue="{value}"/>'
    if shape == 1:
        return f'\t<property name="{key}" value="{value}"/>\t\t<!-- note -->'
    if shape == CONFIG_COMMENTED:
        return f'\t<!-- <property name="{key}" value="{value}"/> -->'
    return f'\t<property name="{key}" value="{value}" />'


def _user_fragment(rng: random.Random, name: str) -> str:
    platform = rng.choice(("Local", "Local", "Steam", "EOS"))
    level = rng.choice(("0", "0", "1000", ""))
    spelled = rng.choice((name, "Player", "steamer"))
    attrs = [
        f'platform="{platform}"',
        f'userid="{name}"',
        f'name="{spelled}"',
    ]
    if level:
        attrs.append(f'permission_level="{level}"')
    rng.shuffle(attrs)
    body = " ".join(attrs)
    if rng.random() < P_SELF_CLOSING:
        return f"    <user {body} />"
    return f"    <user {body}></user>"


def _serveradmin_fragment(rng: random.Random, names: list[str]) -> str:
    roll = rng.randrange(6)
    if roll == 0:
        return "\n".join(_user_fragment(rng, rng.choice(names)) for _ in range(rng.randrange(1, 5)))
    if roll == 1:
        return "  </users>"
    if roll == ADMIN_WHITELIST:
        return "  <whitelist>\n  </whitelist>"
    if roll == ADMIN_NOISE:
        return "\n" + rng.choice(("x" * rng.randrange(1, MAX_RUN_CHARS), "\t", "\n", "<!-- c -->"))
    if roll == ADMIN_TRUNCATED_USER:
        return f'  <user platform="Local" userid="{rng.choice(names)}" name="x">oops'
    return rng.choice(('<?xml version="1.0"?>', "<adminTools>", "</adminTools>", ""))


def _mutate(rng: random.Random, text: str) -> str:
    """Byte-level damage: this is the corrupted-file shape a crash report carries."""
    chars = list(text[:MAX_DOC_CHARS])
    for _ in range(rng.randrange(1, 4)):
        if not chars:
            break
        roll = rng.randrange(5)
        at = rng.randrange(len(chars))
        if roll == 0:
            chars[at] = rng.choice(HOSTILE_VALUE_CHARS)
        elif roll == 1:
            chars[at] = ""
        elif roll == MUTATE_INSERT:
            chars.insert(at, rng.choice(HOSTILE_VALUE_CHARS))
        elif roll == MUTATE_DELETE:
            del chars[at : at + rng.randrange(1, 8)]
        else:
            chars[at : at + 1] = list(rng.choice(("<!--", "-->", ">", "<user ", "</users>", '"')))
    return "".join(chars)[:MAX_DOC_CHARS]


def _serverconfig_input(rng: random.Random) -> str:
    if rng.random() < P_STOCK:
        body = STOCK_SERVERCONFIG
    else:
        parts = [_serverconfig_fragment(rng) for _ in range(rng.randrange(1, MAX_FRAGMENTS))]
        if rng.random() < P_CLOSE_TAGS:
            parts.insert(rng.randrange(len(parts) + 1), "</ServerSettings>")
        joined = "\n".join(parts)
        body = f'<?xml version="1.0"?>\n<ServerSettings>\n{joined}\n</ServerSettings>\n'
    return body if rng.random() < P_MUTATE else _mutate(rng, body)


def _serveradmin_input(rng: random.Random, names: list[str]) -> str:
    if rng.random() < P_STOCK:
        body = STOCK_SERVERADMIN
    else:
        parts = [_serveradmin_fragment(rng, names) for _ in range(rng.randrange(1, MAX_FRAGMENTS))]
        if rng.random() < P_CLOSE_TAGS and not any(p.strip() == "</users>" for p in parts):
            parts.append("  </users>")
        head = '<?xml version="1.0" encoding="UTF-8"?>\n<adminTools>\n  <users>'
        joined = "\n".join(parts)
        body = f"{head}{joined}\n  </users>\n</adminTools>\n"
    return body if rng.random() < P_MUTATE else _mutate(rng, body)


def _shrink(rng: random.Random, failure: str, reproduce: Callable[[str], bool]) -> str:
    """Delta-debug the offending document so the report is a minimal reproducer."""
    doc = failure
    chunk = max(1, len(doc) // 2)
    while chunk:
        at = 0
        while at < len(doc):
            candidate = doc[:at] + doc[at + chunk :]
            if candidate and reproduce(candidate):
                doc = candidate
            else:
                at += chunk
        chunk //= 2
    return doc


class Finding(Exception):
    """An invariant the fuzzer observed broken, with its shrunk reproducer."""

    def __init__(self, detail: str, doc: str) -> None:
        super().__init__(detail)
        self.detail = detail
        self.doc = doc
        self.iteration = -1


def _require(condition: bool, detail: str, doc: str) -> None:
    if not condition:
        raise Finding(detail, doc)


def _timed(doc: str, call: Callable[..., object], *args: object, **kwargs: object) -> object:
    start = time.perf_counter()
    result = call(*args, **kwargs)
    elapsed = time.perf_counter() - start
    _require(
        elapsed < CALL_BUDGET_S,
        f"{call.__name__} took {elapsed:.2f}s on a {len(doc)} char document",
        doc,
    )
    return result


def _parses(text: str) -> bool:
    try:
        ET.fromstring(text)
    except (ET.ParseError, ValueError):
        return False
    return True


def serverconfig_case(rng: random.Random) -> tuple[str, dict[str, str]]:
    key = rng.choice(SERVERCONFIG_KEYS)
    return _serverconfig_input(rng), {key: _random_value(rng)}


def check_serverconfig(doc: str, sets: dict[str, str], tmp: Path) -> None:
    """`render` then `get` is a round trip across a write/read boundary.

    Whatever the input, a property the renderer wrote has to read back with the
    value that was declared, a well-formed source has to stay well-formed (a
    quote in a value cannot add an element), and the config has to land 0600.
    """
    key, value = next(iter(sets.items()))
    src = tmp / "in.xml"
    dst = tmp / "out.xml"
    src.write_text(doc, encoding="utf-8")
    try:
        _timed(doc, sbconfig.render, src, dst, userdata=None, sets=sets)
    except (RuntimeError, ValueError) as ex:
        # Declined input, not a finding, as long as nothing was written.
        _require(not dst.exists(), f"declined render still wrote {dst}: {ex}", doc)
        return

    out = dst.read_bytes().decode("utf-8")
    read = sbconfig.active_value(out, key)
    _require(
        read == value,
        f"round trip lost {key!r}: wrote {value!r}, read {read!r}",
        doc,
    )
    _require(
        dst.stat().st_mode & 0o077 == 0,
        f"rendered config is {dst.stat().st_mode & 0o777:o}",
        doc,
    )
    source_wellformed = _parses(doc)
    try:
        root = ET.fromstring(out)
    except ET.ParseError as ex:
        if source_wellformed:
            raise Finding(
                f"render turned a well-formed template into broken XML: {ex}", doc
            ) from ex
        return
    if source_wellformed:
        # Pair assertion across the injection boundary: the declared property
        # is the only element the declaration produced.
        values = [p.get("value") for p in root.findall("property") if p.get("name") == key]
        _require(set(values) == {value}, f"declaration of {key!r} produced values {values!r}", doc)
    # A second render of the same declaration is byte-identical.
    again = tmp / "again.xml"
    sbconfig.render(src, again, userdata=None, sets=sets)
    _require(again.read_bytes() == dst.read_bytes(), "re-render diverged", doc)


def serveradmin_case(rng: random.Random) -> tuple[str, list[str]]:
    names = [rng.choice(ADMIN_NAMES) for _ in range(rng.randrange(1, 4))]
    return _serveradmin_input(rng, names), names


def check_serveradmin(doc: str, names: list[str], tmp: Path) -> None:
    """`seed-admins` rewrites whatever is in Saves, so it owes a valid file.

    Assertions: well-formed XML out, every declared name at permission 0, 0600,
    and a second seed that changes nothing.
    """
    admin = tmp / "userdata" / "Saves" / "serveradmin.xml"
    admin.parent.mkdir(parents=True, exist_ok=True)
    admin.write_text(doc, encoding="utf-8")
    changed = _timed(doc, sbconfig.seed_admins, admin, names)

    out = admin.read_bytes().decode("utf-8")
    try:
        root = ET.fromstring(out)
    except ET.ParseError as ex:
        raise Finding(f"seeded serveradmin.xml is broken XML: {ex}", doc) from ex
    if changed:
        # The documented contract: 0600 on creation and after a rewrite. A file
        # the seed left untouched keeps whatever mode it arrived with.
        _require(
            admin.stat().st_mode & 0o077 == 0,
            f"a rewritten serveradmin.xml is {admin.stat().st_mode & 0o777:o}",
            doc,
        )
    # Keyed by userid over the whole document, the last entry for a name wins,
    # so a Steam or EOS entry carrying the same userid shadowed the Local one
    # the seeder writes and the assertion failed on a file that grants what it
    # was declared. Stock auth maps `Local_<name>` to platform="Local", so only
    # the Local entry is the identity, and the check is that one is present at
    # level 0 (a duplicate Local entry for the same name does not make it not
    # present).
    granted = {
        u.get("userid")
        for u in root.iter("user")
        if u.get("platform") == "Local" and u.get("permission_level") == "0"
    }
    for name in names:
        _require(name in granted, f"declared admin {name!r} is not a Local level-0 entry", doc)
    _require(
        _timed(doc, sbconfig.seed_admins, admin, names) is False,
        "a second seed changed a correct file",
        doc,
    )
    _require(admin.read_bytes() == out.encode("utf-8"), "an idempotent seed rewrote the file", doc)


def run(
    name: str,
    build: Callable[[random.Random], tuple[str, Payload]],
    check: Callable[[str, Payload, Path], None],
    iterations: int,
    seed: int,
) -> int:
    findings: list[Finding] = []
    for index in range(iterations):
        # S311: seeded from --seed, so the corpus is reproducible rather than
        # unpredictable. Cryptographic strength is not a property a fuzzer wants.
        doc, payload = build(random.Random(seed + index))  # noqa: S311

        # payload is bound as a default argument, not closed over: `reproduce`
        # has to keep checking *this* iteration's payload. A shrinker that ran
        # after the loop advanced would otherwise re-check the shrunk document
        # against the next iteration's payload and report a reproducer that
        # does not reproduce.
        def reproduce(candidate: str, expected: Payload = payload) -> bool:
            with tempfile.TemporaryDirectory() as td:
                try:
                    check(candidate, expected, Path(td))
                except Exception:  # any failure at all is a finding, not a crash
                    return True
            return False

        with tempfile.TemporaryDirectory() as td:
            try:
                check(doc, payload, Path(td))
            except Finding as ex:
                ex.iteration = index
                ex.doc = _shrink(random.Random(seed + index), ex.doc, reproduce)  # noqa: S311
                findings.append(ex)
            except Exception as ex:  # uncaught means the parser broke, not that the input was bad
                escaped = Finding(f"uncaught {type(ex).__name__}: {ex}", "")
                escaped.iteration = index
                findings.append(escaped)

    for ex in findings:
        print(
            f"FAIL {name} iteration {ex.iteration} (seed {seed + ex.iteration}): {ex.detail}",
            file=sys.stderr,
        )
        if ex.doc:
            escaped = ex.doc.encode("unicode_escape").decode("ascii")
            print("reproducer:\n" + escaped, file=sys.stderr)
    if findings:
        print(
            f"test_sbconfig_fuzz: FAILED ({len(findings)} findings in {name}, seed {seed})",
            file=sys.stderr,
        )
        return 1
    print(f"test_sbconfig_fuzz: {name}: OK ({iterations} iterations, seed {seed})")
    return 0


TARGETS = (
    ("serverconfig", serverconfig_case, check_serverconfig),
    ("serveradmin", serveradmin_case, check_serveradmin),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iters", type=int, default=ITERATIONS)
    parser.add_argument(
        "--seed",
        type=int,
        action="append",
        help="seed to run; repeatable. Defaults to SEED and every regression seed",
    )
    args = parser.parse_args()
    seeds = tuple(args.seed) if args.seed else (SEED, *REGRESSION_SEEDS)
    failed = 0
    for seed in seeds:
        for name, build, check in TARGETS:
            failed += run(name, build, check, args.iters, seed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
