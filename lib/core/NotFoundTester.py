from lib.connection import *
from thirdparty.sqlmap import *
from lib.test import *

class NotFoundTester:
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