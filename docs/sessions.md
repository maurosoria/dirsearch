# Sessions

dirsearch supports saving and resuming scan sessions, allowing you to pause a long-running scan and continue it later.

## Session Format

Sessions are stored as one JSON checkpoint inside a session directory. The
checkpoint contains the output history, controller state, wordlist position,
and command-line options as one atomic snapshot.

```text
session_name/
└── dirsearch-session.json
```

Replacing one combined checkpoint prevents a failed save from mixing new scan
state with an older wordlist position or option set. dirsearch can still read
the previous four-file JSON directory format; successfully saving that session
again migrates it to the combined checkpoint. Legacy `.pickle` and `.pkl`
session files are no longer supported.

Support for reading the four-file JSON format is a temporary migration bridge.
It should be removed in a future breaking release after users have had a
documented deprecation window in which to resume and resave older sessions.

## Saving a Session

When you pause a scan with `CTRL+C`, dirsearch prompts you to save the session:

```sh
python3 dirsearch.py -u https://target -e php
# Press CTRL+C during scan
# Select "save" and provide a session name
```

## Resuming a Session

Resume a saved session with `-s` / `--session`:

```sh
python3 dirsearch.py -s sessions/my_session
```

## Listing Available Sessions

View all resumable sessions with `--list-sessions`:

```sh
python3 dirsearch.py --list-sessions
```

The listing includes:

- Session path
- Target URL
- Remaining targets and directories
- Jobs processed
- Error count
- Last modified time

## Custom Sessions Directory

Specify a custom directory to search for sessions:

```sh
python3 dirsearch.py --list-sessions --sessions-dir /path/to/sessions
```

Default session locations:

- Source install: `<dirsearch>/sessions/`
- Bundled binary: `$HOME/.dirsearch/sessions/`

## Output History

Sessions maintain a history of previous scan outputs, allowing you to review results from interrupted scans. Each resume appends to the output history with timestamps.
