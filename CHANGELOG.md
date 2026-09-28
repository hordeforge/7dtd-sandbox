# Changelog

Notable changes to Safehouse. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

The version has one canonical home, `SB_VERSION` in `scripts/sb`, printed by
`sb version`. The release workflow refuses a `vX.Y.Z` tag that disagrees with
it, or that names a version this file has no section for (hordeforge/.github
`REPOSITORY_STANDARDS.md` §8). `scripts/test_sb_release.sh` checks the same
contract on every push, before a tag exists to reject.

**Versioning.** This is a `0.x` line, so SemVer's "anything may change before
1.0" clause is what actually ships here, and the tag history shows the de facto
policy rather than a written one: `0.1.0` was the first tagged release, and
`0.2.0` shipped contract changes that break a consumer (admins declared rather
than scanned, ports derived rather than recorded, a client window that follows
the instance rather than the environment) as a minor bump. So a minor is not a
safe upgrade for a harness that depends on behaviour, and a patch is.

**Deprecation.** There is no deprecation schedule and no support window. The
`sb` verbs a sibling harness calls are the public surface; a verb that goes away
goes away in a release, and its section below is where a caller reads it.
Nothing is deprecated ahead of removal in this repository today.

## [Unreleased]

### Added

- `scripts/test_sb_release.sh` gates the release contract on every push, so a
  version that is bumped without notes is caught here rather than by the tag:
  `SB_VERSION` must be `MAJOR.MINOR.PATCH`, must have a dated section in this
  file, and must be the only version declaration in the tree; every release
  heading needs its link definition, each compare link must name the previous
  release, and `[Unreleased]` must compare against the newest tag.
- `release.yml` refuses a tag whose `SB_VERSION` is not `MAJOR.MINOR.PATCH`,
  whose version has no section here, or whose section is empty because the
  notes are still under `[Unreleased]`. A tag with no notes is a release whose
  only record is a tag name.
- `docs/THREAT_MODEL.md`: entry points, trust boundaries, assets, threats per
  boundary, existing controls, and the mitigation claims the code does not
  implement, each with a file reference.
- Both images carry OCI labels (title, description, source, license, version).
  A `7dtd-safehouse:latest` tag says nothing about the `sb` inside it, so
  `docker image inspect` is the only place that could. The version label is a
  build arg fed from `sb version` by the `docker` and `docker-fetch` targets,
  never a literal in the Dockerfile, and `scripts/test_dockerfile.py` holds the
  derivation.
- The Python half of the tree is analyzed and formatted. `ruff.toml` selects
  the correctness rule groups the tree passes, and `make check` runs
  `ruff check` plus `ruff format --check`; `make format` applies the
  formatting. `python -m compileall` only ever proved the file parsed.
- `.shellcheckrc` turns on the optional shellcheck checks that catch defects
  (an unassigned uppercase, a value assigned in one branch, a glob that
  cannot expand, a zero step, `rm -rf "$DIR"/` with `DIR` unset) rather than
  the style preferences the tree does not follow. The tree passed all of them
  before they were enabled, so they are ratchets, not a backlog.

### Fixed

- A `sb up` (or `sb run both`) that times out waiting for the game port stops
  the server it started. That server was already detached and already holding
  its port block, so a harness retrying against a wedged instance left another
  server, world and userdata tree behind per attempt.
- A `sb create` or `sb create-server` that fails after allocating the instance
  directory removes the partial tree. It used to survive the failure and refuse
  every retry with "instance already exists" until someone removed it by hand.
- `sb stop`, `sb destroy` and both failed bring-up paths share one
  instance-scoped TERM-then-KILL teardown, so a server this run started is the
  server this run stops.
- `start_server_detached` truncates `logs/server.stdout.log` per start. It is
  the sandbox's own capture and nothing ever rotated it, so an instance brought
  up repeatedly grew it without bound. The game's own `server.log` is
  untouched.
- A failed `serveradmin.xml` atomic write no longer leaves its temp file behind
  in the instance's `Saves/` tree, where nothing swept it.
- `sb doctor` removes its reflink probe file whether the probe copy succeeded
  or failed.
- The runtime image defaulted to root. `sb` needs no privilege, and
  `scripts/docker-gui.sh` already pins `--user` to the caller, so a plain
  `docker run` of that image ran as root where nothing needed it. It runs as
  `1000:1000` now, with the image's own `/sandbox` (its `SANDBOX_HOME`) handed
  to that uid. The `fetch` image stays root: steamcmd writes into the tree the
  base image primed under `/root`, and `make fetch-base-docker` chowns the
  bind-mounted `base/` back to the caller through `--entrypoint chown`.
