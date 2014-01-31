from lib.connection import *
from thirdparty.sqlmap import *

class ContentTester:
	def __init__(self, dynamicContentParser):
		self.dynamicContentParser = dynamicContentParser

	def test(self, response):
		return not self.dynamicContentParser.compareTo(response.body)


