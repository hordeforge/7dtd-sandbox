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
| `.shellcheckrc` | The shell analyzer's configuration: optional checks the tree passes, each with the defect it catches |
| `ruff.toml` | The Python analyzer and formatter's configuration: rule groups, per-file ignores, the 100-column cap |
| `.yamllint.yaml` | The workflow analyzer's configuration: the 120-column cap the tree passes, and the `truthy` key exception GitHub's `on:` forces |
| `base/game`, `base/server-game` | Pristine steamcmd bases; never edited in place |
| `instances/<name>/` | One instance (gitignored) |
| `tools/steamcmd/` | The Steam console client (gitignored) |
| `Dockerfile.safehouse` | Image for `docker-gui.sh` |

Docs: [`README.md`](README.md) (what it is and how to drive it),
[`CHANGELOG.md`](CHANGELOG.md) (what each release shipped),
[`SECURITY.md`](SECURITY.md) (credentials, boundaries, what is deliberately
lab-weak), [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) (entry points,
trust boundaries, threats per boundary, and the mitigation claims the code does
not implement, each with a file reference), this file (rules and contracts).

## Gates that must not be weakened

Name them, because a gate nobody can name gets relaxed to make a change pass.
`make check test` runs all of them offline, in CI on every push and pull
request. No game, no Proton, no steamcmd.

| Gate | Pins |
|---|---|
| `scripts/test_sbconfig.py` | Property values are XML-escaped (a quote cannot inject properties); a value XML cannot carry is refused, not written; commented template lines stay commented and a commented `</ServerSettings>` is not an insert anchor; a re-render is byte-identical; ports are name-derived and probe deterministically (including a name carrying a byte that is not UTF-8); admins come only from the declaration, spelled as declared, in either the paired or the self-closing `<user>` form; a name the declaration drops is revoked (whole element, both forms) while an unmarked entry is not, so revocation is a function of the declaration in both directions; a claim on any port of a block takes the whole block, and a superseded `SERVER_PORT` line is not a claim; a file that is not UTF-8 is reported rather than rewritten; an interpreter below `MIN_PYTHON` is refused by name; `seed-admins` reads its names from stdin as UTF-8 whatever the host locale says (a `José` piped under `LC_ALL=C` is seeded as itself, and a name that is not UTF-8 is named and seeds nothing) and refuses the `--name` spelling; an instances directory this account cannot list is reported and skipped rather than raised over; the port scan survives an `instance.env` whose `SERVER_PORT` is Unicode digits rather than ASCII ones; a write that is interrupted rather than failed takes its temp file with it, so an instance tree accumulates no debris from a Ctrl-C |
| `scripts/test_sb_serverconfig.sh` | The config is rebuilt from the base template, so undeclaring a property returns it to the stock value; instance-owned keys are refused; a key outside `[A-Za-z_][A-Za-z0-9_]*` is refused rather than recorded, and a legal key is upserted as a literal, so none can reach the upsert as a pattern; a value spanning lines is refused, and so is one that is not valid UTF-8, while a UTF-8 value round-trips into the config; `instance.props` is 0600, because a declared value reaches a config kept user-only; a port pair the instance cannot use is refused before the declaration is recorded; a duplicate `SERVER_PORT` resolves the same way for the server and for `sb env`, so the port bound is the port a harness is told |
| `scripts/test_sb_ports.sh` | Creation order never shifts an instance's block; an instance does not block itself; a declaration whose 5-port block runs past the last port, or past the shell's integer, is refused |
| `scripts/test_sb_serveradmin.sh` | An unrelated instance on the machine cannot change a server's admin file; the file stays 0600 on creation and after a rewrite; `instance.env`, which carries the same names, is restricted on the same path; no admin name is passed in argv; a name dropped from `SERVER_ADMINS` loses its level-0 entry on the next bring-up, leaving the file parseable |
| `scripts/test_sb_copy.sh` | A copy that fails part-way costs the caller nothing: a failed `sb wipe` and a failed re-stage leave the instance tree and the modlet they were replacing intact, leave no staging or replaced-tree debris, and report `cp`'s own reason. Every replacing copy is staged and published by rename, because deleting the old tree first lost it whenever the rebuild failed. An interrupted run costs the caller the same: a wipe and a create signalled mid-copy leave no staging tree, no replaced tree and no partial instance directory, and the tree moved aside is put back rather than deleted |
| `scripts/test_sb_up.py` | `sb up` returns and leaves the server orphaned, not parented to `sb`, with nothing but the contract on stdout, so `eval "$(sb up <name>)"` works; a running instance is refused; a re-run against the directory a killed create left behind rebuilds the instance and still refuses a live one; a server that never binds fails inside its timeout; `sb list` and `sb stop` see the running instance and leave its idle neighbour alone |
| `scripts/test_sb_cli.sh` | Exit-code surface: every wrong command line (an unknown verb, a missing argument, a bare `--help` on a verb) is exit 2, never 1, and a near-miss verb is answered with the command meant; every verb has a `--help` page reachable both as `sb <verb> --help` and `sb help <verb>`, and each names its own flags; the Steam-library guard refuses a real library and accepts a steamcmd manifest dir; `sb env` output is data, not shell, when the caller evals it; an admin name or a serverconfig property that is not a plain identifier is refused; the declared python floor in `sb` and `MIN_PYTHON` in `sbconfig.py` are one number, a missing interpreter is named, and a caller-supplied `-screen-` argument is still recognised; a re-run teardown converges (`sb destroy` of an instance that is already gone exits 0 and does not stop at that name), and the auto-create path removes an unfinished instance and refuses a directory no create wrote |
| `scripts/test_sb_release.sh` | The shipped version is a `MAJOR.MINOR.PATCH` with a dated changelog section and the only version declaration in the tree; every release heading has its compare link |
| `scripts/test_sbconfig_fuzz.py` | The two untrusted-input parsers (`set_property` / `active_value` over a serverconfig template, `seed_admins` over a `serveradmin.xml` left by an earlier run) hold their invariants on mutated, structure-aware documents: write/read round trip, well-formed output, 0600 after a rewrite, declared admins at level 0, idempotence, and a per-call time budget. Seeded and deterministic (`--seed`, `--iters`); a finding prints a shrunk reproducer |

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
| `instance.env` | The standardized contract (below), written `0600` because a server's copy carries `SERVER_ADMINS`. Server instances carry `SERVER_KIND=server`, their port block, and `SERVER_ADMINS`. |
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

