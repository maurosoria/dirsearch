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

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from lib.connection.requester import AsyncRequester, BaseRequester, Requester
from lib.connection.response import BaseResponse
from lib.core.data import options
from lib.core.logger import logger
from lib.core.settings import (
    REFLECTED_PATH_MARKER,
    WILDCARD_TEST_POINT_MARKER,
)
from lib.parse.url import clean_path
from lib.utils.common import replace_path
from lib.utils.diff import (
    DynamicContentParser,
    content_similarity,
    generate_matching_regex,
    normalize_dynamic_content,
)
from lib.utils.random import rand_stealth_word


AUTO_CALIBRATION_EXTRA_SAMPLES = 2
AMBIGUOUS_SIMILARITY_THRESHOLD = 0.9
AMBIGUOUS_SIMILARITY_MAX_CONTENT_LENGTH = 8192


class BaseScanner:
    def __init__(
        self,
        requester: BaseRequester,
        path: str = "",
        tested: dict[str, Any] = {},
        context: str = "all cases",
    ) -> None:
        self.path = path
        self.tested = tested
        self.context = context
        self.requester = requester
        self.response = None
        self.wildcard_redirect_regex = None
        self.sample_count = 0
        self.reason = ""

    def check(self, path: str, response: BaseResponse) -> bool:
        """
        Perform analyzing to see if the response is wildcard or not
        """
        decision = self.classify(path, response)
        return decision != "wildcard"

    def classify(self, path: str, response: BaseResponse) -> str:
        """Classify response against this wildcard profile."""

        if self.response.status != response.status:
            self.reason = "status differs from wildcard profile"
            return "unique"

        # See the comment in generate_redirect_regex() to understand better
        if self.wildcard_redirect_regex and response.redirect:
            """
            We get rid of queries and DOM in generating redirect regex so we do the same here,
            and we get rid of queries/DOM in path as well because queries in path are usually
            reflected in the redirect as queries too (but we have already got rid of them).
            """
            redirect = replace_path(
                clean_path(response.redirect),
                clean_path(path),
                REFLECTED_PATH_MARKER,
            )

            # If redirection doesn't match the rule, mark as found
            if not re.match(self.wildcard_redirect_regex, redirect, re.IGNORECASE):
                logger.debug(
                    f'"{redirect}" doesn\'t match the regular expression "{self.wildcard_redirect_regex}", passing'
                )
                self.reason = "redirect differs from wildcard profile"
                return "unique"

        if self.is_wildcard(response):
            self.reason = "matches wildcard profile"
            return "wildcard"

        if self.is_probable_wildcard(path, response):
            self.reason = "matches ambiguous wildcard profile"
            logger.debug(
                f'"{path}" filtered by ambiguous wildcard heuristic in "{self.context}"'
            )
            return "wildcard"

        self.reason = "response is unique enough"
        return "unique"

    def get_duplicate(self, response: BaseResponse) -> BaseScanner | None:
        for category in self.tested:
            for tester in self.tested[category].values():
                if response == tester.response:
                    return tester

        return None

    def is_wildcard(self, response: BaseResponse) -> bool:
        """Check if response is similar to wildcard response"""

        # Compare 2 binary responses (Response.content is empty if the body is binary)
        if not self.response.content and not response.content:
            return self.response.body == response.body

        return self.content_parser.compare_to(response.content)

    def is_probable_wildcard(self, path: str, response: BaseResponse) -> bool:
        """Conservative fallback for dynamic soft-404 templates.

        This only runs when the normal wildcard parser could not prove a match.
        Size/line/word counts are deliberately weak signals here; the decision
        requires high normalized body similarity and no strong redirect/content
        divergence.
        """

        if not self.response.content or not response.content:
            return False

        if self.response.type != response.type:
            return False

        if self.response.redirect and not response.redirect:
            return False

        if self.content_parser.static_patterns and len(self.content_parser.static_patterns) >= 20:
            return False

        if (
            len(self.response.content) > AMBIGUOUS_SIMILARITY_MAX_CONTENT_LENGTH
            or len(response.content) > AMBIGUOUS_SIMILARITY_MAX_CONTENT_LENGTH
        ):
            return False

        similarity = content_similarity(self.response.content, response.content)
        if similarity < AMBIGUOUS_SIMILARITY_THRESHOLD:
            return False

        base_length = max(self.response.length, 1)
        length_delta = abs(self.response.length - response.length) / base_length
        if length_delta > 0.35:
            return False

        normalized_content = normalize_dynamic_content(response.content)
        normalized_path = clean_path(path).strip("/")
        if normalized_path and normalized_path in normalized_content:
            return True

        return self.content_parser.is_ambiguous

    def should_auto_calibrate(self) -> bool:
        return bool(options.get("auto_calibration")) or self.content_parser.is_ambiguous

    def add_calibration_sample(self, response: BaseResponse) -> None:
        self.sample_count += 1
        if response.content:
            self.content_parser.add_sample(response.content)

    @staticmethod
    def generate_redirect_regex(first_loc: str, first_path: str, second_loc: str, second_path: str) -> str:
        """
        From 2 redirects of wildcard responses, generate a regexp that matches
        every wildcard redirect.

        How it works:
        1. Replace path in 2 redirect URLs (if it gets reflected in) with a mark
           (e.g. /path1 -> /foo/path1 and /path2 -> /foo/path2 will become /foo[mark] for both)
        2. Compare 2 redirects and generate a regex that matches both
           (e.g. /foo[mark] and /foo[mark] will have the regex: ^/foo[mark]$)
        3. To check if a redirect is wildcard, replace path with the mark and check if it matches this regex
           (e.g. /path3 -> /bar/path3, the redirect becomes /bar[mark], which doesn't match the regex ^/foo[mark]$)
        """

        if first_path:
            first_loc = first_loc.replace("/" + first_path, REFLECTED_PATH_MARKER)
        if second_path:
            second_loc = second_loc.replace("/" + second_path, REFLECTED_PATH_MARKER)

        return generate_matching_regex(first_loc, second_loc)


