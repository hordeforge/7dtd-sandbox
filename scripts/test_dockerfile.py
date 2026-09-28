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
- neither image contains game files,
- `docker-gui.sh` states the host it forwards from (Linux, an X11 socket, a
  GPU render node) instead of letting a bind mount fail deep inside docker,
- both images carry OCI labels, and the version label is filled from `sb version`
  rather than a literal, so a pulled image says which `sb` it carries.

Part of ``make test``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile.safehouse"
DOCKER_GUI = ROOT / "scripts" / "docker-gui.sh"
MAKEFILE = ROOT / "Makefile"

FROM_RE = re.compile(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?\s*$", re.MULTILINE | re.IGNORECASE)


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
    return "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))


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
    # The whole directory, not the script alone. steamcmd.sh resolves
    # linux32/steamcmd relative to itself, so a lone script symlink sent every
    # fetch to /opt/steamcmd/linux32/steamcmd and died with "Couldn't find
    # steamcmd" before contacting Steam at all.
    # Symlink the directory, never copy it and never link the script alone.
    # steamcmd.sh resolves linux32/steamcmd beside itself, and steamcmd resolves
    # its Steam configuration from the install directory's parent; a copy to
    # /opt orphans it from the primed tree and every app_update then fails with
    # "Missing configuration" after logging in fine.
    assert "ln -sfn /root/.local/share/Steam/steamcmd /opt/steamcmd" in body, (
        "symlink the steamcmd directory in place; do not copy or relocate it"
    )
    # steamcmd's Steam tree lives under $HOME and the upstream image primed
    # /root/.local/share/Steam at build time. Overriding HOME to an empty
    # directory hands it a fresh unprimed tree, and every app_update then fails
    # with "Missing configuration" after a clean login.
    assert not re.search(r"(?<![A-Z_])HOME=", body), (
        "the fetch stage must not override HOME: steamcmd needs the Steam tree "
        "the base image primed under /root (SANDBOX_HOME is a different name)"
    )
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
    body = directives(DOCKERFILE.read_text(encoding="utf-8"))
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.upper().startswith(("COPY", "ADD")):
            continue
        for forbidden in ("base/", "instances/"):
            assert forbidden not in stripped, f"{stripped!r} bakes game data into the image"
    assert "app_update" not in body, "no image builds by downloading a depot"
    print("PASS no_game_files_are_baked_in")


def test_helper_scripts_are_executable_in_the_image() -> None:
    for name in ("fetch", "runtime"):
        body = directives(stage_body(name))
        assert "chmod 0755 /usr/local/bin/sb /usr/local/bin/sbconfig.py" in body, (
            f"stage {name} must make both helpers executable"
        )
    print("PASS helper_scripts_are_executable_in_the_image")


def test_docker_gui_names_its_host_requirements() -> None:
    """The GUI path binds host paths a non-Linux or GPU-less host lacks.

    Without a preflight, `docker run` reports a missing device or silently
    turns a missing source into a directory, so each host assumption is
    checked (and named in the message) before the container starts.
    """
    text = DOCKER_GUI.read_text(encoding="utf-8")
    for required in ("uname -s", "/dev/dri", "/tmp/.X11-unix", "DISPLAY"):
        assert required in text, f"docker-gui.sh does not check {required}"
    print("PASS docker_gui_names_its_host_requirements")


def test_images_carry_oci_labels() -> None:
    """`docker image inspect` has to name what an image carries.

    A tag says `7dtd-safehouse:latest` and nothing about the `sb` inside it, so
    source, license and version are the only record of what a pulled image is.
    """
    for name in ("fetch", "runtime"):
        body = directives(stage_body(name))
        for key in (
            "org.opencontainers.image.title",
            "org.opencontainers.image.description",
            "org.opencontainers.image.source",
            "org.opencontainers.image.licenses",
        ):
            assert f"{key}=" in body, f"stage {name} does not label {key}"
        assert re.search(r"org\.opencontainers\.image\.version=", body), (
            f"stage {name} does not label org.opencontainers.image.version"
        )
    print("PASS images_carry_oci_labels")


def test_image_version_is_derived_from_sb_version() -> None:
    """The version label must not be a second place a version is written.

    A literal in the Dockerfile and SB_VERSION in `sb` drift on the first bump
    that misses one, and the drift is invisible: the image still builds.
    """
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"^ARG SB_VERSION=0\.0\.0-unset$", text, re.M), (
        "the Dockerfile needs a global ARG SB_VERSION, defaulted to a value "
        "that cannot pass for a release"
    )
    for name in ("fetch", "runtime"):
        body = directives(stage_body(name))
        assert re.search(r"^ARG SB_VERSION$", body, re.M), (
            f"stage {name} must redeclare ARG SB_VERSION to use it in a LABEL"
        )
        assert 'org.opencontainers.image.version="${SB_VERSION}"' in body, (
            f"stage {name} must take its version from the build arg"
        )
    makefile = MAKEFILE.read_text(encoding="utf-8")
    assert 'SB_VERSION_ARG = --build-arg SB_VERSION="$$($(SB) version' in makefile, (
        "the Makefile must pass `sb version` as the build arg, so the version "
        "home stays SB_VERSION in scripts/sb"
    )
    for target, stage in (("docker", "runtime"), ("docker-fetch", "fetch")):
        pattern = rf"^{target}:\n\tdocker build --target {stage} \$\(SB_VERSION_ARG\) "
        assert re.search(pattern, makefile, re.M), (
            f"the {target} target must pass $(SB_VERSION_ARG)"
        )
    print("PASS image_version_is_derived_from_sb_version")