Every property below is gated:

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
   The pair is read back and re-validated at every bring-up: both keys must be
   present, in range and adjacent, so a hand-edited `instance.env` is refused
   before a server starts rather than after a harness misses a port. Range means
   the whole block: `SERVER_PORT + 4` is the last port the dedicated binds, and
   the check compares digits, since a declaration wider than the shell's
   integer wraps negative and reads as in range.
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
   player names the server admits at `permission_level=0`, on top of the three
   fixed names `sbconfig.py` seeds on every server (`Player`, `client`,
   `admin`) so a server-only create is usable with nothing declared. Seeding
   used to
   enumerate whatever client instances existed on the machine, so the same
   instance produced different servers on different hosts. Add names with
   `sb create-server <name> --admin NAME`, or edit `SERVER_ADMINS` and
   relaunch. A name outside `[A-Za-z0-9._-]` is refused (exit 2): the name
   reaches `instance.env`, which `sb env` hands to a caller that evaluates it.
   A name already in `serveradmin.xml` is found by folded comparison (NFC,
   then case-insensitive, as stock auth is) and rewritten to the declared
   spelling, because the game looks an admin up by exact `userid`: an entry
   left as `Istanbul` under a declaration of `istanbul` admits nobody.
   A name dropped from the declaration is revoked on the next bring-up, in
   both the paired and the self-closing form, so the file is the declaration
   and not the history of it. Revocation is scoped to the `sbseed="1"`
   marker `sbconfig.py` writes on the entries it owns: an admin a person or
   the game added carries no marker and is never deleted by a reseed.

