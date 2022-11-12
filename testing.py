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

from tests.connection.test_dns import TestDNS  # noqa: F401
from tests.parse.test_config import TestConfigParser  # noqa: F401
from tests.parse.test_headers import TestHeadersParser  # noqa: F401
from tests.parse.test_url import TestURLParsers  # noqa: F401
from tests.reports.test_reports import TestReports  # noqa: F401
from tests.utils.test_common import TestCommonUtils  # noqa: F401
from tests.utils.test_crawl import TestCrawl  # noqa: F401
from tests.utils.test_diff import TestDiff  # noqa: F401
from tests.utils.test_mimetype import TestMimeTypeUtils  # noqa: F401
from tests.utils.test_random import TestRandom  # noqa: F401
from tests.utils.test_schemedet import TestSchemedet  # noqa: F401


if __name__ == "__main__":
    unittest.main()
