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


from lib.connection import *
from thirdparty.sqlmap import *
from lib.test import *


class NotFoundTester(object):

    def __init__(self, requester, notFoundPath):
        self.requester = requester
        self.notFoundPath = notFoundPath
        self.tester = None
        if self.testNotFoundStatus():
            self.tester = StatusTester()
        else:
            self.tester = ContentTester(self.getNotFoundDynamicContentParser())

    def testNotFoundStatus(self):
        response = self.requester.request(self.notFoundPath)
        return response.status == 404

    def getNotFoundDynamicContentParser(self):
        return DynamicContentParser(self.requester, self.notFoundPath)

    def test(self, response):
        return self.tester.test(response)


