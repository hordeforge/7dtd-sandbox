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
| 1 | A sandbox server binds UDP/TCP `ServerPort` and a telnet port on **all** interfaces with a level-0 Local admin seeded and no password. Anyone on the lab network reaches a remote-console-capable game server. | `scripts/sb:453`, `scripts/sbconfig.py:279` | Accepted, documented as lab-only in `SECURITY.md`; no network-level control ships |
| 2 | Staged modlets are copied into `instance/game/Mods` and loaded as trusted code. `sb stage` only checks that `ModInfo.xml` exists. | `scripts/sb:947` | Unmitigated by design; isolation is per-instance, not per-mod |
| 3 | The Steam account password is passed to `steamcmd.sh` as a command-line argument, so it is world-readable in the process table for the duration of a fetch. | `scripts/sb:303` | Claim contradicted in `SECURITY.md`; corrected there, fix deferred to sec-review |
| 4 | A serverconfig property value comes from a harness (`render-config KEY=VALUE`) and is XML-escaped, so it cannot inject properties. The base template it is rendered from is a file in the instance tree. | `scripts/sbconfig.py:112` | Escaping in place and gated (`scripts/test_sbconfig.py`) |
| 5 | `instance.env` is a shell file that callers `source` or `eval`. Every value written into it is shell code. | `scripts/sb:407`, `scripts/sb:622` | Values that are attacker-chosen are now charset-validated |
| 6 | The docker GUI path grants a container host IPC, an unconfined seccomp profile, the X11 socket, and the repository read-write. | `scripts/docker-gui.sh:98` | Unmitigated; opt-in, developer-invoked only |
| 7 | `sb stop`/`destroy` decide which processes to kill by reading `/proc/<pid>/environ`. Any process that sets the matching variable is killed. | `scripts/sb:217` | Scoped to per-instance unique values; a same-user process can still opt in |
| 8 | Port allocation is name-derived, so an instance name collides with another machine's recorded block only by chance and is resolved by a forward probe. A wrong block sends a harness to a port nothing binds. | `scripts/sbconfig.py:222` | Deterministic probe, exhaustion fails loudly |

## Entry points

| Entry point | Kind | Reference |
|---|---|---|
| `sb <command> [args]` | CLI argv, the primary operator surface | `scripts/sb:1131` |
| `sbconfig.py render/seed-admins/port-block/get` | CLI argv, also called directly by sibling harnesses | `scripts/sbconfig.py:402` |
| `SANDBOX_HOME`, `SANDBOX_INSTANCES`, `SANDBOX_BASE_GAME`, `SANDBOX_SERVER_BASE_GAME`, `SANDBOX_STEAMCMD`, `SB_CONFIG` | environment: these relocate every path the CLI writes to | `scripts/sb:16` |
| `STEAMCMD_USER`, `STEAMCMD_PASS` | environment: Steam credentials | `scripts/sb:302` |
| `PROTON`, `STEAM_ROOT`, `STEAM_APPID`, `SERVER_APPID` | environment: which binary runs, which app is fetched | `scripts/sb:21` |
| `GFX_API`, `SB_RES`, `SB_FULLSCREEN`, `7DTD_PLAYER_NAME` | environment: window and identity, validated before use | `scripts/sb:599`, `scripts/sb:880` |
| `7DTD_CONNECT`, `SB_CLIENT_CONNECT`, `FASTCONNECT_DIST`, `STEAM_SEED_SOURCE` | environment: connect target, mod source, seed source | `scripts/sb:1121`, `scripts/sb:323` |
| Instance name | argv, charset-validated before it reaches a path | `scripts/sb:108` |
| `render-config KEY=VALUE` | argv from a harness; becomes a serverconfig property | `scripts/sb:1064` |
| `create-server --admin NAME` | argv; becomes a `serveradmin.xml` user and a shell assignment | `scripts/sb:1156` |
| `stage <name> <mod-dir>` | argv directory; its whole tree is copied into `game/Mods` and executed as game code | `scripts/sb:947` |
| `instance.env`, `instance.props` | files in the instance tree, written by `sb` and read back by `sb` and by `source`-ing harnesses | `scripts/sb:407`, `scripts/sb:509` |
| `instance/game/serverconfig.xml` | the base template the generated config is rendered from, read as XML | `scripts/sbconfig.py:162` |
| `userdata/Saves/serveradmin.xml` | read and rewritten on every launch and wipe | `scripts/sbconfig.py:279` |
| Modlet directory contents | every file in it reaches the game | `scripts/sb:947` |
| `/proc/<pid>/environ` | read to find this instance's processes | `scripts/sb:217` |
| Docker socket / `docker run` | deploy-time surface, host mounts and capabilities | `scripts/docker-gui.sh:98` |
| Game port block, all interfaces | the network listener this repo causes to exist | `scripts/sb:453`, `scripts/sbconfig.py:58` |

