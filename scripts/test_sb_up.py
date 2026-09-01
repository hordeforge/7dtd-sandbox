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
  one instance.

Part of ``make test``.
"""

from __future__ import annotations

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
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


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
            ppid = int(
                (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8").split()[3]
            )
            parent_cmd = ""
            try:
                parent_cmd = (
                    (Path("/proc") / str(ppid) / "cmdline")
                    .read_bytes()
                    .decode("utf-8", "replace")
                )
            except OSError:
                pass
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
        assert elapsed < 30, f"the --timeout was not honoured ({elapsed:.0f}s)"
        assert "did not open port" in proc.stderr, proc.stderr
        assert "logs/server.log" in proc.stderr, "the failure must name the log to read"
        pids = server_pids(inst)
    finally:
        stop(pids)
    print("PASS up_fails_inside_its_timeout_and_names_the_log")


TESTS = (
    test_up_returns_and_orphans_the_server,
    test_up_refuses_an_instance_already_running,
    test_up_fails_inside_its_timeout_and_names_the_log,
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
    if failed:
        print(f"test_sb_up: FAILED ({failed})", file=sys.stderr)
        return 1
    print("test_sb_up: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
