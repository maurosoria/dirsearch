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

import re
from difflib import SequenceMatcher

from lib.utils import RandomUtils
from thirdparty.sqlmap import DynamicContentParser


class ScannerException(Exception):
    pass


class Scanner(object):
    def __init__(self, requester, test_path=None, suffix=None):
        if test_path is None or test_path is "":
            self.test_path = RandomUtils.rand_string()
        else:
            self.test_path = test_path

        self.suffix = suffix if suffix is not None else ""
        self.requester = requester
        self.tester = None
        self.redirect_reg_exp = None
        self.invalid_status = None
        self.dynamic_parser = None
        self.ratio = 0.98
        self.redirect_status_codes = [301, 302, 307]
        self.setup()

    def setup(self):
        first_path = self.test_path + self.suffix
        first_response = self.requester.request(first_path)
        self.invalid_status = first_response.status

        if self.invalid_status == 404:
            # Using the response status code is enough :-}
            return

        # look for redirects
        secondPath = RandomUtils.rand_string(omit=self.test_path) + self.suffix
        secondResponse = self.requester.request(secondPath)

        if first_response.status in self.redirect_status_codes and first_response.redirect and secondResponse.redirect:
            self.redirect_reg_exp = self.generate_redirect_reg_exp(first_response.redirect, secondResponse.redirect)

        # Analyze response bodies
        self.dynamic_parser = DynamicContentParser(self.requester, first_path, first_response.body, secondResponse.body)

        baseRatio = float("{0:.2f}".format(self.dynamic_parser.comparisonRatio))  # Rounding to 2 decimals

        # If response length is small, adjust ratio
        if len(first_response) < 2000:
            baseRatio -= 0.1

        if baseRatio < self.ratio:
            self.ratio = baseRatio

    def generate_redirect_reg_exp(self, first_location, second_location):
        if first_location is None or second_location is None:
            return None

        sm = SequenceMatcher(None, first_location, second_location)
        marks = []

        for blocks in sm.get_matching_blocks():
            i = blocks[0]
            n = blocks[2]
            # empty block

            if n == 0:
                continue

            mark = first_location[i:i + n]
            marks.append(mark)

        regexp = "^.*{0}.*$".format(".*".join(map(re.escape, marks)))
        return regexp

    def scan(self, path, response):
        if self.invalid_status == 404 and response.status == 404:
            return False

        if self.invalid_status != response.status:
            return True

        redirect_to_invalid = False

        if self.redirect_reg_exp is not None and response.redirect is not None:
            redirect_to_invalid = re.match(self.redirect_reg_exp, response.redirect) is not None
            # If redirection doesn't match the rule, mark as found

            if not redirect_to_invalid:
                return True

        ratio = self.dynamic_parser.compareTo(response.body)

        if ratio >= self.ratio:
            return False

        elif redirect_to_invalid and ratio >= (self.ratio - 0.15):
            return False

        return True
