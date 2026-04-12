# Contributing to QRTunnel

## Prerequisites

- Python 3.8+
- `git`
- `pip`
- `ssh` binary (Linux/macOS)
- ngrok installed and authed (Windows testing)

## Setup

```bash
git clone https://github.com/AniruthKarthik/qrtunnel.git
cd qrtunnel
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests/ -v
```

## Running the Linter

```bash
ruff check .
ruff format --check .
```

Auto-fix:

```bash
ruff format .
ruff check --fix .
```

## Project Structure

```
qrtunnel/
├── qrtunnel.py          # Main entry point (single-file module)
├── tests/               # Pytest test suite
├── pyproject.toml       # Project metadata and build config (canonical)
├── requirements.txt     # Runtime dependencies
├── .github/
│   ├── ISSUE_TEMPLATE/  # Bug and feature templates
│   └── PULL_REQUEST_TEMPLATE.md
```

## Making Changes

1. Fork the repo.
2. Create a branch: `git checkout -b fix/port-collision` or `feat/progress-bar`.
3. Make your changes.
4. Run tests and linter — both must pass.
5. Commit with a conventional commit message (see below).
6. Open a PR against `master`.

## Commit Message Format

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

Types: feat | fix | docs | refactor | test | ci | chore
```

Examples:

```
fix(lan): handle multi-NIC machines by preferring non-loopback IP
feat(cli): add --version flag reading from pyproject.toml
docs(readme): add TUI screenshot and usage GIF
```

## Good First Issues

Look for issues tagged [`good first issue`](https://github.com/AniruthKarthik/qrtunnel/issues?q=label%3A%22good+first+issue%22). These are scoped, low-risk, and well-described.

## PR Rules

- One concern per PR. Don't bundle unrelated changes.
- PRs without passing CI will not be reviewed.
- Link the relevant issue: `Closes #N`.
- Add or update tests for any logic change.
- Update `CHANGELOG.md` under `[Unreleased]`.

## Questions

Open a [Discussion](https://github.com/AniruthKarthik/qrtunnel/discussions) — not an issue.
