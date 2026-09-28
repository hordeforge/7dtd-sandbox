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

**Grouping.** An entry belongs under `Changed` rather than `Fixed` when it
moves something a consumer resolves: a `sb` verb's exit code or output, a
`sbconfig.py` option, the `instance.env` format, the interpreter floor. The
defect behind such a change is written out under `Fixed` in its own right, so
both are on record. 0.2.0 shipped its client-window change under `Fixed` and
had to be relabelled after the fact; the rule is here so the next one does not
need the same repair.

**Deprecation.** There is no deprecation schedule and no support window. The
`sb` verbs a sibling harness calls are the public surface; a verb that goes away
goes away in a release, and its section below is where a caller reads it.
Nothing is deprecated ahead of removal in this repository today.

## [Unreleased]

### Added

- `sb init` (and `sb doctor`, which calls it) reports the whole resolved
  configuration: both base paths, the steamcmd dir, both app ids, `SB_CONFIG`,
  the window defaults and the bring-up timeout. Reading a run's configuration
  meant reading `scripts/sb`, so the one thing `doctor` is for was the one
  thing it did not say. It also runs on a host with no Proton yet, reporting
  the missing runtime instead of dying before its first line, which is what
  `detect_proton`'s refusal used to do to the report.
- An instances root of `[A-Za-z0-9._/-]` is refused at create, by name.
  `instance.env` carries the instance's paths unquoted and a harness is told to
  `source` it, so a root holding a space wrote a contract that half-evaluates
  when it is sourced (`GAME=/srv/lab/game` sets `GAME=/srv/lab` and runs
  `lab/game` as a command). `sb env` hides it, so it surfaced later as a
  missing game directory.
- `instance.env` is written 0600, like the two files its declarations reach
  (`serveradmin.xml` and `serverconfig.xml`). On a server it carries
  `SERVER_ADMINS`, so a 022 umask left every Local player name the instance
  admits readable to every account on the host. The mode is applied on every
  server bring-up, so an instance created before this is restricted too.
- The three names `sbconfig.py` seeds on every server besides the declared
  ones (`Player`, `client`, `admin`) are documented: in the module docstring,
  in the `seed-admins` help, in README and in AGENTS.md rule 5. They were the
  one set of level-0 Local admins that no document said were unconditional, so
  "admins are declared, not discovered" read as complete when it was not.
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
- The workflow definitions are analyzed too. `yamllint --strict` under
  `.yamllint.yaml` runs over `.github/workflows/*.yml` in `make check`, pinned
  as `YAMLLINT_VERSION` and installed by CI from the Makefile like the other
  two, with a 120-column cap (the longest line in either workflow is 114).
  A workflow is the one file in the tree GitHub reads, and nothing was reading
  it back.
- `ruff.toml` selects more of the analyzer's own groups, all of which the tree
  already passed: `A` (shadowing a builtin), `ANN` (every parameter and return
  annotated, so an untyped signature is a red build rather than a convention
  nobody checks), `ASYNC` (blocking the loop), `BLE` (a blind except), `DTZ` (a
  naive datetime), `ERA` (commented-out code) and `INP` (an implicit namespace
  package). `BLE` is the one that bites the shipped renderer, and `sbconfig.py`
  catches nothing it did not name; the five sites that need it are gate
  runners reporting a raising case as a finding, which the per-file-ignore
  says. ANN needed twelve signatures annotated across three gates to get
  there, none in the shipped renderer.
- `ruff.toml` targets `py38`, the floor `sbconfig.py` declares and `sb` mirrors,
  rather than the interpreter a contributor happens to run. At `py312` pyupgrade
  was free to suggest PEP 695 type parameters the floor cannot parse, and it
  took the first one as soon as a generic gate helper appeared.
- `.shellcheckrc` turns on four more optional checks the tree already passes:
  `check-avoid-nullary-conditions`, `check-redundant-assignment`,
  `check-dollar-star-at-quote` and `check-single-subshell`.
- `.shellcheckrc` turns on the optional shellcheck checks that catch defects
  (an unassigned uppercase, a value assigned in one branch, a glob that
  cannot expand, a zero step, `rm -rf "$DIR"/` with `DIR` unset) rather than
  the style preferences the tree does not follow. The tree passed all of them
  before they were enabled, so they are ratchets, not a backlog.
