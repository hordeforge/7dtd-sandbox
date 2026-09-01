#!/usr/bin/env python3
"""Gate for scripts/sbconfig.py, the workspace's serverconfig/admin renderer.

Drives the real CLI (``main(argv)``) and asserts the files it writes: an
injection through a property value, the stock template's commented shapes, the
insert-if-missing path, and the admin upsert. Part of ``make test``.
"""

from __future__ import annotations

import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sbconfig  # noqa: E402

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

    pattern = re.compile(r'<property\s+name="%s"\s+value="([^"]*)"' % re.escape(key))
    return [
        m.group(1) for m in pattern.finditer(text) if not sbconfig._in_comment(text, m.start())
    ]


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
    assert out.count('name="UserDataFolder"') == 2, out
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
    assert sbconfig.main(["render", str(src), str(dst), "--set", "NoEquals"]) == 2
    assert not dst.exists(), "a malformed --set still wrote a config"
    print("PASS bad_set_fails_closed")


def test_missing_template_names_the_file(tmp: Path) -> None:
    missing = tmp / "nope.xml"
    assert sbconfig.main(["render", str(missing), str(tmp / "o.xml")]) == 1
    print("PASS missing_template_names_the_file")


def _seed(tmp: Path, *names: str) -> str:
    ud = tmp / "userdata"
    argv = ["seed-admins", str(ud)]
    for name in names:
        argv += ["--name", name]
    assert sbconfig.main(argv) == 0
    return (ud / "Saves" / "serveradmin.xml").read_text(encoding="utf-8")


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


def test_recorded_ports_skips_self_and_garbage(tmp: Path) -> None:
    instances = tmp / "instances"
    for name, body in (
        ("srv-self", "SERVER_PORT=27100\n"),
        ("srv-other", "SERVER_PORT=27105\n"),
        ("srv-bad", "SERVER_PORT=not-a-number\n"),
        ("client-x", "SANDBOX_NAME=client-x\n"),
    ):
        (instances / name).mkdir(parents=True)
        (instances / name / "instance.env").write_text(body, encoding="utf-8")
    taken = sbconfig.recorded_ports(instances, exclude="srv-self")
    assert taken == {27105}, taken
    print("PASS recorded_ports_skips_self_and_garbage")


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
    test_seeds_only_declared_names,
    test_seed_upserts_demoted_admin,
    test_seed_is_idempotent,
    test_seed_is_host_independent,
    test_port_block_is_derived_from_the_name,
    test_port_block_probes_past_a_taken_block,
    test_port_block_exhaustion_fails_instead_of_overlapping,
    test_recorded_ports_skips_self_and_garbage,
    test_get_reads_the_active_value,
    test_get_unescapes_what_render_escaped,
    test_seed_rewrites_malformed_admin_file,
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
    if failed:
        print(f"test_sbconfig: FAILED ({failed})", file=sys.stderr)
        return 1
    print("test_sbconfig: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
