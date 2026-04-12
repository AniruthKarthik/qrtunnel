# QRTunnel — Development Setup Guide

## 1. Clone the Repository

```bash
git clone https://github.com/AniruthKarthik/qrtunnel.git
cd qrtunnel
```

## 2. Create a Virtual Environment

```bash
python -m venv .venv
```

Activate it:

| Platform | Command |
|---|---|
| Linux/macOS | `source .venv/bin/activate` |
| Windows CMD | `.venv\Scripts\activate.bat` |
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |

## 3. Install in Editable Mode with Dev Dependencies

```bash
pip install -e ".[dev]"
```

This installs `qrtunnel` as a live-editable package plus `ruff` and `pytest`.

If `[dev]` extras aren't defined yet in `pyproject.toml`, install manually:

```bash
pip install -e .
pip install ruff pytest
```

## 4. Verify Installation

```bash
qrtunnel --version
qrtunnel --help
```

## 5. Run the Linter

```bash
ruff check .
ruff format --check .
```

Auto-fix:

```bash
ruff format .
ruff check --fix .
```

## 6. Run Tests

```bash
pytest tests/ -v
```

Run a specific test file:

```bash
pytest tests/test_port.py -v
```

## 7. Test the Tool Manually

Send a file (LAN only, no tunnel needed):

```bash
qrtunnel send README.md --lan
```

Receive files:

```bash
mkdir /tmp/recv
qrtunnel receive /tmp/recv --lan
```

## 8. External Dependencies for Full Testing

| Feature | Requirement |
|---|---|
| SSH tunnel mode | `ssh` binary + internet access |
| ngrok tunnel mode | ngrok installed + authtoken configured |
| LAN mode | No external deps |
| TUI | Terminal with ANSI support |

### Install SSH (if missing)

```bash
# Ubuntu/Debian
sudo apt install openssh-client

# macOS
brew install openssh
```

### Install ngrok

Download from https://ngrok.com/download, then:

```bash
ngrok config add-authtoken <your-token>
```

## 9. Project Config Files

| File | Purpose |
|---|---|
| `pyproject.toml` | Canonical project metadata and build config |
| `setup.cfg` | Legacy — to be removed (tracked in issue #XX) |
| `requirements.txt` | Runtime dependencies |
| `ruff.toml` or `pyproject.toml [tool.ruff]` | Linter config |

## 10. Branching Convention

| Branch pattern | Use |
|---|---|
| `fix/<short-desc>` | Bug fixes |
| `feat/<short-desc>` | New features |
| `docs/<short-desc>` | Documentation only |
| `refactor/<short-desc>` | Refactoring |
| `ci/<short-desc>` | CI/tooling changes |

## 11. Before Opening a PR

```bash
ruff check .          # must be clean
ruff format --check . # must be clean
pytest tests/ -v      # must pass
```

Update `CHANGELOG.md` under `[Unreleased]`. Link the relevant issue in your PR description.
