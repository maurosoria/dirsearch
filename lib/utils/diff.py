# -*- coding: utf-8 -*-
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#  Author: Mauro Soria

import difflib
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache

from lib.utils.common import lstrip_once
from lib.native import get_native_extension_version_error, supports_native_differ


@dataclass(frozen=True, slots=True)
class _NativeContentHelpers:
    normalize: Callable[[str], str]
    similarity: Callable[[str, str], float]
    static_patterns: Callable[[str, str], list[str]] | None


@cache
def _get_native_content_helpers() -> _NativeContentHelpers | None:
    """Load the optional extension only after a native caller opts in."""
    try:
        import dirsearch_native
    except ImportError:
        return None
    if get_native_extension_version_error(dirsearch_native) is not None:
        return None
    return _NativeContentHelpers(
        dirsearch_native.normalize_ascii_content,
        dirsearch_native.sequence_matcher_ratio,
        # Unknown minors keep their Differ without disabling native HTTP.
        dirsearch_native.static_ascii_patterns if supports_native_differ(sys.version_info) else None,
    )


_DYNAMIC_TOKEN_REGEXES = (
    # UUIDs and long hex/base64-ish identifiers are common in soft-404 pages,
    # CSRF tokens, build IDs, and request IDs.
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
    re.compile(r"\b[0-9a-f]{16,}\b", re.I),
    re.compile(r"\b[A-Za-z0-9+/]{24,}={0,2}\b"),
    # Timestamps and high-cardinality numbers add noise without helping
    # distinguish wildcard templates from real findings.
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+-]+Z?)?\b"),
    re.compile(r"\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b"),
    re.compile(r"\b\d{6,}\b"),
)

_HTML_ATTRIBUTE_VALUE_REGEX = re.compile(
    r"""(?i)\b(?:nonce|csrf|token|request[_-]?id|trace[_-]?id|session[_-]?id)=["'][^"']+["']"""
)


def _normalize_dynamic_content_python(content: str) -> str:
    """Return content with common volatile values replaced by stable markers."""

    normalized = content
    normalized = _HTML_ATTRIBUTE_VALUE_REGEX.sub("__DYNAMIC_ATTR__", normalized)

    for regex in _DYNAMIC_TOKEN_REGEXES:
        normalized = regex.sub("__DYNAMIC__", normalized)

    return " ".join(normalized.split())


def normalize_dynamic_content(content: str, *, use_native: bool = False) -> str:
    """Normalize with Python unless this response belongs to the native engine.

    Unicode keeps Python's regex case folding, word boundaries and whitespace
    definitions rather than depending on another engine's Unicode tables.
    """
    if use_native and content.isascii():
        if helpers := _get_native_content_helpers():
            return helpers.normalize(content)
    return _normalize_dynamic_content_python(content)


def content_similarity(content1: str, content2: str, *, use_native: bool = False) -> float:
    """Return similarity after removing common dynamic values."""

    return normalized_content_similarity(
        normalize_dynamic_content(content1, use_native=use_native),
        normalize_dynamic_content(content2, use_native=use_native),
        use_native=use_native,
    )


def _normalized_content_similarity_python(content1: str, content2: str) -> float:
    return difflib.SequenceMatcher(
        None,
        content1,
        content2,
    ).ratio()


def normalized_content_similarity(content1: str, content2: str, *, use_native: bool = False) -> float:
    """Return the difflib ratio, optionally accelerated for native responses."""
    helpers = _get_native_content_helpers() if use_native else None
    if helpers is not None:
        try:
            return helpers.similarity(content1, content2)
        except UnicodeEncodeError:
            # Lone surrogates in Python strings cannot cross the UTF-8 boundary.
            pass
    return _normalized_content_similarity_python(content1, content2)


@dataclass(frozen=True, slots=True)
class ContentComparisonProfile:
    """Immutable comparison data exported to request-engine adapters."""

    base_content: str
    normalized_contents: tuple[str, ...]
    static_patterns: tuple[str, ...]
    is_static: bool
    is_ambiguous: bool


