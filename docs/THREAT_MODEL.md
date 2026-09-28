# Threat model

Scope: this repository's own code, the `safehouse` container images, and the
instances they manage. The 7 Days to Die client and dedicated server are
third-party binaries; their own attack surface is not modelled here.

Every entry point, boundary and mitigation below carries a file reference so
the next pass can re-verify it against the code.

## Risk-ranked summary

Ranked by exploitability on the deployment this repository actually ships
(a developer machine, local harnesses) times impact.

| # | Risk | Where | Status |
|---|------|-------|--------|
| 1 | A sandbox server binds UDP/TCP `ServerPort` and a telnet port on **all** interfaces with three level-0 Local admins seeded and no password. Anyone on the lab network reaches a remote-console-capable game server. | `scripts/sb:699`, `scripts/sbconfig.py:66` | Accepted, documented as lab-only in `SECURITY.md`; no network-level control ships |
| 2 | Staged modlets are copied into `instance/game/Mods` and loaded as trusted code, and each modlet's `Native` dir is prepended to the server's `LD_LIBRARY_PATH`, so a staged mod also picks which native library loads. `stage_mods` checks only that `ModInfo.xml` exists. | `scripts/sb:1408`, `scripts/sb:731` | Unmitigated by design; isolation is per-instance, not per-mod |
| 3 | The docker GUI path runs the client as the host uid with `--ipc host`, `seccomp=unconfined`, `/dev/dri`, the X11 socket read-write, and the repository mounted read-write. | `scripts/docker-gui.sh:126` | Unmitigated; opt-in, developer-invoked only |
| 4 | `instance.env` is a shell file that callers `source` or `eval` (`scripts/sb:1181`). Every value written into it is shell code in the caller's shell. | `scripts/sb:193`, `scripts/sb:348` | Attacker-chosen values are charset-validated (`scripts/sb:621`) and every written value goes through `env_line` |
| 5 | `SANDBOX_HOME` and the other `SANDBOX_*` variables relocate every path `sb` writes to, and `sb wipe`/`destroy` run `rm -rf` against paths derived from them. | `scripts/sb:17`, `scripts/sb:1061` | Unvalidated by design: the operator's own environment. Instance names *are* validated (`scripts/sb:230`) |
| 6 | A serverconfig property value arrives from a harness (`render-config KEY=VALUE`) and is written into the XML the game parses. | `scripts/sb:753`, `scripts/sbconfig.py:138` | XML-escaped (`scripts/sbconfig.py:116`) and gated (`scripts/test_sbconfig.py`) |
| 7 | `sb stop`/`destroy` decide which processes to kill by matching marker values in `/proc/<pid>/environ`. Any same-user process that sets the matching variable is killed. | `scripts/sb:409`, `scripts/sb:464` | Markers are per-instance unique values; a same-user process can still opt in |
| 8 | Port allocation is name-derived, so two hosts recording the same instance name converge on the same block; a local forward probe then moves the second one. A wrong block sends a harness to a port nothing binds. | `scripts/sbconfig.py:292` | Deterministic probe, exhaustion fails loudly rather than overlapping |
| 9 | `_atomic_write` publishes via a temp file named from the target and the writing pid, in the same directory. | `scripts/sbconfig.py:495` | Same-user only, single-account lab; recorded, not mitigated |

## Entry points

