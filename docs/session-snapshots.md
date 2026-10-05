# Session persistence boundary

Session persistence remains Python-owned and engine-independent. `SessionStore`
reads, validates and writes the existing version-1 JSON representation; it does
not read a live controller, retain run options, construct dictionaries/reporters,
or mutate the caller's output history.

## Ownership and ordering

| Stage | Owner | Contract |
| --- | --- | --- |
| Preparation | Controller | Copy normalized options after raw-request setup or validated session restore. |
| Save preparation | Controller | Flush report rows, overlay active/pending targets from `ScanRunState`, and capture dictionary progress including outstanding claims. |
| Snapshot | `SessionSnapshot` | Own detached controller progress, dictionary progress, normalized options and output history; no runtime handles. |
| Persistence | `SessionStore.save(snapshot, path)` | Encode options and atomically replace the existing JSON checkpoint. |
| Commit history | Controller | Adopt the snapshot's history only after a successful save. |
| Resume | Controller | Validate restored options, rebuild its dictionary/report manager and retain normal resource cleanup ownership. |

`SessionSnapshot` describes the current sequential run, not a future per-target
`TaskCheckpoint`. Its progress mappings have explicit `TypedDict` shapes. It is
detached mutable data, not a deeply immutable object or a thread-safe snapshot
algorithm. Capture still uses the existing paused save boundary. Callers must
not mutate a snapshot while another operation serializes it.

The constructor copies nested containers; changing live headers, targets,
directory lists or output entries afterward cannot alter the pending write.
Conversely, manipulating the snapshot cannot mutate the source controller.
Its representation excludes all payload fields, which may contain credentials
or captured terminal text. The checkpoint itself still contains the data needed
for resume and uses the existing private-file permissions.

The controller's `_session_options` is a transitional, detached copy of normalized
input. Export no longer rereads process-global options. It is not yet the planned
aggregate of prepared component policies: setup, restore and engine composition
still use the CLI options boundary. Complete controllers are not yet safe to run
concurrently in one process.

## Compatibility and cost

- JSON field names, schema version, bytes encoding, active-first target ordering,
  wordlist claims and cross-engine resume are unchanged.
- `load()` still returns validated JSON data. Runtime reconstruction is explicit
  in `Controller._restore_session()`; loading alone opens no runtime resources.
- Existing checkpoint-file paths and the four-file JSON migration bridge remain
  supported. The documented future removal of that bridge is unchanged.
- Output history is initialized explicitly. Resume imports prior output; a fresh
  run does not borrow history from an unrelated existing destination. The old
  missing-attribute/destination-history fallback is removed.
- Copies happen during preparation and checkpoint capture, not per request or
  native chunk. A checkpoint still materializes the saved wordlist; this is not
  an incremental checkpoint implementation or a throughput improvement claim.
- Report flushing, atomic replacement and durability ordering are unchanged.

## Validation

Run `python -m unittest discover -s tests -t .`. Focused coverage is in
`tests.controller.test_session_snapshot`, `tests.controller.test_session_store`
and `tests.controller.test_scan_run_state`.

Coverage includes detached nested inputs, exact JSON structure, repeated snapshot
writes, resource-free storage, prepared options after fresh setup and resume for
all three engine selectors, failed writes/replaces, history commit/retry, legacy
output history, cross-engine progress, file permissions and legacy migration.
Engine-selection tests use controlled controller lifecycles; existing native
integration and loopback tests separately exercise the real backends.

`tests/check_packaged_install.py` exercises an installed snapshot round trip.
Setuptools discovers the module under `lib.controller`, PyInstaller collects
`lib` submodules, and the existing CI package smoke executes that check. No new
dependency, Rust ABI change or bundling rule is needed.
