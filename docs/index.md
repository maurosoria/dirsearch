# dirsearch Documentation

dirsearch is an advanced web path brute-forcer. This documentation is split into focused pages so the repository README can stay concise and the docs can later become the base for a documentation site.

## User Documentation

- [Installation](installation.md): supported platforms, Python installation, release artifacts, and Docker usage.
- [Usage Guide](usage.md): common command examples, recursion, filtering, proxies, raw requests, reports, and practical tips.
- [Wordlists](wordlists.md): extension handling, bundled categories, templates, prefixes, suffixes, and wordlist transformations.
- [CLI Options](options.md): complete command-line option reference.
- [Configuration](configuration.md): `config.ini` behavior and reference.
- [Sessions](sessions.md): saving, listing, and resuming interrupted scans.
- [Python API](python-api.md): using dirsearch from Python automation.

## Maintainer Documentation

- [Building](building.md): PyInstaller builds, portable archives, Docker images, and GitHub Actions workflows.
- [Target Progress](scan-run-state.md): pending/active ownership, sequential execution, and checkpoint boundaries.
- [Target Configuration](target-configuration.md): immutable target preparation hints and transport boundaries.
- [Terminal Configuration](terminal-configuration.md): per-controller output policy, streams, history and cleanup.
- [Refactoring Backlog](refactoring-backlog.md): remaining local state ownership work and mutable-global inventory.
- [References](references.md): external articles, tutorials, and videos.
