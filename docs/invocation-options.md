# Invocation-local options

The CLI owns its mutable input. `default_options()` creates fresh fallback values
for each `main()` call; parsed CLI/config values overlay that local mapping.
`Controller(options, ...)` deep-copies the supplied mapping at construction.
There is no `lib.core.data.options` singleton or compatibility proxy.

## Ownership and preparation

| Owner | Data and lifetime |
| --- | --- |
| CLI `main()` | Fresh defaults plus parsed input; wordlist-only handling and resume confirmation stay here |
| `Controller._options` | Detached mutable invocation input, including raw-request normalization, restored values and the session destination |
| `RunConfig` | Immutable runtime policies captured after preparation |
| `SessionOptions` | Separate captured persistence input, excluding the target queue |
| `ScanRunState` / `TargetProgress` | Live target ordering and progress, not CLI normalization storage |

Constructing a controller still opens no resources and runs no scan. It now
captures input as well as metadata and the borrowed output stream: later edits
to the caller's lists, sets or headers cannot change deferred execution. The
internal constructor requires explicit input; it does not parse argv, fill in
missing fields or consult a fallback global. The documented `DirsearchFuzzer`
Python API is unchanged.

Fresh setup merges default headers or parses a raw request in the owned mapping.
Session resume overlays saved values on this invocation's input, validates them,
restores target descriptors and keeps the explicitly selected checkpoint path.
The overwrite/new prompt changes only this controller's save destination and
captured persistence value. Failed preparation cannot publish partial input into
another invocation. Existing overlay precedence, unknown fields, explicit nulls,
session JSON, CLI diagnostics and exit behavior are preserved.

Policies and persistence input remain detached from normalization storage. No
component receives the whole options mapping as a substitute for its narrow
configuration. Copying happens at construction/preparation, not per request or
native chunk. No change to Rust scheduling or throughput is claimed.

## Tests and limits

Tests now create their own option fixtures. Calibration, request and report
tests no longer import a runtime singleton or save/restore process-wide options;
local `patch.dict` contexts remain where one test varies its own fixture across
subcases. Preparation doubles explicitly mutate the controller's owned input.

`tests/controller/test_invocation_options.py` covers independent mutable defaults,
repeated CLI entry, nested input copies, interleaved preparation, raw requests
and failure isolation. Existing session, target-loop and engine-contract tests
continue to exercise all three engines. Installed-package smoke tests import the
factory and pass explicit input to the controller.

This removes the mutable global options dictionary, not all process state.
Signals, optional event-loop policy and raw-target context still require explicit
ownership and acceptance coverage before concurrent complete controllers are
supported. See the [refactoring backlog](refactoring-backlog.md).