def test_runtime_is_not_root_and_fetch_stays_root() -> None:
    """Least privilege, with the one exception that earns it.

    The runtime image runs `sb`, which needs nothing root, so its default user
    is not root. The fetch image keeps root for two named reasons: steamcmd
    writes into the primed tree under /root, and `make fetch-base-docker`
    chowns the bind-mounted base/ back to the caller through `--entrypoint
    chown`, which a non-root user cannot do.
    """
    runtime = directives(stage_body("runtime"))
    assert re.search(r"^USER 1000:1000$", runtime, re.M), (
        "the runtime image must not default to root: sb needs no privilege, and "
        "scripts/docker-gui.sh already pins --user to the caller"
    )
    assert "chown 1000:1000 /sandbox" in runtime, (
        "the image's own SANDBOX_HOME must belong to the user it runs as, so "
        "`sb create` works in a plain `docker run -v` with no --user"
    )
    fetch = directives(stage_body("fetch"))
    assert not re.search(r"^USER ", fetch, re.M), (
        "the fetch image must stay root: steamcmd writes into the tree the base "
        "image primed under /root, and the chown of base/ back to the caller "
        "needs it"
    )
    gui = (ROOT / "scripts" / "docker-gui.sh").read_text(encoding="utf-8")
    assert '--user "$(id -u):$(id -g)"' in gui, (
        "docker-gui.sh must keep pinning the caller's uid, so the image's "
        "default user never decides who owns the instance files"
    )
    print("PASS runtime_is_not_root_and_fetch_stays_root")


TESTS = (
    test_two_targets_exist,
    test_every_base_is_pinned_by_digest,
    test_runtime_ships_no_steamcmd,
    test_fetch_has_steamcmd_at_the_path_sb_expects,
    test_both_images_ship_the_config_helper,
    test_no_game_files_are_baked_in,
    test_helper_scripts_are_executable_in_the_image,
    test_docker_gui_names_its_host_requirements,
    test_images_carry_oci_labels,
    test_image_version_is_derived_from_sb_version,
    test_runtime_is_not_root_and_fetch_stays_root,
)


def main() -> int:
    failed = 0
    for test in TESTS:
        try:
            test()
        except AssertionError as ex:
            print(f"FAIL {test.__name__}: {ex}", file=sys.stderr)
            failed += 1
        except Exception as ex:
            # A test that raises rather than asserts is still a failing test.
            # Letting it escape abandons every case after it, and the reader
            # cannot tell which one never ran.
            print(f"ERROR {test.__name__}: {type(ex).__name__}: {ex}", file=sys.stderr)
            failed += 1
    if failed:
        print(f"test_dockerfile: FAILED ({failed})", file=sys.stderr)
        return 1
    print("test_dockerfile: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
