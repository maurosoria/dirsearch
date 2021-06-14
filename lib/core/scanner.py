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

from urllib.parse import unquote
from lib.utils import RandomUtils
from thirdparty.sqlmap import DynamicContentParser


class ScannerException(Exception):
    pass


class Scanner(object):
    def __init__(self, requester, calibration=None, suffix=None, prefix=None, tested=None):
        self.calibration = calibration
        self.suffix = suffix if suffix else ""
        self.prefix = prefix if prefix else ""
        self.tested = tested
        self.requester = requester
        self.tester = None
        self.redirect_reg_exp = None
        self.response = None
        self.dynamic_parser = None
        self.sign = None
        self.setup()

    def duplicate(self, response):
        if not self.tested:
            return
        for t in self.tested:
            for tester in self.tested[t].values():
                if [response.status, response.body, response.redirect] == [
                    tester.response.status, tester.response.body, tester.response.redirect
                ]:
                    return tester

        return

    """
    Generate wildcard response information containers, this will be
    used to compare with other path responses
    """
    def setup(self):
        first_path = self.prefix + (
            self.calibration if self.calibration else RandomUtils.rand_string()
        ) + self.suffix
        first_response = self.requester.request(first_path)
        self.response = first_response

        if self.response.status == 404:
            # Using the response status code is enough :-}
            return

        duplicate = self.duplicate(first_response)
        if duplicate:
            # Another test had been performed and shows the same response as this
            self.ratio = duplicate.ratio
            self.dynamic_parser = duplicate.dynamic_parser
            self.redirect_reg_exp = duplicate.redirect_reg_exp
            self.sign = duplicate.sign
            return

        second_path = self.prefix + (
            self.calibration if self.calibration else RandomUtils.rand_string(omit=first_path)
        ) + self.suffix
        second_response = self.requester.request(second_path)

        # Look for redirects
        if first_response.redirect and second_response.redirect:
            self.redirect_reg_exp = self.generate_redirect_reg_exp(
                first_response.redirect, first_path,
                second_response.redirect, second_path,
            )

        # Analyze response bodies
        if first_response.body is not None and second_response.body is not None:
            self.dynamic_parser = DynamicContentParser(
                self.requester, first_path, first_response.body, second_response.body
            )
        else:
            self.dynamic_parser = None

        self.ratio = float(
            "{0:.2f}".format(self.dynamic_parser.comparisonRatio)
        )  # Rounding to 2 decimals

        # The wildcard response is static
        if self.ratio == 1:
            pass
        # Adjusting ratio based on response length
        elif len(first_response) < 100:
            self.ratio -= 0.1
        elif len(first_response) < 500:
            self.ratio -= 0.05
        elif len(first_response) < 2000:
            self.ratio -= 0.02
        else:
            self.ratio -= 0.01
        """
        If the path is reflected in response, decrease the ratio. Because
        the difference between path lengths can reduce the similarity ratio
        """
        if first_path in first_response.body.decode():
            if len(first_response) < 200:
                self.ratio -= 0.15 + 15 / len(first_response)
            elif len(first_response) < 800:
                self.ratio -= 0.06 + 30 / len(first_response)
            elif len(first_response) < 5000:
                self.ratio -= 0.03 + 80 / len(first_response)
            elif len(first_response) < 20000:
                self.ratio -= 0.02 + 200 / len(first_response)
            else:
                self.ratio -= 0.01

    """
    From 2 redirects of wildcard responses, generate a regexp that matches
    every wildcard redirect
    """
    def generate_redirect_reg_exp(self, first_loc, first_path, second_loc, second_path):
        # Use a unique sign to locate where the path gets reflected in the redirect
        self.sign = RandomUtils.rand_string(n=20)
        first_loc = first_loc.replace(first_path, self.sign)
        second_loc = second_loc.replace(second_path, self.sign)
        reg_exp_start = "^"
        reg_exp_end = "$"

        for f, s in zip(first_loc, second_loc):
            if f == s:
                reg_exp_start += re.escape(f)
            else:
                reg_exp_start += ".*"
                break

        if reg_exp_start.endswith(".*"):
            for f, s in zip(first_loc[::-1], second_loc[::-1]):
                if f == s:
                    reg_exp_end = re.escape(f) + reg_exp_end
                else:
                    break

        return unquote(reg_exp_start + reg_exp_end)

    # Check if redirect matches the wildcard redirect regex or the response
    # has high similarity with wildcard tested at the start
    def scan(self, path, response):
        if self.response.status == response.status == 404:
            return False

        if self.response.status != response.status:
            return True

        if self.redirect_reg_exp and response.redirect:
            path = re.escape(unquote(path))
            # A lot of times, '#' or '?' will be removed in the redirect, cause false positives
            for char in ["\\#", "\\?"]:
                if char in path:
                    path = path.replace(char, "(|" + char) + ")"

            redirect_reg_exp = self.redirect_reg_exp.replace(self.sign, path)

            # Redirect sometimes encodes/decodes characters in URL, which may confuse the
            # rule check and make noise in the output, so we need to unquote() everything
            redirect_to_invalid = re.match(redirect_reg_exp, unquote(response.redirect))

            # If redirection doesn't match the rule, mark as found
            if redirect_to_invalid is None:
                return True

        # Compare 2 responses (wildcard one and given one)
        ratio = self.dynamic_parser.compareTo(response.body)

        # If the similarity ratio is high enough to proof it's wildcard
        if ratio >= self.ratio:
            return False
        elif "redirect_to_invalid" in locals() and ratio >= (self.ratio - 0.18):
            return False

        return True
