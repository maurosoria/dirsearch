from unittest import TestCase

from lib.parse.nmap import parse_nmap


class TestNmapParser(TestCase):
    def test_parse_nmap(self):
        self.assertEqual(parse_nmap("./tests/static/nmap.xml"), ["scanme.nmap.org:80"], "Nmap parser gives unexpected result")
