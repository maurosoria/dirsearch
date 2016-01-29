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
    def __init__(self, requester, testPath=None, suffix=None):
        if testPath is None or testPath is "":
            self.testPath = RandomUtils.randString()
        else:
            self.testPath = testPath
        self.suffix = suffix if suffix is not None else ""
        self.requester = requester
        self.tester = None
        self.redirectRegExp = None
        self.invalidStatus = None
        self.dynamicParser = None
        self.ratio = 0.98
        self.redirectStatusCodes = [301, 302, 307]
        self.setup()

    def setup(self):
        firstPath = self.testPath + self.suffix
        firstResponse = self.requester.request(firstPath)
        self.invalidStatus = firstResponse.status
        if self.invalidStatus == 404:
            # Using the response status code is enough :-}
            return

        # look for redirects
        secondPath = RandomUtils.randString(omit=self.testPath) + self.suffix
        secondResponse = self.requester.request(secondPath)
        if firstResponse.status in self.redirectStatusCodes and firstResponse.redirect and secondResponse.redirect:
            self.redirectRegExp = self.generateRedirectRegExp(firstResponse.redirect, secondResponse.redirect)

        # Analyze response bodies
        self.dynamicParser = DynamicContentParser(self.requester, firstPath, firstResponse.body, secondResponse.body)
        baseRatio = float("{0:.2f}".format(self.dynamicParser.comparisonRatio))  # Rounding to 2 decimals
        # If response length is small, adjust ratio
        if len(firstResponse) < 2000:
            baseRatio -= 0.1
        if baseRatio < self.ratio:
            self.ratio = baseRatio

    def generateRedirectRegExp(self, firstLocation, secondLocation):
        if firstLocation is None or secondLocation is None:
            return None
        sm = SequenceMatcher(None, firstLocation, secondLocation)
        marks = []
        for blocks in sm.get_matching_blocks():
            i = blocks[0]
            n = blocks[2]
            # empty block
            if n == 0:
                continue
            mark = firstLocation[i:i + n]
            marks.append(mark)
        regexp = "^.*{0}.*$".format(".*".join(map(re.escape, marks)))
        return regexp

    def scan(self, path, response):
        if self.invalidStatus == 404 and response.status == 404:
            return False
        if self.invalidStatus != response.status:
            return True

        redirectToInvalid = False
        if self.redirectRegExp is not None  and response.redirect is not None:
            redirectToInvalid = re.match(self.redirectRegExp, response.redirect) is not None
            # If redirection doesn't match the rule, mark as found
            if not redirectToInvalid:
                return True

        ratio = self.dynamicParser.compareTo(response.body)
        if ratio >= self.ratio:
            return False
        elif redirectToInvalid and ratio >= (self.ratio - 0.15):
            return False
        return True
