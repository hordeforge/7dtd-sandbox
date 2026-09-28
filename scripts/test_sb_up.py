#!/usr/bin/env python3
"""Gate for ``sb up``: the blocking, exit-coded bring-up harnesses call.

Runs the real CLI against a fake dedicated server (a listener that stays up),
so the contract is exercised without a 17 GB game tree:

- it returns once the game port accepts connections, and leaves the server
  running behind it,
- the server is orphaned to init, not left as a child of ``sb``. A backgrounded
  ``setsid ... &`` kept it parented, and ``sb up`` then sat in ``do_wait``
  forever with its port check already passed, hanging every caller,
- a server that never binds fails inside the timeout and names its log,
- an instance already running is refused, so two harnesses cannot double-bind
  one instance,
- ``sb list`` reports the running instance as running, its idle neighbour as
  idle, and ``sb stop`` stops exactly that instance.

Part of ``make test``.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SB = ROOT / "scripts" / "sb"

# Long enough that a slow runner does not fail the "stays up" assertions, short
# enough that a leaked process is gone well before the suite ends.
FAKE_SERVER_LIFETIME_SEC = 120
# The fake binds instantly, so `sb up` should return in well under this. A
# hung `sb up` is the bug under test, so the wait must be bounded here too.
UP_CALL_TIMEOUT_SEC = 60
# A server that never binds must fail inside its own --timeout, with room to
# spare for a slow runner. A bring-up that waits on the port probe instead of
# the timeout is the bug this gate exists for.
NEVER_BINDS_FAILS_BY_SEC = 30

LISTENER = '''#!/usr/bin/env python3
"""Stand-in for 7DaysToDieServer.x86_64: bind the port, then idle."""
import os
import socket
import sys
import time

port = int(os.environ["FAKE_SERVER_PORT"])
if os.environ.get("FAKE_SERVER_NEVER_BINDS") == "1":
    time.sleep({lifetime})
    sys.exit(0)
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", port))
sock.listen(8)
time.sleep({lifetime})
'''


def make_instance(root: Path, name: str, port: int) -> Path:
    """A server instance whose 'game' is the fake listener."""
    inst = root / "instances" / name
    (inst / "game").mkdir(parents=True)
    (inst / "userdata" / "Saves").mkdir(parents=True)
    (inst / "logs").mkdir(parents=True)

    binary = inst / "game" / "7DaysToDieServer.x86_64"
    binary.write_text(LISTENER.format(lifetime=FAKE_SERVER_LIFETIME_SEC), encoding="utf-8")
    binary.chmod(0o755)
    (inst / "game" / "serverconfig.xml").write_text(
        '<?xml version="1.0"?>\n<ServerSettings>\n</ServerSettings>\n', encoding="utf-8"
    )
    (inst / "instance.env").write_text(
        f"SANDBOX_NAME={name}\n"
        f"INSTANCE_DIR={inst}\n"
        f"SERVER_GAME={inst}/game\n"
        f"SERVER_USERDATA={inst}/userdata\n"
        f"SERVER_PORT={port}\n"
        f"SERVER_TELNET_PORT={port + 1}\n"
        f"SERVER_CONFIG={inst}/serverconfig.xml\n"
        f"SERVER_PROPS={inst}/instance.props\n"
        f"SERVER_LOG={inst}/logs/server.log\n"
        f"SERVER_ADMINS=client-{name}\n"
        "SERVER_KIND=server\n",
        encoding="utf-8",
    )
    (inst / "instance.props").write_text("", encoding="utf-8")
    return inst


def run_up(root: Path, name: str, *, timeout: str, never_binds: bool = False, port: int = 0):
    env = dict(os.environ)
    env["SANDBOX_HOME"] = str(root)
    env["SANDBOX_INSTANCES"] = str(root / "instances")
    env["FAKE_SERVER_PORT"] = str(port)
    if never_binds:
        env["FAKE_SERVER_NEVER_BINDS"] = "1"
    return subprocess.run(
        ["bash", str(SB), "up", name, "--timeout", timeout],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=UP_CALL_TIMEOUT_SEC,
    )


def server_pids(inst: Path) -> list[int]:
    """Pids carrying this instance's SB_INSTANCE marker, as `sb stop` matches."""
    marker = f"SB_INSTANCE={inst}"
    out: list[int] = []
    for pid_dir in Path("/proc").glob("[0-9]*"):
        try:
            environ = (pid_dir / "environ").read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        if marker in environ.split("\0"):
            out.append(int(pid_dir.name))
    return out


