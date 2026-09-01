#!/usr/bin/env python3
"""Serverconfig renderer and serveradmin seeder for 7DTD dedicated instances.

One implementation for the whole workspace. `sb` calls it; sibling harnesses
(loadgen, playtest) call it through `sb render-config` or directly, instead of
each carrying its own XML rewriter.

  sbconfig.py render SRC DST [--userdata PATH] [--set KEY=VALUE ...]
  sbconfig.py seed-admins USERDATA --name NAME [--name NAME ...]
  sbconfig.py port-block NAME [--instances DIR] [--taken PORT ...]
  sbconfig.py get CFG KEY

render rewrites the value of every *active* `<property name="KEY" value="..."/>`
and inserts the property before `</ServerSettings>` when the file has none.
Properties inside XML comments are left verbatim, so the stock template's
commented `UserDataFolder` stays commented and the active value is the inserted
one. Values arrive as argv data and are XML-attribute escaped: a quote in a
world name can never terminate the attribute and inject further properties.

seed-admins upserts a `permission_level="0"` Local entry for each --name given.
Stock auth maps PltfmId `Local_<playername>` to platform="Local"
userid=<playername>; without a seed a Local join lands at permission 1000 and
cannot run dm/givetools. The names are declared by the instance
(`SERVER_ADMINS` in instance.env), never discovered from whatever other
instances happen to exist on the machine: the same declaration must produce
the same admin file on any host.

get prints the value of the first *active* property named KEY, so a caller
reading a config back sees what the game will read, not a value that only
appears inside a comment.

port-block derives an instance's 5-port block from its name, so the same name
gets the same ports on every machine regardless of what was created first.
Collisions with a block another instance already recorded are resolved by a
deterministic forward probe, and an exhausted range fails rather than
overlapping.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape, unescape

# Seeded even when no client instance exists yet, so a server-only create still
# yields a usable admin file.
DEFAULT_ADMIN_NAMES = ("Player", "client", "admin")

SETTINGS_CLOSER = "</ServerSettings>"

# Server port blocks: ServerPort (game, UDP+TCP), +1 telnet, +2..+4 spare (the
# dedicated opens a few ephemeral ports around ServerPort, and loadgen bots
# join on ServerPort+2).
PORT_BLOCK_BASE = 27100
PORT_BLOCK_SIZE = 5
PORT_BLOCK_COUNT = 100

# FNV-1a 32-bit: a stable hash across interpreters and machines. Python's own
# hash() is salted per process, so it would hand the same instance a different
# port on every run.
FNV_OFFSET_BASIS = 0x811C9DC5
FNV_PRIME = 0x01000193
FNV_MASK = 0xFFFFFFFF
USERS_CLOSER = "</users>"

ADMIN_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!-- Safehouse always-admin seed: Local sandbox clients get permission_level=0.
     Regenerated/upserted by `sb` on create-server / launch-server / wipe / run both.
-->
<adminTools>
  <users>
{users}
  </users>
  <whitelist>
  </whitelist>
  <blacklist>
  </blacklist>
  <commands>
  </commands>
</adminTools>
"""


def xml_attr(text: str) -> str:
    """Escape for a double-quoted XML attribute value."""
    return escape(text, {'"': "&quot;"})


def _in_comment(text: str, index: int) -> bool:
    """True when `index` sits inside an XML comment."""
    open_at = text.rfind("<!--", 0, index)
    close_at = text.rfind("-->", 0, index)
    return open_at != -1 and open_at > close_at


def set_property(text: str, key: str, value: str) -> str:
    """Return `text` with every active property `key` set to `value`.

    Inserts the property before </ServerSettings> when no active one exists.
    """
    pattern = re.compile(
        r'(<property\s+name="%s"\s+value=")([^"]*)(")' % re.escape(key)
    )
    escaped = xml_attr(value)
    pieces: list[str] = []
    cursor = 0
    replaced = 0
    for match in pattern.finditer(text):
        if _in_comment(text, match.start()):
            continue
        pieces.append(text[cursor : match.start()])
        pieces.append(match.group(1) + escaped + match.group(3))
        cursor = match.end()
        replaced += 1
    if replaced:
        pieces.append(text[cursor:])
        return "".join(pieces)

    inserted = '  <property name="%s" value="%s"/>\n%s' % (
        xml_attr(key),
        escaped,
        SETTINGS_CLOSER,
    )
    if SETTINGS_CLOSER not in text:
        raise ValueError(
            f"no active property {key!r} and no {SETTINGS_CLOSER} to insert before"
        )
    return text.replace(SETTINGS_CLOSER, inserted, 1)


