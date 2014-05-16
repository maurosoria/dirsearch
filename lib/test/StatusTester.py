# -*- coding: utf-8 -*-
from lib.connection import *


class StatusTester(object):

    def __init__(self):
        pass

    def test(self, response):
        return response.status != 404


