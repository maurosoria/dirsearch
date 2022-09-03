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

import json

from unittest import TestCase

from lib.connection.requester import Requester
from lib.core.settings import DUMMY_URL, DUMMY_WORD, NEW_LINE, TMP_PATH
from lib.reports.csv_report import CSVReport
from lib.reports.json_report import JSONReport
from lib.reports.markdown_report import MarkdownReport
from lib.reports.plain_text_report import PlainTextReport
from lib.reports.simple_report import SimpleReport
from lib.reports.xml_report import XMLReport

requester = Requester()
test_entries = [requester.request(DUMMY_URL + DUMMY_WORD)]


class TestReports(TestCase):
    def test_csv_report(self):
        expected_output = "URL,Status,Size,Content Type,Redirection" + NEW_LINE
        expected_output += f"{DUMMY_URL}{DUMMY_WORD},404,648,text/html," + NEW_LINE

        self.assertEqual(CSVReport(TMP_PATH).generate(test_entries), expected_output, "CSV report is unintended")

    def test_json_report(self):
        output = JSONReport(TMP_PATH).generate(test_entries)
        expected_results = [{
            "url": DUMMY_URL + DUMMY_WORD,
            "status": 404,
            "content-length": 648,
            "content-type": "text/html",
            "redirect": "",
        }]
        self.assertEqual(json.loads(output)["results"], expected_results, "JSON report is unintended")

    def test_markdown_report(self):
        expected_table = "URL | Status | Size | Content Type | Redirection" + NEW_LINE
        expected_table += "----|--------|------|--------------|------------" + NEW_LINE
        expected_table += f"{DUMMY_URL}{DUMMY_WORD} | 404 | 648 | text/html | " + NEW_LINE
        self.assertTrue(MarkdownReport(TMP_PATH).generate(test_entries).endswith(expected_table))

    def test_plain_text_report(self):
        expected_result = f"404   648B   {DUMMY_URL}{DUMMY_WORD}" + NEW_LINE
        self.assertTrue(PlainTextReport(TMP_PATH).generate(test_entries).endswith(expected_result))

    def test_simple_report(self):
        self.assertEqual(SimpleReport(TMP_PATH).generate(test_entries), DUMMY_URL + DUMMY_WORD)

    def test_xml_report(self):
        expected_result = f'\t<target url="{DUMMY_URL}{DUMMY_WORD}">\n'
        expected_result += "\t\t<status>404</status>\n"
        expected_result += "\t\t<contentLength>648</contentLength>\n"
        expected_result += "\t\t<contentType>text/html</contentType>\n"
        expected_result += "\t</target>"
        self.assertTrue(expected_result in XMLReport(TMP_PATH).generate(test_entries))
