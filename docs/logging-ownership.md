# Logging configuration and ownership

`LogConfig` snapshots the normalized file path, rotation size and configured
proxy credentials used for redaction. It is frozen, excludes credentials from
its representation, and never reads global options during formatting.

| Responsibility | Owner |
| --- | --- |
| File and redaction policy | Immutable `LogConfig` |
| Handler and formatter lifetime | `RunLogger`, owned by the controller's `RunResources` |
| Emitting existing messages | Requesters, fuzzers and scanners borrow the logger |
| Early raw-request parse errors | Parser raises; controller handles diagnostics |

The controller's explicit `run()` starts with disabled logging and prepares its
effective logger after raw input preparation or session restoration. Target transitions reuse
that logger. Checkpoints still store the existing normalized options; no live
logger is serialized and the engine-independent session schema is unchanged.
Errors before the logging preparation boundary remain terminal diagnostics.

`RunLogger` is constructed directly, not retrieved from Python's process-global
named logger registry. It neither replaces another run's handlers nor propagates
records to the host application's root logger. Standalone components default to
a disabled, resource-free logger; callers can explicitly supply a borrowed one.
There is no module-level `logger` or `enable_logging()` compatibility shim.

## Redaction and cleanup

Rendered messages and tracebacks retain the existing redaction of URL userinfo,
query values, bare query tokens and explicitly configured proxy credentials.
Each formatter keeps its own credential snapshot, including credentials with
slashes that cannot be inferred reliably from a generic URL pattern. It is not
a general-purpose scrubber for arbitrary secrets or HTTP headers.

Controller cleanup delegates to [RunResources](run-resources.md), closing logging
after reports, requesters, response stores and terminal cleanup, including their
failure paths. Borrowers do not close it.
`close()` disables new records, detaches the owned handler and acquires the
standard handler lock to drain a current local file write. The file handler also
rejects records dispatched before close but arriving at emission afterwards;
append mode cannot reopen the file after closure. Repeated close is harmless.
These locks cover local file operations, not requests or worker joins. A blocked
filesystem can still block its logger; force-quit does not promise a drain.

Rotation still keeps one backup at the configured size. Separate destinations
are isolated; callers must not independently rotate the same physical log file.
No process-wide destination registry or cross-process file locking is introduced.

## Scope and verification

This is ownership isolation, not a change to logging parity or scan execution.
The native path's existing Python-side diagnostics use the run logger, but no
per-request logging bridge is added to Rust. The native request loop and ABI,
network behavior, CLI flags, dependencies and report/session formats are unchanged.
Global options and other process-wide state still prevent claiming complete
concurrent-controller isolation; see the [backlog](refactoring-backlog.md).

Regression tests cover independent destinations and policies, redacted
tracebacks, rotation, disabled logging, no root propagation or named-registry
retention, late writes after close, preparation/resume, consumer injection and
cleanup failures. Run `python -m unittest discover -s tests -t .`.
`tests/check_packaged_install.py` also exercises `LogConfig` and `RunLogger` from
an installed package. Setuptools discovery and PyInstaller's
`collect_submodules('lib')` include the policy module without new build rules.