## Trust boundaries

1. **Operator shell to `sb`.** Every path, port and binary is caller-controlled
   through argv and the environment. Boundary controls: instance names are
   charset-validated (`scripts/sb:108`), the window declaration is validated
   (`scripts/sb:880`), instance-owned properties are refused
   (`scripts/sb:509`). What is not validated: `SANDBOX_*` relocation, `PROTON`
   as a path, and the mod source path.
2. **Harness to the instance contract.** `instance.env` is shell source, and
   `sb env` prints it for `eval` (`README.md:146`). Any value in it is code.
   Boundary control: `SERVER_ADMINS` entries are now charset-validated
   (`scripts/sb:393`).
3. **`sb` to the game process.** Properties are escaped before they reach XML
   (`scripts/sbconfig.py:112`); admin names are escaped before they reach
   `serveradmin.xml` (`scripts/sbconfig.py:241`). Instance-owned keys are
   applied last so a declaration cannot win over them (`scripts/sb:496`).
4. **Host to sandbox instance tree.** Mods staged from an external directory
   become trusted game code, and `LD_LIBRARY_PATH` is prepended from every
   staged modlet's `Native` dir (`scripts/sb:463`), so a staged modlet also
   controls which native library the server loads.
5. **Host to container.** `scripts/docker-gui.sh` grants `--ipc host`,
   `seccomp=unconfined`, `/dev/dri`, the X11 socket read-write, and the
   repository read-write, and enables `xhost +local:` for local socket clients
   for the length of the session, revoking it when the container exits.
6. **LAN to sandbox server.** The dedicated binds its allocated block on all
   interfaces, in the stock configuration this repository does not modify.

## Assets and impact

| Asset | Worth attacking for | Impact if lost |
|---|---|---|
| Steam account credentials (`STEAMCMD_PASS`, Steam Guard) | account takeover, library access | the fetch host's Steam account |
| The developer workstation itself | the container runs as the host uid with the repo mounted | loss of every lab instance and any uncommitted work in the tree |
| Per-instance game state (`userdata/Saves`, worlds) | cheating, cross-instance contamination | a destroyed run, and a misleading result if a run silently reuses another instance's world |
| Lab results (test scores, logs) | repudiation of what a recorded run actually did | a wrong conclusion believed correct |
| Host process table and `/proc` | other instances' environments, and any secret in them | cross-instance and cross-harness credential exposure |
| Availability of the display and GPU | several clients share it | every running instance is degraded, not just the attacker |

## Threats per boundary

### Operator shell to `sb`
- **Tampering / elevation:** `SANDBOX_HOME` or `SANDBOX_INSTANCES` pointed at a
  tree the attacker controls, then `sb wipe` runs `rm -rf` against paths derived
  from it (`scripts/sb:668`). Instance names are validated, so this needs the
  environment, not argv.
- **Information disclosure:** `sb status` and `sb env` print absolute paths and
  instance contracts to stdout, which a CI log captures.
- **Spoofing:** none. There is no authentication in front of `sb`; anything
  that can run it as this user is the operator.

### Harness to the instance contract
- **Elevation of privilege (fixed):** `SERVER_ADMINS` was written into
  `instance.env` unvalidated, and `instance.env` is documented as `source`-able
  and is printed by `sb env` for `eval`. A `--admin` value carrying shell
  metacharacters became code in the caller's shell. Admin names are now
  charset-validated before they are written (`scripts/sb:393`), gated by
  `scripts/test_sb_cli.sh`.

### `sb` to the game process
- **Tampering:** a declared property value reaching the XML. Escaped at
  `scripts/sbconfig.py:112`; gated by `scripts/test_sbconfig.py`.
- **Information disclosure:** the rendered config can carry `TelnetPassword`, so
  it is chmod 0600 rather than inheriting the umask
  (`scripts/sbconfig.py:192`).
- **Elevation:** `UserDataFolder`, `ServerPort` and `TelnetPort` are
  instance-owned; a harness cannot move a server off its allocated port block
  (`scripts/sb:476`).

### Host to sandbox instance tree
- **Elevation of privilege:** a staged modlet runs as game code, and its
  `Native` directory enters the server's `LD_LIBRARY_PATH`. Unmitigated here;
  the repository isolates instances, not mod code.
