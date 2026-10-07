# Session option ownership

`SessionOptions` is the data-only persistence input shared by a controller and
its `SessionSnapshot`. It is separate from runtime `RunConfig` policies, target
input, progress, live resources and output history.

Runtime policies are lossy adapters: they normalize fields, derive values and
omit CLI-only information. Reconstructing a session from them could lose unknown
keys, absent fields or the original normalized types. Instead, `SessionOptions`
encapsulates that input without defining a second set of policy defaults.

## Contract

- `SessionOptions(values)` deep-copies already separated normalized input.
  A `urls` key is rejected; the only target queue is `remaining_tasks`.
- `SessionOptions.from_options(values)` adapts CLI input by excluding `urls`.
  It does not modify the supplied mapping, parse targets or read global options.
- `to_options()` returns a fresh deep copy for CLI restoration or storage
  encoding. Editing any nested container in that copy cannot change later saves.
- `with_session_file(path)` creates a new value for the overwrite/new choice.
  Previously captured snapshots retain their original options.
- The object has no mapping/subscript/update interface, and its representation
  omits all payload fields. Its private normalized-data dictionary is never
  returned or mutated after construction. This is an ownership boundary, not a
  separate dataclass field for every CLI option or a new wire schema.

`SessionSnapshot.options` requires a `SessionOptions` value, with no dictionary
fallback. Snapshots may share the value; mutable output history is still copied.
The enclosing snapshot remains mutable and is not a concurrency primitive.

The controller captures runtime policies and persistence input from the same
detached mapping after raw-request parsing or validated resume. Setup retains a
local copy for wordlist filenames; it no longer indexes persistence storage as
runtime configuration. The mapping returned by preparation can be changed without
changing either owned policy or persistence input. Export uses the captured
`session_options` value, never process-global options.

## Compatibility and limits

`SessionStore` remains the only version-1 JSON adapter. Existing field names,
bytes markers, set/tuple conversions, missing legacy defaults, private-file
permissions, atomic replacement and the four-file migration bridge are unchanged.
Unknown JSON-compatible options and explicit nulls are retained. The existing
codec's type rules remain authoritative; arbitrary unknown Python types do not
gain new serialization support. No input is inferred from `RunConfig` or from a
prepared target origin.

The existing numeric, regex, header and engine validation still runs during
controller preparation. `SessionOptions` establishes ownership, not complete
semantic validation of all CLI fields. CLI normalization still uses the global
`options` dictionary and remains a separate backlog item.

Copies occur at preparation, restoration and explicit export boundaries, not per
request or native chunk. Session capture still takes place at the existing paused
boundary. There is no Rust, scheduling, cancellation or throughput change claimed.

## Validation

Run `python -m unittest discover -s tests -t .`. Tests cover nested copy isolation,
absent/null/unknown fields, secret-safe representations, typed snapshot rejection,
target-queue separation, replacement without changing prior snapshots, exact
version-1 payloads, repeated load/save, binary data and failed persistence/retry.
Existing fresh/resumed controller tests cover all three engine selectors.

`tests/check_packaged_install.py` verifies the installed value's identity and a
real checkpoint round trip. Package-relative imports keep snapshot and option
classes in the same namespace. Setuptools discovery and PyInstaller's existing
`collect_submodules('lib')` include the module without new packaging rules.
