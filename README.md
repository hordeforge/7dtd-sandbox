# 🏠 Safehouse (`7dtd-sandbox/`)

Standardized, Steam-free 7DTD **client and dedicated-server** instances for
sibling harnesses. Each instance is a fresh, isolated copy of a pristine base
plus its own Proton prefix (client) or userdata (server), so `7dtd-playtest`,
`7dtd-fastconnect`, and friends can run independent tests without clobbering
each other's Mods, saves, config, logs, or the Steam-managed install.

## Three launch modes

```bash
sb run client <name>   # client only, windowed 1280x720, no Steam (blocking)
sb run server <name>   # native Linux dedicated server (blocking)
sb run both   <name>   # server in background + client that auto-joins it
```

`sb run` creates the instance on first use. Examples:

```bash
./scripts/sb run both demo            # server 'srv-demo' + client 'client-demo'
./scripts/sb run client alpha         # solo client for manual testing
./scripts/sb run server srv-a         # headless server for loadgen bots
```

In `both` mode the sandbox stages the sibling `7dtd-fastconnect` client mod
(the stock client ignores `-connect=`), waits for the server's game port,
then launches the client, which joins automatically. Verified end to end:
Local-platform auth (`PltfmId='Local_client-demo'`) and
`PlayerSpawnedInWorld (reason: EnterMultiplayer)` with zero Steam processes.

## What it gives you

- **No Steam at runtime.** The client boots straight under Proton with
  `platform=Local` and `crossplatform=None`: no Steam client process, no
  Steam auth ticket, no EOS crossplay, no Twitch. Verified: the client
  reaches the main menu with zero Steam processes running.
- **Local clients are always admin.** `sb create-server` / `launch-server` /
  `wipe` / `run both` seed `userdata/Saves/serveradmin.xml` with
  `platform="Local"` `permission_level="0"` entries for every client instance
  name (stock auth: PltfmId `Local_<playername>`).
- **No Steam data-file verification.** `fetch-base` runs steamcmd without
  `-validate` (opt-in), and the sandbox refuses to live inside a `steamapps`
  tree, so Steam can never own or verify sandbox files.
- **Multiple instances at once.** Each instance has its own game copy (btrfs
  reflink/COW, near-zero disk cost) and its own Proton prefix or userdata.
  The client does not enforce a single instance. Server ports are allocated
  in unique 5-port blocks (27100+) so several servers can run concurrently.
- **Standardized contract** (`sb env <name>` / `instance.env`) that maps onto
  the env vars `launch_client.sh` already consumes.

## Layout

```text
7dtd-sandbox/
  base/game/            pristine Windows client base (steamcmd; never edit)
  base/server-game/     pristine Linux dedicated base (steamcmd, anonymous)
  instances/<name>/     one directory per instance
    game/               fresh COW copy of the base; apply mods here
    game/platform.cfg   Local platform / no EOS
    compatdata/         client: own Proton prefix
    userdata/           server: own saves/worlds/logs (+ declared Local admins)
    instance.props      server: the serverconfig properties declared for it
    logs/               host-side log dir
    instance.env        the standardized contract
  tools/steamcmd/       steam console client
  scripts/sb            the CLI
  scripts/sbconfig.py   serverconfig render/get, admin seeding, port derivation
  scripts/docker-gui.sh containerized client with host X11/GPU forwarding
  Dockerfile.safehouse    steamcmd/steamcmd-based runtime image
```

## Quick start

```bash
# 1. Fetch bases (client depot needs a logged-in Steam account)
./scripts/sb fetch-server-base
STEAMCMD_USER=<steam-name> ./scripts/sb fetch-base

# 2. Launch in any of the three modes (instances auto-create)
./scripts/sb run both demo
./scripts/sb run client alpha
./scripts/sb run server srv-a

# 3. Drive it from a sibling harness
eval "$(/path/to/7dtd-sandbox/scripts/sb env client-demo)"
CLIENT_PLATFORM=local /path/to/7dtd-fastconnect/scripts/launch_client.sh

# 4. Fresh state when done
./scripts/sb wipe srv-demo client-demo
./scripts/sb destroy srv-demo client-demo
```

## Commands

