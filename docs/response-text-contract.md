# Response text contract

All adapters share explicit charset parsing, including quoted parameters and
unknown-codec fallback to UTF-8. When a text response omits its charset, each
engine preserves its established default: threaded uses ISO-8859-1, while async
and native use UTF-8. Other media default to UTF-8. In particular, unlabelled
UTF-8 HTML remains readable by async/native text filters and reports.

Declared textual encodings retain complete captured bodies, including UTF-16.
Binary content keeps an empty `content` value and the existing UTF-8 text view
with invalid bytes ignored. Ordinary text replaces invalid encoded sequences.
Body bytes and completeness remain separate from either text view.

Rust may evaluate text filters early for ASCII bodies in supported encodings.
Word counts include Python's ASCII separators U+001C through U+001F. Other
text bodies remain available for the common Python filter stack, which owns
charset decoding, binary text fallback and Unicode regex definitions. Numeric
and status filters still run natively when they do not require text.

Regression coverage sends identical HTTP bodies through the response adapters
and checks wildcard and filter outcomes, including unlabelled UTF-8 and distinct declared Latin-1 pages,
binary bytes and control separators. The native extension must be rebuilt
after updating this contract.
