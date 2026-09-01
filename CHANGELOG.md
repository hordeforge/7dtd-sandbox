# Changelog

Notable changes to Safehouse. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

The version has one canonical home, `SB_VERSION` in `scripts/sb`, printed by
`sb version`. The release workflow refuses a `vX.Y.Z` tag that disagrees with
it (hordeforge/.github `REPOSITORY_STANDARDS.md` §8).

## [Unreleased]

### Fixed

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