6. **Files are decoded strictly, and an undecodable one is never rewritten.**
   `sbconfig.py` reads UTF-8 without a replacement fallback on every path it
   writes back, so a latin-1 `serveradmin.xml` or serverconfig is reported
   instead of being rewritten with U+FFFD where the bad bytes were, which
   turns one hand-edit into a name no player can ever match on the next
   launch. A read that never writes back (`recorded_ports`, which wants only
   digits) stays tolerant on purpose, and only ASCII digits count as a port:
   `isdigit()` accepts a superscript that `int()` then refuses, which raised
   out of a scan that exists to survive another instance's file.

   The same holds for the process's own streams: `seed-admins` decodes its
   stdin as UTF-8 explicitly rather than from the locale, so a `José` piped
   under `LC_ALL=C` (a cron job, a systemd unit, a CI runner) is the same name
   it is everywhere else instead of a surrogate that matches no player, and
   names that are not UTF-8 are refused with nothing written. `sb render-config`
   refuses a value that is not valid UTF-8 where it is written, rather than
   recording a declaration the renderer would refuse at every later launch.

7. **`instance.env` is shell source, so its values are quoted.** Both
   documented consumers parse the file with a shell (`eval "$(sb env <name>)"`
   and `source instances/<name>/instance.env`), so every value `sb` writes goes
   through `env_line` and lands as `KEY='value'`. A bare value is a value the
   consumer re-splits: the stock `Proton - Experimental` path assigned the
   prefix and then ran `-` as a command, and a path carrying a newline wrote a
   second line that shell executed. `env_value` takes the quotes back off, so a
   hand-edited bare value still reads.

`sb wipe` clears `instance.props` with the rest of the state: a wiped instance
is the base template again, not the last suite's world.

A declaration is `KEY=VALUE` on one line, with `KEY` matching
`[A-Za-z_][A-Za-z0-9_]*`. `sb render-config` refuses anything else (exit 2) at
the point it is written, and a hand-edited `instance.props` is re-validated
where it is read, naming the file and the line: persisting a malformed line
broke every later launch of that instance. A key the base template does not
name is still rendered, but warned about on stderr, because the game ignores a
property it has never heard of and a suite would otherwise believe it had
declared a value that never took effect.

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

A line prefixed `sb:` is a diagnostic and goes to stderr; stdout carries data
only. `sb up` therefore prints nothing but the contract, so
`eval "$(sb up srv-lab)"` is the bring-up and the read-back in one call, and the
same holds for `sb env`, `sb list`, `sb status` and `sb logs`. A status message
added to `sb up`'s stdout (the admin seed's own) broke that eval, so
`sbconfig.py seed-admins` reports on stderr too. Exit codes: 2 for a wrong
command line, 1 for a run that was understood and failed. Every verb has a
`--help` page, reachable as `sb <verb> --help` or `sb help <verb>`.

`sb render-config` refuses a property name outside `[A-Za-z_][A-Za-z0-9_]*` and
a value carrying a newline (exit 2). The name reaches the upsert that rewrites
an existing property and a line prefix in `instance.props`, so a name holding a
regex metacharacter could have matched and dropped a neighbour's declaration
there; the upsert now matches a literal `KEY=` prefix in the shell, and the
charset keeps a metacharacter from reaching it at all. The value is one line
of that file.

