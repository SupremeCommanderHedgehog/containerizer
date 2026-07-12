# Contributing to containerizer

Thanks for your interest in improving `containerizer`. This document covers how
to set up a development environment, the checks your change must pass, and how to
open a pull request.

## Development setup

`containerizer` targets **Python 3.11+**. On a Windows host you also need a
running Podman machine for the `trace`/`build` scenarios; the `probe` and
`generate` paths are pure static analysis and need no Podman.

```pwsh
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

On Linux/macOS:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` if a scenario needs a local installer path — `.env`
is gitignored and must never contain committed paths or credentials.

## Checks your change must pass

CI runs these on Python 3.11 and 3.12; run them locally before pushing:

```sh
ruff format --check .    # formatting
ruff check .             # lint
mypy src                 # type check
pytest tests/            # full test suite
```

New behavior needs tests. This project follows a trace-and-verify philosophy —
prefer tests that assert on observed output over tests that assert on
implementation details.

## Commits

- **Conventional Commits.** Titles must follow the
  [Conventional Commits](https://www.conventionalcommits.org/) spec
  (`feat:`, `fix:`, `docs:`, `chore:`, …); release notes are generated from them
  by release-please.
- **Signed commits.** `main` requires signed commits. Sign yours with
  `git commit -S` and a GPG/SSH key registered to your GitHub account.
- Keep commits focused and the working tree free of generated artifacts
  (`out/`, `*.deb`, `*.log`, `.venv/` are all gitignored — keep it that way).

## Pull requests

1. Branch off `main` and open a PR against `main`.
2. Fill in the pull request template.
3. Ensure CI is green — required checks (tests, lint, typecheck on 3.11 & 3.12,
   CodeQL) must pass and are enforced on `main`.
4. Link the issue your PR closes (`Closes #NNN`).

## Reporting security issues

Do **not** open a public issue for a vulnerability. See
[`SECURITY.md`](SECURITY.md) for private reporting instructions.
