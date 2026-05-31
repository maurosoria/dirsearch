<img src="static/logo.png#gh-light-mode-only" alt="dirsearch logo (light)" width="675px">
<img src="static/logo-dark.png#gh-dark-mode-only" alt="dirsearch logo (dark)" width="675px">

# dirsearch - Web Path Discovery

![Build](https://img.shields.io/badge/Built%20with-Python-Blue)
![License](https://img.shields.io/badge/license-GNU_General_Public_License-_red.svg)
![Stars](https://img.shields.io/github/stars/maurosoria/dirsearch.svg)
[![Release](https://img.shields.io/github/release/maurosoria/dirsearch.svg)](https://github.com/maurosoria/dirsearch/releases)
[![Sponsors](https://img.shields.io/github/sponsors/maurosoria)](https://github.com/sponsors/maurosoria)
[![Discord](https://img.shields.io/discord/992276296669339678.svg?logo=discord)](https://discord.gg/2N22ZdAJRj)
[![Twitter](https://img.shields.io/twitter/follow/_dirsearch?label=Follow)](https://twitter.com/_dirsearch)


> An advanced web path brute-forcer

**dirsearch** is being actively developed by [@maurosoria](https://twitter.com/_maurosoria) and [@shelld3v](https://twitter.com/shells3c_).

Join the [Discord server](https://discord.gg/2N22ZdAJRj) to communicate with the team.

## Quick Start

dirsearch requires Python 3.11 or higher.

```sh
git clone https://github.com/maurosoria/dirsearch.git --depth 1
cd dirsearch
python3 dirsearch.py -u https://example.com -e php,html,js
```

You can also install the latest source directly from GitHub with pip:

```sh
pip3 install git+https://github.com/maurosoria/dirsearch.git
dirsearch -u https://example.com -e php,html,js
```

Pre-built PyInstaller binaries and portable folder archives are available on the [Releases page](https://github.com/maurosoria/dirsearch/releases).

## Documentation

The full documentation now lives in [`docs/`](docs/index.md):

- [Installation](docs/installation.md): supported platforms, Python install, release artifacts, and Docker.
- [Usage Guide](docs/usage.md): common scans, recursion, filters, proxies, raw requests, reports, and tips.
- [Wordlists](docs/wordlists.md): `%EXT%`, categories, templates, prefixes, suffixes, and transformations.
- [CLI Options](docs/options.md): complete command-line reference.
- [Configuration](docs/configuration.md): `config.ini` reference.
- [Sessions](docs/sessions.md): save, list, and resume scan sessions.
- [Python API](docs/python-api.md): importable API examples.
- [Building](docs/building.md): PyInstaller, portable builds, Docker images, and GitHub Actions.
- [References](docs/references.md): external tutorials and articles.

## Minimal Examples

```sh
python3 dirsearch.py -u https://target
python3 dirsearch.py -u https://target -e php,html,js
python3 dirsearch.py -u https://target -e php,html,js -w /path/to/wordlist
python3 dirsearch.py -u https://target -r --max-recursion-depth 3
```

Use `python3 dirsearch.py -h` for the full CLI help.

## Python API

dirsearch can also be used from Python code for local automation, MCP servers,
REST wrappers, and agent-controlled scans. The importable API keeps its
configuration in `FuzzerConfig`, so callers do not need to parse CLI flags or
mutate CLI globals.

See [Python API](docs/python-api.md) for examples covering templates, custom
wordlists, callbacks, authenticated sessions, and agent-oriented scan recipes.

## Contributing

Pull requests and feature requests are welcome. See [CONTRIBUTORS.md](CONTRIBUTORS.md) for the people who have helped improve dirsearch.

## License

Copyright (C) Mauro Soria (maurosoria@gmail.com)

License: GNU General Public License, version 2.
