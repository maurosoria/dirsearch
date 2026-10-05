# Result configuration and ownership

`ResultConfig` is the immutable policy for presenting, capturing and replaying
matched results. The controller snapshots it after raw-input preparation or
session restoration and before opening response stores. Every target in that
run uses the same snapshot; later changes to global options cannot redirect a
capture, change full-URL presentation or enable/disable/change replay.

| Normalized input | Frozen field | Consumer |
| --- | --- | --- |
| `save_response` | `response_directory` | Directory response-store factory |
| `save_response_jsonl` | `response_jsonl_file` | JSONL response-store factory |
| `full_url` | `full_url` | Controller's terminal match callback |
| `replay_proxy` | `replay_proxy` | Controller's existing replay dispatch |
| Either nonempty response destination | Derived `capture_full_body` | Transport configuration during composition |

This separates policy from resources: the controller still owns its open stores,
the stores still own their locks and pending writes, and `ResponseArtifact`
remains the backend-neutral data passed to them. `ReportConfig` continues to own
report formats/destinations; `TerminalConfig` owns quiet/color/output mode.
Quiet-mode full-URL presentation retains its existing precedence. The replay
proxy may contain credentials and is excluded from the policy's representation.

## Transport and callback boundaries

`Controller.run()` derives the transport's `capture_full_body` flag from the
already-prepared result policy, using `dataclasses.replace` before requester
construction. This keeps stores and the transport snapshot consistent even if
options changed after store creation. It happens once per run, not per request
or chunk. Paths are not passed into the transport or Rust. The standalone
`RequestConfig.from_options()` adapter retains its existing contract.

Threaded and async transports continue to use the flag for response reading.
The native requester receives the same request-policy object, but native body
limits and capture behavior are unchanged; this does not add a Rust capture
option or promise unlimited bodies. Artifact completeness/truncation fields
continue to describe what was actually captured.

Replay still uses the existing requester, target state and configured replay
proxy: synchronous/native callbacks replay inline; async callbacks return the
awaitable that their callback runner awaits and cancels with its worker. No new
requests, retry behavior, proxy semantics, recursion or discovery rules are added.

## Preparation, persistence and cleanup

Fresh setup and resume use the same policy adapter. Restored session options,
not the pre-resume CLI values, choose capture destinations and presentation.
The current engine-independent checkpoint schema remains unchanged: it still
stores normalized options, not config objects or open handles. Migrating that
persistence boundary is the next [refactoring step](refactoring-backlog.md).

The response-store factory still closes previously created stores if a later
store fails to open. Preparation errors stop execution before requester creation.
Saving, async cancellation draining, write error handling and final closure keep
their existing implementation. Separate runs need separate destinations or
external coordination when sharing the same physical output files.

## Verification and limits

Tests cover immutable supplied-mapping adaptation, credential-safe repr, empty
destinations, independently prepared captures, artifact bytes/completeness,
global-option changes, raw preparation, real checkpoint restoration, multiple
targets and transport/callback wiring for all three engines. Replay lifecycle
and response-store failure/cancellation regressions remain in the full suite.

Run `python -m unittest discover -s tests -t .`. The installed-package check also
imports `ResultConfig` and creates stores from its destinations. Setuptools
discovery and PyInstaller's `collect_submodules('lib')` already include the module.
This refactor does not yet make complete controllers safe to run concurrently.
