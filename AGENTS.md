# AGENTS.md - Safehouse (`7dtd-sandbox/`; remote `7dtd-sandbox`)

Isolation layer for the stock 7DTD **client and dedicated server**: fresh,
Steam-free, per-instance game directories so sibling harnesses can run
independent tests without clobbering each other's Mods, saves, config, logs,
or the Steam-managed install.

Workspace rules: [`../AGENTS.md`](../AGENTS.md). Canonical modding guide:
[`../MODDING_BEST_PRACTICES.md`](../MODDING_BEST_PRACTICES.md).
Existing client launcher this layers under:
[`../7dtd-fastconnect/scripts/launch_client.sh`](../7dtd-fastconnect/scripts/launch_client.sh).
Auth model: [`../7dtd-loadgen/docs/STOCK_AUTH.md`](../7dtd-loadgen/docs/STOCK_AUTH.md).

Tier 0 and tier 1 of the workspace testing stack
([ADR 0001](https://github.com/hordeforge/.github/blob/main/docs/adr/0001-test-tiers-and-declarative-suites.md)):
everything a test needs to exist before a suite can run. Nothing above this
repo opens a serverconfig, allocates a port, or execs a dedicated server.

## Owns

- `scripts/sb`: the instance lifecycle CLI (`run`, `create`, `create-server`,
  `up`, `stage`, `render-config`, `launch`, `launch-server`, `stop`, `wipe`,
  `destroy`, `env`, `logs`, `list`, `status`, `fetch-base`,
  `fetch-server-base`, `doctor`, `init`).
- `scripts/sbconfig.py`: the workspace's one serverconfig renderer and
  `serveradmin.xml` seeder. `sb` calls it; `7dtd-loadgen` calls it through
  `SANDBOX_ROOT`. Only `7dtd-server-container` keeps a separate renderer
  (production container boot, `@TOKEN@` template with its own assert).
- `base/game` (Windows client) and `base/server-game` (Linux dedicated):
  pristine steamcmd-pulled bases; never edited in place. Instances are
  copies of these.
- Port allocation: a contiguous 5-port block per server instance, derived from
  the instance name.
- The per-instance isolation contract below.

## Does not own

- Gameplay automation, scenario runners, connect plumbing, server-side auth.
  Those stay in their sibling repos (`7dtd-playtest`, `7dtd-fastconnect`,
  `7dtd-loadgen`, ...) and consume the contract below.
- Suites, case refs, scoring, oracles. `7dtd-playtest` decides what runs; this
  repo decides what it runs on. Do not add `suites/*.json` or
  `IScenarioProvider` cases here.
- Production deployment (`7dtd-server-container`).
- The client itself or its modding. `MODDING_BEST_PRACTICES.md` rules still
  apply inside every instance's `game/`.

## Layout

| Path | What it is |
|---|---|
| `scripts/sb` | The instance lifecycle CLI, and the canonical version home (`SB_VERSION`) |
| `scripts/sbconfig.py` | Serverconfig render/get, admin seeding, name-derived port blocks |
| `scripts/docker-gui.sh` | Containerized client with host X11/GPU forwarding (see the limitation below) |
| `scripts/test_*.sh`, `scripts/test_*.py` | The gates; `make test` discovers them, no list to update |
| `base/game`, `base/server-game` | Pristine steamcmd bases; never edited in place |
| `instances/<name>/` | One instance (gitignored) |
| `tools/steamcmd/` | The Steam console client (gitignored) |
| `Dockerfile.safehouse` | Image for `docker-gui.sh` |

Docs: [`README.md`](README.md) (what it is and how to drive it),
[`CHANGELOG.md`](CHANGELOG.md) (what each release shipped),
[`SECURITY.md`](SECURITY.md) (credentials, boundaries, what is deliberately
lab-weak), this file (rules and contracts).

## Gates that must not be weakened

Name them, because a gate nobody can name gets relaxed to make a change pass.
`make check test` runs all of them offline, in CI on every push and pull
request. No game, no Proton, no steamcmd.

| Gate | Pins |
|---|---|
| `scripts/test_sbconfig.py` | Property values are XML-escaped (a quote cannot inject properties); commented template lines stay commented; a re-render is byte-identical; ports are name-derived and probe deterministically; admins come only from the declaration |
| `scripts/test_sb_serverconfig.sh` | The config is rebuilt from the base template, so undeclaring a property returns it to the stock value; instance-owned keys are refused |
| `scripts/test_sb_ports.sh` | Creation order never shifts an instance's block; an instance does not block itself |
| `scripts/test_sb_serveradmin.sh` | An unrelated instance on the machine cannot change a server's admin file |
| `scripts/test_sb_up.py` | `sb up` returns and leaves the server orphaned, not parented to `sb`; a running instance is refused; a server that never binds fails inside its timeout |
| `scripts/test_sb_cli.sh` | Exit-code surface; the Steam-library guard refuses a real library and accepts a steamcmd manifest dir |

## Sibling projects

Which repository owns the thing you are about to reimplement here:

| Project | Owns |
|---|---|
| [`7dtd-playtest`](https://github.com/hordeforge/7dtd-playtest) | Suites, case refs, scoring, the client scenario mod |
| [`7dtd-loadgen`](https://github.com/hordeforge/7dtd-loadgen) | Synthetic protocol clients; calls `scripts/sbconfig.py` for its own configs |
| [`7dtd-fastconnect`](https://github.com/hordeforge/7dtd-fastconnect) | Client join-by-IP and the client launcher this layers under |
| [`7dtd-server-container`](https://github.com/hordeforge/7dtd-server-container) | Production deployment; keeps its own config renderer on purpose |
| [`7dtd-wasm`](https://github.com/hordeforge/7dtd-wasm) | Sandboxing untrusted mod code (Safehouse isolates instances, not mods) |
| [`7dtd-engine-research`](https://github.com/hordeforge/7dtd-engine-research) | Stock-game reverse engineering. Never duplicated here |

## Three launch modes

```bash
sb run client <name> [-- game args]   # client only (Proton, no Steam)
sb run server <name>                  # dedicated server only (native)
sb run both   <name> [-- game args]   # server + client; client auto-joins
```

`sb run` creates the instance on first use. In `both` mode the server runs
detached as `srv-<name>` and the client as `client-<name>`; the sandbox
stages the sibling `7dtd-fastconnect` mod into the client (stock `-connect=`
is ignored by the client), waits for the server game port, then launches the
client with `7DTD_CONNECT=127.0.0.1:<port>`. Verified: Local auth +
`PlayerSpawnedInWorld` with zero Steam processes.

## Isolation model

Every instance `instances/<name>/` is fully independent:

| Path | What it isolates |
|---|---|
| `game/` | The game tree, fresh reflink/COW copy of the base (btrfs `--reflink`; plain copy fallback). Mods applied here never touch the base or other instances. |
| `game/platform.cfg` | Client: per-instance `platform=Local`, `crossplatform=None` (no Steam auth, no EOS). Server: Local/LAN auth surface (`serverplatforms=Steam,LAN,Local,`). |
| `compatdata/` | Client only: own Proton prefix (registry, `%APPDATA%\7DaysToDie`, `LocalLow`). |
| `userdata/` | Server only: own saves, generated worlds, logs, `serveradmin.xml` (always seeded with Local level-0 admins for every client instance name; PltfmId `Local_<playername>`). |
| `logs/` | Host-side log dir (client: symlink from prefix; server: direct write). |
| `instance.env` | The standardized contract (below). Server instances carry `SERVER_KIND=server`, their port block, and `SERVER_ADMINS`. |
| `instance.props` | Server only: the serverconfig properties declared for this instance (`sb render-config`). The config is rebuilt from these, never edited in place. |
| `instance.env` (client) | Also declares the window: `SB_RES`, `SB_FULLSCREEN`. |

Steam is never involved: no `steam -applaunch`, no Steam-managed library path
(`assert_not_steam_owned` refuses any base/instance under a `steamapps` tree),
no Steam auth ticket.

## Declarative and deterministic

An instance is described, not accumulated. Two files hold the description and
everything else is derived from them:

| File | Declares |
|---|---|
| `instance.env` | identity, paths, the port block, `SERVER_ADMINS` (server), the window `SB_RES` / `SB_FULLSCREEN` (client) |
| `instance.props` | the serverconfig properties this instance runs with (server) |

Three properties follow, and each is gated:

1. **The serverconfig is rebuilt, never edited.** `apply_server_config` renders
   the pristine base template plus `instance.props` plus the instance-owned
   values (ports, userdata, name, EAC off), every time. An in-place edit
   accumulates: a suite that sets `MaxSpawnedZombies=0` would leave it set for
   the next suite that says nothing about spawns. Undeclaring a property
   returns it to the base template's value.
2. **Ports are derived from the name.** `srv-lab` gets the same 5-port block on
   every machine whatever was created first, so a recorded port reproduces
   elsewhere. A block another instance already recorded is skipped by a
   deterministic forward probe; an exhausted range fails rather than
   overlapping. `ServerPort`, `TelnetPort` and `UserDataFolder` are
   instance-owned: `sb render-config` refuses them (exit 2), because a
   serverconfig that disagrees sends every harness at a port nothing binds.
3. **An instance's mods are `0_TFP_Harmony` plus exactly what was staged.**
   `sb create` and `sb wipe` prune everything else out of the *instance* (the
   base is never touched: rule 1), for two reasons. A base seeded from a Steam
   install carries whatever that install had, and this repo's client base
   carries RealEarth. And the two depots ship different TFP samples: the
   dedicated carries `TFP_CommandExtensions` and `Xample_MarkersMod`, the
   client neither, so keeping depot samples makes every pair asymmetric by
   construction. A suite that wants one names it in its mods list like any
   other. `sb doctor` reports what each base ships.
4. **The client window is declared, not ambient.** `SB_RES` / `SB_FULLSCREEN`
   live in the client's `instance.env`, so the same instance opens the same
   window anywhere and a stray variable in a caller's shell cannot change what
   a recorded run looked like.
5. **Admins are declared, not discovered.** `SERVER_ADMINS` lists the Local
   player names the server admits at `permission_level=0`. Seeding used to
   enumerate whatever client instances existed on the machine, so the same
   instance produced different servers on different hosts. Add names with
   `sb create-server <name> --admin NAME`, or edit `SERVER_ADMINS` and
   relaunch.

`sb wipe` clears `instance.props` with the rest of the state: a wiped instance
is the base template again, not the last suite's world.

## Harness bring-up

`sb run server` blocks forever, which is right for a person and wrong for a
test runner. The harness form is exit-coded and bounded:

```bash
sb up <name> [--timeout N]        # create if missing, start detached, block
                                  # until the game port listens, print `sb env`
sb stage <name> <mod-dir>...      # copy built modlets into game/Mods
sb render-config <name> K=V ...   # declare serverconfig properties; the config
                                  # is rebuilt from the base template plus every
                                  # declaration, so nothing carries over
sb stop <name>                    # teardown, this instance only
```

`sb up` refuses an instance that is already running, so two harnesses cannot
double-bind one instance. Teardown is by instance: `sb stop` matches processes
by that instance's own `SB_INSTANCE` (server) or `STEAM_COMPAT_DATA_PATH`
(client). A caller that pkills `7DaysToDieServer.x86_64` by pattern kills every
other instance on the machine; that is why `7dtd-playtest` dropped the pattern.

## The contract (sibling harnesses)

Standard env vars, resolvable two ways:

```bash
eval "$(/path/to/7dtd-sandbox/scripts/sb env <name>)"
# or source the instance's own file:
source /path/to/7dtd-sandbox/instances/<name>/instance.env
```

| Var | Meaning |
|---|---|
| `GAME` / `SERVER_GAME` | instance game dir |
| `COMPAT` | client instance Proton compatdata |
| `PROTON` | Proton binary (same name `launch_client.sh` reads) |
| `STEAM_ROOT` | Steam root, only used by Proton for its runtime lookup |
| `STEAM_APPID` | 251570 (client) |
| `SERVER_APPID` | 294420 (dedicated server) |
| `SERVER_USERDATA` | server instance userdata dir |
| `SERVER_PORT` / `SERVER_TELNET_PORT` | server game/telnet ports |
| `SERVER_CONFIG` / `SERVER_LOG` | serverconfig path / server log |
| `SERVER_PROPS` | declared serverconfig properties (`instance.props`) |
| `SERVER_ADMINS` | comma-separated Local player names admitted at level 0 |
| `LOGFILE` | host path of the client log |
| `SANDBOX_NAME` | instance id |
| `SB_RES` / `SB_FULLSCREEN` | windowed resolution (`1280x720`) / windowed (`0`) |
| `SB_SCREEN_ARGS` | the resolved `-screen-*` arguments every launcher passes |

**A sandbox client always starts windowed at the resolution it declared**
(`SB_RES` in its `instance.env`, default `1280x720`). It is a test fixture, not
a game session: it must never take the display fullscreen, and several
instances have to be visible at once.

The window is declared, not ambient. `sb create <name> [--res WxH]
[--fullscreen 0|1]` records it in `instance.env`; every later launch reads it
from there, so the same instance opens the same window on any machine and an
`SB_RES` in the caller's environment at launch time changes nothing. Edit
`instance.env` and relaunch to change it, exactly like `SERVER_ADMINS`.

`sb env` exports the resolved arguments as `SB_SCREEN_ARGS`, and every launcher
passes them, so a client started through `7dtd-fastconnect`'s
`launch_client.sh` (the path `7dtd-playtest` uses) gets the same window as one
started by `sb launch`. The command line wins over whatever the Proton prefix
last saved, which is why this is passed at every launch rather than seeded once
into the prefix. A caller passing its own `-screen-*` arguments to `sb launch`
still wins, because that is an explicit argument rather than ambient state.

A malformed declaration is a refusal, never a silent fallback to a client with
no window arguments.

## Docker GUI (optional)

`Dockerfile.safehouse` has two targets, because provisioning and running are
different jobs with different dependencies:

| Target | Base | Carries | For |
|---|---|---|---|
| `runtime` | `ubuntu` | graphics/X11/Vulkan, python3, `sb`, `sbconfig.py` | the client under Proton (`make docker`, then `scripts/docker-gui.sh`) |
| `fetch` | `steamcmd/steamcmd` | steamcmd, python3, `sb`, `sbconfig.py` | `sb fetch-base` into a bind-mounted `base/` (`make docker-fetch`) |

**The runtime image ships no steamcmd.** "No Steam at runtime" is rule 2; an
image carrying a Steam provisioning toolchain it never invokes contradicts it
while carrying the supply chain anyway. `sb fetch-base` there refuses by name
and points at the `fetch` target.

Both bases are pinned by digest, for the same reason the workflows pin actions
by commit SHA. Both images ship `sbconfig.py` as well as `sb`: every
serverconfig render, admin seed and port derivation shells out to it, so an
image with only `sb` has a CLI whose `create`/`up`/`render-config`/`wipe`
verbs all fail. `scripts/test_dockerfile.py` gates all of this statically, so
CI needs no docker.

Game data, instances and Proton stay on the host (bind mounts); neither image
contains game files. Ports are not published. Known limitation: the dockerized
client hangs during early Unity init (see README); use the native
`sb run client` for reaching the menu.

## Rules

1. **Never edit `base/game` or `base/server-game`.** Create an instance,
   apply mods to the instance's `game/Mods`, run, then `sb wipe`/`sb destroy`.
2. **No Steam at runtime.** No `steam -applaunch`, no Steam auth tickets, no
   Steam libraries in the launch path.
3. **No EOS, no Twitch, no other online services.** Client: `platform=Local`
   + `crossplatform=None`. Discord is disabled per instance via prefix
   registry seeding.
4. **One instance per concurrent client/server.** They are isolated by
   construction; do not run two clients against one instance dir.
5. **Fresh instance for fresh state.** `sb wipe <name>` resets game/Mods and
   saves/userdata to pristine base state; `sb destroy` removes the instance.
6. **Stop by instance.** `sb stop <name>` matches processes by their
   `STEAM_COMPAT_DATA_PATH` (client) or `SB_INSTANCE` env (server), unique
   per instance. Never blanket-`pkill` wine/proton/7DaysToDie from a sibling
   harness; it kills other instances.
7. **Python via `uv`, secrets via env** (workspace rule). No em dashes. No AI
   attribution.
8. `sb fetch-base` forces the **Windows depot** (`@sSteamCmdForcePlatformType
   windows`); steamcmd on Linux would pull the Linux client build, but the
   sibling ecosystem targets the Windows build under Proton. Steam
   data-file verification is off by default (`--validate` to opt in). The
   dedicated server base is the native Linux depot (anonymous pull works).
9. **The whole chain is verified live** (2026-09-02, graded *executed*): a base
   pulled through the `fetch` image with no host steamcmd, reflinked into an
   instance pair, brought up with `sb up`, driven by a real client through
   7dtd-playtest, asserted and torn down by instance. `SUMMARY pass=5 fail=0
   skip=0 wall_s=92.2` on the smoke suite, ports 27535/27536 (the block
   `srv-playtest` derives), lock `playtest_running-client-playtest`.

   No-Steam boot is part of that: the client reaches the world with zero Steam
   processes; `Steamworks is not initialized` in the log is expected and
   non-fatal in Local mode. Do not regress it by adding Steam auth, Steam
   runtime hooks, or `-applaunch` back into the launch path.

   A pristine base is load-bearing for this, not cosmetic. A client base that
   carried a terrain mod made the client fail to deserialize the server's first
   world package and get kicked, roughly forty seconds in, with nothing naming
   the cause. Pruning instance mods was not enough; the depot itself has to be
   clean, which is what `sb doctor`'s base-mods report is for.
10. `sb run both <name>` uses `srv-<name>`/`client-<name>` instance names so
    one command yields one isolated server+client pair; `sb stop` on both
    names tears the pair down.
11. **One version home: `SB_VERSION` in `scripts/sb`**, printed by
    `sb version`. Bump it, land that on main, then push the matching `vX.Y.Z`
    tag; the release workflow refuses a tag that disagrees. Every release gets
    a CHANGELOG entry.
12. **CI runs the same two targets you do.** `.github/workflows/ci.yml` is
    `make lint` then `make test`, nothing inlined, so a gate added here runs
    on every push without touching the workflow. Every gate works against a
    temp `SANDBOX_HOME` with fake bases: no game, no Proton, no steamcmd.
13. **No Python inside a shell script.** `sb` shells out to
    `scripts/sbconfig.py`; it carries no `python3 - <<EOF` heredoc, and the
    same rule holds in reverse. `make test` runs both gate kinds
    (`scripts/test_*.sh` and `scripts/test_*.py`) and `make lint` is
    shellcheck-clean, so neither is optional.

## Fetching the bases

```bash
./scripts/sb fetch-server-base          # anonymous, free app 294420
STEAMCMD_USER=<name> ./scripts/sb fetch-base   # client needs an account
```
