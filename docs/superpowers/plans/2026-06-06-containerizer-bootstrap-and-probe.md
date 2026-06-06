# Containerizer Bootstrap and ELF Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `SupremeCommanderHedgehog/containerizer` private repo with full GitHub automation (CI, Dependabot, release-please, CodeQL, Projects v2, issue forms, branch protection) and ship a working `containerizer probe` command that statically analyses Linux ELF installers and emits a typed `probe.json` with a base-image suggestion.

**Architecture:** Python 3.11+ package built with hatchling, Click-based CLI, Pydantic v2 typed models, pyelftools for ELF parsing. Repo bootstrap commits happen on `main` locally and are pushed before branch protection is enabled. Feature work (the ELF probe) happens on a branch and lands via PR through protected `main`, exercising CI and release-please end-to-end.

**Tech Stack:** Python 3.11+, Click, Pydantic v2, pyelftools, hatchling, ruff, mypy, pytest. GitHub Actions, Dependabot, googleapis/release-please-action, github/codeql-action. `gh` CLI for repo + project setup.

---

## Conventions used throughout

- **Working directory:** all commands assume `C:\Users\yizshachuck\source\containerizer\` is the cwd. Use absolute paths in tools (Read/Edit/Write); use relative paths in shell commands.
- **Commit signing.** Every commit MUST be signed per the user's global `CLAUDE.md`. The canonical form is:
  ```
  git -c user.signingkey=BE707B220C995478 commit -S -m "<message>"
  ```
  `user.name` and `user.email` are already set globally; do NOT override them. NEVER pass `--no-gpg-sign`.
- **Commit messages.** Conventional Commits format (`feat:`, `fix:`, `chore:`, `docs:`, `ci:`, `build:`, `test:`). release-please reads these once the workflow is in place.
- **Line endings.** The user is on Windows; the local repo will see CRLF warnings. They are benign — git stores LF.
- **DO NOT push to `main` directly after Task 14.** From Task 15 onward all changes go through a feature branch + PR.
- **Each task ends with a green test + a signed commit.** Do not batch.

---

## File map

Files created or modified by this plan:

| Path | Purpose | Task |
|------|---------|------|
| `pyproject.toml` | Python package + tool config (ruff, mypy, pytest) | 2 |
| `src/containerizer/__init__.py` | Package version | 2 |
| `src/containerizer/__main__.py` | `python -m containerizer` entry | 2 |
| `src/containerizer/cli.py` | Click CLI group + subcommands | 2, 16 |
| `tests/__init__.py` | Test package marker | 3 |
| `tests/conftest.py` | Shared fixtures (fixtures dir path) | 3 |
| `tests/unit/test_smoke.py` | Initial passing smoke test | 3 |
| `README.md` | Project overview + quickstart | 4, 17 |
| `LICENSE` | Apache-2.0 text | 4 |
| `SECURITY.md` | Vulnerability disclosure | 4 |
| `CODEOWNERS` | `* @SupremeCommanderHedgehog` | 4 |
| `.github/dependabot.yml` | Weekly grouped updates for pip + actions + docker | 5 |
| `.github/workflows/ci.yml` | ruff + mypy + pytest on 3.11 + 3.12 | 6 |
| `.github/workflows/codeql.yml` | CodeQL Python analysis | 7 |
| `.github/workflows/release-please.yml` | Conventional-commit-driven releases | 8 |
| `release-please-config.json` | release-please configuration | 8 |
| `.release-please-manifest.json` | release-please version tracker | 8 |
| `.github/ISSUE_TEMPLATE/bug.yml` | Bug report form | 9 |
| `.github/ISSUE_TEMPLATE/feature.yml` | Feature request form | 9 |
| `.github/ISSUE_TEMPLATE/software-support.yml` | "Add support for software X" form | 9 |
| `.github/ISSUE_TEMPLATE/config.yml` | Disable blank issues | 9 |
| `src/containerizer/probe/__init__.py` | Probe subpackage marker | 10 |
| `src/containerizer/probe/schema.py` | Pydantic models for probe output | 10 |
| `tests/unit/test_probe_schema.py` | Schema model tests | 10 |
| `tests/fixtures/probe/elf-dynamic-x86_64` | Real ELF binary fixture | 11 |
| `src/containerizer/probe/elf.py` | ELF binary parser | 12, 13 |
| `tests/unit/test_probe_elf.py` | ELF parser tests | 12, 13 |
| `src/containerizer/probe/base_image.py` | Base-image suggestion | 14 |
| `tests/unit/test_probe_base_image.py` | Base-image tests | 14 |
| `src/containerizer/probe/installer.py` | Kind detection + dispatch | 15 |
| `tests/unit/test_probe_installer.py` | Dispatcher tests | 15 |
| `tests/integration/test_cli_probe.py` | End-to-end CLI test | 16 |

`README.md` is touched twice (Task 4 stub, Task 17 usage section).

---

## Task 1: Preflight checks

**Files:** none

- [ ] **Step 1: Verify `gh` CLI is installed and authenticated as the right user**

Run: `gh auth status`

Expected output contains `Logged in to github.com as SupremeCommanderHedgehog`. If not, STOP and have the user run `gh auth login` interactively themselves (`gh auth login` is interactive and cannot be driven by an agent). Required scopes: `repo`, `workflow`, `read:project`, `project`.

- [ ] **Step 2: Verify `podman` is installed and the machine is running**

Run: `podman version`, then `podman machine list`

Expected: a podman version is printed; at least one machine has `Running` status. If the machine is stopped, run `podman machine start` and re-check.

- [ ] **Step 3: Verify the GPG signing key is available**

Run: `gpg --list-secret-keys BE707B220C995478`

Expected: the key is listed with uid `Patrick Connallon (SupremeCommanderHedgehog) <github.v5f9w@bitbucket.onl>`. If absent, STOP — signing cannot proceed.

- [ ] **Step 4: Verify `git` identity**

Run: `git config --get user.name; git config --get user.email`

Expected: `SupremeCommanderHedgehog` and `github.v5f9w@bitbucket.onl`. If different, STOP and inform the user — do NOT modify their git config.

- [ ] **Step 5: Verify the repo state**

Run: `git status; git log --oneline -1`

Expected: clean working tree, one commit (`b6d5cea chore: initial commit with containerizer design spec`), branch `main`. If different, STOP and reconcile before proceeding.

There is no commit at the end of Task 1 — these are read-only checks.

---

## Task 2: Python package scaffold (`pyproject.toml`, package skeleton)

**Files:**
- Create: `pyproject.toml`
- Create: `src/containerizer/__init__.py`
- Create: `src/containerizer/__main__.py`
- Create: `src/containerizer/cli.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "containerizer"
version = "0.0.0"
description = "Trace-and-learn containerizer that turns Linux installers into hardened Podman containers."
readme = "README.md"
requires-python = ">=3.11"
license = "Apache-2.0"
license-files = ["LICENSE"]
authors = [{ name = "SupremeCommanderHedgehog" }]
dependencies = [
    "click>=8.1,<9",
    "pydantic>=2.5,<3",
    "pyelftools>=0.30",
]

[project.optional-dependencies]
dev = [
    "ruff>=0.4",
    "mypy>=1.9",
    "pytest>=8",
    "pytest-cov>=5",
]

[project.scripts]
containerizer = "containerizer.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/containerizer"]

[tool.ruff]
line-length = 100
target-version = "py311"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "RUF"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["B011"]

