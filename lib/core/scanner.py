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
    def __init__(self, requester, calibration=None, suffix=None, prefix=None):
        self.calibration = calibration
        self.suffix = suffix if suffix else ""
        self.prefix = prefix if prefix else ""
        self.requester = requester
        self.tester = None
        self.redirectRegExp = None
        self.invalidStatus = None
        self.dynamicParser = None
        self.sign = None
        self.ratio = 0.98
        self.setup()

    def setup(self):
        firstPath = self.prefix + (
            self.calibration if self.calibration else RandomUtils.randString()
        ) + self.suffix
        firstResponse = self.requester.request(firstPath)
        self.invalidStatus = firstResponse.status

        if self.invalidStatus == 404:
            # Using the response status code is enough :-}
            return

        secondPath = self.prefix + (
            self.calibration if self.calibration else RandomUtils.randString(omit=firstPath)
        ) + self.suffix
        secondResponse = self.requester.request(secondPath)

        # Look for redirects
        if firstResponse.redirect and secondResponse.redirect:
            self.redirectRegExp = self.generateRedirectRegExp(
                firstResponse.redirect, firstPath,
                secondResponse.redirect, secondPath,
            )

        # Analyze response bodies
        if firstResponse.body is not None and secondResponse.body is not None:
            self.dynamicParser = DynamicContentParser(
                self.requester, firstPath, firstResponse.body, secondResponse.body
            )
        else:
            self.dynamicParser = None

        baseRatio = float(
            "{0:.2f}".format(self.dynamicParser.comparisonRatio)
        )  # Rounding to 2 decimals

        # If response length is small, adjust ratio
        if len(firstResponse) < 2000:
            baseRatio -= 0.1

        if baseRatio < self.ratio:
            self.ratio = baseRatio

    def generateRedirectRegExp(self, firstLoc, firstPath, secondLoc, secondPath):
        # Use a unique sign to locate where the path gets reflected in the redirect
        self.sign = RandomUtils.randString(n=20)
        firstLoc = firstLoc.replace(firstPath, self.sign)
        secondLoc = secondLoc.replace(secondPath, self.sign)
        regExpStart = "^"
        regExpEnd = "$"

        for f, s in zip(firstLoc, secondLoc):
            if f == s:
                regExpStart += re.escape(f)
            else:
                regExpStart += ".*"
                break

        if regExpStart.endswith(".*"):
            for f, s in zip(firstLoc[::-1], secondLoc[::-1]):
                if f == s:
                    regExpEnd = re.escape(f) + regExpEnd
                else:
                    break

        return unquote(regExpStart + regExpEnd)

    def scan(self, path, response):
        if self.invalidStatus == response.status == 404:
            return False

        if self.invalidStatus != response.status:
            return True

        if self.redirectRegExp and response.redirect:
            path = re.escape(unquote(path))
            # A lot of times, '#' or '?' will be removed in the redirect, cause false positives
            for char in ["\\#", "\\?"]:
                if char in path:
                    path = path.replace(char, "(|" + char) + ")"

            redirectRegExp = self.redirectRegExp.replace(self.sign, path)

            # Redirect sometimes encodes/decodes characters in URL, which may confuse the
            # rule check and make noise in the output, so we need to unquote() everything
            redirectToInvalid = re.match(redirectRegExp, unquote(response.redirect))

            # If redirection doesn't match the rule, mark as found
            if redirectToInvalid is None:
                return True

        ratio = self.dynamicParser.compareTo(response.body)

        if ratio >= self.ratio:
            return False

        elif "redirectToInvalid" in locals() and ratio >= (self.ratio - 0.15):
            return False

        return True