- **Tampering:** `stage_mods` deletes the destination first
  (`scripts/sb:955`), so re-staging a mod with the same basename replaces it
  wholesale rather than merging.

### Host to container
- **Elevation of privilege:** the container is `--ipc host` with
  `seccomp=unconfined` and the repository mounted read-write, running as the
  host uid. A compromised game process reaches the host IPC namespace and every
  instance in the tree.
- **Spoofing:** `xhost +local:` disables access control for local X11 socket
  clients, which is how the container's user reaches the display. That user is
  the host uid, pinned by `scripts/docker-gui.sh` and by the runtime image's own
  `USER` (`Dockerfile.safehouse:143`); the display is not a separate trust
  boundary from the host account. The grant is revoked when the container
  exits, so it does not outlive the session that took it.

### LAN to sandbox server
- **Elevation of privilege:** every `SERVER_ADMINS` name joins at
  `permission_level="0"`, and the seeded defaults (`Player`, `client`, `admin`,
  `scripts/sbconfig.py:51`) mean a server created with no `--admin` still
  admits three well-known names. Deliberate for a lab, fatal on a shared
  network.
- **Stale authorization (fixed):** seeding was an upsert, so a name removed
  from `SERVER_ADMINS` kept its `permission_level="0"` entry in
  `serveradmin.xml` on every later launch. `seed-admins` now revokes the
  entries it seeded for a name the declaration no longer lists, scoped to the
  `sbseed="1"` marker it writes, so an entry a person or the game added is
  not touched.
- **Denial of service:** the server binds a predictable, name-derived port
  (`scripts/sbconfig.py:222`), so a scan finds every lab instance on the
  network. No rate limit, quota or connection control ships.

## Mitigations that exist

| Control | Covers | Reference |
|---|---|---|
| Instance-name charset | path traversal through an instance name | `scripts/sb:108` |
| XML attribute escaping | property injection through a value | `scripts/sbconfig.py:88` |
| Instance-owned property refusal | a harness moving a server off its ports | `scripts/sb:509` |
| Admin-name escaping and validation | injection into `serveradmin.xml` and into `instance.env` | `scripts/sbconfig.py:241`, `scripts/sb:393` |
| `serverconfig.xml` at 0600 | disclosure of `TelnetPassword` | `scripts/sbconfig.py:192` |
| Instance-scoped process matching | a teardown reaching another instance or the Steam client | `scripts/sb:217` |
| Mod pruning to `0_TFP_Harmony` | a contaminated base silently changing what runs | `scripts/sb:922` |
| `assert_not_steam_owned` | Steam verifying or deleting a base or instance | `scripts/sb:115` |
| Image pinning by digest | an unreviewed image move | `Dockerfile.safehouse:33`, `Dockerfile.safehouse:68` |
| No steamcmd in the runtime image | a Steam provisioning chain in the run path | `Dockerfile.safehouse:107` |
| No credentials as build inputs | a credential published in an image layer | `Dockerfile.safehouse:62` |

## Mitigations claimed but not implemented

- **`SECURITY.md` "Nothing goes through argv."** The Steam password is passed
  to `steamcmd.sh` as an argument (`scripts/sb:303`), so it is readable in the
  process table for the life of the fetch. The claim now states the exception.
- **Isolation of instances.** Instances are isolated from each other, not from
  the host user, and not from staged mod code. Nothing in the code sandboxes a
  mod.

## Abuse cases

- **A hostile Local player on the lab network** joins a sandbox server by
  guessing a name in `SERVER_ADMINS` and lands at permission level 0 with
  `dm`/`givetools`. Code path: `scripts/sbconfig.py:279` then
  `scripts/sb:453`.
- **A name-collision harness.** Two instances that derive the same block on
  different machines end up on one machine's block, and the forward probe
  moves the second one. Code path: `scripts/sbconfig.py:222`.
- **Workflow gaming through declared properties.** A suite sets
  `MaxSpawnedZombies=0` through `render-config` and the value persists in
  `instance.props` until someone runs `sb wipe`. That is the designed
  behaviour, and the wipe is the only reset.
- **Trust in client-side enforcement.** The window declaration (`SB_RES`) is
  enforced only in `sb`; a caller that passes its own `-screen-*` arguments
  overrides it (`scripts/sb:810`).

## Response readiness

- Instance actions leave no audit trail beyond the game's own log: `sb stop`,
  `wipe` and `destroy` print to stdout and nothing else.
- `SECURITY.md` names the reporting channel (a private security advisory) and
  no owner or cadence. None is invented here.

Last reviewed: 2026-09-28.
