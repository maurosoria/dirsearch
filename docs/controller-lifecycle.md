# Explicit controller lifecycle

Construction and execution are separate; `run()` owns the complete, single-use
lifecycle. The CLI supplies its process interrupt scope explicitly:

```python
controller = Controller(options, metadata=metadata)
controller.run(interrupts=cli_interrupts(controller.handle_pause))
```

Calling `Controller(options).run()` without a scope does not install signal
handlers. This is useful for internal composition, not a new public API.
This is an internal refactor, not a replacement for the documented
`DirsearchFuzzer` Python API or a new scheduling interface.

## Phase boundaries

| Phase | Responsibility | Side effects |
| --- | --- | --- |
| `__init__` | Copy supplied input, capture/inject invocation metadata and borrowed output stream; initialize local state | Reads argv/clock when metadata is omitted; no global option reads, resource opening, preparation, requests or signal installation |
| `run()` bootstrap | Reject a repeated attempt, create terminal/logger and transfer them to `RunResources` | Opens bootstrap output history; closes it if logger construction fails before transfer |
| `_prepare()` | Select existing fresh `setup()` or session `_import()` | Validate input, prepare policies, dictionary, reports and stores at their existing boundaries |
| `_run_targets()` | Engine setup, optional interrupt scope and sequential target loop | Creates run-owned requester/loop; enters the supplied scope only after setup and restores handlers before resource cleanup |
| `run()` final cleanup | Always close attached `RunResources` after preparation/execution | Existing ordered teardown, including downstream cleanup after an earlier failure |

The target-loop behavior is unchanged. Engine
selection, worker draining, deadlines, recursion, report callbacks and session
continuation are not redesigned here. Configuration, persistence input and live
resources retain their separate owners.

## CLI interrupts and event loops

`lib.utils.cli.cli_interrupts()` is a lazy context manager, not stored in input,
configuration or checkpoints. Only the CLI supplies it. It borrows `SIGINT` and
`SIGTERM` at the existing execution boundary, forwards both to `handle_pause()`,
and restores their previous handlers on every ordinary exit. Partial registration
rolls back handlers already installed; cleanup attempts all restorations even
if one fails. Exceptions are not suppressed. No scope is entered when preparation,
loop creation or requester construction fails.

Signal registration still requires the main thread. Scopes must be strictly
nested and exclusively owned, not overlapped across independent executions.
The existing pause/continue/skip/save/quit menu and force-quit strategy are
unchanged. Force termination bypasses cleanup; a failed OS restoration is
reported, not silently treated as success.

`lib.controller.event_loop.create_event_loop()` creates an optional uvloop loop
directly, or uses asyncio when that optional import is unavailable. It does not
install a process-wide policy or set a current loop. Loop factory errors propagate.
The async loop is acquired before the requester so startup cannot leave an async
requester without a loop for cleanup. `RunResources` closes the loop, including
when requester construction fails. This adds no per-request or per-chunk work.

## Lifetime and failure contract

Before `run()`, `resources` is explicitly `None`; simply constructing and then
discarding a controller has no live handles to close. Metadata and the output
stream are captured at construction. Supplied options are now deep-copied too;
later changes to the caller's input cannot alter a deferred controller. See
[invocation-local options](invocation-options.md) for normalization ownership.

The execution attempt is consumed before reading bootstrap options or acquiring
resources. A second `run()` raises `RuntimeError` before starting work, whether
the first attempt succeeded, failed during preparation, was interrupted, or
failed during cleanup. Reentrant execution is rejected too. A failed startup is
not implicitly retryable on the same object; a new invocation needs a new owner.
This check is not a thread-safety guarantee.

Once resources are attached, `run()` closes them in `finally`, including on
`SystemExit` and `KeyboardInterrupt`. Bootstrap logger-construction failure
closes the terminal that has not yet been transferred. The terminal never closes
its borrowed output stream. Resource-specific close ordering, exception chaining
and no-retry semantics remain in [RunResources](run-resources.md). Force-quit
still bypasses ordinary cleanup.

`_prepare()` and `_run_targets()` are internal phases, not alternative public
entrypoints. Callers must not invoke them to bypass the lifecycle owner. There is
no public prepare-and-hold state, manual controller-close API or automatic-run
compatibility flag. Existing internal callers and fixtures move together.

## Limits and verification

The CLI still normalizes options, handles wordlist-only mode and confirms session
resume before entering the controller. Its output, exit behavior and metadata
ordering are preserved. The package entrypoint and standalone script use the
same explicit invocation; the public Python API is unchanged.

Signals now have a bounded CLI owner and loop creation no longer changes global
policy. [Raw targets](request-target-ownership.md) now belong to each request. This does not
enable concurrent controllers,
parallel targets, external scheduling, or independently executable checkpoints.
Those require separate designs and overlapping-execution acceptance tests; see the
[refactoring backlog](refactoring-backlog.md).

Run `python -m unittest discover -s tests -t .`. Lifecycle tests cover deferred
construction, fresh/resume ordering, repeated and reentrant execution, partial
startup failures, interruptions, borrowed stream ownership and independent local
resource owners. Existing preparation/resume tests now explicitly call `run()`;
isolated target-loop fixtures call `_run_targets()`. CLI tests assert execution
is invoked, and the existing loopback contracts exercise all three engines.
The installed-package smoke verifies both unstarted and completed resource states,
the interrupt scope and loop factory. Process-boundary tests cover unchanged
handlers for all three engine policies, worker-thread execution without signal
patches, scope rollback/restoration, startup/cleanup failures and optional uvloop
selection. POSIX subprocess contracts deliver real `SIGINT` and `SIGTERM` during
a loopback scan and exercise quit through the CLI menu for every available engine.

`tests.controller.test_lifecycle_acceptance` also exercises complete sequential
lifecycles with real loopback HTTP and no process-global patching. Its bounded
child-process runner isolates inherited proxies; the controllers within each
scenario share one process. It verifies detached options/headers, independent terminal streams,
JSON reports, JSONL response bodies, logs and progress; real output failure and
deadline cancellation followed by a healthy invocation; and full session-store
restoration with outstanding words, later directories and later targets. Each
available engine runs the same scenarios. It asserts worker/task cleanup, closed
stores and event loops, unchanged signal handlers/stdout, and no late log writes.
The resume fixture selects "new" at its instance-local overwrite-question seam;
it does not replace parsing, persistence, preparation, execution or cleanup.
These tests do not prove simultaneous execution or a distributed task contract.

No dependencies, CLI flags, checkpoint/report schemas, request pacing or native
chunk defaults are changed. The separate option-default factory is collected by
the existing packaging rules. No performance change is claimed.
