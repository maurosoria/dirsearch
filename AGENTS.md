# Repository Guidelines

## Project Structure & Module Organization
`dirsearch.py` is the main CLI entrypoint. Core code lives in `lib/`: `lib/connection/` handles HTTP/DNS, `lib/controller/` drives scans and sessions, `lib/core/` stores settings and option state, `lib/report/` contains output handlers, and `lib/view/` formats terminal output. Bundled wordlists and data files live in `db/`. Tests are under `tests/`, with static fixtures in `tests/static/`. Packaging files live in `pyproject.toml`, `setup.py`, `requirements/`, and `pyinstaller/`.

## Build, Test, and Development Commands
- `python3 dirsearch.py -u https://example.com -w tests/static/wordlist.txt -q`: quick local CLI smoke test.
- `python3 testing.py`: legacy unit/integration test runner used by CI.
- `python3 -m unittest tests.connection.test_requester tests.connection.test_dns tests.core.test_scanner`: focused regression pass.
- `python3 -m pip install .`: validate packaged install and console entrypoints.
- `docker build -t dirsearch:test .`: verify the Docker image still builds.
- `pyinstaller --clean pyinstaller/dirsearch.spec`: build the standalone binary using the checked-in spec.

## Coding Style & Naming Conventions
Use 4-space indentation and keep Python code straightforward and modular. Prefer descriptive `snake_case` for functions and variables, `PascalCase` for classes, and small helpers for exception-heavy logic. Keep module boundaries clean: networking belongs in `lib/connection`, report logic in `lib/report`, and CLI/config parsing in `lib/parse` or `lib/core`. Follow the existing flake8 rules in `pyproject.toml`.

## Testing Guidelines
Tests use `unittest`. Add new coverage under `tests/` with filenames like `test_requester.py` and methods named `test_*`. When changing request, packaging, or report behavior, add message-level or artifact-level assertions rather than only smoke checks. For compatibility-sensitive changes, prefer Docker validation on supported Python versions.

## Native Backend Benchmarking
Phase 5 native request-backend benchmarks live under `benchmarks/phase5/`, with raw JSON in `benchmarks/phase5/results/`. Use `scripts/benchmark_local_contention.py` for local controlled tests, `scripts/run_phase5_do_benchmark.sh` for one DigitalOcean scanner droplet, and `scripts/run_phase5_do_split_matrix.sh` when the nginx target should run on a separate droplet from the scanners. For CPU scaling comparisons, prefer the split matrix with a fixed target droplet and scanner sizes such as `s-2vcpu-4gb,s-4vcpu-8gb,s-8vcpu-16gb`.

When reporting benchmark results, lead with medians and include best samples only as secondary context. Distinguish direct HTTP client numbers from full `dirsearch` contention numbers because the full scan includes fuzzer, callbacks, filters, process overhead, and scheduler effects. Treat runtime worker count and HTTP in-flight concurrency as separate knobs: runtime workers should follow CPU count, while HTTP concurrency may be higher for I/O-bound scans.

## Commit & Pull Request Guidelines
Recent history favors short imperative commits such as `Fix async SSL classification and add tests` or `Use PyInstaller spec in GitHub workflows`. Keep commits scoped to one change. PRs should explain the user-visible effect, link the issue when applicable, and list the commands you ran. Update docs or workflow files when changing CLI flags, packaging, or bundled artifacts.

## Security & Configuration Tips
Do not commit secrets, session artifacts, or local virtualenv files. DigitalOcean tokens must stay in environment variables such as `DIGITALOCEAN_ACCESS_TOKEN`; never write them into scripts, result files, or docs. After any DigitalOcean benchmark, verify cleanup with `doctl compute droplet list --tag-name dirsearch-phase5-benchmark`, check temporary SSH keys with `doctl compute ssh-key list | rg 'dirsearch-(split|phase5)'`, and scan the repo with `rg -n 'dop[_]v1_' . --glob '!/.git/**' --glob '!/.venv/**' --glob '!build/**'`. If you change dependencies, keep `requirements.txt`, `requirements/runtime.txt`, and packaging metadata aligned. If you add runtime files or imports, verify both `pyinstaller/dirsearch.spec` and GitHub Actions workflows still bundle them.
