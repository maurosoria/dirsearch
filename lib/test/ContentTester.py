# -*- coding: utf-8 -*-
from lib.connection import *
from thirdparty.sqlmap import *


class ContentTester(object):

    def __init__(self, dynamicContentParser):
        self.dynamicContentParser = dynamicContentParser

    def test(self, response):
        return not self.dynamicContentParser.compareTo(response.body)