- `sb up` and `sb run both` took their port-wait deadline from the wall clock,
  so an NTP step ended the wait early or extended it by the size of the step
  instead of running the requested `--timeout`. The deadline is elapsed time
  read from the kernel's uptime counter now, and
  `scripts/test_sb_up.py` pins the port wait to a monotonic source.
- 0.2.0 shipped the client-window change as an unlabelled entry under `Fixed`,
  so the one breaking consumer change in that release (a client now follows
  the instance's `SB_RES` / `SB_FULLSCREEN` declaration instead of an ambient
  `SB_RES` in the calling shell) read as a bug fix. It is an `Added` entry
  under 0.2.0 now, with the before and after and the migration written out.
- 0.2.0 carried two `### Fixed` and two `### Added` headings. Keep a Changelog
  groups each kind once per release, and a repeated heading splits one fix list
  into two that read as separate.
- The 0.2.0 compare link pointed at `/releases/tag/`, which is a page, not the
  diff from 0.1.0.
- `sb launch` refuses a malformed `SB_RES` / `SB_FULLSCREEN` in an instance's
  declaration. The check ran inside a command substitution, so the refusal
  exited the subshell and the game started with no `-screen-*` arguments at
  all, the silent fallback the window contract forbids.
- A Local admin name given to `sb create-server --admin` is charset-validated
  before it is written to `instance.env`. That file is documented as
  source-able and `sb env` prints it for `eval`, so a name carrying shell
  metacharacters became code in the next harness's shell.
- `sb env` emits its contract as quoted shell assignments instead of echoing
  `instance.env` raw. Its documented consumer is `eval "$(sb env <name>)"`, so
  a declared value carrying a quote (an admin name, a path) closed the string
  and ran the rest of the line in the caller's shell.
- `sb render-config` refuses a property name outside `[A-Za-z][A-Za-z0-9_]*`
  and a value carrying a newline. The name is a regex in the upsert that
  rewrites an existing property and a line prefix in `instance.props`.
- `serveradmin.xml` is written `0600` on creation and after every rewrite, like
  the rendered serverconfig. A temp-and-replace that left the file at the
  umask's mode widened a permission_level=0 list to every local user.
- `seed-admins` is idempotent for a name that needs XML escaping. The upsert
  looked the entry up by the raw name while the entry itself was written
  escaped, so a name carrying `&`, `<` or a quote missed its own row and
  appended a second one, growing `serveradmin.xml` by a copy on every launch.
- The rendered serverconfig is published atomically, like `serveradmin.xml`
  already was. A write interrupted partway left a truncated config that the
  server would then start from, after the caller had already wiped the save
  it was about to regenerate. The 0600 mode is applied to the temp file before
  the rename, so there is no window where the config is world-readable.
- A declared property key is matched literally when it replaces an earlier
  declaration. Matched as a regex, a key like `.*` dropped every other entry in
  `instance.props`, so one `sb render-config` call erased the instance's whole
  declared state.
- `sb env` exports for a server instance, as it already did for a client. It
  printed bare `KEY=value` lines, which define a shell variable without
  exporting it, so the documented `eval "$(sb env <name>)"` resolution path
  left every server contract variable invisible to the child processes a
  sibling harness spawns. Both kinds now emit `export K='V'`, with the value
  single-quoted so a path with a space or a quote survives the `eval`.
- `sb fetch-base` refuses `STEAMCMD_PASS` (exit 2) instead of passing it to
  steamcmd as a `+login` argument. argv is world-readable, so the fetch put the
  Steam password on the process table, which contradicted the rule
  `SECURITY.md` states. steamcmd now prompts, as the docker path always did.
- A malformed `render-config` declaration (`=value`, a key with a space or a
  regex metacharacter, a value spanning a line break) is refused where it is
  written instead of being persisted. A persisted one broke every later launch
  of that instance.
- A server instance with a missing, non-numeric, out-of-range or non-adjacent
  `SERVER_PORT` / `SERVER_TELNET_PORT` is refused before the server starts, not
  by whatever the harness finds first.
- A property the base template does not name is warned about on stderr when
  the config is rendered: a misspelled key was inserted and then read by
  nobody, so the suite believed it had declared a value the server ignored.
- A failed `apply_server_config` no longer leaves the caller with an empty
  config path. It ran inside a command substitution, so its refusal exited the
  subshell and the server was launched with `-configfile=`.
