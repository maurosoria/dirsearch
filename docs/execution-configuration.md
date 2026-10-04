# Execution configuration ownership

`ExecutionConfig` holds immutable engine, worker, pacing and stop policy for one run.
`Controller.run()` constructs it after raw-request setup or session restoration,
before selecting requester/fuzzer classes, callbacks or an event loop. Transport,
filter and discovery snapshots follow at the same preparation boundary. The
controller passes the same execution policy to every target's fuzzer.

| Previous global reads | Current owner | Consumers |
| --- | --- | --- |
| `request_backend`, `async_mode` in the running controller | `ExecutionConfig.engine` (`ScanEngine`) | Requester/fuzzer selection, report/response callbacks, root crawl, replay, dispatch, pause and worker-drain routing |
| `thread_count` in `lib/core/fuzzer.py` | `ExecutionConfig.concurrency` | Thread count, async workers/semaphore, native dictionary claim size |
| `delay` in `lib/core/fuzzer.py` | `ExecutionConfig.delay` | Python worker pacing and all engines' calibration scanners |
| `max_time`, `target_max_time` in `lib/controller/controller.py` | `ExecutionConfig` | Threaded polling and async/native deadlines |
| `skip_on_status`, `exit_on_error` in the controller | `ExecutionConfig` | Match and error callbacks |

`lib/core/fuzzer.py` no longer imports global `options`. Internal constructors
require explicit execution, discovery and filter policies, with no fallback to
process-wide options. Numeric validation remains at the existing CLI/session
boundary; this config freezes normalized input rather than implementing a
second parser. Status collections are copied into a frozenset.

```python
from lib.core.execution_config import ExecutionConfig, ScanEngine

policy = ExecutionConfig(
    engine=ScanEngine.THREADED,
    concurrency=3,
    delay=0.1,
    max_time=60,
    target_max_time=10,
    skip_on_status={429},
    exit_on_error=False,
)
```

Pass `execution_config=policy` when constructing `Fuzzer`, `AsyncFuzzer` or
`NativeFuzzer`, together with the existing policies and callbacks. Create new
configuration and consumers to change execution policy; do not replace it under
active workers.

## One engine per run

The existing CLI/session selectors are converted into one enum value:

| `request_backend` | `async_mode` | `ExecutionConfig.engine` |
| --- | --- | --- |
| `python` | `False` | `ScanEngine.THREADED` |
| `python` | `True` | `ScanEngine.ASYNC` |
| `native` | `False` | `ScanEngine.NATIVE` |

Native plus async is rejected with the same diagnostic as CLI validation.
Unknown backend names are also rejected, not silently dispatched as threaded.
This check runs before requester or loop construction, including on resume.
Manual `ExecutionConfig` construction requires a `ScanEngine`, not a string.

Runtime branches use the frozen enum rather than re-reading selector flags.
Only async owns an asyncio loop and awaitable callbacks; threaded/native keep
inline callbacks. Native retains its filtered-result chunk callbacks, and only
threaded uses the threaded worker-drain path. Changing global flags after
preparation cannot switch those paths for later targets. Requester cleanup
continues to use the loop actually created, including after partial startup.

CLI/raw-request validation and wordlist preparation still consume normalized
selector input at their existing boundaries. There is no new CLI flag or fuzzer
constructor argument; the enum travels in the existing execution policy.

## Transport versus execution

`RequestConfig` still owns connection-pool concurrency, rate limits and native
transport pacing. `ExecutionConfig` owns the fuzzer/controller consumers listed
above. Both snapshots take concurrency and delay from the same normalized input
at the run boundary; they do not read one another or mutate live transports.
Manual composition must supply consistent transport and execution settings.

Native request concurrency and delay continue to reach Rust through the existing
request adapter. The Python/native dictionary claim formula remains
`max(1000, concurrency * 100)`. This is not the incremental result-delivery chunk
size or its flush interval; neither is changed here. The ABI, Rust loop, corpus
ownership and callback protocol are unchanged. No extra Python/Rust call per
request or throughput improvement is claimed.

## Lifecycle and deadlines

Config contains no queues, threads, tasks, locks, counters, start timestamps or
cancellation events. Those retain their existing owners and lifetimes.
Resetting a dictionary for a new job or target does not change policy. Stopping
workers, draining async tasks and cancelling the native engine retain their
existing implementation and shutdown budgets.

Zero time limits still disable their respective deadlines. Total-run and
per-target limits retain their existing clocks, starting points, messages and
exception precedence. This refactor intentionally does not unify boundary
checks: threaded polling uses `elapsed > limit`, while the async/native startup
check rejects `remaining <= 0`. Interrupted work and worker-drain behavior are
covered by the existing lifecycle tests.

## Sessions and remaining work

Checkpoints still serialize normalized options and runtime progress, not config
objects. Resume rebuilds execution policy after restoring session options and
before starting any target. No checkpoint schema or engine-specific state is
added; existing saved start-time semantics are unchanged.

[ReportConfig](report-configuration.md) now owns report destinations and SQLite
batch policy. Target queues/routing, terminal and raw-response output, replay
destinations and remaining controller/logging globals are separate migration
steps. This does not make complete controllers safe to run concurrently, even though individual fuzzers
no longer read global options.

## Validation

Run `python -m unittest discover -s tests -t .`.

- Immutable status inputs and complete mapping adaptation.
- All three selector mappings; invalid combinations and unknown backends fail
  before requester/loop creation without a traceback.
- Engine choice, report/response callbacks, native filtered chunks and cleanup
  across two targets even when global selectors change after preparation.
- Root crawl, replay, directory dispatch and pause quit/save/skip routing follow
  the frozen engine, with empty or deliberately contradictory global selectors.
- Threaded/async worker counts and pacing with global options empty.
- Simultaneous async fuzzers retaining separate concurrency limits, with bounded
  event coordination and cancellation/drain assertions.
- Calibration delay for every profile and every engine; native claim-size boundaries.
- Disabled/expired deadlines, exception precedence, status/error stop policy.
- Prepared policy shared across targets and actual JSON session restoration for
  all three request-stack configurations, with transport settings kept aligned.
- Existing lifecycle, native integration and deterministic loopback CLI contracts.

`tests/check_packaged_install.py` imports the config and enum. Setuptools discovers
the module through `lib.core`; PyInstaller's existing `collect_submodules('lib')`
includes it. Native integration requires the matching optional extension and skips when
it is absent.