| Entry point | Kind | Reference |
|---|---|---|
| `sb <command> [args]` | CLI argv, the primary operator surface | `scripts/sb:1617` |
| `sbconfig.py render/seed-admins/port-block/get` | CLI argv, also called directly by sibling harnesses | `scripts/sbconfig.py:616` |
| `SANDBOX_HOME`, `SANDBOX_INSTANCES`, `SANDBOX_BASE_GAME`, `SANDBOX_SERVER_BASE_GAME`, `SANDBOX_STEAMCMD`, `SB_CONFIG`, `SB_PY` | environment: these relocate every path and interpreter the CLI writes to | `scripts/sb:17` |
| `STEAMCMD_USER` | environment: the Steam account name | `scripts/sb:540` |
| `STEAMCMD_PASS` | environment: **refused**, exit 2, before anything else | `scripts/sb:530` |
| `PROTON`, `STEAM_ROOT`, `STEAM_APPID`, `SERVER_APPID` | environment: which binary runs, which app is fetched | `scripts/sb:22`, `scripts/sb:127` |
| `GFX_API`, `SB_RES`, `SB_FULLSCREEN` | environment: window and graphics API, validated before use | `scripts/sb:1243`, `scripts/sb:1320` |
| `7DTD_PLAYER_NAME` | environment: the Local player identity the client runs as | `scripts/sb:1241` |
| `FASTCONNECT_DIST`, `STEAM_SEED_SOURCE` | environment: sibling mod build, alternate seed source | `scripts/sb:1431`, `scripts/sb:559` |
| Instance name | argv, charset-validated before it reaches a path | `scripts/sb:147` |
| `render-config KEY=VALUE` | argv from a harness; becomes a serverconfig property | `scripts/sb:1551` |
| `create-server --admin NAME` | argv; becomes a `serveradmin.xml` user and a shell assignment | `scripts/sb:626` |
| `stage <name> <mod-dir>` | argv directory; its whole tree is copied into `game/Mods` and executed as game code | `scripts/sb:1408` |
| `instance.env`, `instance.props` | files in the instance tree, written by `sb` and read back by `sb` and by `source`-ing harnesses | `scripts/sb:348`, `scripts/sb:843` |
| `instance/game/serverconfig.xml` | the base template the generated config is rendered from, read as UTF-8 text | `scripts/sbconfig.py:202` |
| `userdata/Saves/serveradmin.xml` | read and rewritten on every launch and wipe | `scripts/sbconfig.py:419` |
| Modlet directory contents | every file in it reaches the game | `scripts/sb:1408` |
| `/proc/<pid>/environ` | read to find this instance's processes | `scripts/sb:409` |
| `docker run` flags, host mounts, capabilities | deploy-time surface | `scripts/docker-gui.sh:126` |
| Game port block, all interfaces | the network listener this repo causes to exist | `scripts/sb:699` |

Outputs a caller must not treat as inputs: `SB_CLIENT_CONNECT` is *set* by
`sb run both` for the client (`scripts/sb:1608`); nothing reads it back.

## Trust boundaries

1. **Operator shell to `sb`.** Every path, port and binary is caller-controlled
   through argv and the environment. Boundary controls: instance names are
   charset-validated (`scripts/sb:230`), the window declaration is validated
   (`scripts/sb:1320`), instance-owned properties are refused
   (`scripts/sb:744`). What is not validated: `SANDBOX_*` relocation, `PROTON`
   as a path, and the mod source path.
2. **Harness to the instance contract.** `instance.env` is shell source, and
   `sb env` prints it for `eval` (`scripts/sb:1181`). Any value in it is code.
   Boundary controls: admin names are charset-validated (`scripts/sb:621`),
   and every value `sb` writes goes through `env_line`, which quotes it
   (`scripts/sb:193`).
3. **`sb` to the game process.** Properties are escaped before they reach XML
   (`scripts/sbconfig.py:116`); admin names are escaped before they reach
   `serveradmin.xml` (`scripts/sbconfig.py:334`). Instance-owned keys are
   applied last so a declaration cannot win over them (`scripts/sb:809`).
4. **Host to sandbox instance tree.** Mods staged from an external directory
   become trusted game code, and `LD_LIBRARY_PATH` is prepended from every
   staged modlet's `Native` dir (`scripts/sb:731`).
5. **Host to container.** `scripts/docker-gui.sh` grants `--ipc host` (126),
   `seccomp=unconfined` (127), `/dev/dri` (58), the X11 socket read-write
   (147), the repository read-write (151), and runs as the host uid (68). It
   enables `xhost +local:` for local socket clients (54) and revokes it when
   the container exits (157).
6. **LAN to sandbox server.** The dedicated binds its allocated block on all
   interfaces, in the stock configuration this repository does not modify.

## Assets and impact

