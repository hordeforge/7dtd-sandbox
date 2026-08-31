#!/usr/bin/env bash
# Run a sandbox command inside 7dtd-safehouse:latest with the host X11 socket
# and GPU forwarded, so the Windows client window appears on the desktop.
#
# Game data, instances and Proton stay on the host (bind mounts). The
# container has no published ports (--network none).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${SANDBOX_IMAGE:-7dtd-safehouse:latest}"
STEAM_ROOT="${STEAM_ROOT:-$HOME/.local/share/Steam}"
PROTON_REL="steamapps/common/Proton - Experimental/proton"

die() { echo "docker-gui: $*" >&2; exit 1; }

[[ -x "$STEAM_ROOT/$PROTON_REL" ]] || die "Proton not found at $STEAM_ROOT/$PROTON_REL"
command -v docker >/dev/null || die "docker not on PATH"
docker image inspect "$IMAGE" >/dev/null 2>&1 || die "image $IMAGE missing; run: docker build -t $IMAGE -f Dockerfile.safehouse ."

# Allow local unix-socket X11 clients (container root talking to the host
# display). Revoke later with: xhost -local:
if command -v xhost >/dev/null 2>&1; then
  xhost +local: >/dev/null 2>&1 || true
fi

devices=( --device /dev/dri )
[[ -e /dev/ntsync ]] && devices+=( --device /dev/ntsync )
# Host render node is world-writable; video is needed for /dev/dri/card*.
# The image has no `render` group, so do not --group-add it.
# Wine refuses a prefix not owned by the current uid; run as the host user
# so instances/*/compatdata/pfx (created by native sb) is usable.
user_args=( --user "$(id -u):$(id -g)" )
groups=( --group-add video )
if getent group render >/dev/null 2>&1; then
  groups+=( --group-add "$(getent group render | cut -d: -f3)" )
fi

# Proton writes Fossilize/DXVK caches under steamapps/shadercache; Steam is
# mounted read-only, so redirect that dir onto a host scratch tree.
shader_host="$ROOT/.scratch/shadercache"
mkdir -p "$shader_host" "$ROOT/.scratch/sb-home"
# Proton wants to flock dist.lock next to itself; Steam is mounted ro, so
# overlay just that file with a writable copy.
proton_lock_host="$ROOT/.scratch/proton-dist.lock"
: > "$proton_lock_host"

# Native sb launch works with no Steam *process* because the host still has
# ~/.steam/sdk64 -> linux64/steamclient.so. Recreate that layout inside the
# container home, pointing at the bind-mounted Steam root.
steam_dot="$ROOT/.scratch/sb-home/.steam"
mkdir -p "$steam_dot"
ln -sfn /opt/steam "$steam_dot/root"
ln -sfn /opt/steam "$steam_dot/steam"
ln -sfn /opt/steam/linux64 "$steam_dot/sdk64"
ln -sfn /opt/steam/linux32 "$steam_dot/sdk32"
ln -sfn /opt/steam/ubuntu12_64 "$steam_dot/bin64"
ln -sfn /opt/steam/ubuntu12_32 "$steam_dot/bin32"

tty_args=()
if [[ -t 0 && -t 1 ]]; then
  tty_args=(-it)
else
  tty_args=(-i)
fi

# Extra args after `--` go to `sb`. Default: help.
sb_args=("$@")
[[ ${#sb_args[@]} -gt 0 ]] || sb_args=(help)

xauth_args=()
if [[ -n "${XAUTHORITY:-}" && -f "${XAUTHORITY}" ]]; then
  xauth_args+=( -e "XAUTHORITY=/tmp/.docker.xauth" -v "${XAUTHORITY}:/tmp/.docker.xauth:ro" )
fi

# Proton's pressure-vessel (bwrap) fights Docker's own namespaces. Skip it
# and let Proton's bundled wine talk to the host GPU/X11 directly.
# Default docker network (no -p) keeps ports unpublished; --network none
# hung Proton's steam.exe stub before 7DaysToDie.exe started.
exec docker run --rm \
  "${tty_args[@]}" \
  --name 7dtd-safehouse-gui \
  --ipc host \
  --security-opt seccomp=unconfined \
  "${user_args[@]}" \
  "${devices[@]}" \
  "${groups[@]}" \
  -v /etc/passwd:/etc/passwd:ro \
  -v /etc/group:/etc/group:ro \
  -v /etc/machine-id:/etc/machine-id:ro \
  -e DISPLAY="${DISPLAY:?DISPLAY unset}" \
  -e STEAM_ROOT=/opt/steam \
  -e STEAM_COMPAT_CLIENT_INSTALL_PATH=/opt/steam \
  -e PROTON="/opt/steam/${PROTON_REL}" \
  -e SANDBOX_HOME=/sandbox \
  -e HOME=/tmp/sb-home \
  -v "$ROOT/.scratch/sb-home:/tmp/sb-home" \
  -e PRESSURE_VESSEL_SKIP_RUNTIME=1 \
  -e DXVK_HUD=0 \
  -e PROTON_LOG=1 \
  -e PROTON_LOG_DIR=/tmp/sb-home \
  -e WINEDLLOVERRIDES=steamclient=n,steamclient64=n \
  "${xauth_args[@]}" \
  -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
  -v "$STEAM_ROOT:/opt/steam:ro" \
  -v "$shader_host:/opt/steam/steamapps/shadercache" \
  -v "$proton_lock_host:/opt/steam/steamapps/common/Proton - Experimental/dist.lock" \
  -v "$ROOT:/sandbox" \
  -w /sandbox \
  "$IMAGE" \
  "${sb_args[@]}"
