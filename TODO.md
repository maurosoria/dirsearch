# v5.0.0 Release TODO

## Current Status

Phase 1 is implemented for optional database dependencies. Phase 2 is implemented for the Python 3.14 / `5.0.0` release baseline. Phase 3 is implemented for the first importable Python API. Phase 4 is implemented for template wordlists and generation controls. Phase 5 is implemented for the native wordlist backend and the experimental native request backend. Phase 6 final Docker and packaging gates are complete.

This is a useful foundation for a future MCP server or REST API because import-time side effects are lower, base installs no longer require database drivers, the first supported Python API surface is available, and the optional native backend has measured local and DigitalOcean benchmark coverage.

## Completed

- Moved MySQL/PostgreSQL drivers out of required runtime dependency files.
- Added optional dependency groups:
  - `dirsearch[mysql]`
  - `dirsearch[postgresql]`
  - `dirsearch[db]`
- Added `requirements/db.txt` for database-output installs.
- Changed report manager DB handlers to lazy-load database report modules only when DB output is selected.
- Moved DB driver imports inside the actual connection paths.
- Removed controller/session top-level references to DB driver exception classes.
- Added optional dependency regression tests in `tests/test_optional_db_dependencies.py`.
- Verified the base Docker image builds without DB drivers.
- Updated package version to `5.0.0`.
- Added Python 3.10-3.14 classifiers while keeping `requires-python = ">=3.9"`.
- Updated Docker to use `python:3.14-alpine`.
- Updated CI to test Python 3.9, 3.11, and 3.14.
- Updated PyInstaller release builds to Python 3.14 and PyInstaller 6.20.0.
- Updated Nuitka release builds to Python 3.14 and Nuitka 4.0.8.
- Updated release binary workflows/scripts to install `requirements/db.txt` so standalone builds keep DB report support.
- Updated release docs and changelog for `5.0.0`.
- Removed the Python 3.14 `SyntaxWarning` from threaded fuzzer shutdown handling.
- Updated newer verified pins:
  - `requests==2.33.1`
  - `pyopenssl==26.1.0`
  - `setuptools==82.0.1`
  - `mysql-connector-python==9.6.0`
  - `psycopg[binary]==3.3.3`
- Added public imports:
  - `FuzzerConfig`
  - `DirsearchFuzzer`
  - `FuzzerResult`
  - `Wordlist`
  - `WordlistTemplate`
  - `WordlistState`
- Added an importable API that runs from `FuzzerConfig` without caller-mutated CLI globals.
- Added structured result and callback support.
- Added template wordlist expansion for Python callers, including `%EXT%` and custom placeholders.
- Added isolation coverage proving two configs do not leak state in one process.
- Added packaged install smoke coverage for the public API imports.
- Added optional DB and importable API coverage to `testing.py`.
- Added shared template wordlist expansion for CLI and Python API callers.
- Added named placeholders for subjects, CRUD/auth/admin ops, envs, separators, dates, DB/archive tokens, API versions, categories, and `%EXT%`.
- Added curated template wordlists under `db/templates/`.
- Added `--wordlist-status`.
- Added `--wordlist-max-size` generation limits.
- Added template wordlist regression coverage to `testing.py`.
- Added the wordlist backend interface and `auto|python|native` selection.
- Added the Rust native wordlist implementation with Python-compatible ordering, deduplication, extension filtering, forced extensions, overwrite extensions, affixes, casing, and size limits.
- Added the experimental Rust native request backend with `--request-backend=python|native` selection.
- Added native request response, native request option validation, native fuzzer, and native wordlist backend regression coverage to `testing.py`.
- Added Phase 5 native backend benchmark scripts and recorded DigitalOcean benchmark artifacts under `benchmarks/phase5/`.
- Added `.dockerignore` so Docker release gates do not copy local virtualenvs, build output, caches, sessions, or Rust target artifacts into the runtime image.
- Completed the final Docker gate for base runtime installs, `dirsearch[db]` installs, Python backend tests, native backend tests, CLI smoke checks, packaged import checks, and local benchmark coverage.

## Verification Run

