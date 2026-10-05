# Terminal configuration and ownership

`TerminalConfig` is an immutable snapshot of output mode, color, verbosity and
the configuration summary. Its `from_options()` adapter accepts an explicit
mapping; neither the terminal nor color helpers import global options.

| Responsibility | Owner |
| --- | --- |
| Normalized presentation settings | Frozen `TerminalConfig`; sequences are copied to tuples |
| Selecting normal, quiet or disabled output | `create_terminal()` |
| Output history, inline state and serialization of writes | Each `CLI` instance |
| Stream lifetime | Caller; the terminal borrows it |
| Terminal lifetime during a run | `Controller.interface`, closed in controller cleanup |
| Color/style lookup | Read-only palettes; enabling color is instance-specific |

The internal terminal constructor now requires a config. `print_config()` renders
the summary; `config` holds the snapshot. There is no module-level `interface`,
`disable_color()` mutation, or terminal `atexit` callback. Importing terminal,
session and controller modules creates no history buffer and does not replace
`sys.stdout` or `sys.stderr`.

## Preparation and sessions

The controller initially creates a bootstrap terminal for errors that can happen
before preparation completes. Once raw-request parsing or session restoration
has produced validated options, it constructs the effective terminal and closes
the bootstrap buffer. The replacement is constructed first, so allocation failure
leaves the bootstrap available for error handling and final cleanup. No scan
history has been emitted at this transition.

This also ensures a raw POST request displays POST, and a restored quiet or
verbose policy does not retain the mode chosen before the checkpoint was loaded.
Ordinary target transitions do not replace the terminal or reset its history.

Checkpoint export reads only the owning controller's buffer. Restored historical
output goes through its current terminal with `do_save=False`, so it is displayed
without being copied into the current run's history again. Session serialization
and engine-independent resume formats are unchanged. Session storage propagates
report-configuration errors to the controller, which logs and renders the error
through its own terminal before exiting.

## Streams, colors and cleanup

`create_terminal(config, stream=output)` borrows an explicit text stream. With no
stream supplied it captures the current `sys.stdout` at construction. Controller
construction likewise accepts `output=...` and reuses that stream after input
preparation. Colorama adapts the individual stream, preserving ANSI conversion
on supported Windows consoles and stripping styling from redirected output.
It no longer installs process-global stream wrappers.

Quiet mode still prints matches as full URLs and suppresses progress and headers.
Disabled mode suppresses match/error output. Explicit prompt and history writes
retain their existing behavior. `--no-color` emits no styling or reset sequences
for newly formatted messages and cannot disable another terminal's colors.
Stored history retains its original text, including any previously saved styling.

History still uses a private spooled temporary file with the existing 1 MiB
in-memory threshold. One terminal's lock serializes its stream and history writes,
including close; separate terminals share no output lock. A blocking stream can
still block its own terminal. Callers choosing the same physical stream must
coordinate that shared destination themselves.

`close()` is idempotent, closes only the owned history and never closes the
borrowed stream. Writes after close fail before emitting text. Controller cleanup
closes the terminal even if report, requester or response-store cleanup raises.
Low-level force-quit paths still terminate the process immediately.

## Scope and verification

This is presentation isolation, not concurrent-controller support. Global CLI
options and process signal handlers remain separate concerns. Logging now has
its own [per-run ownership boundary](logging-ownership.md).
The controller supplies full-URL selection per match from its prepared
[result policy](result-configuration.md), which also owns response destinations
and replay selection. No worker dispatch, request pacing,
native transport, CLI flags or dependencies change.

Regression coverage includes independent colors/verbosity, detached config,
readonly palettes, mode selection, redirected streams, buffer isolation, slow
streams, write failures, import side effects, preparation/resume and cleanup
failures. Existing backend CLI contracts exercise the shared controller with
threaded, async and native engines.

Run `python -m unittest discover -s tests -t .`. The installed-package smoke test
imports `TerminalConfig`; existing setuptools discovery and PyInstaller's
`collect_submodules('lib')` include the new module.