| Asset | Worth attacking for | Impact if lost |
|---|---|---|
| Steam account credentials (the password is now prompted for, never stored) | account takeover, library access | the fetch host's Steam account |
| The developer workstation itself | the container runs as the host uid with the repo mounted | loss of every lab instance and any uncommitted work in the tree |
| Per-instance game state (`userdata/Saves`, worlds) | cheating, cross-instance contamination | a destroyed run, and a misleading result if a run silently reuses another instance's world |
| Lab results (test scores, logs) | repudiation of what a recorded run actually did | a wrong conclusion believed correct |
| Host process table and `/proc` | other instances' environments, and any secret in them | cross-instance and cross-harness credential exposure |
| Availability of the display and GPU | several clients share it | every running instance is degraded, not just the attacker |

## Threats per boundary

### Operator shell to `sb`
- **Tampering / elevation:** `SANDBOX_HOME` or `SANDBOX_INSTANCES` pointed at a
  tree the attacker controls, then `sb wipe` (`scripts/sb:1082`) or `sb destroy`
  (`scripts/sb:1061`) runs `rm -rf` against paths derived from it. Instance
  names are validated, so this needs the environment, not argv.
- **Information disclosure:** `sb status` (`scripts/sb:1150`) and `sb env`
  (`scripts/sb:1181`) print absolute paths and instance contracts to stdout,
  which a CI log captures.
- **Spoofing:** none. There is no authentication in front of `sb`; anything
  that can run it as this user is the operator.

### Harness to the instance contract
- **Elevation of privilege (fixed):** `SERVER_ADMINS` was written into
  `instance.env` unvalidated, and `instance.env` is documented as `source`-able
  and is printed by `sb env` for `eval`. A `--admin` value carrying shell
  metacharacters became code in the caller's shell. Admin names are now
  charset-validated before they are written (`scripts/sb:621`), gated by
  `scripts/test_sb_cli.sh`.
- **Repudiation:** nothing records which harness declared which property, so a
  surprising serverconfig cannot be traced back to the run that wrote it.

### `sb` to the game process
- **Tampering:** a declared property value reaching the XML. Escaped at
  `scripts/sbconfig.py:116`; gated by `scripts/test_sbconfig.py`.
- **Information disclosure:** the rendered config can carry `TelnetPassword`
  and `serveradmin.xml` carries the level-0 admin list, so both are published
  `0600` by `_atomic_write`, on the temp before the rename so there is no
  umask window (`scripts/sbconfig.py:495`).
- **Elevation:** `UserDataFolder`, `ServerPort` and `TelnetPort` are
  instance-owned (`scripts/sb:744`); a harness cannot move a server off its
  allocated port block (`scripts/sb:809`).
- **Denial of service:** an undecodable base template or a refused property
  aborts the render with a named reason rather than writing a partial config
  (`scripts/sbconfig.py:202`).

### Host to sandbox instance tree
- **Elevation of privilege:** a staged modlet runs as game code, and its
  `Native` directory enters the server's `LD_LIBRARY_PATH`. Unmitigated here;
  the repository isolates instances, not mod code.
- **Tampering:** re-staging a modlet with the same basename replaces it
  wholesale rather than merging. The replacement is staged and published by
  rename (`scripts/sb:285`, `scripts/sb:309`), so a copy that fails part-way
  leaves the previously working modlet intact, and no staging debris is left
  behind.

### Host to container
- **Elevation of privilege:** the container is `--ipc host` with
  `seccomp=unconfined` and the repository mounted read-write, running as the
  host uid. A compromised game process reaches the host IPC namespace and every
  instance in the tree.
- **Spoofing:** `xhost +local:` disables access control for local X11 socket
  clients, which is how the container's user reaches the display. That user is
  the host uid, pinned by `scripts/docker-gui.sh:68` and by the runtime image's
  own `USER` (`Dockerfile.safehouse:143`); the display is not a separate trust
  boundary from the host account. The grant is revoked when the container
  exits, so it does not outlive the session that took it.

### LAN to sandbox server
- **Elevation of privilege:** every `SERVER_ADMINS` name joins at
  `permission_level="0"`, and the seeded defaults (`Player`, `client`, `admin`,
  `scripts/sbconfig.py:66`) mean a server created with no `--admin` still
  admits three well-known names. Deliberate for a lab, fatal on a shared
  network.
