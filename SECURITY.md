# Security

Safehouse builds and runs 7 Days to Die instances on a developer machine. It
handles Steam credentials during a base fetch and a telnet password in every
generated server config, which is why this file exists
(hordeforge/.github `REPOSITORY_STANDARDS.md` §1).

## Reporting

Open a private security advisory on
[hordeforge/7dtd-sandbox](https://github.com/hordeforge/7dtd-sandbox/security/advisories/new).
Do not open a public issue for anything that discloses a credential or a path
to one.

## Credentials

- **Steam login is env-only.** `sb fetch-base` reads `STEAMCMD_USER` and
  `STEAMCMD_PASS` from the environment and passes them to steamcmd. They never
  appear in a committed file. With `STEAMCMD_PASS` unset, steamcmd prompts on
  the terminal, which is the safer default for an interactive fetch.
- **Nothing goes through argv.** The process table is world-readable on a
  normal Linux host, so a password on a command line is a password every local
  user can read. `sb` passes secrets as environment or file content only.
- **The generated serverconfig is `0600`.** It can carry `TelnetPassword`
  (a harness renders one per run), so `sbconfig.py render` restricts the file
  it writes rather than inheriting the caller's umask.
- **Instance configs are not committed.** `instances/` is gitignored in full.

## Values that are test-only

The bases and instances this repository manages are lab fixtures on a
developer machine. Where a default password or an always-admin entry exists,
it is deliberately weak because the surface is local:

- `serveradmin.xml` seeding grants `permission_level="0"` to every Local
  player name in `SERVER_ADMINS`. That is the point of a lab instance, and it
  is why an instance must never be exposed to an untrusted network.
- Sandbox servers bind their allocated ports on all interfaces, as the stock
  dedicated does. Run them behind a firewall. Production deployment is
  [`7dtd-server-container`](https://github.com/hordeforge/7dtd-server-container),
  which has its own threat model; do not reach for a Safehouse instance to
  host players.

## Boundaries this repository enforces

- **No Steam at runtime.** No `steam -applaunch`, no Steam auth ticket, no EOS
  or Twitch. A client instance runs `platform=Local`.
- **Steam never owns these files.** `assert_not_steam_owned` refuses a base or
  instance inside a Steam library (`steamapps/common`), so Steam cannot verify
  or delete them out from under a run.
- **Values are XML-escaped before they reach a config.** `sbconfig.py` escapes
  every property value, so a quote in a world name cannot terminate the
  attribute and inject further properties. This is gated
  (`scripts/test_sbconfig.py`).
- **Processes are stopped by instance, never by pattern.** `sb stop` matches a
  process's own `SB_INSTANCE` or `STEAM_COMPAT_DATA_PATH`, so a teardown
  cannot reach another instance, another agent's run, or the user's Steam
  client.

## Not in scope

The game itself, its anti-cheat, and anything a mod does once loaded. Safehouse
isolates instances; it does not sandbox mod code. Untrusted mods are
[`7dtd-wasm`](https://github.com/hordeforge/7dtd-wasm).