| Command | Purpose |
|---|---|
| `sb run <client\|server\|both> <name> [-- args]` | three-mode launcher (auto-create) |
| `sb init` / `sb doctor` | detect Proton/steamcmd, report readiness |
| `sb fetch-base [--validate \| --seed-from-steam]` | pull pristine client (Windows depot forced) |
| `sb fetch-server-base [--validate]` | pull pristine dedicated server (anonymous OK) |
| `sb create <name>` / `sb create-server <name> [--admin NAME...]` | fresh client / server instance (name-derived port block, declared admins) |
| `sb launch <name> [-- args...]` | run client under Proton, no Steam |
| `sb launch-server <name>` | run dedicated server |
| `sb up <name> [--timeout N]` | start the server detached, block until its game port listens, print the contract |
| `sb stage <name> <mod-dir>...` | copy built modlets into the instance's `Mods` |
| `sb render-config <name> KEY=VALUE...` | declare serverconfig properties (config is rebuilt from the base template) |
| `sb stop <name> [name...]` | stop only these instances' processes |
| `sb wipe <name> [name...]` | reset game, Mods, saves/userdata to pristine |
| `sb destroy <name> [name...]` | remove instances |
| `sb list` / `sb status <name>` | instances and running state |
| `sb logs <name> [-f]` | client or server log |
| `sb env <name>` | eval-able contract for sibling harnesses |

## Driving an instance from a harness

`sb run server` blocks forever, which is right for a person and wrong for a
test runner. `sb up` is the harness form: it starts the server in its own
session, waits until the game port accepts connections, and exits non-zero
with the log path when it does not.

```bash
./scripts/sb up srv-lab --timeout 240        # bring up (creates on first use)
./scripts/sb stage srv-lab ../7dtd-playtest/dist/7dtd-playtest
./scripts/sb render-config srv-lab GameWorld=Navezgane MaxSpawnedZombies=0
eval "$(./scripts/sb env srv-lab)"           # SERVER_PORT, SERVER_TELNET_PORT, ...
./scripts/sb stop srv-lab                    # teardown, this instance only
```

An instance is described, not accumulated. `instance.env` holds its identity,
port block and admins; `instance.props` holds the serverconfig properties it
was told to run with. Everything else is derived:

- **The config is rebuilt from the base template on every launch**, so
  undeclaring a property returns it to the stock value rather than leaving the
  last run's setting behind.
- **Ports come from the name**, not from creation order: `srv-lab` gets the
  same 5-port block on any machine, so a recorded port reproduces elsewhere. A
  block another instance holds is skipped deterministically. `ServerPort`,
  `TelnetPort` and `UserDataFolder` belong to the instance and `render-config`
  refuses them.
- **Admins are declared** in `SERVER_ADMINS`, not discovered by scanning the
  machine, so the same instance yields the same server on any host.

`sb stop` matches processes by that instance's own `SB_INSTANCE`, so a harness
never needs a `pkill` that would reach another instance's server. `sb wipe`
clears the declared properties along with the save.

`scripts/sbconfig.py` is the workspace's only serverconfig renderer and
`serveradmin.xml` seeder. It rewrites active properties, leaves commented ones
verbatim, inserts a property the template lacks, and escapes every value, so a
quote in a world name cannot terminate the attribute and inject further
properties. `7dtd-loadgen` calls it directly through `SANDBOX_ROOT`; only
`7dtd-server-container` keeps its own (production boot, different template).

## Environment

`SANDBOX_HOME`, `SANDBOX_INSTANCES`, `SANDBOX_BASE_GAME`,
`SANDBOX_SERVER_BASE_GAME`, `SANDBOX_STEAMCMD`, `STEAM_APPID` (251570),
`SERVER_APPID` (294420), `STEAM_ROOT`, `PROTON`, `GFX_API`, `SB_RES`
(windowed resolution, default `1280x720`), `SB_FULLSCREEN` (`0` default
windowed), `STEAMCMD_USER`, `STEAMCMD_PASS`, `7DTD_PLAYER_NAME`.

## Docker GUI (optional, experimental)

```bash
docker build -t 7dtd-safehouse:latest -f Dockerfile.safehouse .
./scripts/docker-gui.sh launch gamma
```

Runs the client in a container on `steamcmd/steamcmd` with the host X11
socket, GPU (`/dev/dri`), and ntsync forwarded; game data stays on the host
via bind mounts. The game window appears on the desktop and GPU rendering
works (`AMD Radeon RX 7900 XTX (RADV NAVI31)` confirmed via DXVK/D3D11), but
the client currently hangs during early Unity init inside the container
(log stops after `Input initialized`), so the native `sb run client` remains
the supported path for reaching the main menu.

## Notes

- **Verified:** the client boots to the main menu with zero Steam processes
  on the system (Local platform; `Steamworks is not initialized` is expected,
  caught, and non-fatal). Multiple instances run concurrently with fully
  separate game copies, Proton prefixes, Mods, saves and logs. Two sandbox
  servers + clients were run side by side with unique port blocks.
- **Sibling cross-talk:** other HordeForge harnesses use broad
  `pkill -f 7DaysToDie` / `clean_processes` sweeps that will also kill
  sandbox clients. Stop sandbox instances with `sb stop <name>` (matches by
  per-instance `STEAM_COMPAT_DATA_PATH` / `SB_INSTANCE`), and prefer that
  when cooperating on a shared machine.
- `sb stop` matches processes by per-instance env markers, so it never
  touches other instances or the Steam client.