- `scripts/test_sbconfig_fuzz.py` fuzzes the two parsers that read text this
  repository does not control: the serverconfig template and a
  `serveradmin.xml` left in an instance's userdata. Structure-aware documents
  from a stock-shaped seed corpus, then byte-level mutation, with invariants a
  fuzzer alone cannot see (write/read round trip, well-formed output, 0600
  after a rewrite, declared admins at level 0, idempotence, per-call time
  budget). Seeded and deterministic; a finding prints a shrunk reproducer.

### Fixed

- Two instances could be handed one port block. The claim scan read
  `SERVER_PORT` verbatim, and `env_line` writes every value quoted
  (`SERVER_PORT='27100'`), so the token it read was not a digit string, the
  block another instance had recorded was not a claim, and the forward probe
  had nothing to step around: every instance derived the same block from its
  name. `recorded_ports` now reads a declaration the way a sourcing shell
  would. Separately, the claim is now taken under a create lock
  (`instances/.create.lock`, held with `flock`): scan and record were two
  steps with nothing between them, so two creates running at once both saw the
  slot free. The lock covers the whole create, because a block becomes visible
  to the next scan only once `instance.env` is written, and the kernel drops it
  when the holder dies, so an interrupted create leaves nothing to step around.
- A concurrent `sb create` of one name ran twice. The refusal was a `-e` test
  followed by `mkdir -p`, and `-p` succeeds against a directory the other
  create had just made, so both copies wrote into one tree. The claim is now
  the `mkdir` itself, which is the one allocation the filesystem makes atomic.
- An interrupted run left what it owned in the instance tree. `sb` registers
  the staging tree a copy is written into, the tree it moves aside to replace
  one, the `instance.props` temp and the directory a create is half-building,
  and settles every one of them on each exit path, a signal included: a
  `Ctrl-C` during a `cp -a` of the base used to leave a full staging tree, or
  a partial instance directory that refuses every retry with "already exists",
  per interrupted run, and nothing in the tree ever swept them. The tree moved
  aside is put back rather than removed, so cleaning up an interrupted publish
  cannot delete the only copy of an instance's game. `sbconfig.py` takes its
  temp with it on a `KeyboardInterrupt` as well as on an `OSError`, for the
  same reason in the same tree.
- The instance port block was range-checked on its first port alone, so a
  hand-edited `SERVER_PORT=65535` was accepted: telnet landed on 65536 and the
  dedicated's +2..+4 ports on 65537..65539, outside TCP/UDP entirely. The check
  bounds the last port of the block (`SERVER_PORT + 4`) against 65535. It also
  compared with the shell's integer, which wraps: `SERVER_PORT=9223372036854775808`
  became a negative value and passed `<= 65535`, and the server was rendered with
  a negative `ServerPort`. Digits are compared now, with the block's span
  (5 ports) named once in `sb` instead of the literal `+4` and `+ 1` it
  replaces. `sb run both` also passes the validated `SERVER_TELNET_PORT` to the
  server it starts rather than recomputing `port + 1`.
- `sbconfig.py port-block` refused nothing when `PORT_BLOCK_BASE` and
  `PORT_BLOCK_COUNT` were raised past the port space, and handed out blocks
  whose telnet and ephemeral ports cannot be bound. It fails by name now.
- `env_value` no longer takes the whole script down when an instance has no
  contract yet. `sed` exits 2 on the missing `instance.env`, and under
  `set -o pipefail` that status came back to any caller not already inside a
  command substitution. "No such key" is empty, the same answer as "no such
  line".
- `sb up` and `sb run` converge when they are run again against an instance
  whose create never finished. A create allocates the instance directory
  before the work that fills it, and its rollback only runs when the create
  failed on its own terms, so a create that was killed (or that ran out of
  disk mid-copy) left the directory behind. The bring-up read that directory
  as an instance and died with "missing instance.env" on every retry, for a
  tree no create ever finished. It now removes the directory and builds the
  instance, and refuses a directory holding an entry no create writes rather
  than deleting it.
- `sb destroy` of an instance that is already gone exits 0, like `sb stop`
  does. Teardown is re-run after a failed pass, and the refusal (exit 2,
  "instance not found") also stopped `sb destroy a b` at the first name that
  was gone, leaving the rest of the list standing.
