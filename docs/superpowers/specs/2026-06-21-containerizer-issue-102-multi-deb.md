# Issue #102 — Multi-`.deb` input + third-party apt sources

**Date:** 2026-06-21
**Status:** Draft (brainstorming)
**Parent spec:** [`2026-06-06-containerizer-design.md`](./2026-06-06-containerizer-design.md)
**Prior milestone specs:** [`2026-06-20-containerizer-issue-99-deb-support.md`](./2026-06-20-containerizer-issue-99-deb-support.md)
**Issue:** [#102](https://github.com/SupremeCommanderHedgehog/containerizer/issues/102)

## 1. Overview

PR #100 shipped `.deb` support end-to-end (Issue #99). The orchestrator's `run_deb_install` mounts a single deb at `/installer.deb` inside a nested `ubuntu:24.04` container and runs `apt-get install`. Real-world packages frequently violate that single-deb assumption in two complementary ways:

1. **Third-party-repo `Depends`.** UniFi 10.4.57 declares `Depends: mongodb-server | mongodb-10gen | mongodb-org-server` — none of which exist in Ubuntu 24.04's default repos. `mongodb-server` was dropped from `main` after the SSPL relicense; `mongodb-org-server` lives in `repo.mongodb.org`. apt fails with `E: Unable to correct problems, you have held broken packages.` Reproduced 2026-06-21 against `unifi_sysvinit_all.deb` + a `sleep infinity` ubuntu:24.04 container.
2. **User-supplied dep debs.** The same UniFi case: if the user has the dep deb locally (e.g. `mongodb-org-server_8.0.x_amd64.deb`), apt can satisfy UniFi's constraint *as long as both debs are visible in the same apt transaction*. Separate-container installs do not work — apt scopes its package universe per process.

This spec adds two complementary knobs to `containerizer build` (and `trace`) so both cases unblock without breaking the existing single-deb path:

- `--installer <path>` (repeatable): extra local debs installed in the same apt transaction as the primary.
- `--apt-source '<deb line>'` (repeatable) + `--apt-key <path>` (repeatable): apt source lines and keyring files made available to `apt-get update` inside the nested container.

After this change, the UniFi flow becomes:

```pwsh
containerizer build .\unifi_sysvinit_all.deb `
    --name unifi `
    --installer .\mongodb-org-server_8.0.x.deb
```

or (for the apt-source path):

```pwsh
containerizer build .\unifi_sysvinit_all.deb `
    --name unifi `
    --apt-source 'deb [signed-by=/etc/apt/keyrings/mongo.gpg] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse' `
    --apt-key .\mongo-server-8.0.gpg
```

## 2. Scope

### In this change

- `src/containerizer/trace/runner.py` — `TraceRunner` gains `extra_installers: tuple[Path, ...]`, `apt_sources: tuple[str, ...]`, `apt_keys: tuple[Path, ...]`. Install-mode argv mounts extras at `/installer-{i+1}.deb`, apt keys under `/work/apt-keys/`, and `TraceRunner.run()` writes apt sources to `output_dir/apt-sources.list` (one source per line). The output_dir is already bind-mounted at `/work/trace`, so the file is visible inside the runner at `/work/trace/apt-sources.list` without a new mount.
- `sandbox/runner_image/trace-orchestrator.sh` — `run_deb_install` gains an apt-source-prep step that runs before `apt-get update`. It writes `/etc/apt/sources.list.d/containerizer.list`, copies key files into `/etc/apt/keyrings/`, then runs apt update + install over `/installer.deb /installer-*.deb`.
- `src/containerizer/trace/cli.py` — `containerizer trace` gains `--installer`, `--apt-source`, `--apt-key` (all `multiple=True`). Mirrors the build CLI surface.
- `src/containerizer/build/cli.py` — `containerizer build` gains the same three flags. `BuildConfig` (in `build/types.py` or equivalent) gains the three new fields.
- `src/containerizer/build/pipeline.py` — `run_pipeline` threads the new fields through to `TraceRunner` for both the original and verify trace phases. Verify mode does NOT receive extras (verify has no apt install; it loads the generated image tarball instead).
- `src/containerizer/generate/readme.py` (or wherever README rendering lives) — new "Install inputs" section lists primary + extras + apt sources, so future readers know what went into the install transaction.
- Unit tests across `tests/unit/test_trace_runner.py`, `tests/unit/test_orchestrator_dispatch.py`, `tests/unit/test_build_cli.py` (extend or add).
- Integration tests: extend `tests/integration/trace/test_deb_pipeline.py` with a multi-deb fixture pair; add `tests/integration/trace/test_deb_apt_source.py` against a CI-local HTTP apt repo built via `dpkg-scanpackages` + `python3 -m http.server`.
- MANUAL.md scenarios 12 + 13 documenting real-world UniFi+MongoDB flows (both --installer and --apt-source paths).

### Carried unchanged

- `src/containerizer/probe/*` — probe still runs against the primary installer only. Extras are install-time inputs, not policy drivers. `DebProbe` schema unchanged.
- `src/containerizer/analyze/*` — kind-agnostic; consumes whatever the trace produced.
- `src/containerizer/generate/*` (except the README install-inputs section) — kind-agnostic.
- `src/containerizer/verify/*` — kind-agnostic.
- The `.deb` magic-bytes dispatch in `trace-orchestrator.sh` — only the primary needs to be a `.deb`. Extras land in `run_deb_install` because the primary did; they are not magic-byte checked individually (apt will surface a clear error if a user mislabels a non-deb).
- `sandbox/runner_image/Containerfile` — no image-build-time changes. The keyring directory `/etc/apt/keyrings/` exists in stock ubuntu:24.04 (since 22.04); we just write into it at runtime via `podman exec`.
- Single-installer invocations: `containerizer build foo.deb --name foo` and `containerizer trace foo.deb` continue to work byte-identically. New flags default to empty tuples.

### Out of scope (deferred)

- **Local `.deb` repo bootstrap.** Using `dpkg-scanpackages` to materialise a tiny local apt repo inside the install container is cleaner long-term but heavier for the common case (1-3 user-supplied debs). `apt-get install /a.deb /b.deb` works fine and is what dpkg + apt are designed for.
- **`Recommends:` / `Suggests:` install.** Stay with apt's default behaviour. A future `--no-install-recommends` flag is a tiny add when wanted.
- **URL fetching for `--installer` / `--apt-key`.** Users provide local files. If they want to pull from a URL they can `curl` it first.
- **Cross-arch extras.** All inputs must share architecture. Enforced at CLI parse time by reading each deb's control + Architecture field would be tidy, but a YAGNI: apt itself errors clearly enough.
- **Auto-generated `[signed-by=...]` injection.** Users must write `--apt-source 'deb [signed-by=/etc/apt/keyrings/foo.gpg] ...'` themselves. We do not parse the line and inject the key path. Keeps the CLI a thin shell over apt's existing semantics; no hidden magic.
- **`.rpm` siblings.** Issue #99's out-of-scope `.rpm` follow-up will mirror this design when it lands; not part of this PR.

## 3. Architecture

### 3.1 CLI surface (`src/containerizer/build/cli.py`, `src/containerizer/trace/cli.py`)

Both subcommands gain three identical Click options:

```python
@click.option(
    "--installer",
    "extra_installers",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Additional .deb file installed in the same apt transaction. "
         "Repeatable.",
)
@click.option(
    "--apt-source",
    "apt_sources",
    multiple=True,
    type=str,
    help="Verbatim line written to /etc/apt/sources.list.d/containerizer.list "
         "inside the nested container. Must start with 'deb ' or 'deb-src '. "
         "Repeatable.",
)
@click.option(
    "--apt-key",
    "apt_keys",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Local keyring file (.gpg or .asc) copied into /etc/apt/keyrings/ "
         "inside the nested container. Reference via [signed-by=...] in your "
         "--apt-source line. Repeatable.",
)
```

CLI-side validation in `build_cmd` / `trace_cmd` callbacks:

- `len(extra_installers) <= 99`. Otherwise `click.BadParameter("--installer cap is 99 extras")`. See §7 risk #2.
- Each `apt_source` must match `re.compile(r"^\s*deb(-src)?\s+")`. Otherwise `click.BadParameter("--apt-source must start with 'deb '")`.
- Each `apt_key` must end in `.gpg` or `.asc` (case-insensitive). Otherwise `click.BadParameter("--apt-key must end in .gpg or .asc")`.
- If `apt_sources` is non-empty and any line contains `[signed-by=` but `apt_keys` is empty, emit a `click.echo` warning (not an error — apt will catch it). Trade-off: don't be cleverer than apt at parsing the source line.

### 3.2 `TraceRunner` argv shape

`TraceRunner` (frozen dataclass) signature delta:

```python
@dataclass(frozen=True)
class TraceRunner:
    image_tag: str
    installer: Path | None
    output_dir: Path
    mode: Literal["install", "verify"] = "install"
    tty: bool = False

    # NEW in #102. Install-mode only; ignored in verify mode.
    extra_installers: tuple[Path, ...] = ()
    apt_sources: tuple[str, ...] = ()
    apt_keys: tuple[Path, ...] = ()

    # Verify-mode fields unchanged.
    verify_image_tar: Path | None = None
    verify_image_tag: str | None = None
    verify_run_flags: tuple[str, ...] = field(default_factory=tuple)
    verify_soak_seconds: int | None = None
    verify_seccomp_path: Path | None = None
```

`__post_init__` checks: if `mode == "verify"` and any of `extra_installers`/`apt_sources`/`apt_keys` are non-empty, raise `ValueError("verify mode does not accept extra installers or apt sources")`.

Install-mode argv additions (conceptual diff):

```diff
 podman run --rm -i -t --privileged --systemd=always
 -v /sys/kernel/debug:/sys/kernel/debug
 ...
 -v <primary>:/installer:ro
 -v <output_dir>:/work/trace
+-v <extra_installers[0]>:/installer-01.deb:ro
+-v <extra_installers[1]>:/installer-02.deb:ro
+...
+-v <apt_keys[0]>:/work/apt-keys/<basename>:ro
+-v <apt_keys[1]>:/work/apt-keys/<basename>:ro
+...
 -e CONTAINERIZER_MODE=install
 -e CONTAINERIZER_INSTALLER=/installer
 -e CONTAINERIZER_INTERACTIVE=...
 <runner-image-tag>
```

apt sources transport: `TraceRunner.run()` writes the apt source lines (one per line, newline-terminated) to `output_dir/apt-sources.list` before exec'ing podman. Since `output_dir` is already bind-mounted at `/work/trace` inside the runner, the file appears at `/work/trace/apt-sources.list` with no new mount needed. The orchestrator simply `cp -f`s it into `/etc/apt/sources.list.d/containerizer.list` when present. File transport sidesteps the POSIX env-var NUL-truncation trap (env vars are NUL-terminated C strings, so multi-source NUL-packed env vars get silently truncated at the first NUL byte).

`/work/apt-keys/` is bind-mounted at the directory level (one mount per key, basename preserved) rather than copying keys at runner-image build time. Keeps the runner image stateless across users.

### 3.3 Orchestrator changes (`sandbox/runner_image/trace-orchestrator.sh`)

`run_deb_install` gains a prep step between `podman run -d` (nested container start) and `podman exec` (apt install). Pseudocode:

```bash
run_deb_install() {
    # ... existing podman pull + podman run -d --rm --name deb-install ... sleep infinity ...
    # ... existing trap extension for INT/TERM ...

    # NEW: apt source + key prep. Runs only if at least one source or key
    # was passed. Touches /etc/apt/sources.list.d/ and /etc/apt/keyrings/
    # inside the nested container; both directories exist in stock
    # ubuntu:24.04.
    podman exec deb-install bash -c '
        set -e
        install -d /etc/apt/keyrings /etc/apt/sources.list.d
        # Copy keyrings shipped via -v /work/apt-keys/<basename>.
        if [ -d /work/apt-keys ]; then
            for key in /work/apt-keys/*; do
                [ -e "$key" ] || continue
                cp -f "$key" "/etc/apt/keyrings/$(basename "$key")"
            done
        fi
        # Copy apt-sources from the file the host CLI wrote to output_dir.
        if [ -e /work/trace/apt-sources.list ]; then
            cp -f /work/trace/apt-sources.list /etc/apt/sources.list.d/containerizer.list
        fi
    ' > "$TRACE_DIR/apt-prep.log" 2>&1

    # Existing apt update + install, now over both primary and extras.
    # `shopt -s nullglob` so /installer-??.deb collapses to empty when no
    # extras were mounted. Zero-padded glob (??) keeps alphabetical order
    # stable up to 99 extras (CLI caps at 99 to match).
    install_rc=0
    podman exec deb-install bash -c '
        shopt -s nullglob
        export DEBIAN_FRONTEND=noninteractive
        apt-get update &&
        apt-get install -y /installer.deb /installer-??.deb
    ' > "$TRACE_DIR/install.log" 2>&1 || install_rc=$?

    # ... existing PHASE_MARKER + interactive/non-interactive finalise ...
}
```

The `/installer-??.deb` glob (two question marks = exactly two characters; matches zero-padded `01`..`99`) expands inside bash before apt sees it. `shopt -s nullglob` collapses it to empty when nothing matches. Zero-padding keeps glob expansion alphabetically stable up to 99 extras — `*` ordering would interleave `installer-10.deb` before `installer-2.deb`, which would break determinism if anyone ever depended on install order.

Diagnostic dump (`deb-debug.log`) gains a section dumping `/etc/apt/sources.list.d/containerizer.list` and `ls /etc/apt/keyrings/` so failures of the prep step are inspectable in the CI failure-artifact.

### 3.4 README "Install inputs" section

`generate/readme.py` (or wherever the README template lives) gains a new section right after the existing audit trail:

```markdown
## Install inputs

Primary installer:
- `unifi_sysvinit_all.deb` (10.4.57-34628-1, amd64)

Additional installers:
- `mongodb-org-server_8.0.7_amd64.deb` (3.2 MB)

apt sources:
- `deb [signed-by=/etc/apt/keyrings/mongo.gpg] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse`
```

If any of the three buckets is empty, omit that subsection. If all three are empty (single-installer, no extras), omit the whole section so existing single-deb output stays byte-identical.

apt-source lines are rendered with their `[bracketed-options]` stripped (so the README doesn't leak `[trusted=yes]` from test fixtures or `[signed-by=...]` paths into a published document where they could be cargo-culted). This keeps the README focused on *what* repo was added, not *how* it was signed.

### 3.5 Where the new fields flow

```
containerizer build foo.deb --installer dep.deb --apt-source 'deb ...' --apt-key key.gpg --name x
        │
        ▼
build/cli.py: builds BuildConfig{installer, extra_installers, apt_sources, apt_keys, ...}
        │
        ▼
build/pipeline.py: passes them to TraceRunner(mode="install") for the ORIGINAL trace
        │
        ▼
trace/runner.py: argv adds extra -v mounts + CONTAINERIZER_APT_SOURCES env
        │
        ▼
trace-orchestrator.sh / run_deb_install: prep step + install over /installer.deb /installer-*.deb
        │
        ▼
analyze, generate, verify: kind-agnostic, consume trace output unchanged
        │
        ▼
README "Install inputs" section: rendered from BuildConfig (not from the trace).
```

Verify mode receives nothing extra — its `TraceRunner` invocation does not set `extra_installers` / `apt_sources` / `apt_keys`. The verify-mode workload loads the generated image tarball and exercises it; apt is not involved.

## 4. Lifecycle

End-to-end install flow with one primary + one extra + one apt source + one key:

1. Host: `containerizer build .\unifi.deb --installer .\mongo.deb --apt-source 'deb [signed-by=/etc/apt/keyrings/m.gpg] https://r/ubuntu noble/mo/8.0 multiverse' --apt-key .\m.gpg --name unifi`.
2. Host CLI: probes `unifi.deb` (primary only). Builds `BuildConfig` with the four new bundles populated.
3. Host pipeline: `TraceRunner(mode="install", installer=unifi.deb, extra_installers=(mongo.deb,), apt_sources=("deb ...",), apt_keys=(m.gpg,)).run()`.
4. Host: `podman run --rm -it --privileged --systemd=always ... -v unifi.deb:/installer:ro -v mongo.deb:/installer-1.deb:ro -v m.gpg:/work/apt-keys/m.gpg:ro -e CONTAINERIZER_APT_SOURCES='<one source>' <runner>`.
5. Inside runner: systemd boots, env-publisher unit exports `CONTAINERIZER_APT_SOURCES`, orchestrator starts as a oneshot.
6. Inside runner: collectors launch, grace period, fallback detection.
7. Inside runner: `_detect_kind /installer` → `deb` → `run_deb_install`.
8. Inside runner: `podman pull`, `podman run -d ... sleep infinity` with `-v /installer:/installer.deb:ro -v /installer-1.deb:/installer-1.deb:ro -v /work/apt-keys/m.gpg:/work/apt-keys/m.gpg:ro -e CONTAINERIZER_APT_SOURCES=...`.
9. Inside nested ubuntu: apt-prep `podman exec` copies `/work/apt-keys/m.gpg` → `/etc/apt/keyrings/m.gpg`, writes `/etc/apt/sources.list.d/containerizer.list` with the supplied `deb` line.
10. Inside nested ubuntu: apt-install `podman exec` runs `apt-get update` (now sees both archive.ubuntu.com and repo.mongodb.org) then `apt-get install -y /installer.deb /installer-1.deb`. Both packages install in one transaction; apt resolves UniFi's `Depends: mongodb-org-server` against the mounted local mongo deb.
11. Inside runner: PHASE_MARKER written. Non-interactive path finalises immediately (CI). Interactive path waits for user Enter.
12. Inside runner: orchestrator stops `deb-install`, finalises COMPLETE marker, exits.
13. Host: analyze parses runtime events (install activity is on the install side of PHASE_MARKER, excluded from policy). Generate produces seccomp.json + README.md (Containerfile if entrypoint inferred). README has the new "Install inputs" section listing both debs and the apt source.

## 5. Failure modes

| Failure | Behavior |
|---|---|
| `--installer foo` where foo doesn't exist | Click's `type=click.Path(exists=True)` rejects at parse. Clear `Error: Invalid value for '--installer': Path 'foo' does not exist.` |
| `--apt-source 'apt-get install foo'` (malformed) | CLI callback rejects with `click.BadParameter("--apt-source must start with 'deb '")` |
| `--apt-source 'deb [signed-by=...]'` without `--apt-key` | Warning printed but not error. apt will fail at update time; install.log surfaces the real cause. |
| Extra installer is not actually a .deb (user mislabelled) | apt-install errors with `E: Unsupported file ...`; install_rc=100; PARTIAL marker; install.log makes it obvious. |
| `apt-get update` fails (bad source URL) | install_rc!=0 captured by the `|| install_rc=$?` pattern. install.log shows the exact apt error. Pre-existing failure path. |
| Keyring file is corrupt / wrong format | apt-get update warns "GPG error" then refuses to update that repo. install.log surfaces. |
| Glob `/installer-*.deb` expands to nothing (no extras) | `shopt -s nullglob` collapses to empty. apt-get install runs over just `/installer.deb`. Equivalent to current single-deb behaviour. |
| Two extras with the same basename in `--apt-key` (user error) | Second `-v` mount overwrites the first inside the nested container. We do not deduplicate at the CLI level; mount semantics are the visible contract. Documented in `--apt-key` help text. |

## 6. Testing

### 6.1 Unit tests (Python)

`tests/unit/test_trace_runner.py`:

- Install argv contains `-v <extra>:/installer-1.deb:ro` for each extra in order.
- Install argv contains `-v <key>:/work/apt-keys/<basename>:ro` for each key.
- Install argv contains `-e CONTAINERIZER_APT_SOURCES=<\x00-joined string>` when sources non-empty; absent (or empty value) when none.
- Verify mode raises `ValueError` if any of the new fields are non-empty.
- Single-installer invocation (no new flags) produces byte-identical argv to current.

`tests/unit/test_orchestrator_dispatch.py`:

- Extend `test_run_deb_install_invokes_expected_podman_argv` with extras + sources + keys. Assert recorded podman-stub calls include the keyring copy, sources.list write, and `apt-get install -y /installer.deb /installer-1.deb`.

`tests/unit/test_build_cli.py` (extend or create):

- `--installer` accepts repeated paths; validates existence.
- `--apt-source` rejects strings that don't start with `deb ` or `deb-src `.
- `--apt-key` rejects paths that don't end in `.gpg`/`.asc`.
- `--apt-source` with `[signed-by=...]` and no `--apt-key` emits a warning.

### 6.2 Integration tests

`tests/integration/trace/test_deb_pipeline.py` (extend):

- Existing single-deb test stays.
- New test: build two fixture debs (`primary_1.0.deb` that `Depends: tinydep`, and `tinydep_1.0.deb`). Run `containerizer trace primary.deb --installer tinydep.deb`. Assert COMPLETE marker + apt activity in install.log + install.log mentions both package names.

`tests/integration/trace/test_deb_apt_source.py` (new):

- CI sets up a local HTTP apt repo: `dpkg-scanpackages` over a directory containing one fake deb, served by `python3 -m http.server 0` on an ephemeral port read from the binding.
- Run `containerizer trace primary.deb --apt-source "deb [trusted=yes] http://127.0.0.1:<port>/ ./ /"`.
- Assert COMPLETE + apt-prep.log shows the sources.list line + install.log mentions the local-fake package fetch.
- Uses `[trusted=yes]` to skip GPG verification — the goal is to test the orchestrator's source-injection contract, not to validate GPG itself.

`tests/integration/trace/test_deb_apt_key.py` (new):

- Generate a throwaway GPG key in CI, write to a `.gpg` file.
- Run `containerizer trace primary.deb --apt-key <gpg> --apt-source "deb [signed-by=/etc/apt/keyrings/<basename>] http://127.0.0.1:<port>/ ./ /"`.
- Assert apt-prep.log shows the `cp -f` of the keyring + `ls /etc/apt/keyrings/` includes the basename.
- Does NOT assert successful repo signature verification — that requires `apt-secure(8)` interactions we'd rather not pin to.

### 6.3 CI integration

- Existing `trace-integration.yml` already exercises `tests/integration/trace/`; new tests are auto-discovered. No workflow changes needed.
- Workflow's debug-dump file list already covers `apt-prep.log` because it dumps `$TRACE_DIR/*.log` — verify the wildcard expands. If not, extend the list.

### 6.4 Manual / docs

- MANUAL.md scenario 12: real UniFi (10.4.x sysvinit) + `mongodb-org-server_8.0.x_amd64.deb` end-to-end via `--installer`. Captures install.log success + README's "Install inputs" section.
- MANUAL.md scenario 13: real UniFi + `--apt-source` against `repo.mongodb.org` (signed). User downloads the MongoDB GPG key, passes it via `--apt-key`. Documents the real-world third-party-repo flow.

## 7. Known risks

1. **File transport: no separator escaping needed.** Earlier drafts proposed a NUL-separated `CONTAINERIZER_APT_SOURCES` env var, but POSIX env-var values are NUL-terminated C strings — `execve(2)` truncates at the first NUL byte, so multi-source input silently lost everything after the first line. Switched to a file written by `TraceRunner.run()` to `output_dir/apt-sources.list` (mounted into the runner at `/work/trace/apt-sources.list`); the orchestrator just `cp -f`s it. One source per line, newline-terminated. No in-band separator, no escaping, no truncation surface.
2. **Glob ordering vs determinism.** Already addressed in §3.2 + §3.3: extras mount as zero-padded `/installer-01.deb`..`/installer-99.deb`, glob is `/installer-??.deb`. CLI caps `--installer` at 99 occurrences and rejects past that with a clear error.
3. **Keyring filename collisions across distinct users.** If two `--apt-key` paths resolve to the same basename (`key.gpg` + `subdir/key.gpg`), the second mount silently shadows the first. Mitigated by the documented CLI contract (basename is the visible name). If a future user trips on it we add a `-d` per-source-prefixed mountpath.
4. **`[trusted=yes]` in tests creates a habit.** Integration tests use `[trusted=yes]` for repo-mock simplicity. The README renders apt-source lines with brackets stripped (see §3.4 last paragraph), so no `[trusted=yes]` ever lands in user-facing output. MANUAL.md scenarios 12 + 13 explicitly use `[signed-by=...]` only.
5. **`apt-prep.log` size on busy traces.** The prep step writes a small log, but if a future change adds more diagnostic output it could grow. Mitigated by the existing 4000-char `head` in the workflow dump. Not blocking.
6. **Existing diagnostics dump path (`deb-debug.log`) only catches `podman run -d` state.** If the apt-prep `podman exec` itself fails (very rare — it only touches `/etc/apt/keyrings` and `sources.list.d`), the failure lands in `apt-prep.log` but the dump doesn't include a fresh `podman inspect`. Mitigation: extend `deb-debug.log` to also dump after apt-prep. Cheap; bundled into the §3.3 changes.

## 8. Open questions

None blocking. The four clarifying questions answered during brainstorming locked the architecture:

1. Scope = multi-deb + `--apt-source` + `--apt-key` together, one PR. **Locked.**
2. CLI = positional primary + repeated `--installer`. **Locked.**
3. Repo support = `--apt-source` + `--apt-key`, both repeatable. **Locked.**
4. Testing = unit (orchestrator-stub) + CI-local HTTP apt repo for integration. **Locked.**

## 9. Implementation phasing

The plan (separate doc, generated by `superpowers:writing-plans`) will expand these into TDD tasks:

- **Phase 1** — `TraceRunner` field additions + argv changes + unit tests. Pure Python, fast, no orchestrator dependency.
- **Phase 2** — `containerizer trace` CLI flags (per-phase command surface), wired into `TraceRunner`. Smaller surface, easier review than wiring `build` first.
- **Phase 3** — `containerizer build` CLI flags + `BuildConfig` fields + pipeline plumbing.
- **Phase 4** — `trace-orchestrator.sh` apt-prep step + glob/nullglob fix. Unit-test the new shell with the existing podman-stub harness.
- **Phase 5** — README "Install inputs" section.
- **Phase 6** — Integration tests (multi-deb, --apt-source, --apt-key) + CI wiring (auto-discovered).
- **Phase 7** — MANUAL.md scenarios 12 + 13.

## 10. Spec / PR shape

- This spec ships as a docs-only PR (matches the issue-99 pattern), alongside the implementation plan written by `superpowers:writing-plans`.
- Implementation PR follows. Recommended shape: one signed commit per phase 1-6, plus a docs commit for scenarios 12+13.
- Gate on `trace-integration` CI green before merging.
- All commits signed with key `BE707B220C995478`, author `github.v5f9w@bitbucket.onl`.
