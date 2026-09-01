#!/usr/bin/env python3
"""Gate for Dockerfile.safehouse: the two targets and what separates them.

Static parse, no docker, so it runs on any runner. It pins the properties that
were wrong before and would be easy to undo:

- the runtime image ships no steamcmd. "No Steam at runtime" is the whole
  product claim, and an image carrying a Steam provisioning toolchain it never
  invokes contradicts it while carrying the supply chain anyway,
- both images ship `sbconfig.py`. `sb` shells out to it for every serverconfig
  render, admin seed and port derivation, so an image with only `sb` has a CLI
  whose create/up/render-config/wipe verbs all fail,
- every base is pinned by digest, for the same reason the workflows pin actions
  by commit SHA: a moved tag is unreviewed code,
- neither image contains game files.

Part of ``make test``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile.safehouse"

FROM_RE = re.compile(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?\s*$", re.M | re.I)


def stages() -> dict[str, str]:
    """Stage name -> base reference, in file order."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    found = {}
    for base, name in FROM_RE.findall(text):
        assert name, f"every FROM must be named with AS: {base}"
        found[name] = base
    return found


def directives(body: str) -> str:
    """Stage body with comments stripped.

    Assertions are about what the image does, not what the file says about it:
    the runtime stage documents *why* it has no SANDBOX_STEAMCMD, and prose
    explaining an absence must not read as the thing being present.
    """
    return "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    )


def stage_body(name: str) -> str:
    """The Dockerfile lines belonging to one stage."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    starts = [(m.start(), m.group(2)) for m in FROM_RE.finditer(text)]
    for i, (pos, stage) in enumerate(starts):
        if stage != name:
            continue
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        return text[pos:end]
    raise AssertionError(f"no stage named {name}")


def test_two_targets_exist() -> None:
    found = stages()
    assert set(found) == {"fetch", "runtime"}, found
    print("PASS two_targets_exist")


def test_every_base_is_pinned_by_digest() -> None:
    for name, base in stages().items():
        assert "@sha256:" in base, (
            f"stage {name} uses {base}, a mutable tag. Pin it by digest: a moved "
            "tag is unreviewed code, the same reason the workflows pin actions."
        )
    print("PASS every_base_is_pinned_by_digest")


def test_runtime_ships_no_steamcmd() -> None:
    body = directives(stage_body("runtime"))
    assert "steamcmd" not in body.lower(), (
        "the runtime image must neither inherit nor install steamcmd, and must "
        "not advertise a steamcmd path: `sb` refuses a fetch there by name"
    )
    print("PASS runtime_ships_no_steamcmd")


def test_fetch_has_steamcmd_at_the_path_sb_expects() -> None:
    body = directives(stage_body("fetch"))
    assert "steamcmd/steamcmd@sha256:" in body, "fetch is the stage that carries steamcmd"
    assert "SANDBOX_STEAMCMD=/opt/steamcmd" in body, (
        "sb looks for $SANDBOX_STEAMCMD/steamcmd.sh; expose the stable path"
    )
    assert "/opt/steamcmd/steamcmd.sh" in body, "the stable path must be linked"
    print("PASS fetch_has_steamcmd_at_the_path_sb_expects")


def test_both_images_ship_the_config_helper() -> None:
    """`sb` without `sbconfig.py` is a CLI whose main verbs all fail."""
    for name in ("fetch", "runtime"):
        body = directives(stage_body(name))
        assert "scripts/sbconfig.py" in body, (
            f"stage {name} copies sb but not sbconfig.py; every serverconfig "
            "render, admin seed and port derivation shells out to it"
        )
        assert "scripts/sb " in body or "scripts/sb\n" in body, f"stage {name} must copy sb"
    print("PASS both_images_ship_the_config_helper")


def test_no_game_files_are_baked_in() -> None:
    """Game trees stay on the host: a 20 GB base does not belong in an image,
    and the depots are not ours to redistribute."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.upper().startswith(("COPY", "ADD")):
            continue
        for forbidden in ("base/", "instances/", "app_update"):
            assert forbidden not in stripped, f"{stripped!r} bakes game data into the image"
    assert "app_update" not in text, "no image builds by downloading a depot"
    print("PASS no_game_files_are_baked_in")


def test_helper_scripts_are_executable_in_the_image() -> None:
    for name in ("fetch", "runtime"):
        body = directives(stage_body(name))
        assert "chmod 0755 /usr/local/bin/sb /usr/local/bin/sbconfig.py" in body, (
            f"stage {name} must make both helpers executable"
        )
    print("PASS helper_scripts_are_executable_in_the_image")


TESTS = (
    test_two_targets_exist,
    test_every_base_is_pinned_by_digest,
    test_runtime_ships_no_steamcmd,
    test_fetch_has_steamcmd_at_the_path_sb_expects,
    test_both_images_ship_the_config_helper,
    test_no_game_files_are_baked_in,
    test_helper_scripts_are_executable_in_the_image,
)


def main() -> int:
    failed = 0
    for test in TESTS:
        try:
            test()
        except AssertionError as ex:
            print(f"FAIL {test.__name__}: {ex}", file=sys.stderr)
            failed += 1
    if failed:
        print(f"test_dockerfile: FAILED ({failed})", file=sys.stderr)
        return 1
    print("test_dockerfile: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