- A non-numeric or zero `STEAM_APPID` / `SERVER_APPID` is refused before the
  fetch instead of being handed to steamcmd's `app_update`.
- `serveradmin.xml` is no longer rewritten with replacement characters where
  it holds a byte that is not UTF-8. The seeder decoded with
  `errors="replace"` and wrote the result back, so a latin-1 `José` became
  `Jos��` on the next launch, permanently. Both files `sbconfig.py` writes
  back are now decoded strictly and an undecodable one is reported instead.
- An admin already in `serveradmin.xml` under a different spelling is rewritten
  to the declared one. The game resolves an admin by exact `userid`, so an
  entry left as `Istanbul` under a declaration of `istanbul` (or a decomposed
  `Café`, which is what a macOS or Windows editor writes) granted level 0 to a
  name no client sends, and the file stopped being a function of the
  declaration alone. Matching is NFC then case-insensitive, as stock auth is.
- `sb render-config` refuses a value containing a newline, which
  `instance.props` would have read back as a second declaration.
- A port block for an instance name carrying a byte that is not UTF-8 is now
  derived instead of raising. Linux directory names may hold such bytes, and
  `7dtd-loadgen` calls `sbconfig.py port-block` directly.

### Documentation

- The changelog states the version policy this project actually follows, which
  the tag history shows and no document did: a `0.x` minor carries breaking
  contract changes, so a minor is not a safe upgrade for a harness pinned to
  behaviour. There is no deprecation schedule and no support window, and the
  `sb` verbs are the public surface.

### Changed

- CI installs a version-pinned ruff through `astral-sh/setup-uv` (pinned to a
  commit, like the checkout above it) and then runs the same `make check test`
  contributors run. Both analyzers are now required in CI: `make check` fails
  rather than skipping when shellcheck or ruff is missing. A test gate's
  shebang matches its executable bit.

## [0.3.0] - 2026-09-11

### Added

- Every server bring-up prepends each staged modlet's `Native` directory to
  `LD_LIBRARY_PATH` before exec. The Mono resolver only sees the loader search
  path captured at process start, so a modlet shipping a native library there
  (the 7dtd-wasm bridge ships `libwasmtime.so`) was never found. The path is
  derived from the instance's own `Mods` tree, never from the caller's
  environment.

## [0.2.0] - 2026-09-02

The instance contract becomes fully declarative, the container images split by
job, and the whole chain is verified running rather than building.

### Verified

- The full chain runs end to end (2026-09-02, graded *executed* per
  hordeforge/.github `REPOSITORY_STANDARDS.md` §9): a base pulled through the
  `fetch` image with no host steamcmd, reflinked into an instance pair, brought
  up with `sb up`, driven by a real client through 7dtd-playtest, asserted and
  torn down by instance. `SUMMARY pass=5 fail=0 skip=0 wall_s=92.2` on the
  smoke suite.
- Instances run in parallel: two full suites at once on separate pairs, both
  `pass=5 fail=0`, on their own name-derived port blocks and lock files, with
  two windowed clients sharing the display. 155s and 150s against 92s solo, so
  GPU contention is the limit rather than any lock. The property needs all four
  of: name-derived ports, a per-client-instance lock, a prefix-scoped probe,
  and no pattern `pkill` on the managed path.
- A contaminated client base was the cause of the client/server desync that
  had blocked every earlier live attempt (`NCSimple_Deserializer (ch=1):
  Attempted to read past the end of the stream`, then a kick, about forty
  seconds after joining). Pruning instance mods did not fix it; re-fetching a
  pristine depot did. `sb doctor`'s base-mods report exists to catch this
  before it costs a run.

### Added

- **`Dockerfile.safehouse` splits into `fetch` and `runtime` targets.** The
  runtime image was built `FROM steamcmd/steamcmd` and never invoked steamcmd
  once: `docker-gui.sh` runs the client under Proton from the host's
  bind-mounted Steam tree. An image shipping a Steam provisioning toolchain it
  never uses contradicts "no Steam at runtime" while carrying the supply chain
  anyway. steamcmd now lives in the `fetch` target, for pulling bases without
  installing it on the host; the runtime carries only the graphics stack.
  `make docker` / `make docker-fetch` build them, both bases are pinned by
  digest, and `scripts/test_dockerfile.py` gates the split without needing
  docker in CI.
