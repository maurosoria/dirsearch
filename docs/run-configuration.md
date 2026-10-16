# Prepared run configuration

`RunConfig` groups the ten immutable policies prepared for one invocation.
It is an internal composition value, not a public execution API, resource
container, task descriptor or checkpoint. Its fields omit their values from
`repr` because policies can contain credentials and request data.

## Preparation boundary

Fresh setup first parses a raw request or combines default and supplied headers.
Resume first loads and validates the saved normalized options. The controller
then detaches one mapping and prepares all policies from it, before constructing
the prepared terminal, dictionary, logger, response stores or report manager.
The bootstrap terminal and logger still exist to handle preparation failures.
An invalid engine selection exits before constructing the prepared resources.

The same mapping is captured in [SessionOptions](session-options.md) for
persistence, separately from runtime policy. Changing global options during resource construction
cannot change the remaining policies or saved configuration. On resume, the
overwrite/new prompt only updates the saved session destination; it does not
recapture the other options. JSON schema, field names and cross-engine resume
are unchanged. No `RunConfig` object is serialized into a checkpoint.

`RunConfig.from_options(values)` expects normalized input and does not read global
options or open files. Its adapters preserve the existing component defaults and
semantics. Direct construction supports explicit component tests; it is not an
alternative CLI validator or a guarantee that arbitrary leaf combinations are
consistent. Production uses the normalized preparation path.

## Narrow consumers

| Field | Consumer / responsibility |
| --- | --- |
| `wordlist` | Dictionary generation and blacklist loading policy |
| `request` | Requester construction, including the full-body capture flag |
| `filters` | Fuzzer and native matching policy, not learned filter state |
| `discovery` | Existing directory/path discovery policy |
| `execution` | Engine selection, worker policy and deadlines |
| `reports` | Report manager destinations and batching |
| `target` | Target preparation hints |
| `terminal` | Prepared terminal presentation and summary |
| `logging` | Logger destination and redaction policy |
| `results` | Response destinations, result presentation and replay selection |

Only the controller owns the aggregate. Dictionary, requester, fuzzer, report
manager, terminal and logger still receive their narrow policies; they do not
receive a controller or a catch-all context. Metadata stays in `RunMetadata`,
input in `TaskSpec`, mutable progress in `ScanRunState`/`TargetProgress`, and live
handles in [RunResources](run-resources.md), with the existing cleanup order.

Blacklist files are loaded at the existing run-start boundary.
`with_blacklists(data)` returns a new aggregate with a detached `FilterConfig`;
the other nine policy instances are retained. This happens before requester and
worker creation. It does not mutate a previously constructed policy or reread
the CLI mapping. Learned target-specific filters remain outside configuration.

## Limits and validation

This is not full process isolation. CLI normalization, initial target input,
session-path interaction, process signals and other items in the
[refactoring backlog](refactoring-backlog.md) still need separate work. Local
resource ownership and [controller execution phases](controller-lifecycle.md)
are explicit; local CLI normalization is not implemented yet.
No target scheduler, Rust engine change or new concurrency
capability is included.

Construction/copying happens at preparation and run start, not per request or
native chunk. There is no throughput-improvement claim or changed batch default.

Run `python -m unittest discover -s tests -t .`. New tests cover all ten adapters,
detached nested values, immutability, engine/capture consistency, blacklist
replacement, raw-request ordering, real JSON resume, overwrite choices, failure
cleanup and mutations between resource construction steps. Existing component
fixtures now explicitly prepare a `RunConfig`; no legacy controller attributes
or missing-attribute fallbacks are retained. Transport-selection tests use mocks;
the existing loopback tests separately exercise the real engines.

The installed-package smoke also checks class identity and engine-dependent
report callback selection. Relative policy imports keep `lib` and `dirsearch.lib`
namespaces from producing mismatched engine enums. Setuptools includes the new
module and PyInstaller's existing `collect_submodules('lib')` collects it without
new packaging rules or dependencies.