def stop(pids: list[int]) -> None:
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


def free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_up_returns_and_orphans_the_server(tmp: Path) -> None:
    port = free_port()
    inst = make_instance(tmp, "srv-fake", port)
    pids: list[int] = []
    try:
        started = time.monotonic()
        proc = run_up(tmp, "srv-fake", timeout="30", port=port)
        elapsed = time.monotonic() - started
        assert proc.returncode == 0, f"sb up failed: {proc.stderr or proc.stdout}"
        assert elapsed < UP_CALL_TIMEOUT_SEC, f"sb up took {elapsed:.0f}s"
        assert f"port {port}" in proc.stdout, proc.stdout
        # It printed the contract, so a caller can read the instance back.
        assert "SERVER_PORT=" in proc.stdout, proc.stdout

        pids = server_pids(inst)
        assert pids, "sb up returned but left no server running"
        # The whole point: no sb is waiting on it. The orphan lands on init or
        # on whatever subreaper claims it (systemd --user on a normal desktop
        # session), so the parent's identity is not the assertion; the
        # assertion is that the parent is not an sb still sitting in do_wait.
        for pid in pids:
            ppid = int((Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8").split()[3])
            parent_cmd = ""
            with contextlib.suppress(OSError):
                parent_cmd = (
                    (Path("/proc") / str(ppid) / "cmdline").read_bytes().decode("utf-8", "replace")
                )
            assert "scripts/sb" not in parent_cmd, (
                f"server {pid} is still a child of sb (pid {ppid}); "
                "sb up returned only because we killed it, not because it detached"
            )
    finally:
        stop(pids)
    print("PASS up_returns_and_orphans_the_server")


def test_up_refuses_an_instance_already_running(tmp: Path) -> None:
    port = free_port()
    inst = make_instance(tmp, "srv-busy", port)
    pids: list[int] = []
    try:
        assert run_up(tmp, "srv-busy", timeout="30", port=port).returncode == 0
        pids = server_pids(inst)
        assert pids, "fixture server did not start"
        proc = run_up(tmp, "srv-busy", timeout="30", port=port)
        assert proc.returncode != 0, "a second up on a running instance must refuse"
        assert "already running" in proc.stderr, proc.stderr
    finally:
        stop(pids)
    print("PASS up_refuses_an_instance_already_running")


def test_up_fails_inside_its_timeout_and_names_the_log(tmp: Path) -> None:
    port = free_port()
    inst = make_instance(tmp, "srv-deaf", port)
    pids: list[int] = []
    try:
        started = time.monotonic()
        proc = run_up(tmp, "srv-deaf", timeout="3", never_binds=True, port=port)
        elapsed = time.monotonic() - started
        assert proc.returncode != 0, "a server that never binds must fail the bring-up"
        assert elapsed < NEVER_BINDS_FAILS_BY_SEC, (
            f"the --timeout was not honoured ({elapsed:.0f}s)"
        )
        assert "did not open port" in proc.stderr, proc.stderr
        assert "logs/server.log" in proc.stderr, "the failure must name the log to read"
        # A server that never bound is still running and still owns its port
        # block. Leaving it there meant every retry piled up another one, so the
        # failure path has to stop what it started. A moment of grace for the
        # kernel to reap the killed process.
        deadline = time.monotonic() + 5
        pids = server_pids(inst)
        while pids and time.monotonic() < deadline:
            time.sleep(0.2)
            pids = server_pids(inst)
        assert not pids, f"sb up failed but left the server running: {pids}"
    finally:
        stop(pids)
    print("PASS up_fails_inside_its_timeout_and_names_the_log")


def test_the_wait_deadline_is_monotonic(tmp: Path) -> None:
    """The bring-up deadline is a duration, so it is not read off the wall clock.

    A wall-clock deadline ends the wait early on a forward NTP step and extends
    it by the size of a backward step, and neither outcome is the --timeout the
    harness asked for. The kernel's uptime counter cannot be stepped.
    """
    source = SB.read_text(encoding="utf-8")
    body = source.split("wait_for_port() {", 1)[1].split("\n}", 1)[0]
    assert "date" not in body, f"the port wait reads a clock through date: {body!r}"
    assert "monotonic_now" in body, "the port wait must take its deadline from monotonic_now"
    assert "date" not in source.split("monotonic_now() {", 1)[1].split("\n}", 1)[0], (
        "monotonic_now must not fall back to the wall clock"
    )
    print("PASS the_wait_deadline_is_monotonic")


def run_sb(root: Path, *args: str):
    env = dict(os.environ)
    env["SANDBOX_HOME"] = str(root)
    env["SANDBOX_INSTANCES"] = str(root / "instances")
    return subprocess.run(
        ["bash", str(SB), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=UP_CALL_TIMEOUT_SEC,
    )


def test_list_and_stop_see_the_running_instance(tmp: Path) -> None:
    """`sb list` and `sb stop` read the same one-pass /proc scan.

    The per-row scan they replaced reported a running server as stopped, and a
    stopped one as running: the marker match has to survive the whole path from
    /proc to the printed row, not just the single-instance commands.
    """
    port = free_port()
    running = make_instance(tmp, "srv-listed", port)
    idle = make_instance(tmp, "srv-idle", free_port())
    pids: list[int] = []
    try:
        proc = run_sb(tmp, "list")
        assert proc.returncode == 0, proc.stderr
        assert "srv-listed" in proc.stdout and "srv-idle" in proc.stdout, proc.stdout
        assert row_for(proc.stdout, "srv-listed").split()[2] == "no", proc.stdout

        assert run_up(tmp, "srv-listed", timeout="30", port=port).returncode == 0
        pids = server_pids(running)
        assert pids, "fixture server did not start"
        proc = run_sb(tmp, "list")
        assert row_for(proc.stdout, "srv-listed").split()[2] == "yes", proc.stdout
        # The neighbour is not running, and must not be reported as such.
        assert row_for(proc.stdout, "srv-idle").split()[2] == "no", proc.stdout

        stopped = run_sb(tmp, "stop", "srv-listed")
        assert stopped.returncode == 0, stopped.stderr
        for _ in range(50):
            if not server_pids(running):
                break
            time.sleep(0.2)
        assert not server_pids(running), "sb stop left the instance's server running"
    finally:
        stop(pids)
    assert idle.is_dir()
    print("PASS list_and_stop_see_the_running_instance")


def row_for(stdout: str, name: str) -> str:
    for line in stdout.splitlines():
        if line.startswith(f"{name} "):
            return line
    return ""


TESTS = (
    test_up_returns_and_orphans_the_server,
    test_up_refuses_an_instance_already_running,
    test_up_fails_inside_its_timeout_and_names_the_log,
    test_list_and_stop_see_the_running_instance,
    test_the_wait_deadline_is_monotonic,
)


def main() -> int:
    failed = 0
    for test in TESTS:
        with tempfile.TemporaryDirectory(prefix="sb-up-") as td:
            try:
                test(Path(td))
            except (AssertionError, subprocess.TimeoutExpired) as ex:
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
        print(f"test_sb_up: FAILED ({failed})", file=sys.stderr)
        return 1
    print("test_sb_up: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
