# Coding Agent Guide (dirsearch)

This repository contains **dirsearch**, a web path discovery tool. Use this guide to keep changes aligned with project expectations and release workflows.

## Scope
- These instructions apply to the entire repository.
- If a subdirectory contains its own `AGENTS.md`, that file takes precedence for that subtree.

## Project overview (high-level map)
- **Entrypoint**: `dirsearch.py` is the CLI entry for running scans.
- **Core flow**: `lib/controller/controller.py` orchestrates scans, sets up reports, handles sessions, and manages runtime flow.
- **Networking**: `lib/connection/requester.py` (sync) and `lib/connection` modules manage HTTP requests, proxies, auth, rate limiting, and DNS caching.
- **Reporting**: `lib/report/` and `lib/report/manager.py` manage output formats (plain, JSON, XML, CSV, HTML, SQLite, MySQL, PostgreSQL, etc.).
- **Sessions**: session persistence is handled by `lib/controller/session.py`, with default session paths configured in `lib/core/settings.py`.
- **Builds**: PyInstaller build files live under `pyinstaller/`, with CI workflows under `.github/workflows/`.
- **Docker**: `Dockerfile` provides a minimal containerized entrypoint.

## Directory structure (quick map)
- `lib/`: Core application code (modules grouped by responsibility).
  - `lib/core/`: settings, options, data, and shared helpers.
  - `lib/controller/`: orchestration and session handling.
  - `lib/connection/`: HTTP/DNS/networking stack.
  - `lib/parse/`: parsing helpers (URLs, raw requests).
  - `lib/report/`: reporting formats and output handlers.
  - `lib/utils/`: utility modules shared across the codebase.
  - `lib/view/`: terminal output and UI helpers.
- `db/`: bundled wordlists and categories.
- `tests/`: test data and unit tests.
- `sessions/`: default session output location for source runs.
- `static/`: static assets (logos).
- `.github/workflows/`: CI/CD, security scanning, and packaging workflows.

## Code style and architecture
- Prefer **pythonic** code: clear naming, readable structure, and small, testable functions.
- Use **polymorphism and classes** where it improves readability or flexibility (especially within `lib/`), avoiding unnecessary complexity.
- Treat `lib/` as a modular framework: keep boundaries clean, use explicit interfaces, and avoid cross-layer leakage.
- Add **comments for edge cases** so behavior is clear to future maintainers.

## When you change X, check Y (dependency map)
Use this section to keep side effects aligned and to avoid missing required updates.

### CLI / options / config
- If you add or change CLI options, update:
  - `README.md` options/usage docs.
  - `config.ini` defaults (when relevant).
  - Any tests or examples referencing the old flags.

### Output formats / reports
- If you add or change report formats:
  - Update `lib/report/manager.py` to register the handler.
  - Confirm the format appears in README output examples if documented.
  - Ensure any CI tests that generate reports still pass (see `.github/workflows/ci.yml`).

### Sessions
- If you change session content or schema:
  - Update `lib/controller/session.py` serialization/deserialization logic.
  - Update any references to default session locations in docs (see `README.md`).
  - Consider backward compatibility for older session formats.

### Networking / request pipeline
- If you modify request logic, proxies, auth, or rate limiting:
  - Review `lib/connection/requester.py` and `lib/connection/dns.py`.
  - Validate behavior with relevant CLI options (proxy, auth, random agents, max rate).
  - Consider updates to tests or example commands in CI.

### Controller / workflow behavior
- If you change scan orchestration or run flow:
  - Review `lib/controller/controller.py` for session handling, callbacks, and report preparation.
  - Ensure that report saving and session export still operate as expected.

### Build & release artifacts (PyInstaller)
- If you add modules or dependencies that must be bundled:
  - Update PyInstaller hidden imports or data in:
    - `pyinstaller/dirsearch.spec` (preferred), and
    - GitHub Actions PyInstaller workflows under `.github/workflows/` (Linux/macOS/Windows).
  - Verify `pyinstaller/build.sh` still produces a working binary.
  - If you change outputs or binary names, update the release workflow (`pyinstaller-release-draft.yml`).

### Docker
- If you add OS-level dependencies or change runtime behavior:
  - Update `Dockerfile` accordingly.
  - Ensure new files are included in the container build context.

### CI / GitHub Actions
- If you change dependencies, CLI usage, or tests:
  - Update `.github/workflows/ci.yml` to keep inspection steps and command flags in sync.
  - Consider whether CodeQL, Semgrep, Docker build, or PyInstaller workflows need updates.

### Adding a new feature or major behavior
- Update docs (`README.md`, CLI examples, and any new flags).
- Ensure reports/session outputs include the new data if applicable.
- Verify CI commands still cover the new feature path.
- Consider whether Docker, PyInstaller, or release workflows need updates for new dependencies or files.

## Current automation (quick reference)
- **CI / Inspection**: `.github/workflows/ci.yml` runs CLI scans, `testing.py`, lint (flake8), and codespell.
- **Security**: CodeQL (`codeql-analysis.yml`) and Semgrep (`semgrep-analysis.yml`) run on PRs/pushes.
- **Docker**: `docker-image.yml` builds the Docker image on pushes and PRs to `master`.
- **PyInstaller**: platform builds and draft release workflows live under `.github/workflows/pyinstaller-*.yml`.

## Testing guidance
- For logic changes, try:
  - `python3 testing.py`
  - `python3 -m pytest` (if you touch tests or add new ones)
- For CLI changes, run a short scan against a sample target:
  - `python3 dirsearch.py -w ./tests/static/wordlist.txt -u https://example.com -q`

## Communication checklist (for summaries / PRs)
- What changed and why.
- Any updates to docs, CLI flags, or output formats.
- Whether sessions or reports were affected (and if a migration is required).
- Tests executed and their results.