- **Stale authorization (fixed):** seeding was an upsert, so a name removed
  from `SERVER_ADMINS` kept its `permission_level="0"` entry in
  `serveradmin.xml` on every later launch. `seed-admins` now revokes the
  entries it seeded for a name the declaration no longer lists, scoped to the
  `sbseed="1"` marker it writes, so an entry a person or the game added is
  not touched.
- **Denial of service:** the server binds a predictable, name-derived port
  (`scripts/sbconfig.py:292`), so a scan finds every lab instance on the
  network. No rate limit, quota or connection control ships.

## Mitigations that exist

| Control | Covers | Reference |
|---|---|---|
| Instance-name charset | path traversal through an instance name | `scripts/sb:147` |
| Value quoting in `instance.env` | a value re-split by the sourcing shell | `scripts/sb:193` |
| Admin-name validation and escaping | injection into `serveradmin.xml` and into `instance.env` | `scripts/sb:621`, `scripts/sbconfig.py:334` |
| Admin names read from stdin, not argv | disclosure through `/proc/<pid>/cmdline` | `scripts/sb:383` |
| `STEAMCMD_PASS` refused | disclosure of the Steam password through the process table | `scripts/sb:530` |
| XML attribute escaping | property injection through a value | `scripts/sbconfig.py:116` |
| Instance-owned property refusal | a harness moving a server off its ports | `scripts/sb:744` |
| `0600` publish by rename | disclosure of `TelnetPassword` and the admin list, with no umask window | `scripts/sbconfig.py:495` |
| Staged copy published by rename | a failed re-stage destroying a working modlet | `scripts/sb:285` |
| Instance-scoped process matching | a teardown reaching another instance or the Steam client | `scripts/sb:409` |
| Mod pruning to `0_TFP_Harmony` | a contaminated base silently changing what runs | `scripts/sb:1389` |
| `assert_not_steam_owned` | Steam verifying or deleting a base or instance | `scripts/sb:201` |
| Image pinning by digest | an unreviewed image move | `Dockerfile.safehouse:38`, `Dockerfile.safehouse:83` |
| No steamcmd in the runtime image | a Steam provisioning chain in the run path | `Dockerfile.safehouse:83`, gated by `scripts/test_dockerfile.py:85` |
| No credentials as build inputs | a credential published in an image layer | `Dockerfile.safehouse:35` |

## Mitigations claimed but not implemented

- **"Instances are isolated from each other."** True, and `SECURITY.md` scopes
  it correctly under *Not in scope*: they are not isolated from the host user
  and not from staged mod code. Nothing in this repository sandboxes a mod.
- **DoS containment for a sandbox server.** There is none. No rate limit, no
  connection cap, no bind-address control ships, and the port is derivable
  from the instance name. Accepted for a lab, named here so a reader does not
  infer a control that does not exist.

## Abuse cases

- **A hostile Local player on the lab network** joins a sandbox server by
  guessing a name in `SERVER_ADMINS` and lands at permission level 0 with
  `dm`/`givetools`. Code path: `scripts/sbconfig.py:419` then
  `scripts/sb:699`.
- **A name-collision harness.** Two hosts that derived the same block for one
  instance name end up on one machine's block, and the forward probe moves the
  second one. Code path: `scripts/sbconfig.py:292`.
- **Workflow gaming through declared properties.** A suite sets
  `MaxSpawnedZombies=0` through `render-config` and the value persists in
  `instance.props` until someone runs `sb wipe`. That is the designed
  behaviour, and the wipe is the only reset.
- **Trust in client-side enforcement.** The window declaration (`SB_RES`) is
  enforced only in `sb`; a caller that passes its own `-screen-*` arguments
  overrides it (`scripts/sb:1330`).
- **A staged modlet as a supply-chain carrier.** Anyone who can write to a
  modlet directory named on an `sb stage` line controls not just the C# the
  game loads but the native library the server resolves, by shipping a `Native`
  directory. Code path: `scripts/sb:731`.

## Response readiness

- Instance actions leave no audit trail beyond the game's own log: `sb stop`,
  `wipe` and `destroy` print to stdout and nothing else.
- `SECURITY.md` names the reporting channel (a private security advisory) and
  no owner or cadence. None is invented here.

Last reviewed: 2026-09-28.