class Scanner(BaseScanner):
    def __init__(
        self,
        requester: Requester,
        *,
        path: str = "",
        tested: dict[str, dict[str, Scanner]] = {},
        context: str = "all cases",
    ) -> None:
        super().__init__(requester, path, tested, context)
        self.setup()

    def setup(self) -> None:
        """
        Generate wildcard response information containers, this will be
        used to compare with other path responses
        """

        first_path = self.path.replace(
            WILDCARD_TEST_POINT_MARKER,
            rand_stealth_word(),
        )
        first_response = self.requester.request(first_path)
        self.response = first_response
        self.sample_count = 1
        time.sleep(options["delay"])

        # Another test was performed before and has the same response as this
        if duplicate := self.get_duplicate(first_response):
            self.content_parser = duplicate.content_parser
            self.wildcard_redirect_regex = duplicate.wildcard_redirect_regex
            logger.debug(f'Skipped the second test for "{self.context}"')
            return

        second_path = self.path.replace(
            WILDCARD_TEST_POINT_MARKER,
            rand_stealth_word(omit=first_path),
        )
        second_response = self.requester.request(second_path)
        self.sample_count += 1
        time.sleep(options["delay"])

        if first_response.redirect and second_response.redirect:
            # Removing the queries (and DOM) with clean_path() because sometimes
            # some queries that are assigned random values that are hard to deal with
            self.wildcard_redirect_regex = self.generate_redirect_regex(
                clean_path(first_response.redirect),
                first_path,
                clean_path(second_response.redirect),
                second_path,
            )
            logger.debug(
                f'Pattern (regex) to detect wildcard redirects for "{self.context}": {self.wildcard_redirect_regex}'
            )

        self.content_parser = DynamicContentParser(
            first_response.content, second_response.content
        )
        self.auto_calibrate((first_path, second_path))

    def auto_calibrate(self, tested_paths: tuple[str, ...]) -> None:
        if not self.should_auto_calibrate():
            return

        omitted = set(tested_paths)
        for _ in range(AUTO_CALIBRATION_EXTRA_SAMPLES):
            sample_path = self.path.replace(
                WILDCARD_TEST_POINT_MARKER,
                rand_stealth_word(omit=omitted),
            )
            omitted.add(sample_path)
            sample_response = self.requester.request(sample_path)
            self.add_calibration_sample(sample_response)
            time.sleep(options["delay"])


class AsyncScanner(BaseScanner):
    def __init__(
        self,
        requester: AsyncRequester,
        *,
        path: str = "",
        tested: dict[str, dict[str, AsyncScanner]] = {},
        context: str = "all cases",
    ) -> None:
        super().__init__(requester, path, tested, context)

    @classmethod
    async def create(
        cls,
        requester: AsyncRequester,
        *,
        path: str = "",
        tested: dict[str, dict[str, AsyncScanner]] = {},
        context: str = "all cases",
    ) -> AsyncScanner:
        self = cls(requester, path=path, tested=tested, context=context)
        await self.setup()
        return self

    async def setup(self) -> None:
        """
        Generate wildcard response information containers, this will be
        used to compare with other path responses
        """

        first_path = self.path.replace(
            WILDCARD_TEST_POINT_MARKER,
            rand_stealth_word(),
        )
        first_response = await self.requester.request(first_path)
        self.response = first_response
        self.sample_count = 1
        await asyncio.sleep(options["delay"])

        duplicate = self.get_duplicate(first_response)
        # Another test was performed before and has the same response as this
        if duplicate:
            self.content_parser = duplicate.content_parser
            self.wildcard_redirect_regex = duplicate.wildcard_redirect_regex
            logger.debug(f'Skipped the second test for "{self.context}"')
            return

        second_path = self.path.replace(
            WILDCARD_TEST_POINT_MARKER,
            rand_stealth_word(omit=first_path),
        )
        second_response = await self.requester.request(second_path)
        self.sample_count += 1
        await asyncio.sleep(options["delay"])

        if first_response.redirect and second_response.redirect:
            self.wildcard_redirect_regex = self.generate_redirect_regex(
                clean_path(first_response.redirect),
                first_path,
                clean_path(second_response.redirect),
                second_path,
            )
            logger.debug(
                f'Pattern (regex) to detect wildcard redirects for "{self.context}": {self.wildcard_redirect_regex}'
            )

        self.content_parser = DynamicContentParser(
            first_response.content, second_response.content
        )
        await self.auto_calibrate((first_path, second_path))

    async def auto_calibrate(self, tested_paths: tuple[str, ...]) -> None:
        if not self.should_auto_calibrate():
            return

        omitted = set(tested_paths)
        for _ in range(AUTO_CALIBRATION_EXTRA_SAMPLES):
            sample_path = self.path.replace(
                WILDCARD_TEST_POINT_MARKER,
                rand_stealth_word(omit=omitted),
            )
            omitted.add(sample_path)
            sample_response = await self.requester.request(sample_path)
            self.add_calibration_sample(sample_response)
            await asyncio.sleep(options["delay"])