def active_value(text: str, key: str) -> str | None:
    """Value of the first property `key` that is not inside an XML comment."""
    pattern = re.compile(
        r'<property\s+name="%s"\s+value="([^"]*)"' % re.escape(key)
    )
    for match in pattern.finditer(text):
        if not _in_comment(text, match.start()):
            # Mirror xml_attr: saxutils only reverses &amp;/&lt;/&gt; unless
            # the extra entities are named, and every value here was written
            # with &quot; for the attribute delimiter.
            return unescape(match.group(1), {"&quot;": '"'})
    return None


def render(
    src: Path,
    dst: Path,
    *,
    userdata: Path | None = None,
    sets: dict[str, str],
) -> str:
    """Render `src` into `dst` with the given property values. Returns the text."""
    try:
        text = src.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as ex:
        # A user-edited template can be non-UTF-8 or unreadable. Name the file
        # and the reason instead of a bare traceback: this runs after the
        # caller has already wiped the save it is about to regenerate.
        raise RuntimeError(f"cannot read serverconfig template {src}: {ex}") from ex

    if userdata is not None:
        text = set_property(text, "UserDataFolder", str(userdata.resolve()))
    for key, value in sets.items():
        text = set_property(text, key, value)

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
    except OSError as ex:
        raise RuntimeError(f"cannot write generated serverconfig {dst}: {ex}") from ex
    # The rendered config can carry TelnetPassword; keep it user-only rather
    # than inheriting a world-readable umask.
    try:
        os.chmod(dst, 0o600)
    except OSError as ex:
        print(f"WARN: could not restrict {dst} to 0600: {ex}", file=sys.stderr)
    return text


def fnv1a(text: str) -> int:
    """FNV-1a 32-bit over the UTF-8 bytes of `text`."""
    value = FNV_OFFSET_BASIS
    for byte in text.encode("utf-8"):
        value = ((value ^ byte) * FNV_PRIME) & FNV_MASK
    return value


def recorded_ports(instances: Path, exclude: str) -> set[int]:
    """SERVER_PORT values other instances under `instances` already hold."""
    taken: set[int] = set()
    if not instances.is_dir():
        return taken
    for entry in sorted(instances.iterdir()):
        if not entry.is_dir() or entry.name == exclude:
            continue
        env = entry / "instance.env"
        if not env.is_file():
            continue
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "SERVER_PORT" and value.strip().isdigit():
                taken.add(int(value.strip()))
    return taken


def port_block(name: str, taken: set[int]) -> int:
    """First free block for `name`, starting from its name-derived slot.

    The starting slot is a pure function of the name, so an instance gets the
    same ports on every machine no matter what was created before it. The
    probe only moves when another instance already recorded that block.
    """
    start = fnv1a(name) % PORT_BLOCK_COUNT
    for offset in range(PORT_BLOCK_COUNT):
        slot = (start + offset) % PORT_BLOCK_COUNT
        port = PORT_BLOCK_BASE + slot * PORT_BLOCK_SIZE
        if port not in taken:
            return port
    raise ValueError(
        f"no free port block for {name!r}: all {PORT_BLOCK_COUNT} blocks from "
        f"{PORT_BLOCK_BASE} are recorded by other instances"
    )


def _user_line(name: str) -> str:
    return (
        f'    <user platform="Local" userid="{xml_attr(name)}" '
        f'name="{xml_attr(name)}" permission_level="0" />'
    )


