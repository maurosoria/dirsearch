#!/usr/bin/env python3
#
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

import unittest

from tests.connection.test_dns import TestDNS
from tests.parse.test_headers import TestHeadersParser
from tests.parse.test_url import TestURLParsers
from tests.reports.test_reports import TestReports
from tests.utils.test_common import TestCommonUtils
from tests.utils.test_diff import TestDiff
from tests.utils.test_mimetype import TestMimeTypeUtils
from tests.utils.test_random import TestRandom
from tests.utils.test_schemedet import TestSchemedet


if __name__ == "__main__":
    unittest.main()
