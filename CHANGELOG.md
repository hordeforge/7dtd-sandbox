# Changelog

Notable changes to Safehouse. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

The version has one canonical home, `SB_VERSION` in `scripts/sb`, printed by
`sb version`. The release workflow refuses a `vX.Y.Z` tag that disagrees with
it (hordeforge/.github `REPOSITORY_STANDARDS.md` §8).

## [Unreleased]

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
