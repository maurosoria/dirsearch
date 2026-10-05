# Target preparation ownership

`TargetConfig` is the immutable run-wide policy used by `Controller.set_target()`.
It is built after raw-request setup or session restoration, at the same run
preparation boundary as `RequestConfig`, before constructing requesters.

| Normalized input | Frozen field | Consumer |
| --- | --- | --- |
| `scheme` | `default_scheme` | Scheme-less target preparation |
| `ip` | `connect_host` | Existing scheme probe and requester IP override |
| `proxies` or `tor` | `proxy_configured` | Existing prohibition on automatic scheme detection with an explicitly configured proxy/Tor |

Changing global options after preparation cannot change these hints for the
current or later targets. The options adapter uses only its supplied mapping;
`set_target()` no longer reads global options. Internal callers that prepare
targets directly must supply `controller.target_config` explicitly.

## Policy versus state

`TargetConfig` is not a target descriptor or a resolved address. It contains no
target URL, parsed credentials, query, DNS answers, connection handles or queue
progress. `connect_host` specifically means the explicit `--ip` override, not
the origin hostname or a list of resolved addresses.

[ScanRunState](scan-run-state.md) owns the active target and pending inputs.
The controller still parses each target's origin, path, query and credentials,
then applies them to its requester. [RequestConfig](request-configuration.md)
owns the transport baseline and actual proxy URLs/credentials. The transport
continues to own DNS resolution and connection selection.

The `proxy_configured` flag records only the existing CLI/session proxy-or-Tor
condition. It neither selects a proxy nor inspects environment variables such as
`HTTP_PROXY` or `NO_PROXY`. Their existing backend behavior is unchanged.

## Preserved behavior

- A URL's explicit HTTP(S) scheme takes precedence over the configured default.
- With no scheme, the same existing detection and default-port fallback run.
- An explicitly configured proxy/Tor still requires a scheme in the URL or
  `--scheme`, before probing or modifying requester authentication.
- The origin hostname and port remain distinct from the `--ip` connection hint.
- Bracketed IPv6 reconstruction, port validation, query preservation and
  target-specific authentication retain their existing implementation.

This does not add a parser, new connection behavior, proxy/auth support,
parallel targets or distributed execution. There is no Rust/ABI change and no
additional Python/Rust call per request. Complete controllers still share other
process-wide services and are not yet safe to run concurrently.

## Sessions

Sessions continue to store the existing normalized options. Resume restores
those options before `run()` constructs `TargetConfig`; no new field or config
object is serialized and the version-1 JSON schema is unchanged.

## Validation

Run `python -m unittest discover -s tests -t .`.

Coverage includes immutable supplied-mapping adaptation, proxy/Tor truth-table
semantics, input mutation, absence of proxy credentials in the target policy,
independent policies with global options cleared, changes to globals during
requester construction, and real JSON checkpoint restoration for all three
engines. Existing IPv6, URL, credentials and loopback CLI contracts remain in use.

`tests/check_packaged_install.py` imports and exercises `TargetConfig` from the
installed package. Setuptools discovers it in `lib.core`; PyInstaller's existing
`collect_submodules('lib')` includes it without changing build rules.
