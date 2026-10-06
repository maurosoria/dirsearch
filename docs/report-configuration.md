# Report configuration ownership

`ReportConfig` is the immutable policy for one report manager. It contains the
ordered formats, file/table destination templates, database URLs and SQLite
commit batch size. It contains no connections, locks, pending rows or journals.

| Previous global reads | New boundary | Consumer |
| --- | --- | --- |
| `output_formats` passed separately to the manager | `ReportConfig.formats` | Enabled reporters, preserving order |
| `output_file`, `output_table`, `mysql_url`, `postgres_url` in `ReportManager` | Frozen destination fields | Per-target formatting and report creation |
| `sqlite_commit_batch_size` in `SQLiteReport` | Explicit constructor argument from the config | Existing SQLite commit/flush policy |

`Controller.setup()` snapshots normalized options when creating the manager.
`Controller._restore_session()` receives an explicit report policy prepared from
validated restored options. Session storage does not construct report managers.
`lib/report` Python modules no longer import the global options dictionary.

## Constructing a manager

```python
from lib.core.report_config import ReportConfig
from lib.report.manager import ReportManager

config = ReportConfig(
    formats=("json", "sqlite"),
    output_file="reports/{host}-{format}.{extension}",
    output_table="results",
    sqlite_commit_batch_size=25,
)
manager = ReportManager(config)
try:
    manager.prepare("https://example.test/")
    # Feed actual response objects to manager.save() or await manager.save_async().
finally:
    manager.finish()
```

The internal manager constructor requires `ReportConfig`; it does not accept a
format list plus ambient settings. The options adapter expects normalized input
from CLI/session preparation and does not implement a second parser. Unset
formats (`None`) mean no reports, matching the options default. Format lists are
copied into a tuple, and credential-bearing database URLs are excluded from
the config's representation. No credential or destination is added to logs.

Destination templates remain unexpanded until `prepare()` or `save()` has a
target. Existing tokens, format order and missing-destination behavior remain
unchanged. Optional database reporters are imported only if their format has
all required destinations; unavailable drivers and unknown formats still fail
instead of being silently skipped.

`SQLiteReport()` now has a deterministic batch size of one. Callers needing
batching pass `commit_batch_size` explicitly; `None` is not a global-options
fallback. Existing positive-integer validation remains in the reporter and the
CLI/session validation boundary.

## Persistence and lifecycle

Each manager retains its reporters, destination sources and async-save lock.
Reporters retain their connections, journal state and pending writes. Replacing
or clearing the original options cannot reroute an existing manager or change
its batch policy. Independent managers must still use independent destinations;
this does not add multi-process coordination for shared files or databases.

[RunMetadata](run-metadata.md) separately supplies the redacted command and start
label. The controller shares one immutable value with the manager and reporters;
standalone managers can receive `metadata=` or capture a new value at construction.
Headers and date tokens no longer read import-time `COMMAND` / `START_TIME` values.

The async executor handoff and cancellation drain are unchanged. SQLite still
commits at its configured boundary and flushes partial batches at explicit
flush, destination changes and finish. Controller checkpoint export continues
to flush report rows before saving progress. This refactor changes neither
recovery behavior nor power-loss durability guarantees.

## Sessions and remaining boundaries

Sessions still store normalized options, not `ReportConfig` objects. Resume
merges saved options at the existing controller boundary and rebuilds the
manager; no checkpoint schema or engine-specific format is introduced.

Target progress now belongs to [ScanRunState](scan-run-state.md), and target
preparation hints to [TargetConfig](target-configuration.md). Raw response capture
destinations, terminal presentation, replay destinations and logging remain
separate ownership work. Complete
concurrent controllers are not yet supported. There is no Rust change, new
batch default, extra Python/Rust call or claimed throughput improvement.

## Validation

Run `python -m unittest discover -s tests -t .`. Coverage includes:

- Immutable format lists, supplied-mapping adaptation and database URL repr safety.
- All reporter destination mappings, missing destinations, optional import failures
  and unknown formats, without connecting to external databases.
- A regression where restored report policy's destinations and SQLite batch differ
  from process globals; the old implementation selected the global destination.
- Real controller setup and JSON checkpoint restoration for all three engine
  selectors, followed by two target-specific JSON/SQLite artifacts.
- Independent managers and batches, with assertions on rows visible before and
  after flush/finish, plus existing async cancellation and checkpoint-flush tests.
- Existing deterministic loopback CLI contracts across threaded, async and native.

`tests/check_packaged_install.py` imports `ReportConfig` from the installed
package. Setuptools includes it under `lib.core`; PyInstaller's existing
`collect_submodules('lib')` includes the new module. No dependency, packaging
rule or workflow change is required.
