#!/usr/bin/env python3
"""Fuzz gate for the three untrusted-input parsers in scripts/sbconfig.py.

Two read text this repository does not control and rewrite in place: the
serverconfig template shipped by the dedicated depot and a serveradmin.xml that
a previous run, a world, or the game itself left in an instance's userdata.
Both are rewritten with regexes (`set_property` / `active_value` /
`_upsert_user`) and the admin file is a persistence boundary, so a malformed
input is not a stack trace, it is a config the server then reads.

The third reads the *other* instances' `instance.env` files while allocating a
port block (`recorded_ports` / `port_block`). Those are the least controlled
input in the tree: a hand edit, another uid's file, or a truncated write on a
machine running several harnesses at once, all read during an unrelated `sb
create`.

Structure-aware generation over a stock-shaped seed corpus, then byte-level
mutation of the result. Every iteration asserts the invariants a fuzzer alone
cannot see: the write/read round trip, XML well-formedness, 0600 mode, the
declared admins, idempotence, and a port block that is in range, unrecorded and
reproducible. Deterministic (seeded) so a failure reproduces from the printed
seed and iteration; `--iters`/`--seed` widen a run.

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
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, NamedTuple, TypeVar

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

# The instances tree the port scan walks: how many directories, and how often a
# directory holds an instance.env that is not a plain file or a plain line. The
# three shape rolls are cumulative thresholds off one draw, not independent
# probabilities.
PORT_MAX_INSTANCES = 6
P_PORT_VALID = 0.45
P_PORT_LONG = 0.65
P_PORT_SHAPE = 0.2
P_PORT_FS_SHAPE = 0.15

# A port-scan document is a rendering, not the file: a 5000-digit run is a few
# thousand characters nobody reads in a report, so it is shortened there.
PORT_RUN_CHARS = 40

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


# Instance names a `sb create` can be handed, and directories already under
# `instances/`. The lone surrogate is one the filesystem accepts and fnv1a has
# to hash over the bytes it came from; the long one is a path a caller can
# really create. The excluded name is the one being created, which the scan has
# to skip so an instance never blocks itself.
PORT_NAMES = (
    "srv-lab",
    "srv-self",
    "client-x",
    "José",
    "istanbul",
    "a" * 200,
    "srv-\udcff",
    "with space",
    "-dash",
)

# One `SERVER_PORT` line, and whether the scan records the port written into
# it. The flag is the generator's own expectation, so the check asserts
# against what it built rather than re-parsing the file back into a verdict.
#
# A comment is not special to this scan: it splits on `=`, so only a line whose
# key is exactly SERVER_PORT counts, and read_text's universal newlines turn a
# bare CR into the line ending it already behaves like. What bites the value is
# a superscript (a digit to isdigit(), not one to int()), a NUL (not whitespace,
# so strip() leaves it) and anything past five digits.
_PORT_LINES: tuple[tuple[str, bool], ...] = (
    ("SERVER_PORT={p}\n", True),
    ("SERVER_PORT={p}\r\n", True),
    (" SERVER_PORT = {p} \n", True),
    ("SERVER_ADMINS=alice\nSERVER_PORT={p}\n", True),
    ("SERVER_PORT={p}\nSERVER_TELNET_PORT={q}\n", True),
    ("SERVER_PORT={p}\nSERVER_PORT={p}\n", True),
    # U+00A0 is whitespace to str.strip(), so the value still declares a port.
    ("SERVER_PORT={p} \u00a0\n", True),
    ("SERVER_PORT={p}\u0000\n", False),
    ("SERVER_PORT={p}\u0001\n", False),
    ("# SERVER_PORT={p}\n", False),
    ("PORT_SERVER={p}\n", False),
    ("SERVERPORT={p}\n", False),
    ("SERVER_PORT=\n", False),
    ("SERVER_PORT\n", False),
    ("SERVER_PORT=-{p}\n", False),
    ("SERVER_PORT=+{p}\n", False),
    ("SERVER_PORT=0x{p}\n", False),
    ("SERVER_PORT=27\u00b2\n", False),
)

# An instance.env is a text file on a shared machine, so the bytes are ones a
# hand edit, another uid or a truncated write leaves behind. Written as bytes,
# not str, so the read path really meets a decode error. The scan decodes with
# errors="replace" and splits on universal newlines, so the last one holds two
# SERVER_PORT lines; the later one supersedes the earlier, which is no claim.
_PORT_RAW_LINES: tuple[tuple[bytes, frozenset[int]], ...] = (
    (b"SERVER_PORT=27105\xff\xfe\n", frozenset()),
    (b"SERVER_PORT=\xc3\xa9\n", frozenset()),
    (b"SERVER_PORT=27110\x00\n", frozenset()),
    (b"\xef\xbb\xbfSERVER_PORT=27115\n", frozenset()),
    (b"SERVER_PORT=27120\rSERVER_PORT=27125\n", frozenset({27125})),
)

# What else a directory under `instances/` holds besides the file the scan
# reads: a name that is a directory, and a link to a file nobody wrote.
PORT_FS_SHAPES = ("dir", "dangling")


class EnvEntry(NamedTuple):
    """One directory under `instances/`, and the ports the scan must take from it."""

    directory: str
    body: str | bytes
    shape: str
    records: frozenset[int]


def _port_run(rng: random.Random) -> tuple[str, bool]:
    """A value, and whether it is a port the scan declares.

    The digit-run lengths are the boundary this pins: a run of PORT_MAX_DIGITS
    is still a port, and one past CPython's own 4300-digit str-to-int cap is
    not, so an unbounded run used to escape the scan as a ValueError.
    """
    roll = rng.random()
    if roll < P_PORT_VALID:
        slot = rng.randrange(0, sbconfig.PORT_BLOCK_COUNT)
        port = sbconfig.PORT_BLOCK_BASE + slot * sbconfig.PORT_BLOCK_SIZE
        return str(port), True
    if roll < P_PORT_LONG:
        return "9" * (sbconfig.PORT_MAX_DIGITS * rng.randrange(2, 1001)), False
    return str(rng.randrange(0, sbconfig.PORT_BLOCK_BASE + 999)), True


def _instance_fragment(rng: random.Random, name: str) -> EnvEntry:
    """One instance directory, named by the caller so no two entries collide.

    Two entries under one name would mean the second overwrites the first, and
    the check would then be asserting against a file that no longer exists.
    """
    if rng.random() < P_PORT_FS_SHAPE:
        return EnvEntry(name, "", rng.choice(PORT_FS_SHAPES), frozenset())
    if rng.random() < P_PORT_SHAPE:
        raw, records = rng.choice(_PORT_RAW_LINES)
        return EnvEntry(name, raw, "file", records)
    port, records = _port_run(rng)
    template, template_records = rng.choice(_PORT_LINES)
    # q is a neighbouring declaration, not part of the expectation: keep it a
    # plain port, so formatting a 5000-digit run cannot overflow int() here.
    body = template.format(p=port, q=sbconfig.PORT_BLOCK_BASE)
    return EnvEntry(
        name,
        body,
        "file",
        frozenset({int(port)}) if records and template_records else frozenset(),
    )


def _render_entries(entries: list[EnvEntry]) -> str:
    lines = []
    for entry in entries:
        if entry.shape != "file":
            lines.append(f"{entry.directory}/ instance.env is a {entry.shape}")
        else:
            body = entry.body
            if isinstance(body, str) and len(body) > PORT_RUN_CHARS:
                body = body[:PORT_RUN_CHARS] + f"... ({len(body)} chars)"
            lines.append(f"{entry.directory}/ instance.env = {body!r}")
    return "\n".join(lines)


def portscan_case(rng: random.Random) -> tuple[str, tuple[object, ...]]:
    exclude = rng.choice(PORT_NAMES)
    # PORT_NAMES walked once per lap, so every directory in the tree is its own
    # entry and the excluded name can be one of them.
    count = rng.randrange(1, PORT_MAX_INSTANCES)
    names = [f"{PORT_NAMES[i % len(PORT_NAMES)]}-{i}" for i in range(count)]
    rng.shuffle(names)
    entries = [_instance_fragment(rng, name) for name in names]
    expected = frozenset().union(*(e.records for e in entries)) if entries else frozenset()
    return _render_entries(entries), (entries, exclude, expected)


def check_portscan(doc: str, payload: tuple[object, ...], tmp: Path) -> None:
    """`recorded_ports` reads other instances' instance.env, none of them ours.

    That file is hand-editable, shared with other uids, and read while an
    unrelated `sb create` allocates a port, so the scan owes the caller the
    same thing the seed owes a serveradmin.xml: never raise, and report a port
    only when the file declares one. The pair assertion is across the boundary
    the port crosses: the block `port_block` hands out against everything
    already recorded, in range, not taken, and the same answer twice, so a
    recorded suite port still reproduces on another host.
    """
    entries, exclude, expected = payload
    instances = tmp / "instances"
    instances.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        inst = instances / entry.directory
        try:
            inst.mkdir(parents=True, exist_ok=True)
        except OSError as ex:
            _require(False, f"the generator could not stage {entry.directory!r}: {ex}", doc)
        if entry.shape == "dir":
            (inst / "instance.env").mkdir(exist_ok=True)
        elif entry.shape == "dangling":
            (inst / "instance.env").symlink_to(inst / "not-written.env")
        elif isinstance(entry.body, bytes):
            (inst / "instance.env").write_bytes(entry.body)
        else:
            (inst / "instance.env").write_text(entry.body, encoding="utf-8")

    try:
        taken = _timed(doc, sbconfig.recorded_ports, instances, exclude)
    except Exception as ex:  # the scan is tolerant by contract, so any raise is one
        raise Finding(f"recorded_ports raised {type(ex).__name__}: {ex}", doc) from ex
    _require(isinstance(taken, set), f"recorded_ports returned {type(taken).__name__}", doc)
    for port in sorted(taken):
        _require(
            str(port).isascii() and str(port).isdigit(),
            f"recorded_ports reported {_short(port)}, which is not an ASCII port",
            doc,
        )
        _require(
            len(str(port)) <= sbconfig.PORT_MAX_DIGITS,
            f"recorded_ports reported {_short(port)}, longer than any port",
            doc,
        )
    _require(
        expected <= taken,
        f"the scan lost declared ports {[_short(p) for p in sorted(expected - taken)]!r}",
        doc,
    )
    _require(
        taken <= expected,
        f"the scan invented ports {[_short(p) for p in sorted(taken - expected)]!r}",
        doc,
    )

    top = sbconfig.PORT_BLOCK_BASE + sbconfig.PORT_BLOCK_COUNT * sbconfig.PORT_BLOCK_SIZE
    try:
        port = _timed(doc, sbconfig.port_block, str(exclude), taken)
    except ValueError as ex:
        # Exhausting the range is a refusal, not a finding, but only when the
        # range really is exhausted: giving up early loses a block a caller
        # could have had.
        _require(
            taken >= set(range(sbconfig.PORT_BLOCK_BASE, top, sbconfig.PORT_BLOCK_SIZE)),
            f"the probe gave up with only {len(taken)} ports recorded: {ex}",
            doc,
        )
        return
    _require(
        sbconfig.PORT_BLOCK_BASE <= port < top,
        f"port_block handed out {port}, outside the block range",
        doc,
    )
    _require(port not in taken, f"port_block handed out {port}, already recorded", doc)
    _require(
        sbconfig.port_block(str(exclude), taken) == port,
        "the probe is not deterministic for one name",
        doc,
    )


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


def _short(number: int) -> str:
    """A number short enough to read in a report; a fuzz corpus holds 5000-digit ones."""
    text = str(number)
    return (
        text if len(text) <= PORT_RUN_CHARS else f"{text[:PORT_RUN_CHARS]}... ({len(text)} digits)"
    )


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


@dataclass(frozen=True)
class Target(Generic[Payload]):
    """One parser under fuzz, and whether its document is the input it reads.

    Only such a document can be shrunk: the port scan's is a rendering of a
    tree the check builds itself, and cutting it would report something the
    check never read.
    """

    name: str
    build: Callable[[random.Random], tuple[str, Payload]]
    check: Callable[[str, Payload, Path], None]
    shrink: bool


def run(target: Target[Payload], iterations: int, seed: int) -> int:
    name, build, check, shrink = target.name, target.build, target.check, target.shrink
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
                # Only a document the payload is derived from can be shrunk
                # down to a reproducer; the port scan's document is a rendering
                # of a tree it builds itself, and cutting it would report
                # something the check never read.
                if shrink:
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
    Target("serverconfig", serverconfig_case, check_serverconfig, shrink=True),
    Target("serveradmin", serveradmin_case, check_serveradmin, shrink=True),
    Target("portscan", portscan_case, check_portscan, shrink=False),
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
        for target in TARGETS:
            failed += run(target, args.iters, seed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