- `sbconfig.py` refuses a `serveradmin.xml` carrying a DTD rather than parsing
  it. Expat expands internal general entities while it parses, so a nested
  entity definition in a hand-editable file cost exponential time in a check
  every bring-up runs. The file is rebuilt from the template, which carries no
  DTD.
- A freshly seeded `serveradmin.xml` is published by a rename from a 0600 temp
  rather than created at the umask and restricted afterwards. It holds the
  level-0 admin list from its first byte, and the create-then-chmod published
  it to every local account for as long as the chmod took.
- The declared `SERVER_ADMINS` are split with globbing off. A hand-edited
  declaration carrying a `*` expanded to the files in the current directory,
  and every one of them was seeded at level 0.
- `instance.props` was published at the caller's umask. A declaration reaches
  `serverconfig.xml`, which is kept 0600 precisely because a rendered config
  can carry `TelnetPassword`, and that password is declared in
  `instance.props`; the temp the rewrite builds is now restricted before the
  rename, like `sbconfig.py`'s own atomic write.
- `sb render-config` recorded its declarations before checking the instance's
  port pair. A hand-edited `instance.env` that failed the check exited with
  nothing rendered and `instance.props` already claiming the world, which the
  next launch then applied.
- `sbconfig.py recorded_ports` raised an unhandled `OSError` when the
  instances directory itself could not be listed, so a sandbox home another
  account owns turned an unrelated `sb create-server` into a traceback over a
  path the caller had never heard of. It is reported and skipped, as the
  per-file case already was.
- `sbconfig.py seed-admins` ended in a traceback over `sys.stdin` when the
  declared names on stdin were not valid UTF-8. The declaration and the reason
  are now named, and nothing is seeded.
- `seed_admins` created a new `serveradmin.xml` with a direct write and
  restricted it afterwards, so the file was readable by every local account for
  the length of that window and a write failing part-way left a half-written
  file behind. Creation goes through the same temp-and-rename the rest of the
  module uses.
- A missing `logs` symlink in the Proton prefix was silent: the client then
  wrote its log inside the prefix and the host path `instance.env` declares as
  `LOGFILE` never appeared, with nothing saying why `sb logs` was empty.
- `scripts/test_sb_up.py` picked a port by binding to 0 and closing, which
  proves nothing once the fixture server is a separate process: the kernel
  hands out ports other sockets are listening on, so the never-binds case ran
  against whatever was squatting on the port and failed or passed at random. A
  port is now handed out only once nothing answers on it.
- `.ruff_cache/` is ignored and `make clean` removes it. `make check` writes
  it into the tree it is checking, so a contributor's local run left an
  untracked directory behind that nothing accounted for.
- `scripts/test_sbconfig_fuzz.py` shipped executable (mode 100755) with no
  shebang, which `ruff check` reports as EXE002, so `make check` was red and
  every push failed CI on a tree nobody had changed. It now carries the same
  `#!/usr/bin/env python3` as the other Python gates; the `EXE` rule group
  ruff already ran is what holds the executable bit and the shebang together.
- A name dropped from `SERVER_ADMINS` kept its `permission_level="0"` entry in
  `serveradmin.xml` forever. Seeding was an upsert and nothing removed what a
  declaration no longer listed, so the file was a function of every
  declaration the instance had ever made rather than the one it makes now: a
  player removed from the list still held `dm` and `givetools` on every later
  launch. `seed-admins` now revokes the entries it seeded for an undeclared
  name. Only entries carrying the new `sbseed="1"` marker are revoked, so an
  admin a person or the game wrote is never touched, and both the paired and
  the self-closing `<user>` forms are removed whole.
- The port the server bound and the port a harness was told could disagree.
  `instance_server_ports` read the first `SERVER_PORT` line while `env_value`
  and `sb env` resolve the last, so a hand-edited duplicate made the server
  listen on one port and every harness connect to another, missing a port
  nothing was listening on. The bring-up reads through `env_value` now, the
  one lookup every other reader uses.
- The port allocator tested only a block's first port, so a claim recorded on
  a port inside a block (a hand-edited `instance.env`, an older layout) was
  handed the same block again and two servers landed on the same ports. A
  block is free when none of the five ports it covers is claimed.
- `recorded_ports` counted a superseded `SERVER_PORT` line as a claim, so a
  hand-edited duplicate reserved a block no server was on and took it out of
  the range for every other instance. The last declaration is the one that
  instance binds, and the only one counted.