- Both images ship `sbconfig.py`, not just `sb`. Every serverconfig render,
  admin seed and port derivation shells out to it, so the previous image had a
  CLI whose `create`/`up`/`render-config`/`wipe` verbs all failed.
- Two bugs in the old image, found by running it instead of building it:
  `/opt/steamcmd/steamcmd.sh` was a symlink to the script alone, so steamcmd
  looked for `linux32/steamcmd` beside it and every fetch died with "Couldn't
  find steamcmd" before contacting Steam. And overriding `HOME` in the fetch
  stage hands steamcmd a fresh unprimed Steam tree, which fails every
  `app_update` with "Missing configuration" after a clean login. Both are
  gated.

- `make fetch-server-base-docker` / `make fetch-base-docker` fetch a base
  through the container straight into `./base`, so the host needs no steamcmd
  at any point. The mount is a Docker local volume *bound to* that directory,
  not a plain `-v host:path` bind mount: steamcmd fails on the latter with
  "Failed to install app ... (Missing configuration)" and succeeds through the
  former (measured: same image, same user, same command, only the mount
  mechanism differs). The depot is chowned back to the invoking user, and
  `sb create` then reflinks from it as usual (about a second for a 17 GB base).
  Credentials are never a build input, because `docker history` prints build
  args and ENV back out; the client fetch is interactive at run time and only
  the account name crosses, through the environment.
- **The client window is declared per instance.** `sb create <name> [--res WxH]
  [--fullscreen 0|1]` records `SB_RES` / `SB_FULLSCREEN` in the instance's
  `instance.env`, and every later launch reads it from there. `sb env` exports
  the resolved `SB_SCREEN_ARGS` and every launcher passes them, so a client
  started through 7dtd-fastconnect's `launch_client.sh` (the path 7dtd-playtest
  uses) gets the same window as one started by `sb launch`. It did not before,
  and inherited whatever the Proton prefix last saved; a sandbox client is a
  test fixture that must never take the display, and several have to be visible
  at once now that instances run in parallel.

  **Breaking for callers:** a client used to follow an ambient `SB_RES` from
  the calling shell, and now follows the instance's own declaration, so a
  harness that set `SB_RES` in its environment has to declare it on the
  instance (`sb create --res WxH`, or edit `instance.env` and relaunch). An
  explicit `-screen-*` argument passed to `sb launch` still wins. A malformed
  `SB_RES` / `SB_FULLSCREEN` is a refusal rather than a silent fallback to a
  client with no window arguments. An instance that declared neither opens at
  the `1280x720` default.
- `make check` (the full static verdict) and `make clean`; `help` is the
  default goal. `make coverage` explains why there is no coverage number here
  rather than producing one nothing regenerates. `make up`, `make stage` and
  `make render-config` pass through to the matching `sb` verbs.
- `.gitattributes`, `.github/dependabot.yml`, `SECURITY.md`, `CLAUDE.md`, and
  the standard README header and badges, so the repository satisfies
  hordeforge/.github `REPOSITORY_STANDARDS.md` sections 1 through 5.
- CI runs `make check test` and then exercises the installed entry point
  (`sb version` against `SB_VERSION`, `sb help`, `sb list`), so a broken
  dispatch fails here rather than in a sibling harness.
- `AGENTS.md` gains a layout table, a named list of the gates that must not be
  weakened, and a sibling-ownership table.

### Fixed

- `sb create-server` declared its own instance name as a Local admin.
  `cmd_create_server` read `"$@"` for `--admin` extras without shifting the
  name off it first, so `srv-lab` seeded both `client-lab` and `srv-lab`.
- `sb fetch-base` / `fetch-server-base` refuse by name when steamcmd is absent
  and point at the `fetch` image, instead of failing inside a `cd` to a
  directory that was never there.

- **An instance no longer inherits mods the base happened to carry.** A base
  seeded from a Steam install carries whatever that install had; this repo's
  client base carries RealEarth, so every client instance ran a terrain mod no
  server instance had. The pair registered different blocks, the client failed
  to deserialize the first world package, and the server kicked it minutes into
  a run with nothing naming the cause. `sb create` and `sb wipe` now prune
  every mod except `0_TFP_Harmony` out of the instance (never out of the base),
  so what an instance runs is the Harmony loader plus exactly what was staged.
  TFP's own samples go too: the dedicated depot ships `TFP_CommandExtensions`
  and `Xample_MarkersMod` and the client ships neither, so keeping them made
  every pair asymmetric by construction. A suite that wants one names it in its
  mods list. `sb doctor` reports what each base ships.