A bring-up that fails owns its own teardown: when the port wait times out, `sb
up` and `sb run both` stop the server they started rather than leaving a
detached process holding the instance's port block. `sb create` and `sb
create-server` are the same contract for a directory: a create that fails after
allocating the instance directory removes the partial tree, so a retry starts
clean instead of being refused with "already exists".

That rollback only runs when the create failed on its own terms. A create that
was killed, or that ran out of disk mid-copy, leaves the directory behind with
no `instance.env` in it, and the auto-create path (`sb up`, `sb run`) would
read it as an instance and fail on a contract nobody wrote. It removes such a
directory and builds the instance instead (`ensure_instance`), and only when
the directory holds nothing outside what a create writes: a directory carrying
anything else was put there by a person and is refused by name, not deleted.
`sb destroy` follows the same rule for the other end: an instance that is
already gone is exit 0, like `sb stop`, because teardown is re-run.

## The contract (sibling harnesses)

Standard env vars, resolvable two ways:

```bash
eval "$(/path/to/7dtd-sandbox/scripts/sb env <name>)"
# or source the instance's own file:
source /path/to/7dtd-sandbox/instances/<name>/instance.env
```

`sb env` prints `export K='V'` for both instance kinds, so the values reach
the environment of every process the caller spawns after the `eval`, not just
the caller's own shell. `instance.env` is written the same way (`KEY='V'`), so
`sourcing` it is the same operation: a stock Proton path (`Proton - Experimental`)
is one word rather than an assignment plus a command named `-`, and a path
carrying a newline cannot write a second line into the sourcing shell. A
hand-edited value may be written bare; `sb` reads both spellings.

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
| `runtime` | `ubuntu` | graphics/X11/Vulkan, python3, `sb`, `sbconfig.py`; runs as `1000:1000` | the client under Proton (`make docker`, then `scripts/docker-gui.sh`) |
| `fetch` | `steamcmd/steamcmd` | steamcmd, python3, `sb`, `sbconfig.py`; runs as root | `sb fetch-base` into a bind-mounted `base/` (`make docker-fetch`) |

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

The runtime image needs no privilege, so it does not run as root; the `fetch`
image does, for the two named reasons above (the primed steamcmd tree under
`/root`, and the chown of the bind-mounted `base/` back to the caller). Both
carry OCI labels, and the version label is `SB_VERSION` fed in as a build arg
by the `docker` and `docker-fetch` targets, so the image and the CLI cannot
disagree about which release an image carries.

Game data, instances and Proton stay on the host (bind mounts); neither image
contains game files. Ports are not published. `docker-gui.sh` forwards a
Linux host's X11 socket, `/dev/dri` and `$XAUTHORITY`, and refuses a host that
has none of them by name, rather than leaving docker to fail on the bind. Known limitation: the dockerized
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

   **Instances run in parallel** (verified the same day, also *executed*): two
   full suites at once on `par-a` and `par-b`, both `pass=5 fail=0`, on their
   own name-derived port blocks (27170/27171 and 27575/27576), their own lock
   files, and two windowed clients sharing the display. Neither refused nor
   killed the other. Wall clock was 155s and 150s against 92s solo, so GPU
   contention is the limit rather than any lock.

   That property rests on four things holding together, and breaking any one
   re-serialises the lab: name-derived ports, a per-client-instance lock file,
   a probe scoped to a prefix's own `STEAM_COMPAT_DATA_PATH`, and no pattern
   `pkill` anywhere on the managed path.

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
    tag. The release workflow refuses a tag that disagrees, a version that is
    not `MAJOR.MINOR.PATCH`, and a version with no dated `CHANGELOG.md`
    section, or one still empty because the notes sit under `[Unreleased]`.
    Every release gets a CHANGELOG entry, written as part of the same commit
    as the bump. `scripts/test_sb_release.sh` holds the same structural rules
    on every push.
12. **CI runs the same two targets you do.** `.github/workflows/ci.yml` is
    `make check` (which is `make lint`) then `make test`, nothing inlined, so
    a gate added here runs on every push without touching the workflow. Every
    gate works against a temp `SANDBOX_HOME` with fake bases: no game, no
    Proton, no steamcmd.
13. **No Python inside a shell script.** `sb` shells out to
    `scripts/sbconfig.py`; it carries no `python3 - <<EOF` heredoc, and the
    same rule holds in reverse. `make test` runs both gate kinds
    (`scripts/test_*.sh` and `scripts/test_*.py`).
14. **Both languages are analyzed, and the analyzers are pinned.**
    `make check` runs `bash -n`, shellcheck under `.shellcheckrc`, `ruff check`
    and `ruff format --check` under `ruff.toml`, yamllint under
    `.yamllint.yaml` over `.github/workflows/*.yml`, and `python -m
    compileall`. All three analyzers are required in CI (the check errors out
    rather than skipping when one is missing there) and each is named
    explicitly on the command line, so a stray rc file elsewhere on the
    machine cannot loosen the gate. All three are pinned in the Makefile
    (`RUFF_VERSION`, `SHELLCHECK_VERSION`, `SHELLCHECK_PY_VERSION`,
    `YAMLLINT_VERSION`, the version home for each), CI installs those pins by
    reading them out of the Makefile rather than repeating them, and
    `check-analyzer-versions` holds the installed analyzer to the pin: a note
    locally, fatal in CI. Use the pinned one locally, or `make format` is a
    diff somebody else has to absorb. A rule the tree does not pass is not
    enabled: an analyzer that fires on every line gets ignored, which is worse
    than the defect it was meant to catch.

## Fetching the bases

```bash
./scripts/sb fetch-server-base          # anonymous, free app 294420
STEAMCMD_USER=<name> ./scripts/sb fetch-base   # client needs an account
```
