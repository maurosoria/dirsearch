from difflib import SequenceMatcher
from lib.connection import *


DYNAMICITY_MARK_LENGTH = 32
UPPER_RATIO_BOUND = 0.98

class DynamicContentParser:

	def __init__(self, requester, path, comparisons = 2):
		self.requester = requester
		self.path = path
		self.comparisons = comparisons
		self.dynamicMarks = []
		self.seqMatcher = SequenceMatcher()

		response = requester.request(path)
		firstPage = response.body

		response = requester.request(path)
		secondPage = response.body

		self.generateDynamicMarks(firstPage, secondPage)


	def generateDynamicMarks(self, firstPage, secondPage):
	    if any(page is None for page in (firstPage, secondPage)):
	        # No content
	        return

	    
	    self.seqMatcher.set_seq1(firstPage)
	    self.seqMatcher.set_seq2(secondPage)

	    # In case of an intolerable difference turn on dynamicity removal engine
	    if self.seqMatcher.quick_ratio() <= UPPER_RATIO_BOUND:
	    	self.dynamicMarks += findDynamicContent(firstPage, secondPage)
	    	count = 0
	    	while count < self.comparisons:
	    		response = self.requester.request(path)
	    		secondPage = response.body
	    		self.dynamicMarks += findDynamicContent(firstPage, secondPage)
	    	
	    self.cleanPage = self.removeDynamicContent(firstPage, self.dynamicMarks)
	    self.seqMatcher.set_seq1(self.cleanPage)
	        	
	
	def compareTo(self, page):
		seqMatcher = SequenceMatcher()
		seqMatcher.set_seq1(self.cleanPage)
		seqMatcher.set_seq2(self.removeDynamicContent(page, self.dynamicMarks))
		return seqMatcher.quick_ratio() > UPPER_RATIO_BOUND


	@staticmethod
	def findDynamicContent(firstPage, secondPage):
		dynamicMarks = []

		blocks = SequenceMatcher(None, firstPage, secondPage)

		# Removing too small matching blocks
		for block in blocks[:]:
			(_, _, length) = block

			if length <= DYNAMICITY_MARK_LENGTH:
				blocks.remove(block)

		# Making of dynamic markings based on prefix/suffix principle
		if len(blocks) > 0:
			blocks.insert(0, None)
			blocks.append(None)

			for i in range(len(blocks) - 1):
				prefix = firstPage[blocks[i][0]:blocks[i][0] + blocks[i][2]] if blocks[i] else None
				suffix = firstPage[blocks[i + 1][0]:blocks[i + 1][0] + blocks[i + 1][2]] if blocks[i + 1] else None

				if prefix is None and blocks[i + 1][0] == 0:
					continue

				if suffix is None and (blocks[i][0] + blocks[i][2] >= len(firstPage)):
					continue




				dynamicMarks.append((re.escape(prefix[-DYNAMICITY_MARK_LENGTH / 2:]) if prefix else None, re.escape(suffix[:DYNAMICITY_MARK_LENGTH / 2]) if suffix else None))


		return dynamicMarks


	def removeDynamicContent(self, page, dynamicMarks):
	    """
	    Removing dynamic content from supplied page basing removal on
	    precalculated dynamic markings
	    """
	    if page:
	        for item in dynamicMarks:
	            prefix, suffix = item

	            if prefix is None and suffix is None:
	                continue
	            elif prefix is None:
	                page = re.sub(r'(?s)^.+%s' % suffix, suffix, page)
	            elif suffix is None:
	                page = re.sub(r'(?s)%s.+$' % prefix, prefix, page)
	            else:
	                page = re.sub(r'(?s)%s.+%s' % (prefix, suffix), '%s%s' % (prefix, suffix), page)

	    return page