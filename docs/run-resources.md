# Run resource ownership

`Controller.resources` is one `RunResources` instance for the controller's
single-use lifecycle. It owns live handles, not configuration or checkpoint
data. This internal object is not a public execution API or a service locator:
components continue to borrow individual requesters, loggers and other handles.

## Boundaries

| Owner | Responsibility |
| --- | --- |
| `RunConfig` | Immutable prepared policies |
| `SessionOptions`, `SessionSnapshot` | Detached persistence input and checkpoint data |
| `RunMetadata` | Invocation command and display date |
| `TaskSpec` | Original target input |
| `ScanRunState`, `TargetProgress`, dictionary | Existing mutable run/target continuation |
| `RunResources` | Terminal, logger, report manager, requester, event loop and response stores |
| `Controller` | Construction, execution, worker draining and composition of these boundaries |

The controller creates handles only inside its explicit `run()` lifecycle, at
the existing preparation points. A bootstrap terminal and disabled logger exist
before effective input is ready; the resource owner starts with those handles
and explicit empty optional fields.
After raw parsing or validated resume, the controller constructs replacements
from prepared policies. `replace_terminal()` and `replace_logger()` adopt the
new handle before closing the bootstrap handle. If construction fails, the
original remains owned; if bootstrap closure fails, final cleanup owns the new
handle. Ordinary target transitions reuse the same resources.

There are no forwarding aliases such as `Controller.requester`, and no dynamic
attribute fallback for partially initialized resource owners. Type-only imports
avoid eagerly loading optional transport backends when this module is imported.
Live handles are excluded from the object's representation.

## Cleanup contract

The controller's final cleanup calls `resources.close()` once. The order is:

1. Finish reports, unless already attempted on normal completion or quit.
2. Close the requester; for async, await its close on the owned event loop,
   then close that loop even when requester closure fails. A loop with no
   requester is also closed. Threaded and native requesters close directly.
3. Close response stores, preserving the existing per-store `OSError`
   diagnostics and continuation to the following store.
4. Close the terminal's owned output history, not its borrowed output stream.
5. Close the logger, after its borrowers and cleanup diagnostics.

Nested `finally` blocks preserve downstream cleanup attempts if an earlier phase
raises. Exceptions are not silently swallowed: a later cleanup exception can
supersede an earlier one, with ordinary Python exception chaining. Non-`OSError`
store failures still propagate; this is not a new aggregate-error policy.

`finish_reports()` records an attempt even if it fails. `close()` likewise allows
only one complete teardown attempt. Calling either again does not retry failed
releases. This avoids duplicate final output and duplicate closure; it is not a
guarantee that a failing resource successfully released everything. Do not attach
or reuse handles after closure. The owner is not thread-safe, and its synchronous
close must not be called from inside its running event loop.

Worker stop/drain and cancellation still belong to the controller and engines;
this object adds no cancellation algorithm. Existing force-quit paths bypass
normal cleanup. Resource factories remain responsible for failures before a
handle is returned; the owner can close only handles already attached to it.

## Scope and validation

CLI flags, checkpoint/report formats, request dispatch, Rust ABI, native chunk
boundaries and batch defaults are unchanged. There is no throughput claim.
Global CLI normalization, process signals and ambient contexts remain;
independent resource owners alone do not prove complete concurrent-controller
safety. The [controller lifecycle](controller-lifecycle.md) now separates
construction from execution; the constructor opens no handles. Further isolation
remains in the [refactoring backlog](refactoring-backlog.md).

Run `python -m unittest discover -s tests -t .`. Resource tests cover cleanup
order, early report completion, partial preparation, repeated closure, independent
owners, replacement failures, each teardown failure, exception chaining, real
event-loop awaiting and cancellation during requester close. Existing controller
tests exercise preparation/resume, terminal/log files, response artifacts, worker
draining and all three engines. Unit fixtures explicitly construct `RunResources`
instead of relying on undeclared controller fields.

The installed-package smoke verifies resource-owner identity during controller
execution and report callback selection. Setuptools package discovery and
PyInstaller's `collect_submodules('lib')` include the module without new
dependencies or packaging rules.
