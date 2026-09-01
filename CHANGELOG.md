# Changelog

Notable changes to Safehouse. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

The version has one canonical home, `SB_VERSION` in `scripts/sb`, printed by
`sb version`. The release workflow refuses a `vX.Y.Z` tag that disagrees with
it (hordeforge/.github `REPOSITORY_STANDARDS.md` §8).

## [Unreleased]

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

### Known limitation

- The `fetch` image reaches Steam and downloads, but cannot install into a
  **bind-mounted** `base/` on this host: identical image, user and command
  succeed to a container-local path and fail on the bind mount with "Failed to
  install app '294420' (Missing configuration)". Fetching therefore remains a
  host job through `tools/steamcmd`, and `tools/steamcmd` stays. Do not put
  steamcmd back into the runtime image to work around this.
- `sb fetch-base` / `fetch-server-base` refuse by name when steamcmd is absent
  and point at the `fetch` image, instead of failing inside a `cd` to a
  directory that was never there.

- **The client window is declared per instance.** `sb create <name> [--res WxH]
  [--fullscreen 0|1]` records `SB_RES` / `SB_FULLSCREEN` in the instance's
  `instance.env`, and every later launch reads it from there, so the same
  instance opens the same window on any machine and an ambient `SB_RES` in a
  caller's shell cannot change what a recorded run looked like. `sb env`
  exports the resolved `SB_SCREEN_ARGS` and every launcher passes them, so a
  client started through 7dtd-fastconnect's `launch_client.sh` (the path
  7dtd-playtest uses) gets the same window as one started by `sb launch`. It
  did not before, and inherited whatever the Proton prefix last saved; a
  sandbox client is a test fixture that must never take the display, and
  several have to be visible at once now that instances run in parallel. A
  malformed declaration is a refusal rather than a silent fallback to a client
  with no window arguments.

### Fixed

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

### Added

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

[Unreleased]: https://github.com/hordeforge/7dtd-sandbox/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/hordeforge/7dtd-sandbox/releases/tag/v0.1.0
