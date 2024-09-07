import asyncio
import re
from typing import Optional
from urllib.parse import unquote

from lib.connection.asynchronous.requester import Requester
from lib.connection.response import Response
from lib.core.data import options
from lib.core.logger import logger
from lib.core.settings import (
    REFLECTED_PATH_MARKER,
    TEST_PATH_LENGTH,
    WILDCARD_TEST_POINT_MARKER,
)
from lib.parse.url import clean_path
from lib.utils.diff import DynamicContentParser, generate_matching_regex
from lib.utils.random import rand_string


class Scanner:
    def __init__(
        self, requester: Requester, path: str, tested: dict, context: str
    ) -> None:
        self.path = path
        self.tested = tested
        self.context = context
        self.requester = requester
        self.response = None
        self.wildcard_redirect_regex = None

    @classmethod
    async def create(
        cls,
        requester: Requester,
        *,
        path: str = "",
        tested: dict = {},
        context: str = "all cases",
    ) -> "Scanner":
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
            rand_string(TEST_PATH_LENGTH),
        )
        first_response = await self.requester.request(first_path)
        self.response = first_response
        await asyncio.sleep(options["delay"])

        duplicate = self._get_duplicate(first_response)
        # Another test was performed before and has the same response as this
        if duplicate:
            self.content_parser = duplicate.content_parser
            self.wildcard_redirect_regex = duplicate.wildcard_redirect_regex
            logger.debug(f'Skipped the second test for "{self.context}"')
            return

        second_path = self.path.replace(
            WILDCARD_TEST_POINT_MARKER,
            rand_string(TEST_PATH_LENGTH, omit=first_path),
        )
        second_response = await self.requester.request(second_path)
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

    def check(self, path: str, response: Response) -> bool:
        """
        Perform analyzing to see if the response is wildcard or not
        """

        if self.response.status != response.status:
            return True

        # Read from line 129 to 138 to understand the workflow of this.
        if self.wildcard_redirect_regex and response.redirect:
            # - unquote(): Sometimes, some path characters get encoded or decoded in the response redirect
            # but it's still a wildcard redirect, so unquote everything to prevent false positives
            # - clean_path(): Get rid of queries and DOM in URL because of weird behaviours could happen
            # with them, so messy that I give up on finding a way to test them
            path = unquote(clean_path(path))
            redirect = unquote(clean_path(response.redirect))
            regex_to_compare = self.wildcard_redirect_regex.replace(
                REFLECTED_PATH_MARKER, re.escape(path)
            )
            is_wildcard_redirect = re.match(regex_to_compare, redirect, re.IGNORECASE)

            # If redirection doesn't match the rule, mark as found
            if not is_wildcard_redirect:
                logger.debug(
                    f'"{redirect}" doesn\'t match the regular expression "{regex_to_compare}", passing'
                )
                return True

        if self._is_wildcard(response):
            return False

        return True

    def _get_duplicate(self, response: Response) -> Optional["Scanner"]:
        for category in self.tested:
            for tester in self.tested[category].values():
                if response == tester.response:
                    return tester

        return None

    def _is_wildcard(self, response):
        """Check if response is similar to wildcard response"""

        # Compare 2 binary responses (Response.content is empty if the body is binary)
        if not self.response.content and not response.content:
            return self.response.body == response.body

        return self.content_parser.compare_to(response.content)

    @staticmethod
    def generate_redirect_regex(first_loc, first_path, second_loc, second_path):
        """
        From 2 redirects of wildcard responses, generate a regexp that matches
        every wildcard redirect.

        How it works:
        1. Replace path in 2 redirect URLs (if it gets reflected in) with a mark
           (e.g. /path1 -> /foo/path1 and /path2 -> /foo/path2 will become /foo/[mark] for both)
        2. Compare 2 redirects and generate a regex that matches both
           (e.g. /foo/[mark]?a=1 and /foo/[mark]?a=2 will have the regex: ^/foo/[mark]?a=(.*)$)
        3. Next time if it redirects, replace mark in regex with the path and check if it matches
           (e.g. /path3 -> /foo/path3?a=5, the regex becomes ^/foo/path3?a=(.*)$, which matches)
        """

        if first_path:
            first_loc = unquote(first_loc).replace(first_path, REFLECTED_PATH_MARKER)
        if second_path:
            second_loc = unquote(second_loc).replace(second_path, REFLECTED_PATH_MARKER)

        return generate_matching_regex(first_loc, second_loc)
