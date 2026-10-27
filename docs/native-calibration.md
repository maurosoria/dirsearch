# Native wildcard calibration

Native extension 0.2.25 accelerates stable-pattern extraction for ASCII samples
on Python 3.14. It preserves the token SequenceMatcher blocks, autojunk policy,
matching ties and Differ's bounded replacement synchronization window. Only
equal words are retained, so intraline display annotations are not constructed.
Unicode and other Python minor versions retain their standard-library Differ.

The default profile is prepared first. Eligible native GET scans then prefetch
the initial probe for the remaining profile shapes in batches of at most four.
Profiles consume those responses in their original order. Duplicate reuse,
second probes and adaptive samples retain their existing behavior; prefetched
responses do not add extra requests to the ordinary probe budget.

Calibration remains sequential for configured delays or rate limits,
authentication, explicit Cookie/Authorization headers, existing session cookies
and redirect-following requests. Default-profile responses establish cookie
state before eligibility is checked. The HTTP in-flight concurrency still caps
each batch, independently of the runtime's CPU worker count.

Tests compare extracted patterns and parser decisions against Python's Differ,
including replacement windows and repetitive reflected bodies. Controlled HTTP
tests verify bounded overlap, unchanged probe count and sequential behavior for
cookies and rate limits. Calibration errors and cancellation propagate through
the unfiltered request path.
