# Invocation metadata ownership

`RunMetadata` owns the redacted command and local-time start label used in report
headers and `{date}` / `{datetime}` destination tokens. These values previously
came from `COMMAND` and `START_TIME` in `settings.py`, captured when Python first
imported the module. A second invocation in the same process could therefore use
the first invocation's command and date.

## Capture and ownership

`main()` captures metadata before parsing options or asking whether to resume.
It passes the immutable value to `Controller`, which passes the same object to
`ReportManager` and every reporter. Metadata has no live handles, mutable option
mapping, raw argv reference or target progress. `capture()` uses the existing
`redact_command` policy; this refactor does not change which arguments it redacts.
The command field is also excluded from the dataclass representation.

Direct callers can capture once and inject the value:

```python
from lib.core.report_config import ReportConfig
from lib.core.run_metadata import RunMetadata
from lib.report.manager import ReportManager

metadata = RunMetadata.capture(["dirsearch", "-w", "words.txt"])
manager = ReportManager(
    ReportConfig(formats=("json",), output_file="reports/{datetime}.json"),
    metadata=metadata,
)
try:
    manager.prepare("https://example.test/")
finally:
    manager.finish()
```

Calling `Controller()`, `ReportManager(config)` or an individual reporter without
metadata captures a new value at construction, never at module import or each
write. Explicit empty argv stays empty. Direct `RunMetadata(command, start_time)`
construction is useful for deterministic callers but expects an already redacted
command and a local-time label in `YYYY-MM-DD HH:MM:SS` format.

## Reports, paths and resume

JSON, XML, HTML, Markdown and plain-text reports use the injected metadata.
Simple, CSV and database output schemas are unchanged. Every reporter receives
the same object, including lazily imported optional database handlers. Rendering,
async saves, subsequent targets, or a midnight boundary do not recapture it.
Report paths and session paths use the same label; filesystem datetime tokens
retain the existing Windows-safe formatting.

This label is **not** the numeric `Controller.start_time` / `RunCheckpoint.start_time`
used for deadlines, progress and output history. Resume keeps that saved numeric
value while the new invocation gets its own presentation metadata, as a fresh
CLI process did before. The version-1 checkpoint schema remains unchanged; it
does not serialize `RunMetadata` or use it to choose a target or backend.

Existing file handling is unchanged: JSON/XML reopening retains stored headers;
plain/Markdown appends do not replace their old headers. HTML continues to render
its document with the current reporter's metadata when compacting stored results.
This change does not introduce metadata migration for existing reports.

## Scope and validation

This removes two import-time invocation values, not the global `options` mapping.
It does not enable concurrent controllers or change worker scheduling, transport
behavior, request batches, checkpoints or report durability. Capture/redaction
runs once per owning invocation, not once per request.

Tests cover two interleaved report managers with different commands/dates,
redaction of secret values, explicit empty input, immutable metadata, repeated
CLI entry, all metadata-bearing formats, existing JSON/XML headers, and session
path formatting without changing the saved progress clock. Setup/resume tests
exercise all three engine selectors without making network requests. The
installed-package smoke verifies importability and identity propagation through
controller restoration. Setuptools package discovery and PyInstaller's existing
`collect_submodules('lib')` include the new module without new build rules.