- `sb up` returned only when its caller killed it. The server was started with
  a backgrounded `setsid ... &`, which left it parented to `sb`; the port check
  passed and then the shell sat in `do_wait` forever, hanging every harness
  that called it. `setsid --fork` orphans the server properly.
  `sb run both` never showed this because it execs the client over itself
  immediately afterwards. Gated by `scripts/test_sb_up.py`, which drives the
  real CLI against a fake listener.
- The Steam-library guard refused this repository's own pristine base.
  steamcmd writes its own `steamapps/` (appmanifest, downloading, temp) into
  whatever `+force_install_dir` it is given, and the ancestor walk read that
  bare directory as a Steam library. A library is `steamapps/common`.

### Changed

- `make lint` degrades with a printed note when shellcheck is absent on a dev
  host and hard-fails in CI, instead of failing everywhere.

## [0.1.0] - 2026-09-01

First tagged release. Safehouse is tier 0 and tier 1 of the workspace testing
stack ([ADR 0001](https://github.com/hordeforge/.github/blob/main/docs/adr/0001-test-tiers-and-declarative-suites.md)):
everything a test needs to exist before a suite can run.

### Isolation

- Steam-free client and dedicated-server instances. Each is a reflink/COW copy
  of a pristine steamcmd-pulled base with its own game tree, Proton prefix
  (client) or userdata (server), logs and config. No `steam -applaunch`, no
  Steam auth ticket, no EOS, no Twitch; `assert_not_steam_owned` refuses any
  base or instance under a `steamapps` tree.
- `sb run client|server|both <name>` as the three launch modes, plus the
  underlying `create`, `create-server`, `launch`, `launch-server`, `stop`,
  `wipe`, `destroy`, `list`, `status`, `logs`, `env`, `doctor`, `init`.
- The `instance.env` contract sibling harnesses consume.

### Declarative and deterministic

- An instance is described by `instance.env` (identity, port block,
  `SERVER_ADMINS`) plus `instance.props` (its declared serverconfig
  properties). Nothing else is remembered.
- The serverconfig is rebuilt from the pristine base template on every launch,
  never edited in place, so undeclaring a property returns it to the stock
  value instead of leaving the last run's setting behind.
- Port blocks are derived from the instance name, not from creation order, so
  the same name yields the same ports on any machine and a recorded port
  reproduces elsewhere. A block another instance holds is skipped by a
  deterministic forward probe; an exhausted range fails rather than
  overlapping. `ServerPort`, `TelnetPort` and `UserDataFolder` are
  instance-owned and `sb render-config` refuses them.
- Local admins come from `SERVER_ADMINS`, not from scanning whatever instances
  exist on the machine, so the same declaration produces the same
  `serveradmin.xml` on any host.

### Harness surface

- `sb up <name> [--timeout N]` starts the server detached and blocks until its
  game port accepts connections, with an exit code. `sb run server` blocks
  forever, which is right for a person and wrong for a test runner.
- `sb stage <name> <mod-dir>...` copies built modlets into the instance.
- `sb render-config <name> KEY=VALUE...` declares serverconfig properties.
- `sb stop` matches processes by that instance's own `SB_INSTANCE` (server) or
  `STEAM_COMPAT_DATA_PATH` (client), so a harness never needs a `pkill` that
  would reach another instance's server.

### Shared tooling

- `scripts/sbconfig.py` is the workspace's one serverconfig renderer,
  `serveradmin.xml` seeder and port derivation: `render`, `get`,
  `seed-admins`, `port-block`. It replaced four copies of the same XML
  rewriter across the workspace, and `7dtd-loadgen` calls it directly.
- `sb version` prints the shipped version.

### Gates

- `make lint` (bash -n + shellcheck, clean) and `make test` (CLI surface,
  port derivation, admin seeding, the serverconfig rebuild contract, and 25
  `sbconfig.py` cases) run in CI on every push. No game, no Proton and no
  steamcmd needed: every gate works against a temp `SANDBOX_HOME`.

### Known limitations

- The dockerized client (`Dockerfile.safehouse`, `scripts/docker-gui.sh`)
  hangs during early Unity init. Use the native `sb run client` to reach the
  menu.
- Instances created before this release keep the ports recorded in their
  `instance.env`; only new instances get a name-derived block.

[Unreleased]: https://github.com/hordeforge/7dtd-sandbox/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/hordeforge/7dtd-sandbox/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/hordeforge/7dtd-sandbox/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/hordeforge/7dtd-sandbox/releases/tag/v0.1.0