- `make check` was red on a clean checkout with the ruff CI pins: 45 findings
  across `sbconfig.py` and the two config gates (long lines, percent-format,
  magic values in the fuzzer's shape rolls, a stale `noqa`, a shebang on a
  gate `make test` runs through `python3`). Fixed in the code rather than in
  `ruff.toml`, so the analyzer a new contributor runs is the one CI runs.
- `make check` said nothing useful when shellcheck or ruff was missing locally:
  a `note:` line naming neither what did not run nor how to get the tool. It
  now prints a warning per missing tool, the install line, and the fact that
  CI refuses to run without it, so a half-run check cannot read as a green one.
- The per-instance process scan read every `/proc/<pid>/environ` through a
  `tr | grep` pair, forking twice per process on the host. On a busy machine a
  `sb up --timeout 3` whose server never bound took over 30s to fail, so
  `scripts/test_sb_up.py` failed a bring-up that was honouring its timeout. The
  environment is read in-process now, on a whole entry, so a value holding the
  marker inside another one still cannot match.
- `scripts/test_sb_serverconfig.sh` declared `Game.World=dot` to prove the
  property upsert matched a key literally. `validate_prop` refuses any key
  outside `[A-Za-z_][A-Za-z0-9_]*` first, so the gate died on its own setup
  line. It now proves the same defect is unreachable through a key that is
  legal, and that the upsert spares the neighbouring declaration.
- `make check` passes again on the tree as committed. The fuzz gate
  (`scripts/test_sbconfig_fuzz.py`) landed with 51 findings under the pinned
  ruff, so the static verdict was red on a clean checkout: percent formatting,
  over-long lines, a closure over a loop variable, dead `noqa` directives and
  a file with a shebang and no execute bit. The gate was never run against the
  file that introduced it, and `make check` is the interface every contributor
  and the CI job share, so a red one hides the findings it exists to report.
- Both analyzers are pinned, and CI installs the pins. The version home is
  `RUFF_VERSION` / `SHELLCHECK_VERSION` / `SHELLCHECK_PY_VERSION` in the
  Makefile, which `.github/workflows/ci.yml` reads rather than repeating; the
  shell half came from whatever shellcheck the runner image happened to carry,
  so the shell gate was a moving target. `make check` now names the pinned
  version and how to install it: a note locally, fatal in CI.
- `make docker` / `make docker-fetch` refuse to build when `sb version` yields
  nothing. The version reached the image as a command substitution, so a
  failure expanded to `--build-arg SB_VERSION=""`, which labels the image with
  a blank version and lets `docker build` report success. That label is the
  only record of which `sb` a pulled image carries.
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
- `sb launch` told the game to write `output_log_sandbox.txt` while every other
  surface named `output_log_client.txt`: the `LOGFILE` an instance declares and
  exports, the `sb status` and `sb logs` paths, and the test fixture. A running
  client therefore had no log at the path the contract names, and `sb logs
  <client>` died with "no log yet". The game writes the declared name now.
- A hand-edited `instance.env` with two declarations of one key was read two
  different ways: `sb env` exported both, so the caller's shell settled on the
  last, while every reader in `sb` read the first. They read the last now, which
  is what "edit it and relaunch" already did for the caller.
- `sb up` and `sb run both` took their port-wait deadline from the wall clock,
  so an NTP step ended the wait early or extended it by the size of the step
  instead of running the requested `--timeout`. The deadline is elapsed time
  read from the kernel's uptime counter now, and
  `scripts/test_sb_up.py` pins the port wait to a monotonic source.
- `sbconfig.py` refuses a property value carrying a C0 control (exit 2)
  instead of writing it. XML cannot hold one in an attribute: a raw control
  makes the config unparsable, and a tab, LF or CR is normalized to a space on
  parse, so the game would read something other than the declared value.
  Generated XML is read and written with `newline=""` for the same reason, so
  text-mode newline translation no longer rewrites a declared CR.
- `seed_admins` rewrites a `serveradmin.xml` that no XML parser accepts rather
  than upserting into it. The upsert left the game reading the same broken
  config with the declared admins missing.
- The admin upsert keeps the closing tag of a paired `<user ...></user>` when
  it adds a `permission_level`. It closed the start tag as if the element were
  self-closing, orphaning `</user>` and producing a file no parser accepts.
