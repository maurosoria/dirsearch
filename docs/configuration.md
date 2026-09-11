# Configuration

By default, dirsearch uses [`config.ini`](../config.ini) from the project
directory. That file is the authoritative reference for available settings and
their defaults. You can select another file with `--config` or the
`DIRSEARCH_CONFIG` environment variable.

`--save-response DIR` (or `save-response` in the `[output]` section) writes the
raw bytes of each matched response into `DIR`. Response capture is limited to
80 MiB per match on every request backend. Query values are replaced with a
short hash in filenames, and a numeric suffix is added when names collide;
existing files are never overwritten. On the Python request backends, enabling
this option requires reading binary bodies through the capture limit before
filtering, so memory and network use can increase on binary-heavy targets.

`--save-response-jsonl FILE` appends one versioned JSON object per matched
response. The `body` field is always Base64 encoded and identified by
`bodyEncoding`, so text and binary responses use the same stable schema.
`capturedBodyLength` records the number of stored bytes, while `bodyComplete`
and `bodyTruncated` explicitly identify whether the capture limit omitted any
of the decoded response body. Both response-saving options can be enabled
together. Existing non-empty JSONL files must contain compatible
`dirsearch.response.v1` records.
