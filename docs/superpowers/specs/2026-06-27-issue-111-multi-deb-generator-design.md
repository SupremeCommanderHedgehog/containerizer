# Issue #111 — Multi-deb / apt-source generator

Design doc for [#111](https://github.com/SupremeCommanderHedgehog/containerizer/issues/111).
Companion to #110 (entrypoint inference, merged as PR #112 / 669ff46).

## Problem

The trace side of `.deb` support (issues #99 and #103) is shipped: `containerizer build` accepts `--installer N.deb` (repeatable), `--apt-source LINE`, and `--apt-key FILE`, and traces install correctly inside the runner. The analyze and generate sides never picked up those inputs:

1. `PolicyImage.installer_path: str` is a single hardcoded path. Multi-deb policies cannot be expressed.
2. `containerfile.py` always emits `COPY ./installer /installer` + `RUN /installer`. For a `.deb` input that line cannot build at all (apt vs executable).
3. `apt_sources` and `apt_keys` have no representation in the policy and no rendering in the Containerfile — third-party repo dependencies cannot be reproduced in the final image.
4. Build orchestrator never stages the installer files into `final_dir/`, so even the existing executable-case `COPY ./installer …` line would fail against a real `podman build` (the current build smoke test uses a fake podman that hides this).

End-user impact: for any real-world `.deb` workload (UniFi, MongoDB, …), `containerizer build` cannot produce a runnable image without hand-writing the Containerfile.

## Out of scope

- `--apt-package NAME` CLI flag and `apt_packages` rendering. The field stays in the schema as `[]`; no new flag, no rendering. Tracked as future work.
- `podman build --build-context` mode (avoid copying large `.deb`s). Future optimization.
- Stability of `policy.json` as a public artifact. It lives under `.intermediates/`; the `schema_version` bump from 2 → 3 has no external consumers.
- Hand-editable Containerfiles surviving rerun. The renderer is authoritative on each run.

## Architecture

```
trace ──▶ analyze ──▶ generate ──▶ build orchestrator ──▶ podman build
 │           │            │              │
 │           │            │              └─ stages installers/ and apt-keys/
 │           │            │                 (and ./installer for executable case)
 │           │            │                 into final_dir/ from BuildConfig
 │           │            │
 │           │            └─ render_containerfile branches on
 │           │               policy.image.installer.kind  (no suffix sniffing)
 │           │
 │           └─ derive_policy reads new trace-dir markers
 │              INSTALLERS + APT_KEYS, builds discriminated
 │              InstallerSpec, propagates apt_sources/apt_keys
 │
 └─ trace runner writes
    /work/trace/INSTALLERS   (one basename per line, primary first)
    /work/trace/APT_KEYS     (one basename per line)
    (apt-sources.list already exists per #102)
```

### Key invariants

- `policy.json` is intermediate (under `.intermediates/`), so the `schema_version: 2 → 3` bump has no external consumers.
- Trace-side `.deb` mount paths stay as `/installer` (primary) + `/installer-NN.deb` (extras) — unchanged from #102. The trace runner just additionally writes basename markers.
- Discriminated union: `derive` decides `kind` once; `containerfile.py` only matches on `kind` (no suffix sniffing in the renderer).
- `apt_packages` stays `[]`; no CLI plumbing.

## Schema changes (`src/containerizer/analyze/schema.py`)

```python
class DebInstaller(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["deb"] = "deb"
    paths: list[str]   # absolute paths inside the image, e.g. "/tmp/foo.deb"

class ExecutableInstaller(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["executable"] = "executable"
    path: str          # absolute path inside the image, e.g. "/installer"

InstallerSpec = Annotated[
    DebInstaller | ExecutableInstaller,
    Field(discriminator="kind"),
]

class PolicyImage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base: str
    installer: InstallerSpec           # replaces installer_path: str
    apt_sources: list[str] = []        # verbatim "deb ..." lines (new)
    apt_keys: list[str] = []           # basenames only, e.g. "mongodb.gpg" (new)
    apt_packages: list[str] = []       # unchanged; still always []
    post_install_cleanup: list[str]
    systemd_required: bool
    entrypoint: list[str]

class PolicyJson(BaseModel):
    schema_version: Literal[3] = 3     # bumped from 2
    image: PolicyImage
    runtime: PolicyRuntime
    warnings: list[str] = []
```

`apt_keys` carries basenames (not host paths) because the policy is a contract between derive and the renderer; the renderer only needs the names that will appear under `final_dir/apt-keys/`.

## Trace runner changes (`src/containerizer/trace/runner.py`)

Two new marker materializers, called from `TraceRunner.run()` alongside the existing `_materialize_apt_sources_file()` and `_materialize_start_cmd_file()`:

```python
def _materialize_installers_file(self) -> None:
    """One basename per line; primary first, then extras in order."""
    if self.installer is None:
        return  # verify mode
    target = self.output_dir / "INSTALLERS"
    lines = [self.installer.name] + [p.name for p in self.extra_installers]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")

def _materialize_apt_keys_file(self) -> None:
    if not self.apt_keys:
        return
    target = self.output_dir / "APT_KEYS"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(k.name for k in self.apt_keys) + "\n", encoding="utf-8")
```

These run only in install mode (verify mode has `installer=None` and the existing `__post_init__` rejects extras/keys/start-cmd).

## Reader + derive changes

### Reader (`src/containerizer/analyze/reader.py`)

Add a sibling helper `read_install_inputs(trace_dir: Path) -> InstallInputs` that reads the marker files and returns an immutable dataclass. `read_trace_dir` stays focused on event ingestion.

```python
@dataclass(frozen=True)
class InstallInputs:
    installers: tuple[str, ...] = ()    # basenames; empty when INSTALLERS file missing
    apt_sources: tuple[str, ...] = ()
    apt_keys: tuple[str, ...] = ()      # basenames

def read_install_inputs(trace_dir: Path) -> InstallInputs:
    installers = _read_lines(trace_dir / "INSTALLERS")
    apt_sources = _read_lines(trace_dir / "apt-sources.list")
    apt_keys = _read_lines(trace_dir / "APT_KEYS")
    return InstallInputs(
        installers=tuple(installers),
        apt_sources=tuple(apt_sources),
        apt_keys=tuple(apt_keys),
    )
```

`InstallInputs` is threaded separately into `derive_policy` so `TraceJson` stays purely about observed events. Both the build pipeline and `analyze_cmd` call `read_install_inputs(trace_dir)` — the trace-dir marker files are the single source of truth. The build pipeline does not derive `InstallInputs` from `BuildConfig` (avoids two-source-of-truth bugs).

### derive (`src/containerizer/analyze/derive.py`)

```python
def derive_policy(
    trace: TraceJson,
    *,
    install_inputs: InstallInputs | None = None,
    probe_base: str = "ubuntu:24.04",
    warnings: list[str] | None = None,
) -> PolicyJson:
    ...
    installer = _build_installer_spec(install_inputs)
    post_install_cleanup = _post_install_cleanup_for(installer)
    apt_sources = list(install_inputs.apt_sources) if install_inputs else []
    apt_keys = list(install_inputs.apt_keys) if install_inputs else []
    ...

def _build_installer_spec(install_inputs: InstallInputs | None) -> InstallerSpec:
    if install_inputs is None or not install_inputs.installers:
        # Legacy / no markers found — preserves today's behavior for old trace dirs.
        return ExecutableInstaller(path="/installer")
    primary, *extras = install_inputs.installers
    if primary.endswith(".deb"):
        # CLI's _validate_multi_deb_flags already enforces "all extras are .deb".
        paths = [f"/tmp/{name}" for name in install_inputs.installers]
        return DebInstaller(paths=paths)
    return ExecutableInstaller(path="/installer")

def _post_install_cleanup_for(installer: InstallerSpec) -> list[str]:
    if isinstance(installer, DebInstaller):
        return ["/tmp/*.deb", "/var/lib/apt/lists/*", "/var/cache/apt/archives/*"]
    return ["/var/cache/apt/archives/*", "/installer"]
```

Decision rule:
- All-or-nothing on `.deb`: if primary is `.deb`, all extras must be `.deb` (CLI already enforces this via `_validate_multi_deb_flags`).
- `/tmp/<basename>` for image-side `.deb` paths.
- Missing INSTALLERS file → legacy single-executable shape (so old trace dirs and existing unit-test fixtures don't break).

## Renderer (`src/containerizer/generate/containerfile.py`)

Dispatch on `kind`:

```python
def render_containerfile(policy: PolicyJson) -> str:
    if isinstance(policy.image.installer, DebInstaller):
        return _render_deb(policy)
    return _render_executable(policy)
```

### Executable case (unchanged)

```dockerfile
FROM ubuntu:24.04

COPY ./installer /installer

RUN /installer \
 && rm -rf /var/cache/apt/archives/* \
 && rm -rf /installer

ENTRYPOINT ["bash","-c","..."]
```

### Deb case (new)

```dockerfile
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive

COPY ./apt-keys/mongodb.gpg /etc/apt/keyrings/mongodb.gpg

RUN install -d /etc/apt/sources.list.d \
 && cat > /etc/apt/sources.list.d/containerizer.list <<'EOF'
deb [signed-by=/etc/apt/keyrings/mongodb.gpg] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse
EOF

COPY ./installers/unifi_sysvinit_all.deb /tmp/unifi_sysvinit_all.deb
COPY ./installers/mongodb-org-server_8.0.26_amd64.deb /tmp/mongodb-org-server_8.0.26_amd64.deb

RUN set -eux \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      /tmp/unifi_sysvinit_all.deb \
      /tmp/mongodb-org-server_8.0.26_amd64.deb \
 && rm -rf /tmp/*.deb /var/lib/apt/lists/* /var/cache/apt/archives/*

ENTRYPOINT ["bash","-c","..."]
```

Choices baked in:
- Order: apt-keys → sources → COPY `.deb`s → single `apt-get update && install` RUN. Standard pattern; one RUN avoids stale-cache layers.
- Heredoc for the sources file with single-quoted `'EOF'` so the verbatim `deb …` line isn't shell-expanded.
- `signed-by=` is the user's responsibility — sources are passed verbatim from `--apt-source`.
- No `apt_keys` ⇒ no key COPY block. No `apt_sources` ⇒ no sources block.
- `--no-install-recommends` for smaller images.
- Cleanup paths come from `policy.image.post_install_cleanup`.
- Entrypoint logic unchanged from #110.

## Build orchestrator (`src/containerizer/build/pipeline.py`)

A new `_stage_install_inputs` helper runs between the generate and podman-build phases:

```python
def _stage_install_inputs(
    *,
    final_dir: Path,
    installer: Path,
    extra_installers: tuple[Path, ...],
    apt_keys: tuple[Path, ...],
) -> None:
    """Copy installer files and apt-keys into final_dir so the Containerfile's
    COPY lines resolve during podman build."""
    if installer.suffix == ".deb" or extra_installers:
        installers_dir = final_dir / "installers"
        installers_dir.mkdir(exist_ok=True)
        shutil.copy2(installer, installers_dir / installer.name)
        for extra in extra_installers:
            shutil.copy2(extra, installers_dir / extra.name)
    else:
        # Executable case — Containerfile uses COPY ./installer /installer
        shutil.copy2(installer, final_dir / "installer")

    if apt_keys:
        keys_dir = final_dir / "apt-keys"
        keys_dir.mkdir(exist_ok=True)
        for key in apt_keys:
            shutil.copy2(key, keys_dir / key.name)
```

Called from `run_pipeline` right after `generate_fn` and before `podman_build_fn`.

`PathLayout` may grow two computed-property fields for clarity (`final_installers_dir`, `final_apt_keys_dir`) but the dataclass shape doesn't need to change.

## Tests

All Windows-runnable except where noted. Test pyramid:

**`tests/unit/generate/test_containerfile.py`**
- `test_render_executable_unchanged` — golden assertion that today's shape still emits for `ExecutableInstaller`.
- `test_render_deb_single` — one `.deb`, no apt-sources, no apt-keys.
- `test_render_deb_multi_with_apt_source_and_key` — UniFi+MongoDB-style scenario, full shape.
- `test_render_deb_apt_source_without_key` — sources only, no keys.
- `test_render_deb_apt_key_without_source` — keys only, no sources (degenerate but allowed).
- Inline golden Containerfile strings.

**`tests/unit/analyze/test_derive.py`**
- `test_derive_installer_executable_default` — no INSTALLERS → `ExecutableInstaller(path="/installer")`.
- `test_derive_installer_deb_single`
- `test_derive_installer_deb_multi`
- `test_derive_apt_sources_propagated`
- `test_derive_apt_keys_propagated_as_basenames`
- `test_derive_post_install_cleanup_for_deb` — `/tmp/*.deb` and apt lists.
- `test_derive_post_install_cleanup_for_executable` — unchanged.

**`tests/unit/analyze/test_schema.py`**
- Roundtrip JSON of `PolicyJson` with each installer kind.
- `extra="forbid"` rejects `installer_path` (it's gone from the schema).

**`tests/unit/analyze/test_reader.py`**
- INSTALLERS / APT_KEYS files present → `InstallInputs` populated.
- Files absent → empty `InstallInputs`.

**`tests/unit/trace/test_runner.py`**
- `_materialize_installers_file` writes primary first, then extras.
- `_materialize_apt_keys_file` writes basenames; no-op when empty.
- Verify mode does not write either file.

**`tests/unit/build/test_pipeline.py`**
- `_stage_install_inputs` copies `.deb`s into `installers/` and keys into `apt-keys/`.
- Executable installer copies to `final_dir/installer`.
- No-op when no apt-keys present.

**Integration**
- Existing `tests/integration/build/test_build_deb.py` and `tests/integration/trace/test_deb_pipeline.py` already exercise the `.deb` path; they'll pick up the new behavior automatically since they go through `BuildConfig`. They run on the CI BPF-capable runner; Windows skips them.

## CI gate

Per containerizer pre-commit policy (see memory): `ruff format --check .` + `ruff check .` + `pytest tests/` must pass before commit. All three runnable on Windows for the unit tier; integration tier may skip locally and run on CI.

## Risks / open questions

- **Schema break for existing intermediate `policy.json` files on disk.** Anyone with a `.intermediates/analyze/policy.json` from a previous run won't be able to load it with the new schema. Mitigation: intermediates are throwaway by design; the build pipeline regenerates them. No user action required beyond rerunning `containerizer build`.
- **`apt-get update` failure when third-party repos are present without `signed-by=`.** Modern apt rejects unsigned repos. We pass user-supplied source lines verbatim; if the user forgets `[signed-by=…]` the build fails with apt's error. Documented behavior, not a bug, but worth a sentence in README.
- **Image-size regression vs. hand-written Containerfile.** Our generated RUN combines update+install+cleanup; should be similar or slightly larger than hand-tuned. Acceptable.