- `set_property` inserts a missing property before the first
  `</ServerSettings>` that is not inside a comment. A template carrying the
  closer only as a commented line got the property inserted into the comment,
  where neither the game nor `sb get` reads it.
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
- `sb render-config` refuses a property name outside `[A-Za-z_][A-Za-z0-9_]*`
  and a value carrying a newline. The name reaches the upsert that rewrites an
  existing property and a line prefix in `instance.props`, where a regex
  metacharacter would have matched and dropped a neighbour's declaration.
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
- `scripts/test_sb_serverconfig.sh` asserted that `sb render-config` accepts a
  key holding a `.`, which `validate_prop` refuses, so the assertion aborted
  the gate under `set -e` on a clean tree and every check after it, including
  the port-block assertions, never ran. It now pins the shipped contract: a
  key that is not a bare identifier is refused, so no key reaching the upsert
  can mean anything but itself, and the declaration beside it is untouched.
- `scripts/docker-gui.sh` names its container per invocation. A fixed name
  refused a second concurrent GUI client with "the container name is already in
  use", which is the one thing this sandbox otherwise runs in parallel.
- `.dockerignore` excludes `.scratch/` and `__pycache__/`. The DXVK/Fossilize
  cache a docker-gui session writes is unbounded and is not a build input, and
  `make docker` uploaded all of it to the daemon first.
- `scripts/docker-gui.sh` resolves Proton the way `sb detect_proton` does
  (-Experimental, 11.0, 10.0) instead of demanding -Experimental, and overlays
  the writable `dist.lock` on whichever Proton it found. A host on Proton 10 or
  11 could run the native client and was refused on the containerized path.
- The declared interpreter floor is 3.8, not 3.7. `_atomic_write` unlinks its
  temp file with `Path.unlink(missing_ok=...)`, which is 3.8, so on 3.7 the
  write-error path raised `TypeError` instead of the `RuntimeError` that names
  the file. `SB_PY_MIN` in `sb`, `MIN_PYTHON` in `sbconfig.py` and the README
  all move together. The raise itself is a contract change and is written out
  under `Changed`.
- The instance directory is created 0700 and restricted again on every bring-up
  and every wipe. `instance.env`, `serveradmin.xml`, `serverconfig.xml` and
  `instance.props` were each restricted by name, and the directories holding
  them were left at the umask (0755 under the usual 022), so the files the game
  writes itself, which carry the same player names plus the saves and the log
  lines naming who connected, were readable by every account on the host
  through a directory the per-file restrictions never covered. The restriction
  is on the directory because the game creates those files; a client instance
  is restricted the same way, since its Proton prefix and log hold the same
  data.
- `sbconfig.py seed-admins` reports how many Local admins it seeded rather
  than naming them. The names are player names this server admits, and the line
  lands on whatever captured stdout: a harness log, a CI transcript, a
  terminal scrollback. The declaration seeded from is where the names belong.

### Documentation

- `sb help` documented the property-key charset as `[A-Za-z][A-Za-z0-9_]*`
  while `validate_prop` accepts a leading underscore. The help text, README and
  AGENTS.md now name the charset the code enforces.
- `Dockerfile.safehouse` still said a base could not be fetched into a
  bind-mounted `base/` and that fetching stayed a host job. The bind mount
  became a Docker local volume bound to `base/` (`make base-volume`, `make
  fetch-server-base-docker`), so the header named a limitation the tree had
  already solved.
- The comment on `usage_err` claimed every usage path exits 2. The older
  verbs (`run`, `create`, `launch`, `status`, ...) report a missing argument
  through `die`, and `scripts/test_sb_cli.sh` pins that as exit 1. The comment
  names the actual split.
- The comment on `instance_env_value` claimed every reader of `instance.env`
  goes through it. `instance_server_ports`, `instance_kind` and `cmd_env` walk
  the file themselves; it now says which readers it serves.
- `emit_env` and its helper `shell_quote` were unreachable, and the comment
  above them described the export behaviour `cmd_env` implements inline. Both
  are gone.
- The FNV-1a rationale in `sbconfig.py` sat above `MIN_PYTHON`, four lines
  from the constants it explains, and read as that declaration's comment. It
  sits with them now.
