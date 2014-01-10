from lib.connection import *

class StatusTester:
	def __init__(self):
		pass

	def test(self, response):
		return response.status != 404


