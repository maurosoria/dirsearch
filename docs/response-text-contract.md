# Response text contract

Threaded, async and native responses resolve encodings from the same rules:
an explicit charset wins; text media without one use ISO-8859-1, preserving
the threaded client's established behavior; other media default to UTF-8.
Unknown charset names fall back to UTF-8. HTTP client encoding guesses do not
change classification or filtering.

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
and checks wildcard and filter outcomes, including distinct unlabelled pages,
binary bytes and control separators. The native extension must be rebuilt
after updating this contract.
