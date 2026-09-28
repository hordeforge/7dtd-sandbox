#!/usr/bin/env python3
"""Gate for scripts/sbconfig.py, the workspace's serverconfig/admin renderer.

Drives the real CLI (``main(argv)``) and asserts the files it writes: an
injection through a property value, the stock template's commented shapes, the
insert-if-missing path, and the admin upsert. Part of ``make test``.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sbconfig

# sbconfig's exit surface: 0 rendered, 1 a failed render or a missing key,
# 2 a malformed invocation. Named so a change to it is a change here too.
EXIT_USAGE = 2

# The stock template mentions UserDataFolder twice: once commented, once
# active. A render must leave both and change only the active one.
USERDATA_MENTIONS_IN_STOCK = 2

# Stock-template shapes: tab padding, a trailing comment, a commented-out
# UserDataFolder, and one property that appears only inside a comment.
STOCK = """<?xml version="1.0"?>
<ServerSettings>
\t<property name="ServerPort"\t\t\tvalue="26900"/>\t\t<!-- Port -->
\t<property name="ServerName"\t\t\tvalue="My Game Host"/>
\t<property name="EACEnabled"\t\t\tvalue="true"/>
\t<!-- <property name="UserDataFolder"\tvalue="absolute_path"/> -->
\t<!-- <property name="GameWorld" value="Navezgane"/> -->
</ServerSettings>
"""


def active_values(text: str, key: str) -> list[str]:
    """Values of every property `key` that is not inside an XML comment."""
    import re

    pattern = re.compile(rf'<property\s+name="{re.escape(key)}"\s+value="([^"]*)"')
    return [m.group(1) for m in pattern.finditer(text) if not sbconfig._in_comment(text, m.start())]


def render(tmp: Path, *sets: str, src_text: str = STOCK) -> str:
    src = tmp / "serverconfig.xml"
    src.write_text(src_text, encoding="utf-8")
    dst = tmp / "out.xml"
    argv = ["render", str(src), str(dst), *[a for s in sets for a in ("--set", s)]]
    assert sbconfig.main(argv) == 0, f"render failed: {argv}"
    return dst.read_text(encoding="utf-8")


def test_rewrites_active_property(tmp: Path) -> None:
    out = render(tmp, "ServerPort=27105")
    assert active_values(out, "ServerPort") == ["27105"], out
    print("PASS rewrites_active_property")


def test_leaves_commented_property_commented(tmp: Path) -> None:
    """A commented stock line stays verbatim; the active value is an insert.

    Rewriting inside the comment is the bug that made a dedicated save under
    its default userdata while the harness wiped an empty tree.
    """
    out = render(tmp, "UserDataFolder=/srv/userdata")
    assert '<!-- <property name="UserDataFolder"' in out, out
    assert active_values(out, "UserDataFolder") == ["/srv/userdata"], out
    assert out.count('name="UserDataFolder"') == USERDATA_MENTIONS_IN_STOCK, out
    print("PASS leaves_commented_property_commented")


def test_inserts_missing_property_once(tmp: Path) -> None:
    out = render(tmp, "GameWorld=Navezgane", "TelnetPort=27106")
    assert active_values(out, "GameWorld") == ["Navezgane"], out
    assert active_values(out, "TelnetPort") == ["27106"], out
    assert out.count("</ServerSettings>") == 1, out
    print("PASS inserts_missing_property_once")


def test_value_cannot_inject_properties(tmp: Path) -> None:
    """A quote in a value must not terminate the attribute and add properties."""
    hostile = 'x"/><property name="EACEnabled" value="true'
    out = render(tmp, f"ServerName={hostile}")
    assert active_values(out, "EACEnabled") == ["true"], out
    assert out.count('name="EACEnabled"') == 1, out
    assert "&quot;" in out, out
    root = ET.fromstring(out)
    names = [p.get("name") for p in root.findall("property")]
    assert names.count("ServerName") == 1, names
    got = [p.get("value") for p in root.findall("property") if p.get("name") == "ServerName"]
    assert got == [hostile], got
    print("PASS value_cannot_inject_properties")


def test_output_is_valid_xml_and_private(tmp: Path) -> None:
    src = tmp / "in.xml"
    src.write_text(STOCK, encoding="utf-8")
    dst = tmp / "priv.xml"
    assert sbconfig.main(["render", str(src), str(dst), "--set", "TelnetPassword=hunter2"]) == 0
    ET.parse(dst)
    assert dst.stat().st_mode & 0o077 == 0, oct(dst.stat().st_mode)
    print("PASS output_is_valid_xml_and_private")


def test_userdata_flag_resolves(tmp: Path) -> None:
    src = tmp / "in.xml"
    src.write_text(STOCK, encoding="utf-8")
    dst = tmp / "ud.xml"
    rel = tmp / "sub" / ".." / "userdata"
    (tmp / "userdata").mkdir()
    assert sbconfig.main(["render", str(src), str(dst), "--userdata", str(rel)]) == 0
    got = active_values(dst.read_text(encoding="utf-8"), "UserDataFolder")
    assert got == [str((tmp / "userdata").resolve())], got
    print("PASS userdata_flag_resolves")


def test_rerun_is_byte_identical_and_never_appends(tmp: Path) -> None:
    """A re-render replaces the target wholesale.

    A crashed or interrupted earlier write can leave residue in the file the
    server is about to parse; the rerun must overwrite it, not append.
    """
    src = tmp / "in.xml"
    src.write_text(STOCK, encoding="utf-8")
    dst = tmp / "out.xml"
    argv = ["render", str(src), str(dst), "--set", "GameName=BotPoi4k"]
    assert sbconfig.main(argv) == 0
    first = dst.read_bytes()
    dst.write_bytes(first + b"\n<!-- stale residue from an earlier run -->\n")
    assert sbconfig.main(argv) == 0
    assert dst.read_bytes() == first, "second render diverged or kept residue"
    print("PASS rerun_is_byte_identical_and_never_appends")


def test_bad_set_fails_closed(tmp: Path) -> None:
    src = tmp / "in.xml"
    src.write_text(STOCK, encoding="utf-8")
    dst = tmp / "never.xml"
    assert sbconfig.main(["render", str(src), str(dst), "--set", "NoEquals"]) == EXIT_USAGE
    assert not dst.exists(), "a malformed --set still wrote a config"
    print("PASS bad_set_fails_closed")


def test_missing_template_names_the_file(tmp: Path) -> None:
    missing = tmp / "nope.xml"
    assert sbconfig.main(["render", str(missing), str(tmp / "o.xml")]) == 1
    print("PASS missing_template_names_the_file")


@contextlib.contextmanager
def _stdin(text: str):
    """Swap sys.stdin for a fixed string.

    contextlib.redirect_stdin needs 3.10 and the module under test supports
    3.7, so the swap is done by hand: sbconfig reads sys.stdin at call time.
    """
    saved = sys.stdin
    sys.stdin = io.StringIO(text)
    try:
        yield
    finally:
        sys.stdin = saved


def _seed_argv(ud: Path, *names: str) -> int:
    """`seed-admins` with the names on stdin, the way `sb` calls it.

    argparse refuses an unknown option by raising SystemExit, so the code is
    caught here rather than ending the gate on the first refusal.
    """
    argv = ["seed-admins", str(ud)]
    stdin = "".join(f"{name}\n" for name in names)
    try:
        with _stdin(stdin):
            return sbconfig.main(argv)
    except SystemExit as ex:
        return int(ex.code or 0)


def _seed(tmp: Path, *names: str) -> str:
    assert _seed_argv(tmp / "userdata", *names) == 0
    return (tmp / "userdata" / "Saves" / "serveradmin.xml").read_text(encoding="utf-8")


def test_seed_takes_no_name_argument(tmp: Path) -> None:
    """The names go on stdin, never in argv.

    An argument is readable through /proc/<pid>/cmdline by every account on
    the host, so a `--name` spelling would publish the player names a server
    admits for the lifetime of the process. The option is refused rather than
    ignored, so a caller still passing it fails loudly instead of seeding
    nothing.
    """
    with contextlib.redirect_stderr(io.StringIO()) as err:
        try:
            rc = sbconfig.main(["seed-admins", str(tmp / "userdata"), "--name", "client-x"])
        except SystemExit as ex:
            rc = int(ex.code or 0)
    assert rc == EXIT_USAGE, f"expected a refusal ({EXIT_USAGE}), got {rc}"
    assert "unrecognized arguments" in err.getvalue(), err.getvalue()
    seeded = tmp / "userdata" / "Saves" / "serveradmin.xml"
    assert not seeded.exists(), "a refused seed wrote a file"
    print("PASS seed_takes_no_name_argument")


def test_seed_reads_names_from_stdin(tmp: Path) -> None:
    """Blank lines around the names do not seed an empty userid."""
    ud = tmp / "userdata"
    with _stdin("\nclient-sg\n\n"):
        assert sbconfig.main(["seed-admins", str(ud)]) == 0
    root = ET.fromstring((ud / "Saves" / "serveradmin.xml").read_text(encoding="utf-8"))
    ids = {u.get("userid") for u in root.iter("user")}
    assert "client-sg" in ids, ids
    assert "" not in ids, ids
    print("PASS seed_reads_names_from_stdin")


def test_seeds_only_declared_names(tmp: Path) -> None:
    """Declared names plus the stable defaults, and nothing else.

    Discovering admins from whatever instances exist on the machine made the
    file depend on unrelated state, so two hosts produced different servers
    from the same declaration.
    """
    text = _seed(tmp, "client-sg")
    root = ET.fromstring(text)
    users = {u.get("userid"): u.get("permission_level") for u in root.iter("user")}
    assert users.get("client-sg") == "0", users
    for default in sbconfig.DEFAULT_ADMIN_NAMES:
        assert users.get(default) == "0", users
    assert set(users) == {"client-sg", *sbconfig.DEFAULT_ADMIN_NAMES}, users
    print("PASS seeds_only_declared_names")


def test_seed_upserts_demoted_admin(tmp: Path) -> None:
    _seed(tmp, "client-sg")
    admin = tmp / "userdata" / "Saves" / "serveradmin.xml"
    admin.write_text(
        admin.read_text(encoding="utf-8").replace(
            'userid="client-sg" name="client-sg" permission_level="0"',
            'userid="client-sg" name="client-sg" permission_level="1000"',
            1,
        ),
        encoding="utf-8",
    )
    text = _seed(tmp, "client-sg")
    root = ET.fromstring(text)
    users = {u.get("userid"): u.get("permission_level") for u in root.iter("user")}
    assert users.get("client-sg") == "0", users
    print("PASS seed_upserts_demoted_admin")


def test_seed_is_idempotent(tmp: Path) -> None:
    first = _seed(tmp, "client-sg")
    second = _seed(tmp, "client-sg")
    assert first == second, "reseed changed a correct file"
    print("PASS seed_is_idempotent")


def test_seed_is_idempotent_for_escaped_names(tmp: Path) -> None:
    """A name that gets XML-escaped is still found by its own upsert.

    The upsert looks the entry up by the value ``_user_line`` wrote. Matching
    the raw name instead meant a name carrying ``&``, ``<`` or a quote missed
    its own entry and appended a second one, so every launch of the instance
    grew the admin file by another copy.
    """
    first = _seed(tmp, 'a"b&c<d')
    second = _seed(tmp, 'a"b&c<d')
    assert first == second, "reseed duplicated an entry whose name needs escaping"
    root = ET.fromstring(second)
    assert [u.get("userid") for u in root.iter("user")].count('a"b&c<d') == 1
    print("PASS seed_is_idempotent_for_escaped_names")


def test_seed_is_host_independent(tmp: Path) -> None:
    """The same declaration produces the same file, byte for byte."""
    a = _seed(tmp, "client-lab", "extra")
    b = _seed(tmp / "elsewhere", "client-lab", "extra")
    assert a == b, "the same declaration produced two different admin files"
    print("PASS seed_is_host_independent")


def test_port_block_is_derived_from_the_name(tmp: Path) -> None:
    """Same name, same block, on any machine and in any creation order."""
    first = sbconfig.port_block("srv-lab", set())
    assert first == sbconfig.port_block("srv-lab", {sbconfig.PORT_BLOCK_BASE + 5000})
    assert first >= sbconfig.PORT_BLOCK_BASE
    assert (first - sbconfig.PORT_BLOCK_BASE) % sbconfig.PORT_BLOCK_SIZE == 0
    assert sbconfig.port_block("srv-other", set()) != first
    print("PASS port_block_is_derived_from_the_name")


def test_port_block_probes_past_a_taken_block(tmp: Path) -> None:
    first = sbconfig.port_block("srv-lab", set())
    probed = sbconfig.port_block("srv-lab", {first})
    assert probed != first
    assert probed == sbconfig.port_block("srv-lab", {first}), "probe is not deterministic"
    print("PASS port_block_probes_past_a_taken_block")


def test_port_block_exhaustion_fails_instead_of_overlapping(tmp: Path) -> None:
    every = {
        sbconfig.PORT_BLOCK_BASE + i * sbconfig.PORT_BLOCK_SIZE
        for i in range(sbconfig.PORT_BLOCK_COUNT)
    }
    try:
        sbconfig.port_block("srv-lab", every)
    except ValueError as ex:
        assert "no free port block" in str(ex), ex
    else:
        raise AssertionError("an exhausted range must fail, not overlap")
    print("PASS port_block_exhaustion_fails_instead_of_overlapping")


def test_port_block_stays_inside_the_port_space(tmp: Path) -> None:
    """Every block the allocator hands out fits, span and all.

    The block is a range the server binds in full (telnet at +1, the dedicated's
    own ephemeral ports at +2..+4), so a base that fits while the span does not
    yields an instance whose harness ports nothing can listen on.
    """
    last = sbconfig.PORT_BLOCK_BASE + (sbconfig.PORT_BLOCK_COUNT - 1) * sbconfig.PORT_BLOCK_SIZE
    assert last + (sbconfig.PORT_BLOCK_SIZE - 1) <= sbconfig.PORT_MAX, (
        "the declared block range runs past the last port"
    )
    for name in ("srv-lab", "srv-other", "client-a", "zzz"):
        port = sbconfig.port_block(name, set())
        assert (port - sbconfig.PORT_BLOCK_BASE) % sbconfig.PORT_BLOCK_SIZE == 0
        assert port + (sbconfig.PORT_BLOCK_SIZE - 1) <= sbconfig.PORT_MAX, port

    # A base or count raised past the port space is a refusal, not a block
    # whose telnet and ephemeral ports cannot be bound.
    base = sbconfig.PORT_BLOCK_BASE
    count = sbconfig.PORT_BLOCK_COUNT
    try:
        sbconfig.PORT_BLOCK_BASE = sbconfig.PORT_MAX
        sbconfig.port_block("srv-lab", set())
    except ValueError as ex:
        assert "do not fit" in str(ex), ex
    else:
        raise AssertionError("a block range past the port space must be refused")
    finally:
        sbconfig.PORT_BLOCK_BASE = base
        sbconfig.PORT_BLOCK_COUNT = count
    print("PASS port_block_stays_inside_the_port_space")


def test_recorded_ports_skips_self_and_garbage(tmp: Path) -> None:
    instances = tmp / "instances"
    for name, body in (
        ("srv-self", "SERVER_PORT=27100\n"),
        ("srv-other", "SERVER_PORT=27105\n"),
        ("srv-bad", "SERVER_PORT=not-a-number\n"),
        # Unicode digits: `isdigit()` accepts a superscript, which int() then
        # refuses, so this used to raise ValueError out of the scan that exists
        # to survive another instance's file.
        ("srv-unicode", "SERVER_PORT=27\u00b2\n"),
        ("client-x", "SANDBOX_NAME=client-x\n"),
    ):
        (instances / name).mkdir(parents=True)
        (instances / name / "instance.env").write_text(body, encoding="utf-8")
    taken = sbconfig.recorded_ports(instances, exclude="srv-self")
    assert taken == {27105}, taken
    print("PASS recorded_ports_skips_self_and_garbage")


def test_seed_admins_is_utf8_under_a_c_locale(tmp: Path) -> None:
    """The names on stdin are UTF-8 whatever the host locale says.

    A cron job, a systemd unit and a CI runner all run under LC_ALL=C, where
    Python decodes stdin as ASCII: `José` arrived as lone surrogates, was
    written into serveradmin.xml as a name no player can match, and left a
    truncated admin file behind. Coercion and UTF-8 mode are switched off so
    the locale really is ASCII here rather than rescued by the interpreter.
    """
    import os
    import subprocess

    env = dict(os.environ, LC_ALL="C", PYTHONCOERCECLOCALE="0", PYTHONUTF8="0")
    proc = subprocess.run(
        [sys.executable, str(Path(sbconfig.__file__)), "seed-admins", str(tmp / "userdata")],
        input="José\n".encode(),
        env=env,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    seeded = (tmp / "userdata" / "Saves" / "serveradmin.xml").read_bytes()
    ids = {u.get("userid") for u in ET.fromstring(seeded.decode("utf-8")).iter("user")}
    assert "José" in ids, ids
    assert b"\xef\xbf\xbd" not in seeded, "the name was written with replacement characters"
    print("PASS seed_admins_is_utf8_under_a_c_locale")


def test_seed_refuses_names_that_are_not_utf8(tmp: Path) -> None:
    """Undecodable names are reported, never seeded as a truncated list.

    Seeding the names that happened to decode would admit a different set of
    players than the caller declared, quietly.
    """
    saved = sys.stdin
    try:
        sys.stdin = io.TextIOWrapper(io.BytesIO(b"good\n\xff\xfe\n"), encoding="ascii")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            rc = sbconfig.main(["seed-admins", str(tmp / "userdata")])
    finally:
        sys.stdin = saved
    assert rc == EXIT_FAILED, f"expected a refusal ({EXIT_FAILED}), got {rc}"
    assert "UTF-8" in err.getvalue(), err.getvalue()
    seeded = tmp / "userdata" / "Saves" / "serveradmin.xml"
    assert not seeded.exists(), "a refused seed wrote a file"
    print("PASS seed_refuses_names_that_are_not_utf8")


def test_get_reads_the_active_value(tmp: Path) -> None:
    """A value that only appears inside a comment is not what the game reads."""
    src = tmp / "in.xml"
    src.write_text(STOCK, encoding="utf-8")
    dst = tmp / "out.xml"
    assert sbconfig.main(["render", str(src), str(dst), "--set", "GameWorld=Nav"]) == 0
    text = dst.read_text(encoding="utf-8")
    assert sbconfig.active_value(text, "GameWorld") == "Nav"
    assert sbconfig.active_value(text, "UserDataFolder") is None
    assert sbconfig.main(["get", str(dst), "UserDataFolder"]) == 1
    assert sbconfig.main(["get", str(dst), "GameWorld"]) == 0
    print("PASS get_reads_the_active_value")


def test_get_unescapes_what_render_escaped(tmp: Path) -> None:
    hostile = 'x"/><property name="EACEnabled" value="true'
    src = tmp / "in.xml"
    src.write_text(STOCK, encoding="utf-8")
    dst = tmp / "out.xml"
    assert sbconfig.main(["render", str(src), str(dst), "--set", f"ServerName={hostile}"]) == 0
    got = sbconfig.active_value(dst.read_text(encoding="utf-8"), "ServerName")
    assert got == hostile, got
    print("PASS get_unescapes_what_render_escaped")


def test_seed_rewrites_malformed_admin_file(tmp: Path) -> None:
    """A file with no </users> cannot be upserted; the contract is admins exist."""
    admin = tmp / "userdata" / "Saves" / "serveradmin.xml"
    admin.parent.mkdir(parents=True)
    admin.write_text("<adminTools></adminTools>", encoding="utf-8")
    text = _seed(tmp)
    root = ET.fromstring(text)
    users = {u.get("userid") for u in root.iter("user")}
    assert set(sbconfig.DEFAULT_ADMIN_NAMES) <= users, users
    print("PASS seed_rewrites_malformed_admin_file")


def test_seed_rewrites_a_differently_spelled_admin(tmp: Path) -> None:
    """The file is folded to find an admin and written in the declared form.

    A file carrying `Istanbul` (or a decomposed `Café`, which is what a
    macOS or Windows editor writes) is one player, not two, and the game
    looks an admin up by exact userid: leaving the old spelling in place
    declares a name no client sends, and the declared admin lands at
    permission 1000.
    """
    nfd = unicodedata.normalize("NFD", "Café")
    admin = tmp / "userdata" / "Saves" / "serveradmin.xml"
    admin.parent.mkdir(parents=True)
    admin.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<adminTools>\n  <users>\n'
        '    <user platform="Local" userid="Istanbul" name="Istanbul"'
        ' permission_level="1000" />\n'
        f'    <user platform="Local" userid="{nfd}" name="{nfd}"'
        ' permission_level="1000" />\n'
        "  </users>\n</adminTools>\n",
        encoding="utf-8",
    )
    assert _seed_argv(tmp / "userdata", "istanbul") == 0
    assert _seed_argv(tmp / "userdata", "Café") == 0
    root = ET.fromstring(admin.read_text(encoding="utf-8"))
    local = [u for u in root.iter("user") if u.get("platform") == "Local"]
    by_id: dict[str, str | None] = {}
    for user in local:
        by_id.setdefault(user.get("userid", ""), user.get("permission_level"))
    assert by_id.get("istanbul") == "0", by_id
    assert by_id.get("Café") == "0", by_id
    assert "Istanbul" not in by_id, by_id
    assert not [u for u in local if u.get("userid", "").startswith("Cafe")], by_id
    # Reseeding the same declaration must not churn the file.
    before = admin.read_bytes()
    assert _seed_argv(tmp / "userdata", "istanbul") == 0
    assert _seed_argv(tmp / "userdata", "Café") == 0
    assert admin.read_bytes() == before, "reseed rewrote an already-correct file"
    print("PASS seed_rewrites_a_differently_spelled_admin")


def test_seed_leaves_a_same_named_non_local_admin_alone(tmp: Path) -> None:
    """A Steam entry is a different identity; raising it grants nothing."""
    admin = tmp / "userdata" / "Saves" / "serveradmin.xml"
    admin.parent.mkdir(parents=True)
    admin.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<adminTools>\n  <users>\n'
        '    <user platform="Steam" userid="admin" name="admin"'
        ' permission_level="1000" />\n'
        "  </users>\n</adminTools>\n",
        encoding="utf-8",
    )
    assert sbconfig.main(["seed-admins", str(tmp / "userdata")]) == 0
    root = ET.fromstring(admin.read_text(encoding="utf-8"))
    steam = [u for u in root.iter("user") if u.get("platform") == "Steam"]
    assert [u.get("permission_level") for u in steam] == ["1000"], steam
    print("PASS seed_leaves_a_same_named_non_local_admin_alone")


def test_seed_refuses_a_non_utf8_admin_file(tmp: Path) -> None:
    """A latin-1 admin name must not be rewritten into replacement characters.

    Decoding with errors="replace" and writing the result back replaced every
    undecodable byte with U+FFFD, so `José` became a name no player can match,
    on the next launch rather than on the edit that caused it.
    """
    admin = tmp / "userdata" / "Saves" / "serveradmin.xml"
    admin.parent.mkdir(parents=True)
    original = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<adminTools>\n  <users>\n'
        '    <user platform="Local" userid="José" name="José"'
        ' permission_level="1000" />\n'
        "  </users>\n</adminTools>\n"
    ).encode("latin-1")
    admin.write_bytes(original)
    assert _seed_argv(tmp / "userdata", "client-x") == 1
    assert admin.read_bytes() == original, "a non-UTF-8 admin file was rewritten"
    print("PASS seed_refuses_a_non_utf8_admin_file")


def test_seed_refuses_non_utf8_declared_names(tmp: Path) -> None:
    """A declaration that will not decode is named, not raised as a traceback.

    The names arrive on stdin, so a caller whose SERVER_ADMINS came from a
    latin-1 source fed bytes that cannot be decoded. Letting the decode escape
    ended the process with a traceback over sys.stdin, naming neither the
    declaration nor the admin file it was refusing to seed.
    """
    ud = tmp / "userdata"
    saved = sys.stdin
    sys.stdin = io.TextIOWrapper(io.BytesIO(b"client-Jos\xe9\n"), encoding="utf-8")
    try:
        with contextlib.redirect_stderr(io.StringIO()) as err:
            rc = sbconfig.main(["seed-admins", str(ud)])
    finally:
        sys.stdin.close()
        sys.stdin = saved
    assert rc == 1, f"an undecodable declaration must fail, got {rc}"
    assert "not valid UTF-8" in err.getvalue(), err.getvalue()
    assert not (ud / "Saves" / "serveradmin.xml").exists(), "a refused seed wrote a file"
    print("PASS seed_refuses_non_utf8_declared_names")


def test_recorded_ports_reports_an_unreadable_instances_dir(tmp: Path) -> None:
    """Another account's instances dir is reported, not raised over.

    recorded_ports runs inside `sb create-server` while scanning every other
    instance on the machine. A sandbox home this account cannot read used to
    escape the skip-and-report promise as an unhandled OSError, so an unrelated
    create died with a traceback naming a path the caller had never heard of.
    Skipping costs the probe at most one block, and a collision surfaces as the
    server failing to bind, which names the port that clashed.
    """
    instances = tmp / "instances"
    instances.mkdir()
    if os.geteuid() == 0:
        print("SKIP recorded_ports_reports_an_unreadable_instances_dir (root reads anything)")
        return
    with contextlib.redirect_stderr(io.StringIO()) as err:
        instances.chmod(0o000)
        try:
            assert sbconfig.recorded_ports(instances, exclude="mine") == set()
        finally:
            instances.chmod(0o755)
    assert str(instances) in err.getvalue(), err.getvalue()
    print("PASS recorded_ports_reports_an_unreadable_instances_dir")


def test_get_refuses_a_non_utf8_config(tmp: Path) -> None:
    """`get` is how a caller reads back what the game will read."""
    cfg = tmp / "latin1.xml"
    cfg.write_bytes(
        '<?xml version="1.0"?>\n<ServerSettings>\n'
        '\t<property name="ServerName"\tvalue="Jos\xe9"/>\n'
        "</ServerSettings>\n".encode("latin-1")
    )
    assert sbconfig.main(["get", str(cfg), "ServerName"]) == 1
    print("PASS get_refuses_a_non_utf8_config")


def test_port_block_hashes_an_undecodable_name(tmp: Path) -> None:
    """A directory name with a byte that is not UTF-8 is a legal directory name.

    Hashing it must not raise, and must stay the same value every time, or the
    name cannot be reproduced on the machine that recorded it.
    """
    name = "we\udcffird"
    first = sbconfig.port_block(name, set())
    assert first == sbconfig.port_block(name, set()), "hash is not stable"
    assert first >= sbconfig.PORT_BLOCK_BASE
    print("PASS port_block_hashes_an_undecodable_name")


def test_refuses_an_interpreter_below_the_declared_floor(tmp: Path) -> None:
    """A host python3 older than the floor is refused by name.

    `sb` shells out to whatever python3 the distribution ships, so the floor
    is only useful if the module itself enforces it instead of failing later
    inside a render.
    """
    saved = sbconfig.sys.version_info
    try:
        sbconfig.sys.version_info = (
            sbconfig.MIN_PYTHON[0],
            sbconfig.MIN_PYTHON[1] - 1,
            0,
        )
        with contextlib.redirect_stderr(io.StringIO()) as err:
            rc = sbconfig.main(["port-block", "lab"])
    finally:
        sbconfig.sys.version_info = saved
    assert rc == EXIT_USAGE, f"expected a refusal ({EXIT_USAGE}), got {rc}"
    assert "needs Python" in err.getvalue(), err.getvalue()


def test_seed_rewrites_unparsable_admin_file(tmp: Path) -> None:
    """A file with a </users> that no parser accepts is rewritten, not upserted.

    Upserting into it left the game reading the same broken config with the
    declared admins missing.
    """
    admin = tmp / "userdata" / "Saves" / "serveradmin.xml"
    admin.parent.mkdir(parents=True)
    admin.write_text("</users>", encoding="utf-8")
    text = _seed(tmp, "client-sg")
    users = {u.get("userid"): u.get("permission_level") for u in ET.fromstring(text).iter("user")}
    assert users.get("client-sg") == "0", users
    print("PASS seed_rewrites_unparsable_admin_file")


def test_seed_upserts_paired_user_without_level(tmp: Path) -> None:
    """A paired <user></user> with no permission_level keeps its closing tag."""
    _seed(tmp, "client-sg")
    admin = tmp / "userdata" / "Saves" / "serveradmin.xml"
    admin.write_text(
        admin.read_text(encoding="utf-8").replace(
            'userid="client-sg" name="client-sg" permission_level="0" />',
            'userid="client-sg" name="client-sg"></user>',
            1,
        ),
        encoding="utf-8",
    )
    text = _seed(tmp, "client-sg")
    users = {u.get("userid"): u.get("permission_level") for u in ET.fromstring(text).iter("user")}
    assert users.get("client-sg") == "0", users
    assert "</user>" in text, "the paired form lost its closing tag"
    print("PASS seed_upserts_paired_user_without_level")


def test_value_xml_cannot_carry_is_refused(tmp: Path) -> None:
    """A CR or a NUL in a value is refused, not written into the config.

    A C0 control is not a legal XML token, and a tab, LF or CR is normalized
    to a space on parse, so either would reach the game as something other than
    the declared value.
    """
    src = tmp / "in.xml"
    src.write_text(STOCK, encoding="utf-8")
    dst = tmp / "never.xml"
    for value in ("a\r\nb", "a\x00b", "a\tb"):
        rc = sbconfig.main(["render", str(src), str(dst), "--set", f"ServerName={value}"])
        assert rc == EXIT_USAGE, value
        assert not dst.exists(), f"{value!r} still wrote a config"
    print("PASS value_xml_cannot_carry_is_refused")


def test_insert_skips_a_commented_closer(tmp: Path) -> None:
    """A </ServerSettings> that only appears inside a comment is not an anchor.

    Inserting before it put the property inside the comment, where neither the
    game nor `get` reads it.
    """
    only_commented = (
        '<?xml version="1.0"?>\n<ServerSettings>\n'
        '\t<property name="ServerPort" value="26900"/>\n'
        "\t<!-- </ServerSettings> -->\n</ServerSettings>\n"
    )
    out = render(tmp, "GameWorld=Navezgane", src_text=only_commented)
    assert active_values(out, "GameWorld") == ["Navezgane"], out
    assert "<!-- </ServerSettings> -->" in out, out
    print("PASS insert_skips_a_commented_closer")


def test_seed_refuses_a_dtd(tmp: Path) -> None:
    """A serveradmin.xml carrying a DTD is rebuilt, never expanded.

    Expat expands internal general entities while it parses, so a nested
    entity definition in a hand-editable file costs exponential time on every
    bring-up. A rewritten file is a known-good one with no DTD at all.
    """
    admin = tmp / "userdata" / "Saves" / "serveradmin.xml"
    admin.parent.mkdir(parents=True)
    _seed(tmp, "client-sg")
    admin.write_text(
        '<?xml version="1.0"?>\n'
        "<!DOCTYPE adminTools [\n"
        '<!ENTITY a "aaaaaaaaaa">\n'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">\n'
        '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">\n'
        "]>\n"
        "<adminTools><users>\n"
        '  <user platform="Local" userid="client-sg" name="client-sg" />\n'
        "  <!-- &c; -->\n"
        "</users></adminTools>\n",
        encoding="utf-8",
    )
    text = _seed(tmp, "client-sg")
    assert "<!DOCTYPE" not in text and "<!ENTITY" not in text, text
    users = {u.get("userid"): u.get("permission_level") for u in ET.fromstring(text).iter("user")}
    assert users.get("client-sg") == "0", users
    assert admin.stat().st_mode & 0o077 == 0, oct(admin.stat().st_mode)
    print("PASS seed_refuses_a_dtd")


def test_seed_creates_the_admin_file_private(tmp: Path) -> None:
    """A freshly seeded admin file is 0600, not the umask's default.

    The file carries the level-0 admin list from its first byte, so it is
    published by a rename from a 0600 temp rather than created readable and
    restricted afterwards.
    """
    ud = tmp / "userdata"
    with _stdin("client-sg\n"):
        assert sbconfig.main(["seed-admins", str(ud)]) == 0
    admin = ud / "Saves" / "serveradmin.xml"
    assert admin.stat().st_mode & 0o077 == 0, oct(admin.stat().st_mode)
    print("PASS seed_creates_the_admin_file_private")


def test_interrupted_write_leaves_no_temp_behind(tmp: Path) -> None:
    """A write that dies on anything but an OSError takes its temp with it.

    The temp is a dot file in the instance's own tree, named for the pid that
    wrote it. One per interrupted bring-up is debris nothing in this tree
    sweeps, and this render runs on every server launch.
    """
    src = tmp / "in.xml"
    src.write_text(STOCK, encoding="utf-8")
    dst = tmp / "serverconfig.xml"
    real_write = Path.write_text
    interrupted = False

    def interrupt(self: Path, *args: object, **kwargs: object) -> int:
        nonlocal interrupted
        if self.name.startswith(".serverconfig.xml.tmp."):
            interrupted = True
            # The half-written file a real interrupt leaves behind, before the
            # exception rather than instead of it.
            real_write(self, "partial")
            raise KeyboardInterrupt
        return real_write(self, *args, **kwargs)  # type: ignore[arg-type]

    Path.write_text = interrupt  # type: ignore[method-assign]
    try:
        with contextlib.suppress(KeyboardInterrupt):
            sbconfig.main(["render", str(src), str(dst), "--set", "ServerPort=27105"])
    finally:
        Path.write_text = real_write  # type: ignore[method-assign]
    assert interrupted, "the render never reached the temp write, so this proved nothing"
    leftovers = [p.name for p in tmp.iterdir() if ".tmp." in p.name]
    assert leftovers == [], leftovers
    assert not dst.exists(), "an interrupted render published a config"
    print("PASS interrupted_write_leaves_no_temp_behind")


TESTS = (
    test_rewrites_active_property,
    test_leaves_commented_property_commented,
    test_inserts_missing_property_once,
    test_value_cannot_inject_properties,
    test_output_is_valid_xml_and_private,
    test_userdata_flag_resolves,
    test_rerun_is_byte_identical_and_never_appends,
    test_bad_set_fails_closed,
    test_missing_template_names_the_file,
    test_seed_takes_no_name_argument,
    test_seed_reads_names_from_stdin,
    test_seeds_only_declared_names,
    test_seed_upserts_demoted_admin,
    test_seed_is_idempotent,
    test_seed_is_idempotent_for_escaped_names,
    test_seed_is_host_independent,
    test_port_block_is_derived_from_the_name,
    test_port_block_probes_past_a_taken_block,
    test_port_block_exhaustion_fails_instead_of_overlapping,
    test_port_block_stays_inside_the_port_space,
    test_recorded_ports_skips_self_and_garbage,
    test_seed_admins_is_utf8_under_a_c_locale,
    test_seed_refuses_names_that_are_not_utf8,
    test_get_reads_the_active_value,
    test_get_unescapes_what_render_escaped,
    test_seed_rewrites_malformed_admin_file,
    test_seed_rewrites_a_differently_spelled_admin,
    test_seed_leaves_a_same_named_non_local_admin_alone,
    test_seed_refuses_a_non_utf8_admin_file,
    test_seed_refuses_non_utf8_declared_names,
    test_recorded_ports_reports_an_unreadable_instances_dir,
    test_get_refuses_a_non_utf8_config,
    test_port_block_hashes_an_undecodable_name,
    test_refuses_an_interpreter_below_the_declared_floor,
    test_seed_rewrites_unparsable_admin_file,
    test_seed_upserts_paired_user_without_level,
    test_value_xml_cannot_carry_is_refused,
    test_insert_skips_a_commented_closer,
    test_seed_refuses_a_dtd,
    test_seed_creates_the_admin_file_private,
    test_interrupted_write_leaves_no_temp_behind,
)


def main() -> int:
    failed = 0
    for test in TESTS:
        with tempfile.TemporaryDirectory() as td:
            try:
                test(Path(td))
            except AssertionError as ex:
                print(f"FAIL {test.__name__}: {ex}", file=sys.stderr)
                failed += 1
            except Exception as ex:
                # A test that raises rather than asserts is still a failing
                # test. Letting it escape would abandon every case after it,
                # so the report says which one broke and the suite still
                # reports the rest.
                print(f"ERROR {test.__name__}: {type(ex).__name__}: {ex}", file=sys.stderr)
                failed += 1
    if failed:
        print(f"test_sbconfig: FAILED ({failed})", file=sys.stderr)
        return 1
    print("test_sbconfig: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
