# AGENTS.md - AI Agent Guidelines for dirsearch

This document provides guidelines for AI agents (Claude Code, GitHub Copilot, Cursor, etc.) working with the dirsearch codebase.

## Project Overview

**dirsearch** is an advanced Python-based web path brute-forcer for discovering hidden directories and files on web servers. It's used for:
- Bug bounty hunting
- Penetration testing
- Security research
- Vulnerability assessment

**Key Facts:**
- Python 3.9+ required
- License: GNU GPL v2
- Maintainers: [@maurosoria](https://github.com/maurosoria), [@shelld3v](https://github.com/shelld3v)

## Repository Structure

```
dirsearch/
├── dirsearch.py              # Main entry point
├── config.ini                # Default configuration
├── requirements.txt          # Dependencies (pinned versions)
├── setup.py                  # Package installation
├── testing.py                # Unit test runner
│
├── lib/                      # Core library
│   ├── core/                 # Business logic
│   │   ├── data.py           # Global options dictionary
│   │   ├── options.py        # Option parsing/merging
│   │   ├── settings.py       # Constants and configuration
│   │   ├── dictionary.py     # Wordlist management
│   │   ├── fuzzer.py         # Fuzzing engine
│   │   ├── scanner.py        # Response analysis, wildcard detection
│   │   ├── logger.py         # Logging setup
│   │   ├── exceptions.py     # Custom exceptions
│   │   ├── decorators.py     # @locked, @cached utilities
│   │   └── structures.py     # CaseInsensitiveDict, OrderedSet
│   │
│   ├── connection/           # HTTP/network operations
│   │   ├── requester.py      # HTTP clients (sync/async)
│   │   ├── response.py       # Response handling
│   │   └── dns.py            # DNS caching
│   │
│   ├── controller/           # Main execution flow
│   │   ├── controller.py     # Main Controller class
│   │   └── session.py        # Session persistence
│   │
│   ├── parse/                # Input parsing
│   │   ├── cmdline.py        # CLI arguments (optparse)
│   │   ├── config.py         # INI config parsing
│   │   ├── headers.py        # HTTP header parsing
│   │   ├── url.py            # URL manipulation
│   │   ├── rawrequest.py     # Raw HTTP request parsing
│   │   └── nmap.py           # Nmap XML parsing
│   │
│   ├── report/               # Output generation
│   │   ├── manager.py        # Report orchestration
│   │   ├── factory.py        # Base classes/mixins
│   │   ├── *_report.py       # Format implementations
│   │   └── templates/        # Jinja2 HTML templates
│   │
│   ├── utils/                # Helper utilities
│   │   ├── common.py         # Path ops, IP ranges, stdin
│   │   ├── file.py           # File operations (FileUtils)
│   │   ├── crawl.py          # HTML crawling
│   │   ├── diff.py           # Dynamic content detection
│   │   ├── mimetype.py       # MIME type detection
│   │   ├── random.py         # Random string generation
│   │   └── schemedet.py      # URI scheme detection
│   │
│   └── view/                 # Terminal UI
│       ├── terminal.py       # CLI output (colors, formatting)
│       └── colors.py         # Color management
│
├── db/                       # Static resources
│   ├── dicc.txt              # Default wordlist
│   ├── user-agents.txt       # User-Agent strings
│   ├── *_blacklist.txt       # Status code blacklists
│   └── categories/           # Wordlist categories
│
├── sessions/                 # Saved scan sessions (JSON)
│
└── tests/                    # Unit tests (mirrors lib/)
    ├── connection/
    ├── controller/
    ├── core/
    ├── parse/
    └── utils/
```

## Key Modules Reference

| Module | Purpose | Key Classes/Functions |
|--------|---------|----------------------|
| `lib/core/data.py` | Global state | `options` dict, `blacklists` dict |
| `lib/core/options.py` | Option handling | `parse_options()` |
| `lib/core/settings.py` | Constants | 150+ settings/constants |
| `lib/core/dictionary.py` | Wordlist mgmt | `Dictionary` class |
| `lib/core/fuzzer.py` | Scanning engine | `Fuzzer`, `AsyncFuzzer` |
| `lib/core/scanner.py` | Response analysis | `Scanner`, `AsyncScanner` |
| `lib/connection/requester.py` | HTTP clients | `Requester`, `AsyncRequester` |
| `lib/controller/controller.py` | Orchestration | `Controller` class |
| `lib/controller/session.py` | Persistence | `SessionStore` class |
| `lib/parse/cmdline.py` | CLI parsing | `parse_arguments()` |
| `lib/report/manager.py` | Report mgmt | `ReportManager` class |

## Coding Conventions

### File Header Template
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#  Author: Mauro Soria

from __future__ import annotations
```

### Import Order
1. `from __future__ import annotations`
2. Standard library imports
3. Third-party library imports
4. Local `lib` imports

### Naming Conventions
- **Constants**: `UPPER_CASE_WITH_UNDERSCORES`
- **Functions/Methods**: `snake_case`
- **Classes**: `PascalCase`
- **Private attributes**: `_name` prefix
- **Base classes**: `Base*` prefix (e.g., `BaseRequester`)
- **Mixins**: `*Mixin` suffix (e.g., `FileReportMixin`)

### Type Hints
Use type hints extensively:
```python
from typing import Any, Callable, Generator

def process(data: dict[str, Any]) -> list[str]:
    ...

def scan(target: str) -> Generator[Response, None, None]:
    ...
```

### Thread Safety
Use the `@locked` decorator from `lib/core/decorators.py` for thread-critical sections:
```python
from lib.core.decorators import locked

@locked
def critical_operation(self):
    # Thread-safe code
    ...
```

### Caching
Use the `@cached` decorator for time-based memoization:
```python
from lib.core.decorators import cached

@cached(timeout=60)
def expensive_lookup(self, key: str) -> str:
    ...
```

## Testing

### Running Tests
```bash
python3 testing.py
```

### Test Structure
Tests mirror the `lib/` structure:
- `tests/core/test_scanner.py` tests `lib/core/scanner.py`
- `tests/utils/test_common.py` tests `lib/utils/common.py`

### Writing Tests
Use Python's `unittest` framework:
```python
import unittest

class TestMyFeature(unittest.TestCase):
    def setUp(self):
        # Setup code
        pass

    def test_feature_behavior(self):
        # Test code
        self.assertEqual(expected, actual)

if __name__ == "__main__":
    unittest.main()
```

Add new test imports to `testing.py`:
```python
from tests.module.test_new_feature import *
```

## Common Development Tasks

### Adding a New CLI Option
1. Add option in `lib/parse/cmdline.py` using `optparse`
2. Add default value in `config.ini` (appropriate section)
3. Handle in `lib/core/options.py` if special processing needed
4. Document in `README.md`

### Adding a New Report Format
1. Create `lib/report/new_report.py`
2. Extend `BaseReport` (and appropriate mixin)
3. Register in `lib/report/factory.py`
4. Update `lib/core/settings.py` constants
5. Add tests in `tests/report/`

### Adding a New Utility Function
1. Add to appropriate file in `lib/utils/`
2. Add tests in corresponding `tests/utils/test_*.py`
3. Import in relevant modules

### Modifying Request Handling
Key files:
- `lib/connection/requester.py` - HTTP client logic
- `lib/connection/response.py` - Response processing
- `lib/core/fuzzer.py` - Request orchestration

## Key Patterns

### Global Options Access
```python
from lib.core.data import options

# Read options
thread_count = options["threads"]

# Options are set once at startup, treat as read-only during scan
```

### Custom Exceptions
```python
from lib.core.exceptions import (
    InvalidURLException,
    RequestException,
    SkipTargetInterrupt,
    QuitInterrupt,
)

# Raise for invalid input
raise InvalidURLException("Invalid target URL")

# Raise to skip current target
raise SkipTargetInterrupt()

# Raise to quit gracefully
raise QuitInterrupt()
```

### File Operations
```python
from lib.utils.file import FileUtils

# Use FileUtils for consistent file handling
content = FileUtils.read(path)
FileUtils.write(path, content)
lines = FileUtils.read_lines(path)
```

### Response Filtering Logic
The fuzzer filters responses using:
1. Status code (include/exclude lists)
2. Response size (min/max thresholds)
3. Content matching (text, regex)
4. Redirect URL patterns
5. Wildcard detection (scanner)

## Security Considerations

### When Modifying This Codebase
- **Never** store credentials in code
- Use `defusedxml` for XML parsing (XXE prevention)
- Use `defusedcsv` for CSV operations
- Validate all user input (URLs, paths, headers)
- Handle encoding issues gracefully
- Respect rate limiting and connection limits
- Don't expose internal errors to users

### Sensitive Data Handling
- Session files contain scan configuration
- Output files may contain discovered paths
- Credentials are handled via authentication options
- Proxy credentials are passed through options

## Important Constants (lib/core/settings.py)

```python
MAX_CONSECUTIVE_REQUEST_ERRORS = 75  # Fail-safe limit
MAX_RESPONSE_SIZE = 80 * 1024 * 1024  # 80MB limit
SOCKET_TIMEOUT = 6  # seconds
DB_CONNECTION_TIMEOUT = 45  # seconds
TEST_PATH_LENGTH = 6  # Wildcard test path length
RATE_UPDATE_DELAY = 0.15  # seconds
```

## Dependencies

Key libraries used:
- `requests` / `httpx` - HTTP clients (sync/async)
- `beautifulsoup4` - HTML parsing
- `Jinja2` - HTML report templates
- `colorama` - Cross-platform colors
- `ntlm-auth` - NTLM authentication
- `PySocks` - SOCKS proxy support
- Database drivers: `mysql-connector-python`, `psycopg`

All versions are pinned in `requirements.txt` to ensure reproducibility and prevent supply chain attacks.

## Data Flow

```
dirsearch.py
    ↓
parse_options() → CLI + config.ini merge
    ↓
Controller()
    ├── Load targets
    ├── Build Dictionary (wordlist)
    ├── Create Scanner (wildcard detection)
    └── For each target:
        ├── Fuzzer.fuzz()
        │   ├── Requester.request()
        │   ├── Response filtering
        │   ├── Scanner.check()
        │   └── Callbacks → ReportManager
        └── Recursion handling
            ↓
        ReportManager.finish()
```

## PR Guidelines

When submitting changes:
1. Follow existing code style and conventions
2. Add tests for new functionality
3. Update documentation if adding features
4. Keep changes focused and minimal
5. Test with `python3 testing.py`
6. Verify no regressions in existing features

## Quick Reference

| Task | Command/File |
|------|-------------|
| Run dirsearch | `python3 dirsearch.py -u URL` |
| Run tests | `python3 testing.py` |
| Config file | `config.ini` |
| Main entry | `dirsearch.py` |
| Global options | `lib/core/data.py` |
| Constants | `lib/core/settings.py` |
| CLI options | `lib/parse/cmdline.py` |
| Default wordlist | `db/dicc.txt` |
| Sessions dir | `sessions/` |

## Environment Variables

- `DIRSEARCH_CONFIG` - Override default config file location

## Getting Help

- README.md - Comprehensive usage documentation
- CHANGELOG.md - Version history
- CONTRIBUTORS.md - Project contributors
- GitHub Issues - Bug reports and feature requests