class DynamicContentParser:
    def __init__(self, content1, content2, *, use_native: bool = False):
        self._use_native = use_native
        self._static_patterns = None
        self._differ = difflib.Differ()
        self._contents = [content1, content2]
        self._normalized_contents = [
            normalize_dynamic_content(content1, use_native=use_native),
            normalize_dynamic_content(content2, use_native=use_native),
        ]
        self._base_content = content1
        self._is_static = False

        self._recalculate()

    @property
    def comparison_profile(self) -> ContentComparisonProfile:
        return ContentComparisonProfile(
            self._base_content, tuple(self._normalized_contents),
            tuple(self.static_patterns), self._is_static, self.is_ambiguous,
        )

    @property
    def static_patterns(self):
        return self._static_patterns or []

    @property
    def is_ambiguous(self):
        if self._is_static:
            return False

        if len(self.static_patterns) < 8:
            return True

        return self.similarity_to(
            self._contents[-1],
            self._normalized_contents[-1],
        ) < 0.55

    def add_sample(self, content):
        self._contents.append(content)
        self._normalized_contents.append(normalize_dynamic_content(content, use_native=self._use_native))
        self._recalculate()

    def compare_to(self, content, normalized_content=None):
        """
        DynamicContentParser.compare_to() workflow

          1. Check if the wildcard response is static or not, if yes, compare two responses.
          2. If it's not static, get static patterns (split by space) and check if the response
            has all of them.
          3. In some cases, checking static patterns isn't reliable enough, so we check the similarity
            ratio of the two responses.
        """

        if normalized_content is None:
            normalized_content = normalize_dynamic_content(content, use_native=self._use_native)

        if self._is_static:
            return (
                content == self._base_content
                or normalized_content == self._normalized_contents[0]
            )

        if not self._static_patterns:
            # Compact JSON/HTML may share no whole whitespace-delimited token.
            # An empty pattern list is not evidence that every response matches.
            # Exact observed samples are still known matches; the scanner owns
            # any further similarity-based fallback.
            return normalized_content in self._normalized_contents

        i = -1
        splitted_content = normalized_content.split()
        # Allow one miss, see https://github.com/maurosoria/dirsearch/issues/1279
        misses = 0
        for pattern in self._static_patterns:
            try:
                i = splitted_content.index(pattern, i + 1)
            except ValueError:
                if misses or len(self._static_patterns) < 20:
                    return False

                misses += 1

        # Static patterns doesn't seem to be a reliable enough method
        if len(content.split()) > len(self._base_content.split()) and len(self._static_patterns) < 20:
            return self.similarity_to(content, normalized_content) > 0.75

        return True

    def similarity_to(self, content, normalized_content=None):
        if normalized_content is None:
            normalized_content = normalize_dynamic_content(content, use_native=self._use_native)

        return normalized_content_similarity(
            self._normalized_contents[0],
            normalized_content,
            use_native=self._use_native,
        )

    def _recalculate(self):
        self._is_static = all(content == self._base_content for content in self._contents)

        if self._is_static:
            self._static_patterns = []
            return

        first, second = self._normalized_contents[:2]
        patterns = None
        helpers = _get_native_content_helpers() if self._use_native else None
        if helpers is not None and helpers.static_patterns is not None and first.isascii() and second.isascii():
            patterns = helpers.static_patterns(first, second)
        if patterns is None:
            patterns = self.get_static_patterns(
                self._differ.compare(first.split(), second.split())
            )

        for normalized_content in self._normalized_contents[2:]:
            normalized_words = normalized_content.split()
            patterns = [pattern for pattern in patterns if pattern in normalized_words]

        self._static_patterns = patterns

    @staticmethod
    def get_static_patterns(patterns):
        # difflib.Differ.compare returns something like below:
        # ["  str1", "- str2", "+ str3", "  str4"]
        #
        # Get only stable patterns in the contents
        return [lstrip_once(pattern, "  ") for pattern in patterns if pattern.startswith("  ")]


def generate_matching_regex(string1: str, string2: str) -> str:
    start = "^"
    end = "$"

    for char1, char2 in zip(string1, string2):
        if char1 != char2:
            start += ".*"
            break

        start += re.escape(char1)

    if start.endswith(".*"):
        for char1, char2 in zip(string1[::-1], string2[::-1]):
            if char1 != char2:
                break

            end = re.escape(char1) + end

    return start + end