- `/home/mauro/dirsearch/.venv/bin/python -m unittest tests.test_optional_db_dependencies tests.controller.test_session_store`
- `/home/mauro/dirsearch/.venv/bin/python -m unittest tests.connection.test_requester tests.connection.test_dns tests.core.test_scanner tests.test_optional_db_dependencies tests.controller.test_session_store`
- `/home/mauro/dirsearch/.venv/bin/python testing.py`
- `/home/mauro/dirsearch/.venv/bin/python -m pip wheel . --no-deps --no-build-isolation -w /tmp/dirsearch-wheel`
- `docker build -t dirsearch:optional-db-test .`
- `docker run --rm --entrypoint python3 dirsearch:optional-db-test -m unittest tests.test_optional_db_dependencies tests.controller.test_session_store`
- `docker run --rm --entrypoint python3 dirsearch:optional-db-test -c "import importlib.util; print(importlib.util.find_spec('mysql')); print(importlib.util.find_spec('psycopg'))"`
- `/home/mauro/dirsearch/.venv/bin/python -m py_compile lib/core/fuzzer.py lib/core/settings.py setup.py tests/test_optional_db_dependencies.py`
- `/home/mauro/dirsearch/.venv/bin/python -m unittest tests.test_optional_db_dependencies tests.controller.test_session_store tests.core.test_scanner`
- `/home/mauro/dirsearch/.venv/bin/python dirsearch.py --version`
- `/home/mauro/dirsearch/.venv/bin/python testing.py`
- `/home/mauro/dirsearch/.venv/bin/python -m pip wheel . --no-deps --no-build-isolation -w /tmp/dirsearch-wheel-v5`
- Wheel metadata inspection confirmed `Version: 5.0.0`, `Requires-Python: >=3.9`, Python 3.14 classifier, and DB extras.
- `docker build -t dirsearch:v5-release-base .`
- `docker run --rm dirsearch:v5-release-base --version`
- `docker run --rm --entrypoint python3 dirsearch:v5-release-base testing.py`
- `docker run --rm --entrypoint python3 dirsearch:v5-release-base dirsearch.py -u https://example.com -w tests/static/wordlist.txt -q`
- `docker run --rm --entrypoint sh dirsearch:v5-release-base -c "python3 -m pip install . && python3 tests/check_packaged_install.py"`
- `/home/mauro/dirsearch/.venv/bin/python -m unittest tests.core.test_importable_api`
- `/home/mauro/dirsearch/.venv/bin/python testing.py` (33 tests)
- `/home/mauro/dirsearch/.venv/bin/python tests/check_packaged_install.py`
- `docker build -t dirsearch:v5-importable-api .`
- `docker run --rm --entrypoint python3 dirsearch:v5-importable-api testing.py`
- `docker run --rm --entrypoint sh dirsearch:v5-importable-api -c "python3 -m pip install . && python3 tests/check_packaged_install.py"`
- `/home/mauro/dirsearch/.venv/bin/python -m unittest tests.core.test_dictionary_templates tests.core.test_importable_api`
- `/home/mauro/dirsearch/.venv/bin/python dirsearch.py --wordlist-status -w db/templates/crud.txt -e php`
- `/home/mauro/dirsearch/.venv/bin/python dirsearch.py --wordlist-status -w db/templates/crud.txt -e php --wordlist-max-size 1`
- `/home/mauro/dirsearch/.venv/bin/python -m unittest tests.core.test_wordlist_backend tests.core.test_dictionary_templates tests.core.test_request_backend tests.connection.test_native_response tests.core.test_native_fuzzer`
- `cargo check --manifest-path native/Cargo.toml`
- `/home/mauro/dirsearch/.venv/bin/python -m maturin develop --manifest-path native/Cargo.toml`
- `/home/mauro/dirsearch/.venv/bin/python testing.py` (53 tests)
- Local CLI smoke against a temporary HTTP server with `--request-backend native`
- `/home/mauro/dirsearch/.venv/bin/python scripts/benchmark_phase5.py --requests 5 --concurrency 2 --wordlist-lines 5 --wordlist-repeats 1 --include-native --json`
- `docker build -t dirsearch:v5-final-gate .`
- `docker run --rm --entrypoint python3 dirsearch:v5-final-gate -c "import importlib.util; print(importlib.util.find_spec('mysql')); print(importlib.util.find_spec('psycopg'))"`
- `docker run --rm --entrypoint python3 dirsearch:v5-final-gate testing.py` (53 tests)
- `docker run --rm dirsearch:v5-final-gate --version`
- `docker run --rm dirsearch:v5-final-gate -u https://example.com -w tests/static/wordlist.txt -q`
- `docker run --rm --entrypoint sh dirsearch:v5-final-gate -c "python3 -m pip install . && python3 tests/check_packaged_install.py"`
- Docker `dirsearch[db]` install check confirmed `dirsearch==5.0.0`, `mysql.connector`, and `psycopg`.
- `/home/mauro/dirsearch/.venv/bin/python -m unittest tests.core.test_dictionary_templates tests.core.test_wordlist_backend tests.core.test_importable_api tests.core.test_request_backend tests.connection.test_native_response tests.core.test_native_fuzzer`
- `cargo check --manifest-path native/Cargo.toml`
- `/home/mauro/dirsearch/.venv/bin/python scripts/benchmark_phase5.py --include-native --json`
- `git diff --check`
- Local-only artifacts removed from the working tree: `.cache/`, `.venv/`, `build/`, `native/target/`, and generated root `dirsearch.spec`.
- Updated ignore rules for local virtualenvs, caches, build outputs, distribution outputs, and generated root PyInstaller specs.

## Final State

All v5.0.0 release phases in this TODO are complete. The remaining work is normal release mechanics: review the final diff, commit the intended source files and benchmark artifacts, push the branch, and open the release PR.