- `scripts/docker-gui.sh` said the X11 `xhost` grant is for "container root",
  but the run is pinned to the host uid.
- The changelog states the version policy this project actually follows, which
  the tag history shows and no document did: a `0.x` minor carries breaking
  contract changes, so a minor is not a safe upgrade for a harness pinned to
  behaviour. There is no deprecation schedule and no support window, and the
  `sb` verbs are the public surface.

### Changed

- The interpreter floor moved from 3.7 to 3.8. Before, a 3.7 host ran
  `sbconfig.py`; after, it is refused by name, by `sb` before it runs anything
  and by `sbconfig.py` at its own entry point. The reason it moved is under
  `Fixed`: `_atomic_write` needs `Path.unlink(missing_ok=...)`, which is 3.8.
  A host on 3.7 upgrades the interpreter; nothing else about its instances
  changes. `SB_PY_MIN` in `sb`, `MIN_PYTHON` in `sbconfig.py` and the README
  moved with it, and `scripts/test_sb_cli.sh` holds the two declarations to
  one number.
- `sbconfig.py seed-admins USERDATA` reads the declared Local admin names from
  stdin, one per line, and the `--name` spelling is refused (exit 2). Before:
  `sbconfig.py seed-admins USERDATA --name alice --name bob`. After:
  `printf 'alice\nbob\n' | sbconfig.py seed-admins USERDATA`. This is a
  sibling-facing entry point (`docs/THREAT_MODEL.md` names it as one), so a
  harness calling it directly has to change its call. An argument is readable
  through `/proc/<pid>/cmdline` by every account on the host for as long as the
  process lives, so the seeding path published the player names a server
  admits. The refusal is deliberate: a caller still passing `--name` fails
  loudly instead of seeding nothing.
- `instance.env` is written with its values quoted (`KEY='value'`), the shape
  `sb env` already printed. Both documented consumers resolve that file with a
  shell (`eval "$(sb env <name>)"`, `source instances/<name>/instance.env`), so
  neither is affected, and `sb` reads a hand-edited bare value back
  (`env_value` takes the quotes off). A harness that parses the file with its
  own line splitter has to strip the quotes. A bare value is a value that
  consumer re-splits: the stock `Proton - Experimental` path assigned the
  prefix and then ran `-` as a command, and a path carrying a newline wrote a
  second line the sourcing shell executed.
- One home per default. `SB_DEFAULT_RES` and `SB_DEFAULT_FULLSCREEN` are
  declared once at the top of `sb`: the window defaults were written down twice
  (`sb create` recorded them, `sb launch` fell back to a private copy). A
  second copy of a default is a second answer to the same question.
- The property-key charset has one predicate, `prop_key_ok`. The two spellings
  it replaced disagreed about the leading underscore, and the one `validate_prop`
  does not use was called by nothing.
- The process scan behind `sb list`, `sb status`, `sb stop`, `sb wipe` and
  `sb destroy` reads every `/proc/<pid>/environ` in one `grep -z` pass instead
  of a `tr | grep` pair per process, and `sb list` asks for every instance's
  marker in that one pass rather than rescanning per row. Measured on a host
  with 1044 processes: 1.59s per instance scan before, 30ms for all of them.
- `sb render-config` drops every replaced declaration in one pass over
  `instance.props` rather than one `awk`/append/rename per property, and
  validates every key before writing anything, so a refused key no longer
  leaves the earlier ones applied.
- Reading a declared value out of `instance.env` uses the shell's own read
  loop rather than a `sed | head` pair per lookup, and `sb env` quotes each
  value into a variable rather than through a command substitution per line.
- CI installs a version-pinned ruff through `astral-sh/setup-uv` (pinned to a
  commit, like the checkout above it) and then runs the same `make check test`
  contributors run. Both analyzers are now required in CI: `make check` fails
  rather than skipping when shellcheck or ruff is missing. A test gate's
  shebang matches its executable bit.
- `write_local_platform` and `write_server_platform` were two copies of one
  three-line file differing in a single line; they are one `write_platform`
  with the platform as its second argument.
- `sb` lost three functions with no caller: `env_value` (a byte-identical
  second copy of `instance_env_value`), `require_env_value`, and `emit_env`
  (whose only caller-facing helper, `shell_quote`, was itself a byte-identical
  second copy of `shquote`).

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
