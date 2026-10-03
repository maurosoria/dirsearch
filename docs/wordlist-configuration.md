# Wordlist configuration ownership

`WordlistConfig` is the immutable policy for generating a dictionary and
validating dynamically added paths. `Dictionary`, the Python/native generators
and blacklist loading receive it explicitly; none reads global `options`.

| Previous global reads | Current owner | Consumers |
| --- | --- | --- |
| Extensions, exclusions, forced/overwritten extensions | `WordlistConfig` | Generation and dynamic-path validation |
| Prefixes/suffixes, case transformations, generation limit | `WordlistConfig` | Python and native generators |
| Wordlist backend and native corpus preference | `WordlistConfig` | Backend factory and native adapter |
| Current index, discovered paths, outstanding claims | `Dictionary` mutable state | All three fuzzers and session persistence |

## Construction and policy lifetime

The controller builds this snapshot in `setup()` before dictionary generation,
or in `_import()` after restoring and validating session options. It passes the
same object to bundled blacklist loading. The CLI's `--wordlist-status` path
also supplies an explicit snapshot.

```python
from lib.core.dictionary import Dictionary
from lib.core.wordlist_config import WordlistConfig

config = WordlistConfig(
    backend="python",
    extensions=("html", "json"),
    exclude_extensions=("zip",),
    max_size=500000,
)
dictionary = Dictionary(config, files=["words.txt"])
```

Collection inputs are copied into tuples, preserving order and duplicates.
Existing CLI normalization and validation remain authoritative; this is not
another parser. Modifying the original mapping cannot change an existing
dictionary's decisions. Create a new config and dictionary to change policy;
do not replace the config while a dictionary is in use.

The generation algorithm, template expansion, case precedence, deduplication,
limit errors and blacklist exceptions retain their existing behavior. Dynamic
paths still undergo validation only, not wordlist transformations. Resetting the
queue for a later job or target retains its configuration. Locking and claim
ordering are unchanged.

## Native ownership

`backend` chooses the generator; `native_corpus` expresses the request engine's
preference to retain generated words in Rust. They are separate decisions:

- `auto` with Python requests selects the Python generator.
- `auto` with native requests prefers native generation and a Rust-owned corpus.
- Explicit `python` generation still produces a Python list, including for
  native requests.
- Explicit `native` generation produces a list for Python requests or a
  `NativeWordlistCorpus` for native requests.
- Blacklists and named templates retain their existing Python expansion path,
  using the same snapshot.

Missing/incompatible native extensions still raise for explicit native
generation. Auto selection retains its existing fallback so requester
initialization can report the native installation error at its established
boundary. No new fallback is introduced.

The adapter passes the same argument set to Rust. Corpus/chunk ownership, native
membership checks, ABI and callback protocol are unchanged. No Python/Rust call
per word or corpus copy is added. This refactor does not claim benchmark gains.

## Sessions

Checkpoints keep their existing options and dictionary-state representation;
they do not serialize `WordlistConfig`. The controller reconstructs the policy
from restored options and supplies it to `SessionStore.apply_to_controller()`.
That method initializes an empty dictionary and restores saved words and indexes
without invoking a generator or accessing the original wordlist files.

`Dictionary(config)` is the explicit empty construction path.
`__setstate__()` restores only queue state on an initialized dictionary; it does
not create missing attributes or infer policy. The state tuple remains
`(items, index, extra, extra_index)`. Outstanding work remains recoverable, and
later jobs/targets still start from the full saved corpus. Sessions remain
engine-independent and continue to restore saved items as a Python list.

## Scope and validation

[ExecutionConfig](execution-configuration.md) owns fuzzer concurrency/pacing and
stop policy. Engine selection, targets, output, replay settings and other
controller/logging globals remain separate migration steps. This does not yet
make complete controllers safe to run concurrently.

Run `python -m unittest discover -s tests -t .`. New coverage checks immutable
input copies, independent dictionaries with global options empty, blacklist and
generation-limit behavior, native argument/corpus ownership, and real controller
setup/session restoration for all three request-stack configurations. Existing
generation parity, dictionary concurrency, resume and loopback CLI contracts
continue to exercise their production paths. Native integration tests require
the compatible optional extension and skip when absent.

The installed-package smoke test imports the new module. Setuptools discovers
it through `lib.core`, and PyInstaller's existing `collect_submodules('lib')`
includes it without a separate hidden-import entry.