def _upsert_user(text: str, name: str) -> tuple[str, bool]:
    """Force a level-0 Local entry for `name`. Returns (text, changed)."""
    pattern = re.compile(
        r'(<user\b(?=[^>]*\bplatform="Local")(?=[^>]*\buserid="%s")[^>]*?/?>)'
        % re.escape(name),
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match is None:
        index = text.find(USERS_CLOSER)
        if index == -1:
            return text, False
        return text[:index] + _user_line(name) + "\n" + text[index:], True

    old = match.group(1)
    if 'permission_level="0"' in old:
        return text, False
    new = re.sub(r'permission_level="[^"]*"', 'permission_level="0"', old)
    if new == old:
        new = re.sub(r"\s*/?>$", ' permission_level="0" />', old)
    if new == old:
        return text, False
    return text[: match.start(1)] + new + text[match.end(1) :], True


def seed_admins(out: Path, names: list[str]) -> bool:
    """Create or upsert serveradmin.xml. Returns True when the file changed."""
    users_block = "\n".join(_user_line(n) for n in names)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.is_file():
        out.write_text(ADMIN_TEMPLATE.format(users=users_block), encoding="utf-8")
        return True

    text = out.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
    if USERS_CLOSER not in text:
        # Malformed or unexpected shape: a rewrite from template is the only
        # way to guarantee the Local admins the sandbox contract promises.
        _atomic_write(out, ADMIN_TEMPLATE.format(users=users_block))
        return True

    changed = False
    for name in names:
        text, hit = _upsert_user(text, name)
        changed = changed or hit
    if changed:
        _atomic_write(out, text)
    return changed


def _atomic_write(path: Path, text: str) -> None:
    """Publish via temp+replace so a failed write leaves the old file intact."""
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _parse_sets(items: list[str]) -> dict[str, str]:
    sets: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise ValueError(f"bad --set {item!r} (want KEY=VALUE)")
        sets[key] = value
    return sets


def cmd_render(args: argparse.Namespace) -> int:
    try:
        sets = _parse_sets(args.sets)
    except ValueError as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        return 2
    try:
        render(args.src, args.dst, userdata=args.userdata, sets=sets)
    except (RuntimeError, ValueError) as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        return 1
    print(f"config -> {args.dst}")
    return 0


def cmd_seed_admins(args: argparse.Namespace) -> int:
    names = list(dict.fromkeys([*args.names, *DEFAULT_ADMIN_NAMES]))
    try:
        changed = seed_admins(args.userdata / "Saves" / "serveradmin.xml", names)
    except OSError as ex:
        print(f"ERROR: cannot seed serveradmin.xml: {ex}", file=sys.stderr)
        return 1
    if changed:
        print(f"seeded serveradmin.xml (Local admins: {', '.join(names)})")
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    try:
        text = args.config.read_text(encoding="utf-8", errors="replace")
    except OSError as ex:
        print(f"ERROR: cannot read {args.config}: {ex}", file=sys.stderr)
        return 1
    value = active_value(text, args.key)
    if value is None:
        print(f"ERROR: no active property {args.key!r} in {args.config}", file=sys.stderr)
        return 1
    print(value)
    return 0


def cmd_port_block(args: argparse.Namespace) -> int:
    taken = set(args.taken)
    if args.instances is not None:
        taken |= recorded_ports(args.instances, exclude=args.name)
    try:
        print(port_block(args.name, taken))
    except ValueError as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    render_cmd = sub.add_parser("render", help="render a dedicated serverconfig")
    render_cmd.add_argument("src", type=Path)
    render_cmd.add_argument("dst", type=Path)
    render_cmd.add_argument(
        "--userdata",
        type=Path,
        default=None,
        help="resolve and set UserDataFolder to this path",
    )
    render_cmd.add_argument(
        "--set", dest="sets", action="append", default=[], metavar="KEY=VALUE"
    )
    render_cmd.set_defaults(func=cmd_render)

    seed_cmd = sub.add_parser("seed-admins", help="upsert declared Local admins")
    seed_cmd.add_argument("userdata", type=Path)
    seed_cmd.add_argument(
        "--name",
        dest="names",
        action="append",
        default=[],
        metavar="NAME",
        help="Local player name to admit as permission_level=0 (repeatable)",
    )
    seed_cmd.set_defaults(func=cmd_seed_admins)

    port_cmd = sub.add_parser("port-block", help="this instance's 5-port block")
    port_cmd.add_argument("name")
    port_cmd.add_argument(
        "--instances",
        type=Path,
        default=None,
        help="instances dir; blocks other instances already recorded are skipped",
    )
    port_cmd.add_argument(
        "--taken", type=int, action="append", default=[], metavar="PORT"
    )
    port_cmd.set_defaults(func=cmd_port_block)

    get_cmd = sub.add_parser("get", help="read back an active property value")
    get_cmd.add_argument("config", type=Path)
    get_cmd.add_argument("key")
    get_cmd.set_defaults(func=cmd_get)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