[tool.mypy]
python_version = "3.11"
strict = true
mypy_path = "src"
explicit_package_bases = true
namespace_packages = true

[[tool.mypy.overrides]]
module = ["elftools.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
```

- [ ] **Step 2: Create `src/containerizer/__init__.py`**

```python
"""Trace-and-learn containerizer."""

__version__ = "0.0.0"
```

- [ ] **Step 3: Create `src/containerizer/__main__.py`**

```python
from containerizer.cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create `src/containerizer/cli.py` (stub)**

```python
"""Containerizer CLI entry point."""

import click

from containerizer import __version__


@click.group()
@click.version_option(__version__, prog_name="containerizer")
def main() -> None:
    """Trace-and-learn containerizer."""


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Install the package locally and verify**

Run: `python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e ".[dev]"`

Then: `.\.venv\Scripts\python.exe -m containerizer --version`

Expected: `containerizer, version 0.0.0`

- [ ] **Step 6: Run lint and typecheck to confirm the scaffold is clean**

Run: `.\.venv\Scripts\python.exe -m ruff check src; .\.venv\Scripts\python.exe -m mypy src/containerizer`

Expected: both report no errors.

- [ ] **Step 7: Commit**

```
git -c user.signingkey=BE707B220C995478 commit -S -m "build: scaffold Python package and CLI entrypoint"
```

before which:

```
git add pyproject.toml src/containerizer/__init__.py src/containerizer/__main__.py src/containerizer/cli.py
```

---

## Task 3: Test scaffold

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/test_smoke.py`

- [ ] **Step 1: Create empty `tests/__init__.py` and `tests/unit/__init__.py`**

Both files are zero-byte markers. They must exist so pytest treats `tests` as a package.

- [ ] **Step 2: Create `tests/conftest.py`**

```python
"""Shared pytest fixtures."""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Directory containing test fixtures."""
    return Path(__file__).parent / "fixtures"
```

- [ ] **Step 3: Write a smoke test that imports the package**

`tests/unit/test_smoke.py`:

```python
"""Smoke test: package imports and CLI exposes a version."""

from click.testing import CliRunner

from containerizer import __version__
from containerizer.cli import main


def test_package_has_version() -> None:
    assert __version__ == "0.0.0"


def test_cli_version_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "containerizer, version 0.0.0" in result.output
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_smoke.py -v`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```
git add tests/__init__.py tests/conftest.py tests/unit/__init__.py tests/unit/test_smoke.py
git -c user.signingkey=BE707B220C995478 commit -S -m "test: add smoke tests for package import and CLI version flag"
```

---

## Task 4: Top-level metadata files (README, LICENSE, SECURITY, CODEOWNERS)

**Files:**
- Create: `README.md`
- Create: `LICENSE`
- Create: `SECURITY.md`
- Create: `CODEOWNERS`

- [ ] **Step 1: Download the verbatim Apache-2.0 text into `LICENSE`**

The Apache-2.0 license is ~11.4 KB of standardised text. Fetch it from the
canonical Apache site directly into the repo root:

```pwsh
Invoke-WebRequest -Uri "https://www.apache.org/licenses/LICENSE-2.0.txt" -OutFile LICENSE
```

Verify the file:

```pwsh
(Get-Item LICENSE).Length     # expect roughly 11400 bytes
Get-Content LICENSE -TotalCount 4
```

Expected first lines:

```
                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/
```

If the file is empty or the first lines don't match, STOP — `Invoke-WebRequest`
may have hit a proxy. Manually obtain the text from
`https://www.apache.org/licenses/LICENSE-2.0.txt` and save it.

No separate copyright line is appended — the license text's own APPENDIX block
is sufficient and matches what Kubernetes, hatchling, and most Apache-2.0
Python projects ship. A `NOTICE` file can be added later if the project ever
needs one.

- [ ] **Step 2: Create `README.md` (stub — fuller usage added in Task 17)**

```markdown
# containerizer

> Trace-and-learn tool that turns Linux installers into hardened Podman containers.

`containerizer` ingests a Linux software installer, runs it in an instrumented
sandbox, observes what files, ports, capabilities and syscalls the resulting
software actually uses, and emits a deny-by-default `Containerfile` plus a
systemd Quadlet unit whose exceptions are exactly those the trace observed and
nothing more.

**Status:** very early. See
[`docs/superpowers/specs/2026-06-06-containerizer-design.md`](docs/superpowers/specs/2026-06-06-containerizer-design.md)
for the design spec.

## Requirements

- Windows host with a running Podman machine (or any Linux host with Podman)
- Python 3.11+

## Install (development)

```pwsh
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## License

Apache-2.0 — see [LICENSE](LICENSE).
```

- [ ] **Step 3: Create `SECURITY.md`**

```markdown
# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities through GitHub's private vulnerability
reporting feature on this repository:
<https://github.com/SupremeCommanderHedgehog/containerizer/security/advisories/new>

Do not open public issues for security problems.

## Response time

We aim to acknowledge reports within 7 days and provide a remediation timeline
within 30 days. As a private-use project, response time is best-effort.

## Supported versions

Only the latest release is supported. Older releases receive no fixes.
```

- [ ] **Step 4: Create `CODEOWNERS`**

```
# Every change requires review from the owner.
*  @SupremeCommanderHedgehog
```

- [ ] **Step 5: Commit**

```
git add README.md LICENSE SECURITY.md CODEOWNERS
git -c user.signingkey=BE707B220C995478 commit -S -m "docs: add README, LICENSE, SECURITY.md, CODEOWNERS"
```

---

## Task 5: Dependabot configuration

**Files:**
- Create: `.github/dependabot.yml`

- [ ] **Step 1: Create `.github/dependabot.yml`**

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "06:00"
      timezone: "America/New_York"
    open-pull-requests-limit: 5
    groups:
      python-dependencies:
        patterns:
          - "*"
    commit-message:
      prefix: "build"
      include: "scope"

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "06:00"
      timezone: "America/New_York"
    open-pull-requests-limit: 5
    groups:
      github-actions:
        patterns:
          - "*"
    commit-message:
      prefix: "ci"
      include: "scope"

  - package-ecosystem: "docker"
    directory: "/src/containerizer/sandbox/runner_image"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "06:00"
      timezone: "America/New_York"
    open-pull-requests-limit: 5
    groups:
      docker:
        patterns:
          - "*"
    commit-message:
      prefix: "build"
      include: "scope"
```

The docker ecosystem points at a directory that does not yet exist; Dependabot tolerates this and starts working once the path is populated in a future plan.

- [ ] **Step 2: Commit**

```
git add .github/dependabot.yml
git -c user.signingkey=BE707B220C995478 commit -S -m "ci: configure Dependabot weekly grouped updates for pip, actions, docker"
```

---

## Task 6: CI workflow (ruff + mypy + pytest matrix)

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    name: Lint (ruff)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: pyproject.toml
      - run: python -m pip install --upgrade pip
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: ruff format --check .

  typecheck:
    name: Typecheck (mypy)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: pyproject.toml
      - run: python -m pip install --upgrade pip
      - run: pip install -e ".[dev]"
      - run: mypy src/containerizer

  test:
    name: Test (Python ${{ matrix.python-version }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip
          cache-dependency-path: pyproject.toml
      - run: python -m pip install --upgrade pip
      - run: pip install -e ".[dev]"
      - run: pytest -v
```

- [ ] **Step 2: Run ruff format locally to confirm we match check mode**

Run: `.\.venv\Scripts\python.exe -m ruff format --check .`

Expected: `X files already formatted` with exit code 0. If any file needs formatting, run `ruff format .` and re-run the check.

- [ ] **Step 3: Commit**

```
git add .github/workflows/ci.yml
git -c user.signingkey=BE707B220C995478 commit -S -m "ci: add ruff + mypy + pytest workflow on 3.11 and 3.12 matrix"
```

---

## Task 7: CodeQL workflow

**Files:**
- Create: `.github/workflows/codeql.yml`

- [ ] **Step 1: Create `.github/workflows/codeql.yml`**

```yaml
name: CodeQL

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
  schedule:
    - cron: "37 8 * * 1"

permissions:
  actions: read
  contents: read
  security-events: write

jobs:
  analyze:
    name: CodeQL analyze (Python)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: github/codeql-action/init@v3
        with:
          languages: python
          queries: security-and-quality
      - uses: github/codeql-action/analyze@v3
        with:
          category: "/language:python"
```

- [ ] **Step 2: Commit**

```
git add .github/workflows/codeql.yml
git -c user.signingkey=BE707B220C995478 commit -S -m "ci: add CodeQL Python analysis on PR, push to main, and weekly schedule"
```

---

## Task 8: release-please workflow + config

**Files:**
- Create: `.github/workflows/release-please.yml`
- Create: `release-please-config.json`
- Create: `.release-please-manifest.json`

- [ ] **Step 1: Create `release-please-config.json`**

```json
{
  "$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
  "release-type": "python",
  "include-component-in-tag": false,
  "include-v-in-tag": true,
  "packages": {
    ".": {
      "package-name": "containerizer",
      "changelog-path": "CHANGELOG.md",
      "extra-files": [
        {
          "type": "generic",
          "path": "src/containerizer/__init__.py"
        }
      ]
    }
  }
}
```

- [ ] **Step 2: Create `.release-please-manifest.json`**

```json
{
  ".": "0.0.0"
}
```

- [ ] **Step 3: Update `src/containerizer/__init__.py` with a release-please marker**

The `extra-files` entry above tells release-please to bump a version string in `__init__.py`. release-please needs an `x-release-please-version` comment annotation. Edit `src/containerizer/__init__.py`:

```python
"""Trace-and-learn containerizer."""

__version__ = "0.0.0"  # x-release-please-version
```

- [ ] **Step 4: Create `.github/workflows/release-please.yml`**

```yaml
name: release-please

on:
  push:
    branches: [main]

permissions:
  contents: write
  pull-requests: write

jobs:
  release-please:
    runs-on: ubuntu-latest
    steps:
      - uses: googleapis/release-please-action@v4
        with:
          config-file: release-please-config.json
          manifest-file: .release-please-manifest.json
```

- [ ] **Step 5: Re-run smoke tests to confirm the version-marker comment did not break anything**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_smoke.py -v`

Expected: 2 passed.

- [ ] **Step 6: Commit**

```
git add release-please-config.json .release-please-manifest.json .github/workflows/release-please.yml src/containerizer/__init__.py
git -c user.signingkey=BE707B220C995478 commit -S -m "ci: add release-please workflow and configuration"
```

---

## Task 9: Issue templates

**Files:**
- Create: `.github/ISSUE_TEMPLATE/config.yml`
- Create: `.github/ISSUE_TEMPLATE/bug.yml`
- Create: `.github/ISSUE_TEMPLATE/feature.yml`
- Create: `.github/ISSUE_TEMPLATE/software-support.yml`

- [ ] **Step 1: Create `.github/ISSUE_TEMPLATE/config.yml`**

```yaml
blank_issues_enabled: false
```

- [ ] **Step 2: Create `.github/ISSUE_TEMPLATE/bug.yml`**

```yaml
name: Bug report
description: Something containerizer did wrong.
title: "bug: "
labels: ["bug"]
body:
  - type: textarea
    id: summary
    attributes:
      label: Summary
      description: One-paragraph description of the problem.
    validations:
      required: true
  - type: textarea
    id: reproduction
    attributes:
      label: Reproduction
      description: Exact commands and inputs that trigger the bug.
      placeholder: |
        $ containerizer build ./installer.bin --name foo
        ...
      render: shell
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: Expected behaviour
    validations:
      required: true
  - type: textarea
    id: actual
    attributes:
      label: Actual behaviour
    validations:
      required: true
  - type: input
    id: containerizer-version
    attributes:
      label: containerizer version
      description: Output of `containerizer --version`.
    validations:
      required: true
  - type: input
    id: podman-version
    attributes:
      label: Podman version
      description: Output of `podman --version`.
  - type: input
    id: kernel
    attributes:
      label: Podman machine kernel
      description: Output of `podman machine ssh uname -a` (or equivalent for non-Windows).
  - type: input
    id: installer-kind
    attributes:
      label: Installer kind
      description: ELF, .deb, .rpm, AppImage, shell, tarball, other.
  - type: textarea
    id: logs
    attributes:
      label: Relevant logs
      render: shell
```

- [ ] **Step 3: Create `.github/ISSUE_TEMPLATE/feature.yml`**

```yaml
name: Feature request
description: Propose a new feature or behavioural change.
title: "feat: "
labels: ["enhancement"]
body:
  - type: textarea
    id: problem
    attributes:
      label: Problem
      description: What problem does this feature solve? Why now?
    validations:
      required: true
  - type: textarea
    id: proposal
    attributes:
      label: Proposal
      description: How would you like containerizer to behave?
    validations:
      required: true
  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives considered
  - type: textarea
    id: acceptance
    attributes:
      label: Acceptance criteria
      description: How would we know this feature is done?
```

- [ ] **Step 4: Create `.github/ISSUE_TEMPLATE/software-support.yml`**

```yaml
name: Add support for software X
description: Request that containerizer be tested or extended to handle a particular piece of software.
title: "support: "
labels: ["software-support"]
body:
  - type: input
    id: software-name
    attributes:
      label: Software name
      description: e.g., "UniFi OS Server", "Plex Media Server".
    validations:
      required: true
  - type: input
    id: installer-source
    attributes:
      label: Installer source
      description: URL or location where the installer can be obtained (if non-confidential).
  - type: dropdown
    id: installer-kind
    attributes:
      label: Installer kind
      options:
        - ELF binary
        - .deb package
        - .rpm package
        - AppImage
        - Shell script
        - Tarball
        - Other
    validations:
      required: true
  - type: textarea
    id: what-it-does
    attributes:
      label: What the software does
      description: One paragraph for context.
    validations:
      required: true
  - type: textarea
    id: smoke-test
    attributes:
      label: How to exercise it during the smoke trace
      description: What does "working" look like? URLs to hit, ports to probe, commands to run.
    validations:
      required: true
  - type: textarea
    id: known-issues
    attributes:
      label: Known issues or special requirements
      description: systemd-required? Hardware access? Outbound dependencies?
```

- [ ] **Step 5: Commit**

```
git add .github/ISSUE_TEMPLATE/
git -c user.signingkey=BE707B220C995478 commit -S -m "ci: add issue forms (bug, feature, software-support) and disable blank issues"
```

---

## Task 10: Probe schema (Pydantic models, TDD)

**Files:**
- Create: `src/containerizer/probe/__init__.py`
- Create: `src/containerizer/probe/schema.py`
- Create: `tests/unit/test_probe_schema.py`

This task and onward are M1 work. From here, work happens on a feature branch.

- [ ] **Step 1: Create and switch to a feature branch**

Run:
```
git switch -c feat/probe-elf
```

- [ ] **Step 2: Create empty `src/containerizer/probe/__init__.py`**

Zero-byte file. Marks the subpackage.

- [ ] **Step 3: Write the failing schema test**

`tests/unit/test_probe_schema.py`:

```python
"""Pydantic model contract for probe outputs."""

import json

import pytest
from pydantic import ValidationError

from containerizer.probe.schema import (
    BaseImageSuggestion,
    ElfProbe,
    InstallerKind,
    ProbeResult,
)


def test_elf_probe_minimum_required_fields() -> None:
    probe = ElfProbe(
        arch="x86_64",
        bit=64,
        endianness="little",
        interpreter="/lib64/ld-linux-x86-64.so.2",
        is_static=False,
        needed_libs=["libc.so.6"],
        glibc_min="2.35",
    )
    assert probe.schema_version == 1
    assert probe.arch == "x86_64"


def test_elf_probe_rejects_unknown_endianness() -> None:
    with pytest.raises(ValidationError):
        ElfProbe(
            arch="x86_64",
            bit=64,
            endianness="middle",  # type: ignore[arg-type]
            interpreter=None,
            is_static=True,
            needed_libs=[],
            glibc_min=None,
        )


def test_base_image_suggestion_round_trips_json() -> None:
    sug = BaseImageSuggestion(image="ubuntu:24.04", reasons=["glibc 2.35", "x86_64"])
    payload = sug.model_dump_json()
    assert BaseImageSuggestion.model_validate_json(payload) == sug


def test_probe_result_serialises_elf_kind() -> None:
    result = ProbeResult(
        kind=InstallerKind.elf,
        arch="x86_64",
        elf=ElfProbe(
            arch="x86_64",
            bit=64,
            endianness="little",
            interpreter="/lib64/ld-linux-x86-64.so.2",
            is_static=False,
            needed_libs=["libc.so.6"],
            glibc_min="2.35",
        ),
        base_image=BaseImageSuggestion(image="ubuntu:24.04", reasons=["glibc 2.35"]),
    )
    payload = json.loads(result.model_dump_json())
    assert payload["kind"] == "elf"
    assert payload["elf"]["glibc_min"] == "2.35"
    assert payload["base_image"]["image"] == "ubuntu:24.04"
    assert payload["schema_version"] == 1
```

- [ ] **Step 4: Run the test and confirm it fails with an import error**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_probe_schema.py -v`

Expected: collection or test failures because `containerizer.probe.schema` does not exist yet.

- [ ] **Step 5: Implement `src/containerizer/probe/schema.py`**

```python
"""Typed JSON models for probe outputs."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InstallerKind(str, Enum):
    elf = "elf"
    deb = "deb"
    rpm = "rpm"
    appimage = "appimage"
    shell = "shell"
    tarball = "tarball"
    unknown = "unknown"


class ElfProbe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    arch: str
    bit: Literal[32, 64]
    endianness: Literal["little", "big"]
    interpreter: str | None
    is_static: bool
    needed_libs: list[str] = Field(default_factory=list)
    glibc_min: str | None


class BaseImageSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    image: str
    reasons: list[str]


class ProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    kind: InstallerKind
    arch: str | None = None
    elf: ElfProbe | None = None
    base_image: BaseImageSuggestion
```

- [ ] **Step 6: Run the test and confirm it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_probe_schema.py -v`

Expected: 4 passed.

- [ ] **Step 7: Run lint and typecheck**

Run: `.\.venv\Scripts\python.exe -m ruff check src tests; .\.venv\Scripts\python.exe -m mypy src/containerizer`

Expected: no errors.

- [ ] **Step 8: Commit**

```
git add src/containerizer/probe/__init__.py src/containerizer/probe/schema.py tests/unit/test_probe_schema.py
git -c user.signingkey=BE707B220C995478 commit -S -m "feat(probe): add typed schema for probe results"
```

---

## Task 11: ELF test fixture

**Files:**
- Create: `tests/fixtures/__init__.py` (empty marker — optional, helps tooling)
- Create: `tests/fixtures/probe/elf-dynamic-x86_64` (binary, ~37 KB)
- Modify: `.gitattributes` (new file) to mark the fixture as binary

- [ ] **Step 1: Create an empty `tests/fixtures/probe/` directory by extracting a known ELF**

The fixture is `/usr/bin/true` from `debian:bookworm-slim`. Use the running Podman machine to extract it. From PowerShell at the repo root:

```pwsh
New-Item -ItemType Directory -Force tests\fixtures\probe | Out-Null
podman run --rm debian:bookworm-slim cat /usr/bin/true | Set-Content -NoNewline -AsByteStream tests\fixtures\probe\elf-dynamic-x86_64
```

If `Set-Content -AsByteStream` is unavailable (older PowerShell), use:

```pwsh
podman run --rm debian:bookworm-slim cat /usr/bin/true > tests\fixtures\probe\elf-dynamic-x86_64
```

Verify the file is a real ELF (first 4 bytes `0x7F 'E' 'L' 'F'`):

```pwsh
Format-Hex -Path tests\fixtures\probe\elf-dynamic-x86_64 -Count 4
```

Expected: hex output beginning with `7F 45 4C 46`.

- [ ] **Step 2: Create `.gitattributes` to mark the fixture as binary**

```
tests/fixtures/probe/* binary
```

This prevents the Windows-host CRLF normalisation from corrupting the ELF.

- [ ] **Step 3: Stage and commit**

```
git add .gitattributes tests/fixtures/probe/elf-dynamic-x86_64
git -c user.signingkey=BE707B220C995478 commit -S -m "test(probe): add real ELF fixture (debian /usr/bin/true) and gitattributes"
```

---

## Task 12: ELF probe — arch, bit, endianness, static-vs-dynamic (TDD)

**Files:**
- Create: `src/containerizer/probe/elf.py`
- Create: `tests/unit/test_probe_elf.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_probe_elf.py`:

```python
"""Tests for ELF binary inspection."""

from pathlib import Path

import pytest

from containerizer.probe.elf import probe_elf


@pytest.fixture
def elf_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "probe" / "elf-dynamic-x86_64"


def test_probe_elf_basic(elf_path: Path) -> None:
    result = probe_elf(elf_path)
    assert result.arch == "x86_64"
    assert result.bit == 64
    assert result.endianness == "little"
    assert result.is_static is False
    assert result.interpreter is not None
    assert result.interpreter.endswith("ld-linux-x86-64.so.2")
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_probe_elf.py -v`

Expected: ImportError because `containerizer.probe.elf` does not exist yet.

- [ ] **Step 3: Implement `src/containerizer/probe/elf.py`**

```python
"""ELF binary probe.

Reads architecture, bit width, endianness, interpreter, dynamic-vs-static, NEEDED
libraries, and minimum glibc requirement from a Linux ELF file using pyelftools.
"""

from __future__ import annotations

from pathlib import Path

from elftools.elf.dynamic import DynamicSection
from elftools.elf.elffile import ELFFile

from containerizer.probe.schema import ElfProbe

_ARCH_FROM_E_MACHINE: dict[str, str] = {
    "EM_X86_64": "x86_64",
    "EM_386": "i386",
    "EM_AARCH64": "aarch64",
    "EM_ARM": "arm",
    "EM_PPC64": "ppc64",
    "EM_PPC": "ppc",
    "EM_RISCV": "riscv",
}


def probe_elf(path: Path) -> ElfProbe:
    """Inspect *path* as an ELF binary and return a typed probe."""
    with path.open("rb") as fh:
        elf = ELFFile(fh)
        arch = _ARCH_FROM_E_MACHINE.get(elf["e_machine"], elf["e_machine"])
        bit = 64 if elf.elfclass == 64 else 32
        endianness = "little" if elf.little_endian else "big"
        interpreter = _read_interpreter(elf)
        needed_libs, has_dynamic = _read_dynamic(elf)
        is_static = interpreter is None and not has_dynamic
        glibc_min = _read_glibc_min(elf)
    return ElfProbe(
        arch=arch,
        bit=bit,
        endianness=endianness,
        interpreter=interpreter,
        is_static=is_static,
        needed_libs=needed_libs,
        glibc_min=glibc_min,
    )


def _read_interpreter(elf: ELFFile) -> str | None:
    for segment in elf.iter_segments():
        if segment["p_type"] == "PT_INTERP":
            raw = segment.get_interp_name()
            return raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
    return None


def _read_dynamic(elf: ELFFile) -> tuple[list[str], bool]:
    needed: list[str] = []
    section = elf.get_section_by_name(".dynamic")
    if not isinstance(section, DynamicSection):
        return needed, False
    for tag in section.iter_tags():
        if tag.entry.d_tag == "DT_NEEDED":
            needed.append(str(tag.needed))
    return needed, True


def _read_glibc_min(elf: ELFFile) -> str | None:
    section = elf.get_section_by_name(".gnu.version_r")
    if section is None:
        return None
    best: tuple[int, int] = (0, 0)
    for verneed, vernaux_iter in section.iter_versions():
        if verneed.name != "libc.so.6":
            continue
        for vernaux in vernaux_iter:
            name = vernaux.name
            if not name.startswith("GLIBC_"):
                continue
            parts = name.removeprefix("GLIBC_").split(".")
            try:
                ver = (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            except ValueError:
                continue
            best = max(best, ver)
    return f"{best[0]}.{best[1]}" if best != (0, 0) else None
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_probe_elf.py -v`

Expected: 1 passed.

- [ ] **Step 5: Run lint and typecheck**

Run: `.\.venv\Scripts\python.exe -m ruff check src tests; .\.venv\Scripts\python.exe -m mypy src/containerizer`

Expected: no errors.

- [ ] **Step 6: Commit**

```
git add src/containerizer/probe/elf.py tests/unit/test_probe_elf.py
git -c user.signingkey=BE707B220C995478 commit -S -m "feat(probe): add ELF binary probe (arch, bit, endianness, interpreter)"
```

---

## Task 13: ELF probe — NEEDED libraries and glibc_min (TDD)

**Files:**
- Modify: `tests/unit/test_probe_elf.py`

The implementation already covers NEEDED libs and glibc_min (Task 12). This task adds explicit tests for those facets.

- [ ] **Step 1: Add the failing tests**

Append to `tests/unit/test_probe_elf.py`:

```python
def test_probe_elf_needed_libs_includes_libc(elf_path: Path) -> None:
    result = probe_elf(elf_path)
    assert any(name == "libc.so.6" for name in result.needed_libs)


def test_probe_elf_glibc_min_parseable(elf_path: Path) -> None:
    result = probe_elf(elf_path)
    assert result.glibc_min is not None
    major, minor = result.glibc_min.split(".")
    assert int(major) >= 2
    assert int(minor) >= 0
```

- [ ] **Step 2: Run the tests and confirm they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_probe_elf.py -v`

Expected: 3 passed (1 from Task 12 plus 2 new).

- [ ] **Step 3: Commit**

```
git add tests/unit/test_probe_elf.py
git -c user.signingkey=BE707B220C995478 commit -S -m "test(probe): assert ELF NEEDED libs and glibc_min extraction"
```

---

## Task 14: Base-image suggestion (TDD)

**Files:**
- Create: `src/containerizer/probe/base_image.py`
- Create: `tests/unit/test_probe_base_image.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_probe_base_image.py`:

```python
"""Tests for base-image suggestion."""

import pytest

from containerizer.probe.base_image import suggest_base_image
from containerizer.probe.schema import ElfProbe


def _elf(glibc: str | None) -> ElfProbe:
    return ElfProbe(
        arch="x86_64",
        bit=64,
        endianness="little",
        interpreter="/lib64/ld-linux-x86-64.so.2",
        is_static=False,
        needed_libs=["libc.so.6"],
        glibc_min=glibc,
    )


@pytest.mark.parametrize(
    ("glibc", "expected_image"),
    [
        ("2.35", "ubuntu:24.04"),
        ("2.36", "ubuntu:24.04"),
        ("2.31", "ubuntu:22.04"),
        ("2.34", "ubuntu:22.04"),
        ("2.30", "ubuntu:20.04"),
        (None, "ubuntu:24.04"),
    ],
)
def test_suggest_base_image_for_glibc(glibc: str | None, expected_image: str) -> None:
    elf = _elf(glibc)
    result = suggest_base_image(elf)
    assert result.image == expected_image
    assert any("glibc" in r or "default" in r for r in result.reasons)


def test_suggest_base_image_includes_arch_reason() -> None:
    elf = _elf("2.35")
    result = suggest_base_image(elf)
    assert any("x86_64" in r for r in result.reasons)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_probe_base_image.py -v`

Expected: ImportError.

- [ ] **Step 3: Implement `src/containerizer/probe/base_image.py`**

```python
"""Base-image suggestion derived from probe metadata.

The picker is intentionally conservative: choose an Ubuntu LTS whose glibc is
new enough to run the binary. The user can always override with --base-image.
"""

from __future__ import annotations

from containerizer.probe.schema import BaseImageSuggestion, ElfProbe


def suggest_base_image(elf: ElfProbe) -> BaseImageSuggestion:
    reasons: list[str] = []
    image = _pick_for_glibc(elf.glibc_min, reasons)
    reasons.append(f"architecture: {elf.arch}")
    return BaseImageSuggestion(image=image, reasons=reasons)


def _pick_for_glibc(glibc_min: str | None, reasons: list[str]) -> str:
    if glibc_min is None:
        reasons.append("no glibc requirement detected; picked ubuntu:24.04 as default")
        return "ubuntu:24.04"
    try:
        major_s, minor_s = glibc_min.split(".", 1)
        major = int(major_s)
        minor = int(minor_s)
    except (ValueError, AttributeError):
        reasons.append(
            f"could not parse glibc version '{glibc_min}'; picked ubuntu:24.04 as default"
        )
        return "ubuntu:24.04"
    if (major, minor) >= (2, 35):
        reasons.append(f"glibc {glibc_min} requires Ubuntu 22.04+; picked 24.04 LTS")
        return "ubuntu:24.04"
    if (major, minor) >= (2, 31):
        reasons.append(f"glibc {glibc_min} fits Ubuntu 22.04 LTS")
        return "ubuntu:22.04"
    reasons.append(f"glibc {glibc_min} fits Ubuntu 20.04 LTS")
    return "ubuntu:20.04"
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_probe_base_image.py -v`

Expected: 7 passed (6 parametrize cases + 1 arch reason test).

- [ ] **Step 5: Run lint and typecheck**

Run: `.\.venv\Scripts\python.exe -m ruff check src tests; .\.venv\Scripts\python.exe -m mypy src/containerizer`

Expected: no errors.

- [ ] **Step 6: Commit**

```
git add src/containerizer/probe/base_image.py tests/unit/test_probe_base_image.py
git -c user.signingkey=BE707B220C995478 commit -S -m "feat(probe): add Ubuntu LTS base-image picker driven by glibc requirement"
```

---

## Task 15: Installer kind dispatch (TDD)

**Files:**
- Create: `src/containerizer/probe/installer.py`
- Create: `tests/unit/test_probe_installer.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_probe_installer.py`:

```python
"""Tests for installer kind detection and dispatch."""

from pathlib import Path

import pytest

from containerizer.probe.installer import (
    UnsupportedInstallerKind,
    detect_kind,
    probe,
)
from containerizer.probe.schema import InstallerKind


@pytest.fixture
def elf_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "probe" / "elf-dynamic-x86_64"


def test_detect_kind_elf(elf_path: Path) -> None:
    assert detect_kind(elf_path) is InstallerKind.elf


def test_detect_kind_unknown(tmp_path: Path) -> None:
    f = tmp_path / "mystery.bin"
    f.write_bytes(b"\x00" * 32)
    assert detect_kind(f) is InstallerKind.unknown


def test_probe_elf_round_trip(elf_path: Path) -> None:
    result = probe(elf_path)
    assert result.kind is InstallerKind.elf
    assert result.arch == "x86_64"
    assert result.elf is not None
    assert result.base_image.image.startswith("ubuntu:")


def test_probe_unsupported_kind_raises(tmp_path: Path) -> None:
    f = tmp_path / "wat.deb"
    f.write_bytes(b"!<arch>\n")  # ar magic; pretends to be .deb
    with pytest.raises(UnsupportedInstallerKind):
        probe(f)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_probe_installer.py -v`

Expected: ImportError.

- [ ] **Step 3: Implement `src/containerizer/probe/installer.py`**

```python
"""Installer kind detection and probe dispatch.

For v0.0.x only ELF binaries are supported. Detection for other kinds is
implemented (so the CLI can surface a clear error), but probing them raises
``UnsupportedInstallerKind`` until later milestones add their parsers.
"""

from __future__ import annotations

from pathlib import Path

from containerizer.probe.base_image import suggest_base_image
from containerizer.probe.elf import probe_elf
from containerizer.probe.schema import InstallerKind, ProbeResult


class UnsupportedInstallerKind(NotImplementedError):
    """Raised when the installer kind is detected but not yet supported."""

    def __init__(self, kind: InstallerKind, path: Path) -> None:
        super().__init__(f"installer kind {kind.value!r} is not yet supported: {path}")
        self.kind = kind
        self.path = path


_ELF_MAGIC = b"\x7fELF"
_AR_MAGIC = b"!<arch>\n"
_RPM_MAGIC = b"\xed\xab\xee\xdb"
_TAR_MAGIC = b"ustar"
_GZIP_MAGIC = b"\x1f\x8b"
_XZ_MAGIC = b"\xfd7zXZ\x00"
_APPIMAGE_MAGIC = b"AI\x02"


def detect_kind(path: Path) -> InstallerKind:
    """Identify the installer kind from its magic bytes and naming hints."""
    head = path.open("rb").read(512)
    if head.startswith(_ELF_MAGIC):
        if _APPIMAGE_MAGIC in head[:32]:
            return InstallerKind.appimage
        return InstallerKind.elf
    if head.startswith(_AR_MAGIC):
        return InstallerKind.deb
    if head.startswith(_RPM_MAGIC):
        return InstallerKind.rpm
    if head.startswith(b"#!"):
        return InstallerKind.shell
    if head.startswith(_GZIP_MAGIC) or head.startswith(_XZ_MAGIC) or _TAR_MAGIC in head[:512]:
        return InstallerKind.tarball
    return InstallerKind.unknown


def probe(path: Path) -> ProbeResult:
    """Probe *path* and return a typed ``ProbeResult``.

    Only :class:`InstallerKind.elf` is implemented for now; everything else
    raises :class:`UnsupportedInstallerKind` with a clear message.
    """
    kind = detect_kind(path)
    if kind is InstallerKind.elf:
        elf = probe_elf(path)
        base = suggest_base_image(elf)
        return ProbeResult(kind=kind, arch=elf.arch, elf=elf, base_image=base)
    raise UnsupportedInstallerKind(kind, path)
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_probe_installer.py -v`

Expected: 4 passed.

- [ ] **Step 5: Run lint and typecheck**

Run: `.\.venv\Scripts\python.exe -m ruff check src tests; .\.venv\Scripts\python.exe -m mypy src/containerizer`

Expected: no errors.

- [ ] **Step 6: Commit**

```
git add src/containerizer/probe/installer.py tests/unit/test_probe_installer.py
git -c user.signingkey=BE707B220C995478 commit -S -m "feat(probe): add installer-kind detection and probe dispatch"
```

---

## Task 16: CLI subcommand `containerizer probe` (TDD)

**Files:**
- Modify: `src/containerizer/cli.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_cli_probe.py`

- [ ] **Step 1: Write the failing integration test**

Create empty `tests/integration/__init__.py`.

`tests/integration/test_cli_probe.py`:

```python
"""End-to-end test for the `containerizer probe` subcommand."""

import json
from pathlib import Path

from click.testing import CliRunner

from containerizer.cli import main


def test_cli_probe_prints_probe_json(fixtures_dir: Path) -> None:
    elf = fixtures_dir / "probe" / "elf-dynamic-x86_64"
    runner = CliRunner()
    result = runner.invoke(main, ["probe", str(elf)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["kind"] == "elf"
    assert payload["arch"] == "x86_64"
    assert payload["elf"]["interpreter"].endswith("ld-linux-x86-64.so.2")
    assert payload["base_image"]["image"].startswith("ubuntu:")


def test_cli_probe_writes_output_file(fixtures_dir: Path, tmp_path: Path) -> None:
    elf = fixtures_dir / "probe" / "elf-dynamic-x86_64"
    out = tmp_path / "probe.json"
    runner = CliRunner()
    result = runner.invoke(main, ["probe", str(elf), "-o", str(out)])
    assert result.exit_code == 0, result.output
    payload = json.loads(out.read_text())
    assert payload["kind"] == "elf"


def test_cli_probe_unsupported_kind_exits_nonzero(tmp_path: Path) -> None:
    f = tmp_path / "wat.deb"
    f.write_bytes(b"!<arch>\n")
    runner = CliRunner()
    result = runner.invoke(main, ["probe", str(f)])
    assert result.exit_code != 0
    assert "not yet supported" in (result.output + (result.stderr if result.stderr else ""))
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_cli_probe.py -v`

Expected: failures because the `probe` subcommand doesn't exist.

- [ ] **Step 3: Update `src/containerizer/cli.py`**

Replace the file contents with:

```python
"""Containerizer CLI entry point."""

from __future__ import annotations

from pathlib import Path

import click

from containerizer import __version__
from containerizer.probe.installer import UnsupportedInstallerKind, probe as probe_installer


@click.group()
@click.version_option(__version__, prog_name="containerizer")
def main() -> None:
    """Trace-and-learn containerizer."""


@main.command("probe")
@click.argument(
    "installer",
    type=click.Path(exists=True, dir_okay=False, path_type=Path, readable=True),
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path, writable=True),
    default=None,
    help="Write probe JSON to this file instead of stdout.",
)
def probe_cmd(installer: Path, output: Path | None) -> None:
    """Statically analyse INSTALLER and emit a probe JSON document."""
    try:
        result = probe_installer(installer)
    except UnsupportedInstallerKind as exc:
        raise click.ClickException(str(exc)) from exc
    payload = result.model_dump_json(indent=2)
    if output is None:
        click.echo(payload)
    else:
        output.write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_cli_probe.py -v`

Expected: 3 passed.

- [ ] **Step 5: Run the full test suite**

Run: `.\.venv\Scripts\python.exe -m pytest -v`

Expected: every test passes; total count is the sum of the smoke, schema, ELF (3), base-image (7), installer dispatch (4), and CLI probe (3) tests.

- [ ] **Step 6: Run lint and typecheck**

Run: `.\.venv\Scripts\python.exe -m ruff check . ; .\.venv\Scripts\python.exe -m ruff format --check . ; .\.venv\Scripts\python.exe -m mypy src/containerizer`

Expected: all green.

- [ ] **Step 7: Commit**

```
git add src/containerizer/cli.py tests/integration/__init__.py tests/integration/test_cli_probe.py
git -c user.signingkey=BE707B220C995478 commit -S -m "feat(cli): add 'containerizer probe' subcommand"
```

---

## Task 17: README usage section

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append a Usage section to README.md**

Edit `README.md`, appending after the "Install (development)" block:

```markdown

## Usage

### `containerizer probe`

Statically inspect an installer and print a typed probe JSON document. For
Linux ELF binaries this reports architecture, glibc requirement, dynamic
loader, NEEDED libraries, and a suggested base image:

```pwsh
PS> containerizer probe .\some-installer.bin
{
  "schema_version": 1,
  "kind": "elf",
  "arch": "x86_64",
  "elf": {
    "schema_version": 1,
    "arch": "x86_64",
    "bit": 64,
    "endianness": "little",
    "interpreter": "/lib64/ld-linux-x86-64.so.2",
    "is_static": false,
    "needed_libs": ["libc.so.6"],
    "glibc_min": "2.35"
  },
  "base_image": {
    "image": "ubuntu:24.04",
    "reasons": [
      "glibc 2.35 requires Ubuntu 22.04+; picked 24.04 LTS",
      "architecture: x86_64"
    ]
  }
}
```

Write the same JSON to a file instead:

```pwsh
PS> containerizer probe .\some-installer.bin -o .\probe.json
```

Only ELF binaries are supported in v0.0.x. Other installer kinds (`.deb`,
`.rpm`, AppImage, shell, tarball) are detected but probing them raises a
clear error until later releases add their parsers.
```

(The triple-backtick fence inside the example is fine since this README is rendered by GitHub which supports nested fences inside fenced blocks.)

- [ ] **Step 2: Commit**

```
git add README.md
git -c user.signingkey=BE707B220C995478 commit -S -m "docs: document 'containerizer probe' usage in README"
```

---

## Task 18: Create the GitHub repository and push `main`

**Files:** none

The local `main` branch has all the M0 bootstrap commits and the design spec, but the M1 work is on `feat/probe-elf`. We push BOTH branches together, then open the PR from the feature branch and let CI run.

- [ ] **Step 1: Create the private GitHub repository**

Run:
```
gh repo create SupremeCommanderHedgehog/containerizer --private --description "Trace-and-learn containerizer that turns Linux installers into hardened Podman containers." --homepage "" --disable-issues=false --disable-wiki=true
```

Expected: a "Created repository" confirmation. The repo URL is `https://github.com/SupremeCommanderHedgehog/containerizer`.

- [ ] **Step 2: Add the remote and push `main` first (without branch protection yet)**

Run:
```
git remote add origin https://github.com/SupremeCommanderHedgehog/containerizer.git
git push -u origin main
```

If the push fails with `GH007: Your push would publish a private email address` (the bitbucket.onl address), STOP and tell the user. They need to either add `github.v5f9w@bitbucket.onl` as a verified email on their `SupremeCommanderHedgehog` GitHub account, or turn off "Keep my email addresses private" in their account settings. Do NOT fall back to a noreply email — that violates their global commit-author policy.

- [ ] **Step 3: Verify the push completed and the remote is correct**

Run:
```
gh repo view SupremeCommanderHedgehog/containerizer --json visibility,defaultBranchRef -q '.'
```

Expected: visibility `PRIVATE`, default branch `main`.

There is no new commit in this task — only remote setup.

---

## Task 19: Configure branch protection on `main`

**Files:** none

- [ ] **Step 1: Apply strict branch protection via `gh api`**

Run this as a single command (HEREDOC with bash):

```bash
gh api --method PUT repos/SupremeCommanderHedgehog/containerizer/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "checks": [
      { "context": "Lint (ruff)" },
      { "context": "Typecheck (mypy)" },
      { "context": "Test (Python 3.11)" },
      { "context": "Test (Python 3.12)" },
      { "context": "CodeQL analyze (Python)" }
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 0
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": false,
  "required_signatures": true
}
JSON
```

Notes:
- `required_approving_review_count: 0` is correct for a solo dev — protection still requires a PR but does not require an external reviewer the user does not have. Code owner review (`require_code_owner_reviews: true`) ensures the user as `CODEOWNERS` is requested.
- `required_signatures: true` matches the global signing policy.
- Status-check contexts MUST match the `name:` of each job in the CI workflow.

- [ ] **Step 2: Verify protection is active**

Run:
```
gh api repos/SupremeCommanderHedgehog/containerizer/branches/main/protection --jq '{required_status_checks: .required_status_checks.checks, required_signatures: .required_signatures.enabled, required_linear_history: .required_linear_history.enabled}'
```

Expected: the JSON shows all five status-check contexts, `required_signatures: true`, and `required_linear_history: true`.

There is no commit in this task.

---

## Task 20: Push the feature branch and open the PR

**Files:** none

- [ ] **Step 1: Push the feature branch**

Run:
```
git push -u origin feat/probe-elf
```

Expected: the branch appears on GitHub.

- [ ] **Step 2: Open the PR**

Run this as a single HEREDOC:

```bash
gh pr create \
  --base main \
  --head feat/probe-elf \
  --title "feat(probe): add ELF probe and 'containerizer probe' command" \
  --body "$(cat <<'EOF'
## Summary

- Adds typed `ProbeResult` schema (Pydantic v2) for installer probes.
- Adds ELF binary probe covering arch, bit width, endianness, interpreter, dynamic vs static, NEEDED libraries, and glibc minimum.
- Adds Ubuntu LTS base-image picker driven by glibc requirement.
- Adds installer-kind detection (ELF, .deb, .rpm, AppImage, shell, tarball, unknown) and a dispatch entry point. Only ELF is implemented for now; other kinds raise a clear `UnsupportedInstallerKind`.
- Wires the `containerizer probe <installer> [-o probe.json]` subcommand.
- Adds unit tests for schema, ELF parsing, base-image picker, dispatch, plus an end-to-end CLI integration test using a real Debian `/usr/bin/true` ELF fixture.

## Test plan

- [x] `pytest -v` locally — all green on 3.12
- [ ] CI: ruff, mypy, pytest matrix (3.11, 3.12), CodeQL all green
- [ ] Manual: `containerizer probe ./some-installer.bin` prints a sane probe JSON

## Out of scope

- `.deb`, `.rpm`, AppImage, shell, tarball probes (detected, not yet probed — separate plans).
- Trace, analyze, generate phases.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: the PR URL is printed.

- [ ] **Step 3: Wait for CI**

Run:
```
gh pr checks --watch
```

Expected: all five required checks pass. If any fails, fix the underlying issue (re-run lint, fix tests, etc.), push, and wait again. Do NOT bypass protection.

There is no commit in this task.

---

## Task 21: Create the Projects v2 board and link it to the repo

**Files:** none

- [ ] **Step 1: Create the project**

Run:
```
gh project create --owner SupremeCommanderHedgehog --title "containerizer roadmap"
```

Expected output includes a project URL of the form `https://github.com/users/SupremeCommanderHedgehog/projects/<N>`. Capture `<N>` as the project number.

- [ ] **Step 2: Resolve the project's GraphQL node id**

Run (substitute `<N>`):
```
gh project view <N> --owner SupremeCommanderHedgehog --format json --jq '{id, title}'
```

Expected: an `{id: "PVT_kw...", title: "containerizer roadmap"}` JSON object. Record the id.

- [ ] **Step 3: Add the `Priority` single-select field**

Run (substitute `<N>`):
```
gh project field-create <N> --owner SupremeCommanderHedgehog --name Priority --data-type SINGLE_SELECT --single-select-options "P0,P1,P2,P3"
```

Expected: a field is created and confirmed.

- [ ] **Step 4: Add the `Area` single-select field**

Run:
```
gh project field-create <N> --owner SupremeCommanderHedgehog --name Area --data-type SINGLE_SELECT --single-select-options "probe,sandbox,trace,generate,cli,meta"
```

Expected: field created.

- [ ] **Step 5: Link the project to the repository so issues/PRs can be added easily**

Run:
```
gh project link <N> --owner SupremeCommanderHedgehog --repo SupremeCommanderHedgehog/containerizer
```

Expected: confirmation that the project is linked.

- [ ] **Step 6: Enable the built-in auto-add workflow (manual web UI step)**

The Projects v2 built-in "Auto-add to project" workflow is configured through the web UI, not the CLI as of `gh` 2.55. Instruct the user to:

1. Open `https://github.com/users/SupremeCommanderHedgehog/projects/<N>/workflows`.
2. Click `Auto-add to project`.
3. Set the filter to `repo:SupremeCommanderHedgehog/containerizer is:issue,pr is:open`.
4. Click `Save and turn on workflow`.

Print these instructions to the user and pause until they confirm.

There is no commit in this task.

---

## Task 22: Enable repository security features

**Files:** none

- [ ] **Step 1: Enable private vulnerability reporting**

Run:
```
gh api --method PUT repos/SupremeCommanderHedgehog/containerizer/private-vulnerability-reporting
```

Expected: HTTP 204 No Content.

- [ ] **Step 2: Enable Dependabot security updates and vulnerability alerts**

Run:
```
gh api --method PUT repos/SupremeCommanderHedgehog/containerizer/vulnerability-alerts
gh api --method PUT repos/SupremeCommanderHedgehog/containerizer/automated-security-fixes
```

Expected: both return HTTP 204.

- [ ] **Step 3: Verify CodeQL is enabled (it auto-enables on first workflow run, but confirm)**

Run:
```
gh api repos/SupremeCommanderHedgehog/containerizer/code-scanning/default-setup --jq '.state'
```

Expected: either `"configured"` (advanced setup, from our `codeql.yml`) or a 404 (advanced workflow not yet run; will auto-configure once the PR runs CodeQL). Either is acceptable — the workflow is the source of truth.

There is no commit in this task.

---

## Task 23: Merge the PR

**Files:** none

- [ ] **Step 1: Verify all checks are green**

Run:
```
gh pr checks
```

Expected: every required check shows `pass`.

- [ ] **Step 2: Merge via squash (linear history is required)**

Run:
```
gh pr merge feat/probe-elf --squash --delete-branch --subject "feat(probe): add ELF probe and 'containerizer probe' command"
```

Expected: PR merged, branch deleted on the remote.

- [ ] **Step 3: Pull the merged history locally**

Run:
```
git switch main
git pull --ff-only
git branch -d feat/probe-elf
```

Expected: `main` is now at the squash merge commit; the local feature branch is removed.

- [ ] **Step 4: Wait for `release-please` to open a release PR**

Run:
```
gh pr list --label "autorelease: pending" --json number,title,headRefName
```

Expected: within ~1 minute of the squash merge, release-please opens a PR titled something like `chore(main): release 0.1.0` because we have at least one `feat:` commit. If the release PR has not opened after 5 minutes, run `gh run list --workflow release-please.yml -L 5` to inspect the workflow output.

- [ ] **Step 5: Review and merge the release-please PR**

Run:
```
gh pr view <release-pr-number>
gh pr merge <release-pr-number> --squash --delete-branch
```

Expected: a tagged release `v0.1.0` is created, the version in `src/containerizer/__init__.py` and `.release-please-manifest.json` is bumped, and `CHANGELOG.md` is generated.

There is no manual commit in this task — release-please commits via PR.

---

## Task 24: Final verification

**Files:** none

- [ ] **Step 1: Confirm v0.1.0 is tagged**

Run:
```
git fetch --tags
git tag --list v0.1.0
gh release view v0.1.0
```

Expected: the tag exists locally; the release exists on GitHub with the release-please-generated notes.

- [ ] **Step 2: Pull and reinstall locally**

Run:
```
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m containerizer --version
```

Expected: `containerizer, version 0.1.0`.

- [ ] **Step 3: End-to-end smoke against the real UniFi installer fixture in the working tree**

Run:
```
.\.venv\Scripts\python.exe -m containerizer probe ".\24e0-linux-x64-5.1.15-926621de-c9d7-48cd-8921-a0ff3eebd3f4.15-x64"
```

Expected: a probe JSON identifying it as an ELF x86_64 binary, with a populated `interpreter`, `needed_libs`, `glibc_min`, and a `base_image.image` of `ubuntu:24.04` or `ubuntu:22.04`. Confirm the output matches the user's understanding of the installer's runtime requirements; if anything looks off, open a bug issue using the new `bug.yml` form.

- [ ] **Step 4: Confirm the project board picked up the merged PRs**

Run:
```
gh project item-list <N> --owner SupremeCommanderHedgehog --format json --jq '.items | length'
```

Expected: at least 1 (the merged feature PR). If 0, revisit Task 21 Step 6 — the auto-add workflow may not be turned on.

There is no commit in this task.

---

## Coverage check

Spec sections vs tasks that implement them:

- §2 Goals & non-goals: scope is implicitly bounded by the plan stopping at the `probe` subcommand (next plan covers trace/analyze/generate).
- §3 Target user / UX: `containerizer --version` and `containerizer probe` exist (Tasks 2, 16).
- §4 Architecture: not exercised in this plan; M2+.
- §5.1 CLI: Tasks 2, 16.
- §5.2 Installer probe: Tasks 10–15.
- §5.3 Sandbox runner: M2 (next plan).
- §5.4 Trace orchestrator: M2 (next plan).
- §5.5 Trace collectors: M2 (next plan).
- §5.6 Trace analyzer: M3 (next plan).
- §5.7 Policy derivation: M3 (next plan).
- §5.8 Generators: M4 (next plan).
- §6 Data flow / schemas: probe schema only here (Task 10); rest in later plans.
- §7 Hardening defaults: M4 (next plan).
- §8 Error handling: probe-level `UnsupportedInstallerKind` (Task 15) and CLI error wrapping (Task 16).
- §9 Testing strategy: unit + integration scaffolding established (Tasks 3, 10–16); golden-file generator tests come in M4 plan.
- §10 Repository & GitHub setup: Tasks 4–9, 18–22.
- §11–§13 Risks / out-of-scope / milestones: spec-level; not directly implemented.

All M0 and M1-ELF spec items have at least one corresponding task.

