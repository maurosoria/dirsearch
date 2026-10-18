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

## Calibration troubleshooting

Add `--log scan.log` to the failing command. The log includes DEBUG messages
without `--verbose`; that flag changes terminal presentation. Normal wildcard
and duplicate-threshold discards now include their cause and response lengths.
See [calibration safeguards](filter-configuration.md#distinct-content-safeguards)
for the scope of those messages.

Each received response now has a `RESPONSE` record with the engine, actual HTTP
response version, content encoding, reported length, retained decoded length,
capture completeness, SHA-256 of those retained bytes, redirect-hop count and
final URL (using the same credential/query redaction).
The version comes from urllib3, HTTPX or reqwest, not an assumption about the
engine default. It is `unknown` when the adapter does not expose it, including
the native byte-preserving raw HTTP fallback. `decision=match`, `excluded`,
`wildcard` and `duplicate` records explain the final Python-side disposition.
Existing calibration messages provide the more specific wildcard/threshold
reason where applicable.

`reported_length` is dirsearch's filtering/display length, which can use the
compressed `Content-Length`; `retained_length` counts decoded bytes actually
available in the response object. Equal lengths alone do not prove equal pages.
`retained_sha256` is stable across processes and engines, but compares only the
retained capture. If `body_complete=false`, it must not be interpreted as a hash
of the complete response. Native prefilters discard bodies before returning to
Python: their log includes the reason (`native_filter`) and metadata, but uses
`retained_sha256=unavailable`, not the hash of an empty response.

Bodies, cookies, authorization and arbitrary HTTP headers are not logged.
Content encoding is restricted to known coding names; URL credentials and query
values still pass through the existing redaction. A digest is not anonymization
for predictable bodies. Review logs before sharing, especially URL paths and
any error messages emitted by dependencies.

No diagnostic hash is computed without `--log`. Enabling it intentionally adds
file I/O and hashing of retained bodies. Native logging also returns metadata
for otherwise compacted filter exclusions, without transferring their bodies;
normal scans keep the existing compact progress-only path. Compare engines
with logging enabled consistently, not against an unlogged performance run.

For a filtering issue, repeat the failing command with `--log native.log`, then
run the same target, wordlist, filters and concurrency with the Python engine
and `--log python.log`. Include both logs and identify one missing path. This
lets maintainers compare protocol, compression, captured content and decision
without asking the reporter to calculate hashes manually. After upgrading a
native build, run `dirsearch-build-native` to rebuild the matching extension.

A portable way to package the log for an issue is:

```sh
python3 -m zipfile -c scan-log.zip native.log python.log
```

If rotation is enabled and a `.log.1` backup exists, include it as an additional input
to that command. This packages the existing logs; it does not collect config
files, sessions or response artifacts automatically.

## Scope and verification

The same run logger is borrowed by all three engines. Native result metadata
includes the actual response version, with an explicit extension-version guard
for the updated contract. The Rust chunk API has an opt-in `include_filtered`
diagnostic mode; no callback or file writer runs on network workers. Python
consumes metadata at the existing ordered chunk boundary. Native prefilters
still own filtering, including when logging is enabled.

No new CLI flags, dependencies, report formats or session formats are introduced.
The diagnostics do not change HTTP negotiation or establish why a remote CDN
or WAF responded differently. Complete concurrent-controller isolation remains
a separate [backlog](refactoring-backlog.md) acceptance step.

Regression tests cover independent destinations and policies, redacted
tracebacks, rotation, disabled logging, no root propagation or named-registry
retention, late writes after close, preparation/resume, consumer injection and
cleanup failures. Run `python -m unittest discover -s tests -t .`.
`tests/check_packaged_install.py` also exercises `LogConfig` and `RunLogger` from
an installed package. Setuptools discovery and PyInstaller's
`collect_submodules('lib')` include the policy module without new build rules.
